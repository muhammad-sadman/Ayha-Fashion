import csv
import io
import json
import re
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import services
from .models import (
    Category, HeroSlide, Order, OrderItem, Product, ProductImage, PromoCode, SiteSettings, SubCategory,
)

PLAIN_STATIC = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(
    STORAGES=PLAIN_STATIC, NOTIFY_ASYNC=False, ORDER_RATE_LIMIT=(100, 10), GOOGLE_SHEET_WEBHOOK_URL="",
    ORDER_ALERT_EMAIL="", WA_TOKEN="", MEDIA_ROOT="/tmp/ayha-test-media",
)
class ShopTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.site = SiteSettings.load()
        self.site.whatsapp_number = "8801712345678"
        self.site.bkash_number = "01711111111"
        self.site.save()
        self.cat = Category.objects.create(name="Cotton Collection", slug="cotton", order=1)
        self.sub = SubCategory.objects.create(category=self.cat, name="Saree")
        self.p1 = Product.objects.create(category=self.cat, subcategory=self.sub, name="Blue Saree", sku="AY101", price=1500, old_price=1850)
        self.p2 = Product.objects.create(category=self.cat, name="Green Kurti", sku="AY102", price=900)
        self.client = Client()

    def post_json(self, url, data, client=None, **extra):
        return (client or self.client).post(url, json.dumps(data), content_type="application/json", **extra)

    def order_payload(self, **over):
        data = {
            "client_ref": "ref-0000-aaaa", "name": "Rima Akter", "phone": "01812345678", "address": "House 5, Dhanmondi, Dhaka",
            "area": "dhaka", "payment": "cod", "items": [{"id": self.p1.id, "qty": 2}],
        }
        data.update(over)
        return data


class CatalogApiTests(ShopTestCase):
    def test_home_page_renders(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "shop/js/app.js")
        self.assertIn("csrftoken", r.cookies)

    def test_store_api_shape(self):
        HeroSlide.objects.create(heading="Hello", hue=150)
        d = self.client.get("/api/store/").json()
        self.assertEqual({c["id"] for c in d["categories"]}, {"cotton"})
        self.assertEqual(d["categories"][0]["subs"], ["Saree"])
        self.assertEqual(len(d["products"]), 2)
        prod = next(p for p in d["products"] if p["id"] == self.p1.id)
        self.assertEqual((prod["price"], prod["old"], prod["cat"], prod["sub"], prod["inStock"]), (1500, 1850, "cotton", "Saree", True))
        self.assertEqual(d["config"]["shipping"]["dhaka"]["fee"], 70)
        self.assertEqual(d["config"]["bkash"]["number"], "01711111111")
        self.assertEqual(len(d["config"]["slides"]), 1)
        self.assertNotIn("sheet", json.dumps(d).lower())

    def test_hidden_products_and_categories_are_not_public(self):
        self.p2.is_active = False
        self.p2.save()
        hidden = Category.objects.create(name="Secret", slug="secret", is_active=False)
        Product.objects.create(category=hidden, name="Hidden item", price=500)
        d = self.client.get("/api/store/").json()
        self.assertEqual([p["id"] for p in d["products"]], [self.p1.id])
        self.assertEqual([c["id"] for c in d["categories"]], ["cotton"])

    def test_sold_out_flag(self):
        self.p1.in_stock = False
        self.p1.save()
        d = self.client.get("/api/store/").json()
        self.assertFalse(next(p for p in d["products"] if p["id"] == self.p1.id)["inStock"])


class OrderApiTests(ShopTestCase):
    def test_cod_order_prices_come_from_the_server(self):
        payload = self.order_payload()
        payload["items"][0]["price"] = 1  # a tampered price must be ignored
        payload["total"] = 1
        r = self.post_json("/api/orders/", payload)
        self.assertEqual(r.status_code, 200, r.content)
        o = r.json()["order"]
        self.assertTrue(re.match(r"^AY-\d{6}-[A-Z0-9]{4}$", o["no"]))
        self.assertEqual((o["subtotal"], o["shipping"], o["total"]), (3000, 70, 3070))
        order = Order.objects.get()
        self.assertEqual((order.total, order.payment_method, order.status), (3070, "cod", "new"))
        item = order.items.get()
        self.assertEqual((item.unit_price, item.quantity, item.line_total, item.name), (1500, 2, 3000, "Blue Saree"))

    def test_outside_dhaka_fee_and_phone_normalised(self):
        r = self.post_json("/api/orders/", self.order_payload(area="out", phone="+8801812345678"))
        self.assertEqual(r.json()["order"]["shipping"], 130)
        self.assertEqual(Order.objects.get().phone, "01812345678")

    def test_whatsapp_url_goes_to_business_number(self):
        o = self.post_json("/api/orders/", self.order_payload()).json()["order"]
        self.assertTrue(o["whatsapp_url"].startswith("https://wa.me/8801712345678?text="))
        self.assertIn(o["no"], o["whatsapp_url"])

    def test_whatsapp_url_empty_when_number_not_set(self):
        self.site.whatsapp_number = ""
        self.site.save()
        o = self.post_json("/api/orders/", self.order_payload()).json()["order"]
        self.assertEqual(o["whatsapp_url"], "")

    def test_validation_errors(self):
        bad = [
            ({"name": ""}, "name"), ({"phone": "12345"}, "mobile"), ({"address": ""}, "address"),
            ({"area": "mars"}, "area"), ({"payment": "cash"}, "payment"), ({"email": "nope"}, "email"),
            ({"items": []}, "cart"), ({"items": [{"id": 1, "qty": 0}]}, "least 1"),
            ({"items": [{"id": self.p1.id, "qty": 21}]}, "up to 20"), ({"items": [{"id": 99999, "qty": 1}]}, "no longer available"),
            ({"items": "x"}, "cart"), ({"items": [{"id": 1, "qty": float("inf")}]}, "cart"),
            ({"items": [{"id": 2**40, "qty": 1}]}, "cart"),
        ]
        for i, (over, word) in enumerate(bad):
            r = self.post_json("/api/orders/", self.order_payload(client_ref="ref-bad-%04d" % i, **over))
            self.assertEqual(r.status_code, 400, (over, r.content))
            self.assertIn(word.lower(), r.json()["error"].lower(), over)
        self.assertEqual(Order.objects.count(), 0)

    def test_non_json_and_wrong_method(self):
        self.assertEqual(self.client.post("/api/orders/", "not json", content_type="application/json").status_code, 400)
        self.assertEqual(self.post_json("/api/orders/", [1, 2]).status_code, 400)
        self.assertEqual(self.client.get("/api/orders/").status_code, 405)

    def test_same_client_ref_is_saved_once(self):
        a = self.post_json("/api/orders/", self.order_payload()).json()["order"]["no"]
        b = self.post_json("/api/orders/", self.order_payload()).json()["order"]["no"]
        self.assertEqual(a, b)
        self.assertEqual(Order.objects.count(), 1)

    def test_sold_out_item_rejected(self):
        self.p1.in_stock = False
        self.p1.save()
        r = self.post_json("/api/orders/", self.order_payload())
        self.assertEqual(r.status_code, 400)
        self.assertIn("out of stock", r.json()["error"])

    def test_hidden_product_rejected(self):
        self.p1.is_active = False
        self.p1.save()
        self.assertEqual(self.post_json("/api/orders/", self.order_payload()).status_code, 400)

    def test_duplicate_lines_are_merged(self):
        r = self.post_json("/api/orders/", self.order_payload(items=[{"id": self.p1.id, "qty": 1}, {"id": self.p1.id, "qty": 2}]))
        self.assertEqual(r.json()["order"]["subtotal"], 4500)
        self.assertEqual(OrderItem.objects.count(), 1)

    def test_honeypot_saves_nothing(self):
        r = self.post_json("/api/orders/", self.order_payload(hp="I am a bot"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Order.objects.count(), 0)

    def test_csrf_is_enforced(self):
        c = Client(enforce_csrf_checks=True)
        self.assertEqual(self.post_json("/api/orders/", self.order_payload(), client=c).status_code, 403)
        c.get("/")
        token = c.cookies["csrftoken"].value
        r = self.post_json("/api/orders/", self.order_payload(), client=c, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(r.status_code, 200)

    @override_settings(ORDER_RATE_LIMIT=(2, 10))
    def test_rate_limit(self):
        for i in range(2):
            self.assertEqual(self.post_json("/api/orders/", self.order_payload(client_ref="rate-ref-%04d" % i)).status_code, 200)
        r = self.post_json("/api/orders/", self.order_payload(client_ref="rate-ref-9999"))
        self.assertEqual(r.status_code, 429)
        self.assertEqual(Order.objects.count(), 2)

    @override_settings(BEHIND_PROXY=True)
    def test_forged_forwarded_for_cannot_dodge_rate_limit(self):
        rf = RequestFactory()
        req = rf.get("/", HTTP_X_FORWARDED_FOR="1.1.1.1, 203.0.113.9", REMOTE_ADDR="127.0.0.1")
        self.assertEqual(services.get_client_ip(req), "203.0.113.9")  # the address nginx saw, not the forged one


class BkashTests(ShopTestCase):
    def bk(self, **over):
        return self.order_payload(**{"payment": "bkash", "bkash_number": "01911111111", "trx": "8n7a6d5e4c", **over})

    def test_bkash_order_saved_unverified(self):
        r = self.post_json("/api/orders/", self.bk())
        self.assertEqual(r.status_code, 200, r.content)
        o = Order.objects.get()
        self.assertEqual((o.payment_method, o.bkash_trx_id, o.bkash_number, o.payment_verified), ("bkash", "8N7A6D5E4C", "01911111111", False))
        self.assertEqual(r.json()["order"]["payment"], "bKash")

    def test_bkash_requires_valid_details(self):
        for over in ({"trx": ""}, {"trx": "short"}, {"trx": "has space 12"}, {"bkash_number": "123"}):
            r = self.post_json("/api/orders/", self.bk(**over))
            self.assertEqual(r.status_code, 400, over)
        self.assertEqual(Order.objects.count(), 0)

    def test_trxid_cannot_be_reused(self):
        self.assertEqual(self.post_json("/api/orders/", self.bk()).status_code, 200)
        r = self.post_json("/api/orders/", self.bk(client_ref="another-ref-0001"))
        self.assertEqual(r.status_code, 400)
        self.assertIn("already been used", r.json()["error"])
        self.assertEqual(Order.objects.count(), 1)

    def test_bkash_blocked_when_number_not_configured(self):
        self.site.bkash_number = ""
        self.site.save()
        r = self.post_json("/api/orders/", self.bk())
        self.assertEqual(r.status_code, 400)
        self.assertIn("not available", r.json()["error"])

    def test_two_cod_orders_do_not_collide_on_empty_trx(self):
        self.post_json("/api/orders/", self.order_payload(client_ref="cod-ref-000001"))
        self.post_json("/api/orders/", self.order_payload(client_ref="cod-ref-000002"))
        self.assertEqual(Order.objects.count(), 2)


class PromoTests(ShopTestCase):
    def test_promo_check_endpoint(self):
        PromoCode.objects.create(code="welcome100", amount=100)
        ok = self.post_json("/api/promo/", {"code": " welcome100 "}).json()
        self.assertEqual((ok["ok"], ok["code"], ok["amount"]), (True, "WELCOME100", 100))
        self.assertFalse(self.post_json("/api/promo/", {"code": "NOPE"}).json()["ok"])

    def test_promo_discount_applied_and_counted(self):
        PromoCode.objects.create(code="EID200", amount=200)
        o = self.post_json("/api/orders/", self.order_payload(promo="eid200")).json()["order"]
        self.assertEqual((o["discount"], o["total"]), (200, 2870))
        self.assertEqual(PromoCode.objects.get().times_used, 1)

    def test_discount_never_exceeds_subtotal(self):
        PromoCode.objects.create(code="HUGE", amount=999999)
        o = self.post_json("/api/orders/", self.order_payload(promo="HUGE", items=[{"id": self.p2.id, "qty": 1}])).json()["order"]
        self.assertEqual((o["discount"], o["total"]), (900, 70))

    def test_bad_expired_and_used_up_promos_rejected(self):
        PromoCode.objects.create(code="OLD", amount=50, expires_at=timezone.now() - timedelta(days=1))
        PromoCode.objects.create(code="OFF", amount=50, is_active=False)
        PromoCode.objects.create(code="ONCE", amount=50, max_uses=1, times_used=1)
        for code in ("OLD", "OFF", "ONCE", "MISSING"):
            r = self.post_json("/api/orders/", self.order_payload(promo=code, client_ref="promo-" + code + "-0000"))
            self.assertEqual(r.status_code, 400, code)
        self.assertEqual(Order.objects.count(), 0)

    def test_promo_endpoint_is_throttled(self):
        for _ in range(30):
            self.post_json("/api/promo/", {"code": "x"})
        self.assertEqual(self.post_json("/api/promo/", {"code": "x"}).status_code, 429)


class NotificationTests(ShopTestCase):
    def test_sheet_payload_matches_apps_script_rules(self):
        self.post_json("/api/orders/", self.order_payload(note="=cmd"))
        pl = services.sheet_payload(Order.objects.prefetch_related("items").get())
        self.assertRegex(pl["no"], r"^AY-[0-9]{6}-[A-Z0-9]{4}$")
        self.assertRegex(pl["phone"], r"^01[3-9][0-9]{8}$")
        self.assertIn(pl["payment"], ("Cash on Delivery", "bKash"))
        self.assertGreater(pl["total"], 0)
        self.assertIn("Blue Saree x2", pl["items"])

    @override_settings(GOOGLE_SHEET_WEBHOOK_URL="https://script.google.com/macros/s/TEST/exec")
    def test_sheet_push_marks_order_synced(self):
        fake = mock.MagicMock()
        fake.__enter__.return_value.read.return_value = b'{"ok":true}'
        with mock.patch("shop.services.urllib.request.urlopen", return_value=fake) as uo:
            with self.captureOnCommitCallbacks(execute=True):
                self.post_json("/api/orders/", self.order_payload())
        req = uo.call_args[0][0]
        self.assertEqual(json.loads(req.data)["name"], "Rima Akter")
        self.assertTrue(Order.objects.get().sheet_synced)

    @override_settings(GOOGLE_SHEET_WEBHOOK_URL="https://script.google.com/macros/s/TEST/exec")
    def test_sheet_failure_never_breaks_the_order(self):
        with mock.patch("shop.services.urllib.request.urlopen", side_effect=OSError("offline")):
            with self.captureOnCommitCallbacks(execute=True):
                r = self.post_json("/api/orders/", self.order_payload())
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Order.objects.get().sheet_synced)

    @override_settings(ORDER_ALERT_EMAIL="owner@example.com")
    def test_owner_email_sent(self):
        with self.captureOnCommitCallbacks(execute=True):
            self.post_json("/api/orders/", self.order_payload())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["owner@example.com"])
        self.assertIn("Rima Akter", mail.outbox[0].body)

    def test_sync_sheet_command_retries_pending(self):
        self.post_json("/api/orders/", self.order_payload())
        with mock.patch("shop.management.commands.sync_sheet.push_to_sheet", return_value=True) as m:
            call_command("sync_sheet", stdout=io.StringIO())
        self.assertEqual(m.call_count, 1)


class ModelTests(ShopTestCase):
    def test_product_validation(self):
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError):
            Product(category=self.cat, name="x", price=500, old_price=400).full_clean()
        other = Category.objects.create(name="Other", slug="other")
        osub = SubCategory.objects.create(category=other, name="Z")
        with self.assertRaises(ValidationError):
            Product(category=self.cat, subcategory=osub, name="x", price=500).full_clean()

    def test_promo_code_saved_uppercase(self):
        self.assertEqual(PromoCode.objects.create(code=" abc ", amount=10).code, "ABC")

    def test_site_settings_is_a_singleton(self):
        from django.db import IntegrityError, transaction

        with self.assertRaises(IntegrityError), transaction.atomic():
            SiteSettings.objects.create(brand_name="Second")  # a second row is refused
        SiteSettings(brand_name="Edited").save()  # saving always updates the one row
        self.assertEqual((SiteSettings.objects.count(), SiteSettings.load().brand_name), (1, "Edited"))

    def test_big_upload_is_downsized(self):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (3000, 2000), (200, 30, 30)).save(buf, "JPEG", quality=95)
        up = SimpleUploadedFile("big.jpg", buf.getvalue(), content_type="image/jpeg")
        pi = ProductImage.objects.create(product=self.p1, image=up)
        with Image.open(pi.image.path) as im:
            self.assertEqual(max(im.size), 1600)

    def test_small_upload_is_untouched_and_bad_file_does_not_crash(self):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (400, 300), (10, 120, 10)).save(buf, "JPEG")
        raw = buf.getvalue()
        pi = ProductImage.objects.create(product=self.p1, image=SimpleUploadedFile("s.jpg", raw, content_type="image/jpeg"))
        with open(pi.image.path, "rb") as f:
            self.assertEqual(f.read(), raw)


class AdminTests(ShopTestCase):
    def setUp(self):
        super().setUp()
        User = get_user_model()
        self.admin_user = User.objects.create_superuser("boss", "b@example.com", "a-long-password-1")
        self.client.force_login(self.admin_user)
        self.post_json("/api/orders/", self.order_payload(client_ref="admin-ref-0001"))
        self.order = Order.objects.get()

    def test_login_required(self):
        r = Client().get(reverse("admin:shop_order_changelist"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("login", r.url)

    def test_every_admin_page_loads(self):
        for name in ("order", "product", "category", "promocode", "heroslide"):
            r = self.client.get(reverse("admin:shop_%s_changelist" % name))
            self.assertEqual(r.status_code, 200, name)
        self.assertEqual(self.client.get(reverse("admin:shop_product_add")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:shop_order_change", args=[self.order.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:shop_product_change", args=[self.p1.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:shop_category_change", args=[self.cat.pk])).status_code, 200)

    def test_settings_page_redirects_to_the_single_row(self):
        r = self.client.get(reverse("admin:shop_sitesettings_changelist"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.get(r.url).status_code, 200)

    def test_orders_cannot_be_added_by_hand(self):
        self.assertEqual(self.client.get(reverse("admin:shop_order_add")).status_code, 403)

    def test_order_list_shows_sales_summary(self):
        r = self.client.get(reverse("admin:shop_order_changelist"))
        self.assertContains(r, "TODAY")
        self.assertEqual(r.context["stats"]["today"]["orders"], 1)

    def test_status_action_and_bkash_verify(self):
        url = reverse("admin:shop_order_changelist")
        self.client.post(url, {"action": "mark_shipped", "_selected_action": [self.order.pk]})
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "shipped")
        self.post_json("/api/orders/", {**self.order_payload(client_ref="admin-ref-0002"), "payment": "bkash", "bkash_number": "01911111111", "trx": "ABCDEFGH12"})
        bk = Order.objects.get(payment_method="bkash")
        self.client.post(url, {"action": "verify_bkash", "_selected_action": [bk.pk]})
        bk.refresh_from_db()
        self.assertTrue(bk.payment_verified)

    def test_slip_and_csv_export(self):
        r = self.client.get(reverse("admin:shop_order_slip", args=[self.order.pk]))
        self.assertContains(r, self.order.order_no)
        self.assertContains(r, "COLLECT FROM CUSTOMER")
        r = self.client.post(reverse("admin:shop_order_changelist"), {"action": "export_csv", "_selected_action": [self.order.pk]})
        rows = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))
        self.assertEqual(rows[1][0], self.order.order_no)
        self.assertIn("Blue Saree x2", rows[1][8])

    def test_slip_requires_login(self):
        r = Client().get(reverse("admin:shop_order_slip", args=[self.order.pk]))
        self.assertEqual(r.status_code, 302)

    def test_seed_demo_is_safe_to_run_twice(self):
        Product.objects.all().delete()
        Category.objects.all().delete()
        call_command("seed_demo", stdout=io.StringIO())
        n = Product.objects.count()
        call_command("seed_demo", stdout=io.StringIO())
        self.assertEqual(Product.objects.count(), n)
        self.assertEqual(n, 16)
        self.assertEqual(HeroSlide.objects.count(), 3)

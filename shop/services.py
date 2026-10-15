"""Order pricing, creation and notifications. All money is calculated here on the server,
so a customer can never change a price by editing the web page."""
import ipaddress
import json
import logging
import re
import secrets
import string
import threading
import urllib.request
from datetime import timedelta
from urllib.parse import quote

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import IntegrityError, close_old_connections, transaction
from django.db.models import F
from django.utils import timezone

from .models import Order, OrderItem, Product, PromoCode, SiteSettings

log = logging.getLogger("shop")

PHONE_RE = re.compile(r"^01[3-9]\d{8}$")
TRX_RE = re.compile(r"^[A-Z0-9]{8,12}$")
REF_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")
AREA_LABELS = dict(Order.AREA)
TRX_USED = "This bKash TrxID has already been used for another order. Check the ID on your bKash receipt, or call us."


class OrderError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def taka(n):
    return "৳{:,}".format(int(n))


def normalize_phone(value):
    value = re.sub(r"[\s-]", "", str(value or ""))
    return re.sub(r"^\+?88", "", value)


def get_client_ip(request):
    ip = request.META.get("REMOTE_ADDR")
    if settings.BEHIND_PROXY:
        # nginx appends the address it actually saw as the LAST entry. Earlier entries are
        # written by the visitor and can be forged, so they must not be trusted.
        forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[-1].strip()
        if forwarded:
            ip = forwarded
    try:
        return str(ipaddress.ip_address(ip))
    except (ValueError, TypeError):
        return None


# ---------------- promo ----------------

def find_usable_promo(code, lock=False):
    code = str(code or "").strip().upper()
    if not code:
        return None
    qs = PromoCode.objects.select_for_update() if lock else PromoCode.objects
    promo = qs.filter(code=code).first()
    return promo if promo and promo.is_usable() else None


# ---------------- pricing ----------------

def price_cart(raw_items, area, promo_code="", lock_promo=False):
    if not isinstance(raw_items, list) or not raw_items:
        raise OrderError("Your cart is empty.")
    if len(raw_items) > settings.MAX_ITEMS_PER_ORDER:
        raise OrderError("Too many items in one order. Please split it into two orders.")

    qtys = {}
    for item in raw_items:
        try:
            pid, qty = int(item["id"]), int(item["qty"])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise OrderError("Something is wrong with your cart. Please refresh and try again.")
        if not 0 < pid < 2**31:
            raise OrderError("Something is wrong with your cart. Please refresh and try again.")
        if qty < 1:
            raise OrderError("Quantity must be at least 1.")
        qtys[pid] = qtys.get(pid, 0) + qty
        if qtys[pid] > settings.MAX_QTY_PER_ITEM:
            raise OrderError("You can order up to %d of the same item. Please call us for larger orders." % settings.MAX_QTY_PER_ITEM)

    products = {p.id: p for p in Product.objects.filter(id__in=qtys.keys(), is_active=True, category__is_active=True)}
    lines = []
    for pid, qty in qtys.items():
        product = products.get(pid)
        if not product:
            raise OrderError("An item in your cart is no longer available. Please remove it and try again.")
        if not product.in_stock:
            raise OrderError("%s is out of stock. Please remove it from your cart." % product.name)
        lines.append((product, qty, product.price * qty))

    subtotal = sum(line[2] for line in lines)
    site = SiteSettings.load()
    shipping = site.shipping_dhaka_fee if area == "dhaka" else site.shipping_out_fee

    promo, discount = None, 0
    if promo_code:
        promo = find_usable_promo(promo_code, lock=lock_promo)
        if not promo:
            raise OrderError("That promo code is not valid. Remove it or check the spelling.")
        discount = min(promo.amount, subtotal)

    return {
        "lines": lines, "subtotal": subtotal, "shipping": shipping, "discount": discount,
        "promo": promo, "total": subtotal + shipping - discount,
    }


# ---------------- creating the order ----------------

def _new_order_no():
    alphabet = string.ascii_uppercase + string.digits
    for _ in range(20):
        no = "AY-%s-%s" % (timezone.localdate().strftime("%y%m%d"), "".join(secrets.choice(alphabet) for _ in range(4)))
        if not Order.objects.filter(order_no=no).exists():
            return no
    raise OrderError("Could not create an order number. Please try again.", 500)


def clean_order_input(data):
    name = str(data.get("name", "")).strip()
    address = str(data.get("address", "")).strip()
    phone = normalize_phone(data.get("phone"))
    email = str(data.get("email", "")).strip()
    note = str(data.get("note", "")).strip()
    area = str(data.get("area", ""))
    payment = str(data.get("payment", ""))

    if not name or len(name) > 120:
        raise OrderError("Please enter your name.")
    if not PHONE_RE.match(phone):
        raise OrderError("Please enter a valid Bangladeshi mobile number, like 01712345678.")
    if not address or len(address) > 600:
        raise OrderError("Please enter your full delivery address.")
    if email:
        try:
            validate_email(email)
        except ValidationError:
            raise OrderError("That email address does not look right. Leave it empty if you do not want to add one.")
    if len(note) > 1000:
        raise OrderError("Your note is too long.")
    if area not in AREA_LABELS:
        raise OrderError("Please choose a shipping area.")
    if payment not in ("cod", "bkash"):
        raise OrderError("Please choose a payment method.")

    bkash_number, trx = "", ""
    if payment == "bkash":
        bkash_number = normalize_phone(data.get("bkash_number"))
        trx = str(data.get("trx", "")).strip().upper()
        if not PHONE_RE.match(bkash_number) or not TRX_RE.match(trx):
            raise OrderError("Enter the bKash number you paid from and the TrxID from your receipt (letters and numbers only).")

    ref = str(data.get("client_ref") or "")
    return {
        "name": name, "phone": phone, "address": address, "email": email, "note": note, "area": area,
        "payment": payment, "bkash_number": bkash_number, "trx": trx, "ref": ref if REF_RE.match(ref) else None,
        "promo": str(data.get("promo") or "").strip().upper()[:30], "items": data.get("items"),
    }


def create_order(data, ip=None):
    """Returns (order, created). A repeated client_ref returns the original order (safe retries)."""
    d = clean_order_input(data)

    if d["ref"]:
        existing = Order.objects.filter(client_ref=d["ref"]).first()
        if existing:
            return existing, False

    if d["payment"] == "bkash":
        if not SiteSettings.load().bkash_number:
            raise OrderError("bKash payment is not available right now. Please choose Cash on Delivery.")
        if Order.objects.filter(bkash_trx_id=d["trx"]).exists():
            raise OrderError(TRX_USED)

    try:
        with transaction.atomic():
            priced = price_cart(d["items"], d["area"], d["promo"], lock_promo=True)
            order = Order.objects.create(
                order_no=_new_order_no(), client_ref=d["ref"], customer_name=d["name"], phone=d["phone"],
                email=d["email"], address=d["address"], area=d["area"], note=d["note"],
                payment_method=d["payment"], bkash_number=d["bkash_number"], bkash_trx_id=d["trx"],
                subtotal=priced["subtotal"], shipping_fee=priced["shipping"], discount=priced["discount"],
                promo_code=priced["promo"].code if priced["promo"] else "", total=priced["total"], ip_address=ip,
            )
            OrderItem.objects.bulk_create([
                OrderItem(order=order, product=p, name=p.name, sku=p.sku, unit_price=p.price, quantity=q, line_total=lt)
                for p, q, lt in priced["lines"]
            ])
            if priced["promo"]:
                PromoCode.objects.filter(pk=priced["promo"].pk).update(times_used=F("times_used") + 1)
            transaction.on_commit(lambda: notify(order.pk))
    except IntegrityError:
        existing = Order.objects.filter(client_ref=d["ref"]).first() if d["ref"] else None
        if existing:
            return existing, False
        if d["trx"] and Order.objects.filter(bkash_trx_id=d["trx"]).exists():
            raise OrderError(TRX_USED)
        raise
    return order, True


def is_rate_limited(ip):
    if not ip:
        return False
    count, minutes = settings.ORDER_RATE_LIMIT
    since = timezone.now() - timedelta(minutes=minutes)
    return Order.objects.filter(ip_address=ip, created_at__gte=since).count() >= count


# ---------------- messages ----------------

def order_lines(order):
    return ["%s x%d (%s)" % (i.name, i.quantity, taka(i.line_total)) for i in order.items.all()]


def whatsapp_text(order):
    lines = [
        "New order %s" % order.order_no, "",
        "Name: %s" % order.customer_name, "Phone: %s" % order.phone, "Address: %s" % order.address,
        "Area: %s" % AREA_LABELS[order.area], "", "Items:",
    ] + order_lines(order) + ["", "Subtotal: %s" % taka(order.subtotal), "Delivery: %s" % taka(order.shipping_fee)]
    if order.discount:
        lines.append("Discount: -%s%s" % (taka(order.discount), " (%s)" % order.promo_code if order.promo_code else ""))
    lines.append("Total: %s" % taka(order.total))
    if order.payment_method == "bkash":
        lines.append("Payment: bKash from %s, TrxID %s" % (order.bkash_number, order.bkash_trx_id))
    else:
        lines.append("Payment: Cash on Delivery")
    if order.note:
        lines += ["", "Note: %s" % order.note]
    return "\n".join(lines)


def whatsapp_url(order):
    number = SiteSettings.load().whatsapp_number
    return "https://wa.me/%s?text=%s" % (number, quote(whatsapp_text(order))) if number else ""


def sheet_payload(order):
    return {
        "no": order.order_no, "name": order.customer_name, "phone": order.phone, "email": order.email,
        "address": order.address, "area": AREA_LABELS[order.area], "items": "\n".join(order_lines(order)),
        "subtotal": order.subtotal, "shipping": order.shipping_fee, "discount": order.discount,
        "promo": order.promo_code, "total": order.total, "payment": dict(Order.PAYMENT)[order.payment_method],
        "bkashNumber": order.bkash_number, "trx": order.bkash_trx_id, "note": order.note,
    }


# ---------------- notifications (never block or break an order) ----------------

def notify(order_id):
    if settings.NOTIFY_ASYNC:
        threading.Thread(target=_notify_thread, args=(order_id,), daemon=True).start()
    else:
        _notify(order_id)


def _notify_thread(order_id):
    try:
        _notify(order_id)
    finally:
        close_old_connections()


def _notify(order_id):
    try:
        order = Order.objects.prefetch_related("items").get(pk=order_id)
    except Order.DoesNotExist:
        return
    for step in (push_to_sheet, send_owner_email, send_whatsapp_cloud):
        try:
            step(order)
        except Exception:
            log.exception("%s failed for order %s", step.__name__, order.order_no)


def push_to_sheet(order):
    """Adds the order to your Google Sheet through the Apps Script web app. Safe to repeat."""
    url = settings.GOOGLE_SHEET_WEBHOOK_URL
    if not url:
        return False
    request = urllib.request.Request(
        url, data=json.dumps(sheet_payload(order)).encode("utf-8"),
        headers={"Content-Type": "text/plain;charset=utf-8"}, method="POST",
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        body = response.read().decode("utf-8", "replace")
    try:
        ok = json.loads(body).get("ok") is True
    except ValueError:
        ok = False
    if ok:
        Order.objects.filter(pk=order.pk).update(sheet_synced=True)
    else:
        log.error("Google Sheet rejected order %s: %s", order.order_no, body[:300])
    return ok


def send_owner_email(order):
    to = SiteSettings.load().order_alert_email or settings.ORDER_ALERT_EMAIL
    if not to:
        return
    send_mail(
        "New Ayha order %s - %s (%s)" % (order.order_no, taka(order.total), order.get_payment_method_display()),
        whatsapp_text(order), None, [to], fail_silently=False,
    )


def send_whatsapp_cloud(order):
    """Optional automatic WhatsApp alert to you using Meta's WhatsApp Cloud API."""
    token, phone_id, to = settings.WA_TOKEN, settings.WA_PHONE_NUMBER_ID, settings.WA_OWNER_NUMBER
    if not (token and phone_id and to):
        return
    payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": whatsapp_text(order)}}
    request = urllib.request.Request(
        "https://graph.facebook.com/v20.0/%s/messages" % phone_id, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token}, method="POST",
    )
    urllib.request.urlopen(request, timeout=20).read()

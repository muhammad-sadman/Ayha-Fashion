import json

from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_POST

from .models import Category, HeroSlide, Order, Product, PromoCode, SiteSettings
from .services import (
    REF_RE, OrderError, create_order, find_usable_promo, get_client_ip, is_rate_limited, whatsapp_url,
)


@ensure_csrf_cookie
def index(request):
    return render(request, "shop/index.html")


def _json_body(request):
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        raise OrderError("Bad request.")
    if not isinstance(data, dict):
        raise OrderError("Bad request.")
    return data


@never_cache
@require_GET
def store_api(request):
    site = SiteSettings.load()
    categories = list(
        Category.objects.filter(is_active=True).prefetch_related("subcategories")
    )
    cat_json, hue_by_cat = [], {}
    for c in categories:
        hue_by_cat[c.id] = c.hue
        cat_json.append({
            "id": c.slug, "name": c.name, "hue": c.hue, "img": c.image.url if c.image else "",
            "subs": [s.name for s in c.subcategories.all()],
        })

    seen = {}
    products = []
    qs = (
        Product.objects.filter(is_active=True, category__is_active=True)
        .select_related("category", "subcategory").prefetch_related("images")
    )
    for p in qs:
        idx = seen.get(p.category_id, 0)
        seen[p.category_id] = idx + 1
        products.append({
            "id": p.id, "cat": p.category.slug, "sub": p.subcategory.name if p.subcategory else "",
            "name": p.name, "price": p.price, "old": p.old_price or 0,
            "hue": (hue_by_cat.get(p.category_id, 152) + idx * 14) % 360,
            "images": [i.image.url for i in p.images.all()], "spec": p.spec_lines, "inStock": p.in_stock,
        })

    slides = [
        {"eyebrow": s.eyebrow, "h": s.heading, "p": s.text, "cta": s.button_text, "hue": s.hue,
         "img": s.image.url if s.image else ""}
        for s in HeroSlide.objects.filter(is_active=True)
    ]
    config = {
        "brand": {"name": site.brand_name, "tagline": site.tagline},
        "whatsappNumber": site.whatsapp_number, "whatsappAutoOpen": site.whatsapp_auto_open,
        "bkash": {"number": site.bkash_number, "type": site.bkash_type},
        "shipping": {
            "dhaka": {"fee": site.shipping_dhaka_fee, "label": "Inside Dhaka City", "days": site.shipping_dhaka_days},
            "out": {"fee": site.shipping_out_fee, "label": "Outside Dhaka City", "days": site.shipping_out_days},
        },
        "promosEnabled": PromoCode.objects.filter(is_active=True).exists(),
        "contact": {
            "phone": site.contact_phone, "email": site.contact_email, "address": site.contact_address,
            "messenger": site.messenger_url,
        },
        "social": {"facebook": site.facebook_url, "youtube": site.youtube_url, "instagram": site.instagram_url},
        "footerText": site.footer_text, "about": site.about_text, "slides": slides,
    }
    return JsonResponse({"config": config, "categories": cat_json, "products": products})


@require_POST
def promo_api(request):
    try:
        data = _json_body(request)
    except OrderError as e:
        return JsonResponse({"ok": False, "error": e.message}, status=400)
    ip = get_client_ip(request) or "unknown"
    key = "promo-checks:%s" % ip
    tries = cache.get(key, 0)
    if tries >= 30:
        return JsonResponse({"ok": False, "error": "Too many attempts. Please wait a few minutes."}, status=429)
    cache.set(key, tries + 1, 600)
    promo = find_usable_promo(data.get("code"))
    if not promo:
        return JsonResponse({"ok": False, "error": "Code not recognised"})
    return JsonResponse({"ok": True, "code": promo.code, "amount": promo.amount})


def order_json(order):
    return {
        "no": order.order_no, "name": order.customer_name, "total": order.total, "subtotal": order.subtotal,
        "shipping": order.shipping_fee, "discount": order.discount,
        "payment": "bKash" if order.payment_method == "bkash" else "COD",
        "trx": order.bkash_trx_id, "whatsapp_url": whatsapp_url(order),
    }


@require_POST
def order_api(request):
    try:
        data = _json_body(request)
    except OrderError as e:
        return JsonResponse({"ok": False, "error": e.message}, status=400)

    if data.get("hp"):  # hidden field only bots fill in: pretend it worked, save nothing
        return JsonResponse({"ok": True, "order": {
            "no": "AY-000000-0000", "name": str(data.get("name", ""))[:60], "total": 0, "subtotal": 0,
            "shipping": 0, "discount": 0, "payment": "COD", "trx": "", "whatsapp_url": "",
        }})

    ref = str(data.get("client_ref") or "")
    if REF_RE.match(ref):  # customer retrying an order we already saved
        existing = Order.objects.filter(client_ref=ref).first()
        if existing:
            return JsonResponse({"ok": True, "order": order_json(existing)})

    ip = get_client_ip(request)
    if is_rate_limited(ip):
        return JsonResponse(
            {"ok": False, "error": "You have placed several orders in a short time. Please wait a few minutes or order on WhatsApp."},
            status=429,
        )
    try:
        order, _ = create_order(data, ip)
    except OrderError as e:
        return JsonResponse({"ok": False, "error": e.message}, status=e.status)
    return JsonResponse({"ok": True, "order": order_json(order)})

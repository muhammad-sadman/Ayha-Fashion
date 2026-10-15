import csv
from datetime import timedelta

from django.contrib import admin, messages
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    Category, HeroSlide, Order, OrderItem, Product, ProductImage, PromoCode, SiteSettings, SubCategory,
)
from .services import push_to_sheet

admin.site.site_header = "Ayha BD admin"
admin.site.site_title = "Ayha BD admin"
admin.site.index_title = "Manage your shop"


# ---------------- store settings ----------------

@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    fieldsets = [
        ("Brand", {"fields": ["brand_name", "tagline", "footer_text", "about_text"]}),
        ("WhatsApp", {"fields": ["whatsapp_number", "whatsapp_auto_open"]}),
        ("bKash (manual payment)", {"fields": ["bkash_number", "bkash_type"]}),
        ("Delivery", {"fields": [
            ("shipping_dhaka_fee", "shipping_dhaka_days"), ("shipping_out_fee", "shipping_out_days"),
        ]}),
        ("Contact", {"fields": ["contact_phone", "contact_email", "contact_address", "messenger_url"]}),
        ("Social media", {"fields": ["facebook_url", "youtube_url", "instagram_url"]}),
        ("Order alerts", {"fields": ["order_alert_email"]}),
    ]

    def has_add_permission(self, request):
        return not SiteSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        obj = SiteSettings.load()
        return redirect(reverse("admin:shop_sitesettings_change", args=[obj.pk]))


@admin.register(HeroSlide)
class HeroSlideAdmin(admin.ModelAdmin):
    list_display = ["heading", "eyebrow", "order", "is_active"]
    list_editable = ["order", "is_active"]


# ---------------- catalog ----------------

class SubCategoryInline(admin.TabularInline):
    model = SubCategory
    extra = 3


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "order", "is_active", "product_count"]
    list_editable = ["order", "is_active"]
    prepopulated_fields = {"slug": ("name",)}
    inlines = [SubCategoryInline]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_n=Count("products"))

    @admin.display(description="Products", ordering="_n")
    def product_count(self, obj):
        return obj._n


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 4


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["thumb", "name", "sku", "category", "subcategory", "price", "old_price", "in_stock", "is_active"]
    list_display_links = ["thumb", "name"]
    list_editable = ["price", "old_price", "in_stock", "is_active"]
    list_filter = ["category", "in_stock", "is_active"]
    search_fields = ["name", "sku"]
    list_per_page = 40
    inlines = [ProductImageInline]
    actions = ["mark_in_stock", "mark_out_of_stock", "hide_products", "show_products"]

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("category", "subcategory").prefetch_related("images")

    @admin.display(description="Photo")
    def thumb(self, obj):
        img = next(iter(obj.images.all()), None)
        if not img:
            return "-"
        return format_html('<img src="{}" style="height:48px;width:36px;object-fit:cover;border-radius:4px">', img.image.url)

    @admin.action(description="Mark selected as in stock")
    def mark_in_stock(self, request, qs):
        qs.update(in_stock=True)

    @admin.action(description="Mark selected as out of stock")
    def mark_out_of_stock(self, request, qs):
        qs.update(in_stock=False)

    @admin.action(description="Hide selected from the website")
    def hide_products(self, request, qs):
        qs.update(is_active=False)

    @admin.action(description="Show selected on the website")
    def show_products(self, request, qs):
        qs.update(is_active=True)


@admin.register(PromoCode)
class PromoCodeAdmin(admin.ModelAdmin):
    list_display = ["code", "amount", "is_active", "times_used", "max_uses", "expires_at"]
    list_editable = ["is_active"]


# ---------------- orders ----------------

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    can_delete = False
    fields = ["name", "sku", "unit_price", "quantity", "line_total"]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


def _status_action(status, label):
    def action(modeladmin, request, queryset):
        n = queryset.update(status=status)
        modeladmin.message_user(request, "%d order(s) marked %s." % (n, label), messages.SUCCESS)
    action.short_description = "Mark selected as %s" % label
    action.__name__ = "mark_%s" % status
    return action


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    change_list_template = "admin/shop/order/change_list.html"
    list_display = [
        "order_no", "created_at", "customer_name", "phone", "area", "payment_col", "payment_verified",
        "total_col", "status", "sheet_synced", "slip_link",
    ]
    list_filter = ["status", "payment_method", "payment_verified", "area", "created_at"]
    search_fields = ["order_no", "customer_name", "phone", "bkash_trx_id", "address"]
    date_hierarchy = "created_at"
    list_per_page = 50
    inlines = [OrderItemInline]
    fieldsets = [
        ("Order", {"fields": ["order_no", "created_at", "status", "slip_link", "sheet_synced"]}),
        ("Customer", {"fields": ["customer_name", "phone", "email", "address", "area", "note"]}),
        ("Payment", {"fields": [
            "payment_method", "bkash_number", "bkash_trx_id", "payment_verified",
            "subtotal", "shipping_fee", "discount", "promo_code", "total",
        ]}),
        ("Your private notes", {"fields": ["admin_note"]}),
    ]
    readonly_fields = [
        "order_no", "created_at", "slip_link", "sheet_synced", "customer_name", "phone", "email", "address",
        "area", "note", "payment_method", "bkash_number", "bkash_trx_id", "subtotal", "shipping_fee",
        "discount", "promo_code", "total",
    ]
    actions = [
        _status_action("confirmed", "Confirmed"), _status_action("packed", "Packed"),
        _status_action("shipped", "Shipped"), _status_action("delivered", "Delivered"),
        _status_action("cancelled", "Cancelled"),
        "verify_bkash", "print_slips", "export_csv", "resend_to_sheet",
    ]

    def has_add_permission(self, request):
        return False  # orders come from the website

    @admin.display(description="Payment")
    def payment_col(self, obj):
        if obj.payment_method == "bkash":
            return format_html('<b style="color:#e2136e">bKash</b> {}', obj.bkash_trx_id)
        return "Cash on Delivery"

    @admin.display(description="Total", ordering="total")
    def total_col(self, obj):
        return "৳{:,}".format(obj.total)

    @admin.display(description="Delivery slip")
    def slip_link(self, obj):
        if not obj.pk:
            return "-"
        return format_html('<a href="{}" target="_blank">Print slip</a>', reverse("admin:shop_order_slip", args=[obj.pk]))

    # --- delivery slips ---
    def get_urls(self):
        custom = [path("<int:pk>/slip/", self.admin_site.admin_view(self.slip_view), name="shop_order_slip")]
        return custom + super().get_urls()

    def _render_slips(self, request, orders):
        return render(request, "shop/slip.html", {"orders": orders})

    def slip_view(self, request, pk):
        order = get_object_or_404(Order.objects.prefetch_related("items"), pk=pk)
        return self._render_slips(request, [order])

    @admin.action(description="Print delivery slips for selected")
    def print_slips(self, request, queryset):
        return self._render_slips(request, list(queryset.prefetch_related("items").order_by("created_at")))

    # --- other actions ---
    @admin.action(description="Mark bKash payment as verified")
    def verify_bkash(self, request, queryset):
        n = queryset.filter(payment_method="bkash").update(payment_verified=True)
        self.message_user(request, "%d bKash payment(s) marked verified." % n, messages.SUCCESS)

    @admin.action(description="Export selected to CSV")
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'attachment; filename="ayha-orders.csv"'
        response.write("﻿")  # so Excel shows Bangla/taka signs correctly
        w = csv.writer(response)
        w.writerow(["Order", "Date", "Status", "Name", "Phone", "Email", "Address", "Area", "Items", "Subtotal",
                    "Delivery", "Discount", "Total", "Payment", "bKash number", "TrxID", "Verified", "Note"])
        for o in queryset.prefetch_related("items").order_by("created_at"):
            w.writerow([
                o.order_no, timezone.localtime(o.created_at).strftime("%Y-%m-%d %H:%M"), o.get_status_display(),
                o.customer_name, o.phone, o.email, o.address, o.get_area_display(),
                "; ".join("%s x%d" % (i.name, i.quantity) for i in o.items.all()),
                o.subtotal, o.shipping_fee, o.discount, o.total, o.get_payment_method_display(),
                o.bkash_number, o.bkash_trx_id, "yes" if o.payment_verified else "no", o.note,
            ])
        return response

    @admin.action(description="Send selected to Google Sheet again")
    def resend_to_sheet(self, request, queryset):
        done = failed = 0
        for o in queryset.prefetch_related("items"):
            try:
                ok = push_to_sheet(o)
            except Exception:
                ok = False
            done += 1 if ok else 0
            failed += 0 if ok else 1
        level = messages.SUCCESS if not failed else messages.WARNING
        self.message_user(request, "%d sent to the Sheet, %d failed (check GOOGLE_SHEET_WEBHOOK_URL)." % (done, failed), level)

    # --- summary above the list ---
    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        extra_context["stats"] = self._stats()
        return super().changelist_view(request, extra_context=extra_context)

    def _stats(self):
        now = timezone.localtime()
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        live = Order.objects.exclude(status__in=["cancelled", "returned"])

        def agg(since):
            r = live.filter(created_at__gte=since).aggregate(n=Count("id"), t=Sum("total"))
            return {"orders": r["n"] or 0, "revenue": r["t"] or 0}

        return {
            "today": agg(today), "week": agg(today - timedelta(days=6)), "month": agg(today.replace(day=1)),
            "new": Order.objects.filter(status="new").count(),
            "unverified": live.filter(payment_method="bkash", payment_verified=False).count(),
        }

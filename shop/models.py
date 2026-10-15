import logging
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone

log = logging.getLogger("shop")

digits_only = RegexValidator(r"^[0-9]+$", "Digits only, no spaces or + sign.")


def shrink_upload(fieldfile, max_side=1600):
    """Downsize big phone photos when they are uploaded so pages stay fast on mobile data.
    Only newly uploaded files are touched. If anything goes wrong the original is kept."""
    if not fieldfile or getattr(fieldfile, "_committed", True):
        return
    try:
        from PIL import Image, ImageOps

        src = Image.open(fieldfile.file)
        fmt = (src.format or "").upper()
        if fmt not in ("JPEG", "PNG", "WEBP"):
            return
        size_bytes = getattr(fieldfile, "size", 0) or 0
        if max(src.size) <= max_side and size_bytes <= 600 * 1024:
            return
        img = ImageOps.exif_transpose(src)
        img.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = BytesIO()
        if fmt == "JPEG":
            img.convert("RGB").save(buf, "JPEG", quality=85, optimize=True)
        elif fmt == "WEBP":
            img.save(buf, "WEBP", quality=85)
        else:
            img.save(buf, "PNG", optimize=True)
        if buf.tell() < size_bytes or max(src.size) > max_side:
            fieldfile.save(fieldfile.name.rsplit("/", 1)[-1], ContentFile(buf.getvalue()), save=False)
    except Exception:  # never block an upload because of resizing
        log.warning("Could not resize uploaded image", exc_info=True)


class SiteSettings(models.Model):
    """One row of store-wide settings. Edit it in the admin under 'Store settings'."""

    brand_name = models.CharField(max_length=60, default="Ayha")
    tagline = models.CharField(max_length=80, default="Style made simple")
    footer_text = models.CharField(
        max_length=200, default="Everyday fashion, delivered across Bangladesh. Pay when your order arrives."
    )
    about_text = models.TextField(default="Ayha is a Bangladeshi online store for everyday fashion.")

    whatsapp_number = models.CharField(
        max_length=20, blank=True, validators=[digits_only],
        help_text="Your WhatsApp Business number, international format, digits only. Example: 8801712345678",
    )
    whatsapp_auto_open = models.BooleanField(
        default=True, help_text="After an order, open WhatsApp automatically with the order details ready to send."
    )

    BKASH_TYPES = [("Personal", "Personal (customers use Send Money)"), ("Merchant", "Merchant (customers use Payment)")]
    bkash_number = models.CharField(max_length=20, blank=True, validators=[digits_only])
    bkash_type = models.CharField(max_length=10, choices=BKASH_TYPES, default="Personal")

    shipping_dhaka_fee = models.PositiveIntegerField(default=70, verbose_name="Inside Dhaka fee (taka)")
    shipping_dhaka_days = models.CharField(max_length=20, default="1-3", verbose_name="Inside Dhaka days")
    shipping_out_fee = models.PositiveIntegerField(default=130, verbose_name="Outside Dhaka fee (taka)")
    shipping_out_days = models.CharField(max_length=20, default="2-5", verbose_name="Outside Dhaka days")

    contact_phone = models.CharField(max_length=40, blank=True)
    contact_email = models.EmailField(blank=True)
    contact_address = models.CharField(max_length=200, blank=True, default="Dhaka, Bangladesh")
    messenger_url = models.URLField(blank=True, help_text="Example: https://m.me/yourpagename")
    facebook_url = models.URLField(blank=True)
    youtube_url = models.URLField(blank=True)
    instagram_url = models.URLField(blank=True)

    order_alert_email = models.EmailField(
        blank=True, help_text="Get an email for every new order. Needs email settings in .env (see README)."
    )

    class Meta:
        verbose_name = "Store settings"
        verbose_name_plural = "Store settings"

    def __str__(self):
        return "Store settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class HeroSlide(models.Model):
    eyebrow = models.CharField(max_length=40, blank=True, help_text="Small text above the heading")
    heading = models.CharField(max_length=80)
    text = models.CharField(max_length=200, blank=True)
    button_text = models.CharField(max_length=30, default="Shop Collection")
    image = models.ImageField(upload_to="slides/", blank=True, help_text="Optional banner photo, about 1200x800")
    hue = models.PositiveSmallIntegerField(default=152, help_text="Background colour tone when there is no photo (0-360)")
    order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "Home banner slide"

    def __str__(self):
        return self.heading

    def save(self, *args, **kwargs):
        shrink_upload(self.image)
        super().save(*args, **kwargs)


class Category(models.Model):
    name = models.CharField(max_length=60)
    slug = models.SlugField(unique=True)
    hue = models.PositiveSmallIntegerField(default=152, help_text="Placeholder colour tone (0-360) when there is no photo")
    image = models.ImageField(upload_to="categories/", blank=True, help_text="Optional photo for the home page tile")
    order = models.PositiveSmallIntegerField(default=0, help_text="Smaller numbers appear first")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order", "name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        shrink_upload(self.image)
        super().save(*args, **kwargs)


class SubCategory(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="subcategories")
    name = models.CharField(max_length=60)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["order", "name"]
        unique_together = [("category", "name")]
        verbose_name = "filter button (subcategory)"
        verbose_name_plural = "filter buttons (subcategories)"

    def __str__(self):
        return f"{self.category.name} / {self.name}"


class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    subcategory = models.ForeignKey(
        SubCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="products"
    )
    name = models.CharField(max_length=160)
    sku = models.CharField(max_length=40, blank=True, help_text="Your product code, e.g. AY101")
    price = models.PositiveIntegerField(validators=[MinValueValidator(1)], help_text="Selling price in taka")
    old_price = models.PositiveIntegerField(
        default=0, blank=True, help_text="Price before discount (shown crossed out). 0 = no discount."
    )
    specs = models.TextField(
        blank=True, help_text="One line per detail, e.g.\nFabric: Cotton\nLength: 12.5 hat\nBlouse piece: 1.5 hat"
    )
    in_stock = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True, help_text="Untick to hide this product from the website")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category__order", "-id"]

    def __str__(self):
        return self.name

    def clean(self):
        if self.old_price and self.old_price <= self.price:
            raise ValidationError({"old_price": "Old price must be higher than the selling price (or 0)."})
        if self.subcategory_id and self.category_id and self.subcategory.category_id != self.category_id:
            raise ValidationError({"subcategory": "This filter button belongs to a different category."})

    @property
    def spec_lines(self):
        return [ln.strip() for ln in self.specs.splitlines() if ln.strip()]


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="products/")
    order = models.PositiveSmallIntegerField(default=0, help_text="First image is the main photo")

    class Meta:
        ordering = ["order", "id"]

    def save(self, *args, **kwargs):
        shrink_upload(self.image)
        super().save(*args, **kwargs)


class PromoCode(models.Model):
    code = models.CharField(max_length=30, unique=True, help_text="Customers type this. Saved in capitals.")
    amount = models.PositiveIntegerField(help_text="Taka taken off the order")
    is_active = models.BooleanField(default=True)
    starts_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    max_uses = models.PositiveIntegerField(null=True, blank=True, help_text="Leave empty for unlimited")
    times_used = models.PositiveIntegerField(default=0, editable=False)

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def is_usable(self, now=None):
        now = now or timezone.now()
        if not self.is_active:
            return False
        if self.starts_at and now < self.starts_at:
            return False
        if self.expires_at and now > self.expires_at:
            return False
        if self.max_uses is not None and self.times_used >= self.max_uses:
            return False
        return True


class Order(models.Model):
    STATUS = [
        ("new", "New"), ("confirmed", "Confirmed"), ("packed", "Packed"), ("shipped", "Shipped"),
        ("delivered", "Delivered"), ("cancelled", "Cancelled"), ("returned", "Returned"),
    ]
    PAYMENT = [("cod", "Cash on Delivery"), ("bkash", "bKash")]
    AREA = [("dhaka", "Inside Dhaka City"), ("out", "Outside Dhaka City")]

    order_no = models.CharField(max_length=20, unique=True, editable=False)
    client_ref = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    status = models.CharField(max_length=12, choices=STATUS, default="new")

    customer_name = models.CharField(max_length=120)
    phone = models.CharField(max_length=11)
    email = models.EmailField(blank=True)
    address = models.TextField()
    area = models.CharField(max_length=6, choices=AREA)
    note = models.TextField(blank=True, verbose_name="Customer note")

    payment_method = models.CharField(max_length=6, choices=PAYMENT)
    bkash_number = models.CharField(max_length=11, blank=True)
    bkash_trx_id = models.CharField(max_length=12, blank=True, verbose_name="bKash TrxID")
    payment_verified = models.BooleanField(
        default=False, help_text="Tick after you match the TrxID and amount in your bKash history."
    )

    subtotal = models.PositiveIntegerField()
    shipping_fee = models.PositiveIntegerField()
    discount = models.PositiveIntegerField(default=0)
    promo_code = models.CharField(max_length=30, blank=True)
    total = models.PositiveIntegerField()

    admin_note = models.TextField(blank=True, help_text="Private note for you and your staff. Customers never see this.")
    sheet_synced = models.BooleanField(default=False, verbose_name="In Google Sheet", editable=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # A bKash TrxID can pay for one order only (stops the same receipt being reused).
            models.UniqueConstraint(
                fields=["bkash_trx_id"], condition=~models.Q(bkash_trx_id=""), name="unique_bkash_trx_id"
            ),
        ]

    def __str__(self):
        return self.order_no


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    name = models.CharField(max_length=160)
    sku = models.CharField(max_length=40, blank=True)
    unit_price = models.PositiveIntegerField()
    quantity = models.PositiveSmallIntegerField()
    line_total = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.name} x{self.quantity}"

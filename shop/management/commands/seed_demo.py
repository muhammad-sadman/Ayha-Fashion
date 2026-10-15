from django.core.management.base import BaseCommand

from shop.models import Category, HeroSlide, Product, SiteSettings, SubCategory

CATEGORIES = [
    ("cotton", "Cotton Collection", 152, ["Three Piece", "Saree", "Kurti"]),
    ("silk", "Silk & Festive", 40, ["Three Piece", "Saree", "Unstitched"]),
    ("print", "Digital Print", 160, ["Three Piece", "Kurti", "Co-ord Set"]),
    ("party", "Party Wear", 36, ["Three Piece", "Gown", "Jewellery"]),
]
NAMES = ["Everyday Block Print", "Soft Weave Daily Wear", "Floral Garden Print", "Classic Border Design",
         "Pastel Bloom", "Heritage Motif", "Midnight Boota", "Sunrise Check"]
FABRIC = ["Cotton", "Silk Blend", "Linen Mix", "Georgette"]
PRINT = ["Block", "Digital", "Hand Dyed", "Embroidered"]
SLIDES = [
    ("New season", "Wear it once, love it for years.",
     "Fresh arrivals picked for Bangladeshi weather, weddings and everyday days.", "Shop Collection", 152),
    ("Free to try", "Cash on delivery, nationwide.",
     "Order today. Check your parcel. Pay only when it reaches your door.", "See Delivery", 158),
    ("Thank you", "Join thousands of happy customers.",
     "Follow Ayha for restock alerts and early access to every drop.", "Browse Products", 146),
]


class Command(BaseCommand):
    help = "Adds example categories, products and banner slides so the site is not empty. Safe to run once."

    def handle(self, *args, **options):
        SiteSettings.load()
        if Category.objects.exists():
            self.stdout.write("Categories already exist, nothing added.")
            return
        n = 0
        for ci, (slug, name, hue, subs) in enumerate(CATEGORIES):
            cat = Category.objects.create(name=name, slug=slug, hue=hue, order=ci)
            sub_objs = [SubCategory.objects.create(category=cat, name=s, order=i) for i, s in enumerate(subs)]
            for i in range(4):
                base = 1450 + ((ci * 4 + i) * 130 % 1300)
                price = base - base % 10
                old = (base + 350) - (base + 350) % 10 if i % 2 == 0 else 0
                n += 1
                Product.objects.create(
                    category=cat, subcategory=sub_objs[i % len(sub_objs)],
                    name="%s %s | AY%03d" % (NAMES[(ci * 2 + i) % 8], name.split()[0], 100 + n),
                    sku="AY%03d" % (100 + n), price=price, old_price=old,
                    specs="Fabric: %s\nPrint: %s\nLength: 12.5 hat\nBlouse piece: 1.5 hat" % (FABRIC[ci], PRINT[i]),
                )
        for i, (eyebrow, heading, text, button, hue) in enumerate(SLIDES):
            HeroSlide.objects.create(eyebrow=eyebrow, heading=heading, text=text, button_text=button, hue=hue, order=i)
        self.stdout.write(self.style.SUCCESS("Added %d example products. Replace them in the admin." % n))

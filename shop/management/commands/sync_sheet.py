from django.core.management.base import BaseCommand

from shop.models import Order
from shop.services import push_to_sheet


class Command(BaseCommand):
    help = "Sends any orders that are not yet in the Google Sheet (use after a network problem)."

    def handle(self, *args, **options):
        pending = Order.objects.filter(sheet_synced=False).prefetch_related("items").order_by("created_at")
        ok = bad = 0
        for order in pending:
            try:
                done = push_to_sheet(order)
            except Exception as exc:
                self.stderr.write("%s failed: %s" % (order.order_no, exc))
                done = False
            ok += 1 if done else 0
            bad += 0 if done else 1
        self.stdout.write("Sent %d, failed %d." % (ok, bad))

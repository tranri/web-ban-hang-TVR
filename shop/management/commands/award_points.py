from django.core.management.base import BaseCommand
from django.db import transaction, IntegrityError
from django.utils import timezone
from datetime import timedelta
from django.db.models import F

from shop.models import Order, Customer, normalize_phone
from django.contrib.auth.hashers import make_password
import os
import binascii


class Command(BaseCommand):
    help = "Award points for completed orders (1% of total_price)."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show actions without changing data.')

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)

        qs = Order.objects.filter(points_awarded=False).order_by('created_at')

        # Filter in Python using the model method
        eligible_orders = [o for o in qs if o.is_eligible_for_points()]

        total = len(eligible_orders)
        if total == 0:
            self.stdout.write("No completed orders to process.")
            return

        self.stdout.write(f"Found {total} completed order(s) to process. dry_run={dry_run}")

        for order in qs:
            # Lock the order row to avoid races with concurrent runs
            try:
                with transaction.atomic():
                    o = Order.objects.select_for_update().get(pk=order.pk)

                    # Re-check in-transaction
                    if o.points_awarded:
                        self.stdout.write(f"Order {o.id}: already processed (skipping).")
                        continue

                    points = o.calculate_points()
                    if points <= 0:
                        self.stdout.write(f"Order {o.id}: calculated 0 points, marking as processed.")
                        if not dry_run:
                            o.points_awarded = True
                            o.awarded_points = 0
                            o.save(update_fields=['points_awarded', 'awarded_points'])
                        continue

                    # Normalize phone and try to find customer
                    phone_val = normalize_phone(o.phone) or (o.phone or "")
                    customer = None
                    if phone_val:
                        customer = Customer.objects.filter(phone=phone_val).first()

                    if not customer:
                        if dry_run:
                            self.stdout.write(f"Order {o.id}: would create guest Customer for phone {phone_val!r}.")
                        else:
                            # Safely create or get existing (handle race via IntegrityError)
                            defaults = {
                                'full_name': o.full_name or "Khách vãng lai",
                                'address': o.address or "",
                                # set temporary unusable password (hashed)
                                'password': make_password(binascii.hexlify(os.urandom(12)).decode()),
                                'points': 0,
                            }
                            try:
                                customer, created = Customer.objects.get_or_create(phone=phone_val, defaults=defaults)
                                if created:
                                    # mark as guest if model has is_guest
                                    if hasattr(customer, 'is_guest'):
                                        customer.is_guest = True
                                        customer.save(update_fields=['is_guest'])
                                    self.stdout.write(
                                        f"Order {o.id}: created guest Customer id={customer.id} phone={phone_val!r}.")
                                else:
                                    self.stdout.write(
                                        f"Order {o.id}: found existing Customer id={customer.id} phone={phone_val!r}.")
                            except IntegrityError:
                                # Race: another process created it — fetch it
                                customer = Customer.objects.filter(phone=phone_val).first()
                                if customer:
                                    self.stdout.write(
                                        f"Order {o.id}: race created Customer id={customer.id} phone={phone_val!r}.")
                                else:
                                    raise

                    # Logging for dry-run when we've found a customer object
                    if dry_run:
                        cust_info = f"id={getattr(customer, 'id', None)} phone={phone_val!r}"
                        self.stdout.write(
                            f"[dry-run] Order {o.id}: would award {points} points to Customer {cust_info}.")
                        # Do not modify DB
                        continue

                    # Award points atomically
                    with transaction.atomic():
                        # Refresh customer with lock if possible
                        if customer:
                            Customer.objects.select_for_update().filter(pk=customer.pk)

                        # increment customer.points using F to avoid race
                        if customer:
                            Customer.objects.filter(pk=customer.pk).update(points=F('points') + points)

                        # mark order processed and link customer
                        o.points_awarded = True
                        o.awarded_points = points
                        if customer and not o.customer_id:
                            o.customer = customer
                        o.save(update_fields=['points_awarded', 'awarded_points', 'customer'])

                        self.stdout.write(
                            f"Order {o.id}: awarded {points} points to customer phone={phone_val!r} (order linked).")

            except Exception as exc:
                self.stderr.write(f"Order {order.id}: ERROR processing order: {exc}")
                # continue processing next orders

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from shop.models import Order, Customer


class Command(BaseCommand):
    help = "Award points for orders that are completed (per is_completed()) and not yet awarded."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show actions without changing data.')

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)

        # Find orders that are not awarded yet and are considered completed
        orders = Order.objects.filter(points_awarded=False)
        orders = [o for o in orders if o.is_completed()]

        if not orders:
            self.stdout.write("No completed orders to process.")
            return

        self.stdout.write(f"Processing {len(orders)} completed order(s). dry_run={dry_run}")

        for order in orders:
            points = order.calculate_points()
            if points <= 0:
                self.stdout.write(f"Order {order.id}: calculated 0 points, marking as processed.")
                if not dry_run:
                    order.points_awarded = True
                    order.awarded_points = 0
                    order.save(update_fields=['points_awarded', 'awarded_points'])
                continue

            # 🔄 THAY ĐỔI TẠI ĐÂY: Thay vì bỏ qua nếu không tìm thấy customer, ta tạo mới dạng vãng lai
            customer = Customer.objects.filter(phone=order.phone).first()
            if not customer:
                if not dry_run:
                    # Tự động tạo tài khoản ngầm cho số điện thoại này để tích điểm
                    customer = Customer.objects.create(
                        full_name=order.full_name,
                        phone=order.phone,
                        address=order.address,
                        password='',  # Chưa đăng ký mật khẩu web
                        points=0
                    )
                    self.stdout.write(f"Order {order.id}: Created automatic Customer record for phone {order.phone}.")
                else:
                    self.stdout.write(
                        f"Order {order.id}: Would create automatic Customer record for phone {order.phone}.")
            self.stdout.write(
                f"Order {order.id}: awarding {points} points to Customer {customer.phone} ({customer.full_name}).")
            if not dry_run:
                try:
                    with transaction.atomic():
                        customer.points = (customer.points or 0) + points
                        customer.save(update_fields=['points'])

                        order.points_awarded = True
                        order.awarded_points = points
                        order.save(update_fields=['points_awarded', 'awarded_points'])
                except Exception as e:
                    self.stderr.write(f"Order {order.id}: ERROR while awarding points: {e}")

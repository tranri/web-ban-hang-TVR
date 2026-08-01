# services.py
import logging
from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone
from django.conf import settings
import requests
import threading
from .models import Product, Order, OrderItem, Customer

logger = logging.getLogger(__name__)


class OrderService:
    @staticmethod
    def send_telegram_notification(order, order_items):
        try:
            token = settings.TELEGRAM_BOT_TOKEN
            chat_id = settings.TELEGRAM_CHAT_ID

            if not token or not chat_id:
                logger.warning("Telegram credentials not configured")
                return

            items_text = "\nnot found".join(  # Hoặc định dạng chuỗi sản phẩm
                f"- {item.product.name} (x{item.quantity}): {item.price:,.0f}đ"
                for item in order_items
            )

            message = f"""🛒 *ĐƠN HÀNG MỚI #{order.id}*
👤 Khách: {order.full_name}
📞 SĐT: {order.phone}
📍 Địa chỉ: {order.address}
📦 Sản phẩm:
{items_text}
💰 Tổng: *{order.total_price:,.0f}đ*"""

            url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(url, data={
                'chat_id': chat_id,
                'text': message,
                'parse_mode': 'Markdown'
            }, timeout=5)
        except Exception as e:
            logger.error(f"Telegram notification failed: {e}")

    @staticmethod
    @transaction.atomic
    def create_pos_order(data):
        """Xử lý nghiệp vụ tạo đơn hàng POS tại quầy"""
        items = data.get('items', [])
        customer_phone = data.get('phone', '').strip()
        customer_name = data.get('full_name', 'Khách lẻ tại quầy').strip()
        customer_address = data.get('address', 'Mua trực tiếp tại cửa hàng').strip()
        applied_points = int(data.get('applied_points', 0))

        if not items:
            raise ValueError("Giỏ hàng trống!")

        total_price = Decimal(0)
        order_items_data = []

        for item in items:
            product = Product.objects.select_for_update().get(id=int(item['product_id']))
            qty = int(item['quantity'])

            if product.stock < qty:
                raise ValueError(f"Sản phẩm {product.name} không đủ tồn kho (Còn: {product.stock})")

            item_total = product.price * qty
            total_price += item_total

            order_items_data.append({
                'product': product,
                'quantity': qty,
                'price': product.price,
                'import_price': product.import_price,
            })

        customer = None
        if customer_phone:
            customer, _ = Customer.objects.get_or_create(
                phone=customer_phone,
                defaults={'full_name': customer_name, 'address': customer_address, 'password': ''}
            )
            if applied_points > 0:
                if customer.points >= applied_points:
                    customer.points -= applied_points
                    customer.save(update_fields=['points'])
                else:
                    raise ValueError("Khách hàng không đủ điểm tích lũy!")

        final_price = max(Decimal(0), total_price - Decimal(applied_points))

        order = Order.objects.create(
            customer=customer,
            full_name=customer_name,
            phone=customer_phone or '0000000000',
            address=customer_address,
            total_price=total_price,
            applied_points=applied_points,
            final_price=final_price,
            is_printed=True,
            printed_at=timezone.now()
        )

        for it in order_items_data:
            product = it['product']
            product.stock -= it['quantity']
            product.save()

            OrderItem.objects.create(
                order=order,
                product=product,
                quantity=it['quantity'],
                price=it['price'],
                import_price=it['import_price']
            )

        awarded = order.calculate_points()
        order.awarded_points = awarded
        order.save(update_fields=['awarded_points'])

        return order

    @staticmethod
    @transaction.atomic
    def create_web_order(form, cart):
        """Xử lý nghiệp vụ đặt hàng trực tuyến từ website[cite: 22]"""
        order = form.save(commit=False)
        order.total_price = 0
        order.save()

        total_amount = Decimal(0)
        cart_items_data = []

        for p_id, item in cart.items():
            product = Product.objects.select_for_update().get(id=int(p_id))

            if product.stock <= 0:
                raise ValueError(f"Sản phẩm {product.name} đã hết hàng.")
            if product.stock < item['quantity']:
                raise ValueError(f"Sản phẩm {product.name} không đủ số lượng trong kho (Chỉ còn {product.stock}).")

            item_total = product.price * item['quantity']
            total_amount += item_total
            cart_items_data.append({
                'product': product,
                'quantity': item['quantity'],
                'total': item_total,
                'price': product.price
            })

        applied_points = form.cleaned_data.get('applied_points') or 0
        discount_value = Decimal(int(applied_points))

        item_discounts = []
        allocated_discount = Decimal(0)
        for i, it in enumerate(cart_items_data):
            if i < len(cart_items_data) - 1 and total_amount > 0:
                exact_disc = (it['total'] / total_amount) * discount_value
                rounded_disc = (exact_disc / 1000).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * 1000
                rounded_disc = max(Decimal(0), min(rounded_disc, it['total']))
                item_discounts.append(rounded_disc)
                allocated_discount += rounded_disc
            else:
                last_disc = discount_value - allocated_discount
                last_disc = max(Decimal(0), min(last_disc, it['total']))
                item_discounts.append(last_disc)
                allocated_discount += last_disc

        final_price = max(Decimal(0), total_amount - discount_value)

        order.total_price = total_amount
        order.applied_points = applied_points
        order.final_price = final_price
        order.awarded_points = order.calculate_points()
        order.save()

        for i, it in enumerate(cart_items_data):
            product = it['product']
            qty = it['quantity']
            total_item_disc = item_discounts[i]
            disc_per_unit = total_item_disc / Decimal(qty) if qty > 0 else Decimal(0)

            product.stock -= qty
            product.save()

            OrderItem.objects.create(
                order=order,
                product=product,
                quantity=qty,
                price=product.price,
                discount_per_unit=disc_per_unit,
                import_price=product.import_price,
            )

        customer, created = Customer.objects.get_or_create(
            phone=order.phone,
            defaults={'full_name': order.full_name, 'address': order.address, 'password': ''}
        )
        if not created:
            customer.full_name = order.full_name
            customer.address = order.address
            customer.save(update_fields=['full_name', 'address'])

        order.customer = customer
        order.save(update_fields=['customer'])

        if applied_points and applied_points > 0:
            if customer.points >= applied_points:
                customer.points = customer.points - applied_points
                customer.save(update_fields=['points'])
            else:
                raise ValueError("Không đủ điểm để trừ cho đơn hàng.")

        order_items = OrderItem.objects.filter(order=order)
        threading.Thread(target=OrderService.send_telegram_notification, args=(order, order_items), daemon=True).start()

        return order, order_items, customer
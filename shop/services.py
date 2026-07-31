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
    def consume_stock_fifo(product, ordered_qty):
        """
        Thuật toán FIFO: Trừ tồn kho từ các lô cũ nhất.
        Trả về tổng giá vốn (total_cogs) và cập nhật số lượng tồn của từng lô.
        """
        batches = product.batches.filter(quantity__gt=0).order_by('created_at')
        remaining_to_deduct = ordered_qty
        total_cogs = Decimal(0)

        for batch in batches:
            if remaining_to_deduct <= 0:
                break

            if batch.quantity >= remaining_to_deduct:
                deduct = remaining_to_deduct
                batch.quantity -= deduct
                batch.save()
                total_cogs += Decimal(batch.import_price) * deduct
                remaining_to_deduct = 0
            else:
                deduct = batch.quantity
                batch.quantity = 0  # Lô này đã hết hàng, tự động đóng lại
                batch.save()
                total_cogs += Decimal(batch.import_price) * deduct
                remaining_to_deduct -= deduct

        if remaining_to_deduct > 0:
            raise ValueError(f"Sản phẩm {product.name} không đủ tồn kho theo lô (thiếu {remaining_to_deduct})")

        return total_cogs

    @staticmethod
    @transaction.atomic
    def create_web_order(data):
        """Xử lý nghiệp vụ tạo đơn hàng trực tuyến (Web Order) áp dụng FIFO"""
        items = data.get('items', [])
        user = data.get('user', None)
        customer_name = data.get('full_name', '').strip()
        customer_phone = data.get('phone', '').strip()
        shipping_address = data.get('shipping_address', '').strip()

        if not items:
            raise ValueError("Giỏ hàng trực tuyến trống!")

        total_price = Decimal(0)
        order_items_data = []

        for item in items:
            # Khóa dòng sản phẩm để tránh xung đột dữ liệu (Race Condition) khi đặt hàng đồng thời
            product = Product.objects.select_for_update().get(id=int(item['product_id']))
            qty = int(item['quantity'])

            if product.stock < qty:
                raise ValueError(f"Sản phẩm {product.name} không đủ tồn kho (Còn: {product.stock})")

            # Áp dụng FIFO để trừ tồn kho từ các lô và tính tổng giá vốn (COGS)
            total_cogs = OrderService.consume_stock_fifo(product, qty)
            avg_import_price = total_cogs / Decimal(qty) if qty > 0 else Decimal(0)

            item_total = product.price * qty
            total_price += item_total

            order_items_data.append({
                'product': product,
                'quantity': qty,
                'price': product.price,
                'import_price': avg_import_price,  # Lưu giá vốn bình quân gia quyền từ các lô FIFO
            })

        # Tạo bản ghi Đơn hàng chính (Order)
        order = Order.objects.create(
            user=user,
            full_name=customer_name,
            phone=customer_phone,
            address=shipping_address,
            total_price=total_price,
            status='pending',  # Trạng thái chờ xử lý cho đơn web
            order_type='web'  # Phân biệt loại đơn hàng nếu cần
        )

        # Cập nhật tồn kho tổng của Product và tạo các chi tiết đơn hàng (OrderItem)
        for it in order_items_data:
            product = it['product']

            OrderItem.objects.create(
                order=order,
                product=product,
                quantity=it['quantity'],
                price=it['price'],
                import_price=it['import_price']
            )

        return order
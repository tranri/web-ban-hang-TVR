from django.contrib import admin
from .models import Category, Product, ShopConfiguration, BannerImage, DocumentPost, Order, OrderItem, Customer
from django import forms
from django.utils.html import format_html
from django.urls import reverse, path
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages
from django.db.models import Prefetch
from django.utils import timezone
from django.db import transaction
from datetime import timedelta
from django.utils.safestring import mark_safe
from decimal import ROUND_HALF_UP, Decimal
from django.http import HttpResponse
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.core.exceptions import ValidationError as AdminValidationError


class BannerImageInline(admin.TabularInline):
    model = BannerImage
    extra = 1


@admin.register(ShopConfiguration)
class ShopConfigurationAdmin(admin.ModelAdmin):
    list_display = ['title', 'phone', 'email']
    inlines = [BannerImageInline]

    def has_add_permission(self, request):
        if ShopConfiguration.objects.exists():
            return False
        return True


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('parent')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'code', 'price', 'sale_price_display', 'import_price_display',
        'stock_display', 'new_import_price', 'new_stock', 'action_button',
        'defective_quantity', 'subtract_defective_button',
        'tax_rate', 'after_tax_profit_display'
    ]
    list_editable = ['code', 'price', 'new_import_price', 'new_stock', 'tax_rate', 'defective_quantity']
    readonly_fields = ['import_price', 'stock', 'sale_price']
    list_filter = ['category']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    list_per_page = 50

    @admin.display(description=mark_safe("Giá Nhập<br>(VNĐ)"))
    def import_price_display(self, obj):
        return f"{obj.import_price:,.0f}".replace(",", ".")

    @admin.display(description=mark_safe("Giá Bán Cũ<br>(VNĐ)"))
    def sale_price_display(self, obj):
        return f"{obj.sale_price:,.0f}".replace(",", ".")

    @admin.display(description=mark_safe("Số Lượng<br>Tồn Kho"))
    def stock_display(self, obj):
        return f"{obj.stock:,.0f}".replace(",", ".")

    class Media:
        css = {
            'all': ('admin/css/product_admin.css',)
        }

    def after_tax_profit_display(self, obj):
        """Display after-tax profit: Selling price - Purchase price - (Selling price * tax%)"""
        if obj.price and obj.import_price and obj.price > 0:
            tax_amount = obj.price * (obj.tax_rate / 100)
            profit = obj.price - obj.import_price - tax_amount
            profit_int = int(profit)

            # Tính phần trăm
            percentage = (profit / obj.price) * 100
            # Tạo chuỗi phần trăm trước để tránh lỗi định dạng trong format_html
            percentage_str = f"{percentage:.1f}%"

            # Color code: green for positive, red for negative
            color = "#51cf66" if profit_int >= 0 else "#ff6b6b"

            profit_str = f"{profit_int:,}đ".replace(",", ".")

            # Truyền chuỗi đã định dạng sẵn vào format_html
            return format_html(
                '<span style="color: {}; font-weight: bold;">{} ({})</span>',
                color, profit_str, percentage_str
            )
        return "-"

    after_tax_profit_display.short_description = mark_safe("Lợi nhuận<br>gôp<br>sau thuế")

    def subtract_defective_button(self, obj):
        """Display subtract button for defective products"""
        url = reverse('admin:product_subtract_defective', args=[obj.pk])
        return format_html('<a class="button" href="{}">Trừ</a>', url)

    subtract_defective_button.short_description = mark_safe("TRỪ<br>HÀNG LỖI")

    def action_button(self, obj):
        url = reverse('admin:product_update_data', args=[obj.pk])
        return format_html('<a class="button" href="{}">CHUYỂN</a>', url)

    action_button.short_description = "Cập nhật"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<path:object_id>/update-data/', self.admin_site.admin_view(self.update_data_view),
                 name='product_update_data'),
            path('<path:object_id>/subtract-defective/', self.admin_site.admin_view(self.subtract_defective_view),
                 name='product_subtract_defective'),
        ]
        return custom_urls + urls

    def update_data_view(self, request, object_id):
        product = get_object_or_404(Product, pk=object_id)

        # Check if product stock is not zero
        if product.stock != 0:
            messages.error(request,
                           f"Không thể cập nhật: Tồn kho của '{product.name}' đang là {product.stock}, phải bằng 0 mới được phép cập nhật!")
            return redirect('admin:shop_product_changelist')

        # NEW VALIDATION: Check if new_stock is non-zero
        if product.new_stock is None or product.new_stock == 0:
            messages.error(request,
                           f"Không thể cập nhật: Số lượng mới phải khác 0!")
            return redirect('admin:shop_product_changelist')

        # NEW VALIDATION: Check if new_import_price is non-zero
        if product.new_import_price is None or product.new_import_price == 0:
            messages.error(request,
                           f"Không thể cập nhật: Giá nhập mới phải khác 0!")
            return redirect('admin:shop_product_changelist')

        product.sale_price = product.price
        if product.new_import_price and product.new_import_price > 0:
            product.import_price = product.new_import_price
            product.new_import_price = 0

        product.stock = product.new_stock if product.new_stock is not None else 0
        product.new_stock = 0

        product.save()
        messages.success(request, f"Đã cập nhật thành công sản phẩm: {product.name}")

        return redirect('admin:shop_product_changelist')

    def subtract_defective_view(self, request, object_id):
        """Handle subtracting defective quantity from inventory"""
        product = get_object_or_404(Product, pk=object_id)
        defective_qty = product.defective_quantity if product.defective_quantity else 0

        # Check if defective_quantity is greater than 0
        if defective_qty == 0:
            messages.error(request,
                           f"Không thể trừ hàng lỗi: Số lượng hàng lỗi của '{product.name}' phải lớn hơn 0!")
            return redirect('admin:shop_product_changelist')

        # Check if stock is sufficient
        if product.stock < defective_qty:
            messages.error(request,
                           f"Không thể trừ hàng lỗi: Tồn kho của '{product.name}' là {product.stock}, nhỏ hơn số lượng hàng lỗi {defective_qty}!")
            return redirect('admin:shop_product_changelist')

        try:
            with transaction.atomic():
                # Subtract defective quantity from stock
                product.stock -= defective_qty
                # Reset defective_quantity to 0
                product.defective_quantity = 0
                product.save()

                messages.success(request,
                                 f"Đã trừ thành công {defective_qty} sản phẩm lỗi của '{product.name}'. Tồn kho hiện tại: {product.stock}")
        except Exception as e:
            messages.error(request, f"Lỗi khi trừ hàng lỗi: {str(e)}")

        return redirect('admin:shop_product_changelist')

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)

        def clean_price(self):
            price = self.cleaned_data.get("price")
            if price is not None and price < 1000:
                raise forms.ValidationError("Giá bán sản phẩm phải lớn hơn 1000 VNĐ!")
            return price

        form.clean_price = clean_price
        return form

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('category')


@admin.register(DocumentPost)
class DocumentPostAdmin(admin.ModelAdmin):
    list_display = ['title', 'created_at']
    list_filter = ['created_at']
    search_fields = ['title', 'slug']
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ['created_at']


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ('product', 'quantity', 'price_display', 'returned_quantity', 'return_item_action')
    readonly_fields = ['product', 'quantity', 'price_display', 'return_item_action']
    can_delete = False

    @admin.display(description="Giá")
    def price_display(self, obj):
        if not obj.pk:
            return "-"
        base_price = obj.price or 0
        discount = obj.discount_per_unit or 0
        final_price = base_price - discount

        base_str = f"{base_price:,.0f}".replace(",", ".") + "đ"
        final_str = f"{final_price:,.0f}".replace(",", ".") + "đ"

        if discount > 0:
            return format_html(
                '<span style="text-decoration: line-through; color: #6c757d;">{}</span> <span style="margin: 0 4px; color: #6c757d;">→</span> <span style="color: #dc3545; font-weight: bold;">{}</span>',
                base_str, final_str
            )
        return base_str

    @admin.display(description="Thao tác trả hàng")
    def return_item_action(self, obj):
        if obj.pk:
            url = reverse('admin:order_item_return_action', args=[obj.pk])
            return format_html(
                '''
                <a class="button" href="#" style="background: #ba2121; color: white; padding: 4px 10px; border-radius: 4px; text-decoration: none;"
                   onclick="var tr = this.closest('tr');
                            var input = tr.querySelector('input[name$=&quot;returned_quantity&quot;]');
                            var qty = input ? input.value : 0;
                            window.location.href = '{}?qty=' + encodeURIComponent(qty);
                            return false;">Trả hàng</a>
                ''',
                url
            )
        return "Lưu trước khi thao tác"


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'full_name',
        'phone',
        'final_price_display',  # total after redeemed points
        'created_at_display',
        'order_status',
        'points_display',
        'points_status_display',
        'print_status_display',  # Đã có trong list_display
        'order_actions'
    ]
    list_filter = ['created_at', 'is_printed', 'full_name', 'points_awarded']
    search_fields = ['full_name', 'phone', 'id']
    readonly_fields = ['created_at', 'total_price', 'id', 'printed_at']
    inlines = [OrderItemInline]
    list_per_page = 50
    date_hierarchy = 'created_at'

    @admin.display(description="Ngày có đơn hàng")
    def created_at_display(self, obj):
        if not getattr(obj, 'created_at', None):
            return "-"
        try:
            local_dt = timezone.localtime(obj.created_at)
            return local_dt.strftime("%H:%M %d/%m/%Y")
        except Exception:
            return str(obj.created_at)

    def order_status(self, obj):
        now = timezone.now()
        time_diff = now - obj.created_at
        limit = Order.ORDER_DURATION

        if time_diff < limit:
            remaining_days = (limit - time_diff).days + 1
            status = f"Còn {remaining_days} ngày"
            color = "#ffc107"  # Yellow
        else:
            status = "Hoàn thành"
            color = "#51cf66"  # Green

        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, status)

    order_status.short_description = "Đang Xử Lý"

    @admin.display(description="Trạng thái in")
    def print_status_display(self, obj):
        """Hiển thị nhãn trạng thái đã in hoặc chưa in kèm thời gian in (nếu có)"""
        if getattr(obj, 'is_printed', False):
            time_str = obj.printed_at.strftime('%H:%M %d/%m/%Y') if obj.printed_at else ""
            return format_html(
                '<span style="color: #fff; background-color: #2b8a3e; padding: 4px 8px; border-radius: 3px; font-weight: bold;" title="In lúc: {}">✓ Đã in</span>',
                time_str
            )
        else:
            # Sửa thành mark_safe ở đây vì chuỗi HTML này tĩnh, không có biến truyền vào
            return mark_safe(
                '<span style="color: #fff; background-color: #adb5bd; padding: 4px 8px; border-radius: 3px; font-weight: bold;">Chưa in</span>'
            )

    @admin.display(description="Điểm cộng")
    def points_display(self, obj):
        """Show points of the order with status indicator"""
        points = obj.awarded_points if (obj.awarded_points and obj.awarded_points > 0) else obj.calculate_points()
        if points > 0:
            if getattr(obj, 'points_awarded', False):
                return format_html(
                    '<span style="color: #2b8a3e; font-weight: bold; background-color: #e8f5e9; padding: 4px 8px; border-radius: 3px;">✓ {} điểm</span>',
                    points
                )
            else:
                return format_html(
                    '<span style="color: #d97706; font-weight: bold; background-color: #fef3c7; padding: 4px 8px; border-radius: 3px;">x {} điểm</span>',
                    points
                )
        return "-"

    @admin.display(description="Trạng thái điểm")
    def points_status_display(self, obj):
        """Show current status of points"""
        if obj.points_awarded:
            return mark_safe(
                '<span style="color: #fff; background-color: #51cf66; padding: 4px 8px; border-radius: 3px; font-weight: bold;">✓ Đã cộng</span>'
            )
        elif obj.is_eligible_for_points():
            return mark_safe(
                '<span style="color: #fff; background-color: #ff9800; padding: 4px 8px; border-radius: 3px; font-weight: bold;">⚠ Sẵn sàng</span>'
            )
        else:
            pending_points = obj.calculate_points()
            return format_html(
                '<span style="color: #fff; background-color: #ffc107; padding: 4px 8px; border-radius: 3px; font-weight: bold;">⏳ Chờ {}</span>',
                pending_points
            )

    def order_actions(self, obj):
        """Hiển thị các nút thao tác: In đơn hàng và Hoàn trả"""
        now = timezone.now()
        time_diff = now - obj.created_at

        print_url = reverse('admin:order_print_action', args=[obj.pk])
        print_btn = f'<a class="button" href="{print_url}" target="_blank" style="background: #417690; color: white; margin-right: 4px; padding: 4px 10px; border-radius: 4px; text-decoration: none;">In đơn</a>'

        if time_diff < Order.ORDER_DURATION:
            return_url = reverse('admin:order_return_action', args=[obj.pk])
            return_btn = f'<a class="button" href="{return_url}" style="background: #ba2121; color: white; padding: 4px 10px; border-radius: 4px; text-decoration: none;">Hoàn trả</a>'
            return format_html('{} {}', mark_safe(print_btn), mark_safe(return_btn))
        else:
            return format_html('{}', mark_safe(print_btn))

    order_actions.short_description = "Hành động"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<path:object_id>/return-action/', self.admin_site.admin_view(self.return_action_view),
                 name='order_return_action'),
            path('<path:object_id>/print/', self.admin_site.admin_view(self.print_order_view),
                 name='order_print_action'),
            path('order-item/<path:item_id>/return/', self.admin_site.admin_view(self.return_order_item_view),
                 name='order_item_return_action'),
        ]
        return custom_urls + urls

    def print_order_view(self, request, object_id):
        """View xử lý giao diện trang in hóa đơn gói hàng"""
        order = get_object_or_404(Order, pk=object_id)
        if not order.is_printed:
            order.is_printed = True
            order.printed_at = timezone.now()
            order.save(update_fields=['is_printed', 'printed_at'])

        config = ShopConfiguration.get_config()
        items = order.items.select_related('product').all()

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>In đơn hàng #{order.id}</title>
            <style>
                body {{ font-family: Arial, sans-serif; font-size: 14px; color: #333; margin: 0; padding: 20px; }}
                .invoice-box {{ max-width: 750px; margin: auto; padding: 25px; border: 1px solid #ddd; background: #fff; }}
                .header {{ text-align: center; margin-bottom: 20px; border-bottom: 2px solid #eee; padding-bottom: 15px; }}
                .header h2 {{ margin: 0; color: #2c3e50; font-size: 22px; }}
                .header p {{ margin: 5px 0; color: #555; font-size: 13px; }}
                .info-section {{ margin-bottom: 20px; font-size: 14px; }}
                .info-section table {{ width: 100%; border-collapse: collapse; }}
                .info-section td {{ padding: 6px; vertical-align: top; }}
                table.items-table {{ width: 100%; border-collapse: collapse; margin-top: 15px; }}
                table.items-table th, table.items-table td {{ border: 1px solid #ccc; padding: 8px 10px; text-align: left; font-size: 13px; }}
                table.items-table th {{ background-color: #f1f1f1; }}
                .text-right {{ text-align: right; }}
                .totals {{ margin-top: 15px; float: right; width: 320px; }}
                .totals table {{ width: 100%; border-collapse: collapse; }}
                .totals td {{ padding: 6px; font-size: 14px; }}
                .print-btn {{ text-align: center; margin-top: 40px; clear: both; }}
                .print-btn button {{ background: #417690; color: white; border: none; padding: 12px 25px; font-size: 16px; cursor: pointer; border-radius: 4px; font-weight: bold; }}
                .print-btn button:hover {{ background: #205067; }}
                @media print {{
                    .print-btn {{ display: none; }}
                    body {{ padding: 0; }}
                    .invoice-box {{ border: none; padding: 0; }}
                }}
            </style>
        </head>
        <body>
            <div class="invoice-box">
                <div class="header">
                    <h2>{config.title}</h2>
                    <p>Địa chỉ: {config.address} | Hotline: {config.phone}</p>
                    <h3 style="margin-top: 10px; margin-bottom: 5px; color: #333;">PHIẾU GIAO HÀNG / HÓA ĐƠN BÁN HÀNG</h3>
                    <p>Mã đơn hàng: <b>#{order.id}</b> | Ngày đặt: {order.created_at.strftime('%H:%M %d/%m/%Y')}</p>
                </div>

                <div class="info-section">
                    <table>
                        <tr>
                            <td style="width: 50%;">
                                <b>Khách hàng:</b> {order.full_name}<br>
                                <b>Số điện thoại:</b> {order.phone}<br>
                            </td>
                            <td>
                                <b>Địa chỉ nhận hàng:</b> {order.address}<br>
                                <b>Ghi chú đơn:</b> <span style="color: #d9534f;">{order.note or 'Không có'}</span>
                            </td>
                        </tr>
                    </table>
                </div>

                <table class="items-table">
                    <thead>
                        <tr>
                            <th style="width: 40px; text-align: center;">STT</th>
                            <th>Tên sản phẩm</th>
                            <th style="width: 70px; text-align: center;">SL</th>
                            <th style="text-align: right;">Đơn giá</th>
                            <th style="text-align: right;">Thành tiền</th>
                        </tr>
                    </thead>
                    <tbody>
        """

        item_rows = ""
        for index, item in enumerate(items, 1):
            base_price = item.price or 0
            discount = item.discount_per_unit or 0
            unit_price = base_price - discount
            subtotal = unit_price * item.quantity
            price_str = f"{unit_price:,.0f}".replace(",", ".") + "đ"
            subtotal_str = f"{subtotal:,.0f}".replace(",", ".") + "đ"

            item_rows += f"""
                        <tr>
                            <td style="text-align: center;">{index}</td>
                            <td>{item.product.name if item.product else 'Sản phẩm'}</td>
                            <td style="text-align: center;">{item.quantity}</td>
                            <td style="text-align: right;">{price_str}</td>
                            <td style="text-align: right;">{subtotal_str}</td>
                        </tr>
            """

        html_content += item_rows

        final_price_str = f"{order.final_price:,.0f}".replace(",", ".") + "đ"

        html_content += f"""
                    </tbody>
                </table>

                <div style="clear: both;"></div>

                <div class="totals">
                    <table>                        
                        <tr style="border-top: 2px solid #333;">
                            <td><b>Thanh Toán:</b></td>
                            <td class="text-right" style="font-size: 16px; color: #d9534f;"><b>{final_price_str}</b></td>
                        </tr>
                    </table>
                </div>

                <div style="clear: both;"></div>

                <div class="print-btn">
                    <button onclick="window.print();">🖨️ In Hóa Đơn Ngay</button>
                </div>
            </div>
        </body>
        </html>
        """
        return HttpResponse(html_content)

    def return_order_item_view(self, request, item_id):
        order_item = get_object_or_404(OrderItem.objects.select_related('order', 'product'), pk=item_id)
        order = order_item.order

        now = timezone.now()
        time_diff = now - order.created_at
        if time_diff >= Order.ORDER_DURATION:
            messages.error(request, f"Không thể trả hàng: Đơn hàng '{order.id}' đã quá hạn 5 ngày.")
            return redirect(reverse('admin:shop_order_change', args=[order.pk]))

        try:
            returned_qty = int(request.GET.get('qty', 0))
        except (ValueError, TypeError):
            returned_qty = 0

        if returned_qty <= 0:
            messages.error(request, "Vui lòng nhập số lượng trả hàng lớn hơn 0!")
            return redirect(reverse('admin:shop_order_change', args=[order.pk]))

        if returned_qty > order_item.quantity:
            messages.error(request, f"Số lượng trả hàng không được lớn hơn số lượng đặt!")
            return redirect(reverse('admin:shop_order_change', args=[order.pk]))

        try:
            with transaction.atomic():
                product = order_item.product
                base_price = order_item.price or 0
                discount_per_unit = order_item.discount_per_unit or 0
                final_unit_price = base_price - discount_per_unit

                product.stock += returned_qty
                product.save()

                refund_total_amount = base_price * returned_qty
                refund_final_amount = final_unit_price * returned_qty
                refund_points_deduct = discount_per_unit * returned_qty

                order.total_price = max(Decimal(0), order.total_price - refund_total_amount)
                order.final_price = max(Decimal(0), order.final_price - refund_final_amount)

                if order.applied_points > 0 and refund_points_deduct > 0:
                    points_to_refund = int(refund_points_deduct)
                    order.applied_points = max(0, order.applied_points - points_to_refund)

                    clean_phone = str(order.phone).strip() if order.phone else ""
                    if clean_phone:
                        customer = Customer.objects.filter(phone=clean_phone).first()
                        if customer:
                            customer.points += points_to_refund
                            customer.save(update_fields=['points'])

                amount_for_points = order.final_price if order.final_price > 0 else order.total_price
                order.awarded_points = int(amount_for_points * Decimal('0.01'))
                order.save()

                if returned_qty == order_item.quantity:
                    order_item.delete()
                else:
                    order_item.quantity -= returned_qty
                    order_item.returned_quantity = 0
                    order_item.save()

                messages.success(request, f"Đã xử lý trả thành công {returned_qty} sản phẩm.")
        except Exception as e:
            messages.error(request, f"Lỗi khi xử lý trả hàng: {str(e)}")

        return redirect(reverse('admin:shop_order_change', args=[order.pk]))

    def return_action_view(self, request, object_id):
        order = get_object_or_404(Order, pk=object_id)
        now = timezone.now()
        time_diff = now - order.created_at

        if time_diff >= Order.ORDER_DURATION:
            messages.error(request, f"Không thể hoàn trả: Đơn hàng đã quá hạn!")
            return redirect('admin:shop_order_changelist')

        try:
            with transaction.atomic():
                order_items = OrderItem.objects.filter(order=order).select_related('product')
                for order_item in order_items:
                    product = order_item.product
                    product.stock += order_item.quantity
                    product.save()

                clean_phone = str(order.phone).strip() if order.phone else ""
                if clean_phone:
                    customer = Customer.objects.filter(phone=clean_phone).first()
                    if customer:
                        if order.applied_points and order.applied_points > 0:
                            customer.points += order.applied_points

                        if getattr(order, 'points_awarded',
                                   False) and order.awarded_points and order.awarded_points > 0:
                            customer.points = max(0, customer.points - order.awarded_points)

                        customer.save(update_fields=['points'])

                order.delete()
                messages.success(request, f"Đã hoàn trả thành công đơn hàng #{object_id}.")
        except Exception as e:
            messages.error(request, f"Lỗi khi hoàn trả đơn hàng: {str(e)}")

        return redirect('admin:shop_order_changelist')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related(Prefetch('items', queryset=OrderItem.objects.select_related('product')))

    @admin.display(description="Thanh toán")
    def final_price_display(self, obj):
        if getattr(obj, 'final_price', None) is not None:
            try:
                return f"{obj.final_price:,.0f}".replace(",", ".")
            except Exception:
                return str(obj.final_price)
        return "-"


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'phone', 'created_at', 'customer_badge', 'points']
    list_filter = ['created_at', 'phone']
    search_fields = ['full_name', 'phone']
    ordering = ['-created_at']
    list_per_page = 100
    readonly_fields = ['password', 'created_at']
    date_hierarchy = 'created_at'

    def customer_badge(self, obj):
        return format_html(
            '<span style="background-color: #e3f2fd; padding: 3px 10px; border-radius: 3px; font-size: 12px;">{}</span>',
            f"ID: {obj.id}"
        )

    customer_badge.short_description = "Mã khách"


class SafeUserAdmin(DjangoUserAdmin):
    """Custom UserAdmin that prevents clearing the email for superusers."""

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)

        class _SafeForm(form):
            def clean(self_inner):
                cleaned = super().clean()
                email = cleaned.get('email', '')

                will_be_superuser = False
                if obj is not None and getattr(obj, 'is_superuser', False):
                    will_be_superuser = True
                if not will_be_superuser:
                    will_be_superuser = cleaned.get('is_superuser', False)

                if will_be_superuser and (email is None or str(email).strip() == ""):
                    raise AdminValidationError("Cannot clear email address of a superuser.")

                return cleaned

        return _SafeForm


try:
    admin.site.unregister(User)
except Exception:
    pass
admin.site.register(User, SafeUserAdmin)

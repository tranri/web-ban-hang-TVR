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
        'name', 'price', 'import_price', 'sale_price',
        'stock', 'new_import_price', 'new_stock',
        'tax_rate', 'after_tax_profit_display', 'action_button'
    ]
    list_editable = ['price', 'new_import_price', 'new_stock', 'tax_rate']
    readonly_fields = ['import_price', 'stock', 'sale_price']
    list_filter = ['category']
    search_fields = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)}
    list_per_page = 50

    def after_tax_profit_display(self, obj):
        """Display after-tax profit: Selling price - Purchase price - (Selling price * tax%)"""
        if obj.price and obj.import_price:
            tax_amount = obj.price * (obj.tax_rate / 100)
            profit = obj.price - obj.import_price - tax_amount
            profit_int = int(profit)

            # Color code: green for positive, red for negative
            if profit_int >= 0:
                color = "#51cf66"  # Green
            else:
                color = "#ff6b6b"  # Red

            profit_str = f"{profit_int:,}đ".replace(",", ".")
            return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, profit_str)
        return "-"

    after_tax_profit_display.short_description = "Lợi nhuận sau thuế (VNĐ)"

    def action_button(self, obj):
        url = reverse('admin:product_update_data', args=[obj.pk])
        return format_html('<a class="button" href="{}">Cập nhật</a>', url)

    action_button.short_description = "Hành động"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<path:object_id>/update-data/', self.admin_site.admin_view(self.update_data_view),
                 name='product_update_data'),
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
    readonly_fields = ['product', 'quantity', 'price']
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'full_name', 'phone', 'total_price', 'created_at', 'order_status', 'order_actions']
    list_filter = ['created_at', 'full_name']
    search_fields = ['full_name', 'phone', 'id']
    readonly_fields = ['created_at', 'total_price', 'id']
    inlines = [OrderItemInline]
    list_per_page = 50
    date_hierarchy = 'created_at'

    def order_status(self, obj):
        now = timezone.now()
        time_diff = now - obj.created_at

        if time_diff < timedelta(days=7):
            status = "Đang xử lý"
            color = "#ffc107"  # Yellow
        else:
            status = "Hoàn thành"
            color = "#51cf66"  # Green

        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, status)

    order_status.short_description = "Trạng thái"

    def order_actions(self, obj):
        """Display action buttons for the order"""
        now = timezone.now()
        time_diff = now - obj.created_at

        # Only show return button if order status is "Đang xử lý" (less than 7 days)
        if time_diff < timedelta(days=7):
            url = reverse('admin:order_return_action', args=[obj.pk])
            return format_html('<a class="button" href="{}">Hoàn trả</a>', url)
        else:
            return "-"

    order_actions.short_description = "Hành động"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<path:object_id>/return-action/', self.admin_site.admin_view(self.return_action_view),
                 name='order_return_action'),
        ]
        return custom_urls + urls

    def return_action_view(self, request, object_id):
        """Handle order return: restore product quantities and delete the order"""
        order = get_object_or_404(Order, pk=object_id)
        now = timezone.now()
        time_diff = now - order.created_at

        # Check if order status is "Đang xử lý" (less than 7 days)
        if time_diff >= timedelta(days=7):
            messages.error(request,
                           f"Không thể hoàn trả: Đơn hàng '{order.id}' đã hoàn thành và không thể hoàn trả!")
            return redirect('admin:shop_order_changelist')

        try:
            with transaction.atomic():
                # Get all order items
                order_items = OrderItem.objects.filter(order=order).select_related('product')

                # Restore product quantities
                for order_item in order_items:
                    product = order_item.product
                    product.stock += order_item.quantity
                    product.save()

                # Delete the order (order items will be deleted automatically due to CASCADE)
                order.delete()

                messages.success(request,
                                 f"Đã hoàn trả thành công đơn hàng #{object_id}. Số lượng sản phẩm đã được khôi phục.")
        except Exception as e:
            messages.error(request, f"Lỗi khi hoàn trả đơn hàng: {str(e)}")

        return redirect('admin:shop_order_changelist')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.prefetch_related(Prefetch('items', queryset=OrderItem.objects.select_related('product')))


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ['full_name', 'phone', 'created_at', 'customer_badge']
    list_filter = ['created_at', 'phone']
    search_fields = ['full_name', 'phone']  # removed 'email'
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

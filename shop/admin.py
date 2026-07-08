from django.contrib import admin
from .models import Category, Product, ShopConfiguration, BannerImage, DocumentPost, Order, OrderItem, Customer
from django import forms
from django.utils.html import format_html
from django.urls import reverse, path
from django.shortcuts import get_object_or_404, redirect
from django.contrib import messages


# Cho phép thêm ảnh Banner trực tiếp trong trang cấu hình Website
class BannerImageInline(admin.TabularInline):
    model = BannerImage
    extra = 1  # Hiển thị sẵn ô để thêm ảnh mới


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

    # ✅ IMPROVED - Optimize queries
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Prefetch parent categories to avoid N+1 queries
        return qs.select_related('parent')


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    # Không còn CSS ẩn nút lưu nữa

    list_display = [
        'name', 'price', 'import_price', 'sale_price',
        'stock', 'new_import_price', 'new_stock',
        'available', 'action_button'
    ]

    # Đã loại bỏ 'sale_price' khỏi list_editable để không thể sửa ở giao diện danh sách
    list_editable = [
        'price', 'new_import_price', 'new_stock', 'available'
    ]

    # Đã thêm 'sale_price' vào readonly_fields để khóa không cho nhập liệu thủ công
    readonly_fields = ['import_price', 'stock', 'sale_price']

    list_filter = ['available', 'category']
    search_fields = ['name', 'slug']  # ✅ IMPROVED - Add search for better usability
    prepopulated_fields = {'slug': ('name',)}

    # ✅ IMPROVED - Add pagination control
    list_per_page = 50

    # Nút cập nhật trong list view
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

    # LOGIC CẬP NHẬT: Giá chưa KM luôn được cập nhật theo Giá bán khi nhấn nút này
    def update_data_view(self, request, object_id):
        product = get_object_or_404(Product, pk=object_id)

        # 1. Kiểm tra tồn kho
        if product.stock != 0:
            messages.error(request,
                           f"Không thể cập nhật: Tồn kho của '{product.name}' đang là {product.stock}, phải bằng 0 mới được phép cập nhật!")
            return redirect('admin:shop_product_changelist')

        # 2. Thực hiện cập nhật
        # Giá chưa KM luôn lấy bằng giá bán hiện tại
        product.sale_price = product.price

        # Cập nhật giá nhập mới
        if product.new_import_price and product.new_import_price > 0:
            product.import_price = product.new_import_price
            product.new_import_price = 0

        # Cập nhật số lượng mới
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

    # ✅ IMPROVED - Optimize queries for list view
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Use select_related for ForeignKey (category)
        return qs.select_related('category')


# Đăng ký trang quản lý bài viết Góc tài liệu
@admin.register(DocumentPost)
class DocumentPostAdmin(admin.ModelAdmin):
    list_display = ['title', 'created_at']
    list_filter = ['created_at']  # ✅ IMPROVED - Add date filter
    search_fields = ['title', 'slug']  # ✅ IMPROVED - Add search
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = ['created_at']  # ✅ IMPROVED - Protect system fields


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    # ✅ IMPROVED - Make OrderItem readonly in inline to prevent accidental edits
    readonly_fields = ['product', 'quantity', 'price']
    can_delete = False  # Prevent deletion from inline


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['id', 'full_name', 'phone', 'total_price', 'created_at', 'order_status']
    list_filter = ['created_at', 'full_name']  # ✅ IMPROVED - Better filtering
    search_fields = ['full_name', 'phone', 'id']  # ✅ IMPROVED - Search by order ID too
    readonly_fields = ['created_at', 'total_price', 'id']  # ✅ IMPROVED - Protect important fields
    inlines = [OrderItemInline]

    # ✅ IMPROVED - Better display of large order lists
    list_per_page = 50
    date_hierarchy = 'created_at'  # ✅ IMPROVED - Add date navigation

    # ✅ IMPROVED - Show order status indicator
    def order_status(self, obj):
        """Display order status with color coding"""
        if obj.total_price == 0:
            status = "Chưa thanh toán"
            color = "#ff6b6b"  # Red
        else:
            status = "Đã thanh toán"
            color = "#51cf66"  # Green
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            status
        )

    order_status.short_description = "Trạng thái"

    # ✅ IMPROVED - Optimize queries with select_related
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Don't join customer as it might not exist, but prefetch OrderItems for inline
        return qs.prefetch_related('orderitem_set')


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    # Hiển thị thông tin trong bảng danh sách
    list_display = ['full_name', 'phone', 'created_at', 'customer_badge']

    # ✅ IMPROVED - Better filtering and search
    list_filter = ['created_at', 'phone']
    search_fields = ['full_name', 'phone', 'email']  # ✅ IMPROVED - Search by email too

    # Sắp xếp theo ngày tạo mới nhất
    ordering = ['-created_at']

    # ✅ IMPROVED - Better pagination for large customer lists
    list_per_page = 100

    # Chặn không cho sửa mật khẩu trực tiếp (bảo mật)
    readonly_fields = ['password', 'created_at']

    # ✅ IMPROVED - Add date hierarchy for easy browsing
    date_hierarchy = 'created_at'

    # ✅ IMPROVED - Show customer status badge
    def customer_badge(self, obj):
        """Display customer status"""
        return format_html(
            '<span style="background-color: #e3f2fd; padding: 3px 10px; border-radius: 3px; font-size: 12px;">{}</span>',
            f"ID: {obj.id}"
        )

    customer_badge.short_description = "Mã khách"

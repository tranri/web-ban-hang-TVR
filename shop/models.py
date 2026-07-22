from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.cache import cache
from decimal import Decimal
from django.utils import timezone
from datetime import timedelta
import re


## python manage.py makemigrations
## python manage.py migrate

def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    # Remove all non-digit characters except leading +
    cleaned = re.sub(r"[^\d+]", "", str(phone).strip())
    return cleaned


class Customer(models.Model):
    full_name = models.CharField(max_length=255, verbose_name="Họ tên")
    phone = models.CharField(max_length=20, unique=True, verbose_name="Số điện thoại")
    password = models.CharField(max_length=128, verbose_name="Mật khẩu")  # Sẽ lưu mật khẩu đã băm (hash)
    created_at = models.DateTimeField(auto_now_add=True)
    address = models.TextField(verbose_name="Địa chỉ", null=True, blank=True)
    points = models.IntegerField(default=0, verbose_name="Điểm")

    class Meta:
        verbose_name = "Tài Khoản Khách Hàng"
        verbose_name_plural = "Tài Khoản Khách Hàng"

    def set_password(self, raw_password):
        self.password = make_password(raw_password)

    def check_password(self, raw_password):
        return check_password(raw_password, self.password)

    def __str__(self):
        return f"{self.full_name} - {self.phone}"


class Category(models.Model):
    parent = models.ForeignKey('self', null=True, blank=True, related_name='children', on_delete=models.CASCADE,
                               verbose_name="Danh mục cha (Bỏ trống nếu là danh mục gốc)")
    name = models.CharField(max_length=200, verbose_name="Tên danh mục")
    slug = models.SlugField(max_length=200, unique=True, verbose_name="Đường dẫn (Slug)")
    description = models.TextField(blank=True, verbose_name="Mô tả danh mục")

    class Meta:
        ordering = ['name']
        verbose_name = 'Danh mục'
        verbose_name_plural = 'Các danh mục'

    def __str__(self):
        if self.parent:
            return f"{self.parent.name} --> {self.name}"
        return self.name


class Product(models.Model):
    category = models.ForeignKey(Category, related_name='products', on_delete=models.CASCADE, verbose_name="Danh mục")
    code = models.CharField(max_length=100, unique=True, verbose_name="Mã sản phẩm", null=True, blank=True)
    name = models.CharField(max_length=200, verbose_name="Tên sản phẩm")
    slug = models.SlugField(max_length=200, unique=True, verbose_name="Đường dẫn (Slug)")
    image = models.ImageField(upload_to="products/%Y/%m/%d", blank=True, null=True, verbose_name="Hình ảnh")
    description = models.TextField(blank=True, verbose_name="Mô tả chi tiết/Thông số")
    datasheet_url = models.URLField(blank=True, verbose_name="Link Tài liệu (Datasheet)")

    price = models.DecimalField(max_digits=10, decimal_places=0, default=0, verbose_name="Giá Bán (VNĐ)")
    import_price = models.DecimalField(max_digits=10, decimal_places=0, default=0, verbose_name="Giá Nhập (VNĐ)")
    sale_price = models.DecimalField(max_digits=10, decimal_places=0, default=0, verbose_name="Giá Bán Cũ (VNĐ)")
    stock = models.IntegerField(default=0, verbose_name="Số Lượng Tồn Kho")

    new_import_price = models.DecimalField(max_digits=10, decimal_places=0, default=0, blank=True, null=True,
                                           verbose_name="Giá Nhập Mới (VNĐ)")
    new_stock = models.IntegerField(default=0, blank=True, null=True, verbose_name="Số Lượng Mới")

    tax_rate = models.DecimalField(max_digits=5, decimal_places=1, default=0, verbose_name="Thuế (%)")
    defective_quantity = models.IntegerField(default=0, blank=True, null=True, verbose_name="Số lượng hàng lỗi")

    class Meta:
        ordering = ['name']
        verbose_name = 'Sản phẩm'
        verbose_name_plural = 'Các sản phẩm'

    def __str__(self):
        return self.name

    @property
    def discount_percentage(self):
        if self.sale_price > self.price and self.sale_price > 0:
            discount = self.sale_price - self.price
            return int((discount / self.price) * 100)
        return 0

    @property
    def after_tax_profit(self):
        if self.price and self.import_price:
            tax_amount = self.price * (self.tax_rate / 100)
            profit = self.price - self.import_price - tax_amount
            return int(profit)
        return 0


class ShopConfiguration(models.Model):
    title = models.CharField(max_length=200, default="Điện Tử TVR", verbose_name="Tên cửa hàng")
    logo = models.ImageField(upload_to="logo/", blank=True, null=True, verbose_name="Logo website")
    banner_text_fallback = models.CharField(max_length=255,
                                            default="🚀 COMBO LINH KIỆN ĐỒ ÁN TỐT NGHIỆP GIẢM 10% - CUNG CẤP LINH KIỆN GIÁ SINH VIÊN",
                                            verbose_name="Chữ thay thế (nếu không có ảnh)")
    address = models.CharField(max_length=255, default="Hòa Khánh Bắc, Quận Liên Chiểu, Thành phố Đà Nẵng",
                               verbose_name="Địa chỉ cửa hàng")
    working_time = models.CharField(max_length=255,
                                    default="7:30-11:30; 13:30-17:30 | Thứ 7, chủ nhật: 08:30-11:30; 14:30-17:30",
                                    verbose_name="Thời gian làm việc")
    phone = models.CharField(max_length=15, default="0705 296 182", verbose_name="Số điện thoại Hotline")
    email = models.EmailField(default="contact.dientutvr@gmail.com", verbose_name="Email cửa hàng")
    zalo_phone = models.CharField(max_length=15, default="0705296182", verbose_name="SĐT nhận chat Zalo (Viết liền số)")
    messenger_url = models.URLField(default="https://m.me/dientutvr", verbose_name="Link Chat Messenger FB")
    map_embed_url = models.TextField(default="", verbose_name="Mã nhúng bản đồ Iframe")
    service_image = models.ImageField(upload_to="services/", blank=True, null=True,
                                      verbose_name="Ảnh mục Thiết kế Đồ Án")
    service_video = models.FileField(upload_to="services/videos/", blank=True, null=True,
                                     verbose_name="Video giới thiệu (Tải từ máy)")

    hkd_name = models.CharField(max_length=255, default="HKD Điện tử Nguyễn Hiền", verbose_name="Tên Hộ Kinh Doanh")
    registration_number = models.CharField(max_length=100, default="8426840468-001", verbose_name="Số GPĐKKD")
    registration_place = models.CharField(max_length=150, default="UBND Quận Liên Chiểu", verbose_name="Nơi cấp GPĐKKD")
    registration_date = models.DateField(null=True, blank=True, verbose_name="Ngày cấp GPĐKKD")

    class Meta:
        verbose_name = "Cấu hình Website"
        verbose_name_plural = "Cấu hình Website"

    def __str__(self):
        return self.title

    @staticmethod
    def get_config():
        config = cache.get('shop_config')
        if config is None:
            config = ShopConfiguration.objects.first()
            if not config:
                config = ShopConfiguration.objects.create()
            cache.set('shop_config', config, 3600)
        return config

    @staticmethod
    def clear_cache():
        cache.delete('shop_config')


@receiver(post_save, sender=ShopConfiguration)
def clear_shop_config_cache(sender, instance, **kwargs):
    ShopConfiguration.clear_cache()


class BannerImage(models.Model):
    config = models.ForeignKey(ShopConfiguration, related_name='banners', on_delete=models.CASCADE)
    image = models.ImageField(upload_to="banners/", verbose_name="Tải ảnh Banner lên")
    alt_text = models.CharField(max_length=150, blank=True, verbose_name="Mô tả ảnh (SEO)")
    order = models.IntegerField(default=0, verbose_name="Thứ tự hiển thị")

    class Meta:
        ordering = ['order']
        verbose_name = "Ảnh Banner"
        verbose_name_plural = "Quản lý nhiều Banner ảnh"


class DocumentPost(models.Model):
    title = models.CharField(max_length=250, verbose_name="Tiêu đề tài liệu")
    slug = models.SlugField(max_length=250, unique=True, verbose_name="Đường dẫn (Slug)")
    summary = models.TextField(verbose_name="Tóm tắt ngắn")
    content = models.TextField(verbose_name="Nội dung chi tiết/Hướng dẫn/Mã code")
    file_url = models.URLField(blank=True, verbose_name="Link tải File đính kèm (nếu có)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Ngày đăng")

    class Meta:
        ordering = ['-created_at']
        verbose_name = "Bài viết tài liệu"
        verbose_name_plural = "Góc Tài liệu kỹ thuật"

    def __str__(self):
        return self.title


class Order(models.Model):
    # Thêm verbose_name vào các trường
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.SET_NULL, related_name='orders',
                                 verbose_name="Khách hàng")
    full_name = models.CharField(max_length=255, verbose_name="Họ và tên")
    phone = models.CharField(max_length=20, verbose_name="Số điện thoại")
    address = models.TextField(verbose_name="Địa chỉ")
    note = models.TextField(blank=True, null=True, verbose_name="Ghi chú")
    total_price = models.DecimalField(max_digits=12, decimal_places=0, verbose_name="Tổng tiền")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Ngày có đơn hàng")
    points_awarded = models.BooleanField(default=False, verbose_name="Đã cộng điểm")
    awarded_points = models.IntegerField(default=0, verbose_name="Số điểm đã cộng")

    class Meta:
        verbose_name = "Đơn hàng"
        verbose_name_plural = "Quản lý đơn hàng"

    def __str__(self):
        return f"Đơn hàng {self.id} - {self.full_name}"

    def calculate_points(self):
        try:
            total = Decimal(self.total_price)
        except Exception:
            total = Decimal(0)
        points = int(total * Decimal('0.01'))
        return points

    def is_completed(self):
        now = timezone.now()
        return (now - self.created_at) >= timedelta(seconds=5)  # days=5

    def is_eligible_for_points(self):
        return self.is_completed() and not self.points_awarded


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    # Thêm verbose_name cho từng trường
    product = models.ForeignKey('Product', on_delete=models.CASCADE, verbose_name="Sản phẩm")
    quantity = models.PositiveIntegerField(verbose_name="Số lượng")
    price = models.DecimalField(max_digits=12, decimal_places=0, verbose_name="Giá")

    class Meta:
        verbose_name = "Mục hàng"
        # Dòng này sẽ thay đổi tiêu đề "ORDER ITEMS" thành "Chi tiết đơn hàng"
        verbose_name_plural = "Chi tiết đơn hàng"

    def __str__(self):
        return f"{self.product.name} x {self.quantity}"

from django.db import models
from django.urls import reverse

class Category(models.Model):
    name = models.CharField(max_length=200, verbose_name="Tên danh mục")
    slug = models.SlugField(max_length=200, unique=True, verbose_name="Đường dẫn (Slug)")
    description = models.TextField(blank=True, verbose_name="Mô tả danh mục")

    class Meta:
        ordering = ['name']
        verbose_name = 'Danh mục'
        verbose_name_plural = 'Các danh mục'

    def __str__(self):
        return self.name


class Product(models.Model):
    category = models.ForeignKey(
        Category,
        related_name='products',
        on_delete=models.CASCADE,
        verbose_name="Danh mục"
    )
    name = models.CharField(max_length=200, verbose_name="Tên sản phẩm")
    slug = models.SlugField(max_length=200, unique=True, verbose_name="Đường dẫn (Slug)")
    image = models.ImageField(upload_to="products/%Y/%m/%d", blank=True, null=True, verbose_name="Hình ảnh")
    description = models.TextField(blank=True, verbose_name="Mô tả chi tiết/Thông số")
    datasheet_url = models.URLField(blank=True, verbose_name="Link Tài liệu (Datasheet)")
    price = models.DecimalField(max_length=10, max_digits=10, decimal_places=0, verbose_name="Giá bán (VNĐ)")
    stock = models.IntegerField(default=0, verbose_name="Số lượng tồn kho")
    available = models.BooleanField(default=True, verbose_name="Hiển thị/Bán")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Ngày tạo")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Ngày cập nhật")

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Sản phẩm'
        verbose_name_plural = 'Các sản phẩm'

    def __str__(self):
        return self.name
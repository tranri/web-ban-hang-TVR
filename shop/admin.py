from django.contrib import admin
from .models import Category, Product

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'slug']
    prepopulated_fields = {'slug': ('name',)} # Tự động điền slug khi bạn gõ tên danh mục


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'price', 'stock', 'available', 'created_at', 'updated_at']
    list_filter = ['available', 'created_at', 'updated_at', 'category']
    list_editable = ['price', 'stock', 'available'] # Cho phép sửa nhanh giá và kho ngay tại danh sách
    prepopulated_fields = {'slug': ('name',)} # Tự động điền slug khi bạn gõ tên sản phẩm
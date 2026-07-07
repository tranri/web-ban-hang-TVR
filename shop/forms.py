from django import forms
from .models import Order, Customer
import re


class OrderForm(forms.ModelForm):
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nhập email (nếu có)...'
        })
    )

    class Meta:
        model = Order
        fields = ['full_name', 'email', 'phone', 'address', 'note']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nhập họ tên...'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Nhập email...'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nhập số điện thoại...'}),
            'address': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Số nhà, đường, phường/xã...'}),
            'note': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Ghi chú thêm...'}),
        }

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if not phone.isdigit() or len(phone) < 10 or len(phone) > 11:
            raise forms.ValidationError("Số điện thoại không hợp lệ (Phải là 10-11 chữ số).")
        return phone

    # Kiểm tra các trường bắt buộc
    def clean_full_name(self):
        name = self.cleaned_data.get('full_name')
        if len(name) < 2:
            raise forms.ValidationError("Họ tên quá ngắn!")
        return name


class CustomerRegisterForm(forms.ModelForm):
    address = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-control', 'placeholder': 'Nhập địa chỉ nhận hàng...', 'rows': 2}),
        required=True,
        label="Địa chỉ"
    )

    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Mật khẩu...'}))

    website_check = forms.CharField(
        required=False,
        label="",  # Để trống nhãn
        widget=forms.TextInput(attrs={'class': 'd-none', 'autocomplete': 'off'})  # d-none là class ẩn của Bootstrap
    )

    class Meta:
        model = Customer
        # Đã xóa 'email' khỏi danh sách này
        fields = ['full_name', 'phone', 'address', 'password']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Họ tên...'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Số điện thoại...'}),
        }

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        # Kiểm tra chỉ chứa số và độ dài 10-11
        if not phone.isdigit() or len(phone) < 10 or len(phone) > 11:
            raise forms.ValidationError("Số điện thoại không hợp lệ (10-11 chữ số).")
        # Kiểm tra tồn tại
        if Customer.objects.filter(phone=phone).exists():
            raise forms.ValidationError("Số điện thoại này đã được đăng ký.")
        return phone

    def clean_website_check(self):
        data = self.cleaned_data.get('website_check')
        # Nếu bot điền gì đó vào đây, chặn lại ngay!
        if data:
            raise forms.ValidationError("Đã xảy ra lỗi hệ thống (Bot detected).")
        return data

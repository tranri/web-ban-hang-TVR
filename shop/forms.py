from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
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

    def clean_full_name(self):
        name = self.cleaned_data.get('full_name')
        if len(name) < 2:
            raise forms.ValidationError("Họ tên quá ngắn!")
        return name


class CustomerRegisterForm(forms.ModelForm):
    """Enhanced registration form with strong password validation"""

    address = forms.CharField(
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': 'Nhập địa chỉ nhận hàng...',
            'rows': 2
        }),
        required=True,
        label="Địa chỉ"
    )

    password = forms.CharField(
        label="Mật khẩu",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Mật khẩu...',
            'autocomplete': 'new-password'
        }),
        validators=[validate_password],
        help_text="Mật khẩu phải có ít nhất 8 ký tự, chứa chữ hoa, chữ thường, số và ký tự đặc biệt"
    )

    password_confirm = forms.CharField(
        label="Xác nhận mật khẩu",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Xác nhận mật khẩu...',
            'autocomplete': 'new-password'
        })
    )

    website_check = forms.CharField(
        required=False,
        label="",
        widget=forms.TextInput(attrs={
            'class': 'd-none',
            'autocomplete': 'off',
            'tabindex': '-1'
        })
    )

    class Meta:
        model = Customer
        fields = ['full_name', 'phone', 'address', 'password']
        widgets = {
            'full_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Họ tên...'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Số điện thoại...',
                'autocomplete': 'tel'
            }),
        }

    def clean_full_name(self):
        """Validate full name"""
        name = self.cleaned_data.get('full_name', '').strip()

        if len(name) < 2:
            raise forms.ValidationError("Họ tên phải có ít nhất 2 ký tự.")

        if len(name) > 255:
            raise forms.ValidationError("Họ tên quá dài (tối đa 255 ký tự).")

        # Check for special characters
        if not re.match(r"^[\w\s\-\u0100-\u01B0\u1EA0-\u1EFF]+$", name):
            raise forms.ValidationError("Họ tên chứa ký tự không hợp lệ.")

        return name

    def clean_phone(self):
        """Validate phone number"""
        phone = self.cleaned_data.get('phone', '').strip()

        # Check format
        if not phone.isdigit() or len(phone) < 10 or len(phone) > 11:
            raise forms.ValidationError("Số điện thoại không hợp lệ (phải là 10-11 chữ số).")

        # Check if already registered
        if Customer.objects.filter(phone=phone).exists():
            raise forms.ValidationError("Số điện thoại này đã được đăng ký.")

        return phone

    def clean_password_confirm(self):
        """Validate password confirmation matches"""
        password = self.cleaned_data.get('password')
        password_confirm = self.cleaned_data.get('password_confirm')

        if password and password_confirm:
            if password != password_confirm:
                raise forms.ValidationError("Mật khẩu không khớp!")

        return password_confirm

    def clean_website_check(self):
        """Bot detection honeypot"""
        data = self.cleaned_data.get('website_check', '').strip()
        if data:
            raise forms.ValidationError("Đã xảy ra lỗi hệ thống (Bot detected).")
        return data

    def clean(self):
        """Overall form validation"""
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')

        if password and password_confirm and password != password_confirm:
            self.add_error('password_confirm', 'Mật khẩu không khớp!')

        return cleaned_data


class CustomerLoginForm(forms.Form):
    """Enhanced login form with security measures"""

    phone = forms.CharField(
        label="Số điện thoại",
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Số điện thoại...',
            'autocomplete': 'tel',
            'type': 'tel'
        })
    )

    password = forms.CharField(
        label="Mật khẩu",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Mật khẩu...',
            'autocomplete': 'current-password'
        })
    )

    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '').strip()
        if not phone.isdigit() or len(phone) < 10 or len(phone) > 11:
            raise forms.ValidationError("Số điện thoại không hợp lệ.")
        return phone

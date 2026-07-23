from decimal import Decimal
from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from .models import Order, Customer
import re


class OrderForm(forms.ModelForm):
    applied_points = forms.IntegerField(
        required=False,
        min_value=0,
        label="Sử dụng điểm",
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Nhập số điểm muốn dùng (Ví dụ: 10000)',
            'step': 1000,
            'min': 0
        }),
        help_text="Tối thiểu 10.000 điểm. 1.000 điểm = 1.000 đ. (Chỉ áp dụng cho khách đã đăng nhập)"
    )

    class Meta:
        model = Order
        fields = ['full_name', 'phone', 'address', 'note', 'applied_points']
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nhập họ tên...'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nhập số điện thoại...'}),
            'address': forms.Textarea(
                attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Số nhà, đường, phường/xã...'}),
            'note': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Ghi chú thêm...'}),
        }

    def __init__(self, *args, customer: Customer = None, order_total: Decimal = None, **kwargs):
        """
        Accept 'customer' (Customer instance or None) and 'order_total' (Decimal) for contextual validation.
        """
        super().__init__(*args, **kwargs)
        self.customer = customer
        self.order_total = Decimal(order_total) if order_total is not None else None

        # If no logged-in customer, hide/disable applied_points input server-side by setting it not required
        if not self.customer:
            self.fields['applied_points'].required = False

    def clean_applied_points(self):
        applied = self.cleaned_data.get('applied_points') or 0
        if applied:
            # Minimum: 10,000 points
            if applied < 10000:
                raise ValidationError("Số điểm tối thiểu phải là 10.000 điểm.")

            # Must be multiple of 1,000
            if applied % 1000 != 0:
                raise ValidationError("Số điểm phải là bội số của 1.000.")

            # Customer must be logged in to use points
            if not self.customer:
                raise ValidationError("Chỉ khách đăng nhập mới có thể sử dụng điểm thưởng.")

            # Customer must have enough points
            if applied > (self.customer.points or 0):
                raise ValidationError("Bạn không có đủ điểm để sử dụng số điểm này.")

            # If order_total provided, ensure points do not exceed order total (1 point = 1 VND)
            if self.order_total is not None:
                if applied > int(self.order_total):
                    raise ValidationError("Không thể sử dụng nhiều điểm hơn tổng tiền đơn hàng.")
        return applied

    def clean(self):
        cleaned = super().clean()
        # Additional cross-field checks can go here
        return cleaned
    
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
        help_text="Mật khẩu phải có ít nhất 8 ký tự, chứa chữ thường, số và ký tự đặc biệt"
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
        name = self.cleaned_data.get('full_name', '').strip()

        if len(name) < 2:
            raise forms.ValidationError("Họ tên phải có ít nhất 2 ký tự.")

        if len(name) > 255:
            raise forms.ValidationError("Họ tên quá dài (tối đa 255 ký tự).")

        if not re.match(r"^[\w\s\-\u0100-\u01B0\u1EA0-\u1EFF]+$", name):
            raise forms.ValidationError("Họ tên chứa ký tự không hợp lệ.")

        return name

    def clean_phone(self):
        phone = self.cleaned_data.get('phone', '').strip()

        if not phone.isdigit() or len(phone) < 10 or len(phone) > 11:
            raise forms.ValidationError("Số điện thoại không hợp lệ (phải là 10-11 chữ số).")

        if Customer.objects.filter(phone=phone).exists():
            raise forms.ValidationError("Số điện thoại này đã được đăng ký.")

        return phone

    def clean_password_confirm(self):
        password = self.cleaned_data.get('password')
        password_confirm = self.cleaned_data.get('password_confirm')

        if password and password_confirm:
            if password != password_confirm:
                raise forms.ValidationError("Mật khẩu không khớp!")

        return password_confirm

    def clean_website_check(self):
        data = self.cleaned_data.get('website_check', '').strip()
        if data:
            raise forms.ValidationError("Đã xảy ra lỗi hệ thống (Bot detected).")
        return data

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')

        if password and password_confirm and password != password_confirm:
            self.add_error('password_confirm', 'Mật khẩu không khớp!')

        return cleaned_data


class CustomerLoginForm(forms.Form):
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


class UpdateAddressForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ['address']
        widgets = {
            'address': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Nhập địa chỉ của bạn...'
            }),
        }
        labels = {
            'address': 'Địa chỉ giao hàng'
        }


class ChangePasswordForm(forms.Form):
    old_password = forms.CharField(
        label="Mật khẩu cũ",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control password-input',
            'placeholder': 'Nhập mật khẩu cũ...',
            'autocomplete': 'current-password'
        })
    )

    new_password = forms.CharField(
        label="Mật khẩu mới",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control password-input',
            'placeholder': 'Nhập mật khẩu mới...',
            'autocomplete': 'new-password'
        }),
        validators=[validate_password],
        help_text="Mật khẩu phải có ít nhất 8 ký tự, chứa chữ thường, số và ký tự đặc biệt"
    )

    new_password_confirm = forms.CharField(
        label="Xác nhận mật khẩu mới",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control password-input',
            'placeholder': 'Xác nhận mật khẩu mới...',
            'autocomplete': 'new-password'
        })
    )

    def clean_new_password_confirm(self):
        new_password = self.cleaned_data.get('new_password')
        new_password_confirm = self.cleaned_data.get('new_password_confirm')

        if new_password and new_password_confirm:
            if new_password != new_password_confirm:
                raise forms.ValidationError("Mật khẩu mới không khớp!")

        return new_password_confirm

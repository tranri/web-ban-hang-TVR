import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from .models import Category, Product, ShopConfiguration, DocumentPost, Order, OrderItem, Customer
from datetime import timedelta
from django.utils import timezone
from django.db.models import Sum
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.hashers import make_password
import random, logging
from django.db import transaction
from .forms import OrderForm, CustomerRegisterForm, CustomerLoginForm, UpdateAddressForm, ChangePasswordForm
import requests
import threading
from django.conf import settings
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit
from django.views.decorators.cache import never_cache
from django.contrib.messages import get_messages
from django.contrib import messages as django_messages
from django.middleware.csrf import get_token
from decimal import Decimal

logger = logging.getLogger(__name__)


def get_shop_config():
    config = ShopConfiguration.objects.first()
    if not config:
        config = ShopConfiguration.objects.create()
    return config


def get_base_context(request=None, include_categories=True):
    context = {'config': get_shop_config()}

    if include_categories:
        context['categories'] = Category.objects.filter(parent__isnull=True).prefetch_related('children')

    if request:
        context['customer_id'] = request.session.get('customer_id')

    return context


def get_all_categories_context():
    return {'categories': Category.objects.all()}


def get_hierarchical_categories_context():
    return {'categories': Category.objects.filter(parent__isnull=True).prefetch_related('children')}


def build_render_context(request, template_name, **kwargs):
    context = get_base_context(request)
    context.update(kwargs)
    return context


# Session helpers for customer-only session data
CUSTOMER_SESSION_KEYS = ['customer_id', 'customer_name', 'customer_phone', 'customer_auth_hash']


def clear_customer_session(request):
    for k in CUSTOMER_SESSION_KEYS:
        request.session.pop(k, None)
    request.session.pop('cart', None)
    request.session.modified = True


# ✅ IMPROVED - Helper function to create and manage user session
def create_user_session(request, customer):
    try:
        request.session.cycle_key()
    except Exception:
        # Ensure a session exists if cycle_key is not available for some reason
        if not request.session.session_key:
            request.session.create()

    # Ensure CSRF token is fresh after session rotation
    try:
        get_token(request)
    except Exception:
        # If CSRF middleware isn't active, skip
        pass

    # Store customer info in safe, custom session keys (no _auth* keys!)
    request.session['customer_id'] = customer.id
    request.session['customer_name'] = customer.full_name
    request.session['customer_phone'] = customer.phone

    # Optional small hash to help verify the session belongs to this customer in application code
    request.session['customer_auth_hash'] = customer.password[:10]

    # Set session expiry for customer sessions (seconds)
    request.session.set_expiry(1800)  # 30 minutes

    logger.info(f"Session created for customer: {customer.phone}")


@never_cache
@require_http_methods(["GET", "POST"])
def tai_khoan(request):
    """Account page with tabs: Account Info, Orders, and Change Password"""
    customer_id = request.session.get('customer_id')

    if not customer_id:
        messages.warning(request, "Vui lòng đăng nhập để xem tài khoản.")
        return redirect('shop:dang_nhap')

    try:
        customer = Customer.objects.get(id=customer_id)

        # ✅ VERIFY SESSION INTEGRITY
        stored_phone = request.session.get('customer_phone')
        if stored_phone != customer.phone:
            # Session data mismatch - potential tampering
            logger.warning(f"Session integrity check failed for customer {customer_id}")
            # Clear only customer session keys instead of flushing the entire session
            clear_customer_session(request)
            messages.error(request, "Phiên làm việc không hợp lệ. Vui lòng đăng nhập lại.")
            return redirect('shop:dang_nhap')

        # Get the active tab from GET parameter (default: 'info')
        active_tab = request.GET.get('tab', 'info')

        # Initialize context
        context = build_render_context(request, 'shop/tai_khoan.html', customer=customer)
        context['active_tab'] = active_tab

        # Handle POST requests for different forms
        if request.method == 'POST':
            form_type = request.POST.get('form_type', '')

            # ✅ IMPROVED - Handle "Update Address" form submission
            if form_type == 'update_address':
                address_form = UpdateAddressForm(request.POST, instance=customer)
                if address_form.is_valid():
                    address_form.save()
                    messages.success(request, "Địa chỉ đã được cập nhật thành công!")
                    logger.info(f"Address updated for customer: {customer.phone}")
                    return redirect('shop:tai_khoan')
                else:
                    context['address_form'] = address_form
                    context['active_tab'] = 'info'

            # ✅ IMPROVED - Handle "Change Password" form submission
            elif form_type == 'change_password':
                password_form = ChangePasswordForm(request.POST)
                if password_form.is_valid():
                    old_password = password_form.cleaned_data['old_password']
                    new_password = password_form.cleaned_data['new_password']

                    # Verify old password
                    if not customer.check_password(old_password):
                        messages.error(request, "Mật khẩu cũ không chính xác!")
                        logger.warning(f"Failed password change attempt for customer: {customer.phone}")
                        context['password_form'] = password_form
                        context['active_tab'] = 'password'
                    else:
                        # Update password
                        customer.set_password(new_password)
                        customer.save()

                        # Refresh session with new password hash
                        request.session['_auth_user_hash'] = customer.password[:10]

                        messages.success(request, "Mật khẩu đã được thay đổi thành công!")
                        logger.info(f"Password changed for customer: {customer.phone}")
                        return redirect(reverse('shop:tai_khoan') + '?tab=password')
                else:
                    context['password_form'] = password_form
                    context['active_tab'] = 'password'
        else:
            # GET request - initialize forms
            context['address_form'] = UpdateAddressForm(instance=customer)
            context['password_form'] = ChangePasswordForm()

        # ✅ IMPROVED - Fetch customer orders for display
        customer_orders = Order.objects.filter(phone=customer.phone).order_by('-created_at')
        context['customer_orders'] = customer_orders

        # Get order items for each order and pre-calculate totals
        orders_with_items = []
        for order in customer_orders:
            order_items = OrderItem.objects.filter(order=order)
            # ✅ FIXED - Pre-calculate item totals in Python instead of template
            items_with_totals = []
            for item in order_items:
                items_with_totals.append({
                    'product': item.product,
                    'quantity': item.quantity,
                    'price': item.price,
                    'total': item.price * item.quantity  # Calculate total here
                })
            orders_with_items.append({
                'order': order,
                'items': items_with_totals,
                'awarded_points': order.awarded_points if order.points_awarded else 0,
                'points_status': 'Đã cộng' if order.points_awarded else 'Chưa cộng'
            })
        context['orders_with_items'] = orders_with_items

        # ✅ NEW - Add reward points information to context
        context['customer_points'] = customer.points
        context['total_earned_points'] = Order.objects.filter(
            phone=customer.phone,
            points_awarded=True
        ).aggregate(total=Sum('awarded_points'))['total'] or 0

        return render(request, 'shop/tai_khoan.html', context)

    except Customer.DoesNotExist:
        logger.warning(f"Account page - customer {customer_id} not found")
        # Clear only customer session keys to avoid logging out admin
        clear_customer_session(request)
        messages.error(request, "Tài khoản không tồn tại.")
        return redirect('shop:dang_nhap')


@never_cache
@require_http_methods(["GET", "POST"])
@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def dang_ky(request):
    if request.method == 'POST':
        from .forms import CustomerRegisterForm
        form = CustomerRegisterForm(request.POST)

        if form.is_valid():
            try:
                phone = form.cleaned_data['phone']
                # Kiểm tra xem SĐT này đã có sẵn chưa (do từng mua hàng trước đó)
                customer = Customer.objects.filter(phone=phone).first()

                if customer:
                    # Nếu đã có, cập nhật lại tên, địa chỉ và gán mật khẩu đăng ký
                    customer.full_name = form.cleaned_data['full_name']
                    customer.set_password(form.cleaned_data['password'])
                    if form.cleaned_data.get('address'):
                        customer.address = form.cleaned_data['address']
                    customer.save()
                else:
                    # Nếu chưa có, tạo mới hoàn toàn
                    customer = form.save(commit=False)
                    customer.set_password(form.cleaned_data['password'])
                    customer.save()

                logger.info(f"Customer registered/updated: {customer.phone}")
                create_user_session(request, customer)

                messages.success(request, f"Đăng ký thành công! Xin chào, {customer.full_name}!")
                return redirect('shop:trang_chu')
            except Exception as e:
                logger.error(f"Registration error: {e}")
                messages.error(request, "Đã xảy ra lỗi. Vui lòng thử lại.")
        else:
            logger.warning(f"Registration form errors: {form.errors}")
    else:
        from .forms import CustomerRegisterForm
        form = CustomerRegisterForm()

    return render(request, 'shop/dang_ky.html', {'form': form})


@never_cache
@require_http_methods(["GET", "POST"])
@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def dang_nhap(request):
    """Login with enhanced security and session management"""
    if request.method == 'POST':
        from .forms import CustomerLoginForm
        form = CustomerLoginForm(request.POST)

        if form.is_valid():
            phone = form.cleaned_data['phone']
            password = form.cleaned_data['password']

            try:
                customer = Customer.objects.get(phone=phone)

                # Verify password
                if customer.check_password(password):
                    # ✅ IMPROVED - Use shared session creation helper
                    create_user_session(request, customer)

                    logger.info(f"Customer logged in: {customer.phone}")
                    messages.success(request, f"Xin chào, {customer.full_name}!")
                    return redirect('shop:trang_chu')
                else:
                    # Log failed attempts
                    logger.warning(f"Failed login attempt for phone: {phone}")
                    messages.error(request, "Sai mật khẩu!")

            except Customer.DoesNotExist:
                logger.warning(f"Login attempt with non-existent phone: {phone}")
                messages.error(request, "Số điện thoại chưa được đăng ký!")
            except Exception as e:
                logger.error(f"Login error: {e}")
                messages.error(request, "Đã xảy ra lỗi. Vui lòng thử lại.")
        else:
            messages.error(request, "Dữ liệu không hợp lệ.")
    else:
        from .forms import CustomerLoginForm
        form = CustomerLoginForm()

    context = get_base_context(request, include_categories=False)
    context['form'] = form
    return render(request, 'shop/dang_nhap.html', context)


@never_cache
@require_http_methods(["GET"])
def dang_xuat(request):
    # Consume any queued messages so they won't survive across flush
    list(get_messages(request))

    customer_name = request.session.get('customer_name')

    clear_customer_session(request)

    logger.info(f"Customer logged out: {customer_name}")
    return redirect('shop:trang_chu')


def thanh_toan(request):
    # Use builder
    context = build_render_context(request, 'shop/thanh_toan.html')

    # Lấy thông tin giỏ hàng
    cart = request.session.get('cart', {})
    cart_items, tong_tien, tong_so_luong = get_cart_items(cart)

    # numeric order total (int) for JS and form validation
    order_total_value = int(tong_tien) if tong_tien else 0

    customer_id = request.session.get('customer_id')
    customer = Customer.objects.filter(id=customer_id).first() if customer_id else None

    if request.method == 'POST':
        form = OrderForm(request.POST, customer=customer, order_total=order_total_value)
        if form.is_valid():
            # we will handle final save in xac_nhan_don_hang; here just a lightweight flow (optional)
            order = form.save(commit=False)
            # Keep order.total_price / final_price to be set in xac_nhan_don_hang for atomic processing
            order.save()
            request.session['cart'] = {}
            return redirect('shop:thanh_cong')
    else:
        initial_data = {'full_name': customer.full_name, 'phone': customer.phone,
                        'address': customer.address} if customer else {}
        form = OrderForm(initial=initial_data, customer=customer, order_total=order_total_value)

    context.update({
        'cart_items': cart_items,
        'tong_tien': tong_tien,
        'tong_so_luong': tong_so_luong,
        'form': form,
        'current_customer': customer,  # template expects current_customer
        'order_total_value': order_total_value  # for JS
    })

    return render(request, 'shop/thanh_toan.html', context)


def send_telegram_notification(order, order_items):
    try:
        token = settings.TELEGRAM_BOT_TOKEN
        chat_id = settings.TELEGRAM_CHAT_ID

        if not token or not chat_id:
            logger.warning("Telegram credentials not configured")
            return

        items_text = "\n".join(
            f"- {item.product.name} (x{item.quantity}): {item.price:,.0f}đ"
            for item in order_items
        )

        message = f"""🛒 *ĐƠN HÀNG MỚI #{order.id}*
👤 Khách: {order.full_name}
📞 SĐT: {order.phone}
📍 Địa chỉ: {order.address}
📦 Sản phẩm:
{items_text}
💰 Tổng: *{order.total_price:,.0f}đ*"""

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, data={
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'Markdown'
        }, timeout=5)
    except Exception as e:
        logger.error(f"Telegram notification failed: {e}")


def xac_nhan_don_hang(request):
    if request.method == 'POST':
        cart = request.session.get('cart', {})
        if not cart:
            return redirect('shop:gio_hang')

        # provide totals for form validation
        cart_items, tong_tien, tong_so_luong = get_cart_items(cart)
        order_total_value = int(tong_tien) if tong_tien else 0

        # Identify logged-in customer (if any) for validation and later deduction
        customer_id = request.session.get('customer_id')
        session_customer = Customer.objects.filter(id=customer_id).first() if customer_id else None

        form = OrderForm(request.POST, customer=session_customer, order_total=order_total_value)

        if form.is_valid():
            try:
                with transaction.atomic():
                    order = form.save(commit=False)
                    order.total_price = 0
                    order.save()

                    total_amount = Decimal(0)
                    for p_id, item in cart.items():
                        product = Product.objects.select_for_update().get(id=int(p_id))
                        if product.stock < item['quantity']:
                            raise ValueError(f"Sản phẩm {product.name} không đủ số lượng.")

                        product.stock -= item['quantity']
                        product.save()

                        item_total = product.price * item['quantity']
                        total_amount += item_total
                        OrderItem.objects.create(order=order, product=product, quantity=item['quantity'],
                                                 price=product.price)

                    # Applied points handling
                    applied_points = form.cleaned_data.get('applied_points') or 0
                    # 1 point = 1 VND
                    discount_value = Decimal(int(applied_points))

                    # final price cannot be negative
                    final_price = total_amount - discount_value
                    if final_price < 0:
                        final_price = Decimal(0)

                    order.total_price = total_amount
                    order.applied_points = applied_points
                    order.final_price = final_price
                    order.save()

                    # Create or update a Customer (guest -> vãng lai)
                    customer, created = Customer.objects.get_or_create(
                        phone=order.phone,
                        defaults={
                            'full_name': order.full_name,
                            'address': order.address,
                            'password': '',
                        }
                    )
                    if not created:
                        customer.full_name = order.full_name
                        customer.address = order.address
                        customer.save(update_fields=['full_name', 'address'])

                    # Link the order to the customer
                    order.customer = customer
                    order.save(update_fields=['customer'])

                    # Deduct used points from customer (only if used and customer has enough)
                    if applied_points and applied_points > 0:
                        if customer.points >= applied_points:
                            customer.points = customer.points - applied_points
                            customer.save(update_fields=['points'])
                        else:
                            # This should not happen (form validation), but guard anyway
                            raise ValueError("Không đủ điểm để trừ cho đơn hàng.")

                    # Lấy danh sách item để gửi thông báo
                    order_items = OrderItem.objects.filter(order=order)

                    telegram_thread = threading.Thread(
                        target=send_telegram_notification,
                        args=(order, order_items),
                        daemon=True
                    )
                    telegram_thread.start()

                # remove cart after success
                del request.session['cart']

                # pass order details to confirmation page
                return render(request, 'shop/xac_nhan_thanh_cong.html', {
                    'order': order,
                    'order_items': order_items,
                    'remaining_points': customer.points if customer else 0
                })

            except Exception as e:
                messages.error(request, str(e))
                return redirect('shop:gio_hang')
        else:
            context = build_render_context(request, 'shop/thanh_toan.html')
            context.update({
                'cart_items': cart_items,
                'tong_tien': tong_tien,
                'tong_so_luong': tong_so_luong,
                'form': form,
                'current_customer': session_customer
            })

            messages.error(request, "Thông tin không hợp lệ. Vui lòng kiểm tra lại.")
            return render(request, 'shop/thanh_toan.html', context)

    return redirect('shop:thanh_toan')


def get_top_selling_or_random(target_count=60):
    target_count = max(50, min(100, target_count))

    ba_tuan_truoc = timezone.now() - timedelta(weeks=3)

    top_products_ids = list(
        OrderItem.objects.filter(
            order__created_at__gte=ba_tuan_truoc
        )
        .values_list('product_id', flat=True)
        .annotate(total_sold=Sum('quantity'))
        .order_by('-total_sold')[:target_count]
    )

    products_from_db = list(
        Product.objects.filter(id__in=top_products_ids)
        .select_related('category')
    )

    product_map = {p.id: p for p in products_from_db}

    products_list = [product_map[pid] for pid in top_products_ids if pid in product_map]

    needed = target_count - len(products_list)
    if needed > 0:
        remaining_ids = list(
            Product.objects.filter()
            .exclude(id__in=top_products_ids)
            .values_list('id', flat=True)
        )

        if remaining_ids:
            # Chọn ngẫu nhiên IDs
            random_ids = random.sample(remaining_ids, min(needed, len(remaining_ids)))
            # Fetch thêm và nối vào list
            random_products = list(
                Product.objects.filter(id__in=random_ids)
                .select_related('category')
            )
            products_list.extend(random_products)

    return products_list


def trang_chu(request):
    # ✅ IMPROVED - Use builder
    context = build_render_context(request, 'shop/trang_chu.html', include_categories=False)
    context['categories'] = Category.objects.all()
    context['banners'] = context['config'].banners.all()

    is_filtered = False
    category_slug = request.GET.get('category')

    if category_slug:
        # Nếu người dùng bấm lọc danh mục: Hiển thị sản phẩm thuộc danh mục đó
        products = Product.objects.filter(category__slug=category_slug)
        is_filtered = True
    else:
        # Nếu ở trang chủ mặc định: Hiển thị 60 sản phẩm bán chạy + ngẫu nhiên phối hợp
        products = get_top_selling_or_random(target_count=60)

    context.update({
        'products': products,
        'is_filtered': is_filtered,
    })

    return render(request, 'shop/trang_chu.html', context)


def chi_tiet_san_pham(request, slug):
    # ✅ IMPROVED - Use builder
    context = build_render_context(request, 'shop/chi_tiet_san_pham.html', include_categories=False)
    context['categories'] = Category.objects.all()
    context['product'] = get_object_or_404(Product, slug=slug)

    # Lấy giỏ hàng từ session
    cart = request.session.get('cart', {})
    # Lấy số lượng đã có trong giỏ (mặc định là 0 nếu chưa có)
    qty_in_cart = 0
    product_id_str = str(context['product'].id)
    if product_id_str in cart:
        qty_in_cart = cart[product_id_str].get('quantity', 0)

    context.update({
        'products': get_top_selling_or_random(target_count=50),
        'qty_in_cart': qty_in_cart,
    })

    return render(request, 'shop/chi_tiet_san_pham.html', context)


def lien_he(request):
    # ✅ IMPROVED - Use builder (single line!)
    return render(request, 'shop/lien_he.html',
                  build_render_context(request, 'shop/lien_he.html', include_categories=False))


def tai_lieu(request):
    # ✅ IMPROVED - Use builder
    context = build_render_context(request, 'shop/tai_lieu.html')
    context['posts'] = DocumentPost.objects.all()
    return render(request, 'shop/tai_lieu.html', context)


def chi_tiet_tai_lieu(request, slug):
    # ✅ IMPROVED - Use builder
    context = build_render_context(request, 'shop/chi_tiet_tai_lieu.html')
    context['post'] = get_object_or_404(DocumentPost, slug=slug)
    return render(request, 'shop/chi_tiet_tai_lieu.html', context)


@require_http_methods(["POST"])
@ratelimit(key='ip', rate='10/m', method='POST', block=False)
def them_vao_gio(request, product_id):
    # 0. Kiểm tra Rate Limit (vì block=False nên phải tự kiểm tra)
    if getattr(request, 'limited', False):
        logger.warning(f"Rate limit triggered for IP: {request.META.get('REMOTE_ADDR')}")
        return JsonResponse({
            'status': 'error',
            'message': 'Bạn thao tác quá nhanh, vui lòng chờ chút!'
        }, status=429)

    # 1. Lấy sản phẩm
    product = get_object_or_404(Product, id=product_id)

    # Lấy quantity từ POST, mặc định là 1 nếu không có
    try:
        qty = int(request.POST.get('quantity', 1))
        if qty < 1: qty = 1
    except (ValueError, TypeError):
        qty = 1

    # 2. Lấy giỏ hàng từ session
    cart = request.session.get('cart', {})
    p_id_str = str(product_id)

    # 3. KIỂM TRA TỒN KHO
    current_in_cart = cart[p_id_str]['quantity'] if p_id_str in cart else 0
    total_requested = current_in_cart + qty

    if total_requested > product.stock:
        return JsonResponse({
            'status': 'error',
            'message': f'Rất tiếc, cửa hàng chỉ còn {product.stock} sản phẩm.'
        })

    # 4. Cập nhật giỏ hàng
    if p_id_str in cart:
        cart[p_id_str]['quantity'] += qty
    else:
        cart[p_id_str] = {
            'quantity': qty,
            'price': float(product.price)
        }

    request.session['cart'] = cart
    request.session.modified = True  # Quan trọng: Báo cho Django biết session đã thay đổi

    # 5. Tính tổng số lượng hiển thị trên icon giỏ hàng
    tong_so_luong = sum(item['quantity'] for item in cart.values())

    return JsonResponse({
        'status': 'success',
        'product_id': product.id,
        'current_qty': cart[p_id_str]['quantity'],
        'product_name': product.name,
        'product_price': f"{product.price:,.0f}".replace(",", ".") + "đ",
        'product_raw_price': float(product.price),
        'product_image': product.image.url if product.image else '/static/images/no-image.png',
        'total_items': tong_so_luong
    })


def gio_hang(request):
    # ✅ IMPROVED - Use builder
    context = build_render_context(request, 'shop/gio_hang.html')
    cart = request.session.get('cart', {})

    cart_items, tong_tien, _ = get_cart_items(cart)

    context.update({
        'cart_items': cart_items,
        'tong_tien': tong_tien
    })

    return render(request, 'shop/gio_hang.html', context)


# THÊM MỚI: Hàm xử lý xóa sản phẩm ra khỏi giỏ hàng qua AJAX
def xoa_khoi_gio(request, product_id):
    if request.method == 'POST':
        cart = request.session.get('cart', {})
        p_id_str = str(product_id)

        if p_id_str in cart:
            del cart[p_id_str]
            request.session['cart'] = cart

        # Tính tổng số lượng thực tế (cộng dồn số lượng của từng món)
        tong_so_luong = sum(int(item['quantity']) for item in cart.values())

        return JsonResponse({'status': 'success', 'total_items': tong_so_luong})
    return JsonResponse({'status': 'error'}, status=400)


# THÊM MỚI: Hàm xử lý cập nhật số lượng khi bấm cộng trừ ở trang giỏ hàng
def cap_nhat_gio(request, product_id):
    if request.method == 'POST':
        # Lấy sản phẩm để kiểm tra tồn kho
        product = get_object_or_404(Product, id=product_id)
        new_qty = int(request.POST.get('quantity', 1))

        # Kiểm tra tồn kho trước khi lưu
        if new_qty > product.stock:
            return JsonResponse({'status': 'error', 'message': f'Sản phẩm chỉ còn {product.stock} chiếc trong kho.'},
                                status=400)

        cart = request.session.get('cart', {})
        p_id_str = str(product_id)

        if p_id_str in cart and new_qty >= 1:
            cart[p_id_str]['quantity'] = new_qty
            request.session['cart'] = cart
            return JsonResponse({'status': 'success'})

        return JsonResponse({'status': 'error', 'message': 'Sản phẩm không có trong giỏ hàng'}, status=400)

    return JsonResponse({'status': 'error'}, status=400)


# ✅ IMPROVED - Extract common policy page pattern
def _render_policy_page(request, template_name):
    """Helper for policy pages - all use same context"""
    context = build_render_context(request, template_name, include_categories=False)
    context['categories'] = Category.objects.filter(parent__isnull=True)
    return render(request, template_name, context)


def chinh_sach_van_chuyen(request):
    return _render_policy_page(request, 'shop/chinh_sach_van_chuyen.html')


def chinh_sach_bao_hanh(request):
    return _render_policy_page(request, 'shop/chinh_sach_bao_hanh.html')


def chinh_sach_doi_tra(request):
    return _render_policy_page(request, 'shop/chinh_sach_doi_tra.html')


def chinh_sach_bao_mat(request):
    return _render_policy_page(request, 'shop/chinh_sach_bao_mat.html')


def search_api(request):
    query = request.GET.get('q', '')
    # Tìm kiếm sản phẩm có tên chứa ký tự đang nhập (Live search)
    products = Product.objects.filter(name__icontains=query)[:5]

    results = []
    for p in products:
        results.append({
            'name': p.name,
            'price': "{:,}".format(p.price).replace(',', '.'),
            'image_url': p.image.url if p.image else '/static/default-image.png',
            # Sửa lại ở đây: dùng 'slug' thay vì 'id'
            'url': reverse('shop:chi_tiet_san_pham', kwargs={'slug': p.slug})
        })
    return JsonResponse({'products': results})


def ket_qua_tim_kiem(request):
    query = request.GET.get('q', '')
    products = Product.objects.filter(name__icontains=query) if query else []

    # ✅ IMPROVED - Use builder
    context = build_render_context(request, 'shop/ket_qua_tim_kiem.html')
    context.update({
        'products': products,
        'query': query,
    })

    return render(request, 'shop/ket_qua_tim_kiem.html', context)


def get_cart_items(cart):
    if not cart:
        return [], 0, 0

    product_ids = [int(p_id) for p_id in cart.keys()]
    # Lấy tất cả sản phẩm trong 1 câu truy vấn
    products = {p.id: p for p in Product.objects.filter(id__in=product_ids)}

    cart_items = []
    tong_tien = 0
    tong_so_luong = 0

    for p_id_str, item in cart.items():
        product = products.get(int(p_id_str))
        if product:
            qty = item['quantity']
            item_total = product.price * qty
            tong_tien += item_total
            tong_so_luong += qty
            cart_items.append({
                'product': product,
                'quantity': qty,
                'total_price': item_total
            })

    return cart_items, tong_tien, tong_so_luong

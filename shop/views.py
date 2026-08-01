import logging
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from .models import Category, Product, ShopConfiguration, DocumentPost, Order, OrderItem, Customer
from datetime import timedelta
from django.utils import timezone
from django.db.models import Sum, Q
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth.hashers import make_password
import random
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
from decimal import ROUND_HALF_UP, Decimal
from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from .services import OrderService
import json

logger = logging.getLogger(__name__)


@staff_member_required(login_url='/admin/login/')
def pos_dashboard(request):
    config = ShopConfiguration.get_config()
    products = Product.objects.select_related('category')
    categories = Category.objects.all()

    context = {
        'config': config,
        'products': products,
        'categories': categories,
    }
    return render(request, 'shop/pos_dashboard.html', context)


@staff_member_required
@require_http_methods(["GET"])
def pos_search_product(request):
    """API tìm kiếm sản phẩm bằng mã vạch hoặc tên cho POS"""
    query = request.GET.get('q', '').strip()
    products = Product.objects.filter(
        Q(name__icontains=query) | Q(code__iexact=query)
    )[:20]

    data = []
    for p in products:
        data.append({
            'id': p.id,
            'name': p.name,
            'code': p.code or '',
            'price': float(p.price),
            'stock': p.stock,
            'image': p.image.url if p.image else '/static/images/no-image.png'
        })
    return JsonResponse({'products': data})


@staff_member_required
@require_http_methods(["POST"])
def pos_checkout(request):
    try:
        data = json.loads(request.body)
        order = OrderService.create_pos_order(data)
        return JsonResponse({
            'status': 'success',
            'order_id': order.id,
            'message': 'Thanh toán thành công!'
        })
    except ValueError as ve:
        return JsonResponse({'status': 'error', 'message': str(ve)}, status=400)
    except Exception as e:
        logger.exception("pos_checkout failed")
        return JsonResponse({'status': 'error', 'message': 'Đã xảy ra lỗi máy chủ. Vui lòng thử lại sau.'}, status=500)


def get_shop_config():
    config = cache.get('shop_config')
    if config is None:
        config = ShopConfiguration.objects.first()
        if not config:
            config = ShopConfiguration.objects.create()
        # cache for 5 minutes
        cache.set('shop_config', config, 300)
    return config


def get_base_context(request=None, include_categories=True):
    context = {'config': ShopConfiguration.get_config()}

    if include_categories:
        context['categories'] = get_cached_categories_tree()

    if request:
        context['customer_id'] = request.session.get('customer_id')

    return context


def build_render_context(request, template_name, **kwargs):
    context = get_base_context(request)
    context.update(kwargs)
    return context


CUSTOMER_SESSION_KEYS = ['customer_id', 'customer_name', 'customer_phone', 'customer_auth_hash']


def clear_customer_session(request):
    for k in CUSTOMER_SESSION_KEYS:
        request.session.pop(k, None)
    request.session.pop('cart', None)
    request.session.modified = True


def create_user_session(request, customer):
    try:
        request.session.cycle_key()
    except Exception:
        if not request.session.session_key:
            request.session.create()

    try:
        get_token(request)
    except Exception:
        pass

    request.session['customer_id'] = customer.id
    request.session['customer_name'] = customer.full_name
    request.session['customer_phone'] = customer.phone
    request.session['customer_auth_hash'] = customer.password[:10]
    request.session.set_expiry(1800)  # 30 phút

    logger.info(f"Session created for customer: {customer.phone}")


@never_cache
@require_http_methods(["GET", "POST"])
def tai_khoan(request):
    customer_id = request.session.get('customer_id')

    if not customer_id:
        messages.warning(request, "Vui lòng đăng nhập để xem tài khoản.")
        return redirect('shop:dang_nhap')

    try:
        customer = Customer.objects.get(id=customer_id)

        stored_phone = request.session.get('customer_phone')
        if stored_phone != customer.phone:
            logger.warning(f"Session integrity check failed for customer {customer_id}")
            clear_customer_session(request)
            messages.error(request, "Phiên làm việc không hợp lệ. Vui lòng đăng nhập lại.")
            return redirect('shop:dang_nhap')

        active_tab = request.GET.get('tab', 'info')
        context = build_render_context(request, 'shop/tai_khoan.html', customer=customer)
        context['active_tab'] = active_tab

        if request.method == 'POST':
            form_type = request.POST.get('form_type', '')

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

            elif form_type == 'change_password':
                password_form = ChangePasswordForm(request.POST)
                if password_form.is_valid():
                    old_password = password_form.cleaned_data['old_password']
                    new_password = password_form.cleaned_data['new_password']

                    if not customer.check_password(old_password):
                        messages.error(request, "Mật khẩu cũ không chính xác!")
                        logger.warning(f"Failed password change attempt for customer: {customer.phone}")
                        context['password_form'] = password_form
                        context['active_tab'] = 'password'
                    else:
                        customer.set_password(new_password)
                        customer.save()

                        # Đồng bộ session hash bảo mật chính xác
                        request.session['customer_auth_hash'] = customer.password[:10]

                        messages.success(request, "Mật khẩu đã được thay đổi thành công!")
                        logger.info(f"Password changed for customer: {customer.phone}")
                        return redirect(reverse('shop:tai_khoan') + '?tab=password')
                else:
                    context['password_form'] = password_form
                    context['active_tab'] = 'password'
        else:
            context['address_form'] = UpdateAddressForm(instance=customer)
            context['password_form'] = ChangePasswordForm()

        # Tối ưu hóa chống N+1 Query bằng prefetch_related
        customer_orders = Order.objects.filter(phone=customer.phone).prefetch_related('items__product').order_by('-created_at')
        context['customer_orders'] = customer_orders

        orders_with_items = []
        now = timezone.now()
        limit = timedelta(seconds=50)

        for order in customer_orders:
            order_items = order.items.all()
            items_with_totals = []
            for item in order_items:
                unit_price = item.price
                disc_unit = getattr(item, 'discount_per_unit', Decimal(0))
                final_unit_price = unit_price - disc_unit
                line_total = final_unit_price * item.quantity

                items_with_totals.append({
                    'product': item.product,
                    'quantity': item.quantity,
                    'price': unit_price,
                    'discount_per_unit': disc_unit,
                    'final_unit_price': final_unit_price,
                    'total': line_total
                })

            points_used = getattr(order, 'applied_points',
                                  getattr(order, 'points_used', getattr(order, 'used_points', 0)))

            time_diff = now - order.created_at
            remaining_days = (limit - time_diff).days + 1 if time_diff < limit else 0

            orders_with_items.append({
                'order': order,
                'items': items_with_totals,
                'awarded_points': order.awarded_points if order.points_awarded else 0,
                'points_status': 'Đã cộng' if order.points_awarded else 'Chưa cộng',
                'points_used': points_used or 0,
                'remaining_days': remaining_days,
            })
        context['orders_with_items'] = orders_with_items

        context['customer_points'] = customer.points
        pending_orders = Order.objects.filter(phone=customer.phone, points_awarded=False)
        pending_points = sum(o.calculate_points() for o in pending_orders)
        context['pending_points'] = pending_points

        total_used_points = Order.objects.filter(phone=customer.phone).aggregate(total=Sum('applied_points'))['total'] or 0
        context['total_points'] = customer.points + total_used_points

        return render(request, 'shop/tai_khoan.html', context)

    except Customer.DoesNotExist:
        logger.warning(f"Account page - customer {customer_id} not found")
        clear_customer_session(request)
        messages.error(request, "Tài khoản không tồn tại.")
        return redirect('shop:dang_nhap')


@never_cache
@require_http_methods(["GET", "POST"])
@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def dang_ky(request):
    if request.method == 'POST':
        form = CustomerRegisterForm(request.POST)

        if form.is_valid():
            try:
                phone = form.cleaned_data['phone']
                customer = Customer.objects.filter(phone=phone).first()

                if customer:
                    customer.full_name = form.cleaned_data['full_name']
                    customer.set_password(form.cleaned_data['password'])
                    if form.cleaned_data.get('address'):
                        customer.address = form.cleaned_data['address']
                    customer.save()
                else:
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
        form = CustomerRegisterForm()

    return render(request, 'shop/dang_ky.html', {'form': form})


@never_cache
@require_http_methods(["GET", "POST"])
@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def dang_nhap(request):
    if request.method == 'POST':
        form = CustomerLoginForm(request.POST)

        if form.is_valid():
            phone = form.cleaned_data['phone']
            password = form.cleaned_data['password']

            try:
                customer = Customer.objects.get(phone=phone)
                if customer.check_password(password):
                    create_user_session(request, customer)
                    logger.info(f"Customer logged in: {customer.phone}")
                    messages.success(request, f"Xin chào, {customer.full_name}!")
                    return redirect('shop:trang_chu')
                else:
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
        form = CustomerLoginForm()

    context = get_base_context(request, include_categories=False)
    context['form'] = form
    return render(request, 'shop/dang_nhap.html', context)


@never_cache
@require_http_methods(["GET"])
def dang_xuat(request):
    list(get_messages(request))
    customer_name = request.session.get('customer_name')
    clear_customer_session(request)
    logger.info(f"Customer logged out: {customer_name}")
    return redirect('shop:trang_chu')


def thanh_toan(request):
    context = build_render_context(request, 'shop/thanh_toan.html')
    cart = request.session.get('cart', {})
    cart_items, tong_tien, tong_so_luong = get_cart_items(cart)

    # KIỂM TRA TỒN KHO TRƯỚC KHI CHO PHÉP VÀO TRANG THANH TOÁN
    for item in cart_items:
        product = item['product']
        qty = item['quantity']
        if product.stock <= 0 or product.stock < qty:
            messages.error(request, f"Sản phẩm '{product.name}' đã hết hàng hoặc không đủ số lượng trong kho.")
            return redirect('shop:gio_hang')

    order_total_value = int(tong_tien) if tong_tien else 0
    customer_id = request.session.get('customer_id')
    customer = Customer.objects.filter(id=customer_id).first() if customer_id else None

    if request.method == 'POST':
        form = OrderForm(request.POST, customer=customer, order_total=order_total_value)
        if form.is_valid():
            order = form.save(commit=False)
            order.save()
            request.session['cart'] = {}
            return redirect('shop:thanh_congh')
    else:
        initial_data = {'full_name': customer.full_name, 'phone': customer.phone, 'address': customer.address} if customer else {}
        form = OrderForm(initial=initial_data, customer=customer, order_total=order_total_value)

    context.update({
        'cart_items': cart_items,
        'tong_tien': tong_tien,
        'tong_so_luong': tong_so_luong,
        'form': form,
        'current_customer': customer,
        'order_total_value': order_total_value
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


@require_http_methods(["POST"])
def xac_nhan_don_hang(request):
    cart = request.session.get('cart', {})
    if not cart:
        return redirect('shop:gio_hang')

    cart_items, tong_tien, tong_so_luong = get_cart_items(cart)
    order_total_value = int(tong_tien) if tong_tien else 0

    customer_id = request.session.get('customer_id')
    session_customer = Customer.objects.filter(id=customer_id).first() if customer_id else None

    form = OrderForm(request.POST, customer=session_customer, order_total=order_total_value)

    if form.is_valid():
        try:
            order, order_items, customer = OrderService.create_web_order(form, cart)
            del request.session['cart']

            return render(request, 'shop/xac_nhan_thanh_cong.html', {
                'order': order,
                'order_items': order_items,
                'remaining_points': customer.points if customer else 0
            })

        except Exception as e:
            messages.error(request, str(e))
    else:
        messages.error(request, "Thông tin không hợp lệ. Vui lòng kiểm tra lại.")

    context = build_render_context(request, 'shop/thanh_toan.html')
    context.update({
        'cart_items': cart_items,
        'tong_tien': tong_tien,
        'tong_so_luong': tong_so_luong,
        'form': form,
        'current_customer': session_customer,
        'order_total_value': order_total_value
    })
    return render(request, 'shop/thanh_toan.html', context)


def thanh_cong(request):
    """Trang thông báo đặt hàng thành công đơn giản"""
    context = build_render_context(request, 'shop/thanh_cong.html')
    return render(request, 'shop/thanh_cong.html', context)


def get_top_selling_or_random(target_count=60):
    target_count = max(50, min(100, target_count))
    ba_tuan_truoc = timezone.now() - timedelta(weeks=3)

    top_products_ids = list(
        OrderItem.objects.filter(order__created_at__gte=ba_tuan_truoc)
        .values_list('product_id', flat=True)
        .annotate(total_sold=Sum('quantity'))
        .order_by('-total_sold')[:target_count]
    )

    products_from_db = list(Product.objects.filter(id__in=top_products_ids).select_related('category'))
    product_map = {p.id: p for p in products_from_db}
    products_list = [product_map[pid] for pid in top_products_ids if pid in product_map]

    needed = target_count - len(products_list)
    if needed > 0:
        # avoid loading all product ids: fetch a manageable pool and sample from it
        candidate_qs = Product.objects.exclude(id__in=top_products_ids).values_list('id', flat=True)[:max(needed * 10, 200)]
        candidate_ids = list(candidate_qs)
        if candidate_ids:
            random_ids = random.sample(candidate_ids, min(needed, len(candidate_ids)))
            random_products = list(Product.objects.filter(id__in=random_ids).select_related('category').only('id', 'name', 'price', 'stock', 'slug', 'category'))
            products_list.extend(random_products)

    return products_list


def trang_chu(request):
    context = build_render_context(request, 'shop/trang_chu.html', include_categories=False)
    context['categories'] = get_cached_all_categories()  # Sử dụng cache toàn bộ danh mục
    context['banners'] = context['config'].banners.all()

    is_filtered = False
    category_slug = request.GET.get('category')

    if category_slug:
        products = Product.objects.filter(category__slug=category_slug)
        is_filtered = True
    else:
        products = get_top_selling_or_random(target_count=60)

    context.update({
        'products': products,
        'is_filtered': is_filtered,
    })

    return render(request, 'shop/trang_chu.html', context)


def chi_tiet_san_pham(request, slug):
    context = build_render_context(request, 'shop/chi_tiet_san_pham.html', include_categories=False)
    context['categories'] = get_cached_all_categories()  # Sử dụng cache toàn bộ danh mục
    context['product'] = get_object_or_404(Product, slug=slug)

    cart = request.session.get('cart', {})
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
    return render(request, 'shop/lien_he.html', build_render_context(request, 'shop/lien_he.html', include_categories=False))


def tai_lieu(request):
    context = build_render_context(request, 'shop/tai_lieu.html')
    context['posts'] = get_cached_document_posts()  # Sử dụng cache bài viết
    return render(request, 'shop/tai_lieu.html', context)


def chi_tiet_tai_lieu(request, slug):
    context = build_render_context(request, 'shop/chi_tiet_tai_lieu.html')
    context['post'] = get_object_or_404(DocumentPost, slug=slug)
    return render(request, 'shop/chi_tiet_tai_lieu.html', context)


def get_cart_items(cart):
    """Hàm hỗ trợ lấy danh sách sản phẩm trong giỏ hàng, tính tổng tiền và tổng số lượng tối ưu"""
    cart_items = []
    tong_tien = Decimal(0)
    tong_so_luong = 0

    if not cart:
        return cart_items, tong_tien, tong_so_luong

    product_ids = [int(p_id) for p_id in cart.keys()]
    products = Product.objects.filter(id__in=product_ids).only('id', 'price', 'stock', 'name', 'image', 'slug')
    product_map = {str(p.id): p for p in products}

    for p_id_str, item_data in cart.items():
        product = product_map.get(p_id_str)
        if product:
            qty = item_data.get('quantity', 0)
            price = product.price

            # Chỉ tính tiền vào tổng thanh toán nếu sản phẩm còn hàng trong kho
            subtotal = price * qty if product.stock > 0 else Decimal(0)
            if product.stock > 0:
                tong_tien += subtotal

            tong_so_luong += qty
            cart_items.append({
                'product': product,
                'quantity': 0 if product.stock <= 0 else qty,
                'price': price,
                'subtotal': subtotal
            })
    return cart_items, tong_tien, tong_so_luong


@require_http_methods(["POST"])
@ratelimit(key='ip', rate='10/m', method='POST', block=False)
@csrf_protect
def them_vao_gio(request, product_id):
    if getattr(request, 'limited', False):
        logger.warning(f"Rate limit triggered for IP: {request.META.get('REMOTE_ADDR')}")
        return JsonResponse({
            'status': 'error',
            'message': 'Bạn thao tác quá nhanh, vui lòng chờ chút!'
        }, status=429)

    product = get_object_or_404(Product, id=product_id)

    try:
        qty = int(request.POST.get('quantity', 1))
    except (ValueError, TypeError):
        qty = 1
    if qty < 1:
        qty = 1
    MAX_QTY = 1000
    if qty > MAX_QTY:
        qty = MAX_QTY

    cart = request.session.get('cart', {})
    p_id_str = str(product_id)

    current_in_cart = cart[p_id_str]['quantity'] if p_id_str in cart else 0
    total_requested = current_in_cart + qty

    if total_requested > product.stock:
        return JsonResponse({
            'status': 'error',
            'message': f'Rất tiếc, cửa hàng chỉ còn {product.stock} sản phẩm.'
        })

    if p_id_str in cart:
        cart[p_id_str]['quantity'] += qty
    else:
        cart[p_id_str] = {
            'quantity': qty,
            'price': float(product.price)
        }

    request.session['cart'] = cart
    request.session.modified = True

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
    context = build_render_context(request, 'shop/gio_hang.html')
    cart = request.session.get('cart', {})
    cart_items, tong_tien, _ = get_cart_items(cart)

    context.update({
        'cart_items': cart_items,
        'tong_tien': tong_tien
    })

    return render(request, 'shop/gio_hang.html', context)


@require_http_methods(["POST"])
@csrf_protect
def xoa_khoi_gio(request, product_id):
    cart = request.session.get('cart', {})
    p_id_str = str(product_id)

    if p_id_str in cart:
        del cart[p_id_str]
        request.session['cart'] = cart
        request.session.modified = True

    cart_items, tong_tien, tong_so_luong = get_cart_items(cart)

    return JsonResponse({
        'status': 'success',
        'message': 'Đã xóa sản phẩm khỏi giỏ hàng!',
        'total_items': tong_so_luong,
        'tong_tien': f"{tong_tien:,.0f}".replace(",", ".") + "đ",
        'tong_tien_raw': float(tong_tien)
    })


@require_http_methods(["POST"])
@csrf_protect
def cap_nhat_gio_hang(request, product_id):
    """Cập nhật số lượng sản phẩm trong giỏ hàng qua AJAX"""
    # Flexible input handling (support form-data and JSON) but validate content-type
    quantity = request.POST.get('quantity')

    if not quantity:
        try:
            # Only attempt JSON decode for JSON content types
            content_type = request.META.get('CONTENT_TYPE', '')
            if content_type.startswith('application/json') and request.body:
                data = json.loads(request.body)
                quantity = data.get('quantity')
        except Exception:
            quantity = None

    if not quantity:
        quantity = request.GET.get('quantity')

    try:
        qty = int(quantity)
    except (ValueError, TypeError):
        qty = 1

    # Clamp the quantity to a reasonable maximum to avoid abuse
    MAX_QTY = 1000
    if qty > MAX_QTY:
        qty = MAX_QTY

    cart = request.session.get('cart', {})
    # compute totals early so we can report them
    cart_items, tong_tien, tong_so_luong = get_cart_items(cart)

    p_id_str = str(product_id)
    product = get_object_or_404(Product, id=product_id)

    # If product is out of stock, set cart qty to 0 (do not silently delete)
    if product.stock == 0:
        if p_id_str in cart:
            cart[p_id_str]['quantity'] = 0
            request.session['cart'] = cart
            request.session.modified = True

        cart_items, tong_tien, tong_so_luong = get_cart_items(cart)
        return JsonResponse({
            'status': 'out_of_stock',
            'message': 'Sản phẩm đã hết hàng.',
            'current_qty': 0,
            'available_stock': 0,
            'tong_tien_raw': float(tong_tien),
            'cart_total_price': float(tong_tien)
        }, status=200)

    # requested quantity exceeds available stock -> suggest corrected qty
    if qty > product.stock:
        current_in_cart = cart.get(p_id_str, {}).get('quantity', 0)
        suggested_qty = min(current_in_cart, product.stock)
        return JsonResponse({
            'status': 'error',
            'message': f'Rất tiếc, sản phẩm này chỉ còn lại {product.stock} sản phẩm trong kho.',
            'available_stock': product.stock,
            'current_qty': suggested_qty,
            'tong_tien_raw': float(tong_tien),
            'cart_total_price': float(tong_tien)
        }, status=400)

    # Normal update
    if qty <= 0:
        if p_id_str in cart:
            del cart[p_id_str]
    else:
        if p_id_str in cart:
            cart[p_id_str]['quantity'] = qty
        else:
            cart[p_id_str] = {
                'quantity': qty,
                'price': float(product.price)
            }

    request.session['cart'] = cart
    request.session.modified = True

    cart_items, tong_tien, tong_so_luong = get_cart_items(cart)
    item_subtotal = Decimal(0)
    if p_id_str in cart:
        item_subtotal = product.price * cart[p_id_str]['quantity']

    return JsonResponse({
        'status': 'success',
        'item_subtotal': f"{item_subtotal:,.0f}".replace(",", ".") + "đ",
        'current_qty': cart.get(p_id_str, {}).get('quantity', 0),
        'total_items': tong_so_luong,
        'tong_tien': f"{tong_tien:,.0f}".replace(",", ".") + "đ",
        'tong_tien_raw': float(tong_tien),
        'cart_total_price': float(tong_tien)
    })


def _render_policy_page(request, template_name):
    context = build_render_context(request, template_name, include_categories=False)
    context['categories'] = get_cached_categories_tree()  # Sử dụng cache danh mục gốc
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
    products = Product.objects.filter(name__icontains=query)[:5]

    results = []
    for p in products:
        results.append({
            'name': p.name,
            'price': "{:,}".format(p.price).replace(',', '.'),
            'image_url': p.image.url if p.image else '/static/default-image.png',
            'url': reverse('shop:chi_tiet_san_pham', kwargs={'slug': p.slug})
        })
    return JsonResponse({'products': results})


def ket_qua_tim_kiem(request):
    query = request.GET.get('q', '')
    products = Product.objects.filter(name__icontains=query) if query else []

    context = build_render_context(request, 'shop/ket_qua_tim_kiem.html')
    context.update({
        'products': products,
        'query': query,
    })

    return render(request, 'shop/ket_qua_tim_kiem.html', context)


@staff_member_required
@require_http_methods(["GET"])
def pos_get_customer_points(request):
    """API lấy điểm tích lũy của khách hàng theo số điện thoại cho trang POS"""
    phone = request.GET.get('phone', '').strip()
    if not phone:
        return JsonResponse({'status': 'error', 'message': 'Số điện thoại không được để trống'}, status=400)

    customer = Customer.objects.filter(phone=phone).first()
    if customer:
        return JsonResponse({
            'status': 'success',
            'points': customer.points,
            'full_name': customer.full_name
        })
    else:
        return JsonResponse({
            'status': 'success',
            'points': 0,
            'full_name': ''
        })


def get_cached_categories_tree():
    """Lấy danh mục phân cấp gốc từ cache"""
    categories = cache.get('shop_categories_tree')
    if categories is None:
        categories = list(Category.objects.filter(parent__isnull=True).prefetch_related('children'))
        cache.set('shop_categories_tree', categories, 900)
    return categories


def get_cached_all_categories():
    """Lấy toàn bộ danh mục từ cache"""
    categories = cache.get('shop_categories_all')
    if categories is None:
        categories = list(Category.objects.all())
        cache.set('shop_categories_all', categories, 900)
    return categories


def get_cached_document_posts():
    """Lấy danh sách bài viết tài liệu từ cache"""
    posts = cache.get('shop_document_posts')
    if posts is None:
        posts = list(DocumentPost.objects.all())
        cache.set('shop_document_posts', posts, 900)
    return posts
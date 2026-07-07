from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from .models import Category, Product, ShopConfiguration, DocumentPost, Order, OrderItem, Customer
from datetime import timedelta
from django.utils import timezone
from django.db.models import Sum
from django.urls import reverse
from django.contrib import messages
import random
from django.db import transaction
from .forms import OrderForm, CustomerRegisterForm
import requests
import threading
from django.conf import settings
from django_ratelimit.decorators import ratelimit


def tai_khoan(request):
    # Kiểm tra xem đã đăng nhập chưa
    customer_id = request.session.get('customer_id')
    if not customer_id:
        return redirect('shop:dang_nhap')

    # Lấy thông tin khách hàng
    customer = get_object_or_404(Customer, id=customer_id)
    config = get_shop_config()
    categories = Category.objects.filter(parent__isnull=True).prefetch_related('children')

    return render(request, 'shop/tai_khoan.html', {
        'customer': customer,
        'config': config,
        'categories': categories
    })


@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def dang_ky(request):
    if request.method == 'POST':
        form = CustomerRegisterForm(request.POST)
        if form.is_valid():
            customer = form.save(commit=False)
            customer.set_password(form.cleaned_data['password'])  # Mã hóa mật khẩu
            customer.save()
            messages.success(request, "Đăng ký thành công! Hãy đăng nhập.")
            return redirect('shop:dang_nhap')
    else:
        form = CustomerRegisterForm()
    return render(request, 'shop/dang_ky.html', {'form': form})


@ratelimit(key='ip', rate='5/m', method='POST', block=True)
def dang_nhap(request):
    config = get_shop_config()  # Lấy cấu hình shop
    if request.method == 'POST':
        phone = request.POST.get('phone')
        password = request.POST.get('password')
        try:
            customer = Customer.objects.get(phone=phone)
            if customer.check_password(password):  # Kiểm tra password đã hash
                request.session['customer_id'] = customer.id
                request.session['customer_name'] = customer.full_name
                return redirect('shop:trang_chu')
            else:
                messages.error(request, "Sai mật khẩu!")
        except Customer.DoesNotExist:
            messages.error(request, "Số điện thoại chưa được đăng ký!")

    # Render trang với config để tránh lỗi thiếu biến
    return render(request, 'shop/dang_nhap.html', {'config': config})


def dang_xuat(request):
    if 'customer_id' in request.session:
        del request.session['customer_id']
    if 'customer_name' in request.session:
        del request.session['customer_name']

    return redirect('shop:trang_chu')


def thanh_toan(request):
    config = get_shop_config()
    categories = Category.objects.filter(parent__isnull=True).prefetch_related('children')

    # Lấy thông tin giỏ hàng
    cart = request.session.get('cart', {})
    cart_items = []
    tong_tien = 0
    tong_so_luong = 0

    for product_id, item in cart.items():
        try:
            product = Product.objects.get(id=int(product_id))
            item_total = product.price * item['quantity']
            tong_tien += item_total
            tong_so_luong += item['quantity']
            cart_items.append({'product': product, 'quantity': item['quantity'], 'total_price': item_total})
        except Product.DoesNotExist:
            continue

    # --- LOGIC XỬ LÝ FORM THANH TOÁN ---
    # 1. Lấy thông tin khách hàng nếu đã đăng nhập
    customer_id = request.session.get('customer_id')
    customer = None
    if customer_id:
        customer = Customer.objects.filter(id=customer_id).first()

    # 2. Xử lý logic form
    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            if customer:
                # Nếu đã đăng nhập, có thể lưu thêm customer_id vào đơn hàng nếu model Order có field này
                # order.customer = customer
                pass
            order.save()
            # Xóa giỏ hàng sau khi đặt thành công
            request.session['cart'] = {}
            return redirect('shop:thanh_cong')  # Chuyển hướng đến trang thông báo thành công
    else:
        # 3. Đổ dữ liệu vào form (Nếu có đăng nhập thì điền sẵn)
        initial_data = {}
        if customer:
            initial_data = {
                'full_name': customer.full_name,
                'phone': customer.phone,
                'address': customer.address,
            }
        form = OrderForm(initial=initial_data)

    return render(request, 'shop/thanh_toan.html', {
        'config': config,
        'categories': categories,
        'cart_items': cart_items,
        'tong_tien': tong_tien,
        'tong_so_luong': tong_so_luong,
        'form': form,  # Truyền form vào template
    })


def send_telegram_notification(order, order_items):
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID

    # Tạo nội dung thông báo
    items_text = ""
    for item in order_items:
        items_text += f"- {item.product.name} (x{item.quantity}): {item.price:,.0f}đ\n"

    message = (
        f"🛒 *ĐƠN HÀNG MỚI #{order.id}*\n"
        f"👤 Khách: {order.full_name}\n"
        f"📞 SĐT: {order.phone}\n"
        f"📍 Địa chỉ: {order.address}\n"
        f"📦 Sản phẩm:\n{items_text}"
        f"💰 Tổng: *{order.total_price:,.0f}đ*"
    )

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'Markdown'
    }

    try:
        requests.post(url, data=payload, timeout=5)
    except Exception as e:
        print(f"Lỗi gửi Telegram: {e}")


def xac_nhan_don_hang(request):
    if request.method == 'POST':
        cart = request.session.get('cart', {})
        if not cart:
            return redirect('shop:gio_hang')

        # 1. Khởi tạo form với dữ liệu từ POST
        form = OrderForm(request.POST)

        # 2. Kiểm tra dữ liệu (Validation)
        if form.is_valid():
            try:
                with transaction.atomic():
                    # Lưu order nhưng chưa commit vào DB ngay để xử lý total_price
                    order = form.save(commit=False)
                    order.total_price = 0
                    order.save()

                    total_amount = 0
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

                    order.total_price = total_amount
                    order.save()

                    # Lấy danh sách item để gửi thông báo
                    order_items = OrderItem.objects.filter(order=order)

                    # GỌI THREAD GỬI TELEGRAM
                    telegram_thread = threading.Thread(
                        target=send_telegram_notification,
                        args=(order, order_items)
                    )
                    telegram_thread.start()

                del request.session['cart']
                return render(request, 'shop/xac_nhan_thanh_cong.html', {'order_id': order.id})

            except Exception as e:
                messages.error(request, str(e))
                return redirect('shop:gio_hang')
        else:
            config = get_shop_config()
            categories = Category.objects.filter(parent__isnull=True).prefetch_related('children')

            # Tính toán lại giỏ hàng cho template
            cart = request.session.get('cart', {})
            cart_items = []
            tong_tien = 0
            tong_so_luong = 0
            for product_id, item in cart.items():
                try:
                    product = Product.objects.get(id=int(product_id))
                    item_total = product.price * item['quantity']
                    tong_tien += item_total
                    tong_so_luong += item['quantity']
                    cart_items.append({'product': product, 'quantity': item['quantity'], 'total_price': item_total})
                except Product.DoesNotExist:
                    continue

            # Trả về trang thanh toán với form hiện tại (có chứa lỗi)
            messages.error(request, "Thông tin không hợp lệ. Vui lòng kiểm tra lại.")
            return render(request, 'shop/thanh_toan.html', {
                'config': config,
                'categories': categories,
                'cart_items': cart_items,
                'tong_tien': tong_tien,
                'tong_so_luong': tong_so_luong,
                'form': form  # Gửi object form chứa dữ liệu và lỗi sang template
            })

    return redirect('shop:thanh_toan')


def get_shop_config():
    config = ShopConfiguration.objects.first()
    if not config:
        config = ShopConfiguration.objects.create()
    return config


def get_top_selling_or_random(target_count=60):
    """
    Hàm lấy ra danh sách sản phẩm bán chạy nhất trong 3 tuần.
    Nếu không đủ số lượng target_count, tự động lấy ngẫu nhiên bù vào.
    """
    # Ngưỡng an toàn: Khống chế trong khoảng từ 50 đến 100
    if target_count < 50: target_count = 50
    if target_count > 100: target_count = 100

    ba_tuan_truoc = timezone.now() - timedelta(weeks=3)

    # Bước 1: Lấy danh sách sản phẩm bán chạy trong 3 tuần gần đây
    # (Đoạn này giả định cấu trúc OrderItem, nếu lỗi cấu trúc sẽ tự động bỏ qua nhờ khối try-except)
    top_products_ids = []
    try:
        # Thay thế 'OrderItem' bằng tên Model chi tiết đơn hàng thực tế của bạn nếu có
        # Ví dụ: OrderItem.objects.filter(order__created_at__gte=ba_tuan_truoc)...
        from .models import OrderItem
        top_sales = (
            OrderItem.objects.filter(created_at__gte=ba_tuan_truoc, product__available=True)
            .values('product_id')
            .annotate(total_sold=Sum('quantity'))
            .order_by('-total_sold')[:target_count]
        )
        top_products_ids = [item['product_id'] for item in top_sales]
    except Exception:
        # Nếu chưa tạo Model đơn hàng, tạm thời danh sách bán chạy trống để tránh lỗi hệ thống
        top_products_ids = []

    # Truy vấn lấy các đối tượng sản phẩm bán chạy thực tế
    products_list = list(Product.objects.filter(id__in=top_products_ids, available=True))

    # Bước 2: Nếu chưa đủ số lượng quy định, lấy thêm sản phẩm ngẫu nhiên để bù vào
    current_count = len(products_list)
    if current_count < target_count:
        needed_count = target_count - current_count
        # Lấy danh sách các sản phẩm còn lại mà chưa nằm trong nhóm bán chạy
        remaining_products = Product.objects.filter(available=True).exclude(id__in=[p.id for p in products_list])

        remaining_list = list(remaining_products)
        # Lấy ngẫu nhiên số lượng sản phẩm còn thiếu
        if len(remaining_list) >= needed_count:
            random_added = random.sample(remaining_list, needed_count)
        else:
            random_added = remaining_list  # Nếu kho không đủ hàng thì lấy hết sạch

        products_list.extend(random_added)

    return products_list


def trang_chu(request):
    config = get_shop_config()
    categories = Category.objects.all()
    banners = config.banners.all()

    is_filtered = False
    category_slug = request.GET.get('category')

    if category_slug:
        # Nếu người dùng bấm lọc danh mục: Hiển thị sản phẩm thuộc danh mục đó
        products = Product.objects.filter(category__slug=category_slug, available=True)
        is_filtered = True
    else:
        # Nếu ở trang chủ mặc định: Hiển thị 60 sản phẩm bán chạy + ngẫu nhiên phối hợp
        products = get_top_selling_or_random(target_count=60)  # Bạn có thể đổi số này từ 50-100 tùy ý

    return render(request, 'shop/trang_chu.html', {
        'config': config,
        'categories': categories,
        'products': products,
        'banners': banners,
        'is_filtered': is_filtered,
    })


def chi_tiet_san_pham(request, slug):
    config = get_shop_config()
    categories = Category.objects.all()
    product = get_object_or_404(Product, slug=slug)

    # Lấy giỏ hàng từ session
    cart = request.session.get('cart', {})
    # Lấy số lượng đã có trong giỏ (mặc định là 0 nếu chưa có)
    qty_in_cart = 0
    product_id_str = str(product.id)
    if product_id_str in cart:
        qty_in_cart = cart[product_id_str].get('quantity', 0)

    suggested_products = get_top_selling_or_random(target_count=50)

    return render(request, 'shop/chi_tiet_san_pham.html', {
        'config': config,
        'categories': categories,
        'product': product,
        'products': suggested_products,
        'qty_in_cart': qty_in_cart,  # Truyền biến này sang template
    })


def lien_he(request):
    config = get_shop_config()
    return render(request, 'shop/lien_he.html', {'config': config})


def tai_lieu(request):
    config = get_shop_config()
    categories = Category.objects.all()  # Bổ sung danh mục cho cột trái
    posts = DocumentPost.objects.all()
    return render(request, 'shop/tai_lieu.html', {
        'config': config, 'categories': categories, 'posts': posts
    })


def chi_tiet_tai_lieu(request, slug):
    config = get_shop_config()
    categories = Category.objects.all()  # Bổ sung danh mục cho cột trái
    post = get_object_or_404(DocumentPost, slug=slug)
    return render(request, 'shop/chi_tiet_tai_lieu.html', {
        'config': config, 'categories': categories, 'post': post
    })


def them_vao_gio(request, product_id):
    if request.method == 'POST':
        # 1. Lấy sản phẩm để kiểm tra tồn kho
        product = get_object_or_404(Product, id=product_id)
        qty = int(request.POST.get('quantity', 1))

        # 2. Lấy giỏ hàng hiện tại
        cart = request.session.get('cart', {})
        p_id_str = str(product_id)

        # Tính số lượng hiện có trong giỏ + số lượng muốn thêm
        current_in_cart = cart[p_id_str]['quantity'] if p_id_str in cart else 0
        total_requested = current_in_cart + qty

        # 3. KIỂM TRA TỒN KHO (Chốt chặn tại server)
        if total_requested > product.stock:
            return JsonResponse({
                'status': 'error',
                'message': f'Rất tiếc, cửa hàng chỉ còn {product.stock} sản phẩm.'
            })

        # 4. Nếu hợp lệ thì mới lưu vào giỏ hàng
        if p_id_str in cart:
            cart[p_id_str]['quantity'] += qty
        else:
            cart[p_id_str] = {
                'quantity': qty,
                'price': float(product.price)
            }

        request.session['cart'] = cart

        # Tính tổng số lượng để cập nhật giao diện
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
    return JsonResponse({'status': 'error', 'message': 'Yêu cầu không hợp lệ'}, status=400)


def gio_hang(request):
    config = get_shop_config()
    categories = Category.objects.all()
    cart = request.session.get('cart', {})

    cart_items = []
    tong_tien = 0

    for product_id, item in cart.items():
        try:
            product = Product.objects.get(id=int(product_id))
            item_total = product.price * item['quantity']
            tong_tien += item_total
            cart_items.append({
                'product': product,
                'quantity': item['quantity'],
                'total_price': item_total
            })
        except Product.DoesNotExist:
            continue

    return render(request, 'shop/gio_hang.html', {
        'config': config,
        'categories': categories,
        'cart_items': cart_items,
        'tong_tien': tong_tien
    })


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


def chinh_sach_van_chuyen(request):
    config = get_shop_config()
    categories = Category.objects.filter(parent__isnull=True)  # Hoặc query danh mục bạn muốn
    return render(request, 'shop/chinh_sach_van_chuyen.html', {
        'config': config,
        'categories': categories
    })


def chinh_sach_bao_hanh(request):
    config = get_shop_config()
    categories = Category.objects.filter(parent__isnull=True)  # Hoặc query danh mục bạn muốn
    return render(request, 'shop/chinh_sach_bao_hanh.html', {
        'config': config,
        'categories': categories
    })


def chinh_sach_doi_tra(request):
    config = get_shop_config()
    categories = Category.objects.filter(parent__isnull=True)  # Hoặc query danh mục bạn muốn
    return render(request, 'shop/chinh_sach_doi_tra.html', {
        'config': config,
        'categories': categories
    })


def chinh_sach_bao_mat(request):
    config = get_shop_config()
    categories = Category.objects.filter(parent__isnull=True)  # Hoặc query danh mục bạn muốn
    return render(request, 'shop/chinh_sach_bao_mat.html', {
        'config': config,
        'categories': categories
    })


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


# shop/views.py

def ket_qua_tim_kiem(request):
    query = request.GET.get('q', '')
    products = Product.objects.filter(name__icontains=query) if query else []

    # 1. Truy xuất danh mục cha (để sidebar nhận diện được)
    # Giả sử bạn có model Category với field 'parent'
    categories = Category.objects.filter(parent__isnull=True).prefetch_related('children')

    return render(request, 'shop/ket_qua_tim_kiem.html', {
        'products': products,
        'query': query,
        'categories': categories,  # <--- BẮT BUỘC CÓ DÒNG NÀY
        'config': get_shop_config()  # Nếu bạn có hàm lấy config
    })

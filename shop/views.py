from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from .models import Category, Product, ShopConfiguration, DocumentPost, Order, OrderItem
from datetime import timedelta
from django.utils import timezone
from django.db.models import Sum
from django.urls import reverse
from django.core.mail import send_mail
import random


def thanh_toan(request):
    config = get_shop_config()
    categories = Category.objects.filter(parent__isnull=True).prefetch_related('children')

    cart = request.session.get('cart', {})
    cart_items = []
    tong_tien = 0
    tong_so_luong = 0  # <--- THÊM BIẾN NÀY

    for product_id, item in cart.items():
        try:
            product = Product.objects.get(id=int(product_id))
            item_total = product.price * item['quantity']
            tong_tien += item_total

            # CỘNG DỒN SỐ LƯỢNG
            tong_so_luong += item['quantity']

            cart_items.append({
                'product': product,
                'quantity': item['quantity'],
                'total_price': item_total
            })
        except Product.DoesNotExist:
            continue

    return render(request, 'shop/thanh_toan.html', {
        'config': config,
        'categories': categories,
        'cart_items': cart_items,
        'tong_tien': tong_tien,
        'tong_so_luong': tong_so_luong,  # <--- TRUYỀN BIẾN NÀY VÀO TEMPLATE
    })


def xac_nhan_don_hang(request):
    if request.method == 'POST':
        config = ShopConfiguration.objects.first()
        shop_email = config.email if config else 'ritran7395@gmail.com'

        # 1. Lưu thông tin Order
        order = Order.objects.create(
            full_name=request.POST.get('full_name'),
            email=request.POST.get('email'),
            phone=request.POST.get('phone'),
            address=request.POST.get('address'),
            note=request.POST.get('note'),
            total_price=0  # Tạm tính, sẽ cập nhật sau
        )

        # 2. Lưu chi tiết sản phẩm (OrderItem)
        cart = request.session.get('cart', {})
        total = 0
        order_details_text = "\n--- Chi tiết đơn hàng ---\n"
        for p_id, item in cart.items():
            product = Product.objects.get(id=int(p_id))
            item_total = product.price * item['quantity']
            total += item_total
            order_details_text += f"- {product.name}: {item['quantity']} x {product.price:,}đ = {item_total:,}đ\n"
            OrderItem.objects.create(
                order=order,
                product=product,
                quantity=item['quantity'],
                price=product.price
            )
        order_details_text += f"-------------------------\nTổng cộng: {total:,}đ"
        # Cập nhật tổng tiền vào đơn hàng
        order.total_price = total
        order.save()

        # 3. Gửi Email thông báo cho chủ shop
        send_mail(
            subject=f'Đơn hàng mới #{order.id}',
            message=f'Khách hàng {order.full_name} vừa đặt hàng.\n'
                    f'SĐT: {order.phone}\n'
                    f'Địa chỉ: {order.address}\n'
                    f'Ghi chú: {order.note or "Không có"}\n'
                    f'{order_details_text}',  # Chèn danh sách sản phẩm vào đây
            from_email='shop@yourdomain.com',
            recipient_list=[shop_email],
        )
        # 4. Xóa giỏ hàng
        del request.session['cart']
        return render(request, 'shop/xac_nhan_thanh_cong.html', {'order_id': order.id})
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


def dang_nhap(request):
    config = get_shop_config()
    return render(request, 'shop/dang_nhap.html', {'config': config})


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

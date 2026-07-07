from .models import Product, ShopConfiguration


def customer_info(request):
    # Lấy tên khách hàng từ session
    customer_name = request.session.get('customer_name')
    return {'customer_name': customer_name}


def global_cart(request):
    # Xử lý giỏ hàng hiển thị trên Header
    cart = request.session.get('cart', {})
    cart_items = []

    for p_id, item in cart.items():
        try:
            product = Product.objects.get(id=int(p_id))
            cart_items.append({
                'product': product,
                'quantity': item['quantity']
            })
        except Product.DoesNotExist:
            continue

    return {'global_cart_items': cart_items}


def shop_global_settings(request):
    # Xử lý cấu hình website (Logo, tên shop, địa chỉ...) để dùng ở mọi nơi
    config = ShopConfiguration.objects.first()
    if not config:
        config = ShopConfiguration.objects.create()  # Tạo mặc định nếu chưa có
    return {'config': config}

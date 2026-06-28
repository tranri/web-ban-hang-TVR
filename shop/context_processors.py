# shop/context_processors.py
from .models import Product, ShopConfiguration

def shop_global_settings(request):
    config = ShopConfiguration.objects.first()
    if not config:
        config = ShopConfiguration.objects.create()
    return {
        'config': config
    }

def global_cart(request):
    cart = request.session.get('cart', {})
    global_cart_items = []
    global_tong_tien = 0

    for product_id, item in cart.items():
        try:
            product = Product.objects.get(id=int(product_id))
            item_total = product.price * item['quantity']
            global_tong_tien += item_total
            global_cart_items.append({
                'product': product,
                'quantity': item['quantity'],
                'total_price': item_total
            })
        except Product.DoesNotExist:
            continue

    return {
        'global_cart_items': global_cart_items,
        'global_tong_tien': global_tong_tien
    }
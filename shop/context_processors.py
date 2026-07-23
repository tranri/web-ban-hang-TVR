from .models import Product, ShopConfiguration, Category, Customer
from django.core.cache import cache


def customer_info(request):
    customer_name = request.session.get('customer_name')
    customer_id = request.session.get('customer_id')
    customer_points = 0

    # Get customer points if logged in
    if customer_id:
        try:
            customer = Customer.objects.get(id=customer_id)
            customer_points = customer.points
        except Customer.DoesNotExist:
            customer_points = 0

    return {
        'customer_name': customer_name,
        'customer_points': customer_points
    }


def global_cart(request):
    """Cache cart items to reduce database queries"""
    cart = request.session.get('cart', {})
    if not cart:
        return {'global_cart_items': []}

    # Batch fetch all products instead of N+1 queries
    product_ids = [int(p_id) for p_id in cart.keys()]
    products_dict = {
        p.id: p for p in Product.objects.filter(id__in=product_ids)
    }

    cart_items = []
    for p_id, item in cart.items():
        product = products_dict.get(int(p_id))
        if product:
            cart_items.append({
                'product': product,
                'quantity': item['quantity']
            })

    return {'global_cart_items': cart_items}


def shop_global_settings(request):
    """Get shop configuration with caching"""
    config = ShopConfiguration.get_config()
    return {'config': config}


def categories_list(request):
    """Cache categories - rarely change"""
    cache_key = 'shop_categories_tree'
    categories = cache.get(cache_key)

    if categories is None:
        categories = Category.objects.filter(parent__isnull=True).prefetch_related('children')
        cache.set(cache_key, list(categories), 7200)  # Cache for 2 hours

    return {'categories': categories}

from django.urls import path
from . import views

app_name = 'shop'

urlpatterns = [
    path('', views.trang_chu, name='trang_chu'),
    path('san-pham/<slug:slug>/', views.chi_tiet_san_pham, name='chi_tiet_san_pham'),  # Thêm mới
    path('lien-he/', views.lien_he, name='lien_he'),
    path('tai-lieu/', views.tai_lieu, name='tai_lieu'),
    path('tai-lieu/<slug:slug>/', views.chi_tiet_tai_lieu, name='chi_tiet_tai_lieu'),
    path('gio-hang/', views.gio_hang, name='gio_hang'),
    path('dang-nhap/', views.dang_nhap, name='dang_nhap'),
    path('add-to-cart/<int:product_id>/', views.them_vao_gio, name='them_vao_gio'),
    path('remove-from-cart/<int:product_id>/', views.xoa_khoi_gio, name='xoa_khoi_gio'),
    path('update-cart/<int:product_id>/', views.cap_nhat_gio, name='cap_nhat_gio'),
    path('chinh-sach-van-chuyen/', views.chinh_sach_van_chuyen, name='chinh_sach_van_chuyen'),
    path('chinh-sach-bao-hanh/', views.chinh_sach_bao_hanh, name='chinh_sach_bao_hanh'),
    path('chinh-sach-doi-tra/', views.chinh_sach_doi_tra, name='chinh_sach_doi_tra'),
    path('chinh-sach-bao-mat/', views.chinh_sach_bao_mat, name='chinh_sach_bao_mat'),
    path('search-api/', views.search_api, name='search_api'),
    path('ket-qua-tim-kiem/', views.ket_qua_tim_kiem, name='ket_qua_tim_kiem'),
    path('thanh-toan/', views.thanh_toan, name='thanh_toan'),
    path('xac-nhan-don-hang/', views.xac_nhan_don_hang, name='xac_nhan_don_hang'),
]

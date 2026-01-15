from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from django.views.generic import RedirectView # 引入跳轉功能

router = DefaultRouter()
router.register(r'products', views.ProductViewSet, basename='product')
router.register(r'orders', views.OrderViewSet, basename='order')

urlpatterns = [
    # 0. 解決 404：把根目錄直接導向管理後台
    path('', RedirectView.as_view(url='/owner/', permanent=False)),

    # 1. API 網址
    path('api/', include(router.urls)),

    # 2. 管理端
    path('owner/', views.owner_dashboard, name='owner_dashboard'),
    path('report-dashboard/', views.report_dashboard, name='report_dashboard'),

    # 3. 客人點餐入口 (注意：這行要放在後面，避免 slug 攔截掉其他路徑)
    path('<slug:store_slug>/', views.index, name='index'),

    # 4. 叫號看板入口
    path('status/<slug:store_slug>/', views.order_status_board, name='status_board'),
]
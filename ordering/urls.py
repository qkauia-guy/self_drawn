from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# API 路由
router = DefaultRouter()
router.register(r'products', views.ProductViewSet, basename='product')
router.register(r'orders', views.OrderViewSet, basename='order')

urlpatterns = [
    # 1. API 網址 (維持原樣，但 View 內部現在會吃 ?store= 參數)
    path('api/', include(router.urls)),

    # 2. 管理端 (老闆進去後再選擇分店)
    path('owner/', views.owner_dashboard, name='owner_dashboard'),
    path('report-dashboard/', views.report_dashboard, name='report_dashboard'),

    # 3. 客人點餐入口 (關鍵修改：將 slug 放在網址最前面)
    # 例如：http://127.0.0.1:8000/dajin/
    # 例如：http://127.0.0.1:8000/neipu/
    path('<slug:store_slug>/', views.index, name='index'),

    # 4. 叫號看板入口
    # 例如：http://127.0.0.1:8000/status/dajin/
    path('status/<slug:store_slug>/', views.order_status_board, name='status_board'),

    # 5. 預設首頁 (選填：可以導向一個選擇分店的頁面)
    # path('', views.store_selector, name='store_selector'),
]
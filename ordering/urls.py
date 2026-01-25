# urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from django.views.generic import RedirectView

router = DefaultRouter()
router.register(r"products", views.ProductViewSet, basename="product")
router.register(r"orders", views.OrderViewSet, basename="order")

# urls.py

urlpatterns = [
    # ... (原有的 API 與固定路徑) ...
    path("api/stores/", views.store_list, name="store_list"),
    path(
        "api/stores/<slug:store_slug>/reset_daily/",
        views.reset_daily_orders,
        name="reset_daily",
    ),
    path("api/", include(router.urls)),
    # ... (原有的 owner 與 dashboard) ...
    path("", RedirectView.as_view(url="/owner/", permanent=False)),
    path("owner/", views.owner_dashboard, name="owner_dashboard"),
    path("dashboard/", views.report_dashboard, name="report_dashboard"),
    path("backend/", views.mobile_admin, name="mobile_admin"),
    # 給 HTMX 用的 API，用來快速更新商品
    path(
        "backend/api/update/<int:pk>/",
        views.quick_update_product,
        name="quick_update_product",
    ),
    # 用來新增商品的 API
    path("backend/api/create/", views.create_product, name="create_product"),
    path(
        "backend/api/category/create/",
        views.api_create_category,
        name="api_create_category",
    ),
    path(
        "backend/api/category/update/<int:pk>/",
        views.api_update_category,
        name="api_update_category",
    ),
    path(
        "backend/api/get-categories-options/",
        views.api_get_categories_options,
        name="api_get_categories_options",
    ),
    # ==========================================
    # ... (原有的其他頁面) ...
    path("status/<slug:store_slug>/", views.order_status_board, name="status_board"),
    path("about/", views.about, name="about"),
    path("<slug:store_slug>/", views.index, name="index"),
]

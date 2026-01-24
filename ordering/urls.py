# urls.py
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from django.views.generic import RedirectView

router = DefaultRouter()
router.register(r"products", views.ProductViewSet, basename="product")
router.register(r"orders", views.OrderViewSet, basename="order")

urlpatterns = [
    # 1. API 與固定路徑
    path("api/stores/", views.store_list, name="store_list"),
    # ✅ 新增這行：處理營業結束歸零 (必須放在 api/ 之前)
    path(
        "api/stores/<slug:store_slug>/reset_daily/",
        views.reset_daily_orders,
        name="reset_daily",
    ),
    path("api/", include(router.urls)),
    # 2. 頁面導向
    path("", RedirectView.as_view(url="/owner/", permanent=False)),
    path("owner/", views.owner_dashboard, name="owner_dashboard"),
    path("dashboard/", views.report_dashboard, name="report_dashboard"),
    # 3. 叫號看板
    path("status/<slug:store_slug>/", views.order_status_board, name="status_board"),
    # 4. 關於頁面
    path("about/", views.about, name="about"),
    # 5. 客人點餐入口
    path("<slug:store_slug>/", views.index, name="index"),
]

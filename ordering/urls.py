from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from django.views.generic import RedirectView

router = DefaultRouter()
router.register(r"products", views.ProductViewSet, basename="product")
router.register(r"orders", views.OrderViewSet, basename="order")

urlpatterns = [
    # 1. 先處理精確路徑 (API 與固定路徑)
    path("api/stores/", views.store_list, name="store_list"),
    path("api/", include(router.urls)),
    # 2. 頁面導向
    path("", RedirectView.as_view(url="/owner/", permanent=False)),
    path("owner/", views.owner_dashboard, name="owner_dashboard"),
    path("report-dashboard/", views.report_dashboard, name="report_dashboard"),
    # 3. 叫號看板
    path("status/<slug:store_slug>/", views.order_status_board, name="status_board"),
    # 4. 關於頁面
    path("about/", views.about, name="about"),
    # 5. 客人點餐入口（這行務必放最後，因為它會匹配所有單層路徑）
    path("<slug:store_slug>/", views.index, name="index"),
]

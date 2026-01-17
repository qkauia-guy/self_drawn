from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from django.views.generic import RedirectView

router = DefaultRouter()
router.register(r"products", views.ProductViewSet, basename="product")
router.register(r"orders", views.OrderViewSet, basename="order")

urlpatterns = [
    # 0) 根目錄導向管理端
    path("", RedirectView.as_view(url="/owner/", permanent=False)),
    # 1) API
    path("api/", include(router.urls)),
    # 2) 管理端頁面
    path("owner/", views.owner_dashboard, name="owner_dashboard"),
    path("report-dashboard/", views.report_dashboard, name="report_dashboard"),
    # 3) 叫號看板
    path("status/<slug:store_slug>/", views.order_status_board, name="status_board"),
    # 🔥 修正：把 about 移到 slug 之前
    path("about/", views.about, name="about"),
    # 4) 客人點餐入口（這行要放最後，因為它會吃掉所有單層路徑）
    path("<slug:store_slug>/", views.index, name="index"),
]

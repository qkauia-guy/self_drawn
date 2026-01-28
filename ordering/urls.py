from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from django.views.generic import RedirectView

# 1. 設定 DRF Router (自動產生 RESTful API)
router = DefaultRouter()
router.register(r"products", views.ProductViewSet, basename="product")
router.register(r"orders", views.OrderViewSet, basename="order")

urlpatterns = [
    # ==========================================
    # 1. API 接口 (供前端 JS / Ajax 呼叫)
    # ==========================================
    # 包含 /api/orders/ 和 /api/products/
    path("api/", include(router.urls)),
    # 取得分店列表
    path("api/stores/", views.store_list, name="store_list"),
    # 每日結算 API (清除流水號/歸檔)
    path(
        "api/stores/<slug:store_slug>/reset_daily/",
        views.reset_daily_orders,
        name="reset_daily",
    ),
    # ==========================================
    # 2. 管理後台頁面 (HTML Render)
    # ==========================================
    # 電腦版接單後台 (店長用)
    path("owner/", views.owner_dashboard, name="owner_dashboard"),
    # 財務報表中心
    path("dashboard/", views.report_dashboard, name="report_dashboard"),
    # 手機版商品管理 (新增/修改/上下架)
    path("backend/", views.mobile_admin, name="mobile_admin"),
    # 快速進貨頁面 (庫存管理)
    path("backend/restock/", views.restock_page, name="restock_page"),
    # ==========================================
    # 3. 後台功能操作 API (HTMX / Form Post)
    # ==========================================
    # 商品操作
    path(
        "backend/api/update/<int:pk>/",
        views.quick_update_product,
        name="quick_update_product",
    ),  # 快速更新(價格/庫存/開關)
    path(
        "backend/api/create/", views.create_product, name="create_product"
    ),  # 建立商品
    path(
        "backend/api/batch_restock/", views.batch_restock, name="batch_restock"
    ),  # 批次進貨
    # 分類操作
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
    # 4. 公開頁面 (顧客/現場顯示)
    # ==========================================
    # 現場叫號看板 (全螢幕/語音)
    path("status/<slug:store_slug>/", views.order_status_board, name="status_board"),
    # 關於頁面 / 分店選擇入口
    path("about/", views.about, name="about"),
    # ==========================================
    # 5. 根路徑與動態路由 (必須放在最後！)
    # ==========================================
    # 首頁預設導向 (目前導向 owner，可依需求改為 about 或其他)
    path("", RedirectView.as_view(url="/owner/", permanent=False)),
    # 顧客自助點餐頁面 (例如: /dajin/, /neipu/)
    # 注意：這是一個「捕獲所有字串」的規則，必須放在最下面，否則會把上面的 backend/ owner/ 都攔截走
    path("<slug:store_slug>/", views.index, name="index"),
]

from django.contrib import admin
from django.utils.html import format_html
from django.db import models
from .models import Product, Order, Store, Category  # ✅ 記得引入 Category
from django_json_widget.widgets import JSONEditorWidget


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    list_editable = ("is_active",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """
    ✅ 新增：分類管理介面
    特色：可以直接在列表頁調整順序 (sort_order)，方便管理菜單排序。
    """

    list_display = ("name", "slug", "store", "sort_order", "product_count", "is_active")
    list_editable = ("sort_order", "is_active")  # 讓您直接在列表改順序
    list_filter = ("store", "is_active")
    search_fields = ("name", "slug")
    ordering = ("store", "sort_order")  # 預設依照分店與設定的順序排列

    def product_count(self, obj):
        # 顯示該分類下有多少商品
        count = obj.products.count()
        return f"{count} 項商品"

    product_count.short_description = "商品數量"


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """
    ✅ 優化：商品管理介面
    特色：加入 select_related 優化資料庫查詢，並支援用分類篩選。
    """

    # 使用 select_related 預先抓取關聯資料，避免 N+1 查詢問題，提升後台速度
    list_select_related = ("category", "store")

    list_display = (
        "category",  # 這裡現在會顯示 Category 物件名稱
        "name",
        "store",
        "price",
        "stock",
        "is_active",
        "flavor_options",
        "display_inventory_status",
    )

    # 點擊商品名稱進入編輯
    list_display_links = ("name",)

    # 在列表頁直接修改這些欄位
    list_editable = ("category", "price", "stock", "is_active", "flavor_options")

    # 篩選器
    list_filter = ("store", "category", "is_active")

    # 搜尋欄位 (支援搜尋商品名與分類名)
    search_fields = ("name", "category__name")

    # 預設排序
    ordering = ("category__sort_order", "id")

    def display_inventory_status(self, obj):
        if obj.stock <= 0:
            return format_html(
                '<span style="color: #d63031; font-weight: bold;">{}</span>',
                "🚫 已售完",
            )
        elif obj.stock <= 5:
            return format_html(
                '<span style="color: #e17055; font-weight: bold;">⚠️ 剩餘 {}</span>',
                obj.stock,
            )
        return format_html('<span style="color: #27ae60;">{}</span>', "OK")

    display_inventory_status.short_description = "庫存狀態"


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    # (保持您原本優秀的設定)
    list_display = (
        "display_id",
        "store",
        "phone_tail",
        "payment_method",
        "status",
        "display_status_badge",
        "total",
        "display_refund_badge",
        "display_linepay_transaction_copy",
        "display_linepay_refund_transaction_copy",
        "created_at",
    )
    list_display_links = ("display_id",)
    list_editable = ("status",)
    list_filter = ("store", "status", "payment_method", "created_at")
    ordering = ("-id",)

    formfield_overrides = {models.JSONField: {"widget": JSONEditorWidget}}

    fieldsets = (
        (
            "基本資訊",
            {"fields": ("store", "status", "phone_tail", "payment_method", "total")},
        ),
        (
            "訂單明細 (JSON 編輯器)",
            {
                "fields": ("items",),
                "description": "提示：若手動修改數量或金額，請確保格式正確。",
            },
        ),
        (
            "LINE Pay / 退款資訊",
            {
                "fields": (
                    "linepay_transaction_id",
                    "linepay_refunded",
                    "linepay_refund_transaction_id",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "紀錄時間",
            {"fields": ("created_at", "completed_at"), "classes": ("collapse",)},
        ),
    )

    readonly_fields = (
        "created_at",
        "completed_at",
        "linepay_transaction_id",
        "linepay_refunded",
        "linepay_refund_transaction_id",
    )

    # ---------- common display helpers ----------
    def display_id(self, obj):
        return format_html(
            '<span style="font-size: 14px; font-weight: bold;">#{}</span>', obj.id
        )

    display_id.short_description = "單號"

    def display_status_badge(self, obj):
        colors = {
            "pending": "#ff4d4d",  # 紅 (確認中)
            "confirmed": "#007bff",  # 藍 (已成立)
            "preparing": "#f39c12",  # 橘 (製作中)
            "completed": "#2ecc71",  # 綠 (完成-發送通知)
            "arrived": "#d63031",  # 深紅 (客人在櫃檯)
            "final": "#636e72",  # 灰 (結案)
            "cancelled": "#2d3436",  # 黑 (取消)
        }
        # 兼容原本的 CHOICES 顯示
        status_dict = dict(obj.STATUS_CHOICES)
        status_text = status_dict.get(obj.status, obj.status)

        return format_html(
            '<span style="background: {}; color: white; padding: 2px 10px; border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>',
            colors.get(obj.status, "#eee"),
            status_text,
        )

    display_status_badge.short_description = "狀態預覽"

    def display_refund_badge(self, obj):
        if obj.payment_method != "linepay":
            return "—"
        if obj.linepay_refunded:
            return "✅ 已退款"
        if obj.linepay_transaction_id:
            return "⚠️ 未退款"
        return "（未付款資訊）"

    display_refund_badge.short_description = "退款狀態"

    # ---------- copy widget ----------
    def _copy_input(self, *, value, input_id, placeholder="—"):
        if not value:
            return format_html(
                '<span style="color: var(--body-quiet-color);">{}</span>',
                placeholder,
            )

        return format_html(
            """
            <div style="display:inline-flex; gap:6px; align-items:center;">
              <input id="{0}"
                     type="text"
                     value="{1}"
                     readonly
                     style="
                       width: auto;
                       max-width: 520px;
                       font-family: ui-monospace, monospace;
                       font-size: 12px;
                       padding: 1px 6px;
                       line-height: 1.2;
                       border: 1px solid var(--border-color);
                       border-radius: 6px;
                       background: var(--body-bg);
                       color: var(--body-fg);
                     "
                     onclick="this.select();"
              />
              <button type="button"
                      style="
                        padding: 1px 6px;
                        line-height: 1.2;
                        font-size: 11px;
                        border-radius: 6px;
                        border: 1px solid var(--border-color);
                        background: var(--body-bg);
                        color: var(--body-fg);
                        cursor: pointer;
                      "
                      onclick="
                        (function(){{
                          var el = document.getElementById('{0}');
                          if(!el) return;
                          var txt = el.value || '';
                          if (navigator.clipboard && navigator.clipboard.writeText) {{
                            navigator.clipboard.writeText(txt).then(function(){{}}, function(){{}});
                          }} else {{
                            el.focus(); el.select();
                            try {{ document.execCommand('copy'); }} catch(e) {{}}
                          }}
                        }})();
                      "
              >複製</button>
            </div>
            """,
            input_id,
            value,
        )

    def display_linepay_transaction_copy(self, obj):
        if obj.payment_method != "linepay":
            return "—"
        return self._copy_input(
            value=obj.linepay_transaction_id,
            input_id=f"pay-tid-{obj.id}",
            placeholder="（無）",
        )

    display_linepay_transaction_copy.short_description = "原交易號(可複製)"

    def display_linepay_refund_transaction_copy(self, obj):
        if obj.payment_method != "linepay":
            return "—"
        return self._copy_input(
            value=obj.linepay_refund_transaction_id,
            input_id=f"refund-tid-{obj.id}",
            placeholder="（未退款）",
        )

    display_linepay_refund_transaction_copy.short_description = "退款交易號(可複製)"

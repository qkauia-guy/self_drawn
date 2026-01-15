from django.contrib import admin
from django.utils.html import format_html
from django.db import models
from .models import Product, Order, Store

# 匯入 JSON 編輯器套件
from django_json_widget.widgets import JSONEditorWidget

@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    """分店管理"""
    list_display = ('name', 'slug', 'is_active')
    list_editable = ('is_active',)
    prepopulated_fields = {'slug': ('name',)}

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """商品管理 - 支持列表直接改庫存"""
    list_display = ('name', 'store', 'price', 'stock', 'is_active', 'display_inventory_status')
    list_editable = ('price', 'stock', 'is_active')
    list_filter = ('store', 'is_active')
    search_fields = ('name',)
    
    def display_inventory_status(self, obj):
        """庫存視覺化狀態"""
        if obj.stock <= 0:
            return format_html('<span style="color: #d63031; font-weight: bold;">🚫 已售完</span>')
        elif obj.stock <= 5:
            return format_html('<span style="color: #e17055; font-weight: bold;">⚠️ 剩餘 {}</span>', obj.stock)
        return format_html('<span style="color: #27ae60;">OK</span>')
    display_inventory_status.short_description = "庫存狀態"

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """訂單管理 - 整合狀態快速切換與視覺標籤"""
    
    # 重要修正：status 必須同時存在於 list_display 與 list_editable
    list_display = (
        'display_id', 
        'store', 
        'phone_tail', 
        'status',               # 這是可編輯的下拉選單
        'display_status_badge',  # 這是純顯示的彩色標籤
        'total', 
        'created_at'
    )
    list_display_links = ('display_id',) 
    list_editable = ('status',)  # 讓老闆在清單頁就能直接切換狀態並儲存
    list_filter = ('store', 'status', 'created_at')
    ordering = ('-id',)

    # 套用 JSON 編輯器 (items 欄位)
    formfield_overrides = {
        models.JSONField: {'widget': JSONEditorWidget},
    }

    # 詳情頁配置
    fieldsets = (
        ("基本資訊", {
            'fields': ('store', 'status', 'phone_tail', 'total')
        }),
        ("訂單明細 (JSON 編輯器)", {
            'fields': ('items',),
            'description': '提示：若手動修改數量或金額，請確保格式正確，儲存後系統將自動重新計算。'
        }),
        ("紀錄時間", {
            'fields': ('created_at', 'completed_at'),
            'classes': ('collapse',),
        }),
    )
    readonly_fields = ('created_at', 'completed_at')

    # --- 自定義方法 ---

    def display_id(self, obj):
        return format_html('<span style="font-size: 14px; font-weight: bold;">#{}</span>', obj.id)
    display_id.short_description = "單號"

    def display_status_badge(self, obj):
        """根據狀態顯示不同顏色的標籤，輔助快速辨識"""
        colors = {
            'pending': '#ff4d4d',    # 紅色
            'confirmed': '#007bff',  # 藍色
            'preparing': '#f39c12',  # 橘色
            'completed': '#2ecc71',  # 綠色
            'arrived': '#9b59b6',    # 紫色
            'final': '#636e72',      # 灰色
            'cancelled': '#2d3436',  # 黑色
        }
        status_dict = dict(obj.STATUS_CHOICES)
        status_text = status_dict.get(obj.status, obj.status)
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 10px; border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>',
            colors.get(obj.status, '#eee'),
            status_text
        )
    display_status_badge.short_description = "狀態預覽"
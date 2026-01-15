from django.contrib import admin
from django.utils.html import format_html
from django.db import models
from .models import Product, Order, Store
from django_json_widget.widgets import JSONEditorWidget

@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active')
    list_editable = ('is_active',)
    prepopulated_fields = {'slug': ('name',)}

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'store', 'price', 'stock', 'is_active', 'display_inventory_status')
    list_editable = ('price', 'stock', 'is_active')
    list_filter = ('store', 'is_active')
    search_fields = ('name',)
    
    def display_inventory_status(self, obj):
        """庫存視覺化狀態 - 修正 Django 6.0 崩潰點"""
        if obj.stock <= 0:
            # 修正：加上 {} 並把文字移到後方參數
            return format_html('<span style="color: #d63031; font-weight: bold;">{}</span>', "🚫 已售完")
        elif obj.stock <= 5:
            return format_html('<span style="color: #e17055; font-weight: bold;">⚠️ 剩餘 {}</span>', obj.stock)
        
        # 修正：加上 {} 並把文字移到後方參數
        return format_html('<span style="color: #27ae60;">{}</span>', "OK")
    display_inventory_status.short_description = "庫存狀態"

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        'display_id', 
        'store', 
        'phone_tail', 
        'status',               
        'display_status_badge',  
        'total', 
        'created_at'
    )
    list_display_links = ('display_id',) 
    list_editable = ('status',)  
    list_filter = ('store', 'status', 'created_at')
    ordering = ('-id',)

    formfield_overrides = {
        models.JSONField: {'widget': JSONEditorWidget},
    }

    fieldsets = (
        ("基本資訊", {'fields': ('store', 'status', 'phone_tail', 'total')}),
        ("訂單明細 (JSON 編輯器)", {
            'fields': ('items',),
            'description': '提示：若手動修改數量或金額，請確保格式正確。'
        }),
        ("紀錄時間", {'fields': ('created_at', 'completed_at'), 'classes': ('collapse',)}),
    )
    readonly_fields = ('created_at', 'completed_at')

    def display_id(self, obj):
        return format_html('<span style="font-size: 14px; font-weight: bold;">#{}</span>', obj.id)
    display_id.short_description = "單號"

    def display_status_badge(self, obj):
        """還原正確的彩色標籤邏輯，並修正潛在崩潰點"""
        colors = {
            'pending': '#ff4d4d', 'confirmed': '#007bff', 'preparing': '#f39c12',
            'completed': '#2ecc71', 'arrived': '#d63031', 'final': '#636e72', 'cancelled': '#2d3436',
        }
        status_dict = dict(obj.STATUS_CHOICES)
        status_text = status_dict.get(obj.status, obj.status)
        
        # 確保 format_html 的字串裡有兩個 {} 對應後面的顏色與文字
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 10px; border-radius: 12px; font-size: 11px; font-weight: bold;">{}</span>',
            colors.get(obj.status, '#eee'),
            status_text
        )
    display_status_badge.short_description = "狀態預覽"
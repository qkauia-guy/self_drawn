from django.contrib import admin
from .models import Product, Order # 從 models 匯入，不要在這邊定義

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'price', 'description')

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    # 將 ID 放在最前面，並加粗顯示
    list_display = ('id', 'phone_tail', 'status', 'total', 'created_at')
    list_display_links = ('id',) # 點擊單號進入詳情
    list_editable = ('status',)
    ordering = ('-id',) # 最新的訂單排在最上面
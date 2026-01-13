from rest_framework import serializers
from .models import Product, Order

class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = '__all__'

class OrderSerializer(serializers.ModelSerializer):
    # 明確指定 id 為可見欄位
    id = serializers.ReadOnlyField()

    class Meta:
        model = Order
        # 確保所有老闆面板需要的欄位都在這裡
        fields = ['id', 'phone_tail', 'items', 'subtotal', 'total', 'status', 'created_at']
        
        # 移除 'status'，只保留不允許客人/老闆手動修改的系統欄位
        # status 必須是可以被修改的（Writable），老闆面板的 PATCH 才會生效
        read_only_fields = ['id', 'created_at']

    def validate_items(self, value):
        """簡單檢查品項格式是否為列表"""
        if not isinstance(value, list):
            raise serializers.ValidationError("品項必須是列表格式")
        return value
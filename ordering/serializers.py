from rest_framework import serializers
from .models import Product, Order


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = "__all__"


class OrderSerializer(serializers.ModelSerializer):
    id = serializers.ReadOnlyField()
    store_slug = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = Order
        fields = [
            "id",
            "phone_tail",
            "items",
            "subtotal",
            "total",
            "status",
            "created_at",
            "payment_method",
            "store_slug",
            # ✅ 新增：讓前端/後台查得到 LINE Pay 交易/退款狀態
            "linepay_transaction_id",
            "linepay_refunded",
            "linepay_refund_transaction_id",
        ]
        read_only_fields = [
            "id",
            "created_at",
            # ✅ 建議：交易/退款欄位不要讓前端 PATCH 改掉（只能由後端寫入）
            "linepay_transaction_id",
            "linepay_refunded",
            "linepay_refund_transaction_id",
        ]

    def validate_items(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("品項必須是列表格式")
        return value

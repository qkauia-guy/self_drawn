from rest_framework import serializers
from .models import Product, Order, Category, Store


# --- 分類 Serializer ---
class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "slug", "sort_order"]


# --- 商品 Serializer ---
class ProductSerializer(serializers.ModelSerializer):
    # 讓 API 回傳 category 的 slug (例如 'drink')
    category = serializers.SlugRelatedField(
        slug_field="slug", queryset=Category.objects.all()
    )

    # 顯示中文名稱與排序 (唯讀)
    category_name = serializers.CharField(source="category.name", read_only=True)
    category_sort_order = serializers.IntegerField(
        source="category.sort_order", read_only=True
    )

    class Meta:
        model = Product
        fields = "__all__"


# --- 訂單 Serializer (修正重點：加入 daily_serial) ---
class OrderSerializer(serializers.ModelSerializer):
    id = serializers.ReadOnlyField()
    # write_only=True 表示前端寫入時需要，但後端回傳時不顯示
    store_slug = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "daily_serial",  # ✨ 新增：回傳當日流水號 (1, 2, 3...)
            "phone_tail",
            "items",
            "subtotal",
            "total",
            "status",
            "created_at",
            "payment_method",
            "store_slug",
            "linepay_transaction_id",
            "linepay_refunded",
            "linepay_refund_transaction_id",
        ]
        read_only_fields = [
            "id",
            "daily_serial",  # ✨ 新增：此欄位由後端自動產生，前端不可修改
            "created_at",
            "linepay_transaction_id",
            "linepay_refunded",
            "linepay_refund_transaction_id",
            "subtotal",
            "total",
        ]

    def validate_items(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("品項必須是列表格式")
        return value

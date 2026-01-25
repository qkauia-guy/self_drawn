from django.db import models
from django.utils import timezone
from django.db import transaction


class Store(models.Model):
    """分店資訊"""

    name = models.CharField(max_length=50, verbose_name="分店名稱")
    slug = models.SlugField(
        unique=True, verbose_name="網址辨識碼", help_text="例如：main 或 branch1"
    )
    is_active = models.BooleanField(default=True, verbose_name="是否營業中")

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = "分店"
        verbose_name_plural = "分店管理"


class Category(models.Model):
    """商品分類"""

    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="categories",
        verbose_name="所屬分店",
    )
    name = models.CharField(
        max_length=50, verbose_name="分類名稱", help_text="例如：飲品系列"
    )
    slug = models.SlugField(
        max_length=50,
        verbose_name="分類代碼",
        help_text="對應前端 ID，例如：drink, tanghulu",
    )
    sort_order = models.PositiveIntegerField(default=0, verbose_name="顯示順序")
    is_active = models.BooleanField(default=True, verbose_name="是否啟用")

    class Meta:
        verbose_name = "商品分類"
        verbose_name_plural = "分類管理"
        ordering = ["sort_order"]
        unique_together = ["store", "slug"]

    def __str__(self):
        return f"{self.name}"


class Product(models.Model):
    """商品資訊"""

    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="products",
        verbose_name="所屬分店",
    )

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name="商品分類",
        null=True,
        blank=True,
    )

    name = models.CharField(max_length=50, verbose_name="商品名稱")
    price = models.PositiveIntegerField(verbose_name="單價(元)")
    description = models.CharField(
        max_length=100, blank=True, verbose_name="短描述(如：口味二選一)"
    )

    flavor_options = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="口味選項",
        help_text="請用逗號隔開。例：紅豆,花生,芝麻",
    )

    stock = models.IntegerField(default=99, verbose_name="剩餘庫存")
    is_active = models.BooleanField(default=True, verbose_name="是否供應")

    class Meta:
        verbose_name = "商品"
        verbose_name_plural = "商品管理"
        ordering = ["category__sort_order", "id"]

    def __str__(self):
        cat_name = self.category.name if self.category else "未分類"
        return f"[{cat_name}] {self.name}"

    @property
    def is_sold_out(self):
        return not self.is_active or self.stock <= 0

    # 🔥🔥🔥 重點修改：覆寫 save 方法 🔥🔥🔥
    def save(self, *args, **kwargs):
        # 邏輯：只要庫存 <= 0，強制將 is_active 設為 False (下架)
        if self.stock <= 0:
            self.is_active = False

        # 備註：通常"不建議"寫「庫存>0 自動上架」，
        # 因為有時候店員補庫存只是先輸入，但還沒準備好要賣。

        # 執行原本的儲存動作
        super().save(*args, **kwargs)


class Order(models.Model):
    STATUS_CHOICES = [
        ("pending", "訂單確認中"),
        ("confirmed", "訂單已成立"),
        ("preparing", "訂單製作中"),
        ("completed", "訂單完成"),
        ("arrived", "客人已到櫃檯"),
        ("final", "交易結案"),
        ("cancelled", "已取消"),
    ]

    PAYMENT_CHOICES = [
        ("cash", "現金"),
        ("linepay", "LINE Pay"),
    ]

    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="orders", verbose_name="所屬分店"
    )
    phone_tail = models.CharField(
        max_length=10, verbose_name="手機後4碼"
    )  # 加大長度避免錯誤
    payment_method = models.CharField(
        max_length=10, choices=PAYMENT_CHOICES, default="cash", verbose_name="付款方式"
    )

    items = models.JSONField(default=list, verbose_name="訂單內容")
    subtotal = models.PositiveIntegerField(default=0, verbose_name="小計")
    total = models.PositiveIntegerField(default=0, verbose_name="總額")

    # LINE Pay 相關
    linepay_transaction_id = models.CharField(
        max_length=100, blank=True, null=True, verbose_name="LINE Pay 交易號"
    )
    linepay_refunded = models.BooleanField(default=False, verbose_name="已退款")
    linepay_refund_transaction_id = models.CharField(
        max_length=100, blank=True, null=True, verbose_name="退款交易號"
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
        verbose_name="訂單狀態",
    )

    created_at = models.DateTimeField(default=timezone.now, verbose_name="建立時間")
    completed_at = models.DateTimeField(null=True, blank=True, verbose_name="完成時間")

    class Meta:
        verbose_name = "訂單"
        verbose_name_plural = "訂單管理"
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.store.name}] 訂單 #{self.id} - {self.phone_tail}"

    def update_total_from_json(self):
        """從 JSONField 重新計算總額"""
        new_total = 0
        if self.items:
            for item in self.items:
                price = int(item.get("price", 0))
                qty = int(item.get("quantity", 0))
                new_total += price * qty
        self.subtotal = new_total
        self.total = new_total

    def restore_stock(self):
        """取消訂單時歸還庫存"""
        with transaction.atomic():
            if self.items:
                for item in self.items:
                    product_id = item.get("id")
                    qty = int(item.get("quantity", 0))
                    if product_id:
                        Product.objects.filter(id=product_id).update(
                            stock=models.F("stock") + qty
                        )

    def save(self, *args, **kwargs):
        self.update_total_from_json()

        if self.pk:
            try:
                old_order = Order.objects.get(pk=self.pk)
                if old_order.status != "cancelled" and self.status == "cancelled":
                    self.restore_stock()
            except Order.DoesNotExist:
                pass

        if self.status in ["completed", "final"] and not self.completed_at:
            self.completed_at = timezone.now()

        super().save(*args, **kwargs)

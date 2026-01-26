from django.db import models
from django.utils import timezone


# ==========================================
# 1. 門市 (Store)
# ==========================================
class Store(models.Model):
    """分店資訊"""

    name = models.CharField(max_length=50, verbose_name="分店名稱")
    slug = models.SlugField(
        unique=True, verbose_name="網址辨識碼", help_text="例如：main 或 branch1"
    )
    is_active = models.BooleanField(default=True, verbose_name="是否營業中")
    enable_linepay = models.BooleanField(default=True, verbose_name="啟用 LINE Pay")

    class Meta:
        verbose_name = "分店"
        verbose_name_plural = "分店管理"

    def __str__(self):
        return self.name


# ==========================================
# 2. 分類 (Category)
# ==========================================
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
        # 關鍵修正：確保同一間店內的 slug 不重複，但不同店可以使用相同的 slug (如 'drink')
        unique_together = ["store", "slug"]

    def __str__(self):
        return f"[{self.store.name}] {self.name}"


# ==========================================
# 3. 商品 (Product)
# ==========================================
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
        return f"[{self.store.name}] {self.name}"

    @property
    def is_sold_out(self):
        """前端判斷顯示用：是否售完或下架"""
        return not self.is_active or self.stock <= 0


# ==========================================
# 4. 訂單 (Order)
# ==========================================
class Order(models.Model):
    STATUS_CHOICES = [
        ("pending", "訂單確認中"),  # 剛建立 / 待付款
        ("confirmed", "訂單已成立"),  # 已付款 / 店家已接單
        ("preparing", "訂單製作中"),
        ("completed", "訂單完成"),  # 製作完成
        ("arrived", "客人已到櫃檯"),  # 用於叫號通知
        ("final", "交易結案"),  # 雙方銀貨兩訖
        ("cancelled", "已取消"),
        ("archived", "已歸檔"),  # 隔日結算後的歷史資料
    ]

    PAYMENT_CHOICES = [
        ("cash", "現金"),
        ("linepay", "LINE Pay"),
    ]

    store = models.ForeignKey(
        Store, on_delete=models.CASCADE, related_name="orders", verbose_name="所屬分店"
    )
    phone_tail = models.CharField(max_length=10, verbose_name="手機後4碼")
    payment_method = models.CharField(
        max_length=10, choices=PAYMENT_CHOICES, default="cash", verbose_name="付款方式"
    )

    # 訂單內容 (Snapshot)
    items = models.JSONField(default=list, verbose_name="訂單內容")

    subtotal = models.PositiveIntegerField(default=0, verbose_name="小計")
    total = models.PositiveIntegerField(default=0, verbose_name="總額")

    # LINE Pay 相關欄位
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
        return f"[{self.store.name}] #{self.id} ({self.get_status_display()})"

    def update_total_from_json(self):
        """
        從 items JSON 欄位重新計算 subtotal 與 total。
        僅做數值計算，不涉及資料庫寫入或庫存變更。
        """
        new_total = 0
        if self.items and isinstance(self.items, list):
            for item in self.items:
                try:
                    price = int(item.get("price", 0))
                    # 兼容 quantity 或 qty 鍵名
                    qty = int(item.get("quantity") or item.get("qty") or 0)
                    new_total += price * qty
                except (ValueError, TypeError):
                    continue
        self.subtotal = new_total
        self.total = new_total

    def save(self, *args, **kwargs):
        """
        覆寫 save 方法：
        1. 自動計算總金額 (確保資料一致性)。
        2. 自動填寫完成時間。
        注意：這裡已移除所有「庫存還原」邏輯，避免與 ViewSet 衝突。
        """
        # 1. 計算金額
        self.update_total_from_json()

        # 2. 若狀態變為完成/結案，且沒有時間戳記，則自動填入
        if self.status in ["completed", "final"] and not self.completed_at:
            self.completed_at = timezone.now()

        super().save(*args, **kwargs)

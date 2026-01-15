from django.db import models
from django.utils import timezone
from django.db import transaction

class Store(models.Model):
    """分店資訊"""
    name = models.CharField(max_length=50, verbose_name='分店名稱')
    slug = models.SlugField(unique=True, verbose_name='網址辨識碼', help_text="例如：main 或 branch1")
    is_active = models.BooleanField(default=True, verbose_name='是否營業中')

    def __str__(self):
        return self.name


class Product(models.Model):
    """商品資訊（關聯分店）"""
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='products', verbose_name='所屬分店')
    name = models.CharField(max_length=50, verbose_name='商品名稱')
    price = models.PositiveIntegerField(verbose_name='單價(元)')
    description = models.CharField(max_length=100, blank=True, verbose_name='描述')
    
    # --- 庫存功能 ---
    stock = models.IntegerField(default=99, verbose_name='剩餘庫存')
    is_active = models.BooleanField(default=True, verbose_name='是否供應')

    def __str__(self):
        return f"[{self.store.name}] {self.name}"

    @property
    def is_sold_out(self):
        """判斷是否售完或手動停售"""
        return not self.is_active or self.stock <= 0


class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', '訂單確認中'),
        ('confirmed', '訂單已成立'),
        ('preparing', '訂單製作中'),
        ('completed', '訂單完成'),
        ('arrived', '客人已到櫃檯'),
        ('final', '交易結案'),
        ('cancelled', '已取消'),
    ]

    # --- 新增付款方式選項 ---
    PAYMENT_CHOICES = [
        ('cash', '現金'),
        ('linepay', 'LINE Pay'),
    ]

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='orders', verbose_name='所屬分店')
    phone_tail = models.CharField(max_length=4, verbose_name='手機後4碼')
    
    # --- 新增付款方式欄位 ---
    payment_method = models.CharField(
        max_length=10, 
        choices=PAYMENT_CHOICES, 
        default='cash', 
        verbose_name='付款方式'
    )
    
    # items 格式：[{"id": 1, "name": "漢堡", "price": 100, "quantity": 2}, ...]
    items = models.JSONField(default=list, verbose_name='訂單內容')
    subtotal = models.PositiveIntegerField(default=0, verbose_name='小計')
    total = models.PositiveIntegerField(default=0, verbose_name='總額')
    
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='pending',
        verbose_name='訂單狀態'
    )
    
    created_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.store.name}] 訂單 #{self.id} - {self.phone_tail}"

    def update_total_from_json(self):
        """
        修正：從 JSONField 重新計算總額
        店家在後台修改 JSON 內容後，調用此方法可重算錢
        """
        new_total = 0
        for item in self.items:
            # 確保 JSON 裡有 price 和 quantity 欄位
            price = item.get('price', 0)
            qty = item.get('quantity', 0)
            new_total += (price * qty)
        self.subtotal = new_total
        self.total = new_total

    def restore_stock(self):
        """將該訂單所有商品數量歸還給庫存 (用於取消訂單時)"""
        with transaction.atomic():
            for item in self.items:
                product_id = item.get('id')
                qty = item.get('quantity', 0)
                if product_id:
                    # 使用 F 表達式避免並發競爭條件
                    Product.objects.filter(id=product_id).update(stock=models.F('stock') + qty)

    def save(self, *args, **kwargs):
        # 1. 自動重算總額 (當店家手動修改了 items 的內容時)
        self.update_total_from_json()

        # 2. 自動處理取消訂單的庫存返還
        if self.pk:
            try:
                old_order = Order.objects.get(pk=self.pk)
                # 如果狀態從其他變為 'cancelled'，且原本不是 cancelled
                if old_order.status != 'cancelled' and self.status == 'cancelled':
                    self.restore_stock()
            except Order.DoesNotExist:
                pass # 新增訂單時不需檢查舊狀態
        
        # 3. 處理完成時間
        if self.status in ['completed', 'final'] and not self.completed_at:
            self.completed_at = timezone.now()
            
        super().save(*args, **kwargs)

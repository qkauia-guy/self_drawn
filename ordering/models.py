from django.db import models
from django.utils import timezone

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

    def __str__(self):
        return f"[{self.store.name}] {self.name}"

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
    
    # 關鍵：這張單子是哪家分店的
    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name='orders', verbose_name='所屬分店')
    phone_tail = models.CharField(max_length=4, verbose_name='手機後4碼')
    items = models.JSONField(default=list, verbose_name='訂單內容')
    subtotal = models.PositiveIntegerField(verbose_name='小計')
    total = models.PositiveIntegerField(verbose_name='總額')
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
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Product, Order, Store
from .serializers import ProductSerializer, OrderSerializer
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.utils import timezone
from django.db import transaction  # 引入事務處理
import pytz

# --- 頁面視圖 (HTML) ---

@login_required(login_url='/admin/login/') 
def owner_dashboard(request):
    """即時訂單管理頁面"""
    return render(request, 'ordering/owner.html')

@login_required(login_url='/admin/login/')
def report_dashboard(request):
    """財務報表中心頁面"""
    return render(request, 'ordering/dashboard.html')

def index(request, store_slug):
    """客人點餐主頁"""
    store = get_object_or_404(Store, slug=store_slug)
    return render(request, 'ordering/index.html', {'store': store})

def order_status_board(request, store_slug):
    """叫號看板頁面"""
    store = get_object_or_404(Store, slug=store_slug)
    return render(request, 'ordering/status.html', {'store': store})

# --- API 視圖 ---

class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProductSerializer
    
    def get_queryset(self):
        store_slug = self.request.query_params.get('store')
        if store_slug:
            # 這裡確保只顯示 is_active=True 的產品，或是讓前端自行判斷
            return Product.objects.filter(store__slug=store_slug)
        return Product.objects.all()

@method_decorator(csrf_exempt, name='dispatch')
class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer

    def get_queryset(self):
        store_slug = self.request.query_params.get('store')
        if store_slug:
            return Order.objects.filter(store__slug=store_slug)
        return Order.objects.all()

    def create(self, request, *args, **kwargs):
        """
        覆寫 create 邏輯：下單即扣庫存
        """
        store_slug = request.data.get('store_slug')
        store = get_object_or_404(Store, slug=store_slug)
        items_data = request.data.get('items', [])

        try:
            # 使用 atomic 確保資料一致性，若其中一個商品失敗，整筆訂單就不會成立
            with transaction.atomic():
                for item in items_data:
                    product_id = item.get('id')
                    qty = int(item.get('quantity', 0)) # 注意前端傳的是 quantity

                    # select_for_update() 會鎖定該列資料，防止超賣
                    product = Product.objects.select_for_update().get(id=product_id)
                    
                    if not product.is_active:
                        return Response({"error": f"{product.name} 目前不供應"}, status=status.HTTP_400_BAD_REQUEST)
                    
                    if product.stock < qty:
                        return Response({"error": f"{product.name} 庫存不足 (剩餘 {product.stock})"}, status=status.HTTP_400_BAD_REQUEST)
                    
                    # 扣除庫存
                    product.stock -= qty
                    product.save()

                # 建立訂單
                serializer = self.get_serializer(data=request.data)
                serializer.is_valid(raise_exception=True)
                serializer.save(store=store)
                return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Product.DoesNotExist:
            return Response({"error": "找不到商品資料"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def get_permissions(self):
        if self.action in ['latest', 'create', 'retrieve', 'partial_update']:
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    @action(detail=False, methods=['get'])
    def latest(self, request):
        store_slug = request.query_params.get('store')
        orders = self.get_queryset().order_by('-id')[:30]
        serializer = self.get_serializer(orders, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def dashboard_stats(self, request):
        store_slug = request.query_params.get('store')
        if not store_slug:
            return Response({"error": "請提供 store 參數"}, status=400)
            
        tw_tz = pytz.timezone('Asia/Taipei')
        now_tw = timezone.now().astimezone(tw_tz)
        today_start = now_tw.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now_tw.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        def calculate_metrics(queryset):
            final_qs = queryset.filter(status='final')
            total_rev = final_qs.aggregate(Sum('total'))['total__sum'] or 0
            total_count = final_qs.count()
            
            items_stats = {
                "hulu": {"qty": 0, "rev": 0},
                "daifuku": {"qty": 0, "rev": 0},
                "drink": {"qty": 0, "rev": 0},
                "dessert": {"qty": 0, "rev": 0}
            }
            
            for order in final_qs:
                for item in order.items:
                    name = item.get('name', '')
                    # 修正：支援 quantity 或 qty 兩種 key
                    qty = item.get('quantity') or item.get('qty', 0)
                    price = item.get('price', 0)
                    subtotal = price * qty
                    
                    if "糖葫蘆" in name:
                        items_stats["hulu"]["qty"] += qty
                        items_stats["hulu"]["rev"] += subtotal
                    elif "大福" in name:
                        items_stats["daifuku"]["qty"] += qty
                        items_stats["daifuku"]["rev"] += subtotal
                    elif any(x in name for x in ["牛奶", "茶", "飲", "咖啡"]):
                        items_stats["drink"]["qty"] += qty
                        items_stats["drink"]["rev"] += subtotal
                    else:
                        items_stats["dessert"]["qty"] += qty
                        items_stats["dessert"]["rev"] += subtotal
                        
            return total_rev, total_count, items_stats

        base_qs = self.get_queryset()
        d_rev, d_count, d_items = calculate_metrics(base_qs.filter(created_at__gte=today_start))
        m_rev, m_count, m_items = calculate_metrics(base_qs.filter(created_at__gte=month_start))

        return Response({
            "store_name": get_object_or_404(Store, slug=store_slug).name,
            "today": {"revenue": d_rev, "orders": d_count, "items": d_items},
            "monthly": {"revenue": m_rev, "orders": m_count, "items": m_items},
            "update_time": now_tw.strftime("%Y-%m-%d %H:%M:%S")
        })
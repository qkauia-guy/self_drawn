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
import pytz

# --- 頁面視圖 (HTML) ---

@login_required(login_url='/admin/login/') 
def owner_dashboard(request):
    """即時訂單管理頁面 (owner.html) - 這裡現在需要前端選擇分店"""
    return render(request, 'ordering/owner.html')

@login_required(login_url='/admin/login/')
def report_dashboard(request):
    """財務報表中心頁面 (dashboard.html)"""
    return render(request, 'ordering/dashboard.html')

def index(request, store_slug):
    """客人點餐主頁 (支援 /dajin/ 或 /neipu/)"""
    store = get_object_or_404(Store, slug=store_slug)
    return render(request, 'ordering/index.html', {'store': store})

def order_status_board(request, store_slug):
    """叫號看板頁面 (支援 /status/dajin/)"""
    store = get_object_or_404(Store, slug=store_slug)
    return render(request, 'ordering/status.html', {'store': store})

# --- API 視圖 ---

class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProductSerializer
    
    def get_queryset(self):
        """根據網址參數 ?store=dajin 過濾產品"""
        store_slug = self.request.query_params.get('store')
        if store_slug:
            return Product.objects.filter(store__slug=store_slug)
        return Product.objects.all()

@method_decorator(csrf_exempt, name='dispatch')
class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer

    def get_queryset(self):
        """根據參數過濾該店訂單"""
        store_slug = self.request.query_params.get('store')
        if store_slug:
            return Order.objects.filter(store__slug=store_slug)
        return Order.objects.all()

    def perform_create(self, serializer):
        """下單時自動關聯分店"""
        store_slug = self.request.data.get('store_slug')
        store = get_object_or_404(Store, slug=store_slug)
        serializer.save(store=store)

    def get_permissions(self):
        if self.action in ['latest', 'create', 'retrieve', 'partial_update']: # 允許客人下單與查詢
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    @action(detail=False, methods=['get'])
    def latest(self, request):
        """獲取特定分店的最新 30 筆訂單"""
        store_slug = request.query_params.get('store')
        orders = self.get_queryset().order_by('-id')[:30]
        serializer = self.get_serializer(orders, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def dashboard_stats(self, request):
        """分店專屬報表數據"""
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
                "drink": {"qty": 0, "rev": 0}, # 統稱為飲品
                "dessert": {"qty": 0, "rev": 0} # 統稱為甜點
            }
            
            for order in final_qs:
                for item in order.items:
                    name = item.get('name', '')
                    qty = item.get('qty', 0)
                    price = item.get('price', 0)
                    subtotal = price * qty
                    
                    if "糖葫蘆" in name:
                        items_stats["hulu"]["qty"] += qty
                        items_stats["hulu"]["rev"] += subtotal
                    elif "大福" in name:
                        items_stats["daifuku"]["qty"] += qty
                        items_stats["daifuku"]["rev"] += subtotal
                    elif any(x in name for x in ["牛奶", "茶", "飲"]):
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
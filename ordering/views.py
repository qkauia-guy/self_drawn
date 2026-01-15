import uuid
import json
import hmac
import hashlib
import base64
import requests
import pytz
import os 

from django.shortcuts import render, get_object_or_404, redirect
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.utils import timezone
from django.db import transaction
from django.conf import settings
from django.http import JsonResponse

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Product, Order, Store
from .serializers import ProductSerializer, OrderSerializer

# ==========================================
# 1. LINE Pay 設定
# ==========================================
LINE_PAY_CHANNEL_ID = '2008899430'
LINE_PAY_CHANNEL_SECRET = 'd28add183df89849bdd3180a44fd9d3b'
LINE_PAY_SANDBOX = True

LINE_PAY_CHANNEL_ID = os.environ.get('LINE_PAY_CHANNEL_ID')
LINE_PAY_CHANNEL_SECRET = os.environ.get('LINE_PAY_CHANNEL_SECRET')
LINE_PAY_SANDBOX = os.environ.get('LINE_PAY_SANDBOX', 'True') == 'True'
LINE_PAY_API_URL = 'https://sandbox-api-pay.line.me' if LINE_PAY_SANDBOX else 'https://api-pay.line.me'




class LinePayHandler:
    """處理 LINE Pay API 簽章與請求的工具類"""
    def __init__(self):
        self.headers = {
            'Content-Type': 'application/json',
            'X-LINE-ChannelId': LINE_PAY_CHANNEL_ID,
            'X-LINE-ChannelSecret': LINE_PAY_CHANNEL_SECRET,
        }

    def _get_auth_headers(self, uri, body_json):
        nonce = str(uuid.uuid4())
        message = LINE_PAY_CHANNEL_SECRET + uri + body_json + nonce
        signature = base64.b64encode(
            hmac.new(
                LINE_PAY_CHANNEL_SECRET.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).digest()
        ).decode('utf-8')
        
        headers = self.headers.copy()
        headers.update({
            'X-LINE-Authorization-Nonce': nonce,
            'X-LINE-Authorization': signature
        })
        return headers

    def request_payment(self, order, confirm_url):
        uri = '/v3/payments/request'
        products = []
        for item in order.items:
            # 兼容 qty 與 quantity
            qty = item.get('quantity') or item.get('qty', 0)
            products.append({
                "name": item['name'],
                "quantity": int(qty),
                "price": int(item['price'])
            })

        payload = {
            "amount": order.total,
            "currency": "TWD",
            "orderId": f"ORDER_{order.id}_{int(order.created_at.timestamp())}",
            "packages": [{
                "id": f"PKG_{order.id}",
                "amount": order.total,
                "products": products
            }],
            "redirectUrls": {
                "confirmUrl": confirm_url,
                "cancelUrl": confirm_url 
            }
        }
        
        body_json = json.dumps(payload)
        headers = self._get_auth_headers(uri, body_json)
        
        try:
            res = requests.post(f"{LINE_PAY_API_URL}{uri}", headers=headers, data=body_json, timeout=10)
            
            # 除錯用 LOG
            if res.status_code != 200:
                print(f"LINE Pay API Error: {res.status_code}")
                print(f"Response: {res.text}")
                
            return res.json()
        except Exception as e:
            print(f"Line Pay Connection Error: {e}")
            return None

    def confirm_payment(self, transaction_id, amount):
        uri = f'/v3/payments/{transaction_id}/confirm'
        payload = {
            "amount": amount,
            "currency": "TWD"
        }
        body_json = json.dumps(payload)
        headers = self._get_auth_headers(uri, body_json)
        
        try:
            res = requests.post(f"{LINE_PAY_API_URL}{uri}", headers=headers, data=body_json, timeout=10)
            return res.json()
        except Exception as e:
            return None


# ==========================================
# 2. ViewSets (API)
# ==========================================

class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProductSerializer
    
    def get_queryset(self):
        store_slug = self.request.query_params.get('store')
        if store_slug:
            return Product.objects.filter(store__slug=store_slug)
        return Product.objects.all()


@method_decorator(csrf_exempt, name='dispatch')
class OrderViewSet(viewsets.ModelViewSet):
    """
    整合了下單、庫存扣除、LINE Pay 處理與 Dashboard 統計的 ViewSet
    """
    serializer_class = OrderSerializer

    def get_queryset(self):
        store_slug = self.request.query_params.get('store')
        if store_slug:
            return Order.objects.filter(store__slug=store_slug)
        return Order.objects.all()

    def get_permissions(self):
        # 允許前台訪客下單與查詢最新狀態，後台管理與報表需登入
        if self.action in ['latest', 'create', 'retrieve', 'partial_update', 'line_callback']:
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def create(self, request, *args, **kwargs):
        """
        建立訂單邏輯：
        1. 檢查並鎖定庫存
        2. 建立訂單
        3. 若為現金 -> 直接回傳成功
        4. 若為 LINE Pay -> 呼叫 API 並回傳轉跳網址
        """
        store_slug = request.data.get('store_slug')
        store = get_object_or_404(Store, slug=store_slug)
        items_data = request.data.get('items', [])
        payment_method = request.data.get('payment_method', 'cash')

        try:
            with transaction.atomic():
                # --- 1. 庫存檢查與扣除 ---
                for item in items_data:
                    product_id = item.get('id')
                    qty = int(item.get('quantity') or item.get('qty', 0))

                    # 鎖定該列，防止超賣
                    product = Product.objects.select_for_update().get(id=product_id)
                    
                    if not product.is_active:
                        return Response({"error": f"{product.name} 目前不供應"}, status=status.HTTP_400_BAD_REQUEST)
                    
                    if product.stock < qty:
                        return Response({"error": f"{product.name} 庫存不足 (剩餘 {product.stock})"}, status=status.HTTP_400_BAD_REQUEST)
                    
                    # 扣除庫存
                    product.stock -= qty
                    product.save()

                # --- 2. 建立訂單物件 ---
                data_copy = request.data.copy()
                data_copy['status'] = 'pending' # 初始狀態
                
                serializer = self.get_serializer(data=data_copy)
                serializer.is_valid(raise_exception=True)
                
                # [修正] 移除 store_slug 後再儲存，避免 TypeError
                save_data = serializer.validated_data
                if 'store_slug' in save_data:
                    del save_data['store_slug']
                
                # 手動儲存，補上 store
                order = serializer.save(store=store) 

                # --- 3. 根據付款方式分流 ---
                if payment_method == 'linepay':
                    line_handler = LinePayHandler()
                    
                    # 動態產生 callback url
                    host = request.get_host()
                    protocol = 'https' if request.is_secure() else 'http'
                    confirm_url = f"{protocol}://{host}/api/orders/line_callback/?oid={order.id}"
                    
                    result = line_handler.request_payment(order, confirm_url)
                    
                    if result and result.get('returnCode') == '0000':
                        payment_url = result['info']['paymentUrl']['web']
                        # 回傳給前端進行轉跳
                        return Response({
                            'id': order.id,
                            'status': 'pending',
                            'total': order.total,
                            'phone_tail': order.phone_tail,
                            'payment_method': 'linepay',
                            'payment_url': payment_url,
                            'items': order.items
                        }, status=status.HTTP_201_CREATED)
                    else:
                        # 請求失敗，手動回滾交易 (拋出錯誤讓 atomic 還原庫存)
                        raise Exception(f"LINE Pay 請求失敗 (Code: {result.get('returnCode') if result else 'Unknown'})")
                
                else:
                    # 現金付款，直接成功
                    return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Product.DoesNotExist:
            return Response({"error": "找不到商品資料"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            # 捕捉所有錯誤
            print(f"Create Order Error: {e}")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def line_callback(self, request):
        """LINE Pay 回調處理"""
        transaction_id = request.GET.get('transactionId')
        order_id = request.GET.get('oid')

        if not transaction_id or not order_id:
            return redirect('/') 

        try:
            order = Order.objects.get(id=order_id)
            # [新增] 取得這筆訂單的分店代號 (例如 'dajin')
            store_slug = order.store.slug 
        except Order.DoesNotExist:
            return redirect('/')

        # 1. 如果已經付過了，直接跳回該分店的狀態頁
        if order.status == 'confirmed':
             return redirect(f'/{store_slug}/?oid={order.id}')

        # 2. 向 LINE Pay 請款
        line_handler = LinePayHandler()
        result = line_handler.confirm_payment(transaction_id, order.total)

        if result and result.get('returnCode') == '0000':
            order.status = 'confirmed' 
            # [選做] 如果您有加 transaction_id 欄位，記得在這裡存
            # order.transaction_id = transaction_id 
            order.save()
            
            # [修正] 成功後，跳回該分店的頁面 (帶上 oid)
            # 前端 index.html 讀到 ?oid=58 就會自動切換成「等待取餐模式」
            return redirect(f'/{store_slug}/?oid={order.id}')
        else:
            print(f"LINE Pay Confirm Failed: {result}")
            # 失敗時也跳回該分店，並顯示錯誤
            return redirect(f'/{store_slug}/?error=payment_failed&oid={order.id}')


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


# ==========================================
# 3. 頁面視圖 (HTML)
# ==========================================

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

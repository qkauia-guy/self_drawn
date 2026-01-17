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
from django.http import JsonResponse

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Product, Order, Store
from .serializers import ProductSerializer, OrderSerializer


# ==========================================
# 1. LINE Pay 設定
# ==========================================
# ⚠️ 你目前把 SECRET 寫死在程式碼裡且已公開貼出，請立刻去 LINE Pay 後台換一組新的 secret，再改用環境變數。
LINE_PAY_CHANNEL_ID = os.environ.get("LINE_PAY_CHANNEL_ID")
LINE_PAY_CHANNEL_SECRET = os.environ.get("LINE_PAY_CHANNEL_SECRET")
LINE_PAY_SANDBOX = os.environ.get("LINE_PAY_SANDBOX", "True") == "True"

LINE_PAY_API_URL = (
    "https://sandbox-api-pay.line.me" if LINE_PAY_SANDBOX else "https://api-pay.line.me"
)


class LinePayHandler:
    """處理 LINE Pay API 簽章與請求的工具類（V3）"""

    def __init__(self):
        self.base_headers = {
            "Content-Type": "application/json",
            "X-LINE-ChannelId": LINE_PAY_CHANNEL_ID,
            "X-LINE-ChannelSecret": LINE_PAY_CHANNEL_SECRET,
        }

    def _get_auth_headers(self, uri, body_json: str):
        nonce = str(uuid.uuid4())
        message = LINE_PAY_CHANNEL_SECRET + uri + body_json + nonce
        signature = base64.b64encode(
            hmac.new(
                LINE_PAY_CHANNEL_SECRET.encode("utf-8"),
                message.encode("utf-8"),
                hashlib.sha256,
            ).digest()
        ).decode("utf-8")

        headers = self.base_headers.copy()
        headers.update(
            {"X-LINE-Authorization-Nonce": nonce, "X-LINE-Authorization": signature}
        )
        return headers

    def request_payment(self, order, confirm_url, cancel_url):
        """LINE Pay Request API (V3)"""
        uri = "/v3/payments/request"

        products = []
        for item in order.items or []:
            qty = item.get("quantity") or item.get("qty", 0) or 0
            products.append(
                {
                    "name": item.get("name", ""),
                    "quantity": int(qty),
                    "price": int(item.get("price", 0)),
                }
            )

        payload = {
            "amount": int(order.total),
            "currency": "TWD",
            "orderId": f"ORDER_{order.id}_{int(order.created_at.timestamp())}",
            "packages": [
                {
                    "id": f"PKG_{order.id}",
                    "amount": int(order.total),
                    "products": products,
                }
            ],
            "redirectUrls": {"confirmUrl": confirm_url, "cancelUrl": cancel_url},
        }

        body_json = json.dumps(payload)
        headers = self._get_auth_headers(uri, body_json)

        res = requests.post(
            f"{LINE_PAY_API_URL}{uri}", headers=headers, data=body_json, timeout=10
        )
        try:
            return res.json()
        except Exception:
            return {"returnCode": "HTTP_ERROR", "returnMessage": res.text}

    def confirm_payment(self, transaction_id, amount):
        """LINE Pay Confirm API (V3)"""
        uri = f"/v3/payments/{transaction_id}/confirm"
        payload = {"amount": int(amount), "currency": "TWD"}

        body_json = json.dumps(payload)
        headers = self._get_auth_headers(uri, body_json)

        res = requests.post(
            f"{LINE_PAY_API_URL}{uri}", headers=headers, data=body_json, timeout=10
        )
        try:
            return res.json()
        except Exception:
            return {"returnCode": "HTTP_ERROR", "returnMessage": res.text}

    def refund_payment(self, transaction_id, refund_amount=None):
        """
        LINE Pay Refund API (V3)
        - refund_amount=None：全額退
        - refund_amount=int：部分退
        """
        uri = f"/v3/payments/{transaction_id}/refund"
        payload = {}
        if refund_amount is not None:
            payload["refundAmount"] = int(refund_amount)

        body_json = json.dumps(payload)
        headers = self._get_auth_headers(uri, body_json)

        res = requests.post(
            f"{LINE_PAY_API_URL}{uri}", headers=headers, data=body_json, timeout=10
        )
        try:
            return res.json()
        except Exception:
            return {"returnCode": "HTTP_ERROR", "returnMessage": res.text}


# ==========================================
# 2. ViewSets (API)
# ==========================================
class ProductViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = ProductSerializer

    def get_queryset(self):
        store_slug = self.request.query_params.get("store")
        qs = Product.objects.all()
        if store_slug:
            qs = qs.filter(store__slug=store_slug)
        return qs


@method_decorator(csrf_exempt, name="dispatch")
class OrderViewSet(viewsets.ModelViewSet):
    """
    下單、庫存、LINE Pay、Dashboard 統計
    + 新增：後台取消訂單會自動退款（LINE Pay）
    """

    serializer_class = OrderSerializer

    def get_queryset(self):
        store_slug = self.request.query_params.get("store")
        qs = Order.objects.all()
        if store_slug:
            qs = qs.filter(store__slug=store_slug)
        return qs

    def get_permissions(self):
        # 前台允許：下單、查詢最新、查單、LINE 回調
        if self.action in [
            "latest",
            "create",
            "retrieve",
            "line_confirm",
            "line_cancel",
        ]:
            return [permissions.AllowAny()]

        # 後台（含取消/狀態變更）必須登入
        return [permissions.IsAuthenticated()]

    # -------- 共用：回補庫存（給 pending 取消/付款失敗用）--------
    def _restore_stock(self, order: Order):
        for item in order.items or []:
            product_id = item.get("id")
            qty = int(item.get("quantity") or item.get("qty", 0) or 0)
            if not product_id or qty <= 0:
                continue
            product = Product.objects.select_for_update().get(id=product_id)
            product.stock += qty
            product.save()

    def create(self, request, *args, **kwargs):
        store_slug = request.data.get("store_slug")
        store = get_object_or_404(Store, slug=store_slug)
        items_data = request.data.get("items", [])
        payment_method = request.data.get("payment_method", "cash")

        try:
            with transaction.atomic():
                # 1) 庫存檢查與扣除
                for item in items_data:
                    product_id = item.get("id")
                    qty = int(item.get("quantity") or item.get("qty", 0) or 0)
                    product = Product.objects.select_for_update().get(id=product_id)

                    if not product.is_active:
                        return Response(
                            {"error": f"{product.name} 目前不供應"},
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                    if product.stock < qty:
                        return Response(
                            {
                                "error": f"{product.name} 庫存不足 (剩餘 {product.stock})"
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                    product.stock -= qty
                    product.save()

                # 2) 建立訂單（pending）
                data_copy = request.data.copy()
                data_copy["status"] = "pending"

                serializer = self.get_serializer(data=data_copy)
                # serializer.is_valid(raise_exception=True)
                if not serializer.is_valid():
                    return Response(
                        serializer.errors, status=status.HTTP_400_BAD_REQUEST
                    )

                save_data = serializer.validated_data
                if "store_slug" in save_data:
                    del save_data["store_slug"]

                order = serializer.save(store=store)

                # 3) 付款分流
                if payment_method == "linepay":
                    line_handler = LinePayHandler()

                    host = request.get_host()

                    # 本地 + ngrok 測試建議直接固定 https（否則 request.is_secure() 常是 False）
                    protocol = "https" if request.is_secure() else "http"
                    # 如果你確定是 ngrok https，可改成：protocol = "https"

                    confirm_url = (
                        f"{protocol}://{host}/api/orders/line_confirm/?oid={order.id}"
                    )
                    cancel_url = (
                        f"{protocol}://{host}/api/orders/line_cancel/?oid={order.id}"
                    )

                    result = line_handler.request_payment(
                        order, confirm_url, cancel_url
                    )

                    if result and result.get("returnCode") == "0000":
                        payment_url = result["info"]["paymentUrl"]["web"]
                        return Response(
                            {
                                "id": order.id,
                                "status": "pending",
                                "total": order.total,
                                "phone_tail": order.phone_tail,
                                "payment_method": "linepay",
                                "payment_url": payment_url,
                                "items": order.items,
                            },
                            status=status.HTTP_201_CREATED,
                        )

                    raise Exception(
                        f"LINE Pay 請求失敗 (Code: {result.get('returnCode') if result else 'Unknown'})"
                    )

                # 現金付款
                return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Product.DoesNotExist:
            return Response(
                {"error": "找不到商品資料"}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            print(f"Create Order Error: {e}")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    # ✅ LINE Pay Confirm：付款成功回來會帶 transactionId
    @action(detail=False, methods=["get"])
    def line_confirm(self, request):
        transaction_id = request.GET.get("transactionId")
        order_id = request.GET.get("oid")

        if not order_id:
            return redirect("/")

        try:
            with transaction.atomic():
                order = Order.objects.select_for_update().get(id=order_id)
                store_slug = order.store.slug

                # 已確認就直接回客人頁
                if order.status == "confirmed":
                    return redirect(f"/{store_slug}/?oid={order.id}")

                if not transaction_id:
                    return redirect(
                        f"/{store_slug}/?error=missing_transaction&oid={order.id}"
                    )

                line_handler = LinePayHandler()
                result = line_handler.confirm_payment(transaction_id, order.total)

                if result and result.get("returnCode") == "0000":
                    order.status = "confirmed"
                    order.payment_method = "linepay"

                    # ✅ 必存：退款需要 transactionId
                    # ⚠️ 需先在 Order model 增加 linepay_transaction_id 欄位，並 migrate
                    if hasattr(order, "linepay_transaction_id"):
                        order.linepay_transaction_id = str(transaction_id)

                    order.save()
                    return redirect(f"/{store_slug}/?oid={order.id}")

                # confirm 失敗：回補庫存、取消訂單
                print(f"LINE Pay Confirm Failed: {result}")
                if order.status == "pending":
                    self._restore_stock(order)
                    order.status = "cancelled"
                    order.save()

                return redirect(f"/{store_slug}/?error=payment_failed&oid={order.id}")

        except Order.DoesNotExist:
            return redirect("/")
        except Exception as e:
            print(f"LINE Confirm Error: {e}")
            return redirect(f"/?error=server_error&oid={order_id}")

    # ✅ LINE Pay Cancel：使用者在 LINE Pay 頁面取消付款會走這裡
    @action(detail=False, methods=["get"])
    def line_cancel(self, request):
        order_id = request.GET.get("oid")
        if not order_id:
            return redirect("/")

        try:
            with transaction.atomic():
                order = Order.objects.select_for_update().get(id=order_id)
                store_slug = order.store.slug

                # 已 confirmed 就不動（代表已付了，取消應走退款流程，不該走這支）
                if order.status == "confirmed":
                    return redirect(f"/{store_slug}/?oid={order.id}")

                # pending 才回補
                if order.status == "pending":
                    self._restore_stock(order)
                    order.status = "cancelled"
                    order.save()

                return redirect(f"/{store_slug}/?error=cancelled&oid={order.id}")

        except Order.DoesNotExist:
            return redirect("/")
        except Exception as e:
            print(f"LINE Cancel Error: {e}")
            return redirect(f"/?error=cancel_failed&oid={order_id}")

    # ✅ 後台取消（會自動退款）
    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        try:
            with transaction.atomic():
                order = Order.objects.select_for_update().get(id=pk)

                # 已取消就不重做
                if order.status == "cancelled":
                    return Response({"detail": "already cancelled"})

                # 只有 LINE Pay 且已付款(confirmed 之後)才需要退款
                if order.payment_method == "linepay" and order.status in [
                    "confirmed",
                    "preparing",
                    "arrived",
                    "completed",
                    "final",
                ]:
                    if not getattr(order, "linepay_transaction_id", None):
                        return Response(
                            {"error": "missing linepay_transaction_id"}, status=400
                        )

                    # 已退過就不要重退
                    if getattr(order, "linepay_refunded", False):
                        order.status = "cancelled"
                        order.save()
                        return Response({"detail": "already refunded, order cancelled"})

                    line_handler = LinePayHandler()
                    refund_res = line_handler.refund_payment(
                        order.linepay_transaction_id
                    )

                    # ✅ 你問的這段：加在這裡
                    print("[LINEPAY REFUND RES]", refund_res)

                    if refund_res and refund_res.get("returnCode") == "0000":
                        order.linepay_refunded = True
                        order.linepay_refund_transaction_id = str(
                            refund_res.get("info", {}).get("refundTransactionId", "")
                        )
                        order.save()
                    else:
                        return Response(
                            {"error": "refund failed", "linepay": refund_res},
                            status=400,
                        )

                # 最後都要取消訂單（你的 Order.save 會回補庫存）
                order.status = "cancelled"
                order.save()

            return Response({"detail": "cancelled (refunded if linepay)"})
        except Order.DoesNotExist:
            return Response({"error": "order not found"}, status=404)

    @action(detail=False, methods=["get"])
    def latest(self, request):
        store_slug = request.query_params.get("store")
        qs = self.get_queryset()
        if store_slug:
            qs = qs.filter(store__slug=store_slug)
        orders = qs.order_by("-id")[:30]
        serializer = self.get_serializer(orders, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def dashboard_stats(self, request):
        store_slug = request.query_params.get("store")
        if not store_slug:
            return Response({"error": "請提供 store 參數"}, status=400)

        store = get_object_or_404(Store, slug=store_slug)

        tw_tz = pytz.timezone("Asia/Taipei")
        now_tw = timezone.now().astimezone(tw_tz)
        today_start = now_tw.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now_tw.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        def calculate_metrics(queryset):
            final_qs = queryset.filter(status="final")
            total_rev = final_qs.aggregate(Sum("total"))["total__sum"] or 0
            total_count = final_qs.count()

            items_stats = {
                "hulu": {"qty": 0, "rev": 0},
                "daifuku": {"qty": 0, "rev": 0},
                "drink": {"qty": 0, "rev": 0},
                "dessert": {"qty": 0, "rev": 0},
            }

            for order in final_qs:
                for item in order.items or []:
                    name = item.get("name", "")
                    qty = item.get("quantity") or item.get("qty", 0) or 0
                    price = item.get("price", 0) or 0
                    subtotal = int(price) * int(qty)

                    if "糖葫蘆" in name:
                        items_stats["hulu"]["qty"] += int(qty)
                        items_stats["hulu"]["rev"] += int(subtotal)
                    elif "大福" in name:
                        items_stats["daifuku"]["qty"] += int(qty)
                        items_stats["daifuku"]["rev"] += int(subtotal)
                    elif any(x in name for x in ["牛奶", "茶", "飲", "咖啡"]):
                        items_stats["drink"]["qty"] += int(qty)
                        items_stats["drink"]["rev"] += int(subtotal)
                    else:
                        items_stats["dessert"]["qty"] += int(qty)
                        items_stats["dessert"]["rev"] += int(subtotal)

            return total_rev, total_count, items_stats

        base_qs = self.get_queryset().filter(store=store)

        d_rev, d_count, d_items = calculate_metrics(
            base_qs.filter(created_at__gte=today_start)
        )
        m_rev, m_count, m_items = calculate_metrics(
            base_qs.filter(created_at__gte=month_start)
        )

        return Response(
            {
                "store_name": store.name,
                "today": {"revenue": d_rev, "orders": d_count, "items": d_items},
                "monthly": {"revenue": m_rev, "orders": m_count, "items": m_items},
                "update_time": now_tw.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )


# ==========================================
# 3. 頁面視圖 (HTML)
# ==========================================
@login_required(login_url="/admin/login/")
def owner_dashboard(request):
    return render(request, "ordering/owner.html")


@login_required(login_url="/admin/login/")
def report_dashboard(request):
    return render(request, "ordering/dashboard.html")


def index(request, store_slug):
    store = get_object_or_404(Store, slug=store_slug)
    return render(request, "ordering/index.html", {"store": store})


def order_status_board(request, store_slug):
    store = get_object_or_404(Store, slug=store_slug)
    return render(request, "ordering/status.html", {"store": store})


def about(request):
    stores = Store.objects.filter(is_active=True)
    return render(request, "about.html", {"stores": stores})

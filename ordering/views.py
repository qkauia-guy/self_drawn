import uuid
import json
import hmac
import hashlib
import base64
import requests
import pytz
import os

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.utils import timezone
from django.db import transaction
from django.http import JsonResponse

from rest_framework.decorators import api_view
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response

# ✅ 引入 Category
from .models import Product, Order, Store, Category
from .serializers import ProductSerializer, OrderSerializer


# ==========================================
# 1. LINE Pay 設定
# ==========================================
LINE_PAY_CHANNEL_ID = os.environ.get("LINE_PAY_CHANNEL_ID")
LINE_PAY_CHANNEL_SECRET = os.environ.get("LINE_PAY_CHANNEL_SECRET")
LINE_PAY_SANDBOX = os.environ.get("LINE_PAY_SANDBOX", "True") == "True"

if LINE_PAY_CHANNEL_ID or LINE_PAY_CHANNEL_SECRET:
    if not LINE_PAY_CHANNEL_ID or not LINE_PAY_CHANNEL_SECRET:
        print("⚠️ 警告: 偵測到 LINE Pay 設定，但缺少 ID 或 Secret。")

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
        message = (LINE_PAY_CHANNEL_SECRET or "") + uri + body_json + nonce
        signature = base64.b64encode(
            hmac.new(
                (LINE_PAY_CHANNEL_SECRET or "").encode("utf-8"),
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
        """LINE Pay Request API"""
        uri = "/v3/payments/request"
        products = []
        for item in order.items or []:
            qty = item.get("quantity") or item.get("qty", 0) or 0
            products.append(
                {
                    "name": item.get("name", "商品"),
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

        try:
            res = requests.post(
                f"{LINE_PAY_API_URL}{uri}", headers=headers, data=body_json, timeout=10
            )
            return res.json()
        except Exception as e:
            return {"returnCode": "HTTP_ERROR", "returnMessage": str(e)}

    def confirm_payment(self, transaction_id, amount):
        """LINE Pay Confirm API"""
        uri = f"/v3/payments/{transaction_id}/confirm"
        payload = {"amount": int(amount), "currency": "TWD"}

        body_json = json.dumps(payload)
        headers = self._get_auth_headers(uri, body_json)

        try:
            res = requests.post(
                f"{LINE_PAY_API_URL}{uri}", headers=headers, data=body_json, timeout=10
            )
            return res.json()
        except Exception as e:
            return {"returnCode": "HTTP_ERROR", "returnMessage": str(e)}

    def refund_payment(self, transaction_id, refund_amount=None):
        """LINE Pay Refund API"""
        uri = f"/v3/payments/{transaction_id}/refund"
        payload = {}
        if refund_amount is not None:
            payload["refundAmount"] = int(refund_amount)

        body_json = json.dumps(payload)
        headers = self._get_auth_headers(uri, body_json)

        try:
            res = requests.post(
                f"{LINE_PAY_API_URL}{uri}", headers=headers, data=body_json, timeout=10
            )
            return res.json()
        except Exception as e:
            return {"returnCode": "HTTP_ERROR", "returnMessage": str(e)}


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


class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer

    def get_queryset(self):
        store_slug = self.request.query_params.get("store")
        qs = Order.objects.all()

        if store_slug:
            qs = qs.filter(store__slug=store_slug)

        # 這樣「營業結束」後，這些單就不會出現在 iPad/電腦 畫面上
        qs = qs.exclude(status="archived")

        return qs

    def get_permissions(self):
        if self.action in ["latest", "create", "line_confirm", "line_cancel"]:
            return [permissions.AllowAny()]
        if self.action == "retrieve":
            return [permissions.AllowAny()]
        if self.action == "partial_update":
            return [permissions.AllowAny()]
        return [permissions.IsAuthenticated()]

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        phone_tail = request.query_params.get("phone_tail")
        if phone_tail and phone_tail != instance.phone_tail:
            return Response(
                {"error": "無權限查看此訂單"}, status=status.HTTP_403_FORBIDDEN
            )
        serializer = self.get_serializer(instance)
        return Response(serializer.data)

    def partial_update(self, request, *args, **kwargs):
        instance = self.get_object()

        # --- [新增功能] 後台修改訂單內容 (僅限已登入管理員 & 待付款訂單) ---
        if request.user.is_authenticated and "items" in request.data:
            if instance.status != "pending":
                return Response({"error": "只能修改「待付款」狀態的訂單"}, status=400)

            new_items_data = request.data.get("items")
            if not isinstance(new_items_data, list):
                return Response({"error": "商品資料格式錯誤"}, status=400)

            try:
                with transaction.atomic():
                    # 1. 先「歸還」舊訂單的庫存
                    self._restore_stock(instance)

                    # 2. 重新計算新訂單內容 (扣庫存 + 建立快照)
                    updated_items_snapshot = []
                    new_total = 0

                    for item in new_items_data:
                        product_id = item.get("id")
                        # 允許 quantity 或 qty 欄位
                        qty = int(item.get("quantity") or item.get("qty") or 0)

                        if qty <= 0:
                            continue

                        # 鎖定並讀取商品
                        product = Product.objects.select_for_update().get(id=product_id)

                        # 檢查庫存 (注意：剛才已經把舊單的庫存加回去了，所以這裡是檢查最新庫存)
                        if product.stock < qty:
                            raise ValueError(
                                f"{product.name} 庫存不足 (剩餘 {product.stock})"
                            )

                        # 扣庫存
                        product.stock -= qty
                        product.save()

                        # 建立訂單細項快照 (保留當下價格與分類)
                        item_copy = {
                            "id": product.id,
                            "name": product.name,
                            "price": int(product.price),
                            "quantity": qty,
                            "category": product.category.slug,
                            "category_name": product.category.name,
                        }
                        updated_items_snapshot.append(item_copy)
                        new_total += item_copy["price"] * qty

                    # 3. 更新訂單實體
                    instance.items = updated_items_snapshot
                    instance.total = new_total
                    instance.save()

                    # 回傳更新後的訂單
                    serializer = self.get_serializer(instance)
                    return Response(serializer.data)

            except Product.DoesNotExist:
                return Response({"error": "找不到指定商品"}, status=404)
            except ValueError as e:
                return Response({"error": str(e)}, status=400)
            except Exception as e:
                print(f"Edit Order Error: {e}")
                return Response({"error": "修改失敗"}, status=500)

        # --- 以下維持原本的狀態更新邏輯 (給前端用) ---

        # 如果是管理員且沒有傳 items，就走預設邏輯 (改狀態)
        if request.user.is_authenticated:
            return super().partial_update(request, *args, **kwargs)

        # 客戶端驗證邏輯 (原本的程式碼)
        phone_tail = request.data.get("phone_tail")
        if not phone_tail or phone_tail != instance.phone_tail:
            return Response({"error": "驗證失敗"}, status=status.HTTP_403_FORBIDDEN)

        new_status = request.data.get("status")
        if new_status and new_status not in ["arrived", "final"]:
            return Response(
                {"error": "只能更新狀態為 arrived 或 final"},
                status=status.HTTP_403_FORBIDDEN,
            )

        if new_status == "arrived" and instance.status != "completed":
            return Response({"error": "訂單尚未完成，無法通知"}, status=400)

        allowed_fields = ["status"]
        update_data = {k: v for k, v in request.data.items() if k in allowed_fields}
        serializer = self.get_serializer(instance, data=update_data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def _restore_stock(self, order: Order):
        for item in order.items or []:
            product_id = item.get("id")
            qty = int(item.get("quantity") or item.get("qty", 0) or 0)
            if not product_id or qty <= 0:
                continue
            try:
                product = Product.objects.select_for_update().get(id=product_id)
                product.stock += qty
                product.save()
            except Product.DoesNotExist:
                continue

    def create(self, request, *args, **kwargs):
        store_slug = request.data.get("store_slug")
        if not store_slug:
            return Response({"error": "請提供 store_slug"}, status=400)

        store = get_object_or_404(Store, slug=store_slug)
        items_data = request.data.get("items", [])
        payment_method = request.data.get("payment_method", "cash")

        if not isinstance(items_data, list) or not items_data:
            return Response({"error": "items 格式錯誤或為空"}, status=400)

        try:
            with transaction.atomic():
                updated_items = []

                # 1. 扣除庫存並更新訂單細項
                for item in items_data:
                    product_id = item.get("id")
                    qty = int(item.get("quantity") or item.get("qty", 0))

                    if qty <= 0:
                        continue

                    product = Product.objects.select_for_update().get(id=product_id)

                    if not product.is_active:
                        raise ValueError(f"{product.name} 目前不供應")
                    if product.stock < qty:
                        raise ValueError(
                            f"{product.name} 庫存不足 (剩餘 {product.stock})"
                        )

                    product.stock -= qty
                    product.save()

                    # 將商品當下的 Category 資訊寫入訂單 JSON (快照)
                    item_copy = item.copy()
                    item_copy["category"] = product.category.slug
                    item_copy["category_name"] = product.category.name
                    item_copy["name"] = product.name
                    item_copy["price"] = product.price
                    updated_items.append(item_copy)

                # 2. 建立訂單
                data_copy = request.data.copy()
                data_copy["status"] = "pending"
                data_copy["items"] = updated_items  # 使用更新後的 items

                serializer = self.get_serializer(data=data_copy)
                if not serializer.is_valid():
                    return Response(serializer.errors, status=400)

                if "store_slug" in serializer.validated_data:
                    del serializer.validated_data["store_slug"]

                order = serializer.save(store=store)

                # 3. LINE Pay 處理邏輯 (已修正網址問題)
                if payment_method == "linepay":
                    line_handler = LinePayHandler()

                    # 🟢 [修正] 直接填入您的 Render 正確網址
                    MY_DOMAIN = "yibahu-order.it.com"

                    # 🟢 [修正] 強制使用 https (LINE Pay 嚴格要求)
                    confirm_url = (
                        f"https://{MY_DOMAIN}/api/orders/line_confirm/?oid={order.id}"
                    )
                    cancel_url = (
                        f"https://{MY_DOMAIN}/api/orders/line_cancel/?oid={order.id}"
                    )

                    # 🔵 [除錯] 印出網址確認 (請在 Render Logs 查看)
                    print(f"DEBUG: LINE Pay Confirm URL: {confirm_url}")

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
                            status=201,
                        )

                    # 錯誤處理：印出詳細錯誤原因
                    print(f"ERROR: LINE Pay Request Failed: {result}")
                    raise ValueError(
                        f"LINE Pay 請求失敗: {result.get('returnMessage')}"
                    )

                return Response(serializer.data, status=201)

        except Product.DoesNotExist:
            return Response({"error": "找不到商品資料"}, status=404)
        except ValueError as e:
            return Response({"error": str(e)}, status=400)
        except Exception as e:
            print(f"Create Order Error: {e}")
            return Response({"error": "系統發生錯誤"}, status=400)

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

                if order.status == "confirmed":
                    return redirect(f"/{store_slug}/?oid={order.id}")

                if not transaction_id:
                    return redirect(
                        f"/{store_slug}/?error=missing_transaction&oid={order.id}"
                    )

                line_handler = LinePayHandler()
                result = line_handler.confirm_payment(transaction_id, order.total)
                print(f"DEBUG: LINE Pay 回傳內容: {result}")

                if result and result.get("returnCode") == "0000":
                    order.status = "confirmed"
                    order.payment_method = "linepay"
                    order.linepay_transaction_id = str(transaction_id)
                    order.save()
                    return redirect(f"/{store_slug}/?oid={order.id}")

                self._restore_stock(order)
                order.status = "cancelled"
                order.save()
                return redirect(f"/{store_slug}/?error=payment_failed&oid={order.id}")

        except Exception as e:
            return redirect(f"/?error=server_error")

    @action(detail=False, methods=["get"])
    def line_cancel(self, request):
        order_id = request.GET.get("oid")
        if not order_id:
            return redirect("/")

        try:
            with transaction.atomic():
                order = Order.objects.select_for_update().get(id=order_id)
                store_slug = order.store.slug

                if order.status == "confirmed":
                    return redirect(f"/{store_slug}/?oid={order.id}")

                if order.status == "pending":
                    self._restore_stock(order)
                    order.status = "cancelled"
                    order.save()

                return redirect(f"/{store_slug}/?error=cancelled&oid={order.id}")
        except Exception:
            return redirect(f"/?error=cancel_failed")

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        try:
            with transaction.atomic():
                order = Order.objects.select_for_update().get(id=pk)

                if order.status == "cancelled":
                    return Response({"detail": "already cancelled"})

                if order.payment_method == "linepay" and order.status in [
                    "confirmed",
                    "preparing",
                    "arrived",
                    "completed",
                    "final",
                ]:
                    if not getattr(order, "linepay_transaction_id", None):
                        return Response({"error": "missing transaction id"}, status=400)

                    if not getattr(order, "linepay_refunded", False):
                        line_handler = LinePayHandler()
                        refund_res = line_handler.refund_payment(
                            order.linepay_transaction_id
                        )

                        if refund_res and refund_res.get("returnCode") == "0000":
                            order.linepay_refunded = True
                            order.linepay_refund_transaction_id = str(
                                refund_res.get("info", {}).get(
                                    "refundTransactionId", ""
                                )
                            )
                        else:
                            return Response(
                                {"error": "refund failed", "detail": refund_res},
                                status=400,
                            )

                order.status = "cancelled"
                order.save()

            return Response({"detail": "cancelled"})
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

    # ✅ 修正重點 2: 儀表板改為動態讀取 Category
    @action(detail=False, methods=["get"])
    def dashboard_stats(self, request):
        store_slug = request.query_params.get("store")
        if not store_slug:
            return Response({"error": "請提供 store 參數"}, status=400)

        store = get_object_or_404(Store, slug=store_slug)
        categories = Category.objects.filter(store=store).order_by("sort_order")

        tw_tz = pytz.timezone("Asia/Taipei")
        now_tw = timezone.now().astimezone(tw_tz)
        today_start = now_tw.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now_tw.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        def calculate_metrics(queryset):
            # ✅ 修改 1: 這裡加入了 "archived"，確保歸檔後的業績依然被計算
            final_qs = queryset.filter(status__in=["completed", "final", "archived"])

            total_rev = final_qs.aggregate(Sum("total"))["total__sum"] or 0
            total_count = final_qs.count()

            # 1. 初始化統計容器 (加入 details)
            items_stats = {}
            for cat in categories:
                items_stats[cat.slug] = {
                    "qty": 0,
                    "rev": 0,
                    "name": cat.name,
                    "details": {},
                }
            # 處理未分類或已刪除分類的情況
            items_stats["uncategorized"] = {
                "qty": 0,
                "rev": 0,
                "name": "其他",
                "details": {},
            }

            for order in final_qs:
                for item in order.items or []:
                    cat_slug = item.get("category", "uncategorized")
                    p_name = item.get("name", "未知商品")

                    qty = int(item.get("quantity") or item.get("qty", 0))
                    price = int(item.get("price", 0))
                    subtotal = price * qty

                    # 確保分類存在 (防呆)
                    target_stats = items_stats.get(
                        cat_slug, items_stats["uncategorized"]
                    )

                    # A. 更新分類總數
                    target_stats["qty"] += qty
                    target_stats["rev"] += subtotal

                    # B. 更新該商品細項 (Details)
                    details = target_stats["details"]
                    if p_name not in details:
                        details[p_name] = {"qty": 0, "rev": 0}

                    details[p_name]["qty"] += qty
                    details[p_name]["rev"] += subtotal

            return total_rev, total_count, items_stats

        # ✅ 修改 2: 這裡改用 Order.objects 直接查詢
        # 因為 self.get_queryset() 已經過濾掉 archived (為了前台隱藏)，
        # 所以報表必須繞過 get_queryset 才能統計到已歸檔的資料。
        base_qs = Order.objects.filter(store=store)

        # 計算今日與本月
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


def store_list(request):
    """回傳所有營業中的分店清單，供後台選擇器使用"""
    stores = Store.objects.filter(is_active=True).values("name", "slug")
    return JsonResponse(list(stores), safe=False)


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


# views.py 中的 reset_daily_orders


@api_view(["POST"])
def reset_daily_orders(request, store_slug):
    """
    營業結束歸零邏輯 (修正版)：
    1. 進行中訂單 -> 轉為 'cancelled' (清空且不計費)
    2. 已完成訂單 -> 轉為 'archived' (清空但保留業績)
    """
    store = get_object_or_404(Store, slug=store_slug)

    # 1. 處理「進行中」的單 -> 取消
    active_statuses = ["pending", "confirmed", "preparing", "completed", "arrived"]
    cancelled_count = Order.objects.filter(
        store=store, status__in=active_statuses
    ).update(status="cancelled")

    # 2. 處理「已完成(final)」的單 -> 歸檔 (隱藏但保留業績)
    # 注意：update() 會繞過 model validate，所以即使 choices 裡沒有 archived 也可以寫入
    archived_count = Order.objects.filter(store=store, status="final").update(
        status="archived"
    )

    return Response(
        {
            "status": "success",
            "message": f"今日結算完成：\n已取消 {cancelled_count} 筆未完成訂單\n已歸檔 {archived_count} 筆完成訂單 (業績保留)",
        }
    )

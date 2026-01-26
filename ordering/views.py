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
from django.db.models import Sum, Max, Q, F
from django.utils import timezone
from django.db import transaction
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST

from rest_framework.decorators import api_view
from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response


# ✅ 引入 Category
from .models import Product, Order, Store, Category
from .forms import ProductForm
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

    throttle_classes = []

    def get_queryset(self):
        # 1. 取得基本 QuerySet
        qs = Order.objects.all()

        # 2. 分店過濾 (必須)
        store_slug = self.request.query_params.get("store")
        if store_slug:
            qs = qs.filter(store__slug=store_slug)

        from django.db.models import Q

        active_statuses = ["pending", "confirmed", "preparing", "completed", "arrived"]

        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # 過濾邏輯：(建立時間是今天) OR (狀態是未結案)
        qs = qs.filter(Q(created_at__gte=today_start) | Q(status__in=active_statuses))

        # 雙重保險：絕對不顯示已歸檔的單 (雖然上面邏輯應該已經排除了)
        qs = qs.exclude(status="archived")

        return qs.order_by("-id")

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

        # --- [管理員修改內容] ---
        if request.user.is_authenticated and "items" in request.data:
            # 限制狀態
            if instance.status not in ["pending", "confirmed"]:
                return Response({"error": "只能修改未完成的訂單"}, status=400)

            new_items_data = request.data.get("items")
            if not isinstance(new_items_data, list):
                return Response({"error": "商品資料格式錯誤"}, status=400)

            try:
                with transaction.atomic():
                    # 1. 先「全額還原」舊訂單的庫存
                    self._restore_stock(instance)

                    # 2. 重新計算新訂單內容 (扣庫存 + 建立快照)
                    updated_items_snapshot = []
                    new_total = 0

                    for item in new_items_data:
                        product_id = item.get("id")
                        try:
                            qty = int(item.get("quantity") or item.get("qty") or 0)
                        except:
                            qty = 0

                        if qty <= 0:
                            continue

                        # 鎖定並讀取商品 (確保庫存檢查時沒人插隊)
                        product = Product.objects.select_for_update().get(id=product_id)

                        # 檢查庫存
                        # 注意：因為步驟 1 已經把舊庫存還原了，所以這裡是檢查「總可用量」
                        if product.stock < qty:
                            raise ValueError(
                                f"{product.name} 庫存不足 (剩餘 {product.stock})"
                            )

                        # 扣庫存
                        product.stock -= qty
                        product.save()

                        # 建立快照
                        item_copy = {
                            "id": product.id,
                            "name": product.name,
                            "price": int(product.price),
                            "quantity": qty,
                            "category": (
                                product.category.slug if product.category else "other"
                            ),
                            "category_name": (
                                product.category.name if product.category else "其他"
                            ),
                        }
                        updated_items_snapshot.append(item_copy)
                        new_total += item_copy["price"] * qty

                    # 3. 更新訂單
                    instance.items = updated_items_snapshot
                    instance.total = new_total
                    # 注意：不需手動算 subtotal，Order.save() 會處理 (如果 model 有保留 update_total_from_json)
                    # 但為了保險，這裡可以直接寫入
                    instance.subtotal = new_total
                    instance.save()

                    serializer = self.get_serializer(instance)
                    return Response(serializer.data)

            except Product.DoesNotExist:
                return Response({"error": "找不到指定商品"}, status=404)
            except ValueError as e:
                return Response({"error": str(e)}, status=400)
            except Exception as e:
                print(f"Edit Order Error: {e}")
                return Response({"error": "修改失敗，請稍後再試"}, status=500)

        # ... (原本的狀態更新邏輯保持不變) ...
        return super().partial_update(request, *args, **kwargs)

    # 在 OrderViewSet 類別內，替換原本的 _restore_stock
    def _restore_stock(self, order: Order):
        """
        還原庫存 (原子操作版)
        修正：移除 json.loads，因為 JSONField 自動轉為 list
        """
        # 1. 取得訂單內容 (Django JSONField 自動轉為 List)
        items = order.items

        # 防呆：確保是列表
        if not items or not isinstance(items, list):
            return

        print(f"🔄 [庫存還原] 訂單 #{order.id}，項目數: {len(items)}")

        # 2. 遍歷並還原
        for item in items:
            product_id = item.get("id")
            # 兼容 quantity 或 qty
            try:
                qty = int(item.get("quantity") or item.get("qty") or 0)
            except (ValueError, TypeError):
                qty = 0

            if product_id and qty > 0:
                # 使用 F() 表達式進行原子更新 (避免 Race Condition)
                Product.objects.filter(id=product_id).update(stock=F("stock") + qty)

    def create(self, request, *args, **kwargs):
        store_slug = request.data.get("store_slug")
        store = get_object_or_404(Store, slug=store_slug)
        items_data = request.data.get("items", [])
        payment_method = request.data.get("payment_method", "cash")

        try:
            with transaction.atomic():
                updated_items = []

                for item in items_data:
                    product_id = item.get("id")
                    try:
                        qty = int(item.get("quantity") or 0)
                    except:
                        qty = 0

                    if qty <= 0:
                        continue

                    # 🔥 關鍵修復：原子鎖定扣庫存
                    # 只有當 stock >= qty 時才會扣除，且直接在 DB 運算
                    rows_affected = Product.objects.filter(
                        id=product_id, is_active=True, stock__gte=qty
                    ).update(stock=F("stock") - qty)

                    if rows_affected == 0:
                        # 為了顯示具體錯誤，再查一次商品名稱
                        p = Product.objects.filter(id=product_id).first()
                        if p:
                            raise ValueError(f"{p.name} 庫存不足 (剩餘 {p.stock})")
                        else:
                            raise ValueError("商品不存在或已下架")

                    # 取得最新資訊做快照
                    product = Product.objects.get(id=product_id)
                    item_copy = item.copy()
                    item_copy.update(
                        {
                            "name": product.name,
                            "price": product.price,
                            "category": (
                                product.category.slug if product.category else "other"
                            ),
                            "category_name": (
                                product.category.name if product.category else "其他"
                            ),
                        }
                    )
                    updated_items.append(item_copy)

                # 建立訂單
                data_copy = request.data.copy()
                data_copy["status"] = "pending"
                data_copy["items"] = updated_items

                serializer = self.get_serializer(data=data_copy)
                if not serializer.is_valid():
                    raise ValueError(str(serializer.errors))
                if "store_slug" in serializer.validated_data:
                    del serializer.validated_data["store_slug"]

                order = serializer.save(store=store)

                # LINE Pay
                if payment_method == "linepay":
                    line_handler = LinePayHandler()
                    MY_DOMAIN = "yibahu-order.it.com"  # 請確認您的網址
                    confirm_url = (
                        f"https://{MY_DOMAIN}/api/orders/line_confirm/?oid={order.id}"
                    )
                    cancel_url = (
                        f"https://{MY_DOMAIN}/api/orders/line_cancel/?oid={order.id}"
                    )

                    result = line_handler.request_payment(
                        order, confirm_url, cancel_url
                    )
                    if result.get("returnCode") == "0000":
                        return Response(
                            {
                                "id": order.id,
                                "status": "pending",
                                "total": order.total,
                                "payment_method": "linepay",
                                "payment_url": result["info"]["paymentUrl"]["web"],
                                "items": order.items,
                            },
                            status=201,
                        )
                    else:
                        raise ValueError(
                            f"LINE Pay 錯誤: {result.get('returnMessage')}"
                        )

                return Response(serializer.data, status=201)

        except Exception as e:
            return Response({"error": str(e)}, status=400)

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

                # 🔥 關鍵修復：雙重檢查狀態
                if order.status in ["cancelled", "archived"]:
                    return Response(
                        {"status": "success", "detail": "already cancelled"}
                    )

                self._restore_stock(order)
                order.status = "cancelled"
                order.save()

            return Response({"status": "success", "detail": "cancelled"})
        except Order.DoesNotExist:
            return Response({"error": "order not found"}, status=404)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

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
    store = get_object_or_404(Store, slug=store_slug)

    # 1. 找出需要取消的訂單
    pending_orders = Order.objects.filter(
        store=store,
        status__in=["pending", "confirmed", "preparing", "completed", "arrived"],
    )

    cancel_count = 0
    restore_updates = {}  # 用 dict 來合併同一商品的庫存 {product_id: qty_to_add}

    with transaction.atomic():
        # A. 計算要還原的總庫存
        for order in pending_orders:
            items = order.items  # JSONField 自動轉 list
            if isinstance(items, list):
                for item in items:
                    pid = item.get("id")
                    qty = int(item.get("quantity") or item.get("qty") or 0)
                    if pid and qty > 0:
                        restore_updates[pid] = restore_updates.get(pid, 0) + qty

            # 標記訂單為取消
            order.status = "cancelled"
            order.save()
            cancel_count += 1

        # B. 批量更新商品庫存 (減少 DB連線次數)
        for pid, qty_to_add in restore_updates.items():
            Product.objects.filter(id=pid).update(stock=F("stock") + qty_to_add)

    # 2. 處理已完成 -> 歸檔
    archived_count = Order.objects.filter(store=store, status="final").update(
        status="archived"
    )

    return Response(
        {
            "status": "success",
            "message": f"結算完成：\n已取消 {cancel_count} 筆 (庫存已合併還原)\n已歸檔 {archived_count} 筆",
        }
    )


def mobile_admin(request):
    """
    對應網址: /backend/
    功能: 顯示手機版管理介面
    """
    # 1. 取得分店 (支援 ?store=ID 切換)
    stores = Store.objects.filter(is_active=True)
    current_store_id = request.GET.get("store")

    # 預設選第一間，或者選網址參數指定的那間
    if current_store_id:
        current_store = get_object_or_404(Store, id=current_store_id)
    else:
        current_store = stores.first()

    if not current_store:
        return HttpResponse("請先至 Django Admin 後台建立至少一間分店")

    # 2. 取得分類與商品
    # 這裡依照您的 Model 結構，Category 有 store 外鍵
    categories = Category.objects.filter(store=current_store).order_by("sort_order")

    # 取得篩選參數
    current_cat_id = request.GET.get("category")

    # 撈取該分店所有商品
    products = Product.objects.filter(store=current_store).select_related("category")

    # 如果有選特定分類，就進行過濾
    if current_cat_id and current_cat_id != "all":
        products = products.filter(category_id=current_cat_id)

    # 3. 初始化新增商品的表單 (給 Modal 用)
    product_form = ProductForm(store=current_store)

    context = {
        "stores": stores,
        "current_store": current_store,
        "categories": categories,
        "products": products,
        "current_cat_id": current_cat_id or "all",
        "product_form": product_form,
    }

    return render(request, "ordering/mobile_admin.html", context)


@require_POST
def quick_update_product(request, pk):
    """
    對應網址: /backend/api/update/<pk>/
    功能: HTMX 快速更新 (不刷新頁面)
    """
    product = get_object_or_404(Product, pk=pk)

    # 1. 更新價格 (轉型為 int)
    if "price" in request.POST:
        # 使用你原本定義的 _to_int 或是直接 try-except
        try:
            product.price = int(request.POST.get("price"))
        except (ValueError, TypeError):
            pass  # 如果傳來亂七八糟的值，就忽略

    # 2. 更新庫存 (🔥 關鍵修正：必須轉型為 int)
    if "stock" in request.POST:
        try:
            val = int(request.POST.get("stock"))
            product.stock = val
        except (ValueError, TypeError):
            pass  # 忽略非數字輸入

    # 3. 更新上下架
    if "is_active" in request.POST:
        val = request.POST.get("is_active")
        # HTMX 傳來的會是字串 "true" 或 "false"
        product.is_active = val == "true"

    if "description" in request.POST:
        product.description = request.POST.get("description")

    product.save()  # 現在這裡是 int，Model 裡的 <= 0 判斷就不會報錯了
    return HttpResponse("", status=200)


@require_POST
def create_product(request):
    # 1. 取得基本資料
    current_store_id = request.POST.get("store_id")
    current_store = get_object_or_404(Store, id=current_store_id)

    # 2. 檢查是否有勾選「批量建立」
    is_batch = request.POST.get("batch_create") == "true"

    # 3. 建立原本那筆 (當作主體)
    form = ProductForm(request.POST, store=current_store)

    if form.is_valid():
        try:
            with transaction.atomic():  # 開啟交易，確保要嘛全成功，要嘛全失敗
                # A. 先建立當前這筆
                master_product = form.save(commit=False)
                master_product.store = current_store
                master_product.save()

                # B. 如果勾選批量，開始複製到其他分店
                if is_batch:
                    # 找出所有"其他"營業中的分店
                    other_stores = Store.objects.filter(is_active=True).exclude(
                        id=current_store_id
                    )

                    # 取得原始分類名稱 (用來去別間店找對應)
                    source_cat_name = (
                        master_product.category.name
                        if master_product.category
                        else None
                    )

                    for target_store in other_stores:
                        target_category = None

                        # 處理分類對應
                        if source_cat_name:
                            # 嘗試在目標分店找同名分類，找不到就自動建立！
                            # slug 隨機產生或是用名稱轉碼皆可，這裡簡化用 uuid 避免衝突
                            import uuid

                            target_category, _ = Category.objects.get_or_create(
                                store=target_store,
                                name=source_cat_name,
                                defaults={
                                    "slug": f"auto_{uuid.uuid4().hex[:6]}",
                                    "sort_order": 99,
                                },
                            )

                        # 複製商品
                        Product.objects.create(
                            store=target_store,
                            category=target_category,
                            name=master_product.name,
                            price=master_product.price,
                            stock=master_product.stock,
                            flavor_options=master_product.flavor_options,
                            description=master_product.description,
                            is_active=master_product.is_active,
                        )

        except Exception as e:
            # 這裡可以加 log，暫時先簡單處理
            print(f"Batch Create Error: {e}")

    # 導回原本頁面
    return redirect(f"/backend/?store={current_store_id}")


def _to_int(val, default=None):
    try:
        if val is None or val == "":
            return default
        return int(val)
    except (TypeError, ValueError):
        return default


def _render_category_options(store_id):
    options_html = '<option value="">---------</option>'
    if not store_id:
        return options_html

    categories = Category.objects.filter(store_id=store_id, is_active=True).order_by(
        "sort_order", "id"
    )
    for cat in categories:
        options_html += (
            f'<option value="{cat.id}">{cat.name} ({cat.store.name})</option>'
        )
    return options_html


@require_POST
def api_create_category(request):
    """新增分類（支援 sort_order；未提供則自動排到最後）"""
    store_id = request.POST.get("store_id")
    name = (request.POST.get("name") or "").strip()
    sort_order = _to_int(request.POST.get("sort_order"), default=None)

    if not store_id:
        return JsonResponse(
            {"status": "error", "error": "missing_store_id"}, status=400
        )
    if not name:
        return JsonResponse({"status": "error", "error": "missing_name"}, status=400)

    store = get_object_or_404(Store, id=store_id)

    # 產生 slug：你原本用 uuid 方式 OK
    import uuid

    slug = f"cat_{uuid.uuid4().hex[:8]}"

    with transaction.atomic():
        # 若沒傳 sort_order，就取目前該分店最大 sort_order + 1
        if sort_order is None:
            current_max = (
                Category.objects.filter(store=store).aggregate(Max("sort_order"))[
                    "sort_order__max"
                ]
                or 0
            )
            sort_order = current_max + 1

        Category.objects.create(
            store=store,
            name=name,
            slug=slug,
            sort_order=sort_order,
            is_active=True,
        )

    # 回傳給你：可選擇直接 reload 或直接更新 select options
    return JsonResponse(
        {
            "status": "ok",
            "options_html": _render_category_options(store.id),
        }
    )


@require_POST
def api_update_category(request, pk):
    """修改分類（名稱/排序）"""
    cat = get_object_or_404(Category, pk=pk)

    new_name = request.POST.get("name")
    new_sort = _to_int(request.POST.get("sort_order"), default=None)

    changed_fields = []

    if new_name is not None:
        new_name = new_name.strip()
        if not new_name:
            return JsonResponse({"status": "error", "error": "empty_name"}, status=400)
        if new_name != cat.name:
            cat.name = new_name
            changed_fields.append("name")

    if new_sort is not None and new_sort != cat.sort_order:
        cat.sort_order = new_sort
        changed_fields.append("sort_order")

    if changed_fields:
        cat.save(update_fields=changed_fields)

    return JsonResponse(
        {
            "status": "ok",
            "options_html": _render_category_options(cat.store_id),
        }
    )


def api_get_categories_options(request):
    """給 modal 裡的 category 下拉選單用（依 sort_order 排序）"""
    store_id = request.GET.get("store_id")
    return HttpResponse(_render_category_options(store_id))


@login_required
def restock_page(request):
    """進貨頁面 (顯示清單)"""
    stores = Store.objects.filter(is_active=True)

    # 預設選第一間或網址參數指定
    current_store_id = request.GET.get("store")
    if current_store_id:
        current_store = get_object_or_404(Store, id=current_store_id)
    else:
        current_store = stores.first()

    if not current_store:
        return HttpResponse("請先建立分店")

    # 取得分類與商品 (一次撈出來，減少 DB 查詢)
    categories = (
        Category.objects.filter(store=current_store)
        .prefetch_related("products")
        .order_by("sort_order")
    )

    return render(
        request,
        "ordering/restock.html",
        {
            "stores": stores,
            "current_store": current_store,
            "categories": categories,
        },
    )


@require_POST
def batch_restock(request):
    """處理批次進貨 + 上下架狀態更新"""
    try:
        with transaction.atomic():
            # 遍歷所有 POST 資料
            for key, value in request.POST.items():

                # 1. 處理進貨數量 (name="add_stock_{id}")
                if key.startswith("add_stock_") and value:
                    try:
                        pid = int(key.split("_")[-1])
                        qty = int(value)
                        if qty != 0:
                            # 使用 F() 原子更新庫存
                            Product.objects.filter(id=pid).update(
                                stock=F("stock") + qty
                            )
                    except (ValueError, TypeError):
                        continue

                # 2. 處理上下架狀態 (name="is_active_{id}")
                # HTML Form 的 Checkbox 特性：有勾選才會送出值，沒勾選就不會送出 key
                # 所以我們需要用另一個 hidden input 來判斷「這個商品是否有在表單中」

                # 這裡採用更簡單的策略：
                # HTMX 送出時，我們只處理「有變更」的庫存
                # 至於上下架，建議在 UI 上做成「即時開關」(點了就存)，跟進貨數量分開處理會比較順
                # 但如果您堅持要一起送出，邏輯會變得非常複雜 (因為沒勾選 = 沒送出)

                # 🔥 修正策略：
                # 為了「快速」，上下架開關我們維持「點擊即時生效」(使用 quick_update_product)，
                # 這樣進貨表單就單純處理「數量」，避免邏輯打架。

        return HttpResponse("OK", status=200)

    except Exception as e:
        print(f"Restock Error: {e}")
        return HttpResponse("Error", status=500)

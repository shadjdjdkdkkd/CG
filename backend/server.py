from fastapi import FastAPI, APIRouter, HTTPException, Query, Header, Request, Response, Cookie, Body
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import asyncio
import logging
import re
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone, timedelta
import secrets  # Cryptographically secure random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import razorpay
from pincode_data import get_state_from_pincode
from analytics_tracker import AnalyticsTracker
from routes import admin as admin_routes
from routes import i18n as i18n_routes
from routes import consultation as consultation_routes
from routes import doctor_consultation as doctor_consultation_routes
from routes import mp_core as mp_core_routes
from routes import mp_ops as mp_ops_routes
from routes import mp_catalog as mp_catalog_routes
from routes import skincare_extras as skincare_extras_routes
from routes import sale_mode as sale_mode_routes
from routes import payment_policy as payment_policy_routes
from routes import delivery_men as delivery_men_routes
from routes import geo as geo_routes
from routes import warehouses as warehouses_routes
from routes import reels as reels_routes
from services.enhanced_analytics import EnhancedAnalyticsTracker, VisitorLeadTracker
from services.ai_content_generator import AIContentGenerator
from services.auto_blog_generator import AutoBlogGenerator
from services.image_service import get_image_for_category, get_image_for_keywords
from services.user_behavior_tracker import UserBehaviorTracker
from services.whatsapp_service import WhatsAppService
from services.trending_news_generator import TrendingNewsBlogGenerator
from services.referral_service import ReferralService
from services.delhivery_service import init_delhivery_service
from services.landing_page_service import LandingPageService
from routes import landing_pages as landing_page_routes
from routes import products as product_routes
from routes import concerns as concerns_routes
from routes import image_ai as image_ai_routes
from routes import reviews as reviews_routes
from routes import customer_auth as customer_auth_routes
from routes import bulk_import as bulk_import_routes
from routes import master_import as master_import_routes
from routes import gift_cards_and_ai as gift_cards_routes
from services.bulk_import_service import BulkImportService
from services.gift_card_service import GiftCardService


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')
# All AI generation must use the direct Gemini key only.
os.environ.pop('EMERGENT_LLM_KEY', None)

mongo_url = os.environ['MONGO_URL']
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ['DB_NAME']]
analytics_tracker = AnalyticsTracker(db)

# Initialize enhanced analytics
enhanced_analytics = EnhancedAnalyticsTracker(db)
visitor_lead_tracker = VisitorLeadTracker(db)
ai_content_generator = AIContentGenerator(db)
auto_blog_generator = AutoBlogGenerator(db)
user_behavior_tracker = UserBehaviorTracker(db)
whatsapp_service = WhatsAppService(db)
trending_news_generator = TrendingNewsBlogGenerator(db)
referral_service = ReferralService(db)
delhivery_service = init_delhivery_service(db)
landing_page_service = LandingPageService(db)

# Employee and Customer services
from services.employee_service import EmployeeService
from services.customer_service import CustomerService
employee_service = EmployeeService(db)
customer_service = CustomerService(db)

# Initialize product routes
product_routes.set_db(db)

# Initialize concerns + categories routes
concerns_routes.set_db(db)

# Initialize reviews routes
reviews_routes.set_db(db)

# Initialize admin routes with database
admin_routes.set_db(db)

# Initialize landing page routes
landing_page_routes.set_landing_page_service(landing_page_service)

# Share admin_sessions with admin routes (will be set after admin_sessions is defined)
# This is done later in the file after admin_sessions is created

# Initialize consultation routes with database
consultation_routes.set_db(db)

_razorpay_key_id = os.environ.get('RAZORPAY_KEY_ID')
_razorpay_key_secret = os.environ.get('RAZORPAY_KEY_SECRET')
razorpay_client = razorpay.Client(auth=(_razorpay_key_id, _razorpay_key_secret)) if _razorpay_key_id and _razorpay_key_secret else None

app = FastAPI()
api_router = APIRouter(prefix="/api")


class OrderCreate(BaseModel):
    name: str
    phone: str
    house_number: str
    area: str
    pincode: str
    state: str
    payment_method: str
    amount: float
    email: Optional[str] = None
    referral_code: Optional[str] = None
    referral_discount: Optional[float] = 0
    items: Optional[List[Dict[str, Any]]] = None  # Multi-product: [{slug, name, quantity, price}]
    combo_id: Optional[str] = None
    coupon_code: Optional[str] = None
    coupon_discount: Optional[float] = 0
    gift_card_code: Optional[str] = None
    gift_card_discount: Optional[float] = 0
    campaign_slug: Optional[str] = None  # /sale/{slug} attribution
    # Instant Delivery fields (Feb-2026) — populated by the CheckoutMap pin.
    delivery_lat: Optional[float] = None
    delivery_lng: Optional[float] = None
    delivery_type: Optional[str] = None  # 'instant' | 'standard'
    assigned_warehouse_id: Optional[str] = None
    eta_minutes: Optional[int] = None
    prepaid_bonus: bool = False  # ₹100 off when user opts-in on checkout (prepaid only)
    promo_active: bool = True  # Flash-offer 3-min timer; False = timer expired, strip perks
    session_id: Optional[str] = None  # stable per session — seeds the free-gift picker
    # Meta CAPI plumbing — browser sends fbp/fbc cookies + client user-agent so
    # the server-side Purchase event can dedup with the browser Pixel via event_id.
    fbp: Optional[str] = None
    fbc: Optional[str] = None
    client_user_agent: Optional[str] = None


class Order(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    order_id: str = Field(default_factory=lambda: f"CG{secrets.randbelow(900000) + 100000}")
    name: str
    phone: str
    house_number: str = ""
    area: str = ""
    pincode: str = ""
    state: str = ""
    address: Optional[str] = None
    payment_method: str
    amount: float
    email: Optional[str] = None
    delivery_timeline: str = ""
    status: str = "confirmed"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    referral_code: Optional[str] = None
    referral_link: Optional[str] = None
    referral_code_used: Optional[str] = None
    awb_number: Optional[str] = None
    shipping_provider: Optional[str] = None
    items: Optional[List[Dict[str, Any]]] = None
    combo_id: Optional[str] = None
    coupon_code: Optional[str] = None
    coupon_discount: Optional[float] = 0


class RazorpayOrderCreate(BaseModel):
    amount: float


class RazorpayPaymentVerify(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


async def send_order_confirmation_email(order: Order, referral_data: dict = None):
    """Routes through services.email_service — auto-switches Gmail → SendGrid
    past 250 emails/day (IST). One call sends BOTH customer + business emails.
    Business notifications support comma-separated recipients via BUSINESS_EMAIL."""
    from services import email_service
    try:
        business_email_raw = os.environ.get("BUSINESS_EMAIL") or os.environ.get("SMTP_USER") or ""
        business_recipients = [e.strip() for e in business_email_raw.split(",") if e.strip()]
        full_address = f"{order.house_number}, {order.area}, {order.state} - {order.pincode}"
        items_list = ", ".join(f"{it.name} ×{it.quantity}" for it in (order.items or []))

        # ---- Customer email ----
        referral_block_html = ""
        if referral_data and referral_data.get("referral_code"):
            ref_link = referral_data.get("referral_link",
                f"{os.environ.get('PUBLIC_SITE_URL') or 'https://celestaglow.com'}?ref={referral_data['referral_code']}")
            referral_block_html = (
                f"<div style=\"background:linear-gradient(135deg,#10b981,#059669);"
                f"color:#fff;padding:20px;margin-top:25px;border-radius:10px;text-align:center;\">"
                f"<h3 style=\"margin:0 0 10px;\">Share &amp; Earn {chr(0x20B9)}100</h3>"
                f"<p style=\"margin:0 0 15px;font-size:14px;\">Give friends {chr(0x20B9)}50 off; get "
                f"{chr(0x20B9)}100 back after their delivery.</p>"
                f"<div style=\"background:#fff;color:#059669;padding:12px;border-radius:8px;"
                f"font-weight:bold;font-size:14px;word-break:break-all;\">{ref_link}</div>"
                f"<p style=\"margin:15px 0 0;font-size:12px;opacity:0.9;\">Your referral code: "
                f"<strong>{referral_data['referral_code']}</strong></p></div>"
            )

        if order.email:
            text_c = (
                f"Order Confirmed: {order.order_id}\n\n"
                f"Items: {items_list}\n"
                f"Total: {chr(0x20B9)}{order.amount}\n"
                f"Payment: {order.payment_method}\n"
                f"Delivery: {order.delivery_timeline}\n\n"
                f"Shipping to:\n{order.name}\n+91 {order.phone}\n{full_address}\n\n"
                f"Thank you for choosing Celesta Glow."
            )
            html_c = (
                "<html><body style=\"font-family:Arial,sans-serif;line-height:1.6;color:#333;\">"
                "<div style=\"max-width:600px;margin:0 auto;padding:20px;background:#f9f9f9;\">"
                "<div style=\"background:linear-gradient(135deg,#047857,#0f766e);color:#fff;padding:30px;"
                "text-align:center;border-radius:10px;\">"
                "<h1 style=\"margin:0;font-size:28px;\">Order Confirmed</h1>"
                "<p style=\"margin:10px 0 0;font-size:16px;\">Thank you for choosing Celesta Glow</p>"
                "</div>"
                "<div style=\"background:#fff;padding:30px;margin-top:20px;border-radius:10px;\">"
                "<div style=\"background:#047857;color:#fff;padding:15px;text-align:center;border-radius:8px;margin-bottom:20px;\">"
                "<p style=\"margin:0;font-size:14px;\">Your Order ID</p>"
                f"<h2 style=\"margin:5px 0 0;font-size:32px;letter-spacing:2px;\">{order.order_id}</h2>"
                "</div>"
                "<h3 style=\"color:#047857;margin-bottom:15px;\">Order Details</h3>"
                f"<p style=\"margin:5px 0;\"><strong>Items:</strong> {items_list}</p>"
                f"<p style=\"margin:5px 0;\"><strong>Total:</strong> "
                f"<span style=\"color:#059669;font-weight:bold;\">{chr(0x20B9)}{order.amount}</span></p>"
                f"<p style=\"margin:5px 0;\"><strong>Payment:</strong> {order.payment_method}</p>"
                f"<p style=\"margin:5px 0;\"><strong>Delivery:</strong> {order.delivery_timeline}</p>"
                "<h3 style=\"color:#047857;margin-top:25px;margin-bottom:15px;\">Delivery Address</h3>"
                f"<p style=\"margin:5px 0;\"><strong>{order.name}</strong></p>"
                f"<p style=\"margin:5px 0;\">+91 {order.phone}</p>"
                f"<p style=\"margin:5px 0;\">{full_address}</p>"
                f"{referral_block_html}"
                "</div>"
                "<div style=\"text-align:center;margin-top:20px;color:#666;font-size:12px;\">"
                f"<p>Questions? Contact us at {(business_recipients[0] if business_recipients else 'support@celestaglow.com')}</p>"
                "<p style=\"margin-top:10px;\">&copy; 2025 Celesta Glow. All rights reserved.</p>"
                "</div></div></body></html>"
            )
            res_c = await email_service.send_email(
                to=order.email,
                subject=f"Order Confirmed - {order.order_id} | Celesta Glow",
                text=text_c, html=html_c,
            )
            if res_c.get("success"):
                logging.info(f"[order-email] customer confirmation sent for {order.order_id} via {res_c.get('channel')}")
            else:
                logging.warning(f"[order-email] customer send failed for {order.order_id}: {res_c.get('reason')}")

        # ---- Business notification email ----
        for biz_to in business_recipients:
            text_b = (
                f"New Order: {order.order_id}\n"
                f"Items: {items_list}\nTotal: {chr(0x20B9)}{order.amount}\n"
                f"Payment: {order.payment_method}\nCustomer: {order.name}\n+91 {order.phone}\n"
                f"Email: {order.email or 'N/A'}\nAddress: {full_address}"
            )
            html_b = (
                "<html><body style=\"font-family:Arial,sans-serif;line-height:1.6;color:#333;\">"
                "<div style=\"max-width:600px;margin:0 auto;padding:20px;background:#f9f9f9;\">"
                "<div style=\"background:#047857;color:#fff;padding:20px;text-align:center;border-radius:10px;\">"
                "<h2 style=\"margin:0;\">New Order Received</h2>"
                f"<h1 style=\"margin:10px 0;font-size:36px;letter-spacing:2px;\">{order.order_id}</h1>"
                "</div>"
                "<div style=\"background:#fff;padding:25px;margin-top:20px;border-radius:10px;\">"
                "<h3 style=\"color:#047857;margin-bottom:15px;\">Order</h3>"
                f"<p><strong>Items:</strong> {items_list}</p>"
                f"<p><strong>Total:</strong> <span style=\"color:#059669;font-weight:bold;\">{chr(0x20B9)}{order.amount}</span></p>"
                f"<p><strong>Payment:</strong> {order.payment_method}</p>"
                f"<p><strong>Delivery:</strong> {order.delivery_timeline}</p>"
                "<h3 style=\"color:#047857;margin-top:20px;margin-bottom:15px;\">Customer</h3>"
                f"<p><strong>Name:</strong> {order.name}</p>"
                f"<p><strong>Phone:</strong> +91 {order.phone}</p>"
                f"<p><strong>Email:</strong> {order.email or 'Not provided'}</p>"
                f"<p><strong>Address:</strong> {full_address}</p>"
                "<div style=\"background:#FFFBEB;border-left:4px solid #F59E0B;padding:15px;margin-top:20px;border-radius:5px;\">"
                "<p style=\"margin:0;color:#92400E;\"><strong>Action:</strong> Review + call customer, then "
                "send to Delhivery from the admin panel.</p></div>"
                "</div></div></body></html>"
            )
            res_b = await email_service.send_email(
                to=biz_to,
                subject=f"New Order Received - {order.order_id}",
                text=text_b, html=html_b,
            )
            if res_b.get("success"):
                logging.info(f"[order-email] business notif sent to {biz_to} for {order.order_id} via {res_b.get('channel')}")
            else:
                logging.warning(f"[order-email] business send failed for {biz_to} / {order.order_id}: {res_b.get('reason')}")
    except Exception as e:
        logging.error(f"Failed to send order email: {e}")


@api_router.get("/admin/email/stats")
async def admin_email_stats(x_admin_token: str = Header(None, alias="X-Admin-Token")):
    """How many emails were sent today (IST), broken out by channel (Gmail vs SendGrid).
    Also tells you which channel the NEXT email will use."""
    # Cheap auth: session token OR active admin password (env-seed inert
    # once a custom password is saved).
    import hashlib as _hashlib
    from services.admin_auth import get_cached_active_admin_hash
    if not x_admin_token:
        raise HTTPException(status_code=401, detail="Invalid admin token")
    if x_admin_token in admin_sessions:
        pass  # OK
    elif _hashlib.sha256(x_admin_token.encode()).hexdigest() != get_cached_active_admin_hash():
        raise HTTPException(status_code=401, detail="Invalid admin token")
    from services import email_service as _es
    return await _es.get_daily_stats()


@api_router.get("/")
async def root():
    return {"message": "Celesta Glow API"}


@api_router.post("/create-razorpay-order")
async def create_razorpay_order(order_data: RazorpayOrderCreate):
    if razorpay_client is None:
        raise HTTPException(
            status_code=503,
            detail="Online payment is not configured yet. Please use Cash on Delivery or ask the admin to add Razorpay keys."
        )
    try:
        amount_in_paise = int(order_data.amount * 100)
        logging.info(f"Creating Razorpay order for amount: {amount_in_paise} paise")
        razorpay_order = razorpay_client.order.create({
            "amount": amount_in_paise,
            "currency": "INR",
            "payment_capture": 1
        })
        logging.info(f"Razorpay order created successfully: {razorpay_order}")
        return razorpay_order
    except Exception as e:
        logging.error(f"Razorpay order creation failed: {type(e).__name__} - {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/verify-payment")
async def verify_payment(payment_data: RazorpayPaymentVerify):
    if razorpay_client is None:
        raise HTTPException(status_code=503, detail="Razorpay not configured")
    try:
        razorpay_client.utility.verify_payment_signature({
            'razorpay_order_id': payment_data.razorpay_order_id,
            'razorpay_payment_id': payment_data.razorpay_payment_id,
            'razorpay_signature': payment_data.razorpay_signature
        })
        # S3 fix: verify the captured payment amount matches the order amount.
        # Without this check, an attacker can pay ₹1 for a ₹5000 order using
        # a hijacked order_id from a different user.
        try:
            rzp_order = razorpay_client.order.fetch(payment_data.razorpay_order_id)
            rzp_payment = razorpay_client.payment.fetch(payment_data.razorpay_payment_id)
            if int(rzp_payment.get("amount", 0)) < int(rzp_order.get("amount", 0)):
                logging.warning(
                    f"[security] Razorpay amount mismatch order={rzp_order.get('amount')} "
                    f"paid={rzp_payment.get('amount')} payment_id={payment_data.razorpay_payment_id}"
                )
                raise HTTPException(status_code=400, detail="Payment amount mismatch")
            if rzp_payment.get("status") not in ("captured", "authorized"):
                raise HTTPException(status_code=400, detail=f"Payment not captured (status: {rzp_payment.get('status')})")
        except HTTPException:
            raise
        except Exception as fetch_err:
            logging.warning(f"[razorpay] amount-check fetch failed: {fetch_err}")
        return {"verified": True}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=400, detail="Payment verification failed")


@api_router.post("/orders", response_model=Order)
async def create_order(order_input: OrderCreate, request: Request):
    # ===== STOCK VALIDATION + DECREMENT =====
    # Build a list of (slug, qty, shade_id) tuples from incoming items + combo (combos decrement underlying products too)
    stock_changes = []  # list of (slug, qty, shade_id_or_None)
    if order_input.items:
        for it in order_input.items:
            slug = it.get('slug') or it.get('product_slug')
            qty = int(it.get('quantity') or 1)
            shade_id = it.get('shade_id')
            if slug:
                stock_changes.append((slug, qty, shade_id))
    if order_input.combo_id:
        combo = await db.combos.find_one({"combo_id": order_input.combo_id}, {"_id": 0})
        if combo:
            for slug in (combo.get('product_slugs') or []):
                stock_changes.append((slug, 1, None))
    # Validate stock for non-TBL products + REJECT any TBL product (defense in depth)
    # PERF (Feb-2026): batch-fetch all products in ONE query (was N+1). Cuts
    # order-placement latency by ~200-500 ms on 3+ item carts.
    _unique_slugs = list({s for s, _, _ in stock_changes})
    _stock_docs = {}
    if _unique_slugs:
        async for p in db.products.find(
            {"slug": {"$in": _unique_slugs}},
            {"_id": 0, "slug": 1, "stock_qty": 1, "is_to_be_launched": 1, "name": 1, "shades": 1}
        ):
            _stock_docs[p["slug"]] = p
    for slug, qty, shade_id in stock_changes:
        prod = _stock_docs.get(slug)
        if not prod:
            continue
        if prod.get("is_to_be_launched"):
            # TBL products cannot be ordered until admin marks them LIVE.
            raise HTTPException(
                status_code=400,
                detail=f"{prod.get('name', slug)} is To Be Launched and not yet available for purchase. Please remove it from your cart."
            )
        # Shade-aware stock check
        shades = prod.get("shades") or []
        if shades and shade_id:
            shade = next((s for s in shades if str(s.get("id")) == str(shade_id)), None)
            if not shade:
                raise HTTPException(status_code=400, detail=f"{prod.get('name', slug)}: selected shade no longer available")
            shade_stock = shade.get("stock_qty")
            if shade_stock is not None and shade_stock < qty:
                raise HTTPException(status_code=400, detail=f"Out of stock: {prod.get('name', slug)} — {shade.get('name','shade')} (only {shade_stock} left)")
        else:
            available = prod.get("stock_qty")
            if available is not None and available < qty:
                raise HTTPException(status_code=400, detail=f"Out of stock: {prod.get('name', slug)} (only {available} left)")

    # ===== SERVER-SIDE AMOUNT RECALCULATION (S1/S2 fix) =====
    # NEVER trust client-sent amount. To guarantee parity with the cart UI math
    # (tiered delivery + tax bands + coupon + gift card + stock caps), we delegate
    # the entire calculation to `/api/cart/validate` so the two endpoints can never
    # drift. Anything that changed in cart/validate is auto-mirrored here.
    from routes.products import validate_cart as _validate_cart, CartValidateRequest as _CartReq, CartItem as _CartItem

    _cart_items_in: list = []
    for it in (order_input.items or []):
        slug = it.get('slug') or it.get('product_slug')
        c_id = it.get('combo_id')
        qty = int(it.get('quantity') or 1)
        if slug:
            _cart_items_in.append(_CartItem(product_slug=slug, quantity=qty, shade_id=it.get('shade_id')))
        elif c_id:
            _cart_items_in.append(_CartItem(combo_id=c_id, quantity=qty))
    if order_input.combo_id and not any(getattr(c, 'combo_id', None) == order_input.combo_id for c in _cart_items_in):
        _cart_items_in.append(_CartItem(combo_id=order_input.combo_id, quantity=1))

    cart_calc = await _validate_cart(_CartReq(
        items=_cart_items_in,
        coupon_code=order_input.coupon_code,
        gift_card_code=order_input.gift_card_code,
        payment_method=(order_input.payment_method or "prepaid"),
        prepaid_bonus=bool(order_input.prepaid_bonus),
        promo_active=bool(order_input.promo_active),
        session_id=getattr(order_input, "session_id", None) or (request.headers.get("x-session-id") or None),
    ))

    # MOQ enforcement (cart/validate only flags; we hard-block at checkout)
    if cart_calc.get("moq_block"):
        moq_amt = cart_calc.get("moq_amount", 300)
        raise HTTPException(
            status_code=400,
            detail=f"Minimum order amount is ₹{moq_amt}. Add more items to your cart."
        )
    # If gift card was sent but rejected by cart_validate, fail loudly
    gc_info = cart_calc.get("gift_card") or {}
    if order_input.gift_card_code and gc_info.get("error"):
        raise HTTPException(status_code=400, detail=f"Gift card: {gc_info.get('error')}")

    server_final_amount = float(cart_calc.get("total") or 0)
    server_coupon_discount = float(cart_calc.get("discount") or 0)
    server_coupon_code = (order_input.coupon_code or None) if server_coupon_discount > 0 else None
    server_gift_card_discount = float(cart_calc.get("gift_card_discount") or 0)
    # Referral discount is informational metadata — cart total does NOT subtract it
    # (matches cart UI). We record the user's referral_code on the order, but never
    # alter the amount they pay.
    server_referral_discount = 0.0

    # Reject if client-sent amount differs by more than ₹1 (rounding tolerance)
    client_amount = float(order_input.amount or 0)
    if abs(client_amount - server_final_amount) > 1.0:
        logging.warning(
            f"[security] amount mismatch — client={client_amount} server={server_final_amount} "
            f"subtotal={cart_calc.get('subtotal')} coupon_disc={server_coupon_discount} "
            f"shipping_fee={cart_calc.get('shipping_fee')} pm={order_input.payment_method}"
        )
        raise HTTPException(
            status_code=400,
            detail=f"Amount mismatch — your cart total has changed. Please refresh and try again. (server: ₹{server_final_amount}, sent: ₹{client_amount})"
        )

    # Override client values with server-computed authoritative values
    order_input.amount = server_final_amount
    order_input.coupon_code = server_coupon_code
    order_input.coupon_discount = server_coupon_discount
    order_input.referral_discount = server_referral_discount
    order_input.gift_card_discount = server_gift_card_discount

    order_obj = Order(**order_input.model_dump())
    
    if order_obj.payment_method == "COD":
        order_obj.delivery_timeline = "5-7 Business Days"
    else:
        order_obj.delivery_timeline = "Fast Delivery (2-3 Days)"
    
    doc = order_obj.model_dump()
    doc['created_at'] = doc['created_at'].isoformat()
    
    # Store multi-product items if provided
    if order_input.items:
        doc['items'] = order_input.items
    if order_input.combo_id:
        doc['combo_id'] = order_input.combo_id
    if order_input.campaign_slug:
        # Attribution: order came via a /sale/{slug} landing page.
        doc['campaign_slug'] = order_input.campaign_slug
    # Instant Delivery — persist coords + assigned warehouse (Feb-2026).
    for field in ('delivery_lat', 'delivery_lng', 'delivery_type', 'assigned_warehouse_id', 'eta_minutes'):
        val = getattr(order_input, field, None)
        if val is not None:
            doc[field] = val
    if order_input.coupon_code:
        doc['coupon_code'] = order_input.coupon_code
        doc['coupon_discount'] = order_input.coupon_discount
        # Increment coupon usage
        await db.coupons.update_one({"code": order_input.coupon_code.upper()}, {"$inc": {"used_count": 1}})
    
    # Check if this order was made through a referral
    referral_code = order_input.referral_code if hasattr(order_input, 'referral_code') else None
    if referral_code:
        doc['referral_code_used'] = referral_code
        # Record the referral purchase
        await referral_service.record_referral_purchase(referral_code, {
            "order_id": doc['order_id'],
            "phone": doc.get('phone'),
            "name": doc.get('name'),
            "amount": doc.get('final_amount', doc.get('cod_amount', 599))
        })
    
    # Attach the free gift (Feb-2026) so it appears on order-success, /orders,
    # admin panels and the WhatsApp confirmation. cart_calc already picked the
    # gift deterministically from session_id, so client + server agree.
    fg = cart_calc.get("free_gift")
    if fg and isinstance(fg, dict) and fg.get("slug"):
        doc['free_gift'] = fg

    await db.orders.insert_one(doc)

    # Redeem gift card AFTER order is inserted (idempotent on order_id)
    if order_input.gift_card_code and server_gift_card_discount > 0:
        try:
            from services.gift_card_service import GiftCardService
            gc_svc = GiftCardService(db)
            await gc_svc.redeem(order_input.gift_card_code, server_gift_card_discount, doc['order_id'])
            await db.orders.update_one(
                {"order_id": doc['order_id']},
                {"$set": {
                    "gift_card_code": order_input.gift_card_code,
                    "gift_card_discount": server_gift_card_discount,
                }},
            )
        except Exception as e:
            logging.warning(f"[order] gift card redemption failed for {doc['order_id']}: {e}")

    # Decrement stock_qty atomically on live (non-TBL) products — guard against overselling
    # Reuse the batch we already fetched above; no extra Mongo reads.
    for slug, qty, shade_id in stock_changes:
        prod = _stock_docs.get(slug)
        if not prod or prod.get("is_to_be_launched"):
            continue
        shades = prod.get("shades") or []
        if shades and shade_id:
            # Shade-level atomic decrement using positional operator
            result = await db.products.update_one(
                {"slug": slug, "shades": {"$elemMatch": {"id": shade_id, "stock_qty": {"$gte": qty}}}},
                {"$inc": {"shades.$.stock_qty": -qty}, "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}}
            )
        else:
            # Atomic conditional decrement: only succeeds if stock_qty >= qty
            result = await db.products.update_one(
                {"slug": slug, "stock_qty": {"$gte": qty}},
                {"$inc": {"stock_qty": -qty}, "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}}
            )
        if result.matched_count == 0:
            # Race lost — stock was depleted between validation and decrement.
            # Roll back any prior decrements in this order to prevent partial fulfillment.
            for prev_slug, prev_qty, prev_shade in stock_changes:
                if prev_slug == slug and prev_shade == shade_id:
                    break
                if prev_shade:
                    await db.products.update_one(
                        {"slug": prev_slug, "shades.id": prev_shade},
                        {"$inc": {"shades.$.stock_qty": prev_qty}}
                    )
                else:
                    await db.products.update_one(
                        {"slug": prev_slug},
                        {"$inc": {"stock_qty": prev_qty}}
                    )
            await db.orders.delete_one({"order_id": doc.get("order_id")})
            raise HTTPException(status_code=409, detail=f"Out of stock: {prod.get('name', slug)} sold out before checkout completed")
    
    # Generate referral code for this customer
    referral_data = await referral_service.create_referral({
        "phone": doc.get('phone'),
        "email": doc.get('email'),
        "name": doc.get('name'),
        "order_id": doc['order_id']
    })
    
    # Store referral info in the order document
    await db.orders.update_one(
        {"order_id": doc['order_id']},
        {"$set": {
            "referral_code": referral_data['referral_code'],
            "referral_link": referral_data['referral_link']
        }}
    )
    
    # Add referral info to response
    order_obj_dict = order_obj.model_dump()
    order_obj_dict['referral_code'] = referral_data['referral_code']
    order_obj_dict['referral_link'] = referral_data['referral_link']
    
    # PERF (Feb-2026): order-confirmation email is fire-and-forget — used to
    # block the checkout POST for 2-6 s on slow SMTP/SendGrid days and was
    # the #1 reason "place order" felt unresponsive. Result now returns as
    # soon as Mongo commits; the mailer keeps running on the event loop.
    asyncio.create_task(send_order_confirmation_email(order_obj, referral_data))

    # ===== Meta Conversions API — Purchase (server-side, dedups with browser Pixel via event_id=order_id) =====
    try:
        from services import meta_capi
        if meta_capi.is_enabled():
            # Split full name → first / last (Meta prefers separate fields)
            _name_parts = (order_obj.name or "").strip().split(maxsplit=1)
            _fn = _name_parts[0] if _name_parts else None
            _ln = _name_parts[1] if len(_name_parts) > 1 else None
            _client_ip = (request.headers.get("x-forwarded-for") or request.client.host or "").split(",")[0].strip() or None
            _ua = order_input.client_user_agent or request.headers.get("user-agent")

            _contents = []
            for it in (order_obj.items or []):
                _contents.append({
                    "id": it.get("slug") or it.get("combo_id") or "celesta_glow",
                    "quantity": it.get("quantity") or 1,
                    "item_price": float(it.get("price") or 0),
                })
            _num_items = sum((it.get("quantity") or 1) for it in (order_obj.items or [])) or 1
            _content_name = ", ".join((it.get("name") or it.get("slug") or "") for it in (order_obj.items or [])) or "Celesta Glow Products"

            _user_data = meta_capi.build_user_data(
                email=order_obj.email,
                phone=order_obj.phone,
                first_name=_fn,
                last_name=_ln,
                city=(order_obj.address or ""),
                state=order_obj.state,
                pincode=order_obj.pincode,
                country="in",
                external_id=order_obj.phone or order_obj.email or order_obj.order_id,
                client_ip=_client_ip,
                client_user_agent=_ua,
                fbp=order_input.fbp,
                fbc=order_input.fbc,
            )
            # Fire and forget — never block checkout on Meta latency
            asyncio.create_task(meta_capi.track_purchase(
                order_id=order_obj.order_id,
                value=float(order_obj.amount or 0),
                contents=_contents,
                num_items=_num_items,
                user_data=_user_data,
                content_name=_content_name,
                event_source_url=f"https://celestaglow.com/order-success/{order_obj.order_id}",
            ))
    except Exception as _capi_err:
        logging.warning(f"[meta_capi] Purchase dispatch failed for {order_obj.order_id}: {_capi_err}")

    # Auto-Delhivery DISABLED — admin reviews each order, calls the customer, then
    # manually clicks "Send to Delhivery" from the admin panel.

    return order_obj_dict


@api_router.get("/orders/{order_id}", response_model=Order)
async def get_order(order_id: str):
    order = await db.orders.find_one({"order_id": order_id}, {"_id": 0})
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if isinstance(order['created_at'], str):
        order['created_at'] = datetime.fromisoformat(order['created_at'])
    
    return order


@api_router.get("/orders", response_model=List[Order])
async def get_all_orders(
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    x_employee_token: str = Header(None, alias="X-Employee-Token")
):
    # Allow admin or employee with orders permission
    if x_admin_token:
        verify_admin_token(x_admin_token)
    elif x_employee_token:
        session = verify_employee_token(x_employee_token)
        if not session["permissions"].get("orders"):
            raise HTTPException(status_code=403, detail="No permission to view orders")
    else:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    orders = await db.orders.find({}, {"_id": 0}).to_list(1000)
    
    for order in orders:
        if isinstance(order['created_at'], str):
            order['created_at'] = datetime.fromisoformat(order['created_at'])
    
    return orders


# ==================== ORDER STATUS UPDATE WITH EMAIL ====================

class OrderStatusUpdate(BaseModel):
    status: str  # "shipped", "delivered", "cancelled"

def send_order_status_email(order: dict, new_status: str):
    """Send email notification when order status changes"""
    if not order.get('email'):
        logging.info(f"No email for order {order['order_id']}, skipping email notification")
        return
    
    smtp_host = os.environ.get('SMTP_HOST', 'smtp.gmail.com')
    smtp_port = int(os.environ.get('SMTP_PORT', 587))
    smtp_user = os.environ.get('SMTP_USER')
    smtp_password = os.environ.get('SMTP_PASSWORD')
    
    if not smtp_user or not smtp_password:
        logging.warning("SMTP credentials not configured, skipping email")
        return
    
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"Celesta Glow - Order {order['order_id']} {new_status.capitalize()}"
        msg['From'] = smtp_user
        msg['To'] = order['email']
        
        if new_status == "shipped":
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px; }}
                    .container {{ max-width: 600px; margin: 0 auto; background: white; border-radius: 16px; padding: 30px; }}
                    .header {{ text-align: center; margin-bottom: 30px; }}
                    .logo {{ font-size: 24px; font-weight: bold; color: #22c55e; }}
                    .status-badge {{ background: #3b82f6; color: white; padding: 8px 16px; border-radius: 20px; display: inline-block; font-weight: bold; }}
                    .order-box {{ background: #f8fafc; padding: 20px; border-radius: 12px; margin: 20px 0; }}
                    .footer {{ text-align: center; color: #666; font-size: 12px; margin-top: 30px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <div class="logo">Celesta Glow</div>
                        <p style="color: #666;">Your order is on its way!</p>
                    </div>
                    
                    <div style="text-align: center; margin-bottom: 20px;">
                        <span class="status-badge">🚚 SHIPPED</span>
                    </div>
                    
                    <p>Hi {order['name']},</p>
                    <p>Great news! Your order has been shipped and is on its way to you.</p>
                    
                    <div class="order-box">
                        <p><strong>Order ID:</strong> {order['order_id']}</p>
                        <p><strong>Product:</strong> Celesta Glow Anti-Aging Products</p>
                        <p><strong>Amount:</strong> ₹{order['amount']}</p>
                        <p><strong>Delivery Address:</strong><br/>
                        {order['house_number']}, {order['area']}<br/>
                        {order['state']} - {order['pincode']}</p>
                    </div>
                    
                    <p>Expected delivery: <strong>2-3 business days</strong></p>
                    
                    <p>Track your order or contact us on WhatsApp: <a href="https://wa.me/919446125745">+91 9446125745</a></p>
                    
                    <div class="footer">
                        <p>Thank you for choosing Celesta Glow!</p>
                        <p>© 2024 Celesta Glow. All rights reserved.</p>
                    </div>
                </div>
            </body>
            </html>
            """
        elif new_status == "delivered":
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <style>
                    body {{ font-family: Arial, sans-serif; background-color: #f5f5f5; padding: 20px; }}
                    .container {{ max-width: 600px; margin: 0 auto; background: white; border-radius: 16px; padding: 30px; }}
                    .header {{ text-align: center; margin-bottom: 30px; }}
                    .logo {{ font-size: 24px; font-weight: bold; color: #22c55e; }}
                    .status-badge {{ background: #22c55e; color: white; padding: 8px 16px; border-radius: 20px; display: inline-block; font-weight: bold; }}
                    .order-box {{ background: #f8fafc; padding: 20px; border-radius: 12px; margin: 20px 0; }}
                    .tips-box {{ background: #fef3c7; padding: 20px; border-radius: 12px; margin: 20px 0; border-left: 4px solid #f59e0b; }}
                    .footer {{ text-align: center; color: #666; font-size: 12px; margin-top: 30px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <div class="logo">Celesta Glow</div>
                        <p style="color: #666;">Your order has been delivered!</p>
                    </div>
                    
                    <div style="text-align: center; margin-bottom: 20px;">
                        <span class="status-badge">✅ DELIVERED</span>
                    </div>
                    
                    <p>Hi {order['name']},</p>
                    <p>Your Celesta Glow order has been successfully delivered!</p>
                    
                    <div class="order-box">
                        <p><strong>Order ID:</strong> {order['order_id']}</p>
                        <p><strong>Product:</strong> Celesta Glow Anti-Aging Products</p>
                        <p><strong>Amount:</strong> ₹{order['amount']}</p>
                    </div>
                    
                    <div class="tips-box">
                        <p><strong>💡 Pro Tip for Best Results:</strong></p>
                        <p>Follow the usage instructions included with your products for best results. Use your skincare routine consistently — morning and night.</p>
                    </div>
                    
                    <p>We'd love to hear about your experience! Reply to this email or share your feedback on WhatsApp: <a href="https://wa.me/919446125745">+91 9446125745</a></p>
                    
                    <div class="footer">
                        <p>Thank you for choosing Celesta Glow!</p>
                        <p>© 2024 Celesta Glow. All rights reserved.</p>
                    </div>
                </div>
            </body>
            </html>
            """
        else:
            return  # Don't send email for other statuses
        
        part = MIMEText(html_content, 'html')
        msg.attach(part)
        
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        
        logging.info(f"Order status email sent to {order['email']} for order {order['order_id']} - Status: {new_status}")
    except Exception as e:
        logging.error(f"Failed to send order status email: {str(e)}")


@api_router.put("/orders/{order_id}/status")
async def update_order_status(order_id: str, status_update: OrderStatusUpdate):
    """Update order status and send email notification"""
    # Find the order
    order = await db.orders.find_one({"order_id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    new_status = status_update.status.lower()
    valid_statuses = ["confirmed", "shipped", "delivered", "cancelled"]
    
    if new_status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
    
    # If marking as shipped, create Delhivery shipment first
    delhivery_result = None
    if new_status == "shipped" and not order.get("awb_number"):
        try:
            from services.delhivery_service import delhivery_service
            if delhivery_service:
                # Prepare order data for Delhivery.
                # IMPORTANT: For COD orders the customer pays the entire
                # ``order.amount`` on delivery — no Razorpay advance is taken
                # at checkout. Delhivery must therefore collect the FULL
                # ``amount`` field. Earlier this code subtracted ₹49 (a
                # phantom "COD advance"), which made the collectable show
                # up ~₹50 less than what the customer actually owes.
                is_cod = "COD" in (order.get("payment_method") or "")
                order_for_delhivery = {
                    "order_id": order.get("order_id"),
                    "name": order.get("name"),
                    "phone": order.get("phone"),
                    "house_number": order.get("house_number", ""),
                    "area": order.get("area", ""),
                    "pincode": order.get("pincode"),
                    "city": order.get("city", ""),
                    "state": order.get("state", ""),
                    "payment_method": "cod" if is_cod else "prepaid",
                    "cod_balance": order.get("amount", 0) if is_cod else 0,
                    "total_amount": order.get("amount", 0)
                }
                delhivery_result = await delhivery_service.create_shipment(order_for_delhivery)
                logging.info(f"Delhivery shipment created for order {order_id}: {delhivery_result}")
        except Exception as e:
            logging.error(f"Delhivery shipment creation failed: {str(e)}")
            delhivery_result = {"success": False, "error": str(e)}
    
    # Update the order status
    update_data = {
        "status": new_status,
        "status_updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    # If Delhivery shipment was created, add AWB to update
    if delhivery_result and delhivery_result.get("success"):
        update_data["awb_number"] = delhivery_result.get("awb")
        update_data["shipping_provider"] = "delhivery"
    
    await db.orders.update_one(
        {"order_id": order_id},
        {"$set": update_data}
    )
    
    # Get updated order data
    updated_order = await db.orders.find_one({"order_id": order_id}, {"_id": 0})
    
    # If delivered and this was a referred order, process cashback for the referrer
    referral_cashback = None
    if new_status == "delivered" and updated_order.get("referral_code_used"):
        referral_cashback = await referral_service.process_delivery_cashback(order_id)
        logging.info(f"Referral cashback processed for order {order_id}: {referral_cashback}")
    
    # Send email notification if shipped or delivered
    if new_status in ["shipped", "delivered"]:
        send_order_status_email(updated_order, new_status)
    
    return {
        "success": True,
        "order_id": order_id,
        "new_status": new_status,
        "email_sent": new_status in ["shipped", "delivered"] and bool(updated_order.get('email')),
        "referral_cashback": referral_cashback,
        "delhivery": delhivery_result,
        "awb_number": updated_order.get("awb_number")
    }


class OrderEmailUpdate(BaseModel):
    email: str


@api_router.delete("/admin/orders/{order_id}")
async def admin_delete_order(order_id: str, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    """Admin: hard-delete a single order document. Prefer status='cancelled'
    for real-world use — this endpoint is for cleaning up test/spam rows."""
    verify_admin_token(x_admin_token)
    result = await db.orders.delete_one({"order_id": order_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"success": True, "deleted": order_id}


@api_router.put("/orders/{order_id}/email")
async def update_order_email(order_id: str, email_update: OrderEmailUpdate):
    """Update customer email for an order (Admin only)"""
    # Find the order
    order = await db.orders.find_one({"order_id": order_id})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    # Validate email format
    import re
    email = email_update.email.strip().lower()
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    
    if not re.match(email_regex, email):
        raise HTTPException(status_code=400, detail="Invalid email format")
    
    # Update the order email
    await db.orders.update_one(
        {"order_id": order_id},
        {"$set": {
            "email": email,
            "email_updated_at": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    return {
        "success": True,
        "order_id": order_id,
        "email": email
    }


@api_router.get("/stats/recent-orders")
async def get_recent_orders_count():
    count = await db.orders.count_documents({})
    base_count = 30 + secrets.randbelow(16)  # 0-15 range
    return {"count": base_count + count}


# ==================== PUSH NOTIFICATIONS ====================

class PushSubscription(BaseModel):
    visitor_id: str
    subscription: dict

class PushNotificationRequest(BaseModel):
    title: str
    body: str
    url: Optional[str] = "/"
    visitor_ids: Optional[List[str]] = None  # None = send to all

@api_router.post("/notifications/subscribe")
async def subscribe_to_notifications(data: PushSubscription):
    """Store push notification subscription for a visitor"""
    try:
        await db.push_subscriptions.update_one(
            {"visitor_id": data.visitor_id},
            {
                "$set": {
                    "subscription": data.subscription,
                    "subscribed_at": datetime.now(timezone.utc).isoformat(),
                    "active": True
                }
            },
            upsert=True
        )
        return {"success": True, "message": "Subscribed to notifications"}
    except Exception as e:
        logging.error(f"Push subscription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@api_router.post("/admin/notifications/send")
async def send_push_notification(
    data: PushNotificationRequest,
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    """Send in-site notification to CURRENT visitors only (expires in 5 minutes)"""
    if x_admin_token != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    notification_id = f"notif_{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)
    
    # Store as a GLOBAL broadcast notification - EXPIRES IN 5 MINUTES (only for current visitors)
    broadcast_doc = {
        "notification_id": notification_id,
        "title": data.title,
        "body": data.body,
        "url": data.url or "/",
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=5)).isoformat(),  # Expires in 5 minutes - only current visitors
        "active": True
    }
    
    await db.broadcast_notifications.insert_one(broadcast_doc)
    
    # Also send to push subscribers if any
    push_sent = 0
    query = {"active": True}
    if data.visitor_ids:
        query["visitor_id"] = {"$in": data.visitor_ids}
    
    subscriptions = await db.push_subscriptions.find(query, {"_id": 0}).to_list(1000)
    
    for sub in subscriptions:
        try:
            await db.pending_notifications.insert_one({
                "notification_id": notification_id,
                "visitor_id": sub["visitor_id"],
                "title": data.title,
                "body": data.body,
                "url": data.url,
                "created_at": now.isoformat(),
                "read": False
            })
            push_sent += 1
        except Exception as e:
            logging.error(f"Failed to queue push notification: {e}")
    
    # Log the notification broadcast
    await db.notification_logs.insert_one({
        "notification_id": notification_id,
        "title": data.title,
        "body": data.body,
        "url": data.url,
        "sent_at": now.isoformat(),
        "push_recipients": push_sent,
        "type": "broadcast"
    })
    
    return {
        "success": True,
        "notification_id": notification_id,
        "message": "Broadcast sent! Current visitors will see this notification for 5 minutes.",
        "push_subscribers_notified": push_sent
    }

@api_router.get("/notifications/pending/{visitor_id}")
async def get_pending_notifications(visitor_id: str):
    """Get unread notifications for a visitor"""
    notifications = await db.pending_notifications.find(
        {"visitor_id": visitor_id, "read": False},
        {"_id": 0}
    ).sort("created_at", -1).to_list(10)
    
    return {"notifications": notifications}


@api_router.get("/notifications/broadcast")
async def get_active_broadcasts():
    """Get active broadcast notifications for in-site display"""
    now = datetime.now(timezone.utc).isoformat()
    
    broadcasts = await db.broadcast_notifications.find(
        {
            "active": True,
            "expires_at": {"$gte": now}
        },
        {"_id": 0}
    ).sort("created_at", -1).limit(5).to_list(5)
    
    return {"broadcasts": broadcasts}


@api_router.post("/notifications/dismiss-broadcast")
async def dismiss_broadcast(data: dict):
    """Track which broadcast a visitor has dismissed"""
    visitor_id = data.get("visitor_id")
    notification_id = data.get("notification_id")
    
    if visitor_id and notification_id:
        await db.dismissed_broadcasts.update_one(
            {"visitor_id": visitor_id, "notification_id": notification_id},
            {"$set": {"dismissed_at": datetime.now(timezone.utc).isoformat()}},
            upsert=True
        )
    
    return {"success": True}

@api_router.post("/notifications/mark-read/{visitor_id}")
async def mark_notifications_read(visitor_id: str):
    """Mark all notifications as read for a visitor"""
    await db.pending_notifications.update_many(
        {"visitor_id": visitor_id},
        {"$set": {"read": True}}
    )
    return {"success": True}

@api_router.get("/admin/notifications/subscribers")
async def get_notification_subscribers(
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    """Get list of push notification subscribers"""
    if x_admin_token != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    subscribers = await db.push_subscriptions.find(
        {"active": True},
        {"_id": 0, "visitor_id": 1, "subscribed_at": 1}
    ).to_list(500)
    
    return {
        "total": len(subscribers),
        "subscribers": subscribers
    }


@api_router.post("/track")
async def track_page_visit(page: str, session_id: str = None):
    await analytics_tracker.track_visit(page, session_id)
    return {"status": "tracked"}


@api_router.get("/pincode/{pincode}/state")
async def get_state_by_pincode(pincode: str):
    state = get_state_from_pincode(pincode)
    return {"pincode": pincode, "state": state}


@api_router.get("/pincode/{pincode}")
async def lookup_pincode(pincode: str):
    """Resolve pincode → state, district, city/locality (uses free India Post API + local fallback)"""
    import httpx
    pincode = (pincode or "").strip()
    if not pincode.isdigit() or len(pincode) != 6:
        raise HTTPException(status_code=400, detail="Invalid pincode")

    state = get_state_from_pincode(pincode) or ""
    city = ""
    district = ""
    localities: list = []

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"https://api.postalpincode.in/pincode/{pincode}")
            if resp.status_code == 200:
                payload = resp.json()
                if payload and isinstance(payload, list) and payload[0].get("Status") == "Success":
                    offices = payload[0].get("PostOffice", []) or []
                    if offices:
                        first = offices[0]
                        state = first.get("State", state) or state
                        district = first.get("District", "") or ""
                        city = first.get("Block", "") or first.get("District", "") or ""
                        localities = [o.get("Name") for o in offices if o.get("Name")][:8]
    except Exception as e:
        logging.warning(f"Pincode lookup external API failed for {pincode}: {e}")

    return {
        "pincode": pincode,
        "state": state,
        "district": district,
        "city": city,
        "localities": localities
    }


# ==================== BLOG API ROUTES ====================

class BlogCreate(BaseModel):
    title: str
    content: str
    meta_description: Optional[str] = None
    keywords: List[str] = []
    status: str = "published"


class BlogResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    
    id: str
    title: str
    slug: str
    meta_description: Optional[str] = None
    content: str
    keywords: List[str] = []
    status: str = "published"
    view_count: int = 0
    generated_by: str = "Manual"
    created_at: str
    updated_at: str


def generate_slug(title: str) -> str:
    """Generate URL-friendly slug from title"""
    slug = title.lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = re.sub(r'^-|-$', '', slug)
    return slug


@api_router.get("/blogs")
async def get_blogs():
    """Get all published blog posts"""
    blogs = await db.blogs.find({"status": "published"}, {"_id": 0}).sort("created_at", -1).to_list(100)
    return blogs


@api_router.get("/blogs/{slug}")
async def get_blog_by_slug(slug: str):
    """Get a single blog post by slug"""
    blog = await db.blogs.find_one({"slug": slug}, {"_id": 0})
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    
    # Increment view count
    await db.blogs.update_one({"slug": slug}, {"$inc": {"view_count": 1}})
    return blog


@api_router.post("/blogs")
async def create_blog(blog_data: BlogCreate):
    """Create a new blog post"""
    slug = generate_slug(blog_data.title)
    
    # Check if slug already exists
    existing = await db.blogs.find_one({"slug": slug})
    if existing:
        slug = f"{slug}-{secrets.randbelow(9000) + 1000}"  # 1000-9999 range
    
    now = datetime.now(timezone.utc).isoformat()
    blog_doc = {
        "id": str(uuid.uuid4()),
        "title": blog_data.title,
        "slug": slug,
        "meta_description": blog_data.meta_description,
        "content": blog_data.content,
        "keywords": blog_data.keywords,
        "status": blog_data.status,
        "view_count": 0,
        "generated_by": "Manual",
        "created_at": now,
        "updated_at": now
    }
    
    await db.blogs.insert_one(blog_doc)
    del blog_doc["_id"]
    return blog_doc


# ==================== SEARCH API ROUTE ====================

@api_router.get("/search")
async def search_content(q: str = Query(..., min_length=1), limit: int = Query(40, le=80)):
    """Unified site search — products + blogs in one shot.

    Used by the header search overlay AND the `/search?q=…` results page.
    Previously this endpoint only returned blogs, which made the header
    search bar look broken because typing a product name returned nothing.
    """
    import re as _re
    safe = _re.escape(q.strip())
    # ---- Products ----
    p_query: dict = {"is_active": True}
    # Use $text on long queries for speed; $regex prefix for short ones.
    if len(q) >= 3 and _re.search(r"[A-Za-z0-9]", q):
        p_query["$text"] = {"$search": q}
    else:
        p_query["$or"] = [
            {"name":  {"$regex": safe, "$options": "i"}},
            {"brand": {"$regex": safe, "$options": "i"}},
            {"slug":  {"$regex": safe, "$options": "i"}},
            {"tags":  {"$regex": safe, "$options": "i"}},
        ]
    proj = {
        "_id": 0, "slug": 1, "name": 1, "brand": 1, "niche": 1,
        "images": {"$slice": 2}, "prepaid_price": 1, "mrp": 1,
        "discount_percent": 1, "average_rating": 1,
    }
    products = await db.products.find(p_query, proj).limit(limit).to_list(length=None)

    # ---- Blogs ----
    b_query = {
        "$or": [
            {"title":   {"$regex": safe, "$options": "i"}},
            {"content": {"$regex": safe, "$options": "i"}},
            {"keywords": {"$in": [q.lower()]}},
        ],
        "status": "published",
    }
    blogs = await db.blogs.find(b_query, {"_id": 0}).limit(20).to_list(length=None)

    return {
        "products": products,
        "blogs": blogs,
        "total": len(products) + len(blogs),
        "q": q,
    }


@api_router.get("/search/suggest")
async def search_suggest(q: str = Query(..., min_length=1), limit: int = Query(8, le=20)):
    """Lightweight autocomplete for the header search bar — returns the top
    `limit` products that match by name / brand prefix. Snappy (<30 ms) by
    capping results and projecting only what the dropdown needs."""
    import re as _re
    safe = _re.escape(q.strip())
    query = {
        "is_active": True,
        "$or": [
            {"name":  {"$regex": "^" + safe, "$options": "i"}},
            {"name":  {"$regex": safe,       "$options": "i"}},
            {"brand": {"$regex": "^" + safe, "$options": "i"}},
        ],
    }
    proj = {
        "_id": 0, "slug": 1, "name": 1, "brand": 1, "niche": 1,
        "images": {"$slice": 1}, "prepaid_price": 1,
    }
    rows = await db.products.find(query, proj).limit(limit).to_list(length=None)
    return {"items": rows, "q": q}


# ==================== LOCATION API ROUTES ====================

@api_router.get("/location/{state}")
async def get_location_state(state: str):
    """Get location page content for a state"""
    location = await db.locations.find_one({"state": {"$regex": f"^{state}$", "$options": "i"}}, {"_id": 0})
    
    if not location:
        # Return default content for the state
        return {
            "state": state.title(),
            "city": None,
            "content": {
                "title": f"Anti-Aging Skincare in {state.title()}",
                "description": f"Discover premium anti-aging solutions for {state.title()}. Celesta Glow is trusted by thousands.",
                "climate": "Varies by region",
                "skin_issues": ["wrinkles", "fine lines", "dryness"],
                "recommendations": "Use Celesta Glow daily for best results"
            }
        }
    
    return location


@api_router.get("/location/{state}/{city}")
async def get_location_city(state: str, city: str):
    """Get location page content for a specific city"""
    location = await db.locations.find_one({
        "state": {"$regex": f"^{state}$", "$options": "i"},
        "city": {"$regex": f"^{city}$", "$options": "i"}
    }, {"_id": 0})
    
    if not location:
        # Return default content for the city
        return {
            "state": state.title(),
            "city": city.title(),
            "content": {
                "title": f"Anti-Aging Skincare in {city.title()}, {state.title()}",
                "description": f"Get Celesta Glow anti-aging products delivered to {city.title()}. Free shipping available.",
                "climate": "Varies by season",
                "skin_issues": ["wrinkles", "fine lines", "pollution damage"],
                "recommendations": "Use Celesta Glow twice daily for optimal results"
            }
        }
    
    return location


# ==================== ENHANCED ANALYTICS ENDPOINTS ====================

class VisitorLeadCreate(BaseModel):
    phone: str
    session_id: str
    page: str


@api_router.post("/track-visit")
async def track_enhanced_page_visit(
    page: str = Query(...),
    session_id: str = Query(...),
    user_agent: Optional[str] = Query(None),
    referrer: Optional[str] = Query(None),
    ip_address: Optional[str] = Query(None)
):
    """Track a page visit with enhanced analytics including IP"""
    return await enhanced_analytics.track_page_visit(page, session_id, user_agent, referrer, ip_address)


@api_router.get("/live-visitors")
async def get_live_visitors(page: Optional[str] = None):
    """Get live visitors count"""
    if page:
        count = enhanced_analytics.get_live_visitors_count(page)
        return {"page": page, "live_visitors": count}
    
    by_page = enhanced_analytics.get_live_visitors_by_page()
    total = enhanced_analytics.get_live_visitors_count()
    return {"total_live_visitors": total, "by_page": by_page}


@api_router.post("/claim-discount")
async def claim_visitor_discount(lead: VisitorLeadCreate):
    """Claim ₹50 discount by providing phone number"""
    # Validate phone number
    phone = lead.phone.strip()
    if not re.match(r'^[6-9]\d{9}$', phone):
        raise HTTPException(status_code=400, detail="Invalid phone number")
    
    result = await visitor_lead_tracker.save_visitor_lead(
        phone=phone,
        session_id=lead.session_id,
        page=lead.page,
        discount_code="WELCOME50"
    )
    
    # Also update visitor profile with phone number for tracking
    if lead.session_id:
        # Get visitor_id from session
        visitor_profile = await db.visitor_profiles.find_one({"last_session": lead.session_id})
        if visitor_profile:
            await db.visitor_profiles.update_one(
                {"visitor_id": visitor_profile.get("visitor_id")},
                {"$set": {"phone": phone, "discount_claimed": True}}
            )
        else:
            # Try to find by recent activity
            recent_visit = await db.user_page_visits.find_one(
                {"session_id": lead.session_id},
                sort=[("timestamp", -1)]
            )
            if recent_visit and recent_visit.get("visitor_id"):
                await db.visitor_profiles.update_one(
                    {"visitor_id": recent_visit.get("visitor_id")},
                    {"$set": {"phone": phone, "discount_claimed": True}}
                )
    
    return result


# ==================== ADMIN ANALYTICS ENDPOINTS ====================

# Load admin password from environment variable (with fallback for development)
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'celestaglow2024')

def verify_admin_token(x_admin_token: str = Header(None), admin_session: str = Cookie(None)):
    """Verify admin token - accepts header token, cookie, or plain password.

    Security: once a custom admin password is stored in ``admin_settings``,
    the env-seed password (``ADMIN_PASSWORD``) is no longer accepted.
    Bootstrap mode (no custom password yet) keeps the env-seed working so
    a fresh install can still log in.
    """
    from services.admin_auth import get_cached_active_admin_hash

    # Get the token from header or cookie
    token_to_check = x_admin_token or admin_session

    # Ensure we have a string, not a Cookie object
    if token_to_check is not None and not isinstance(token_to_check, str):
        token_to_check = str(token_to_check) if token_to_check else None

    if not token_to_check:
        raise HTTPException(status_code=401, detail="Admin token required")

    # 1. Active session token (always allowed regardless of password change).
    if token_to_check in admin_sessions:
        session = admin_sessions[token_to_check]
        expires_at = session["expires_at"]
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        elif isinstance(expires_at, datetime):
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) < expires_at:
            return True
        else:
            del admin_sessions[token_to_check]
            raise HTTPException(status_code=401, detail="Session expired, please login again")

    # 2. Plain-text password — must match the *active* admin hash.
    import hashlib as _hashlib
    if _hashlib.sha256(token_to_check.encode()).hexdigest() == get_cached_active_admin_hash():
        return True

    raise HTTPException(status_code=403, detail="Invalid admin token")


async def verify_admin_token_async(x_admin_token: str = Header(None), admin_session: str = Cookie(None)):
    """Async version of verify_admin_token. Reads directly from the DB if the
    in-memory cache is cold."""
    from services.admin_auth import get_active_admin_hash

    token_to_check = x_admin_token or admin_session
    if token_to_check is not None and not isinstance(token_to_check, str):
        token_to_check = str(token_to_check) if token_to_check else None
    if not token_to_check:
        raise HTTPException(status_code=401, detail="Admin token required")

    if token_to_check in admin_sessions:
        session = admin_sessions[token_to_check]
        expires_at = session["expires_at"]
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        elif isinstance(expires_at, datetime):
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) < expires_at:
            return True
        else:
            del admin_sessions[token_to_check]
            raise HTTPException(status_code=401, detail="Session expired, please login again")

    import hashlib as _hashlib
    active_hash = await get_active_admin_hash(db)
    if _hashlib.sha256(token_to_check.encode()).hexdigest() == active_hash:
        return True
    raise HTTPException(status_code=403, detail="Invalid admin token")


class AdminLoginRequest(BaseModel):
    password: str


# Generate a secure admin session token
def generate_admin_session_token() -> str:
    """Generate a cryptographically secure session token"""
    import hashlib
    import time
    data = f"{ADMIN_PASSWORD}{time.time()}{secrets.token_hex(16)}"
    return hashlib.sha256(data.encode()).hexdigest()

# MongoDB-backed session stores with in-memory cache (drop-in dict replacement).
# Survives pod restarts, works across multiple uvicorn workers / k8s pods, and
# auto-expires stale rows via a TTL index on `expires_at`.
from services.session_store import SessionStore  # noqa: E402
admin_sessions = SessionStore(db, "admin_sessions")
employee_sessions = SessionStore(db, "employee_sessions")

# Share admin_sessions with admin routes for token verification
admin_routes.set_admin_sessions(admin_sessions)

# Share admin_sessions with landing pages routes for token verification
landing_page_routes.set_admin_sessions(admin_sessions)

# Share employee_sessions with landing pages routes for employee access
landing_page_routes.set_employee_sessions(employee_sessions)

# Share sessions with product routes
product_routes.set_admin_sessions(admin_sessions)
product_routes.set_employee_sessions(employee_sessions)

# Share admin_sessions with concerns/categories routes
concerns_routes.set_admin_sessions(admin_sessions)

# Share admin_sessions with reviews routes
reviews_routes.set_admin_sessions(admin_sessions)

# Share admin_sessions with consultation routes for token verification
consultation_routes.set_admin_sessions(admin_sessions)

# Wire bulk-import service + auth into its routes module
bulk_import_service = BulkImportService(db)
bulk_import_routes.setup(bulk_import_service, admin_sessions, verify_admin_token)

# Wire up the fast master-list import + product groups + margin updater + order export
master_import_routes.setup(db, admin_sessions, verify_admin_token)

# Wire up gift cards + AI URL analyze + per-product fill-with-AI
gift_card_service = GiftCardService(db)
gift_cards_routes.setup(db, gift_card_service, verify_admin_token)

@api_router.post("/admin/login")
async def admin_login(request: AdminLoginRequest, response: Response):
    """Admin login endpoint - sets httpOnly cookie for security.

    Accepts ONLY the *active* admin password — i.e. the one stored in
    ``admin_settings`` if the admin has saved a custom one, otherwise the
    env-seed value. Once a custom password exists the env-seed is inert.
    """
    from services.admin_auth import is_admin_password
    valid = await is_admin_password(request.password, db)
    if valid:
        # Generate a session token
        session_token = generate_admin_session_token()
        
        # Store session (with expiry in 24 hours)
        admin_sessions[session_token] = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
        }
        
        # Set httpOnly cookie for security (prevents XSS attacks from accessing token)
        response.set_cookie(
            key="admin_session",
            value=session_token,
            httponly=True,
            secure=True,  # Only send over HTTPS
            samesite="lax",
            max_age=86400,  # 24 hours
            path="/api/admin"
        )
        
        # Also return token for backward compatibility with existing frontend
        return {"success": True, "token": session_token}
    raise HTTPException(status_code=401, detail="Invalid password")


@api_router.post("/admin/logout")
async def admin_logout(response: Response, admin_session: str = Cookie(None)):
    """Admin logout - clears session"""
    if admin_session and admin_session in admin_sessions:
        del admin_sessions[admin_session]
    
    response.delete_cookie(key="admin_session", path="/api/admin")
    return {"success": True, "message": "Logged out successfully"}


@api_router.get("/admin/analytics/live")
async def get_live_analytics(
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    x_employee_token: str = Header(None, alias="X-Employee-Token")
):
    """Get real-time analytics for admin dashboard"""
    if x_admin_token:
        verify_admin_token(x_admin_token)
    elif x_employee_token:
        session = verify_employee_token(x_employee_token)
        if not session["permissions"].get("analytics"):
            raise HTTPException(status_code=403, detail="No permission to view analytics")
    else:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    live_by_page = enhanced_analytics.get_live_visitors_by_page()
    total_live = enhanced_analytics.get_live_visitors_count()
    total_stats = await enhanced_analytics.get_total_stats()
    page_totals = await enhanced_analytics.get_page_visit_totals()
    top_locations = await enhanced_analytics.get_top_locations()
    
    return {
        "live_visitors": {
            "total": total_live,
            "by_page": live_by_page
        },
        "total_visits": total_stats.get("total_visits", 0),
        "page_totals": page_totals,
        "top_locations": top_locations,
        "last_updated": datetime.now(timezone.utc).isoformat()
    }


@api_router.get("/admin/analytics/pages")
async def get_page_analytics(
    x_admin_token: str = Header(None),
    days: int = Query(7, ge=1, le=90)
):
    """Get detailed page-wise analytics"""
    verify_admin_token(x_admin_token)
    
    analytics = await enhanced_analytics.get_page_analytics(days=days)
    hourly = await enhanced_analytics.get_hourly_distribution(days=days)
    
    return {
        "page_analytics": analytics,
        "hourly_distribution": hourly
    }


@api_router.get("/admin/analytics/daywise")
async def get_daywise_analytics(
    x_admin_token: str = Header(None),
    days: int = Query(7, ge=1, le=365),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None)
):
    """Get day-wise visitor analytics with date filtering
    
    Returns visitors for Homepage, Product Page, and Checkout for each day.
    Supports preset days filter or custom date range.
    """
    verify_admin_token(x_admin_token)
    
    daywise_data = await enhanced_analytics.get_daywise_analytics(
        days=days, 
        start_date=start_date, 
        end_date=end_date
    )
    
    return daywise_data


@api_router.get("/admin/analytics/leads")
async def get_visitor_leads(x_admin_token: str = Header(None)):
    """Get all visitor leads (phone numbers)"""
    verify_admin_token(x_admin_token)
    
    leads = await visitor_lead_tracker.get_all_leads()
    stats = await visitor_lead_tracker.get_leads_stats()
    
    return {
        "leads": leads,
        "stats": stats
    }


# ==================== AI CONTENT GENERATION ENDPOINTS ====================

class BlogGenerateRequest(BaseModel):
    topic: str
    keywords: Optional[List[str]] = None
    target_audience: Optional[str] = "Indian adults 28+"


class LocationGenerateRequest(BaseModel):
    state: str
    city: Optional[str] = None


@api_router.post("/admin/ai/generate-blog")
async def generate_blog_with_ai(request: BlogGenerateRequest, x_admin_token: str = Header(None)):
    """Generate a blog article using AI (costs credits)"""
    verify_admin_token(x_admin_token)
    
    result = await ai_content_generator.generate_blog_article(
        topic=request.topic,
        keywords=request.keywords,
        target_audience=request.target_audience
    )
    
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "AI generation failed"))
    
    return result


@api_router.post("/admin/ai/generate-location")
async def generate_location_with_ai(request: LocationGenerateRequest, x_admin_token: str = Header(None)):
    """Generate location page content using AI (costs credits)"""
    verify_admin_token(x_admin_token)
    
    result = await ai_content_generator.generate_location_content(
        state=request.state,
        city=request.city
    )
    
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "AI generation failed"))
    
    return result


@api_router.get("/admin/ai/suggest-topics")
async def suggest_blog_topics(
    x_admin_token: str = Header(None), 
    count: int = Query(5, ge=1, le=10),
    format: str = Query("full", description="'full' for objects with description, 'simple' for title strings only")
):
    """Get AI-suggested blog topics
    
    Args:
        format: 'full' returns {topic, description, keywords}, 'simple' returns just topic titles
    """
    verify_admin_token(x_admin_token)
    
    result = await ai_content_generator.suggest_blog_topics(count=count, format=format)
    
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "AI generation failed"))
    
    return result


# ==================== AUTO BLOG GENERATION ENDPOINTS ====================

class AutoGenerateBlogsRequest(BaseModel):
    count: int = 12


class BatchLocationBlogsRequest(BaseModel):
    states: List[str]


class BatchTopicBlogsRequest(BaseModel):
    topics: List[str]


@api_router.post("/admin/ai/auto-generate-blogs")
async def auto_generate_blogs(request: AutoGenerateBlogsRequest, x_admin_token: str = Header(None)):
    """Auto-generate multiple SEO blogs (12 by default)"""
    verify_admin_token(x_admin_token)
    
    result = await auto_blog_generator.generate_and_save_blogs(count=request.count)
    return result


@api_router.post("/admin/ai/batch-location-blogs")
async def batch_location_blogs(request: BatchLocationBlogsRequest, x_admin_token: str = Header(None)):
    """Generate blogs targeting specific Indian states"""
    verify_admin_token(x_admin_token)
    
    # When user manually selects states, force=True to allow regeneration
    result = await auto_blog_generator.generate_location_blogs(states=request.states, force=True)
    return result


@api_router.post("/admin/ai/batch-topic-blogs")
async def batch_topic_blogs(request: BatchTopicBlogsRequest, x_admin_token: str = Header(None)):
    """Generate blogs for specific user-defined topics"""
    verify_admin_token(x_admin_token)
    
    # When user manually enters topics, force=True to allow regeneration
    result = await auto_blog_generator.generate_topic_blogs(topics=request.topics, force=True)
    return result


@api_router.get("/admin/ai/generation-history")
async def get_blog_generation_history(x_admin_token: str = Header(None)):
    """Get blog generation history"""
    verify_admin_token(x_admin_token)
    
    history = await auto_blog_generator.get_generation_history()
    return {"history": history}


@api_router.post("/admin/blogs/backfill-images")
async def backfill_blog_images(x_admin_token: str = Header(None)):
    """Backfill images for blogs that don't have them"""
    verify_admin_token(x_admin_token)
    
    # Find blogs without images
    blogs_without_images = await db.blogs.find(
        {"$or": [{"image_url": {"$exists": False}}, {"image_url": None}, {"image_url": ""}]},
        {"_id": 0}
    ).to_list(100)
    
    updated = 0
    used_images = []
    
    for blog in blogs_without_images:
        category = blog.get("category", "tips")
        keywords = blog.get("keywords", [])
        title = blog.get("title", "")
        
        # Get appropriate image
        image_url = get_image_for_category(category, used_images)
        if not image_url:
            image_url = get_image_for_keywords(keywords, title)
        
        used_images.append(image_url)
        
        # Update blog with image
        await db.blogs.update_one(
            {"id": blog.get("id"), "slug": blog.get("slug")},
            {"$set": {"image_url": image_url}}
        )
        updated += 1
    
    return {
        "success": True,
        "updated_count": updated,
        "message": f"Added images to {updated} blogs"
    }


# ==================== DISCOUNT VALIDATION ENDPOINT ====================

@api_router.get("/validate-discount")
async def validate_discount_code(phone: str = Query(...)):
    """Validate if a phone number has a valid discount"""
    # Check if phone has claimed discount
    lead = await db.visitor_leads.find_one({"phone": phone}, {"_id": 0})
    
    if lead and not lead.get("converted"):
        return {
            "valid": True,
            "discount_code": lead.get("discount_code", "WELCOME50"),
            "discount_amount": lead.get("discount_amount", 50),
            "message": "Discount applied!"
        }
    elif lead and lead.get("converted"):
        return {
            "valid": False,
            "message": "Discount already used"
        }
    else:
        return {
            "valid": False,
            "message": "No discount found for this number"
        }


# ==================== RECENT PURCHASES FOR SOCIAL PROOF ====================

@api_router.get("/recent-purchases")
async def get_recent_purchases():
    """Get recent purchases for social proof notifications"""
    # Get recent orders (last 24 hours, anonymized)
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    
    orders = await db.orders.find(
        {"created_at": {"$gte": cutoff}},
        {"_id": 0, "name": 1, "state": 1, "created_at": 1}
    ).sort("created_at", -1).limit(10).to_list(10)
    
    # Anonymize names (first name + initial)
    purchases = []
    for order in orders:
        name = order.get("name", "Someone")
        name_parts = name.split()
        if len(name_parts) > 1:
            display_name = f"{name_parts[0]} {name_parts[1][0]}."
        else:
            display_name = name_parts[0] if name_parts else "Someone"
        
        purchases.append({
            "name": display_name,
            "location": order.get("state", "India"),
            "time_ago": order.get("created_at")
        })
    
    # If no recent orders, return sample data
    if not purchases:
        sample_names = [
            {"name": "Priya S.", "location": "Mumbai"},
            {"name": "Anita R.", "location": "Delhi"},
            {"name": "Kavya P.", "location": "Bangalore"},
            {"name": "Neha K.", "location": "Chennai"},
            {"name": "Divya M.", "location": "Hyderabad"}
        ]
        purchases = sample_names[:3]
    
    return {"purchases": purchases}


# ==================== USER BEHAVIOR TRACKING ====================

class TrackingData(BaseModel):
    visitor_id: str
    session_id: str
    page: Optional[str] = None
    action: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None
    referrer: Optional[str] = None
    user_agent: Optional[str] = None
    screen_width: Optional[int] = None
    screen_height: Optional[int] = None
    time_spent: Optional[int] = None


# ==================== CENTRALIZED TRACKING ENDPOINTS (TrackingProvider.js) ====================

class TrackActionRequest(BaseModel):
    visitor_id: str
    session_id: str
    action: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None


class TrackBatchRequest(BaseModel):
    visitor_id: str
    session_id: str
    events: List[Dict[str, Any]]


@api_router.post("/track-action")
async def track_action_centralized(data: TrackActionRequest):
    """Centralized tracking endpoint for individual actions (from TrackingProvider.js)"""
    try:
        action_doc = {
            "visitor_id": data.visitor_id,
            "session_id": data.session_id,
            "action": data.action,
            "data": data.data or {},
            "timestamp": data.timestamp or datetime.now(timezone.utc).isoformat()
        }
        await db.tracking_events.insert_one(action_doc)
        
        # Also update visitor profile with action
        await db.visitor_profiles.update_one(
            {"visitor_id": data.visitor_id},
            {
                "$set": {"last_session": data.session_id, "last_active": datetime.now(timezone.utc).isoformat()},
                "$push": {"recent_actions": {"$each": [{"action": data.action, "timestamp": action_doc["timestamp"]}], "$slice": -50}}
            },
            upsert=True
        )
        # Delegate to behavior tracker so funnel flags (order_completed, reached_checkout, address_entered) get set
        try:
            await user_behavior_tracker.track_action({
                "visitor_id": data.visitor_id,
                "session_id": data.session_id,
                "action": data.action,
                "details": data.data or {},
                "page": (data.data or {}).get("page"),
                "timestamp": action_doc["timestamp"]
            })
        except Exception as inner_e:
            logging.warning(f"Behavior tracker delegation failed: {inner_e}")
        return {"success": True, "tracked": True}
    except Exception as e:
        logging.error(f"Track action error: {e}")
        return {"success": False, "error": str(e)}


@api_router.post("/track-batch")
async def track_batch_centralized(data: TrackBatchRequest):
    """Centralized batch tracking endpoint (from TrackingProvider.js)"""
    try:
        if not data.events:
            return {"success": True, "tracked": 0}
        
        # Process batch events
        docs = []
        for event in data.events:
            doc = {
                "visitor_id": data.visitor_id,
                "session_id": data.session_id,
                "action": event.get("action"),
                "data": event.get("data", {}),
                "timestamp": event.get("timestamp") or datetime.now(timezone.utc).isoformat()
            }
            docs.append(doc)
        
        if docs:
            await db.tracking_events.insert_many(docs)
        
        # Update visitor profile
        await db.visitor_profiles.update_one(
            {"visitor_id": data.visitor_id},
            {
                "$set": {"last_session": data.session_id, "last_active": datetime.now(timezone.utc).isoformat()},
                "$inc": {"total_events": len(docs)}
            },
            upsert=True
        )
        
        # Delegate funnel-relevant events to behavior tracker (order_complete, view_checkout, etc.)
        funnel_actions = {"order_complete", "view_checkout", "address_complete", "payment_method_selected", "initiate_checkout"}
        for event in data.events:
            if event.get("action") in funnel_actions or (event.get("data") or {}).get("has_address") or (event.get("data") or {}).get("has_phone"):
                try:
                    await user_behavior_tracker.track_action({
                        "visitor_id": data.visitor_id,
                        "session_id": data.session_id,
                        "action": event.get("action"),
                        "details": event.get("data", {}),
                        "page": (event.get("data") or {}).get("page"),
                        "timestamp": event.get("timestamp") or datetime.now(timezone.utc).isoformat()
                    })
                except Exception as inner_e:
                    logging.warning(f"Behavior tracker delegation (batch) failed: {inner_e}")
        
        return {"success": True, "tracked": len(docs)}
    except Exception as e:
        logging.error(f"Track batch error: {e}")
        return {"success": False, "error": str(e)}


@api_router.post("/tracking/page-visit")
async def track_user_page_visit(data: TrackingData):
    """Track user page visit with behavior data"""
    return await user_behavior_tracker.track_page_visit(data.model_dump())


@api_router.post("/tracking/time-spent")
async def track_user_time_spent(data: TrackingData):
    """Track time spent on page"""
    return await user_behavior_tracker.track_time_spent(data.model_dump())


@api_router.post("/tracking/action")
async def track_user_action(data: TrackingData):
    """Track user action (click, scroll, form fill)"""
    return await user_behavior_tracker.track_action(data.model_dump())


@api_router.post("/tracking/update-location")
async def update_visitor_location(data: dict):
    """Update visitor profile with browser geolocation and reverse geocode to actual place"""
    import httpx
    
    visitor_id = data.get("visitor_id")
    location = data.get("location")
    
    if visitor_id and location:
        lat = location.get("latitude")
        lng = location.get("longitude")
        
        # Reverse geocode to get actual place name
        place_info = {}
        if lat and lng:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    # Use OpenStreetMap Nominatim API (free, no key needed)
                    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lng}&zoom=10&addressdetails=1"
                    response = await client.get(url, headers={"User-Agent": "CelestaGlow/1.0"})
                    if response.status_code == 200:
                        geo_data = response.json()
                        address = geo_data.get("address", {})
                        place_info = {
                            "city": address.get("city") or address.get("town") or address.get("village") or address.get("suburb", ""),
                            "district": address.get("state_district") or address.get("county", ""),
                            "state": address.get("state", ""),
                            "country": address.get("country", "India"),
                            "pincode": address.get("postcode", ""),
                            "display_name": geo_data.get("display_name", "")[:100]
                        }
            except Exception as e:
                logging.warning(f"Reverse geocode failed: {e}")
        
        await db.visitor_profiles.update_one(
            {"visitor_id": visitor_id},
            {
                "$set": {
                    "browser_location": location,
                    "location_place": place_info,
                    "location_updated_at": datetime.now(timezone.utc).isoformat()
                }
            },
            upsert=True
        )
    return {"updated": True, "place": place_info if 'place_info' in dir() else {}}


@api_router.post("/tracking/blog-view")
async def track_blog_view(data: dict):
    """Track blog view and increment view counter"""
    blog_slug = data.get("blog_slug")
    visitor_id = data.get("visitor_id")
    
    if blog_slug:
        # Increment blog view count
        await db.blogs.update_one(
            {"slug": blog_slug},
            {"$inc": {"views": 1, "view_count": 1}}
        )
        
        # Log the view
        await db.blog_views.insert_one({
            "blog_slug": blog_slug,
            "blog_title": data.get("blog_title", ""),
            "visitor_id": visitor_id,
            "session_id": data.get("session_id"),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        # Update visitor profile with blogs viewed
        if visitor_id:
            await db.visitor_profiles.update_one(
                {"visitor_id": visitor_id},
                {
                    "$addToSet": {"blogs_viewed": blog_slug},
                    "$inc": {"total_blog_views": 1}
                }
            )
    
    return {"tracked": True}


@api_router.post("/tracking/discount-claimed")
async def track_discount_claimed(data: dict, request: Request):
    """Track when a visitor claims a discount"""
    visitor_id = data.get("visitor_id")
    discount_type = data.get("discount_type", "regular")  # "regular" (₹50) or "exit" (₹100)
    discount_amount = data.get("amount", 50)
    phone = data.get("phone", "")
    email = data.get("email", "")
    
    if visitor_id:
        update_data = {
            "$set": {
                "discount_claimed": True,
                "discount_type": discount_type,
                "discount_amount": discount_amount,
                "discount_claimed_at": datetime.now(timezone.utc).isoformat()
            }
        }
        
        if phone:
            update_data["$set"]["phone"] = phone
        if email:
            update_data["$set"]["email"] = email
        
        await db.visitor_profiles.update_one(
            {"visitor_id": visitor_id},
            update_data,
            upsert=True
        )

    # Meta CAPI — Lead event (server-side, dedups with browser Pixel via event_id)
    try:
        from services import meta_capi
        if meta_capi.is_enabled() and (phone or email):
            _client_ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "") or "").split(",")[0].strip() or None
            _ua = data.get("client_user_agent") or request.headers.get("user-agent")
            _user_data = meta_capi.build_user_data(
                email=email or None,
                phone=phone or None,
                country="in",
                external_id=phone or email or visitor_id,
                client_ip=_client_ip,
                client_user_agent=_ua,
                fbp=data.get("fbp"),
                fbc=data.get("fbc"),
            )
            _event_id = data.get("event_id") or f"lead_{visitor_id}_{int(datetime.now(timezone.utc).timestamp())}"
            import asyncio
            asyncio.create_task(meta_capi.track_lead(
                event_id=_event_id,
                source=discount_type or "discount_popup",
                user_data=_user_data,
                event_source_url=request.headers.get("referer"),
                value=float(discount_amount or 0),
            ))
    except Exception as _capi_err:
        logging.warning(f"[meta_capi] Lead dispatch failed: {_capi_err}")

    return {"tracked": True}


@api_router.get("/admin/blog-stats")
async def get_blog_stats(x_admin_token: str = Header(None)):
    """Get blog statistics for admin dashboard"""
    verify_admin_token(x_admin_token)
    
    total_blogs = await db.blogs.count_documents({})
    
    # Today's blogs
    # IST-anchored "today" so admins in India see counts that match the wall
    # clock. UTC boundary was excluding all events between 00:00-05:30 IST.
    _ist = timezone(timedelta(hours=5, minutes=30))
    today = datetime.now(_ist).strftime("%Y-%m-%d")
    today_blogs = await db.blogs.count_documents({"created_at": {"$regex": f"^{today}"}})
    
    # Total views
    pipeline = [
        {"$group": {"_id": None, "total_views": {"$sum": {"$ifNull": ["$views", 0]}}}}
    ]
    views_result = await db.blogs.aggregate(pipeline).to_list(1)
    total_views = views_result[0]["total_views"] if views_result else 0
    
    # Today's views
    today_views = await db.blog_views.count_documents({"timestamp": {"$regex": f"^{today}"}})
    
    # Top blogs by views
    top_blogs = await db.blogs.find(
        {"views": {"$gt": 0}},
        {"_id": 0, "title": 1, "slug": 1, "views": 1, "category": 1}
    ).sort("views", -1).limit(5).to_list(5)
    
    # Recent blogs
    recent_blogs = await db.blogs.find(
        {},
        {"_id": 0, "title": 1, "slug": 1, "created_at": 1, "views": 1, "is_trending": 1}
    ).sort("created_at", -1).limit(10).to_list(10)
    
    # Trending blogs count
    trending_count = await db.blogs.count_documents({"is_trending": True})
    
    return {
        "total_blogs": total_blogs,
        "today_blogs": today_blogs,
        "total_views": total_views,
        "today_views": today_views,
        "top_blogs": top_blogs,
        "recent_blogs": recent_blogs,
        "trending_count": trending_count
    }


@api_router.get("/admin/user-tracking/visitors")
async def get_tracked_visitors(
    x_admin_token: str = Header(None),
    date: Optional[str] = Query(None),
    days: int = Query(7, ge=1, le=365)
):
    """Get all tracked visitors"""
    verify_admin_token(x_admin_token)
    
    if date:
        visitors = await user_behavior_tracker.get_visitors_by_date(date)
    else:
        visitors = await user_behavior_tracker.get_all_visitors(days=days)
    
    return {"visitors": visitors}


@api_router.get("/admin/user-tracking/visitor/{visitor_id}")
async def get_visitor_journey(
    visitor_id: str,
    x_admin_token: str = Header(None)
):
    """Get complete journey of a specific visitor"""
    verify_admin_token(x_admin_token)
    
    journey = await user_behavior_tracker.get_visitor_journey(visitor_id)
    return journey


@api_router.get("/admin/user-tracking/stats")
async def get_user_tracking_stats(
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    x_employee_token: str = Header(None, alias="X-Employee-Token"),
    days: int = Query(7, ge=1, le=365),
    date: Optional[str] = Query(None, description="Single date in YYYY-MM-DD format")
):
    """Get user tracking statistics - supports both days range and single date"""
    if x_admin_token:
        verify_admin_token(x_admin_token)
    elif x_employee_token:
        session = verify_employee_token(x_employee_token)
        if not session["permissions"].get("analytics"):
            raise HTTPException(status_code=403, detail="No permission to view analytics")
    else:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    stats = await user_behavior_tracker.get_visitor_stats(days=days, date=date)
    return stats


@api_router.post("/admin/cron/trigger-blog-generation")
async def trigger_blog_generation(
    x_admin_token: str = Header(None),
    blog_type: str = Query("auto", description="Type: auto, location, or topic")
):
    """Manually trigger blog generation (for testing cron)"""
    verify_admin_token(x_admin_token)
    
    if blog_type == "location":
        result = await auto_blog_generator.generate_location_blogs(states=None, count=12)
    elif blog_type == "topic":
        # Generate with sample topics
        topics = [
            "Best anti-aging ingredients for Indian skin",
            "How to reduce wrinkles naturally",
            "Night skincare routine for 30+",
            "Benefits of retinol serum"
        ]
        result = await auto_blog_generator.generate_topic_blogs(topics=topics, count=12)
    else:
        result = await auto_blog_generator.generate_and_save_blogs(count=12)
    
    # Log the manual trigger
    await db.cron_logs.insert_one({
        "job": "manual_blog_generation",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "blog_type": blog_type,
        "generated": result.get("generated", 0),
        "failed": result.get("failed", 0),
        "triggered_by": "admin"
    })
    
    return result


@api_router.get("/admin/cron/logs")
async def get_cron_logs(
    x_admin_token: str = Header(None),
    limit: int = Query(20, ge=1, le=100)
):
    """Get recent cron job logs"""
    verify_admin_token(x_admin_token)
    
    logs = await db.cron_logs.find(
        {}, 
        {"_id": 0}
    ).sort("timestamp", -1).limit(limit).to_list(limit)
    
    return {"logs": logs}


@api_router.get("/admin/cron/status")
async def get_cron_status(x_admin_token: str = Header(None)):
    """Get cron job status and next run time"""
    verify_admin_token(x_admin_token)
    
    # Get last generation log
    last_log = await db.cron_logs.find_one(
        {"job": {"$in": ["auto_blog_generation", "manual_blog_generation", "trending_blog_generation"]}},
        {"_id": 0},
        sort=[("timestamp", -1)]
    )
    
    # Calculate next run times based on staggered schedule:
    # 6 AM - Location blogs (12)
    # 12 PM - Topic blogs (6)
    # 6 PM - Trending blogs (6)
    # 12 AM - Mix blogs (6)
    # PLUS: Hourly trending blogs
    now = datetime.now(timezone.utc)
    
    scheduled_hours = [0, 6, 12, 18]  # 12AM, 6AM, 12PM, 6PM
    next_scheduled = None
    
    for hour in scheduled_hours:
        target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
        if now.hour < hour:
            next_scheduled = target
            break
    
    if not next_scheduled:
        # Next day 12 AM
        next_scheduled = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    
    time_until_scheduled = (next_scheduled - now).total_seconds()
    
    # Next hourly trending (runs every hour)
    next_hourly = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    time_until_hourly = (next_hourly - now).total_seconds()
    
    # Use the sooner of the two
    if time_until_hourly < time_until_scheduled:
        next_run = next_hourly
        time_until_next = time_until_hourly
        next_type = "Hourly Trending"
    else:
        next_run = next_scheduled
        time_until_next = time_until_scheduled
        job_map = {0: "Mix Blogs", 6: "Location Blogs", 12: "Topic Blogs", 18: "Trending Batch"}
        next_type = job_map.get(next_scheduled.hour, "Auto Blogs")
    
    # Get today's blog count — IST-anchored so admins see wall-clock counts
    _ist = timezone(timedelta(hours=5, minutes=30))
    today_str = datetime.now(_ist).strftime("%Y-%m-%d")
    today_blogs = await db.blogs.count_documents({"created_at": {"$regex": f"^{today_str}"}})
    total_blogs = await db.blogs.count_documents({})
    trending_blogs = await db.blogs.count_documents({"is_trending": True})
    
    return {
        "cron_active": True,
        "schedule": "Staggered (6AM/12PM/6PM/12AM) + Hourly Trending",
        "next_run": next_run.isoformat() if next_run else None,
        "next_run_type": next_type,
        "time_until_next_seconds": int(time_until_next),
        "time_until_next_formatted": f"{int(time_until_next // 3600)}h {int((time_until_next % 3600) // 60)}m",
        "last_run": last_log.get("timestamp") if last_log else None,
        "last_run_generated": last_log.get("generated", 0) if last_log else 0,
        "today_blogs_generated": today_blogs,
        "total_blogs": total_blogs,
        "trending_blogs": trending_blogs,
        "blogs_per_run": 12
    }


# ==================== TRENDING NEWS BLOG ENDPOINTS ====================

@api_router.get("/admin/ai/trending-news")
async def get_trending_news(x_admin_token: str = Header(None), feed_type: str = Query("celebrity_india")):
    """Fetch current trending news for preview"""
    verify_admin_token(x_admin_token)
    
    news = await trending_news_generator.fetch_trending_news(feed_type, limit=10)
    return {"news": news, "feed_type": feed_type}


@api_router.post("/admin/ai/generate-trending-blogs")
async def generate_trending_blogs(x_admin_token: str = Header(None), count: int = Query(3, ge=1, le=5)):
    """Generate blogs from trending news"""
    verify_admin_token(x_admin_token)
    
    result = await trending_news_generator.generate_trending_blogs(count=count)
    
    # Log the generation
    await db.cron_logs.insert_one({
        "job": "trending_blog_generation",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "generated": result.get("successful", 0),
        "failed": result.get("failed", 0),
        "triggered_by": "admin"
    })
    
    return result


@api_router.get("/admin/ai/trending-stats")
async def get_trending_blog_stats(x_admin_token: str = Header(None)):
    """Get trending blog statistics"""
    verify_admin_token(x_admin_token)
    
    stats = await trending_news_generator.get_trending_stats()
    return stats


# ==================== WHATSAPP API ENDPOINTS ====================

class WhatsAppSendRequest(BaseModel):
    phone: str
    message: str
    category: Optional[str] = "promotional"


class WhatsAppBulkRequest(BaseModel):
    phones: List[str]
    message: str
    category: Optional[str] = "promotional"


class WhatsAppOrderNotifyRequest(BaseModel):
    order_id: str


class WhatsAppConsultationNotifyRequest(BaseModel):
    consultation_id: str
    recommendations: Optional[str] = None


@api_router.post("/admin/whatsapp/send")
async def send_whatsapp_message(request: WhatsAppSendRequest, x_admin_token: str = Header(None)):
    """Send a custom WhatsApp message to a customer"""
    verify_admin_token(x_admin_token)
    
    result = await whatsapp_service.send_custom_message(
        phone_number=request.phone,
        message=request.message,
        message_category=request.category
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to send message"))
    
    return result


@api_router.post("/admin/whatsapp/send-bulk")
async def send_bulk_whatsapp(request: WhatsAppBulkRequest, x_admin_token: str = Header(None)):
    """Send WhatsApp message to multiple recipients"""
    verify_admin_token(x_admin_token)
    
    result = await whatsapp_service.send_bulk_messages(
        phone_numbers=request.phones,
        message=request.message,
        message_category=request.category
    )
    
    return result


@api_router.post("/admin/whatsapp/notify-order")
async def send_order_whatsapp_notification(request: WhatsAppOrderNotifyRequest, x_admin_token: str = Header(None)):
    """Send order confirmation via WhatsApp"""
    verify_admin_token(x_admin_token)
    
    # Get order details
    order = await db.orders.find_one({"order_id": request.order_id}, {"_id": 0})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    result = await whatsapp_service.send_order_confirmation(
        phone_number=order.get("phone"),
        order_id=order.get("order_id"),
        customer_name=order.get("name"),
        amount=order.get("amount"),
        payment_method=order.get("payment_method"),
        delivery_timeline=order.get("delivery_timeline", "3-5 Business Days")
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to send WhatsApp notification"))
    
    return result


# ==================== CONSULTATIONS ====================

@api_router.get("/admin/consultations")
async def get_all_consultations(
    limit: int = Query(100),
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    x_employee_token: str = Header(None, alias="X-Employee-Token")
):
    """Get all skin consultations"""
    if x_admin_token:
        verify_admin_token(x_admin_token)
    elif x_employee_token:
        session = verify_employee_token(x_employee_token)
        if not session["permissions"].get("consultations"):
            raise HTTPException(status_code=403, detail="No permission to view consultations")
    else:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    consultations = await db.consultations.find({}).sort("created_at", -1).to_list(limit)
    
    # Convert ObjectId to string
    for c in consultations:
        c["_id"] = str(c["_id"])
    
    return {"consultations": consultations}


@api_router.post("/admin/whatsapp/notify-consultation")
async def send_consultation_whatsapp_notification(request: WhatsAppConsultationNotifyRequest, x_admin_token: str = Header(None)):
    """Send consultation results via WhatsApp"""
    verify_admin_token(x_admin_token)
    
    # Get consultation details
    consultation = await db.consultations.find_one({"consultation_id": request.consultation_id}, {"_id": 0})
    if not consultation:
        raise HTTPException(status_code=404, detail="Consultation not found")
    
    # Build recommendations text
    recommendations = request.recommendations or "Based on your skin analysis, we recommend Celesta Glow's complete anti-aging routine. Start with our Gentle Cleanser, apply the Advanced Face Serum, and protect with SPF 50 Sunscreen daily. Use the Retinoid Night Cream and Under Eye Cream at night for best results."
    
    result = await whatsapp_service.send_consultation_result(
        phone_number=consultation.get("phone"),
        customer_name=consultation.get("name"),
        consultation_id=consultation.get("consultation_id"),
        skin_type=consultation.get("skin_type", "Normal"),
        concerns=consultation.get("concerns", []),
        recommendations=recommendations
    )
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to send WhatsApp notification"))
    
    return result


@api_router.get("/admin/whatsapp/logs")
async def get_whatsapp_logs(
    x_admin_token: str = Header(None),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None)
):
    """Get WhatsApp message logs"""
    verify_admin_token(x_admin_token)
    
    logs = await whatsapp_service.get_message_logs(limit=limit, status=status)
    return {"logs": logs}


@api_router.get("/admin/whatsapp/stats")
async def get_whatsapp_stats(x_admin_token: str = Header(None)):
    """Get WhatsApp messaging statistics"""
    verify_admin_token(x_admin_token)
    
    stats = await whatsapp_service.get_stats()
    return stats


@api_router.post("/admin/whatsapp/test")
async def test_whatsapp_connection(x_admin_token: str = Header(None), phone: str = Query(...)):
    """Test WhatsApp API connection by sending a test message"""
    verify_admin_token(x_admin_token)
    
    result = await whatsapp_service.send_text_message(
        phone_number=phone,
        message="This is a test message from Celesta Glow Admin Panel. WhatsApp integration is working! ✅"
    )
    
    return result



# ==================== REFERRAL SYSTEM ENDPOINTS ====================

@api_router.post("/referral/validate")
async def validate_referral(referral_code: str = Query(...)):
    """Validate a referral code and return referrer info.
    The ₹50 referral discount only applies on orders ≥ ₹500 (enforced by
    the existing WELCOME50 coupon, which mirrors the same min-order rule).
    """
    referral = await referral_service.validate_referral_code(referral_code)
    if referral:
        return {
            "valid": True,
            "referral": referral,
            "discount": 50,
            "min_order_amount": 500,
            "discount_code": "WELCOME50",  # auto-apply the same WELCOME50 coupon
        }
    return {"valid": False, "discount": 0}


@api_router.post("/referral/track-click")
async def track_referral_click(referral_code: str = Query(...), visitor_id: str = Query(None)):
    """Track when someone clicks a referral link"""
    success = await referral_service.track_referral_click(referral_code, visitor_id)
    return {"success": success}


@api_router.get("/referral/stats/{phone}")
async def get_referral_stats(phone: str):
    """Get referral stats for a user"""
    stats = await referral_service.get_referral_stats(phone=phone)
    if stats:
        return {"success": True, "stats": stats}
    return {"success": False, "stats": None}


@api_router.get("/admin/referrals")
async def get_all_referrals(
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    limit: int = Query(100),
    page: int = Query(1, ge=1),
    q: Optional[str] = Query(None, description="Search by referrer name/phone/code"),
):
    """Get referrals with pagination + search."""
    verify_admin_token(x_admin_token)

    query: Dict[str, Any] = {}
    if q:
        pat = {"$regex": re.escape(q), "$options": "i"}
        query["$or"] = [
            {"referrer_name":  pat},
            {"referrer_phone": pat},
            {"referral_code":  pat},
        ]

    total = await db.referrals.count_documents(query)
    skip = (page - 1) * limit
    cursor = db.referrals.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit)
    referrals = await cursor.to_list(length=limit)
    summary = await referral_service.get_referral_summary()

    return {
        "referrals": referrals,
        "summary": summary,
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "pages": max(1, (total + limit - 1) // limit),
        },
    }


class ManualReferralIn(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None


@api_router.post("/admin/referrals/create-manual")
async def create_manual_referral(
    payload: ManualReferralIn,
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
):
    """Admin: manually create a referral link for a person without needing them
    to place an order first. Idempotent — reusing the same phone returns the
    existing code so admins can safely re-share the same link."""
    verify_admin_token(x_admin_token)
    if not payload.phone or not payload.name:
        raise HTTPException(status_code=400, detail="name and phone are required")

    result = await referral_service.create_referral({
        "name": payload.name,
        "phone": payload.phone,
        "email": payload.email,
        "order_id": None,  # manual — no linked order
    })
    return {
        "success": True,
        "referral_code": result["referral_code"],
        "referral_link": result["referral_link"],
        "is_new": result.get("is_new", False),
        "referrer_name": payload.name,
        "referrer_phone": payload.phone,
    }


@api_router.post("/admin/referrals/mark-paid")
async def mark_referral_paid(
    referral_code: str = Query(...),
    amount: int = Query(...),
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    """Mark referral earnings as paid"""
    verify_admin_token(x_admin_token)
    
    success = await referral_service.mark_earnings_paid(referral_code, amount)
    return {"success": success}


@api_router.post("/admin/referrals/mark-order-paid")
async def mark_order_cashback_paid(
    referral_code: str = Query(...),
    order_id: str = Query(...),
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    """Mark a specific referred order's cashback as paid"""
    verify_admin_token(x_admin_token)
    
    success = await referral_service.mark_order_cashback_paid(referral_code, order_id)
    return {"success": success, "message": f"Cashback for order {order_id} marked as paid" if success else "Failed to mark as paid"}


@api_router.get("/admin/referrals/{referral_code}")
async def get_referral_details(
    referral_code: str,
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    """Get detailed referral info including all referred orders"""
    verify_admin_token(x_admin_token)
    
    referral = await referral_service.get_referral_with_orders(referral_code)
    if not referral:
        raise HTTPException(status_code=404, detail="Referral not found")
    return referral


class SeoBroadcastIn(BaseModel):
    keywords: List[str]
    only_niche: Optional[str] = None  # e.g. 'anti-aging' → limit scope
    only_active: bool = True


class AltTextBackfillIn(BaseModel):
    only_niche: Optional[str] = None
    only_active: bool = True
    overwrite: bool = False  # False = only fill empties


@api_router.post("/admin/seo-keywords/bulk-alt-text")
async def bulk_generate_alt_text(
    payload: AltTextBackfillIn,
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
):
    """Admin: auto-generate `image_alt_text` on every matching product using
    the pattern `{name} — {niche} skincare from Celesta Glow`. Skips products
    that already have alt text unless `overwrite=True`. Fires Google image
    search discoverability without needing per-product manual entry."""
    verify_admin_token(x_admin_token)

    query: Dict[str, Any] = {}
    if payload.only_active:
        query["is_active"] = {"$ne": False}
    if payload.only_niche:
        query["niche"] = payload.only_niche
    if not payload.overwrite:
        query["$or"] = [
            {"image_alt_text": {"$exists": False}},
            {"image_alt_text": None},
            {"image_alt_text": ""},
        ]

    matched = 0
    modified = 0
    _NICHE_LABEL = {"anti-aging": "anti-aging", "skincare": "skincare", "cosmetics": "cosmetics"}
    async for p in db.products.find(query, {"_id": 0, "slug": 1, "name": 1, "niche": 1}):
        matched += 1
        nlabel = _NICHE_LABEL.get(str(p.get("niche") or "").lower(), "skincare")
        alt = f"{p.get('name') or p.get('slug')} — dermatologist recommended {nlabel} from Celesta Glow Kerala"
        r = await db.products.update_one(
            {"slug": p["slug"]},
            {"$set": {"image_alt_text": alt, "updated_at": datetime.now(timezone.utc).isoformat()}},
        )
        modified += r.modified_count

    return {"success": True, "products_matched": matched, "products_modified": modified}


@api_router.post("/admin/seo-keywords/broadcast")
async def broadcast_seo_keywords(
    payload: SeoBroadcastIn,
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
):
    """Admin: append one or more keywords to *every* product's seo_keywords[]
    in a single batch. Uses `$addToSet` so duplicates are silently ignored.
    Optionally scoped to a specific niche or only active products."""
    verify_admin_token(x_admin_token)

    cleaned = sorted({str(k).strip().lower() for k in (payload.keywords or []) if str(k).strip()})
    if not cleaned:
        raise HTTPException(status_code=400, detail="At least one keyword required")

    query: Dict[str, Any] = {}
    if payload.only_active:
        query["is_active"] = {"$ne": False}
    if payload.only_niche:
        query["niche"] = payload.only_niche

    matched = await db.products.count_documents(query)
    result = await db.products.update_many(
        query,
        {"$addToSet": {"seo_keywords": {"$each": cleaned}},
         "$set": {"updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {
        "success": True,
        "keywords_added": cleaned,
        "products_matched": matched,
        "products_modified": result.modified_count,
    }


@api_router.post("/admin/referrals/test-purchase")
async def test_referral_purchase(
    referral_code: str = Query(...),
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    """Simulate a referral purchase for testing"""
    verify_admin_token(x_admin_token)
    
    # Create a test order
    test_order = {
        "order_id": f"TEST_{uuid.uuid4().hex[:8].upper()}",
        "phone": "9999999999",
        "name": "Test Buyer",
        "amount": 599
    }
    
    result = await referral_service.record_referral_purchase(referral_code, test_order)
    return result


# ---- Customer-facing referral dashboard ----
@api_router.get("/referral/customer-summary")
async def referral_customer_summary(
    phone: Optional[str] = Query(None),
    email: Optional[str] = Query(None),
):
    """Returns the data needed to render the customer's referral widget on
    /account: their share link, lifetime/pending/withdrawable balances, and
    every order made via their link with its delivery + cashback state.
    Either `phone` or `email` is required.
    """
    summary = await referral_service.get_customer_summary(phone=phone, email=email)
    if not summary:
        return {"success": False, "summary": None, "message": "No referral record yet"}
    return {"success": True, "summary": summary}


@api_router.post("/referral/request-withdrawal")
async def request_referral_withdrawal(payload: dict = Body(...)):
    """Customer requests a payout of their full withdrawable balance.

    Body: {
      referral_code: str,
      payout_method: 'upi' | 'bank',
      payout_destination: str,   # UPI ID or account number
      note?: str
    }
    """
    code = (payload.get("referral_code") or "").strip()
    method = (payload.get("payout_method") or "").strip().lower()
    dest   = (payload.get("payout_destination") or "").strip()
    note   = payload.get("note", "")
    if not code or method not in ("upi", "bank") or not dest:
        raise HTTPException(status_code=400, detail="referral_code, payout_method (upi/bank) and payout_destination are required")
    result = await referral_service.request_withdrawal(code, method, dest, note)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Withdrawal request failed"))
    return result


@api_router.get("/admin/withdrawal-requests")
async def admin_list_withdrawals(
    status: Optional[str] = Query(None),
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
):
    """Admin: list withdrawal requests, optionally filter by status
    (pending | paid | rejected)."""
    verify_admin_token(x_admin_token)
    requests = await referral_service.list_withdrawal_requests(status=status)
    return {"success": True, "requests": requests}


@api_router.post("/admin/withdrawal-requests/{request_id}/mark-paid")
async def admin_mark_withdrawal_paid(
    request_id: str,
    payload: dict = Body(default={}),
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
):
    """Admin: mark a withdrawal request as paid. Optional body { txn_ref: str }."""
    verify_admin_token(x_admin_token)
    txn_ref = (payload or {}).get("txn_ref", "")
    result = await referral_service.mark_withdrawal_paid(request_id, txn_ref=txn_ref)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Mark-paid failed"))
    return result


@api_router.post("/admin/withdrawal-requests/{request_id}/reject")
async def admin_reject_withdrawal(
    request_id: str,
    payload: dict = Body(default={}),
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
):
    """Admin: reject a withdrawal request with a reason."""
    verify_admin_token(x_admin_token)
    reason = (payload or {}).get("reason", "")
    result = await referral_service.reject_withdrawal(request_id, reason)
    return result



# ==================== CONTACT FORM ====================

class ContactFormRequest(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    subject: str = "general"
    message: str

@api_router.post("/contact")
async def submit_contact_form(request: ContactFormRequest):
    """Handle contact form submissions"""
    from datetime import datetime, timezone
    
    contact_entry = {
        "name": request.name,
        "email": request.email,
        "phone": request.phone,
        "subject": request.subject,
        "message": request.message,
        "status": "new",
        "created_at": datetime.now(timezone.utc)
    }
    
    await db.contact_submissions.insert_one(contact_entry)
    
    return {"success": True, "message": "Your message has been received. We'll get back to you within 24 hours."}


# ==================== EMPLOYEE MANAGEMENT ====================

# employee_sessions is declared earlier near admin_sessions

class CreateEmployeeRequest(BaseModel):
    username: str
    name: str
    password: Optional[str] = None
    email: Optional[str] = None
    permissions: Dict[str, bool]

class EmployeeLoginRequest(BaseModel):
    # Accept either username OR email — frontend can send whichever the user typed.
    # Older clients still send `username`, so we keep that name and treat its value
    # as "any identifier (username or email)".
    username: str
    password: str

class UpdatePasswordRequest(BaseModel):
    username: str
    new_password: str

class UpdatePermissionsRequest(BaseModel):
    username: str
    permissions: Dict[str, bool]


@api_router.post("/admin/employees")
async def create_employee(request: CreateEmployeeRequest, http_request: Request, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    """Create a new employee account (Admin only). Returns the auto-generated
    password (one-time) plus a ready-to-share login URL the admin can paste in
    chat / email — the employee then signs in at /employee/login.
    """
    verify_admin_token(x_admin_token)
    result = await employee_service.create_employee(
        username=request.username,
        name=request.name,
        permissions=request.permissions,
        password=request.password,
        email=request.email,
    )
    if result.get("success"):
        # Build the login URL using whatever public origin the admin is currently on.
        # Order: PUBLIC_APP_URL env → Origin/Referer header → relative fallback.
        public_base = (os.environ.get("PUBLIC_APP_URL") or "").rstrip("/")
        if not public_base:
            origin = http_request.headers.get("origin") or http_request.headers.get("referer") or ""
            if origin:
                # strip path from referer
                from urllib.parse import urlparse
                p = urlparse(origin)
                public_base = f"{p.scheme}://{p.netloc}".rstrip("/")
        result["login_url"] = f"{public_base}/employee/login" if public_base else "/employee/login"
        identifier_line = f"Username: {result.get('username')}"
        if result.get("email"):
            identifier_line += f"\nEmail: {result.get('email')}"
        result["login_message"] = (
            f"Hi {request.name}, your Celesta Glow employee account is ready.\n"
            f"{identifier_line}\n"
            f"Password: {result.get('password')}\n"
            f"Sign in here: {result['login_url']}\n"
            f"(You can sign in with either your username or email.)"
        )
    return result


@api_router.get("/admin/employees")
async def get_all_employees(x_admin_token: str = Header(None, alias="X-Admin-Token")):
    """Get all employees (Admin only)"""
    verify_admin_token(x_admin_token)
    employees = await employee_service.get_all_employees()
    return {"employees": employees}


@api_router.post("/admin/employees/update-password")
async def update_employee_password(request: UpdatePasswordRequest, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    """Update employee password (Admin only)"""
    verify_admin_token(x_admin_token)
    success = await employee_service.update_password(request.username, request.new_password)
    return {"success": success}


@api_router.post("/admin/employees/update-permissions")
async def update_employee_permissions(request: UpdatePermissionsRequest, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    """Update employee permissions (Admin only)"""
    verify_admin_token(x_admin_token)
    success = await employee_service.update_permissions(request.username, request.permissions)
    return {"success": success}


@api_router.delete("/admin/employees/{username}")
async def delete_employee(username: str, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    """Delete/deactivate employee (Admin only)"""
    verify_admin_token(x_admin_token)
    success = await employee_service.delete_employee(username)
    return {"success": success}


@api_router.post("/employee/login")
async def employee_login(request: EmployeeLoginRequest):
    """Employee login endpoint. Accepts username OR email as the identifier."""
    employee = await employee_service.authenticate(request.username, request.password)
    if not employee:
        raise HTTPException(status_code=401, detail="Invalid username/email or password")

    # Generate session token (30-day expiry, stored in MongoDB)
    token = secrets.token_hex(32)
    employee_sessions[token] = {
        "username": employee["username"],
        "permissions": employee["permissions"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=30)),
    }

    return {
        "success": True,
        "token": token,
        "employee": employee
    }


def verify_employee_token(token: str) -> Dict:
    """Verify employee token and return session data"""
    if not token:
        raise HTTPException(status_code=401, detail="No token provided")
    
    session = employee_sessions.get(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    return session


@api_router.get("/employee/verify")
async def verify_employee(x_employee_token: str = Header(None, alias="X-Employee-Token")):
    """Verify employee token and return permissions"""
    session = verify_employee_token(x_employee_token)
    return {"valid": True, "permissions": session["permissions"], "username": session["username"]}


# ==================== CUSTOMER MANAGEMENT ====================

@api_router.get("/admin/customers")
async def get_all_customers(
    limit: int = Query(100),
    skip: int = Query(0),
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    x_employee_token: str = Header(None, alias="X-Employee-Token")
):
    """Get all customers with order status"""
    # Allow admin or employee with customers permission
    if x_admin_token:
        verify_admin_token(x_admin_token)
    elif x_employee_token:
        session = verify_employee_token(x_employee_token)
        if not session["permissions"].get("customers"):
            raise HTTPException(status_code=403, detail="No permission to view customers")
    else:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    result = await customer_service.get_all_customers(limit=limit, skip=skip)
    return result


@api_router.get("/admin/customers/search")
async def search_customers(
    q: str = Query(...),
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    x_employee_token: str = Header(None, alias="X-Employee-Token")
):
    """Search customers by name, phone, or email"""
    if x_admin_token:
        verify_admin_token(x_admin_token)
    elif x_employee_token:
        session = verify_employee_token(x_employee_token)
        if not session["permissions"].get("customers"):
            raise HTTPException(status_code=403, detail="No permission to view customers")
    else:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    customers = await customer_service.search_customers(q)
    return {"customers": customers}


@api_router.get("/admin/customers/{phone}")
async def get_customer_by_phone(
    phone: str,
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    x_employee_token: str = Header(None, alias="X-Employee-Token")
):
    """Get customer details by phone"""
    if x_admin_token:
        verify_admin_token(x_admin_token)
    elif x_employee_token:
        session = verify_employee_token(x_employee_token)
        if not session["permissions"].get("customers"):
            raise HTTPException(status_code=403, detail="No permission to view customers")
    else:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    customer = await customer_service.get_customer_by_phone(phone)
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


# ==================== DELHIVERY SHIPPING INTEGRATION ====================

class TrackOrderRequest(BaseModel):
    phone: Optional[str] = None
    email: Optional[str] = None


@api_router.post("/track-order")
async def track_order_by_phone(request: TrackOrderRequest):
    """Track orders by phone OR email (Customer facing)."""
    phone = (request.phone or "").strip()
    email = (request.email or "").strip().lower()

    if not phone and not email:
        raise HTTPException(status_code=400, detail="Enter phone number or email")

    # Email-first path: look up orders by email directly from our DB
    if email:
        cursor = db.orders.find({"email": email}, {"_id": 0}).sort("created_at", -1).limit(50)
        orders = []
        async for o in cursor:
            awb = o.get("awb_number")
            orders.append({
                "order_id": o.get("order_id"),
                "status": o.get("status"),
                "total_amount": o.get("amount"),
                "payment_method": o.get("payment_method"),
                "created_at": o.get("created_at"),
                "items": o.get("items") or [],
                "awb_number": awb,
                "tracking_url": f"https://www.delhivery.com/track/package/{awb}" if awb else None,
                "delivery_timeline": o.get("delivery_timeline"),
            })
        return {"success": True, "orders": orders, "count": len(orders)}

    # Phone path (legacy): delegate to Delhivery service
    if len(phone) < 10:
        raise HTTPException(status_code=400, detail="Enter valid 10-digit phone number")
    phone = phone[-10:]
    return await delhivery_service.track_by_phone(phone)


@api_router.get("/track-order/{order_id}")
async def track_order_by_id(order_id: str):
    """Track a specific order by order ID"""
    order = await db.orders.find_one(
        {"order_id": order_id},
        {"_id": 0}
    )
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    result = {
        "success": True,
        "order_id": order_id,
        "name": order.get("name"),
        "status": order.get("status"),
        "total_amount": order.get("total_amount"),
        "payment_method": order.get("payment_method"),
        "created_at": order.get("created_at"),
        "awb_number": order.get("awb_number"),
        "tracking_url": None,
        "delivery_status": None
    }
    
    # If AWB exists, get tracking info
    awb = order.get("awb_number")
    if awb:
        tracking = await delhivery_service.track_shipment(awb)
        if tracking.get("success"):
            result["delivery_status"] = tracking.get("status")
            result["expected_delivery"] = tracking.get("expected_delivery")
            result["status_location"] = tracking.get("status_location")
            result["tracking_url"] = f"https://www.delhivery.com/track/package/{awb}"
            result["scans"] = tracking.get("scans", [])
    
    return result


@api_router.get("/shipping/serviceability/{pincode}")
async def check_pincode_serviceability(pincode: str):
    """Check if a pincode is serviceable for delivery"""
    if not pincode.isdigit() or len(pincode) != 6:
        raise HTTPException(status_code=400, detail="Invalid pincode")
    
    result = await delhivery_service.check_serviceability(pincode)
    return result


@api_router.post("/admin/shipping/create-shipment/{order_id}")
async def admin_create_shipment(
    order_id: str,
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    x_employee_token: str = Header(None, alias="X-Employee-Token")
):
    """Create a Delhivery shipment for an order (Admin only)"""
    if x_admin_token:
        verify_admin_token(x_admin_token)
    elif x_employee_token:
        session = verify_employee_token(x_employee_token)
        if not session["permissions"].get("orders"):
            raise HTTPException(status_code=403, detail="No permission to manage shipments")
    else:
        raise HTTPException(status_code=401, detail="Unauthorized")

    order = await db.orders.find_one({"order_id": order_id}, {"_id": 0})
    
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    
    if order.get("awb_number"):
        return {
            "success": False,
            "error": "Shipment already created",
            "awb_number": order.get("awb_number")
        }

    # Normalise order payload for Delhivery.
    # IMPORTANT: For COD the customer pays the entire ``order.amount`` on
    # delivery — no Razorpay advance is collected at checkout. Delhivery
    # must therefore collect the FULL ``amount`` field (do not subtract
    # any phantom "COD advance" here — that bug previously made the
    # collectable show up ~₹50 short on Delhivery).
    is_cod = "COD" in (order.get("payment_method") or "")
    order_for_delhivery = {
        "order_id": order.get("order_id"),
        "name": order.get("name"),
        "phone": order.get("phone"),
        "house_number": order.get("house_number", ""),
        "area": order.get("area", ""),
        "pincode": order.get("pincode"),
        "city": order.get("city") or order.get("area", ""),
        "state": order.get("state", ""),
        "payment_method": "cod" if is_cod else "prepaid",
        "cod_balance": order.get("amount", 0) if is_cod else 0,
        "total_amount": order.get("amount", 0),
    }

    result = await delhivery_service.create_shipment(order_for_delhivery)
    return result


@api_router.get("/admin/shipping/track/{awb}")
async def admin_track_shipment(
    awb: str,
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    x_employee_token: str = Header(None, alias="X-Employee-Token")
):
    """Track a shipment by AWB number (Admin only)"""
    if x_admin_token:
        verify_admin_token(x_admin_token)
    elif x_employee_token:
        verify_employee_token(x_employee_token)
    else:
        raise HTTPException(status_code=401, detail="Unauthorized")

    result = await delhivery_service.track_shipment(awb)
    return result


# Webhook for Delhivery status updates
@api_router.post("/webhook/delhivery")
async def delhivery_webhook(request: Request):
    """Receive delivery status updates from Delhivery"""
    try:
        data = await request.json()
        
        waybill = data.get("waybill")
        status = data.get("status", {})
        
        if waybill:
            # Update order status based on Delhivery status
            delhivery_status = status.get("Status", "").lower()
            
            new_status = None
            if "delivered" in delhivery_status:
                new_status = "delivered"
            elif "out for delivery" in delhivery_status:
                new_status = "out_for_delivery"
            elif "in transit" in delhivery_status:
                new_status = "shipped"
            
            if new_status:
                await db.orders.update_one(
                    {"awb_number": waybill},
                    {"$set": {
                        "status": new_status,
                        "delivery_status": delhivery_status,
                        "last_tracking_update": datetime.now(timezone.utc).isoformat()
                    }}
                )
        
        return {"success": True}
        
    except Exception as e:
        logging.error(f"Delhivery webhook error: {str(e)}")
        return {"success": False, "error": str(e)}


# ---------- Keep-alive / health probe (cheap, no DB hit) ----------
# Frontend pings this every 4 min to keep the backend pod warm. Returns 200
# instantly with no Mongo query so it costs almost zero compute.
@app.get("/api/health")
async def health_check():
    return {"ok": True, "ts": datetime.now(timezone.utc).isoformat()}




app.include_router(api_router)
app.include_router(admin_routes.router, prefix="/api")
app.include_router(i18n_routes.router, prefix="/api")
app.include_router(consultation_routes.router, prefix="/api")
doctor_consultation_routes.setup(db, verify_admin_token, razorpay_client)
app.include_router(doctor_consultation_routes.router, prefix="/api")
mp_core_routes.setup(db, verify_admin_token, razorpay_client)
mp_ops_routes.setup(db, verify_admin_token, razorpay_client)
app.include_router(mp_core_routes.router, prefix="/api")
app.include_router(mp_ops_routes.router, prefix="/api")
app.include_router(mp_catalog_routes.router, prefix="/api")

# AutoFill AI — Amazon & Flipkart listing feature (cloned from dragon16t/chrome-extension,
# mounted under /api/af on its own _afext database so it never collides with the store).
try:
    import af_feature
    app.include_router(af_feature.af_api)
    app.include_router(af_feature.af_auth_router)

    @app.on_event("startup")
    async def _af_seed_startup():
        try:
            await af_feature.seed_admin(af_feature.af_db)
        except Exception as _afse:  # noqa: BLE001
            logging.getLogger(__name__).error(f"AF seed failed: {_afse}")
except Exception as _afe:  # noqa: BLE001
    logging.getLogger(__name__).error(f"AF feature mount failed: {_afe}")
from services import mp_common as _mp_common


@app.on_event("startup")
async def mp_marketplace_bootstrap():
    try:
        await _mp_common.ensure_indexes()
        await mp_core_routes.seed_defaults(db)
        await mp_catalog_routes.seed_hb(db)
    except Exception as exc:
        logging.getLogger(__name__).warning(f"[mp] bootstrap failed: {exc}")
skincare_extras_routes.setup(db, verify_admin_token)
app.include_router(skincare_extras_routes.router, prefix="/api")
sale_mode_routes.setup(db, verify_admin_token)
app.include_router(sale_mode_routes.router, prefix="/api")
payment_policy_routes.setup(db, verify_admin_token)
app.include_router(payment_policy_routes.router, prefix="/api")
from routes import trend_products as trend_products_routes  # noqa: E402
trend_products_routes.setup(db, verify_admin_token)
app.include_router(trend_products_routes.router, prefix="/api")
from routes import image_gallery_admin as image_gallery_admin_routes  # noqa: E402
image_gallery_admin_routes.setup(db, verify_admin_token)
app.include_router(image_gallery_admin_routes.router, prefix="/api")
delivery_men_routes.setup(db, verify_admin_token)
app.include_router(delivery_men_routes.router, prefix="/api")
app.include_router(geo_routes.router, prefix="/api")
app.include_router(reels_routes.router, prefix="/api")
warehouses_routes.setup(db, verify_admin_token)
app.include_router(warehouses_routes.router, prefix="/api")
app.include_router(landing_page_routes.router, prefix="/api")
app.include_router(product_routes.router, prefix="/api")
app.include_router(concerns_routes.router, prefix="/api")
app.include_router(image_ai_routes.router, prefix="/api")
app.include_router(reviews_routes.router, prefix="/api")

# Shipping labels (India Post A6 PDF) — single + bulk
from routes import shipping_labels as _shipping_labels  # noqa: E402
app.include_router(_shipping_labels.router, prefix="/api")

# SEO — dynamic sitemap + product feed (DB-backed; new SKUs auto-show up)
from routes import seo as _seo_routes  # noqa: E402
_seo_routes.set_db(db)
app.include_router(_seo_routes.router, prefix="/api")

# Live visitor tracking — anonymous presence pings ("who's online right now")
from routes import visitor_tracking as _visitor_tracking  # noqa: E402
_visitor_tracking.init_visitor_tracking(db, verify_admin_token)
app.include_router(_visitor_tracking.router)

# Customer Email OTP auth + orders + cart
customer_auth_routes.init_auth_router(db)
app.include_router(customer_auth_routes.router, prefix="/api")
app.include_router(bulk_import_routes.router)
app.include_router(master_import_routes.router)
app.include_router(gift_cards_routes.router)

# P1: Admin Revenue (Feb 2026) — day/month revenue, two-line split (placed vs delivered),
# Delhivery sync, full-fields export.
from routes import admin_revenue as _admin_revenue  # noqa: E402
app.include_router(_admin_revenue.router, prefix="/api")

# P2: Admin brand grouping, brand-wise pricing, public order tracking, user journey
from routes import admin_brands as _admin_brands  # noqa: E402
app.include_router(_admin_brands.router, prefix="/api")
from routes import brands_public as _brands_public  # noqa: E402
app.include_router(_brands_public.router, prefix="/api")

# Email service (Gmail → SendGrid auto-failover at 250 emails/day IST)
from services import email_service as _email_service
_email_service.set_db(db)
# Cloudinary admin + upload endpoints
from routes import cloudinary_routes  # noqa: E402
cloudinary_routes.set_db(db)
app.include_router(cloudinary_routes.router, prefix="/api")

# Routines + retention reorder endpoints
from routes import routines as routines_routes  # noqa: E402
routines_routes.set_db(db)
app.include_router(routines_routes.router, prefix="/api")

from routes import progress_tracker as progress_tracker_routes  # noqa: E402
progress_tracker_routes.set_db(db)
app.include_router(progress_tracker_routes.router, prefix="/api")

# 30-Day AI Skin Journey (progressive Gemini tasks + Razorpay renewal)
from routes import journey as journey_routes  # noqa: E402
journey_routes.set_db(db)
journey_routes.set_razorpay(razorpay_client)
app.include_router(journey_routes.router, prefix="/api")

# AI-generated FAQs per niche (skincare / cosmetics / anti-aging)
from routes import faqs as faqs_routes  # noqa: E402
from services.faq_generator import FAQGenerator  # noqa: E402
_faq_service = FAQGenerator(db)
faqs_routes.set_faq_service(_faq_service)
faqs_routes.set_admin_sessions(admin_sessions)
app.include_router(faqs_routes.router)

# Admin orders v2 — internal notes, audit log, bulk status, printable invoice (B5)
from routes import admin_orders_v2 as admin_orders_v2_routes  # noqa: E402
admin_orders_v2_routes.set_db(db)
admin_orders_v2_routes.set_admin_sessions(admin_sessions)
app.include_router(admin_orders_v2_routes.router)

# Admin shades — AI color lookup + swatch image upload
from routes import admin_shades as admin_shades_routes  # noqa: E402
admin_shades_routes.set_db(db)
admin_shades_routes.set_admin_sessions(admin_sessions)
app.include_router(admin_shades_routes.router)

# Admin dashboard summary widgets
from routes import admin_dashboard as admin_dashboard_routes  # noqa: E402
admin_dashboard_routes.set_db(db)
admin_dashboard_routes.set_admin_sessions(admin_sessions)
app.include_router(admin_dashboard_routes.router)

# Share admin_sessions with image_ai routes
image_ai_routes.set_admin_sessions(admin_sessions)
image_ai_routes.set_db(db)

# Mount uploads directory so /api/uploads/ai_bg/* is publicly accessible via ingress
from fastapi.staticfiles import StaticFiles  # noqa: E402
_uploads_dir = ROOT_DIR / "uploads"
_uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/api/uploads", StaticFiles(directory=str(_uploads_dir)), name="uploads")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)

# Gzip-compress responses > 1KB → 60-80% smaller payloads, much faster page loads
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Rate limiting (B8 fix S12) — per-IP + per-endpoint token bucket
from services.rate_limit import RateLimitMiddleware  # noqa: E402
app.add_middleware(RateLimitMiddleware)

# Auto-snapshot middleware: per-write snapshot was disabled (Feb 2026) and the
# remaining no-op BaseHTTPMiddleware tripped Starlette's "No response returned"
# bug for certain streaming/long-poll responses, spamming the logs. The
# snapshot schedule_snapshot helper is still imported for explicit callers
# below; the middleware itself is unregistered.
from services import catalog_backup as _cb_module  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.on_event("startup")
async def startup_seed():
    """Fast startup — offload heavy work to a background task so the K8s
    readiness probe (`/health`) responds in <1s. Anything that scans the full
    27k-product catalog (canonical taxonomy reset, reclassify, master-brain,
    catalog snapshot restore) MUST run in `_run_heavy_startup_tasks()` below.
    """
    # Fast: hydrate admin/employee sessions from Mongo so cookies survive pod
    # restarts. These are single collection loads (<100ms).
    try:
        await admin_sessions.ensure_indexes()
        await employee_sessions.ensure_indexes()
        await admin_sessions.hydrate()
        await employee_sessions.hydrate()
    except Exception as e:
        logging.error(f"Failed to hydrate sessions: {e}")

    # Fast: refresh admin password cache (single Mongo doc lookup)
    try:
        await product_routes._refresh_admin_pw_cache()
    except Exception as e:
        logging.error(f"Failed to refresh admin pw cache: {e}")

    # Fast: hydrate active-admin-hash cache used by every admin verifier
    try:
        from services.admin_auth import refresh_active_admin_hash
        await refresh_active_admin_hash(db)
    except Exception as e:
        logging.error(f"Failed to hydrate active admin hash: {e}")

    # Fast: visitor-tracking TTL index
    try:
        await _visitor_tracking.ensure_indexes()
    except Exception as e:
        logging.error(f"Failed to create visitor tracking indexes: {e}")

    # Fast: bootstrap Cloudinary credentials from env
    try:
        from services import cloudinary_service as _cs
        env_cloud  = (os.environ.get("CLOUDINARY_CLOUD_NAME") or "").strip()
        env_key    = (os.environ.get("CLOUDINARY_API_KEY") or "").strip()
        env_secret = (os.environ.get("CLOUDINARY_API_SECRET") or "").strip()
        existing = await db.admin_settings.find_one({"type": "cloudinary"})
        patch = {}
        if not existing:
            patch = {
                "type": "cloudinary",
                "cloud_name": env_cloud,
                "api_key": env_key,
                "api_secret": env_secret,
            }
        else:
            if not (existing.get("cloud_name") or "").strip() and env_cloud:
                patch["cloud_name"] = env_cloud
            if not (existing.get("api_key") or "").strip() and env_key:
                patch["api_key"] = env_key
            if not (existing.get("api_secret") or "").strip() and env_secret:
                patch["api_secret"] = env_secret
        if patch:
            patch["updated_at"] = datetime.now(timezone.utc).isoformat()
            await db.admin_settings.update_one(
                {"type": "cloudinary"}, {"$set": patch}, upsert=True,
            )
            logging.info(f"[cloudinary] bootstrap patched fields: {list(patch.keys())}")
        await _cs.get_cloudinary_credentials(db)
        if _cs.is_configured():
            logging.info("[cloudinary] ready for uploads")
        else:
            logging.warning(
                "[cloudinary] NOT configured — image uploads will fail. "
                "Set CLOUDINARY_CLOUD_NAME / API_KEY / API_SECRET env vars or "
                "save them in admin settings."
            )
    except Exception as e:
        logging.error(f"Failed to seed cloudinary creds: {e}")

    # Fast: one-time migration to update legacy volume_discount tiers
    try:
        await db.site_settings.update_one(
            {"_id": "main", "$or": [
                {"volume_discounts": {"$exists": False}},
                {"volume_discounts": [
                    {"min_items": 2, "discount_percent": 5},
                    {"min_items": 3, "discount_percent": 10},
                    {"min_items": 4, "discount_percent": 15},
                ]}
            ]},
            {"$set": {"volume_discounts": [
                {"min_items": 2, "discount_percent": 3},
                {"min_items": 3, "discount_percent": 5},
                {"min_items": 4, "discount_percent": 8},
            ]}},
        )
    except Exception as e:
        logging.error(f"Failed to migrate volume_discounts: {e}")

    # Kick off ALL heavy work in the background so /health returns instantly
    # and the K8s readiness probe passes. Anything below runs on the event
    # loop but does NOT block the ASGI lifespan startup completion.
    asyncio.create_task(_run_heavy_startup_tasks())

    # Daily midnight-IST backup scheduler (also a background task)
    try:
        asyncio.create_task(_daily_backup_loop())
        logging.info("[catalog_backup] daily midnight-IST scheduler started")
    except Exception as e:
        logging.warning(f"[catalog_backup] could not start scheduler: {e}")

    logging.info("[startup] fast bootstrap complete — heavy tasks running in background")


async def _run_heavy_startup_tasks():
    """Heavy startup work (product seeding, migrations, catalog restore, 27k
    product reclassification). Runs as a background task after the ASGI
    lifespan startup so the K8s readiness probe on /health passes in seconds
    instead of timing out after 10+ min.
    """
    try:
        await product_routes.seed_products()
        await product_routes.ensure_indexes()
    except Exception as e:
        logging.error(f"[bg-startup] Failed to seed products: {e}")
    try:
        from migrations import run_all_migrations
        await run_all_migrations(db)
    except Exception as e:
        logging.error(f"[bg-startup] Failed to run migrations: {e}", exc_info=True)
    try:
        from concerns_seed import run_concerns_seed
        await run_concerns_seed(db)
    except Exception as e:
        logging.error(f"[bg-startup] Failed to seed concerns: {e}", exc_info=True)

    # ---- Taxonomy auto-restore from Cloudinary snapshot (RUN FIRST) ----
    # CRITICAL ORDERING (Feb-2026): restore runs BEFORE the canonical taxonomy
    # reset so the version sentinel + admin-curated images come back FIRST.
    try:
        from services import catalog_backup as _cb
        restore_res = await _cb.auto_restore_if_empty(db)
        if restore_res.get("restored"):
            logging.info(f"[bg-startup][catalog_backup] auto-restored taxonomy: {restore_res}")
    except Exception as e:
        logging.warning(f"[bg-startup][catalog_backup] auto-restore skipped: {e}")

    # Apply the CANONICAL taxonomy (Jan 2026 user spec).
    CANONICAL_VERSION = "2026-02-granular-subs-v5"
    try:
        settings = await db.site_settings.find_one(
            {"_id": "main"},
            {"_id": 0, "taxonomy_canonical_applied": 1, "taxonomy_canonical_version": 1}
        )
        applied_version = (settings or {}).get("taxonomy_canonical_version")
        if applied_version != CANONICAL_VERSION:
            from services.taxonomy_canonical import (
                reset_canonical_taxonomy, reclassify_all_products, compute_product_tags
            )
            seeded = await reset_canonical_taxonomy(db)
            logging.info(f"[bg-startup][taxonomy_canonical {CANONICAL_VERSION}] reset inserted {seeded}")
            classified = await reclassify_all_products(db)
            logging.info(f"[bg-startup][taxonomy_canonical] classified {classified.get('updated')} products")
            tagged = await compute_product_tags(db)
            logging.info(f"[bg-startup][taxonomy_canonical] tagged {tagged.get('updated')} products")
        else:
            logging.info(f"[bg-startup][taxonomy_canonical] {CANONICAL_VERSION} already applied — skipping reset")
    except Exception as e:
        logging.error(f"[bg-startup] Failed to apply canonical taxonomy: {e}", exc_info=True)

    # ---- Post-restore master-brain reclassify ----
    try:
        from services.taxonomy_canonical import reclassify_all_products as _rc
        rerun = await _rc(db)
        logging.info(f"[bg-startup][taxonomy_canonical] post-startup reclassify: updated={rerun.get('updated')}")
    except Exception as e:
        logging.warning(f"[bg-startup][taxonomy_canonical] post-startup reclassify skipped: {e}")

    try:
        from services.live_seed import apply_live_seed
        await apply_live_seed(db)
    except Exception as e:
        logging.error(f"[bg-startup][live_seed] failed: {e}")

    logging.info("[bg-startup] heavy startup tasks complete")


async def _daily_backup_loop():
    """Daily midnight-IST catalog backup scheduler."""
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    IST = _tz(_td(hours=5, minutes=30))
    from services import catalog_backup as _cb_local
    while True:
        try:
            now_ist = _dt.now(IST)
            next_run = now_ist.replace(hour=0, minute=0, second=0, microsecond=0) + _td(days=1)
            wait_seconds = max(60, (next_run - now_ist).total_seconds())
            logging.info(f"[catalog_backup] next daily snapshot at {next_run.isoformat()} (in {int(wait_seconds//60)} min)")
            await asyncio.sleep(wait_seconds)
            try:
                meta = await db.admin_settings.find_one({"type": "catalog_backup"}, {"_id": 0, "current_full_public_id": 1}) or {}
                if meta.get("current_full_public_id"):
                    res = await _cb_local.incremental_snapshot(db)
                    if res.get("skipped_no_changes") or res.get("skipped_dedupe"):
                        logging.info("[catalog_backup] daily: no changes since last snapshot — nothing to upload")
                    elif res.get("success"):
                        logging.info(f"[catalog_backup] daily incremental uploaded: changed={res.get('changed')}")
                    else:
                        logging.warning(f"[catalog_backup] daily incremental skipped: {res.get('reason')}")
                else:
                    res = await _cb_local.snapshot(db)
                    logging.info(f"[catalog_backup] daily full snapshot OK: {res.get('counts')}")
            except Exception as exc:
                logging.error(f"[catalog_backup] daily snapshot FAILED: {exc}")
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logging.warning(f"[catalog_backup] scheduler error, retrying in 5 min: {exc}")
            await asyncio.sleep(300)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
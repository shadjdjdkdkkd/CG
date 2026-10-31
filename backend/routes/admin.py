"""
Admin API Routes - Content Management System
"""
import logging
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime, timezone
import uuid
import re
import os
import hashlib

from services.admin_auth import (
    get_active_admin_hash,
    is_admin_password,
    has_custom_admin_password,
)

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger(__name__)


def _admin_pw_hash() -> str:
    """Always resolve from env at call-time so password changes actually take
    effect without a redeploy. Falls back to the seed value only when no env
    var is set. Fixes a security bug where the hash was frozen at module-load
    time and accepted the seed password forever."""
    pw = os.environ.get("ADMIN_PASSWORD") or "celestaglow2024"
    return hashlib.sha256(pw.encode()).hexdigest()


# Back-compat shim — some older code paths read the module-level constant.
# We keep the name but make it a lazy property by evaluating via a function.
def _get_admin_password_hash():
    return _admin_pw_hash()


class AdminLogin(BaseModel):
    password: str


class AdminPasswordChange(BaseModel):
    current_password: str
    new_password: str


class BlogCreate(BaseModel):
    title: str
    content: str
    meta_description: Optional[str] = None
    keywords: List[str] = []
    status: str = "draft"
    language: str = "en"


class BlogUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    meta_description: Optional[str] = None
    keywords: Optional[List[str]] = None
    status: Optional[str] = None
    language: Optional[str] = None


class LocationCreate(BaseModel):
    state: str
    city: Optional[str] = None
    title: str
    description: str
    climate: Optional[str] = None
    skin_issues: List[str] = []
    recommendations: Optional[str] = None


class LocationUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    climate: Optional[str] = None
    skin_issues: Optional[List[str]] = None
    recommendations: Optional[str] = None


async def verify_admin_async(x_admin_token: str):
    """Async admin token verification.

    Security: once a custom password is stored in ``admin_settings``, the
    env/seed password is no longer accepted (see services/admin_auth.py).
    """
    if not x_admin_token:
        raise HTTPException(status_code=401, detail="Admin token required")

    token_hash = hashlib.sha256(x_admin_token.encode()).hexdigest()
    active_hash = await get_active_admin_hash(db)
    if token_hash == active_hash:
        return True

    raise HTTPException(status_code=403, detail="Invalid admin token")


# Reference to admin_sessions from server.py (will be set via set_admin_sessions)
admin_sessions = {}

def set_admin_sessions(sessions_dict):
    """Set reference to admin_sessions from server.py"""
    global admin_sessions
    admin_sessions = sessions_dict

async def verify_admin(x_admin_token: str = Header(None)):
    """Admin token verification.

    Accepts (1) an active session token, or (2) the *currently active* admin
    password. The active password is the one stored in ``admin_settings`` if
    present; otherwise the env-seed value. Once a custom password has been
    saved, the env-seed value is no longer accepted — closing the security
    hole where the default password kept working after a password change.
    """
    from datetime import datetime, timezone

    if not x_admin_token:
        raise HTTPException(status_code=401, detail="Admin token required")

    # First check if it's a valid session token
    if x_admin_token in admin_sessions:
        session = admin_sessions[x_admin_token]
        expires_at = session["expires_at"]
        # Handle both string (new sessions) and datetime (hydrated from MongoDB)
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        elif isinstance(expires_at, datetime):
            # Ensure timezone-aware
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) < expires_at:
            return True
        else:
            # Remove expired session
            del admin_sessions[x_admin_token]

    # Otherwise the token must hash to the *active* admin hash (DB if set, else env seed).
    token_hash = hashlib.sha256(x_admin_token.encode()).hexdigest()
    if token_hash == await get_active_admin_hash(db):
        return True

    raise HTTPException(status_code=403, detail="Invalid admin token")


def generate_slug(title: str) -> str:
    """Generate URL-friendly slug from title"""
    slug = title.lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    slug = re.sub(r'^-|-$', '', slug)
    return slug


# Will be set from server.py
db = None


def set_db(database):
    global db
    db = database


@router.post("/login")
async def admin_login(credentials: AdminLogin):
    """Admin login - returns token if password matches the *active* admin password.

    Active = stored in ``admin_settings`` if set, otherwise the env-seed value.
    """
    if await is_admin_password(credentials.password, db):
        return {"success": True, "token": credentials.password}
    raise HTTPException(status_code=401, detail="Invalid password")


@router.post("/change-password")
async def change_admin_password(password_data: AdminPasswordChange, x_admin_token: str = Header(None)):
    """Change admin password.
    Auth: accepts an active session token OR the current password as the X-Admin-Token header.
    The body's `current_password` must always match the saved (or default) password.
    """
    if not x_admin_token:
        raise HTTPException(status_code=401, detail="Admin token required")

    # ---- 1. Authenticate the request (token is either a session id or the password itself) ----
    from datetime import datetime, timezone
    is_session = False
    if x_admin_token in admin_sessions:
        session = admin_sessions[x_admin_token]
        try:
            expires_at = datetime.fromisoformat(session["expires_at"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) < expires_at:
                is_session = True
            else:
                del admin_sessions[x_admin_token]
        except Exception:
            pass

    stored_hash = await get_active_admin_hash(db)
    token_hash = hashlib.sha256(x_admin_token.encode()).hexdigest()

    if not is_session and token_hash != stored_hash:
        raise HTTPException(status_code=403, detail="Invalid admin token")

    # ---- 2. Verify current_password matches the saved password ----
    current_hash = hashlib.sha256(password_data.current_password.encode()).hexdigest()
    if current_hash != stored_hash:
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    # ---- 3. Validate + persist new password ----
    if len(password_data.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")

    new_hash = hashlib.sha256(password_data.new_password.encode()).hexdigest()
    await db.admin_settings.update_one(
        {"type": "password"},
        {"$set": {"hash": new_hash, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True
    )
    # Invalidate ALL existing admin sessions so anyone holding the old password
    # token (especially the env-seed default) is forced to re-authenticate.
    try:
        if hasattr(admin_sessions, "clear_all"):
            await admin_sessions.clear_all()
        else:
            for k in list(admin_sessions.keys()):
                del admin_sessions[k]
    except Exception:
        pass
    # Update the in-memory active-hash cache so EVERY verifier in this pod
    # immediately rejects the old/env password. No redeploy required.
    try:
        from services.admin_auth import set_active_admin_hash
        set_active_admin_hash(new_hash)
    except Exception:
        pass
    # Refresh the admin password cache used by verify_auth in products.py routes
    try:
        from routes import products as _products
        await _products._refresh_admin_pw_cache()
    except Exception:
        pass

    return {"success": True, "message": "Password changed successfully"}


# ==================== BLOG MANAGEMENT ====================

@router.get("/blogs")
async def get_all_blogs(admin: bool = Depends(verify_admin)):
    """Get all blogs (including drafts) for admin"""
    blogs = await db.blogs.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return blogs


@router.post("/blogs")
async def create_blog(blog_data: BlogCreate, admin: bool = Depends(verify_admin)):
    """Create a new blog post"""
    slug = generate_slug(blog_data.title)
    
    # Check if slug exists
    existing = await db.blogs.find_one({"slug": slug})
    if existing:
        slug = f"{slug}-{uuid.uuid4().hex[:6]}"
    
    now = datetime.now(timezone.utc).isoformat()
    blog_doc = {
        "id": str(uuid.uuid4()),
        "title": blog_data.title,
        "slug": slug,
        "meta_description": blog_data.meta_description,
        "content": blog_data.content,
        "keywords": blog_data.keywords,
        "status": blog_data.status,
        "language": blog_data.language,
        "view_count": 0,
        "generated_by": "Manual",
        "created_at": now,
        "updated_at": now
    }
    
    await db.blogs.insert_one(blog_doc)
    del blog_doc["_id"]
    return blog_doc


@router.put("/blogs/{blog_id}")
async def update_blog(blog_id: str, blog_data: BlogUpdate, admin: bool = Depends(verify_admin)):
    """Update an existing blog post"""
    blog = await db.blogs.find_one({"id": blog_id})
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found")
    
    update_data = {k: v for k, v in blog_data.model_dump().items() if v is not None}
    
    if "title" in update_data:
        update_data["slug"] = generate_slug(update_data["title"])
    
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.blogs.update_one({"id": blog_id}, {"$set": update_data})
    
    updated_blog = await db.blogs.find_one({"id": blog_id}, {"_id": 0})
    return updated_blog


@router.delete("/blogs/{blog_id}")
async def delete_blog(blog_id: str, admin: bool = Depends(verify_admin)):
    """Delete a blog post"""
    result = await db.blogs.delete_one({"id": blog_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Blog not found")
    return {"success": True, "message": "Blog deleted"}


@router.post("/blogs/{blog_id}/publish")
async def publish_blog(blog_id: str, admin: bool = Depends(verify_admin)):
    """Publish a draft blog post"""
    result = await db.blogs.update_one(
        {"id": blog_id},
        {"$set": {"status": "published", "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Blog not found")
    return {"success": True, "message": "Blog published"}


# ==================== LOCATION MANAGEMENT ====================

@router.get("/locations")
async def get_all_locations(admin: bool = Depends(verify_admin)):
    """Get all location pages for admin"""
    locations = await db.locations.find({}, {"_id": 0}).sort("created_at", -1).to_list(500)
    return locations


@router.post("/locations")
async def create_location(location_data: LocationCreate, admin: bool = Depends(verify_admin)):
    """Create a new location page"""
    # Generate slug
    slug = location_data.city.lower() if location_data.city else location_data.state.lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    
    # Check for existing
    query = {"state": {"$regex": f"^{location_data.state}$", "$options": "i"}}
    if location_data.city:
        query["city"] = {"$regex": f"^{location_data.city}$", "$options": "i"}
    
    existing = await db.locations.find_one(query)
    if existing:
        raise HTTPException(status_code=400, detail="Location already exists")
    
    now = datetime.now(timezone.utc).isoformat()
    location_doc = {
        "id": str(uuid.uuid4()),
        "state": location_data.state.title(),
        "city": location_data.city.title() if location_data.city else None,
        "slug": slug,
        "content": {
            "title": location_data.title,
            "description": location_data.description,
            "climate": location_data.climate,
            "skin_issues": location_data.skin_issues,
            "recommendations": location_data.recommendations
        },
        "view_count": 0,
        "created_at": now,
        "updated_at": now
    }
    
    await db.locations.insert_one(location_doc)
    del location_doc["_id"]
    return location_doc


@router.put("/locations/{location_id}")
async def update_location(location_id: str, location_data: LocationUpdate, admin: bool = Depends(verify_admin)):
    """Update an existing location page"""
    location = await db.locations.find_one({"id": location_id})
    if not location:
        raise HTTPException(status_code=404, detail="Location not found")
    
    update_data = {}
    content_update = {}
    
    for field in ["title", "description", "climate", "skin_issues", "recommendations"]:
        value = getattr(location_data, field, None)
        if value is not None:
            content_update[field] = value
    
    if content_update:
        update_data["content"] = {**location.get("content", {}), **content_update}
    
    update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
    
    await db.locations.update_one({"id": location_id}, {"$set": update_data})
    
    updated_location = await db.locations.find_one({"id": location_id}, {"_id": 0})
    return updated_location


@router.delete("/locations/{location_id}")
async def delete_location(location_id: str, admin: bool = Depends(verify_admin)):
    """Delete a location page"""
    result = await db.locations.delete_one({"id": location_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Location not found")
    return {"success": True, "message": "Location deleted"}


# ==================== ANALYTICS ====================

@router.get("/analytics/overview")
async def get_analytics_overview(admin: bool = Depends(verify_admin)):
    """Get analytics overview for admin dashboard"""
    total_orders = await db.orders.count_documents({})
    total_blogs = await db.blogs.count_documents({})
    published_blogs = await db.blogs.count_documents({"status": "published"})
    total_locations = await db.locations.count_documents({})

    # Add-to-cart clicks (product + combo adds, and legacy DOM-level "Add to Cart"
    # clicks) — feeds the dashboard "Add to Bag Clicks" card.
    add_to_cart_clicks = await db.tracking_events.count_documents({
        "$or": [
            {"action": "add_to_cart"},
            {"action": "add_combo"},
            {"action": "button_click", "data.button_type": "claim_offer"},
        ]
    })
    
    # Calculate revenue
    orders = await db.orders.find({}, {"amount": 1}).to_list(10000)
    total_revenue = sum(o.get("amount", 0) for o in orders)
    
    # Get recent orders
    recent_orders = await db.orders.find({}, {"_id": 0}).sort("created_at", -1).limit(5).to_list(5)
    
    # Get top blogs by views
    top_blogs = await db.blogs.find({"status": "published"}, {"_id": 0, "title": 1, "slug": 1, "view_count": 1}).sort("view_count", -1).limit(5).to_list(5)
    
    return {
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "total_blogs": total_blogs,
        "published_blogs": published_blogs,
        "draft_blogs": total_blogs - published_blogs,
        "total_locations": total_locations,
        "add_to_cart_clicks": add_to_cart_clicks,
        "recent_orders": recent_orders,
        "top_blogs": top_blogs
    }


@router.get("/orders")
async def get_all_orders(
    admin: bool = Depends(verify_admin),
    limit: int = 200,
    date_from: Optional[str] = None,  # ISO date YYYY-MM-DD
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    payment_method: Optional[str] = None,
):
    """Get all orders for admin with optional date/status/payment filters."""
    query = {}
    if date_from or date_to:
        date_q = {}
        if date_from:
            date_q["$gte"] = f"{date_from}T00:00:00"
        if date_to:
            date_q["$lte"] = f"{date_to}T23:59:59.999"
        query["created_at"] = date_q
    if status and status != "all":
        query["status"] = status
    if payment_method and payment_method != "all":
        query["payment_method"] = payment_method
    orders = await db.orders.find(query, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)
    return orders


@router.get("/orders/export")
async def export_orders(
    admin: bool = Depends(verify_admin),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    payment_method: Optional[str] = None,
    fmt: str = "csv",  # csv | xlsx
):
    """Export orders as CSV or XLSX with full customer + product + price detail."""
    from fastapi.responses import StreamingResponse
    import io
    import csv as _csv

    query = {}
    if date_from or date_to:
        date_q = {}
        if date_from:
            date_q["$gte"] = f"{date_from}T00:00:00"
        if date_to:
            date_q["$lte"] = f"{date_to}T23:59:59.999"
        query["created_at"] = date_q
    if status and status != "all":
        query["status"] = status
    if payment_method and payment_method != "all":
        query["payment_method"] = payment_method

    orders = await db.orders.find(query, {"_id": 0}).sort("created_at", -1).limit(10000).to_list(10000)

    headers = [
        "Order ID", "Date", "Status", "Customer Name", "Phone", "Email",
        "House/Building", "Area/Street", "City/State", "Pincode",
        "Products", "Item Count", "Payment Method", "Subtotal (MRP)",
        "Coupon", "Coupon Discount", "Total Paid", "AWB Number", "Provider", "Referral Used",
    ]

    def _row(o):
        items = o.get("items") or []
        # Each item may have shade_name/shade_id/quantity/price
        prod_str = " | ".join(
            f"{(it.get('short_name') or it.get('name') or it.get('slug') or '?')}"
            + (f" ({it.get('shade_name')})" if it.get('shade_name') else "")
            + f" x{it.get('quantity', 1)} @{it.get('price', 0)}"
            for it in items
        ) or "—"
        item_count = sum(int(it.get('quantity') or 1) for it in items) if items else 1
        mrp_total = sum(float(it.get('mrp', it.get('price', 0)) or 0) * int(it.get('quantity') or 1) for it in items)
        return [
            o.get("order_id", ""),
            (o.get("created_at") or "")[:19].replace("T", " "),
            o.get("status", ""),
            o.get("name", ""),
            o.get("phone", ""),
            o.get("email", ""),
            o.get("house_number", ""),
            o.get("area", ""),
            o.get("state", ""),
            o.get("pincode", ""),
            prod_str,
            item_count,
            o.get("payment_method", ""),
            f"{mrp_total:.2f}",
            o.get("coupon_code", ""),
            f"{float(o.get('coupon_discount') or 0):.2f}",
            f"{float(o.get('amount') or 0):.2f}",
            o.get("awb_number", ""),
            o.get("shipping_provider", ""),
            o.get("referral_code_used", ""),
        ]

    fname = f"celesta-orders-{(date_from or 'all')}_to_{(date_to or 'today')}"

    if fmt.lower() == "xlsx":
        try:
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "Orders"
            ws.append(headers)
            for o in orders:
                ws.append(_row(o))
            buf = io.BytesIO()
            wb.save(buf)
            buf.seek(0)
            return StreamingResponse(
                buf,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": f'attachment; filename="{fname}.xlsx"'},
            )
        except ImportError:
            pass  # fall through to CSV if openpyxl not installed

    buf = io.StringIO()
    writer = _csv.writer(buf)
    writer.writerow(headers)
    for o in orders:
        writer.writerow(_row(o))
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'},
    )


@router.get("/orders/daily-summary")
async def orders_daily_summary(admin: bool = Depends(verify_admin), days: int = 30):
    """Return per-day order stats (count, revenue, COD%) for the dashboard."""
    from datetime import timedelta as _td
    today = datetime.now(timezone.utc).date()
    out = []
    for i in range(days):
        d = today - _td(days=i)
        d_start = f"{d.isoformat()}T00:00:00"
        d_end = f"{d.isoformat()}T23:59:59.999"
        cursor = db.orders.find(
            {"created_at": {"$gte": d_start, "$lte": d_end}},
            {"_id": 0, "amount": 1, "payment_method": 1, "status": 1, "items": 1},
        )
        orders = await cursor.to_list(5000)
        count = len(orders)
        revenue = sum(float(o.get("amount") or 0) for o in orders)
        cod = sum(1 for o in orders if (o.get("payment_method") or "").upper() == "COD")
        item_count = sum(sum(int(it.get('quantity') or 1) for it in (o.get('items') or [])) or 1 for o in orders)
        out.append({
            "date": d.isoformat(),
            "orders": count,
            "revenue": round(revenue, 2),
            "cod_orders": cod,
            "cod_pct": round((cod / count * 100) if count else 0, 1),
            "items_sold": item_count,
        })
    out.reverse()
    return {"days": out, "total_orders": sum(d["orders"] for d in out), "total_revenue": round(sum(d["revenue"] for d in out), 2)}



# ==================== TAXONOMY ADMIN (Jan 2026 canonical reset) ====================

@router.post("/taxonomy/reset-canonical")
async def admin_reset_canonical_taxonomy(admin: bool = Depends(verify_admin)):
    """SYNCHRONOUS reset — only safe for small catalogs (<500 products).
    For production-scale catalogs (7k+), use POST /taxonomy/reset-canonical/start
    which returns a job_id immediately and runs in the background."""
    from services.taxonomy_canonical import (
        reset_canonical_taxonomy, reclassify_all_products, compute_product_tags
    )
    seeded = await reset_canonical_taxonomy(db)
    classified = await reclassify_all_products(db)
    tagged = await compute_product_tags(db)
    return {"seeded": seeded, "classified": classified, "tagged": tagged}


@router.post("/taxonomy/reset-canonical/start")
async def admin_reset_canonical_start(admin: bool = Depends(verify_admin)):
    """Kick off reset-canonical + reclassify + tags + flagship guard as a
    BACKGROUND task. Returns {job_id} immediately so the UI can render a
    progress bar by polling /taxonomy/job/{job_id}.

    Avoids the 60-second gateway timeout that breaks for 7k+ product catalogs.
    """
    import asyncio
    import uuid as _uuid
    from services.taxonomy_canonical import (
        reset_canonical_taxonomy, reclassify_all_products, compute_product_tags,
        _now,
    )

    job_id = _uuid.uuid4().hex
    total = await db.products.count_documents({})
    await db.taxonomy_jobs.insert_one({
        "_id": job_id,
        "stage": "queued",
        "processed": 0,
        "total": total,
        "percent": 0,
        "result": None,
        "error": None,
        "started_at": _now(),
        "updated_at": _now(),
    })

    async def _run():
        def _sanitize_none_keys(o):
            """Mongo rejects None as a document key. Convert recursively."""
            if isinstance(o, dict):
                return {("__null__" if k is None else str(k)): _sanitize_none_keys(v)
                        for k, v in o.items()}
            if isinstance(o, list):
                return [_sanitize_none_keys(v) for v in o]
            return o

        async def _safe_set(payload: dict):
            """Sanitized update wrapper — guarantees no None key ever reaches Mongo."""
            try:
                await db.taxonomy_jobs.update_one(
                    {"_id": job_id},
                    {"$set": _sanitize_none_keys({**payload, "updated_at": _now()})},
                )
            except Exception as e:
                import traceback as _tb
                logger.error(f"[taxonomy_job {job_id}] safe_set failed: {e}\n{_tb.format_exc()[-1000:]}")

        try:
            await _safe_set({"stage": "seeding"})
            seeded = await reset_canonical_taxonomy(db)
            seeded = _sanitize_none_keys(seeded)

            classified = await reclassify_all_products(db, job_id=job_id)
            classified = _sanitize_none_keys(classified)

            await _safe_set({"stage": "computing_tags"})
            tagged = await compute_product_tags(db)
            tagged = _sanitize_none_keys(tagged)

            # Flagship guard sweep (same as enforce-flagship-niche).
            await _safe_set({"stage": "flagship_guard"})
            scanned = demoted = kept = 0
            demoted_sample: list[dict] = []
            cur = db.products.find({"niche": "anti-aging"}, {
                "_id": 0, "slug": 1, "brand": 1, "name": 1, "category": 1
            })
            async for prod in cur:
                scanned += 1
                brand_text = (prod.get("brand") or "").lower()
                name_text = (prod.get("name") or "").lower()
                is_celesta = "celesta glow" in brand_text or "celesta glow" in name_text
                if is_celesta:
                    kept += 1
                    continue
                new_cat = prod.get("category") or "anti-aging-products"
                await db.products.update_one(
                    {"slug": prod["slug"]},
                    {"$set": {"niche": "skincare", "category": new_cat}},
                )
                demoted += 1
                if len(demoted_sample) < 25:
                    demoted_sample.append({
                        "slug": prod["slug"], "brand": prod.get("brand"),
                        "name": prod.get("name"), "new_category": new_cat,
                    })

            await _safe_set({
                "stage": "completed",
                "percent": 100,
                "result": {
                    "seeded": seeded,
                    "classified": classified,
                    "tagged": tagged,
                    "flagship": {
                        "scanned": scanned, "demoted": demoted,
                        "kept_celesta_glow": kept,
                        "demoted_sample": demoted_sample,
                    },
                },
                "finished_at": _now(),
            })
        except Exception as e:
            import traceback as _tb
            try:
                await db.taxonomy_jobs.update_one(
                    {"_id": job_id},
                    {"$set": {
                        "stage": "failed",
                        "error": f"{type(e).__name__}: {e}",
                        "trace": _tb.format_exc()[-2000:],
                        "updated_at": _now(),
                    }},
                )
            except Exception:
                logger.exception(f"[taxonomy_job {job_id}] could not record failure")

    asyncio.create_task(_run())
    return {"job_id": job_id, "stage": "queued", "total": total}


@router.get("/taxonomy/job/{job_id}")
async def admin_taxonomy_job_status(job_id: str, admin: bool = Depends(verify_admin)):
    """Poll status of a background taxonomy job started via reset-canonical/start."""
    doc = await db.taxonomy_jobs.find_one({"_id": job_id})
    if not doc:
        raise HTTPException(404, "Job not found")
    doc["job_id"] = doc.pop("_id")
    return doc


@router.post("/taxonomy/reclassify-products")
async def admin_reclassify_products(admin: bool = Depends(verify_admin)):
    """Re-link every product to concerns/categories/subcategories via keyword
    matching on name+description. Use after a bulk-import or admin edits."""
    from services.taxonomy_canonical import reclassify_all_products
    return await reclassify_all_products(db)


@router.post("/taxonomy/recompute-tags")
async def admin_recompute_tags(admin: bool = Depends(verify_admin)):
    """Re-compute filter tags (bestseller / luxury / trending / most_bought)."""
    from services.taxonomy_canonical import compute_product_tags
    return await compute_product_tags(db)


@router.post("/products/cleanup-bad-brands")
async def admin_cleanup_bad_brands(dry_run: bool = False, admin: bool = Depends(verify_admin)):
    """Repair bad brand values from bulk imports: sheet names ('Sheet27'),
    numeric / empty / 'nan' / 'null' strings. Extracts the real brand from
    the product name's first word(s) when a known brand prefix matches;
    otherwise sets brand=None. Pass dry_run=true to preview only."""
    from services.taxonomy_canonical import cleanup_bad_brands
    return await cleanup_bad_brands(db, dry_run=dry_run)


@router.post("/taxonomy/cleanup-empty")
async def admin_cleanup_empty_taxonomy(admin: bool = Depends(verify_admin)):
    """Auto-deactivate (sub)categories that have no products. Hides them from
    the Cosmetics/Skincare hub UIs without deleting them — reactivates when a
    product is added later via the same endpoint."""
    from services.taxonomy_canonical import cleanup_empty_taxonomy
    return await cleanup_empty_taxonomy(db)


@router.post("/products/dedupe")
async def admin_dedupe_products(dry_run: bool = False, admin: bool = Depends(verify_admin)):
    """Find products with identical names, keep the best one (most reviews +
    rating) and deactivate the rest. Pass `dry_run=true` to preview only."""
    from services.taxonomy_canonical import dedupe_products
    return await dedupe_products(db, dry_run=dry_run)


@router.post("/taxonomy/enforce-flagship-niche")
async def admin_enforce_flagship_niche(admin: bool = Depends(verify_admin)):
    """Anti-aging is the flagship Celesta Glow niche. This endpoint ENFORCES
    that rule on existing data:
      - Any product currently in `niche=anti-aging` whose brand is NOT
        'Celesta Glow' is demoted to `niche=skincare` and routed to the
        `anti-aging-products` category if it doesn't already have one.
      - Idempotent — safe to re-run any time.
    Returns: { scanned, demoted, kept, demoted_sample[] }
    """
    cur = db.products.find({"niche": "anti-aging"}, {
        "_id": 0, "slug": 1, "brand": 1, "name": 1, "category": 1
    })
    scanned = 0
    demoted = 0
    kept = 0
    sample: list[dict] = []
    async for prod in cur:
        scanned += 1
        brand_text = (prod.get("brand") or "").lower()
        name_text = (prod.get("name") or "").lower()
        is_celesta = "celesta glow" in brand_text or "celesta glow" in name_text
        if is_celesta:
            kept += 1
            continue
        new_cat = prod.get("category") or "anti-aging-products"
        await db.products.update_one(
            {"slug": prod["slug"]},
            {"$set": {"niche": "skincare", "category": new_cat}},
        )
        demoted += 1
        if len(sample) < 25:
            sample.append({
                "slug": prod["slug"], "brand": prod.get("brand"),
                "name": prod.get("name"), "new_category": new_cat,
            })
    # Refresh category product_count after the moves.
    from services.taxonomy_canonical import cleanup_empty_taxonomy
    cleanup = await cleanup_empty_taxonomy(db)
    return {
        "scanned": scanned, "demoted": demoted, "kept_celesta_glow": kept,
        "demoted_sample": sample, "cleanup": cleanup,
    }

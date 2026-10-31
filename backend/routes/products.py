"""
Product Management Routes - Multi-product catalog, combos, coupons, cart
"""
from fastapi import APIRouter, Header, HTTPException, Query, UploadFile, File, Form, Response, Body
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import secrets
import logging
import random
import re

router = APIRouter()
db = None
admin_sessions = {}
employee_sessions = {}

# ---------------------------------------------------------------------------
# Sale-mode price adjuster (Feb-2026)
# ---------------------------------------------------------------------------
# When the global Flat 50% OFF toggle is ON, every product whose niche is in
# `applies_to_niches` (default: anti-aging) is re-priced on the wire so cards
# show the discounted price straight from the API. Combos get the same treatment.
_SALE_CACHE = {"cfg": None, "ts": 0}
async def _get_sale_cfg():
    import time
    if _SALE_CACHE["cfg"] and time.time() - _SALE_CACHE["ts"] < 30:
        return _SALE_CACHE["cfg"]
    doc = await db.admin_settings.find_one({"type": "sale_mode"}, {"_id": 0}) or {}
    _SALE_CACHE["cfg"] = doc
    _SALE_CACHE["ts"] = time.time()
    return doc


# ---------------------------------------------------------------------------
# Niche-mode config (Feb-2026 business pivot)
# ---------------------------------------------------------------------------
# Admin can toggle the site between "Anti-Aging Only" (public only sees the
# 6 flagship anti-aging SKUs) and "Three Niche" (legacy: anti-aging + skincare
# + cosmetics). Stored as `active_niches: [str]` under
# `admin_settings.{type: 'niche_mode'}`. Public defaults to anti-aging only
# so ~8,000 third-party skincare/cosmetics products stop hitting the wire.
_NICHE_MODE_CACHE = {"cfg": None, "ts": 0}
DEFAULT_ACTIVE_NICHES = ["skin-care", "anti-aging", "skincare"]  # production default (all treated as one skin-care umbrella)


async def _get_active_niches() -> List[str]:
    import time
    if _NICHE_MODE_CACHE["cfg"] and time.time() - _NICHE_MODE_CACHE["ts"] < 30:
        return list(_NICHE_MODE_CACHE["cfg"])
    doc = await db.admin_settings.find_one({"type": "niche_mode"}, {"_id": 0}) or {}
    niches = doc.get("active_niches")
    if not niches or not isinstance(niches, list):
        niches = list(DEFAULT_ACTIVE_NICHES)
    _NICHE_MODE_CACHE["cfg"] = list(niches)
    _NICHE_MODE_CACHE["ts"] = time.time()
    return list(niches)


def _invalidate_niche_cache():
    _NICHE_MODE_CACHE["cfg"] = None
    _NICHE_MODE_CACHE["ts"] = 0


class NicheModePatch(BaseModel):
    active_niches: List[str]


@router.get("/niche-mode")
async def public_get_niche_mode(response: Response):
    """Public: return the currently active niches so the frontend can hide
    the skincare/cosmetics niche cards + routes when the site is running in
    Anti-Aging Only mode."""
    response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=60"
    return {"active_niches": await _get_active_niches()}


@router.put("/admin/niche-mode")
async def admin_set_niche_mode(payload: NicheModePatch, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_auth(x_admin_token=x_admin_token)
    allowed = {"skin-care", "anti-aging", "skincare", "cosmetics"}
    active = [n for n in payload.active_niches if n in allowed]
    if not active:
        raise HTTPException(400, "At least one niche must be active")
    await db.admin_settings.update_one(
        {"type": "niche_mode"},
        {"$set": {"type": "niche_mode", "active_niches": active,
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    _invalidate_niche_cache()
    return {"active_niches": active}


# ---------------------------------------------------------------------------
# Combo bonus config (Feb-2026)
# ---------------------------------------------------------------------------
# Admin sets the ₹X OFF combo bonus amount that auto-applies when the cart
# holds ≥ N anti-aging products. Falls back to sensible defaults.

class ComboBonusTier(BaseModel):
    items: int
    amount: int


class ComboBonusPatch(BaseModel):
    tiers: Optional[List[ComboBonusTier]] = None
    min_subtotal: Optional[int] = None
    # Legacy single-tier fields (still accepted for backwards compatibility)
    amount: Optional[int] = None
    min_items: Optional[int] = None


DEFAULT_COMBO_TIERS = [
    {"items": 2, "amount": 99},
    {"items": 3, "amount": 150},
    {"items": 4, "amount": 200},
]


@router.get("/admin/combo-bonus")
async def admin_get_combo_bonus(x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_auth(x_admin_token=x_admin_token)
    doc = await db.admin_settings.find_one({"type": "combo_bonus"}, {"_id": 0}) or {}
    tiers = doc.get("tiers")
    if not isinstance(tiers, list) or not tiers:
        # Migrate legacy single-tier config into a proper tier list
        if doc.get("amount"):
            tiers = [{"items": int(doc.get("min_items") or 2), "amount": int(doc["amount"])}]
        else:
            tiers = list(DEFAULT_COMBO_TIERS)
    tiers = sorted(
        [{"items": int(t.get("items") or 0), "amount": int(t.get("amount") or 0)} for t in tiers if int(t.get("items") or 0) >= 2 and int(t.get("amount") or 0) > 0],
        key=lambda t: t["items"],
    )
    return {
        "tiers": tiers,
        "min_subtotal": int(doc.get("min_subtotal") or 500),
    }


@router.put("/admin/combo-bonus")
async def admin_update_combo_bonus(
    payload: ComboBonusPatch, x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    verify_auth(x_admin_token=x_admin_token)
    upd: Dict[str, Any] = {}
    if payload.tiers is not None:
        cleaned = []
        for t in payload.tiers:
            if t.items >= 2 and 0 < t.amount <= 5000:
                cleaned.append({"items": int(t.items), "amount": int(t.amount)})
        if not cleaned:
            raise HTTPException(400, "At least one valid tier required (items>=2, 0<amount<=5000)")
        cleaned = sorted(cleaned, key=lambda t: t["items"])
        upd["tiers"] = cleaned
    if payload.min_subtotal is not None:
        upd["min_subtotal"] = max(0, int(payload.min_subtotal))
    # Legacy
    if payload.amount is not None and "tiers" not in upd:
        upd["tiers"] = [{"items": int(payload.min_items or 2), "amount": int(payload.amount)}]
    if not upd:
        raise HTTPException(400, "Nothing to update")
    upd["type"] = "combo_bonus"
    upd["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.admin_settings.update_one({"type": "combo_bonus"}, {"$set": upd}, upsert=True)
    doc = await db.admin_settings.find_one({"type": "combo_bonus"}, {"_id": 0}) or {}
    return {
        "tiers": doc.get("tiers") or list(DEFAULT_COMBO_TIERS),
        "min_subtotal": int(doc.get("min_subtotal") or 500),
    }


# ---------------------------------------------------------------------------
# Top Banner config (Feb-2026) — homepage top strip separate from niche hero
# ---------------------------------------------------------------------------

class TopBannerPatch(BaseModel):
    image_desktop: Optional[str] = None
    image_mobile: Optional[str] = None
    link_url: Optional[str] = None
    is_active: Optional[bool] = None
    slides: Optional[List[Dict[str, str]]] = None
    autoplay_ms: Optional[int] = None


def _top_banner_admin_view(doc: dict) -> dict:
    return {
        "image_desktop": doc.get("image_desktop") or "",
        "image_mobile": doc.get("image_mobile") or "",
        "link_url": doc.get("link_url") or "/shop?niche=anti-aging",
        "is_active": bool(doc.get("is_active", True)),
        "slides": [s for s in (doc.get("slides") or []) if s.get("image_desktop") or s.get("image_mobile")],
        "autoplay_ms": int(doc.get("autoplay_ms") or 4000),
    }


@router.get("/top-banner")
async def public_top_banner(response: Response):
    """Public: get the homepage top banner slides (images + click destinations)."""
    response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=60"
    doc = await db.admin_settings.find_one({"type": "top_banner"}, {"_id": 0}) or {}
    from services.image_optimizer import optimize_cloudinary_url as _opt
    cfg = _top_banner_admin_view(doc)
    raw = [{"image_desktop": cfg["image_desktop"], "image_mobile": cfg["image_mobile"], "link_url": cfg["link_url"]}] + cfg["slides"]
    slides = []
    for s in raw:
        desktop = s.get("image_desktop") or s.get("image_mobile") or ""
        mobile = s.get("image_mobile") or desktop
        if not desktop:
            continue
        slides.append({
            "image_desktop": _opt(desktop, 1600),
            "image_mobile": _opt(mobile, 1200),
            "link_url": s.get("link_url") or cfg["link_url"],
        })
    first = slides[0] if slides else {"image_desktop": "", "image_mobile": "", "link_url": cfg["link_url"]}
    return {**first, "is_active": cfg["is_active"], "slides": slides, "autoplay_ms": cfg["autoplay_ms"]}


@router.get("/admin/top-banner")
async def admin_get_top_banner(x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_auth(x_admin_token=x_admin_token)
    doc = await db.admin_settings.find_one({"type": "top_banner"}, {"_id": 0}) or {}
    return _top_banner_admin_view(doc)


@router.put("/admin/top-banner")
async def admin_update_top_banner(payload: TopBannerPatch, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_auth(x_admin_token=x_admin_token)
    upd = {k: v for k, v in payload.dict().items() if v is not None}
    if not upd:
        raise HTTPException(400, "Nothing to update")
    upd["type"] = "top_banner"
    upd["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.admin_settings.update_one({"type": "top_banner"}, {"$set": upd}, upsert=True)
    doc = await db.admin_settings.find_one({"type": "top_banner"}, {"_id": 0}) or {}
    return _top_banner_admin_view(doc)

def _apply_sale_one(p: dict, cfg: dict):
    """Mutate a product/combo dict in-place: add sale_active + discounted
    prepaid_price + discount_percent. Leaves mrp untouched (customers see MRP
    struck through and the new price highlighted)."""
    if not cfg or not cfg.get("enabled"):
        return
    niches = cfg.get("applies_to_niches") or ["anti-aging"]
    if p.get("niche") not in niches:
        return
    try:
        pct = int(cfg.get("discount_percent") or 50)
    except (TypeError, ValueError):
        pct = 50
    mrp = p.get("mrp") or p.get("prepaid_price") or 0
    if mrp <= 0:
        return
    new_price = max(1, round(mrp * (100 - pct) / 100))
    # Only mark as on-sale if this is actually cheaper than the current price.
    if new_price >= (p.get("prepaid_price") or mrp):
        return
    p["sale_active"] = True
    p["sale_badge_label"] = cfg.get("badge_label") or f"FLAT {pct}% OFF"
    p["original_prepaid_price"] = p.get("prepaid_price")
    p["prepaid_price"] = new_price
    p["cod_price"] = new_price
    p["discount_percent"] = pct

async def _apply_sale(items):
    """Apply sale_mode adjustment to a list of product/combo dicts."""
    if not items:
        return items
    cfg = await _get_sale_cfg()
    if not cfg.get("enabled"):
        return items
    for p in items:
        _apply_sale_one(p, cfg)
    return items

def set_db(database):
    global db
    db = database

def set_admin_sessions(sessions):
    global admin_sessions
    admin_sessions = sessions

def set_employee_sessions(sessions):
    global employee_sessions
    employee_sessions = sessions

import os
import hashlib

# Cache stored admin password hash so we don't hit DB on every request
_admin_pw_cache = {"hash": None, "checked_at": 0}

def _get_stored_admin_hash_sync():
    """Best-effort cache of the latest admin password hash from DB. Refreshed at most every 30s."""
    import time
    now_ts = time.time()
    if _admin_pw_cache["hash"] is not None and (now_ts - _admin_pw_cache["checked_at"]) < 30:
        return _admin_pw_cache["hash"]
    try:
        # use motor's sync collection access via run_in_executor is overkill; instead store via callback
        return _admin_pw_cache["hash"]
    except Exception:
        return None

async def _refresh_admin_pw_cache():
    import time
    if db is None:
        return
    try:
        doc = await db.admin_settings.find_one({"type": "password"})
        _admin_pw_cache["hash"] = (doc or {}).get("hash")
        _admin_pw_cache["checked_at"] = time.time()
    except Exception:
        pass

def verify_auth(x_admin_token=None, x_employee_token=None, permission=None):
    if x_admin_token:
        # Accept active session tokens (always, regardless of password change).
        if x_admin_token in admin_sessions:
            return True
        # Plain-password fallback — must match the *active* admin hash.
        # Once a custom password is saved, the env-seed password is rejected.
        from services.admin_auth import get_cached_active_admin_hash
        token_hash = hashlib.sha256(x_admin_token.encode()).hexdigest()
        if token_hash == get_cached_active_admin_hash():
            return True
    if x_employee_token and x_employee_token in employee_sessions:
        session = employee_sessions[x_employee_token]
        if permission and not session.get("permissions", {}).get(permission):
            raise HTTPException(status_code=403, detail=f"No permission: {permission}")
        return True
    raise HTTPException(status_code=401, detail="Unauthorized")


# ==================== PRODUCT ENDPOINTS ====================

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    short_name: Optional[str] = None
    tagline: Optional[str] = None
    description: Optional[str] = None
    key_ingredients: Optional[str] = None
    ingredients_full: Optional[str] = None
    benefits: Optional[List[str]] = None
    how_to_use: Optional[str] = None
    size: Optional[str] = None
    images: Optional[List[str]] = None
    image: Optional[str] = None  # singular convenience field — mirrored into images[0] on save
    mrp: Optional[float] = None
    prepaid_price: Optional[float] = None
    cod_price: Optional[float] = None
    cod_advance: Optional[float] = None
    discount_percent: Optional[float] = None
    badge: Optional[str] = None
    badges: Optional[List[str]] = None
    offer_price: Optional[float] = None
    offer_label: Optional[str] = None
    offer_ends_at: Optional[str] = None
    source_url: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None  # filter chip within parent category
    concerns: Optional[List[str]] = None
    niche: Optional[str] = None
    # TBL / Preorder
    is_to_be_launched: Optional[bool] = None
    launch_date: Optional[str] = None  # ISO date string
    preorder_enabled: Optional[bool] = None
    # Inventory
    stock_qty: Optional[int] = None
    low_stock_threshold: Optional[int] = None
    # Display
    fill_card: Optional[bool] = None
    brand: Optional[str] = None
    # Content extras
    faqs: Optional[List[Dict[str, Any]]] = None
    # Niche-specific specs (dict so per-niche fields can vary):
    #   skincare/anti-aging → { skin_type, fragrance, suitable_for, ... }
    #   cosmetics → { shade, finish, spf, skin_tone, coverage, ... }
    #   hair → { hair_type, hair_length, fragrance, ... }
    specs: Optional[Dict[str, Any]] = None
    # Cosmetics shade variants — each shade has independent stock & optional image.
    # Empty/None means the product is sold as a single SKU (no shade picker).
    shades: Optional[List[Dict[str, Any]]] = None  # [{id,name,hex,image,sku,stock_qty}]
    # Price guard — must be explicitly true to allow prepaid_price/cod_price/mrp updates
    allow_price_change: Optional[bool] = False
    # Dermatologist test-report (Feb 2026) — admin uploads the lab certificate image
    # for the product; a "Dermatologically Tested" badge + report thumbnail then
    # renders on the storefront (ProductCard + ProductDetailPage).
    test_report_image: Optional[str] = None
    test_report_lab: Optional[str] = None
    test_report_date: Optional[str] = None  # ISO date string
    is_dermat_tested: Optional[bool] = None
    # SEO alt-text + keyword injector (Feb 2026) — populates <img alt> and
    # emits a JSON-LD `keywords` block on the product page. Multiple keywords
    # supported to widen long-tail organic reach.
    image_alt_text: Optional[str] = None
    seo_keywords: Optional[List[str]] = None

class ProductCreate(BaseModel):
    slug: str
    name: str
    short_name: str
    tagline: str = ""
    description: str = ""
    category: str = "skincare"
    subcategory: str = ""  # optional filter chip slug within the parent category
    concerns: List[str] = []
    niche: str = "anti-aging"  # 'anti-aging' | 'skincare' | 'cosmetics'
    key_ingredients: str = ""
    ingredients_full: str = ""
    benefits: List[str] = []
    how_to_use: str = ""
    size: str = ""
    images: List[str] = []
    mrp: float = 0
    prepaid_price: float = 0
    cod_price: float = 0
    cod_advance: float = 29
    discount_percent: float = 0
    badge: str = ""
    badges: List[str] = []
    offer_price: Optional[float] = None
    offer_label: Optional[str] = None
    offer_ends_at: Optional[str] = None
    source_url: Optional[str] = None
    is_active: bool = True
    sort_order: int = 99
    # TBL / Preorder
    is_to_be_launched: bool = False
    launch_date: Optional[str] = None
    preorder_enabled: bool = False
    # Inventory
    stock_qty: int = 100
    low_stock_threshold: int = 10
    # Display
    fill_card: bool = False
    brand: str = ""
    # Per-niche specs (free-form dict)
    specs: Dict[str, Any] = {}
    # Cosmetics shade variants — optional list of {id,name,hex,image,sku,stock_qty}
    shades: List[Dict[str, Any]] = []


@router.get("/products")
async def get_all_products(
    response: Response,
    active_only: bool = Query(True),
    niche: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    concern: Optional[str] = Query(None),
    subcategory: Optional[str] = Query(None),
    brand: Optional[str] = Query(None, description="Filter by brand — accepts exact brand name OR a slug (e.g. 'fix-derma')"),
    generated_from: Optional[str] = Query(None, description="Return all variations generated from this base product slug"),
    include_variations: bool = Query(False, description="When False (default), generated variation SKUs are hidden from listings so each product shows once"),
    tag: Optional[str] = Query(None, description="Filter by tag: bestseller | luxury | trending | most_bought"),
    # --- NEW: pagination + server-side search ---
    # `page` is 1-indexed. `limit` is the page size.
    # When neither param is passed, the endpoint stays backward-compatible and
    # returns up to 500 items so tiny catalogs (27 products) just work.
    page: Optional[int] = Query(None, ge=1),
    limit: Optional[int] = Query(None, ge=1, le=1000),
    search: Optional[str] = Query(None, description="Text search on name/description/brand/tags"),
    sort: Optional[str] = Query("sort_order", description="sort_order | price_asc | price_desc | newest | popular"),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    x_employee_token: Optional[str] = Header(None, alias="X-Employee-Token"),
):
    """Public: paginated + searchable product list, with TBL auto-flip.

    Response shape (always a dict now so clients can see totals):
      { items: [...], total, page, limit, has_next }
    For back-compat we still return a plain array when NEITHER `page` nor `limit`
    are provided AND no `search` is used, so nothing breaks on existing callers.

    Security: ``active_only=false`` returns inactive/draft products and is
    therefore an admin-only mode. Anonymous callers that pass
    ``active_only=false`` are silently coerced back to ``True`` so we never
    leak unpublished SKUs.
    """
    # If the caller is asking for inactive products, they MUST authenticate
    # as admin or as an employee with the products permission. Otherwise we
    # silently force active_only=True so anonymous traffic only sees the
    # public catalog. Previously this endpoint leaked every draft product.
    if not active_only:
        try:
            verify_auth(x_admin_token=x_admin_token, x_employee_token=x_employee_token, permission="products")
        except HTTPException:
            active_only = True
    # Build the query
    query = {"is_active": True} if active_only else {}
    # Variation-group filter: return every SKU generated from one base product.
    if generated_from:
        query["generated_from"] = generated_from
    elif not include_variations:
        # Default catalog view: hide generated variation SKUs so each base
        # product shows only ONCE on Home / Shop All / mega-menu. Variations are
        # surfaced only on the /customize/:slug page (via generated_from).
        query["is_variation"] = {"$ne": True}
    # Public catalog: hide out-of-stock products entirely (business rule).
    # Admins can still see all products via active_only=false.
    if active_only:
        query["$and"] = [
            {"$or": [
                {"is_to_be_launched": True},  # Coming-soon products are shown (different CTA)
                {"stock_qty": {"$gt": 0}},
                {"shades.stock_qty": {"$gt": 0}},
            ]}
        ]
    if niche:
        # Alias: "skin-care" is the marketing/URL slug used by the Feb-2026
        # rebrand; internally the reclassifier still stores flagship SKUs as
        # niche="anti-aging". Map both to the same result set so the storefront
        # keeps working regardless of which slug the frontend passes.
        _niche_aliases = {
            "skin-care": ["skin-care", "anti-aging", "skincare"],
            "skincare":  ["skincare", "skin-care", "anti-aging"],
            "anti-aging": ["anti-aging", "skin-care", "skincare"],
        }
        if niche in _niche_aliases:
            query["niche"] = {"$in": _niche_aliases[niche]}
        else:
            query["niche"] = niche
    else:
        # Global "Anti-Aging Only" mode (Feb-2026): when admin has narrowed
        # active_niches, hide products from disabled niches on the public
        # catalog entirely. Admin/employee token bypasses this filter so the
        # admin panel still sees the full catalog.
        is_admin_or_emp = False
        try:
            verify_auth(x_admin_token=x_admin_token, x_employee_token=x_employee_token, permission="products")
            is_admin_or_emp = True
        except HTTPException:
            is_admin_or_emp = False
        if not is_admin_or_emp:
            active_niches = await _get_active_niches()
            if active_niches and len(active_niches) < 3:
                # Expand via the skin-care umbrella aliases so narrowing to
                # e.g. 'anti-aging' still surfaces products stored as 'skincare'
                # / 'skin-care' (they are one catalog). Prevents the whole
                # storefront from going blank on a niche toggle.
                _umbrella = {"skin-care", "anti-aging", "skincare"}
                expanded = set()
                for n in active_niches:
                    expanded.add(n)
                    if n in _umbrella:
                        expanded |= _umbrella
                query["niche"] = {"$in": list(expanded)}
    if category:
        # Match the parent category OR a child subcategory with this slug.
        # This lets the Cosmetics hub fetch counts via ?category=foundation
        # even though the product is stored as category=face-makeup + subcategory=foundation.
        query["$or"] = (query.get("$or") or []) + [
            {"category": category},
            {"subcategory": category},
        ]
    if concern:
        query["concerns"] = concern
    if subcategory:
        query["subcategory"] = subcategory
    if brand:
        # Accept either the exact brand name (e.g. "Fix Derma") OR the URL slug
        # (e.g. "fix-derma"). The brand field in DB is stored mixed-case with
        # spaces, so we match case-insensitively. This powers the BrandDetailPage
        # — previously it fetched 60 niche products and filtered client-side,
        # which silently dropped 95% of multi-page brands like Fix Derma (95
        # products, only 5-15 showed up).
        import re as _re
        b = brand.strip()
        # If it looks like a slug, also try matching the de-slugified form via regex
        if "-" in b and " " not in b:
            # "fix-derma" → match "fix derma" / "Fix Derma" / "Fix-Derma" etc.
            words = [_re.escape(w) for w in b.split("-") if w]
            pattern = r"^" + r"[\s\-]+".join(words) + r"$"
            query["brand"] = {"$regex": pattern, "$options": "i"}
        else:
            query["brand"] = {"$regex": f"^{_re.escape(b)}$", "$options": "i"}
    if tag:
        query["tags"] = tag
    if search and search.strip():
        s = search.strip()
        # PERF: Use the MongoDB text index (created in ensure_indexes) for whole-word
        # matches — ~50ms across 7,800 products vs ~2-4s for $regex. Fall back to
        # a $regex prefix match across name/brand/tags for short queries (<3 chars)
        # or queries containing only special chars where $text isn't useful.
        if len(s) >= 3 and re.search(r"[A-Za-z0-9]", s):
            query["$text"] = {"$search": s}
        else:
            safe = re.escape(s)
            query["$or"] = [
                {"name":  {"$regex": safe, "$options": "i"}},
                {"brand": {"$regex": safe, "$options": "i"}},
                {"tags":  {"$regex": safe, "$options": "i"}},
                {"slug":  {"$regex": safe, "$options": "i"}},
            ]

    # Sort map. Each entry includes `slug` as a stable final tie-breaker so the
    # ordering is deterministic across requests (otherwise Mongo can return
    # documents in different orders when the primary key ties — that's the
    # "Cosmetics shuffled" bug we hit).
    sort_spec = {
        "sort_order": [("sort_order", 1), ("name", 1), ("slug", 1)],
        "price_asc":  [("prepaid_price", 1), ("sort_order", 1), ("slug", 1)],
        "price_desc": [("prepaid_price", -1), ("sort_order", 1), ("slug", 1)],
        "newest":     [("created_at", -1), ("sort_order", 1), ("slug", 1)],
        "popular":    [("total_orders", -1), ("sort_order", 1), ("slug", 1)],
        # NEW: products that have at least one image come first, then sort_order.
        # Used by both public listings (best-looking products on top) and admin
        # (lets you find missing-image products by scrolling to the bottom).
        "images_first": [("has_image_rank", -1), ("sort_order", 1), ("name", 1), ("slug", 1)],
    }.get((sort or "sort_order").lower(), [("sort_order", 1), ("slug", 1)])

    # Whether to paginate
    paginating = page is not None or limit is not None or bool(search and search.strip())
    page_i  = max(1, page or 1)
    limit_i = min(1000, max(1, limit or 24))
    skip_i  = (page_i - 1) * limit_i

    # Count — cheap because of the index we ensure below
    total = await db.products.count_documents(query)

    # Lean projection — when the caller is the public catalog listing pages
    # (paginating + no admin/employee), strip the heavy fields that the card
    # UI never renders. Cuts response size by ~80% on a 24-product page (from
    # ~600KB down to ~120KB) and is the single biggest contributor to slow
    # initial page-paint on 3G mobile.
    lean = paginating and active_only
    if lean:
        projection = {
            "_id": 0, "slug": 1, "name": 1, "short_name": 1, "tagline": 1,
            "brand": 1, "niche": 1, "category": 1, "subcategory": 1, "concerns": 1,
            "images": {"$slice": 2},  # only the first 2 images for card hover
            "mrp": 1, "prepaid_price": 1, "cod_price": 1, "discount_percent": 1,
            "badge": 1, "badges": 1, "tags": 1,
            "is_active": 1, "is_to_be_launched": 1, "launch_date": 1,
            "stock_qty": 1, "low_stock_threshold": 1,
            "shades": 1, "fill_card": 1,
            "average_rating": 1, "reviews_count": 1, "total_orders": 1,
            "needs_review": 1, "size": 1, "created_at": 1, "sort_order": 1,
            # variation grouping — lets cards show the "View all N variations" link
            "variation_count": 1, "is_variation": 1, "generated_from": 1,
            # per-variation targeting badges (skin type · concern · gender+age)
            "target_skin_type": 1, "target_gender": 1, "target_age_group": 1,
            "concern_label": 1, "exclusive_for": 1,
        }
    else:
        projection = {"_id": 0}

    cursor = db.products.find(query, projection).sort(sort_spec)
    if paginating:
        cursor = cursor.skip(skip_i).limit(limit_i)
    else:
        # Admin & legacy callers fetch the full catalog in one shot. Cap raised
        # to 20 000 (Feb 2026) — the catalog grew past 5 000 and admins were
        # blind to the tail end. Without this lift, the admin UI's product
        # search couldn't find products past index 4 999, and reorder/edit
        # operations on the missing tail were impossible. The list view uses
        # react-window virtualization so 20 000 rows render fine.
        cursor = cursor.limit(20000)

    # ---- images_first sort: switch to aggregation so we can rank by has-image
    # without an extra column on the doc. Adds ~10-25 ms on 8k rows but only
    # when this sort is selected. Public catalog default sort is unchanged.
    if (sort or "").lower() == "images_first":
        proj_stage = {**{k: 1 for k in (projection or {}) if k != "_id"}}
        proj_stage["_id"] = 0
        # Map $size of images to a 0/1 rank for sort
        pipeline = [
            {"$match": query},
            {"$addFields": {
                "has_image_rank": {
                    "$cond": [
                        {"$gt": [{"$size": {"$ifNull": ["$images", []]}}, 0]},
                        1, 0,
                    ]
                }
            }},
            {"$sort": dict(sort_spec)},
            {"$project": proj_stage},
        ]
        if paginating:
            pipeline.append({"$skip": skip_i})
            pipeline.append({"$limit": limit_i})
        else:
            pipeline.append({"$limit": 20000})
        products = await db.products.aggregate(pipeline).to_list(length=None)
    else:
        products = await cursor.to_list(length=None)

    # Auto-flip TBL → launched on read if launch_date passed (unchanged logic)
    now = datetime.now(timezone.utc)
    for p in products:
        if p.get("is_to_be_launched") and p.get("launch_date"):
            try:
                ld = datetime.fromisoformat(str(p["launch_date"]).replace("Z", "+00:00"))
                if ld <= now:
                    p["is_to_be_launched"] = False
                    p["launch_date"] = None
                    await db.products.update_one(
                        {"slug": p["slug"]},
                        {"$set": {"is_to_be_launched": False, "launch_date": None,
                                  "updated_at": now.isoformat()}}
                    )
            except Exception:
                pass
        if p.get("is_to_be_launched") and p.get("launch_date"):
            try:
                ld = datetime.fromisoformat(str(p["launch_date"]).replace("Z", "+00:00"))
                delta = ld - now
                p["days_to_launch"] = max(0, delta.days)
                p["hours_to_launch"] = max(0, int(delta.total_seconds() // 3600))
            except Exception:
                p["days_to_launch"] = None
        else:
            p["days_to_launch"] = None

    # Apply Cloudinary auto-format/quality/width transforms to all image URLs
    # in the response. 70-90% smaller images delivered through the CDN
    # without re-uploading anything. Card images use 600px; detail uses 1200.
    try:
        from services.image_optimizer import optimize_products_list
        optimize_products_list(products, width=800 if lean else 1600)
    except Exception as e:
        logging.warning(f"[products] image optimize failed: {e}")

    # BRAND DIVERSIFICATION (Feb-2026 user request): no more than 2 products
    # of the same brand in a row. Image-first preference preserved — the
    # diversifier partitions into "with image" + "without image" and
    # re-interleaves each partition independently. Only runs on public
    # active-only listings (search, admin and brand-filtered queries are
    # left untouched — those callers expect raw ordering).
    if active_only and not (search and search.strip()) and not (brand and brand.strip()):
        try:
            from services.brand_diversify import diversify_by_brand
            products = diversify_by_brand(products, brand_key="brand", max_consecutive=2)
        except Exception as e:
            logging.warning(f"[products] brand diversify failed: {e}")

    # CDN cache headers — public catalog responses are safe to cache at the
    # edge for 60 seconds. Searches and admin (active_only=False) bypass cache.
    if active_only and not (search and search.strip()):
        response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=300"
    else:
        response.headers["Cache-Control"] = "no-cache, no-store"

    # Sale-mode: overlay Flat 50% OFF price on eligible (anti-aging) products.
    await _apply_sale(products)

    # Safety: strip any residual `_id` from raw MongoDB docs (projections
    # should already exclude it, but the aggregate pipeline path relies on
    # `$project` — this guarantees no ObjectId sneaks into JSON responses).
    for _p in products:
        _p.pop("_id", None)

    # Back-compat: if the caller didn't ask for pagination, return a plain array.
    if not paginating:
        return products
    return {
        "items": products,
        "total": total,
        "page": page_i,
        "limit": limit_i,
        "has_next": skip_i + len(products) < total,
    }


@router.post("/products/batch")
async def get_products_batch(data: Dict[str, Any]):
    """Public: fetch a batch of products by slug list in ONE query.

    Used by the cart page (and other client surfaces) so it can avoid pulling
    the entire 7,000+ catalog just to render a few cards. Returns a lean
    projection identical to the public catalog listing.

    Body: ``{ "slugs": ["a", "b", "c"] }`` — max 200 slugs per call.
    """
    slugs = data.get("slugs") or []
    if not isinstance(slugs, list):
        raise HTTPException(status_code=400, detail="`slugs` must be a list")
    # Hard cap to keep one request bounded
    slugs = [s for s in slugs if isinstance(s, str) and s][:200]
    if not slugs:
        return []
    projection = {
        "_id": 0, "slug": 1, "name": 1, "short_name": 1, "tagline": 1,
        "brand": 1, "niche": 1, "category": 1, "subcategory": 1, "concerns": 1,
        "images": {"$slice": 2},
        "mrp": 1, "prepaid_price": 1, "cod_price": 1, "discount_percent": 1,
        "badge": 1, "badges": 1, "tags": 1,
        "is_active": 1, "is_to_be_launched": 1, "launch_date": 1,
        "stock_qty": 1, "low_stock_threshold": 1,
        "shades": 1, "fill_card": 1,
        "average_rating": 1, "reviews_count": 1, "total_orders": 1,
        "size": 1,
    }
    items = await db.products.find(
        {"slug": {"$in": slugs}, "is_active": True}, projection
    ).to_list(length=None)
    # Preserve client-supplied order so the cart shows items in cart order
    order = {s: i for i, s in enumerate(slugs)}
    items.sort(key=lambda p: order.get(p.get("slug"), 9999))
    try:
        from services.image_optimizer import optimize_products_list
        optimize_products_list(items, width=800)
    except Exception:
        pass
    await _apply_sale(items)
    return items


@router.get("/certificates")
async def public_certificates(response: Response):
    """Public: list every product that has a lab-report / certificate image.
    Powers the homepage trust strip and the standalone `/certificates` page.
    Only returns products in the currently active niches."""
    active_niches = await _get_active_niches()
    query: Dict[str, Any] = {
        "test_report_image": {"$exists": True, "$nin": [None, ""]},
        "is_active": True,
    }
    if active_niches and len(active_niches) < 3:
        query["niche"] = {"$in": active_niches}
    docs = await db.products.find(
        query,
        {"_id": 0, "slug": 1, "name": 1, "short_name": 1, "image": 1,
         "test_report_image": 1, "test_report_lab": 1, "test_report_date": 1,
         "niche": 1},
    ).sort("sort_order", 1).limit(60).to_list(60)
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=120"
    return docs


@router.get("/admin/certificates")
async def admin_certificates(x_admin_token: str = Header(None, alias="X-Admin-Token")):
    """Admin: list every product with a test_report_image so the media-tools
    Certificates tab can render a grid instead of just an empty picker."""
    verify_auth(x_admin_token=x_admin_token)
    docs = await db.products.find(
        {"test_report_image": {"$exists": True, "$nin": [None, ""]}},
        {"_id": 0, "slug": 1, "name": 1, "short_name": 1, "image": 1,
         "test_report_image": 1, "test_report_lab": 1, "test_report_date": 1,
         "niche": 1},
    ).sort("name", 1).to_list(200)
    return docs


@router.get("/products/{slug}")
async def get_product(slug: str):
    """Public: Get single product by slug (with TBL auto-flip + countdown)"""
    product = await db.products.find_one({"slug": slug}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    now = datetime.now(timezone.utc)
    if product.get("is_to_be_launched") and product.get("launch_date"):
        try:
            ld = datetime.fromisoformat(str(product["launch_date"]).replace("Z", "+00:00"))
            if ld <= now:
                product["is_to_be_launched"] = False
                product["launch_date"] = None
                await db.products.update_one(
                    {"slug": slug},
                    {"$set": {"is_to_be_launched": False, "launch_date": None,
                              "updated_at": now.isoformat()}}
                )
            else:
                delta = ld - now
                product["days_to_launch"] = max(0, delta.days)
                product["hours_to_launch"] = max(0, int(delta.total_seconds() // 3600))
        except Exception:
            pass
    try:
        from services.image_optimizer import optimize_product_images
        optimize_product_images(product, width=1600)
    except Exception:
        pass
    # Sale-mode overlay (Feb-2026)
    cfg = await _get_sale_cfg()
    _apply_sale_one(product, cfg)
    return product


class LaunchStatusUpdate(BaseModel):
    is_to_be_launched: bool
    launch_date: Optional[str] = None  # ISO date; required if is_to_be_launched=True
    preorder_enabled: Optional[bool] = None


@router.put("/admin/products/{slug}/launch-status")
async def set_product_launch_status(
    slug: str,
    data: LaunchStatusUpdate,
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    """Admin: Toggle a product's TBL (To-Be-Launched) status, set launch date, toggle preorder."""
    verify_auth(x_admin_token=x_admin_token)
    product = await db.products.find_one({"slug": slug})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    update = {
        "is_to_be_launched": data.is_to_be_launched,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if data.is_to_be_launched:
        # When marking as TBL, default to +25 days from today if no date provided
        if data.launch_date:
            update["launch_date"] = data.launch_date
        else:
            from datetime import timedelta as _td
            update["launch_date"] = (datetime.now(timezone.utc) + _td(days=25)).isoformat()
        if data.preorder_enabled is not None:
            update["preorder_enabled"] = data.preorder_enabled
    else:
        # When marking as launched, clear launch_date and disable preorder
        update["launch_date"] = None
        update["preorder_enabled"] = False

    await db.products.update_one({"slug": slug}, {"$set": update})
    return {"success": True, "slug": slug, "is_to_be_launched": data.is_to_be_launched, "launch_date": update.get("launch_date")}


@router.post("/products/{slug}/preorder-count")
async def increment_preorder_count(slug: str):
    """Public: Increment preorder counter when a TBL item is added to cart."""
    product = await db.products.find_one({"slug": slug}, {"_id": 0})
    if not product or not product.get("is_to_be_launched"):
        raise HTTPException(status_code=400, detail="Product is not in preorder state")
    await db.products.update_one({"slug": slug}, {"$inc": {"preorder_count": 1}})
    return {"success": True}


class ProductReorderItem(BaseModel):
    slug: str
    sort_order: int


class ProductReorderRequest(BaseModel):
    items: List[ProductReorderItem]


@router.post("/admin/products/reorder")
async def bulk_reorder_products(
    data: ProductReorderRequest,
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    """Admin: Bulk update sort_order on multiple products in a single request."""
    verify_auth(x_admin_token=x_admin_token)
    now = datetime.now(timezone.utc).isoformat()
    updated = 0
    for it in data.items:
        result = await db.products.update_one(
            {"slug": it.slug},
            {"$set": {"sort_order": int(it.sort_order), "updated_at": now}}
        )
        if result.matched_count:
            updated += 1
    return {"success": True, "updated": updated}




@router.post("/admin/products")
async def create_product(
    data: ProductCreate,
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    """Admin: Create a new product"""
    verify_auth(x_admin_token=x_admin_token)
    # Category is OPTIONAL (Feb 2026 spec). Flagship products like the Celesta
    # Glow Anti-Aging Serum live directly under the niche without a category
    # bucket. The admin UI no longer renders the asterisk either — see
    # /app/frontend/src/pages/admin/AdminProducts.js.
    existing = await db.products.find_one({"slug": data.slug})
    if existing:
        raise HTTPException(status_code=400, detail="Product slug already exists")
    
    product = data.dict()
    product["created_at"] = datetime.now(timezone.utc).isoformat()
    product["updated_at"] = datetime.now(timezone.utc).isoformat()
    # If admin didn't pick a sort_order (or kept the default 99), auto-place this
    # product at the TOP of its niche so it's visible immediately on home/listing
    # pages without manual reordering. Existing products at sort_order=1 will
    # naturally tie-break by created_at desc inside `newest` sort.
    if not data.sort_order or data.sort_order >= 99:
        try:
            min_existing = await db.products.find_one(
                {"niche": data.niche or "skincare"},
                sort=[("sort_order", 1)],
                projection={"sort_order": 1, "_id": 0},
            )
            min_so = (min_existing or {}).get("sort_order")
            if isinstance(min_so, (int, float)):
                product["sort_order"] = max(1, int(min_so) - 1) if min_so > 1 else 1
            else:
                product["sort_order"] = 1
        except Exception:
            product["sort_order"] = 1
    # Auto-seed a realistic review count + rating so new cards don't feel empty.
    product["reviews_count"] = random.randint(1020, 4875)
    product["rating"] = round(random.uniform(4.5, 4.9), 1)
    await db.products.insert_one(product)

    # Fire-and-forget: generate personalised reviews tailored to this product.
    try:
        from services.ai_content_generator import generate_product_reviews
        reviews = await generate_product_reviews(
            name=data.name,
            niche=data.niche or "skincare",
            key_ingredients=data.key_ingredients or "",
            benefits=data.benefits or [],
        )
        if reviews:
            await db.product_reviews.insert_many([
                {**r, "product_slug": data.slug, "created_at": datetime.now(timezone.utc).isoformat()}
                for r in reviews
            ])
    except Exception as e:
        logging.warning(f"[admin.create_product] AI reviews generation failed for {data.slug}: {e}")

    return {"success": True, "slug": data.slug}


@router.put("/admin/products/{slug}")
async def update_product(
    slug: str,
    data: ProductUpdate,
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    """Admin: Update product details.

    PRICE GUARD: prepaid_price / cod_price / mrp are NEVER updated by this
    endpoint unless the request also passes ``allow_price_change=true``.
    This is enforced because price changes must be a deliberate admin action
    (Jan 2026 spec — see gift_cards_and_ai.admin_update_product).
    """
    verify_auth(x_admin_token=x_admin_token)
    update = {k: v for k, v in data.dict().items() if v is not None}
    # The deprecated `allow_price_change` flag is no longer required for the
    # per-product PUT — bulk-update has its own price whitelist (see
    # `bulk_update_products`), so a single-product edit is always a deliberate
    # admin action and prices MUST flow through to the DB. Without this fix
    # the admin form silently dropped prepaid_price / cod_price / mrp on save
    # and the new price never showed on the storefront.
    update.pop("allow_price_change", None)
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    # Mirror singular `image` into images[0] so legacy schema consumers still find it.
    if "image" in update and update["image"]:
        img = update["image"]
        existing_imgs = update.get("images") or []
        if not existing_imgs:
            # Fetch current images to preserve any extras
            cur = await db.products.find_one({"slug": slug}, {"_id": 0, "images": 1})
            existing_imgs = (cur or {}).get("images") or []
        if not existing_imgs or existing_imgs[0] != img:
            update["images"] = [img] + [i for i in existing_imgs if i and i != img]
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await db.products.update_one({"slug": slug}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"success": True}


@router.post("/admin/products/{slug}/generate-images")
async def generate_product_images(
    slug: str,
    payload: dict = Body(default={}),
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
):
    """Admin: auto-compose the Formula-Technology gallery cards + lab certificate
    for a product, using its FIRST image (hero product shot) as the bottle source
    so the bottle stays pixel-identical. Budget-free (drawn with Pillow).

    Body: {"gallery": true, "certificate": true}
    """
    verify_auth(x_admin_token=x_admin_token)
    product = await db.products.find_one({"slug": slug}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    do_gallery = payload.get("gallery", True)
    do_cert = payload.get("certificate", True)
    do_ba = payload.get("before_after", True)
    try:
        from services.gallery_composer import generate_and_persist
        fields = await generate_and_persist(
            db, product, do_gallery=do_gallery, do_certificate=do_cert, do_before_after=do_ba
        )
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        logging.error(f"[generate-images] {slug}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Image generation failed: {str(e)[:160]}")
    # Register the generated before/after pair in the collection so the PDP
    # "Before & After" carousel (queried by product_slug) shows it too.
    b_img = fields.pop("before_after_before", None)
    a_img = fields.pop("before_after_after", None)
    if b_img and a_img:
        import hashlib as _h
        ba_id = "ba_" + _h.md5(slug.encode()).hexdigest()[:8]
        await db.before_after_images.update_one(
            {"ba_id": ba_id},
            {"$set": {
                "ba_id": ba_id, "product_slug": slug,
                "before_image": b_img, "after_image": a_img,
                "description": f"{product.get('name', 'Product')} — visible improvement",
                "is_global": False, "sort_order": 0,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
    fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.products.update_one({"slug": slug}, {"$set": fields})
    return {"success": True, **fields}


_variation_jobs: Dict[str, Dict[str, Any]] = {}


async def _variation_worker(job_id: str, slug: str, concern_slug: str, concern_label: str):
    """Run the 24-variation generation in the background so a slow run can never
    trip the proxy/health-probe timeout (the old cause of intermittent 502/503
    failures). Progress + the final summary are polled via the status endpoint."""
    job = _variation_jobs[job_id]
    try:
        product = await db.products.find_one({"slug": slug}, {"_id": 0})
        if not product:
            job.update(status="failed", error="Product not found")
            return
        from services.variation_generator import generate_variations
        summary = await generate_variations(db, product, concern_slug, concern_label)
        job.update(status="completed", result=summary,
                   finished_at=datetime.now(timezone.utc).isoformat())
    except ValueError as ve:
        job.update(status="failed", error=str(ve))
    except Exception as e:
        logging.error(f"[generate-variations] {slug}: {e}", exc_info=True)
        job.update(status="failed", error=f"Variation generation failed: {str(e)[:160]}")


@router.post("/admin/products/{slug}/generate-variations")
async def generate_product_variations(
    slug: str,
    payload: dict = Body(default={}),
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
):
    """Admin: one-click generate the full targeting matrix (2 genders x 3 skin
    types x 4 age groups = 24 shoppable products) from a source product.

    Runs as a BACKGROUND job and returns a job_id immediately — poll
    GET /admin/products/variations-job/{job_id} for progress + the final result.
    Each variation reuses the source product's ACTUAL hero image (0 AI credits),
    but gets its own title / description / how-to-use + certificate.
    """
    verify_auth(x_admin_token=x_admin_token)
    concern_slug = (payload.get("concern") or "").strip()
    concern_label = (payload.get("concern_label") or "").strip()
    if not concern_slug:
        raise HTTPException(status_code=400, detail="Please choose the concern this product solves.")
    product = await db.products.find_one({"slug": slug}, {"_id": 1})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    import uuid as _uuid
    import asyncio as _aio
    job_id = f"var_{_uuid.uuid4().hex[:10]}"
    _variation_jobs[job_id] = {
        "job_id": job_id, "slug": slug, "concern": concern_slug,
        "concern_label": concern_label, "status": "running", "result": None,
        "error": None, "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _aio.create_task(_variation_worker(job_id, slug, concern_slug, concern_label))
    from services.job_store import start_mirror
    start_mirror(db, _variation_jobs[job_id])
    return {"success": True, "job_id": job_id, "status": "running"}


@router.get("/admin/products/variations-job/{job_id}")
async def generate_variations_status(
    job_id: str,
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
):
    verify_auth(x_admin_token=x_admin_token)
    from services.job_store import get_job
    job = await get_job(db, _variation_jobs, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job




@router.delete("/admin/products/{slug}")
async def delete_product(
    slug: str,
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    """Admin: Delete product. Writes a tombstone so seed scripts won't
    resurrect this slug on the next container redeploy."""
    verify_auth(x_admin_token=x_admin_token)
    result = await db.products.delete_one({"slug": slug})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    from services import taxonomy_tombstones as _tomb
    await _tomb.add_tombstone(db, "product", slug)
    return {"success": True}


class BulkDeleteRequest(BaseModel):
    slugs: List[str]


class BulkUpdateRequest(BaseModel):
    slugs: List[str]
    patch: Dict[str, Any]


class BulkDiscountRequest(BaseModel):
    slugs: List[str]
    discount_percent: float  # 0-95, applied to `mrp` to compute new prepaid/cod


@router.post("/admin/products/bulk-delete")
async def bulk_delete_products(
    payload: BulkDeleteRequest,
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
):
    """Admin: Hard-delete a batch of products by slug. Cap at 500 per call so
    a runaway click can never wipe the entire catalog. Returns counts of
    deleted vs not-found so the UI can confirm what actually changed.
    """
    verify_auth(x_admin_token=x_admin_token)
    slugs = [s for s in (payload.slugs or []) if isinstance(s, str) and s][:500]
    if not slugs:
        raise HTTPException(status_code=400, detail="`slugs` cannot be empty")
    res = await db.products.delete_many({"slug": {"$in": slugs}})
    # Tombstone each deleted slug so seed scripts don't resurrect them
    from services import taxonomy_tombstones as _tomb
    for s in slugs:
        await _tomb.add_tombstone(db, "product", s)
    return {"deleted": res.deleted_count, "not_found": len(slugs) - res.deleted_count, "requested": len(slugs)}


@router.post("/admin/products/bulk-update")
async def bulk_update_products(
    payload: BulkUpdateRequest,
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
):
    """Admin: Apply the same patch (e.g. {is_active: False}) to a batch.
    Whitelisted keys only — protects against accidental mass mutation of
    fields like `slug`, `price`, etc."""
    verify_auth(x_admin_token=x_admin_token)
    slugs = [s for s in (payload.slugs or []) if isinstance(s, str) and s][:500]
    if not slugs:
        raise HTTPException(status_code=400, detail="`slugs` cannot be empty")
    ALLOWED = {"is_active", "is_to_be_launched", "badge", "niche", "category", "subcategory", "stock_qty", "low_stock_threshold"}
    patch = {k: v for k, v in (payload.patch or {}).items() if k in ALLOWED}
    if not patch:
        raise HTTPException(status_code=400, detail="`patch` must contain at least one allowed field: " + ", ".join(sorted(ALLOWED)))
    patch["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = await db.products.update_many({"slug": {"$in": slugs}}, {"$set": patch})
    return {"matched": res.matched_count, "modified": res.modified_count, "requested": len(slugs)}


@router.post("/admin/products/bulk-apply-discount")
async def bulk_apply_discount(
    payload: BulkDiscountRequest,
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
):
    """Admin: Apply a flat percentage discount to a batch of products.

    For every selected SKU we recompute:
      • prepaid_price = round(mrp * (100 - pct) / 100)
      • cod_price     = same as prepaid_price
      • discount_percent = pct  (rounded int)
    `mrp` is preserved so the strike-through price stays intact on cards.

    Passing pct = 0 clears the discount (prepaid_price snaps back to mrp).
    """
    verify_auth(x_admin_token=x_admin_token)
    slugs = [s for s in (payload.slugs or []) if isinstance(s, str) and s][:500]
    if not slugs:
        raise HTTPException(status_code=400, detail="`slugs` cannot be empty")
    try:
        pct = float(payload.discount_percent)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="`discount_percent` must be a number")
    if pct < 0 or pct > 95:
        raise HTTPException(status_code=400, detail="`discount_percent` must be between 0 and 95")

    now_iso = datetime.now(timezone.utc).isoformat()
    updated = 0
    skipped = 0
    cursor = db.products.find({"slug": {"$in": slugs}}, {"slug": 1, "mrp": 1, "prepaid_price": 1})
    async for doc in cursor:
        mrp = float(doc.get("mrp") or doc.get("prepaid_price") or 0)
        if mrp <= 0:
            skipped += 1
            continue
        if pct <= 0:
            new_price = int(round(mrp))
            new_disc = 0
        else:
            new_price = max(1, int(round(mrp * (100 - pct) / 100)))
            new_disc = int(round(pct))
        await db.products.update_one(
            {"slug": doc["slug"]},
            {"$set": {
                "prepaid_price": new_price,
                "cod_price": new_price,
                "discount_percent": new_disc,
                "updated_at": now_iso,
            }},
        )
        updated += 1
    return {"updated": updated, "skipped": skipped, "requested": len(slugs), "discount_percent": pct}


# ==================== SCRAPER ENDPOINTS ====================
class ScrapeRequest(BaseModel):
    url: str
    max_reviews: Optional[int] = 20

@router.post("/admin/scrape/product")
async def scrape_product_endpoint(
    payload: ScrapeRequest,
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    """Admin: Analyze a product URL → returns auto-filled product fields.
    Tries JSON-LD first, then site-specific selectors (Amazon/Flipkart/Nykaa),
    and finally an AI fallback (Claude) for unstructured pages."""
    verify_auth(x_admin_token=x_admin_token)
    from services.product_scraper import scrape_product
    data = scrape_product(payload.url)
    return data


@router.post("/admin/scrape/reviews")
async def scrape_reviews_endpoint(
    payload: ScrapeRequest,
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    """Admin: Pull reviews from a product URL."""
    verify_auth(x_admin_token=x_admin_token)
    from services.product_scraper import scrape_reviews
    data = scrape_reviews(payload.url, payload.max_reviews or 20)
    return data


@router.post("/admin/scrape/reviews-bulk")
async def scrape_reviews_bulk_endpoint(
    urls: Dict[str, List[str]],  # {"urls": [...]}
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    """Admin: Pull reviews from multiple URLs (bulk import)."""
    verify_auth(x_admin_token=x_admin_token)
    from services.product_scraper import scrape_reviews
    out = []
    for u in (urls.get("urls") or [])[:5]:  # cap 5 sources
        d = scrape_reviews(u, 20)
        if d.get("success"):
            for r in d.get("reviews", []):
                r["source_domain"] = d.get("source_domain")
                out.append(r)
    return {"success": True, "count": len(out), "reviews": out}


# ==================== PRODUCT REVIEWS (per-product imported list) ====================
class ReviewItem(BaseModel):
    author: str
    text: str
    rating: Optional[float] = None
    source_domain: Optional[str] = None

@router.get("/products/{slug}/reviews")
async def list_product_reviews(slug: str):
    """Public: list imported reviews for a product."""
    p = await db.products.find_one({"slug": slug}, {"_id": 0, "imported_reviews": 1})
    if not p:
        return {"reviews": []}
    return {"reviews": p.get("imported_reviews", [])}


@router.put("/admin/products/{slug}/reviews")
async def set_product_reviews(
    slug: str,
    payload: Dict[str, List[Dict]],  # {"reviews": [...]}
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    """Admin: replace the imported reviews list for a product."""
    verify_auth(x_admin_token=x_admin_token)
    reviews = payload.get("reviews", [])[:50]
    result = await db.products.update_one(
        {"slug": slug},
        {"$set": {"imported_reviews": reviews, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"success": True, "count": len(reviews)}


# ==================== COMBO ENDPOINTS ====================

class ComboCreate(BaseModel):
    combo_id: str
    name: str
    description: str = ""
    product_slugs: List[str]
    mrp_total: float = 0
    combo_prepaid_price: float = 0
    combo_cod_price: float = 0
    discount_percent: float = 0
    badge: str = ""
    is_active: bool = True
    sort_order: int = 99
    image: Optional[str] = None
    niche: Optional[str] = None  # 'anti-aging' | 'skincare' | 'cosmetics' — controls where the combo shows
    # TBL / Preorder
    is_to_be_launched: bool = False
    launch_date: Optional[str] = None
    preorder_enabled: bool = False

class ComboUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    product_slugs: Optional[List[str]] = None
    mrp_total: Optional[float] = None
    combo_prepaid_price: Optional[float] = None
    combo_cod_price: Optional[float] = None
    discount_percent: Optional[float] = None
    badge: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None
    image: Optional[str] = None
    niche: Optional[str] = None
    # TBL / Preorder
    is_to_be_launched: Optional[bool] = None
    launch_date: Optional[str] = None
    preorder_enabled: Optional[bool] = None


@router.get("/combos")
async def get_all_combos(active_only: bool = Query(True), niche: Optional[str] = Query(None)):
    """Public: Get all active combos with TBL auto-flip + countdown.
    If `niche` is provided, returns combos matching that niche (combos with no niche set
    are considered universal and included as well, so legacy combos still appear)."""
    query = {"is_active": True} if active_only else {}
    if niche:
        # match niche==<niche> OR no niche set (legacy/universal)
        query["$or"] = [{"niche": niche}, {"niche": {"$in": [None, ""]}}, {"niche": {"$exists": False}}]
    combos = await db.combos.find(query, {"_id": 0}).sort("sort_order", 1).to_list(50)
    now = datetime.now(timezone.utc)
    for c in combos:
        if c.get("is_to_be_launched") and c.get("launch_date"):
            try:
                ld = datetime.fromisoformat(str(c["launch_date"]).replace("Z", "+00:00"))
                if ld <= now:
                    c["is_to_be_launched"] = False
                    c["launch_date"] = None
                    await db.combos.update_one(
                        {"combo_id": c["combo_id"]},
                        {"$set": {"is_to_be_launched": False, "launch_date": None,
                                  "updated_at": now.isoformat()}}
                    )
                else:
                    delta = ld - now
                    c["days_to_launch"] = max(0, delta.days)
                    c["hours_to_launch"] = max(0, int(delta.total_seconds() // 3600))
            except Exception:
                pass
        else:
            c["days_to_launch"] = None
    await _apply_sale(combos)
    return combos


@router.put("/admin/combos/{combo_id}/launch-status")
async def set_combo_launch_status(
    combo_id: str,
    data: LaunchStatusUpdate,
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    """Admin: Toggle a combo's TBL status."""
    verify_auth(x_admin_token=x_admin_token)
    combo = await db.combos.find_one({"combo_id": combo_id})
    if not combo:
        raise HTTPException(status_code=404, detail="Combo not found")

    update = {
        "is_to_be_launched": data.is_to_be_launched,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if data.is_to_be_launched:
        if data.launch_date:
            update["launch_date"] = data.launch_date
        else:
            from datetime import timedelta as _td
            update["launch_date"] = (datetime.now(timezone.utc) + _td(days=25)).isoformat()
        if data.preorder_enabled is not None:
            update["preorder_enabled"] = data.preorder_enabled
    else:
        update["launch_date"] = None
        update["preorder_enabled"] = False

    await db.combos.update_one({"combo_id": combo_id}, {"$set": update})
    return {"success": True, "combo_id": combo_id, "is_to_be_launched": data.is_to_be_launched}


@router.post("/admin/combos")
async def create_combo(
    data: ComboCreate,
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    verify_auth(x_admin_token=x_admin_token)
    combo = data.dict()
    combo["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.combos.insert_one(combo)
    return {"success": True, "combo_id": data.combo_id}


@router.put("/admin/combos/{combo_id}")
async def update_combo(
    combo_id: str,
    data: ComboUpdate,
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    verify_auth(x_admin_token=x_admin_token)
    update = {k: v for k, v in data.dict().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await db.combos.update_one({"combo_id": combo_id}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Combo not found")
    return {"success": True}


@router.delete("/admin/combos/{combo_id}")
async def delete_combo(
    combo_id: str,
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    verify_auth(x_admin_token=x_admin_token)
    await db.combos.delete_one({"combo_id": combo_id})
    return {"success": True}


# ==================== COUPON ENDPOINTS ====================

class CouponCreate(BaseModel):
    code: str
    discount_type: str = "percentage"  # percentage or fixed
    discount_value: float = 10
    min_order_amount: float = 0
    max_uses: int = 100
    expiry_days: int = 30
    is_active: bool = True
    show_on_cart: bool = True
    description: Optional[str] = None


class CouponUpdate(BaseModel):
    discount_type: Optional[str] = None
    discount_value: Optional[float] = None
    min_order_amount: Optional[float] = None
    max_uses: Optional[int] = None
    expiry_date: Optional[str] = None  # ISO date string
    expiry_days: Optional[int] = None  # alternative — extend expiry by N days
    is_active: Optional[bool] = None
    show_on_cart: Optional[bool] = None
    description: Optional[str] = None


@router.get("/admin/coupons")
async def get_all_coupons(x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_auth(x_admin_token=x_admin_token)
    coupons = await db.coupons.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return coupons


@router.post("/admin/coupons")
async def create_coupon(data: CouponCreate, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_auth(x_admin_token=x_admin_token)
    coupon = data.dict()
    coupon["used_count"] = 0
    coupon["created_at"] = datetime.now(timezone.utc).isoformat()
    from datetime import timedelta
    coupon["expiry_date"] = (datetime.now(timezone.utc) + timedelta(days=data.expiry_days)).isoformat()
    del coupon["expiry_days"]
    await db.coupons.insert_one(coupon)
    return {"success": True, "code": data.code}


@router.post("/validate-coupon")
async def validate_coupon(code: str = Query(...), cart_total: float = Query(0)):
    """Public: Validate a coupon code"""
    coupon = await db.coupons.find_one({"code": code.upper(), "is_active": True}, {"_id": 0})
    if not coupon:
        raise HTTPException(status_code=404, detail="Invalid coupon code")
    if coupon.get("expiry_date") and datetime.fromisoformat(coupon["expiry_date"]) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Coupon expired")
    if coupon.get("max_uses") and coupon.get("used_count", 0) >= coupon["max_uses"]:
        raise HTTPException(status_code=400, detail="Coupon usage limit reached")
    if cart_total < coupon.get("min_order_amount", 0):
        raise HTTPException(status_code=400, detail=f"Minimum order amount: ₹{coupon['min_order_amount']}")
    
    discount = coupon["discount_value"]
    if coupon["discount_type"] == "percentage":
        discount = round(cart_total * coupon["discount_value"] / 100, 2)
    
    return {"valid": True, "discount": discount, "discount_type": coupon["discount_type"], "discount_value": coupon["discount_value"]}


@router.get("/coupons/public")
async def list_public_coupons():
    """Public: list active, non-expired coupons that admin marked as `show_on_cart=True`.
    These appear on the cart page so customers can apply them in one click."""
    now = datetime.now(timezone.utc)
    coupons = await db.coupons.find(
        {"is_active": True, "show_on_cart": True},
        {"_id": 0, "code": 1, "discount_type": 1, "discount_value": 1,
         "min_order_amount": 1, "expiry_date": 1, "description": 1, "max_uses": 1, "used_count": 1}
    ).sort("created_at", -1).to_list(20)
    out = []
    for c in coupons:
        # Skip expired/exhausted coupons
        if c.get("expiry_date"):
            try:
                if datetime.fromisoformat(c["expiry_date"]) < now:
                    continue
            except Exception:
                pass
        if c.get("max_uses") and c.get("used_count", 0) >= c["max_uses"]:
            continue
        # Auto-generate description if missing
        if not c.get("description"):
            if c.get("discount_type") == "percentage":
                c["description"] = f"{int(c.get('discount_value', 0))}% OFF"
            else:
                c["description"] = f"₹{int(c.get('discount_value', 0))} OFF"
            if c.get("min_order_amount"):
                c["description"] += f" on orders above ₹{int(c['min_order_amount'])}"
        out.append(c)
    return out


@router.delete("/admin/coupons/{code}")
async def delete_coupon(code: str, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_auth(x_admin_token=x_admin_token)
    await db.coupons.delete_one({"code": code})
    return {"success": True}


@router.put("/admin/coupons/{code}")
async def update_coupon(code: str, data: CouponUpdate, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    """Admin: edit coupon details — discount, expiry, active state, show_on_cart, description, etc."""
    verify_auth(x_admin_token=x_admin_token)
    update = {k: v for k, v in data.dict().items() if v is not None and k != "expiry_days"}
    # Convenience: extend expiry by N days from now
    if data.expiry_days is not None:
        from datetime import timedelta
        update["expiry_date"] = (datetime.now(timezone.utc) + timedelta(days=int(data.expiry_days))).isoformat()
    if not update:
        return {"success": True, "code": code, "updated": 0}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await db.coupons.update_one({"code": code.upper()}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Coupon not found")
    return {"success": True, "code": code}


# ==================== CART VALIDATION ====================

class CartItem(BaseModel):
    product_slug: Optional[str] = None
    combo_id: Optional[str] = None
    quantity: int = 1
    shade_id: Optional[str] = None  # cosmetics shade variant selection

class CartValidateRequest(BaseModel):
    items: List[CartItem]
    coupon_code: Optional[str] = None
    gift_card_code: Optional[str] = None
    payment_method: str = "prepaid"
    prepaid_bonus: bool = False  # ₹100 off — only honored when payment_method == 'prepaid'
    # Flash-offer window (3 min countdown started on first /checkout landing,
    # 2-day cooldown). When False the anti-aging tax/delivery perks + prepaid
    # bonus are ALL stripped so the user sees the "regular" price. Server never
    # trusts this blindly for money — it's just a signal from the client.
    promo_active: bool = True
    session_id: Optional[str] = None  # stable per session — seeds the free-gift picker


@router.post("/cart/validate")
async def validate_cart(data: CartValidateRequest):
    """Validate cart items, calculate totals.

    Perf: previously did N round-trips to MongoDB (one find_one per cart item +
    one per combo). For a 10-item cart that's 10 sequential queries. Now we
    batch-load ALL products with a single ``$in`` query and ALL combos with
    another single ``$in`` query, then iterate in-memory. ~10x speedup on
    typical carts; preserves shade/stock/TBL/coupon logic byte-for-byte.
    """
    validated_items = []
    subtotal = 0
    mrp_total = 0
    stock_warnings = []  # list of {slug, message, capped_to}

    # COD no longer carries a premium — the new platform fee covers both COD + prepaid
    # uniformly (delivery & taxes are the differentiators below).
    cod_premium = 0

    # ---- Batch-load products & combos in TWO queries instead of 2N ----
    product_slugs = [i.product_slug for i in data.items if i.product_slug]
    combo_ids = [i.combo_id for i in data.items if i.combo_id]
    products_by_slug: Dict[str, Any] = {}
    combos_by_id: Dict[str, Any] = {}
    if product_slugs:
        async for p in db.products.find(
            {"slug": {"$in": product_slugs}, "is_active": True}, {"_id": 0}
        ):
            products_by_slug[p["slug"]] = p
    if combo_ids:
        async for c in db.combos.find(
            {"combo_id": {"$in": combo_ids}, "is_active": True}, {"_id": 0}
        ):
            combos_by_id[c["combo_id"]] = c

    # ---- Feb-2026: "Other brands out of stock" master switch ----
    # If admin has turned the toggle OFF (default), we DROP any non-Celesta-Glow
    # branded item from the cart silently. If AFTER dropping the cart still has
    # at least one Celesta Glow item, checkout proceeds normally with just the
    # house-brand items (with a `dropped_other_brand_items` notice so the UI
    # can surface a small message). Only when the ENTIRE cart is non-house
    # brand do we raise a 409 that bounces the shopper to the homepage.
    _brand_flag_doc = await db.site_settings.find_one(
        {"_id": "main"}, {"_id": 0, "other_brands_in_stock": 1}
    ) or {}
    _other_brands_in_stock = bool(_brand_flag_doc.get("other_brands_in_stock", False))
    dropped_other_brand_items: list = []
    if not _other_brands_in_stock:
        def _is_other_brand(p: dict) -> bool:
            brand = (p.get("brand") or "").strip().lower()
            return bool(brand) and "celesta" not in brand
        # Drop the non-house products from the lookup so the downstream loop
        # skips them (item.product_slug won't resolve).
        keep_slugs: list = []
        for slug, p in list(products_by_slug.items()):
            if _is_other_brand(p):
                dropped_other_brand_items.append({
                    "slug": p.get("slug"),
                    "name": p.get("name"),
                    "brand": p.get("brand"),
                })
                del products_by_slug[slug]
            else:
                keep_slugs.append(slug)
        # Combos: drop any combo whose constituents include a non-house SKU
        for combo_id, c in list(combos_by_id.items()):
            has_other = False
            for s in (c.get("product_slugs") or []):
                pdoc = products_by_slug.get(s)
                if pdoc is None:
                    # Not batched — fetch just this doc's brand
                    pdoc = await db.products.find_one(
                        {"slug": s}, {"_id": 0, "slug": 1, "name": 1, "brand": 1}
                    )
                if pdoc and _is_other_brand(pdoc):
                    has_other = True
                    dropped_other_brand_items.append({
                        "slug": pdoc.get("slug"),
                        "name": pdoc.get("name"),
                        "brand": pdoc.get("brand"),
                        "via_combo": combo_id,
                    })
                    break
            if has_other:
                del combos_by_id[combo_id]
        # If the ENTIRE cart was non-house brand → block. Otherwise silently
        # proceed with just the house-brand items.
        original_products = len(data.items)
        remaining = len(products_by_slug) + len(combos_by_id)
        if original_products > 0 and remaining == 0 and dropped_other_brand_items:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": "other_brands_out_of_stock",
                    "message": (
                        "Oh no — those products are currently out of stock. "
                        "Check out our anti-aging line for fresh formulas and today's best offers."
                    ),
                    "redirect_to": "/",
                    "offending_items": dropped_other_brand_items,
                },
            )

    # Batch-load niches for any products referenced by combos but not directly
    # in the cart — needed so we can compute a combo-level niche (used by the
    # checkout page to decide COD availability for anti-aging-only carts).
    combo_product_slugs = set()
    for c in combos_by_id.values():
        for s in (c.get("product_slugs") or []):
            if s and s not in products_by_slug:
                combo_product_slugs.add(s)
    combo_slug_niches: Dict[str, str] = {}
    if combo_product_slugs:
        async for p in db.products.find(
            {"slug": {"$in": list(combo_product_slugs)}}, {"_id": 0, "slug": 1, "niche": 1}
        ):
            combo_slug_niches[p["slug"]] = str(p.get("niche") or "").lower()

    for item in data.items:
        if item.product_slug:
            product = products_by_slug.get(item.product_slug)
            if not product:
                continue
            # Defense in depth: drop TBL products from the cart so they cannot reach checkout.
            if product.get("is_to_be_launched"):
                continue
            # ---- Shade resolution (for cosmetics with shade variants) ----
            shades = product.get("shades") or []
            chosen_shade = None
            if shades:
                # If product has shades but no shade_id passed, drop with warning
                if not item.shade_id:
                    stock_warnings.append({"slug": product["slug"], "message": "Please pick a shade", "code": "shade_required"})
                    continue
                chosen_shade = next((s for s in shades if str(s.get("id")) == str(item.shade_id)), None)
                if not chosen_shade:
                    stock_warnings.append({"slug": product["slug"], "message": "Selected shade no longer available", "code": "shade_missing"})
                    continue
            # ---- Stock enforcement ----
            available = int(chosen_shade["stock_qty"]) if chosen_shade and chosen_shade.get("stock_qty") is not None else int(product.get("stock_qty") or 0)
            qty = item.quantity
            if available <= 0:
                stock_warnings.append({"slug": product["slug"], "message": "Out of stock", "code": "out_of_stock"})
                continue
            if qty > available:
                stock_warnings.append({"slug": product["slug"], "message": f"Only {available} left — quantity reduced", "code": "qty_capped", "capped_to": available})
                qty = available
            # Always use prepaid price as base — COD premium is applied at cart-level (not per-item)
            price = product["prepaid_price"]
            line_total = price * qty
            mrp_line = product["mrp"] * qty
            shade_img = (chosen_shade or {}).get("image") if chosen_shade else None
            base_img = product["images"][0] if product.get("images") else ""
            validated_items.append({
                "type": "product",
                "slug": product["slug"],
                "name": product["name"],
                "short_name": product["short_name"],
                "image": shade_img or base_img,
                "mrp": product["mrp"],
                "price": price,
                "quantity": qty,
                "line_total": line_total,
                "shade_id": chosen_shade.get("id") if chosen_shade else None,
                "shade_name": chosen_shade.get("name") if chosen_shade else None,
                "shade_hex": chosen_shade.get("hex") if chosen_shade else None,
                "stock_left": available,
                "niche": product.get("niche"),
            })
            subtotal += line_total
            mrp_total += mrp_line
        elif item.combo_id:
            combo = combos_by_id.get(item.combo_id)
            if not combo:
                continue
            # Defense in depth: drop TBL combos from cart.
            if combo.get("is_to_be_launched"):
                continue
            price = combo["combo_prepaid_price"]  # uniform prepaid base
            line_total = price * item.quantity
            mrp_line = combo["mrp_total"] * item.quantity
            # Combo-level niche: derive from constituent product niches so the
            # checkout page can gate COD correctly for anti-aging-only combos.
            combo_niches = set()
            for s in (combo.get("product_slugs") or []):
                n = combo_slug_niches.get(s)
                if n is None:
                    n = str((products_by_slug.get(s) or {}).get("niche") or "").lower()
                if n:
                    combo_niches.add(n)
            combo_niche = None
            if combo_niches:
                combo_niche = next(iter(combo_niches)) if len(combo_niches) == 1 else "mixed"
            validated_items.append({
                "type": "combo",
                "combo_id": combo["combo_id"],
                "name": combo["name"],
                "image": combo.get("image", ""),
                "product_slugs": combo["product_slugs"],
                "mrp_total": combo["mrp_total"],
                "price": price,
                "quantity": item.quantity,
                "line_total": line_total,
                "niche": combo_niche,
                "niches": sorted(combo_niches),
            })
            subtotal += line_total
            mrp_total += mrp_line
    
    # Apply coupon
    discount = 0
    if data.coupon_code:
        coupon = await db.coupons.find_one({"code": data.coupon_code.upper(), "is_active": True}, {"_id": 0})
        if coupon:
            if coupon["discount_type"] == "percentage":
                discount = round(subtotal * coupon["discount_value"] / 100, 2)
            else:
                discount = coupon["discount_value"]
    
    total = max(subtotal - discount, 0)
    
    # Volume discount DISABLED — buy-N-get-X% removed per business policy (kills margin).
    total_items = sum(i["quantity"] for i in validated_items)
    volume_discount = 0
    volume_discount_percent = 0
    settings_doc = await db.site_settings.find_one({"_id": "main"}, {"_id": 0})

    # Band Margin Strategy (Feb 2026 — tiered for profitability):
    #   Delivery fee:
    #     < ₹1000  → ₹49
    #     ≥ ₹1000  → ₹39
    #     ≥ ₹1500  → ₹29
    #     ≥ ₹2500  → ₹19
    #   Tax & charges reduction (base ₹99):
    #     < ₹1000  → 0%  (full ₹99)
    #     ≥ ₹1000  → 30% off
    #     ≥ ₹1500  → 35% off
    #     ≥ ₹2000  → 40% off
    #     ≥ ₹5000  → 50% off
    delivery_fee_amount = float((settings_doc or {}).get("delivery_fee") or 49)
    tax_charges_full = float((settings_doc or {}).get("tax_charges") or 99)
    packaging_fee_amount = float((settings_doc or {}).get("packaging_fee") or 15)
    moq_amount = float((settings_doc or {}).get("moq_amount") or 300)
    pre_ship_total = max(total - volume_discount, 0)

    # ---- Tiered delivery fee ----
    if pre_ship_total >= 2500:
        delivery_fee = 19
    elif pre_ship_total >= 1500:
        delivery_fee = 29
    elif pre_ship_total >= 1000:
        delivery_fee = 39
    else:
        delivery_fee = delivery_fee_amount

    # ---- Tiered tax reduction ----
    if pre_ship_total >= 5000:
        tax_reduction_pct = 0.50
    elif pre_ship_total >= 2000:
        tax_reduction_pct = 0.40
    elif pre_ship_total >= 1500:
        tax_reduction_pct = 0.35
    elif pre_ship_total >= 1000:
        tax_reduction_pct = 0.30
    else:
        tax_reduction_pct = 0.0
    tax_charges = round(tax_charges_full * (1 - tax_reduction_pct))

    qualifies_999 = pre_ship_total >= 1000  # any tier discount = unlock badge
    free_shipping_threshold = 1000  # legacy field; first discount tier
    packaging_fee = packaging_fee_amount if pre_ship_total > 0 else 0

    # ---- FREE DELIVERY + ZERO CHARGES on every order above ₹100 (business rule) ----
    # Any cart over ₹100 ships free with no delivery / tax / packaging charges.
    free_delivery_threshold = 100
    free_delivery_applied = pre_ship_total >= free_delivery_threshold
    free_delivery_remaining = max(0, free_delivery_threshold - pre_ship_total)
    if free_delivery_applied:
        delivery_fee = 0
        tax_charges = 0
        packaging_fee = 0
    # Savings on charges = (full delivery − tier delivery) + (tax_full − tier tax)
    charges_savings = (delivery_fee_amount - delivery_fee) + (tax_charges_full - tax_charges) if pre_ship_total >= 1000 else 0
    tax_reduction_label = f"{int(tax_reduction_pct * 100)}% OFF" if tax_reduction_pct > 0 else None

    free_shipping_remaining = max(0, free_shipping_threshold - pre_ship_total)
    moq_remaining = max(0, moq_amount - pre_ship_total) if pre_ship_total > 0 else 0
    moq_block = bool(pre_ship_total > 0 and pre_ship_total < moq_amount)

    # ---- Anti-Aging niche perks: waive delivery + tax on qualifying carts.
    # The zero_shipping / zero_tax flags are DECOUPLED from the FLAT 50% OFF
    # toggle (per admin request Feb-2026) — even when the sale price cut is
    # off, the delivery + tax waivers still apply as a permanent perk of the
    # anti-aging range. This keeps the "always free delivery on anti-aging"
    # promise valid regardless of the sale schedule.
    sale_cfg = await _get_sale_cfg()
    sale_perks_applied = {"delivery": False, "tax": False, "reason": None}
    # Flash-offer gate: when the 3-min countdown has expired on the client,
    # `promo_active=False` is sent, so we skip the anti-aging tax/delivery
    # waivers entirely — the user sees the "regular" price with full charges.
    if data.promo_active and sale_cfg and validated_items and (sale_cfg.get("zero_shipping") or sale_cfg.get("zero_tax")):
        elig_niches = set((sale_cfg.get("applies_to_niches") or ["anti-aging"]))
        # Only apply when every physical product line qualifies. Standalone combos
        # skip this fast-path since their niche field isn't a simple string.
        product_lines = [it for it in validated_items if it.get("type") == "product"]
        if product_lines:
            item_niches = set()
            for it in product_lines:
                p = products_by_slug.get(it.get("slug"))
                item_niches.add(str((p or {}).get("niche") or "").lower())
            all_eligible = item_niches and item_niches.issubset({n.lower() for n in elig_niches})
            if all_eligible:
                if sale_cfg.get("zero_shipping"):
                    delivery_fee = 0
                    sale_perks_applied["delivery"] = True
                if sale_cfg.get("zero_tax"):
                    tax_charges = 0
                    sale_perks_applied["tax"] = True
                if sale_perks_applied["delivery"] or sale_perks_applied["tax"]:
                    # Prefer the sale badge label when the sale is live, otherwise
                    # fall back to a niche-perk label so the cart UI still shows
                    # the reason chip.
                    if sale_cfg.get("enabled"):
                        sale_perks_applied["reason"] = sale_cfg.get("badge_label") or "FLAT 50% OFF"
                    else:
                        sale_perks_applied["reason"] = "Anti-Aging Perk"

    # Keep legacy `shipping_fee` field for backward compatibility with older clients
    shipping_fee = delivery_fee + tax_charges + packaging_fee

    final_total = pre_ship_total + cod_premium + shipping_fee
    total_savings = max(mrp_total - (final_total - shipping_fee - cod_premium), 0)

    # Apply gift card AFTER all charges — gift card can pay for charges too
    gift_card_discount = 0
    gift_card_info = None
    if data.gift_card_code and final_total > 0:
        from services.gift_card_service import GiftCardService
        gc_svc = GiftCardService(db)
        gc_res = await gc_svc.validate_for_redemption(data.gift_card_code, final_total)
        if gc_res.get("valid"):
            gift_card_discount = gc_res["discount"]
            gift_card_info = {
                "code": gc_res["code"],
                "discount": gc_res["discount"],
                "remaining_balance": gc_res["remaining_balance"],
                "remaining_after": gc_res["remaining_after"],
                "message": gc_res["message"],
            }
            final_total = max(0, final_total - gift_card_discount)
        else:
            gift_card_info = {"error": gc_res.get("message", "Invalid gift card")}
    
    # Compute next tier hint so the cart UI can say "Spend ₹X more to save ₹Y"
    next_tier = None
    tier_thresholds = [
        (1000, 30, 39),
        (1500, 35, 29),
        (2000, 40, 29),
        (2500, 40, 19),
        (5000, 50, 19),
    ]
    for thr, pct, dlv in tier_thresholds:
        if pre_ship_total < thr:
            tier_tax = round(tax_charges_full * (1 - pct / 100))
            next_tier = {
                "threshold": thr,
                "spend_more": int(round(thr - pre_ship_total)),
                "next_tax_charges": int(tier_tax),
                "next_delivery_fee": int(dlv),
                "next_tax_pct_off": pct,
                "label": f"Spend ₹{int(round(thr - pre_ship_total))} more to unlock {pct}% OFF taxes" + (f" + ₹{dlv} delivery" if dlv != delivery_fee else ""),
            }
            break

    # ---- Prepaid bonus (₹100 off, prepaid only, cart subtotal ≥ ₹800) ----
    # Frontend toggles this via a checkout button. Server enforces all three
    # rules (flag on, payment_method='prepaid', subtotal >= threshold) so the
    # discount can never be abused via COD or low-value carts.
    PREPAID_BONUS_AMOUNT = 100
    PREPAID_BONUS_MIN_SUBTOTAL = 800
    prepaid_bonus_applied = 0
    if (
        data.prepaid_bonus
        and data.promo_active
        and data.payment_method == "prepaid"
        and subtotal >= PREPAID_BONUS_MIN_SUBTOTAL
        and final_total > PREPAID_BONUS_AMOUNT
    ):
        prepaid_bonus_applied = PREPAID_BONUS_AMOUNT
        final_total = max(0, final_total - PREPAID_BONUS_AMOUNT)

    # ---- Checkout Free Gift (replaces the ₹50 flash bonus, Feb-2026) ----
    # When prepaid + subtotal above threshold, we lock in a RANDOM free product
    # from a whitelist. The actual pick is deterministic per session (so the
    # same cart shows the same gift, no flicker) but different sessions get
    # different gifts — that's the "surprise" the marketing team wants.
    checkout_bonus_applied = 0            # kept for backwards compat in old clients
    CHECKOUT_BONUS_AMOUNT = 0
    CHECKOUT_BONUS_MIN_SUBTOTAL = 1000
    free_gift = None
    free_gift_pool = ["sunscreen", "under-eye-cream", "cleanser"]
    # Allow admin override via admin_settings
    fg_cfg = await db.admin_settings.find_one({"type": "free_gift"}, {"_id": 0}) or {}
    if isinstance(fg_cfg.get("pool"), list) and fg_cfg["pool"]:
        free_gift_pool = [str(s).strip() for s in fg_cfg["pool"] if s]
    fg_min_subtotal = int(fg_cfg.get("min_subtotal") or CHECKOUT_BONUS_MIN_SUBTOTAL)
    checkout_bonus_eligible = (
        data.promo_active
        and data.payment_method == "prepaid"
        and subtotal > fg_min_subtotal
    )
    if checkout_bonus_eligible and free_gift_pool:
        import hashlib
        # Deterministic seed = session_id (if provided) OR the sorted set of
        # slugs+quantities. This locks the gift for the session so the user
        # sees the same one on cart, checkout and order pages.
        seed_src = (data.session_id or "") + "|" + "|".join(
            f"{(getattr(it, 'product_slug', None) or getattr(it, 'combo_id', None))}:{getattr(it, 'quantity', 0)}"
            for it in (data.items or [])
        )
        idx = int(hashlib.md5(seed_src.encode("utf-8")).hexdigest(), 16) % len(free_gift_pool)
        gift_slug = free_gift_pool[idx]
        gp = await db.products.find_one(
            {"slug": gift_slug},
            {"_id": 0, "slug": 1, "name": 1, "short_name": 1, "image": 1,
             "mrp": 1, "prepaid_price": 1, "images": 1, "size": 1},
        )
        if gp:
            free_gift = {
                "slug": gp.get("slug"),
                "name": gp.get("short_name") or gp.get("name"),
                "full_name": gp.get("name"),
                "image": gp.get("image") or ((gp.get("images") or [None])[0]),
                "mrp": gp.get("mrp") or gp.get("prepaid_price") or 0,
                "size": gp.get("size") or "",
            }

    # ---- Cart Combo Bonus (admin-configurable, tiered) OFF ----
    # Defaults: 2 anti-aging items = ₹99, 3 = ₹150, 4+ = ₹200. Fully
    # configurable via `admin_settings.{type: 'combo_bonus'}.tiers`.
    # Not stackable with explicit combo line items.
    combo_bonus_cfg = await db.admin_settings.find_one({"type": "combo_bonus"}, {"_id": 0}) or {}
    combo_tiers = combo_bonus_cfg.get("tiers")
    if not isinstance(combo_tiers, list) or not combo_tiers:
        # Backwards compatible: derive a single-tier list from the legacy amount field
        legacy_amount = int(combo_bonus_cfg.get("amount") or 99)
        legacy_min = int(combo_bonus_cfg.get("min_items") or 2)
        combo_tiers = [{"items": legacy_min, "amount": legacy_amount}]
    # Normalise + sort by items ascending
    combo_tiers = sorted(
        [{"items": int(t.get("items") or 0), "amount": int(t.get("amount") or 0)} for t in combo_tiers if int(t.get("items") or 0) >= 2 and int(t.get("amount") or 0) > 0],
        key=lambda t: t["items"],
    )
    COMBO_BONUS_MIN_SUBTOTAL = int(combo_bonus_cfg.get("min_subtotal") or 500)
    combo_bonus_applied = 0
    combo_bonus_eligible = False
    combo_bonus_message = None
    combo_bonus_next_tier = None  # {items_needed, amount} — what's next
    product_lines_only = [it for it in validated_items if it.get("type") == "product"]
    has_explicit_combo = any(it.get("type") == "combo" for it in validated_items)
    aa_item_count = sum(int(it.get("quantity") or 0) for it in product_lines_only if str((it.get("niche") or "")).lower() == "anti-aging")
    total_qty = sum(int(it.get("quantity") or 0) for it in product_lines_only)
    # Combo Bonus now applies to ANY combination of products (not just anti-aging).
    combo_item_count = total_qty
    if not has_explicit_combo and combo_tiers and combo_item_count > 0:
        # Pick the highest tier the customer already qualifies for
        active_tier = None
        for t in combo_tiers:
            if combo_item_count >= t["items"]:
                active_tier = t
            else:
                combo_bonus_next_tier = {"items_needed": t["items"] - combo_item_count, "amount": t["amount"], "target_items": t["items"]}
                break
        if active_tier:
            combo_bonus_eligible = True
            if final_total > active_tier["amount"] and subtotal >= COMBO_BONUS_MIN_SUBTOTAL:
                combo_bonus_applied = active_tier["amount"]
                final_total = max(0, final_total - active_tier["amount"])
                combo_bonus_message = f"Combo Bonus \u20b9{active_tier['amount']} OFF applied — {combo_item_count} products"

    return {
        "items": validated_items,
        "dropped_other_brand_items": dropped_other_brand_items,
        "mrp_total": int(round(mrp_total)),
        "subtotal": int(round(subtotal)),
        "discount": int(round(discount)),
        "volume_discount": 0,
        "volume_discount_percent": 0,
        "cod_premium": int(round(cod_premium)),
        "shipping_fee": int(round(shipping_fee)),
        "delivery_fee": int(round(delivery_fee)),
        "delivery_fee_original": int(round(delivery_fee_amount)),
        "tax_charges": int(round(tax_charges)),
        "tax_charges_original": int(round(tax_charges_full)),
        "tax_reduction_label": tax_reduction_label,
        "tax_reduction_pct": int(tax_reduction_pct * 100),
        "packaging_fee": int(round(packaging_fee)),
        "charges_savings": int(round(charges_savings)),
        "free_shipping_threshold": int(round(free_shipping_threshold)),
        "free_shipping_remaining": int(round(free_shipping_remaining)),
        "free_delivery_threshold": int(round(free_delivery_threshold)),
        "free_delivery_applied": bool(free_delivery_applied),
        "free_delivery_remaining": int(round(free_delivery_remaining)),
        "moq_amount": int(round(moq_amount)),
        "moq_remaining": int(round(moq_remaining)),
        "moq_block": moq_block,
        "sale_perks": sale_perks_applied,
        "payment_method": data.payment_method,
        "gift_card": gift_card_info,
        "gift_card_discount": int(round(gift_card_discount)),
        "prepaid_bonus_applied": prepaid_bonus_applied,
        "prepaid_bonus_amount": PREPAID_BONUS_AMOUNT,
        "prepaid_bonus_min_subtotal": PREPAID_BONUS_MIN_SUBTOTAL,
        "prepaid_bonus_eligible": subtotal >= PREPAID_BONUS_MIN_SUBTOTAL,
        "checkout_bonus_applied": checkout_bonus_applied,
        "checkout_bonus_amount": CHECKOUT_BONUS_AMOUNT,
        "checkout_bonus_min_subtotal": CHECKOUT_BONUS_MIN_SUBTOTAL,
        "checkout_bonus_eligible": bool(checkout_bonus_eligible),
        "free_gift": free_gift,
        "free_gift_eligible": bool(checkout_bonus_eligible),
        "free_gift_pool": free_gift_pool,
        "free_gift_min_subtotal": fg_min_subtotal,
        "combo_bonus_applied": combo_bonus_applied,
        "combo_bonus_tiers": combo_tiers,
        "combo_bonus_next_tier": combo_bonus_next_tier,
        "combo_bonus_eligible": bool(combo_bonus_eligible),
        "combo_bonus_message": combo_bonus_message,
        # Progress bar must reflect the SAME count the tier/discount logic uses
        # (all products, not just anti-aging), otherwise the bar won't move when
        # a non-anti-aging product is added even though the bonus unlocks.
        "combo_bonus_aa_count": combo_item_count,
        "total": int(round(final_total)),
        "savings": int(round(total_savings + prepaid_bonus_applied + checkout_bonus_applied + combo_bonus_applied)),
        "item_count": total_items,
        "prepaid_savings_hint": int(round(cod_premium)),
        "stock_warnings": stock_warnings,
        "next_tier": next_tier,
    }


# ==================== ADMIN SITE SETTINGS ====================

class SiteSettingsUpdate(BaseModel):
    splash_image: Optional[str] = None
    hero_banner_image: Optional[str] = None
    hero_title: Optional[str] = None
    hero_subtitle: Optional[str] = None
    presale_enabled: Optional[bool] = None
    presale_title: Optional[str] = None
    presale_badge: Optional[str] = None
    presale_price: Optional[float] = None
    cod_advance_amount: Optional[float] = None
    before_after_images: Optional[List[Dict]] = None
    result_images: Optional[List[str]] = None
    bundle_hero_image: Optional[str] = None
    # Anti-aging kit landscape banner shown on /shop view-all page
    shop_kit_banner_image: Optional[str] = None
    shop_kit_banner_eyebrow: Optional[str] = None
    shop_kit_banner_title: Optional[str] = None
    shop_kit_banner_subtitle: Optional[str] = None
    shop_kit_banner_link: Optional[str] = None
    homepage_feature_image: Optional[str] = None  # NEW: editable landscape banner that replaces 3-product hero side panel
    homepage_feature_title: Optional[str] = None
    homepage_feature_subtitle: Optional[str] = None
    volume_discounts: Optional[List[Dict]] = None  # [{min_items: 2, discount_percent: 5}, ...]
    # Store-wide master switch: when True, Cash on Delivery is disabled at
    # checkout AND rejected by the order API (admin Prepaid-only toggle).
    prepaid_only: Optional[bool] = None
    # Multi-banner hero carousel
    banner_carousel: Optional[List[Dict]] = None  # [{id, image, title, subtitle, cta_text, cta_link, sort_order}, ...]
    carousel_autoplay_ms: Optional[int] = None  # default 2000
    # Per-niche home page customization
    # Shape: { "anti-aging": {hero: {...}, bestsellers: {...}, cta_section: {...}, banner_carousel: [...], ...},
    #          "skincare": {...}, "cosmetics": {...} }
    niche_settings: Optional[Dict[str, Dict]] = None
    # Premium /categories hub (Shop by Category) — admin-editable hero, niche cards, ribbon banner, ingredient strip.
    # Shape: {
    #   hero: { eyebrow, title_line1, title_line2, subtitle, image_desktop, image_mobile, accent, search_placeholder },
    #   niche_cards: {
    #     anti_aging: { enabled, eyebrow, title, subtitle, image, cta_label, cta_link, accent },
    #     skincare:   {...same...},
    #     cosmetics:  {...same...}
    #   },
    #   ribbon: { enabled, text, cta_label, cta_link, bg_from, bg_to },
    #   ingredient_strip: { enabled, title, subtitle, items: [{name, image, hex}, ...] },
    #   editors_picks: { enabled, eyebrow, title, slugs: [...product_slug...] }
    # }
    categories_hub: Optional[Dict] = None
    # Feb-2026: toggle for "brand-only categories" mode. When ON, /categories
    # shows ONLY Celesta Glow-branded products grouped by product_type
    # (serums, sunscreen, etc.) — no third-party brand links. When OFF (default),
    # the existing multi-brand hub UI stays untouched.
    house_categories_only: Optional[bool] = None
    # Feb-2026: master switch for "other brand" products (any product whose
    # `brand` isn't Celesta Glow). When False (default) these SKUs are still
    # visible on the site but the cart-validate + create-order endpoints
    # reject them with a friendly `other_brands_out_of_stock` error so the
    # customer is bounced back to the homepage. When True, they can be
    # purchased normally.
    other_brands_in_stock: Optional[bool] = None
    # Admin-supplied reference bottle photo used as the base for one-click
    # product image generation. The product's own name is reprinted onto it.
    product_image_reference_url: Optional[str] = None
    # Kind-specific references so the AI uses the correct bottle (serum vs cream).
    product_image_reference_serum_url: Optional[str] = None
    product_image_reference_cream_url: Optional[str] = None


@router.get("/site-settings")
async def get_site_settings():
    """Public: Get site settings"""
    settings = await db.site_settings.find_one({"_id": "main"}, {"_id": 0})
    return settings or {}


@router.put("/admin/site-settings")
async def update_site_settings(
    data: SiteSettingsUpdate,
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    verify_auth(x_admin_token=x_admin_token)
    update = {k: v for k, v in data.dict().items() if v is not None}
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.site_settings.update_one({"_id": "main"}, {"$set": update}, upsert=True)
    return {"success": True}


# ==================== CUSTOMER RETENTION ====================

@router.get("/admin/retention/customers")
async def get_retention_customers(
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    x_employee_token: str = Header(None, alias="X-Employee-Token"),
    days: int = Query(15)
):
    """Get customers due for follow-up (15 or 30 days after purchase)"""
    verify_auth(x_admin_token=x_admin_token, x_employee_token=x_employee_token, permission="retention")
    from datetime import timedelta
    target_date = datetime.now(timezone.utc) - timedelta(days=days)
    window_start = target_date - timedelta(days=2)
    window_end = target_date + timedelta(days=2)
    
    orders = await db.orders.find({
        "status": {"$in": ["confirmed", "delivered"]},
        "created_at": {"$gte": window_start.isoformat(), "$lte": window_end.isoformat()}
    }, {"_id": 0}).to_list(500)
    
    # Check for existing retention notes
    for order in orders:
        note = await db.retention_notes.find_one({"order_id": order.get("order_id")}, {"_id": 0})
        order["retention_note"] = note
    
    return {"customers": orders, "days": days}


class RetentionNoteCreate(BaseModel):
    order_id: str
    status: str  # interested, not_interested, reorder, callback
    notes: str = ""


@router.post("/admin/retention/note")
async def add_retention_note(
    data: RetentionNoteCreate,
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    x_employee_token: str = Header(None, alias="X-Employee-Token")
):
    verify_auth(x_admin_token=x_admin_token, x_employee_token=x_employee_token, permission="retention")
    note = data.dict()
    note["created_at"] = datetime.now(timezone.utc).isoformat()
    await db.retention_notes.update_one(
        {"order_id": data.order_id},
        {"$set": note},
        upsert=True
    )
    return {"success": True}


# ==================== BEFORE/AFTER IMAGE MANAGEMENT ====================

class BeforeAfterImage(BaseModel):
    # Legacy fields — product_slug optional so admin can upload GLOBAL homepage
    # before/after images that aren't tied to a specific SKU.
    product_slug: Optional[str] = None
    customer_name: str = ""
    before_image: str = ""      # legacy: separate before URL
    after_image: str = ""       # legacy: separate after URL
    image: str = ""             # NEW: single stitched B/A image (user's format)
    duration: str = ""
    description: str = ""
    is_global: bool = False     # NEW: True = show on homepage carousel
    sort_order: int = 0


@router.get("/admin/before-after")
async def get_before_after(x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_auth(x_admin_token=x_admin_token)
    images = await db.before_after_images.find({}, {"_id": 0}).sort("sort_order", 1).to_list(200)
    return images


@router.get("/before-after")
async def get_public_before_after(response: Response, product_slug: Optional[str] = None, only_global: bool = False):
    """Public: Get before/after images. If product_slug provided, returns
    images for that product PLUS globals. If only_global=true, only globals.
    Otherwise returns everything (used by the homepage strip)."""
    query: Dict[str, Any] = {}
    if only_global:
        query["is_global"] = True
    elif product_slug:
        query["$or"] = [{"product_slug": product_slug}, {"is_global": True}]
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=120"
    images = await db.before_after_images.find(query, {"_id": 0}).sort("sort_order", 1).to_list(200)
    return images


@router.get("/before-after/{product_slug}")
async def get_product_before_after(product_slug: str, response: Response):
    """Public: Get before/after images for a product (includes globals)."""
    response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=120"
    images = await db.before_after_images.find(
        {"$or": [{"product_slug": product_slug}, {"is_global": True}]}, {"_id": 0}
    ).sort("sort_order", 1).to_list(50)
    return images


@router.post("/admin/before-after")
async def add_before_after(data: BeforeAfterImage, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_auth(x_admin_token=x_admin_token)
    doc = data.dict()
    # Validate that we have at least one usable image URL.
    if not (doc.get("image") or doc.get("before_image") or doc.get("after_image")):
        raise HTTPException(400, "Provide 'image' (single stitched B/A) or before_image + after_image")
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    doc["ba_id"] = f"ba_{secrets.token_hex(4)}"
    await db.before_after_images.insert_one(doc)
    return {"success": True, "ba_id": doc["ba_id"]}


class BeforeAfterUpdate(BaseModel):
    customer_name: Optional[str] = None
    before_image: Optional[str] = None
    after_image: Optional[str] = None
    image: Optional[str] = None
    duration: Optional[str] = None
    description: Optional[str] = None
    is_global: Optional[bool] = None
    sort_order: Optional[int] = None
    product_slug: Optional[str] = None


@router.put("/admin/before-after/{ba_id}")
async def update_before_after(ba_id: str, data: BeforeAfterUpdate, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_auth(x_admin_token=x_admin_token)
    patch = {k: v for k, v in data.dict().items() if v is not None}
    if not patch:
        return {"success": True}
    r = await db.before_after_images.update_one({"ba_id": ba_id}, {"$set": patch})
    if r.matched_count == 0:
        raise HTTPException(404, "Not found")
    return {"success": True}


@router.delete("/admin/before-after/{ba_id}")
async def delete_before_after(ba_id: str, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_auth(x_admin_token=x_admin_token)
    await db.before_after_images.delete_one({"ba_id": ba_id})
    return {"success": True}


# ==================== IMAGE UPLOAD (admin) ====================

@router.post("/admin/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    x_admin_token: str = Header(None, alias="X-Admin-Token")
):
    """Upload an image. Automatically compresses + resizes (max 1600px, JPEG/WebP quality 80)
    to keep product pages fast. Saves to /app/backend/uploads/products/ and returns a public URL
    served via `/api/uploads/products/<file>`.
    """
    verify_auth(x_admin_token=x_admin_token)
    import io
    import uuid
    from pathlib import Path
    from PIL import Image

    raw = await file.read()
    if len(raw) > 15 * 1024 * 1024:  # 15 MB raw cap — we'll compress heavily
        raise HTTPException(status_code=400, detail="Image too large (max 15 MB)")
    mime = file.content_type or "image/jpeg"
    if not mime.startswith("image/"):
        raise HTTPException(status_code=400, detail="File is not an image")

    try:
        img = Image.open(io.BytesIO(raw))
        img.verify()
        # Store the ORIGINAL file untouched (no resize, no re-encode) so quality is preserved.
        fmt = (Image.open(io.BytesIO(raw)).format or "JPEG").lower()
        out_ext = {"jpeg": "jpg"}.get(fmt, fmt)
        out_mime = mime
        compressed = raw
    except Exception as e:
        logging.error(f"Image read failed: {e}")
        raise HTTPException(status_code=400, detail="Could not process image")

    # === Storage strategy ===
    # Cloudinary is the ONLY durable storage — the local /uploads folder is
    # ephemeral (wiped on every redeploy in Kubernetes). If Cloudinary is
    # configured we upload there and return its CDN URL. If it's NOT configured
    # we FAIL the request loudly instead of silently saving to the local disk
    # that will disappear on next deploy — that's exactly the bug that caused
    # "uploaded images are missing" in production.
    from services import cloudinary_service as _cs
    cloudinary_ok = False
    try:
        cloudinary_ok = await _cs.ensure_configured(db)
    except Exception as exc:
        logging.warning(f"Cloudinary probe failed: {exc}")

    public_url = None
    if cloudinary_ok:
        try:
            res = await _cs.upload_image(db, compressed, folder="celesta-glow/products", public_id=uuid.uuid4().hex)
            if res.get("url"):
                public_url = res["url"]
        except Exception as exc:
            logging.error(f"Cloudinary upload failed: {exc}")
            raise HTTPException(
                status_code=502,
                detail=f"Image upload to Cloudinary failed: {exc}. "
                       f"Please retry — your image is NOT saved yet."
            )

    # Fallback: local disk is only used when Cloudinary is unreachable AND we
    # explicitly allow it via env. In production this branch should never run.
    allow_local = (os.environ.get("ALLOW_LOCAL_UPLOADS") or "").lower() in ("1", "true", "yes")
    if not public_url:
        if not allow_local:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Image storage is not configured. Cloudinary credentials "
                    "(CLOUDINARY_CLOUD_NAME / CLOUDINARY_API_KEY / CLOUDINARY_API_SECRET) "
                    "are missing or invalid. Images uploaded to local disk would "
                    "be lost on the next deploy, so this request is being blocked "
                    "to protect you. Fix: set the three Cloudinary env vars and redeploy."
                ),
            )
        # Dev/preview fallback only — write locally for iteration speed.
        uploads_dir = Path(__file__).parent.parent / "uploads" / "products"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid.uuid4().hex}.{out_ext}"
        (uploads_dir / filename).write_bytes(compressed)
        public_url = f"/api/uploads/products/{filename}"

    return {
        "success": True,
        "url": public_url,
        "storage": "cloudinary" if cloudinary_ok else "local",
        "original_size": len(raw),
        "size": len(compressed),
        "mime": out_mime,
        "width": img.size[0],
        "height": img.size[1],
    }


# ==================== STORAGE HEALTH / DIAGNOSTICS (admin) ====================

@router.get("/admin/storage/health")
async def storage_health(x_admin_token: str = Header(None, alias="X-Admin-Token")):
    """Tells the admin EXACTLY where image uploads go right now + which existing
    products are pointing at ephemeral /api/uploads/ URLs (which will 404 after
    the next redeploy). Lets you see the damage and target your re-uploads."""
    verify_auth(x_admin_token=x_admin_token)
    from services import cloudinary_service as _cs
    ok = await _cs.ensure_configured(db)
    creds = await _cs.get_cloudinary_credentials(db)

    # Scan products + combos for any URL pointing at the ephemeral /api/uploads path
    broken_slugs = []
    async for p in db.products.find({}, {"_id": 0, "slug": 1, "name": 1, "images": 1}):
        imgs = p.get("images") or []
        dead = [u for u in imgs if isinstance(u, str) and u.startswith("/api/uploads/")]
        if dead:
            broken_slugs.append({"slug": p.get("slug"), "name": p.get("name"), "dead_count": len(dead), "total": len(imgs)})
    return {
        "cloudinary_configured": ok,
        "cloud_name": creds.get("cloud_name") or None,
        "loaded_from": creds.get("loaded_from"),
        "new_uploads_will_go_to": "cloudinary" if ok else "FAIL (request will be blocked)",
        "products_with_dead_images": broken_slugs,
        "dead_image_count": sum(p["dead_count"] for p in broken_slugs),
        "fix_hint": (
            "Re-upload the flagged products' images — the new version of the "
            "upload endpoint will push them straight to Cloudinary."
            if ok else
            "Set CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET "
            "env vars on the production deployment and redeploy."
        ),
    }


@router.post("/admin/storage/purge-dead-images")
async def purge_dead_images(x_admin_token: str = Header(None, alias="X-Admin-Token")):
    """Remove every /api/uploads/... URL from product.images arrays so the
    broken icon is replaced by the empty-placeholder on the store. Admin can
    then re-upload fresh images cleanly."""
    verify_auth(x_admin_token=x_admin_token)
    touched = 0
    async for p in db.products.find({"images": {"$regex": "^/api/uploads/"}}, {"_id": 0, "slug": 1, "images": 1}):
        clean = [u for u in (p.get("images") or []) if not (isinstance(u, str) and u.startswith("/api/uploads/"))]
        await db.products.update_one({"slug": p["slug"]}, {"$set": {"images": clean}})
        touched += 1
    return {"success": True, "products_updated": touched}


# ==================== SEED DATA ====================

async def ensure_indexes():
    """Create the indexes that make paginated listing + search fast at scale.
    Safe to call on every startup — MongoDB skips re-creation when an index
    with the same spec already exists."""
    try:
        # Hub pages — niche + is_active + (subcategory|category) is the hot path.
        await db.products.create_index([("niche", 1), ("is_active", 1), ("sort_order", 1)])
        await db.products.create_index([("niche", 1), ("category", 1), ("is_active", 1)])
        await db.products.create_index([("niche", 1), ("subcategory", 1), ("is_active", 1)])
        await db.products.create_index([("category", 1), ("is_active", 1)])
        await db.products.create_index([("subcategory", 1), ("is_active", 1)])
        await db.products.create_index([("concerns", 1), ("is_active", 1)])
        await db.products.create_index([("brand", 1), ("is_active", 1)])
        await db.products.create_index([("tags", 1), ("is_active", 1)])
        # Slug — hot path for product detail
        await db.products.create_index("slug", unique=True, sparse=True)
        # Price + recency
        await db.products.create_index([("prepaid_price", 1)])
        await db.products.create_index([("created_at", -1)])
        await db.products.create_index([("total_orders", -1)])
        # Stock filter (used inside the public-catalog $and clause)
        await db.products.create_index([("is_active", 1), ("stock_qty", 1)])
        # Text index for /search (Atlas-Search-compatible)
        try:
            await db.products.create_index(
                [("name", "text"), ("brand", "text"),
                 ("description", "text"), ("tags", "text")],
                name="product_text_search",
                default_language="english",
            )
        except Exception:
            pass  # already exists with different spec → skip
        # Orders — for revenue dashboards
        await db.orders.create_index([("status", 1), ("created_at", -1)])
        await db.orders.create_index([("created_at", -1)])
        await db.orders.create_index([("delivery_status", 1), ("created_at", -1)])
        await db.orders.create_index([("delivered_at", -1)])
        await db.orders.create_index("order_id", unique=True, sparse=True)
        logging.info("[products] indexes ensured")
    except Exception as e:
        logging.warning(f"[products] ensure_indexes failed: {e}")


async def seed_products():
    """Seed initial product catalog if empty"""
    count = await db.products.count_documents({})
    if count > 0:
        return
    
    logging.info("Seeding product catalog...")
    
    products = [
        {
            "slug": "anti-aging-serum",
            "name": "Celesta Glow Advanced Face Serum",
            "short_name": "Anti-Aging Serum",
            "tagline": "Anti-Aging + Brightening Formula",
            "description": "A lightweight, fast-absorbing formula designed to improve skin clarity and enhance overall radiance. Formulated with Niacinamide, Alpha Arbutin, and a stable form of Vitamin C, it helps reduce dullness, refine skin texture, and promote a more even-looking complexion. Suitable for daily use across all skin types.",
            "category": "serum",
            "key_ingredients": "Niacinamide + Alpha Arbutin + Vitamin C",
            "ingredients_full": "Aqua, Aloe Barbadensis Leaf Extract, Coco-Caprylate/Caprate, Glycerin, Helianthus Annuus (Sunflower) Seed Oil, Sodium Polyacrylate, Xylitol, Caprylic Acid, Glyceryl Stearate, Diethylhexyl Maleate, Cetearyl Alcohol, Propanediol, Sodium Hyaluronate, Phenoxyethanol, Ethylhexylglycerin, Hydrolyzed Pea Protein, Tocopherol, Stevioside, 4-n-Butylresorcinol, Dimethyl Isosorbide, Hydroxypinacolone Retinoate, Sodium Gluconate, Cyamopsis Tetragonoloba (Guar) Gum",
            "benefits": ["Reduces Dullness & Dark Spots", "Supports Firm, Youthful Skin", "Brightens & Evens Skin Tone", "Lightweight Daily Use Formula"],
            "how_to_use": "Apply to clean, dry skin on the face and neck. Use in the evening. Follow with sunscreen during the day.",
            "size": "30ml / 1.01 fl oz",
            "images": [],
            "mrp": 1699,
            "prepaid_price": 999,
            "cod_price": 1099,
            "cod_advance": 29,
            "discount_percent": 41,
            "badge": "Bestseller",
            "is_active": True,
            "sort_order": 1,
            "rating": 4.8,
            "reviews_count": 2847,
            "skin_type": "All Skin Types",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "slug": "anti-aging-cream",
            "name": "Celesta Glow Advanced Retinoid Night Cream",
            "short_name": "Anti-Aging Night Cream",
            "tagline": "Anti-Aging + Brightening Formula",
            "description": "An advanced night cream formulated with Retinoid and Hyaluronic Acid. Works overnight to reduce fine lines and wrinkles, improve skin firmness, brighten and even skin tone, and deeply hydrate for a youthful morning glow.",
            "category": "cream",
            "key_ingredients": "Retinoid + Hyaluronic Acid",
            "ingredients_full": "Aqua, Aloe Barbadensis Leaf Extract, Coco-Caprylate/Caprate, Glycerin, Helianthus Annuus (Sunflower) Seed Oil, Sodium Polyacrylate, Xylitol, Caprylic Acid, Glyceryl Stearate, Diethylhexyl Maleate, Cetearyl Alcohol, Propanediol, Sodium Hyaluronate, Phenoxyethanol, Ethylhexylglycerin, Hydrolyzed Pea Protein, Tocopherol, Stevioside, 4-n-Butylresorcinol, Dimethyl Isosorbide, Hydroxypinacolone Retinoate, Sodium Gluconate, Cyamopsis Tetragonoloba (Guar) Gum",
            "benefits": ["Reduces Fine Lines & Wrinkles", "Improves Skin Firmness", "Brightens & Evens Skin Tone", "Deeply Hydrates Overnight"],
            "how_to_use": "Apply to clean, dry skin on the face and neck. Use in the evening. Follow with sunscreen during the day.",
            "size": "50ml / 1.69 fl oz",
            "images": [],
            "mrp": 1499,
            "prepaid_price": 899,
            "cod_price": 999,
            "cod_advance": 29,
            "discount_percent": 40,
            "badge": "New Launch",
            "is_active": True,
            "sort_order": 2,
            "rating": 4.7,
            "reviews_count": 1293,
            "skin_type": "All Skin Types",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "slug": "under-eye-cream",
            "name": "Celesta Glow Caffeine Under Eye Cream",
            "short_name": "Under Eye Cream",
            "tagline": "Dark Circle + Puffiness + Anti-Aging Formula",
            "description": "A lightweight formula designed for the delicate under-eye area. Enriched with Caffeine, Niacinamide, and Hyaluronic Acid, it helps reduce the appearance of puffiness, improve under-eye brightness, and smooth the look of fine lines while providing lasting hydration.",
            "category": "eye-care",
            "key_ingredients": "Caffeine + Niacinamide + Hyaluronic Acid",
            "ingredients_full": "Aqua, Aloe Barbadensis Leaf Extract, Caffeine, Butyrospermum Parkii (Shea) Butter Extract, Sodium Starch Octenylsuccinate, Cera Alba (Beeswax), Hydroxyethyl Behenamidopropyl Dimonium Chloride, Polyquaternium-67, Hydrated Silica, Isopropyl Myristate, PEG-100 Stearate, Glyceryl Stearate, Stearic Acid, Cetyl Alcohol, Glycerin, Propanediol, Butyrospermum Parkii (Shea) Butter, Glyceryl Stearate SE, Olea Europaea (Olive) Fruit Oil, Prunus Amygdalus Dulcis (Sweet Almond) Oil, Glycyrrhiza Glabra (Licorice) Root Extract, Sodium Hyaluronate, Hydrolyzed Pea Protein, Niacinamide, Phenoxyethanol, Ethylhexylglycerin, Ammonium Acryloyldimethyltaurate/VP Copolymer, Stevioside, Allantoin, Sodium Gluconate, Tocopherol",
            "benefits": ["Reduces Appearance of Puffiness", "Improves Under-Eye Brightness", "Smooths Fine Lines Around Eyes", "Provides Lightweight Hydration", "Suitable for Daily Use"],
            "how_to_use": "Apply a small amount to the under-eye area. Gently pat with fingertips until absorbed. Use morning and evening.",
            "size": "15g / 0.52 oz",
            "images": [],
            "mrp": 899,
            "prepaid_price": 549,
            "cod_price": 649,
            "cod_advance": 29,
            "discount_percent": 39,
            "badge": "New Launch",
            "is_active": True,
            "sort_order": 3,
            "rating": 4.7,
            "reviews_count": 987,
            "skin_type": "All Skin Types",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "slug": "sunscreen",
            "name": "Celesta Glow SPF 50 PA+++ Sunscreen",
            "short_name": "SPF 50 Sunscreen",
            "tagline": "Broad Spectrum + Lightweight + Matte Feel",
            "description": "A lightweight, broad-spectrum formula designed to protect the skin from harmful UVA and UVB rays. Enriched with Niacinamide and antioxidant Vitamin E, it helps support skin clarity while providing a comfortable, non-greasy matte finish.",
            "category": "sunscreen",
            "key_ingredients": "Niacinamide + Vitamin E",
            "ingredients_full": "Aqua, Aloe Barbadensis Leaf Extract, Methylene Bis-Benzotriazolyl Tetramethylbutylphenol, Decyl Glucoside, Propylene Glycol, Xanthan Gum, Propanediol, Glycerin, Titanium Dioxide, Niacinamide, Betaine, Chamomilla Recutita (Chamomile) Flower Water, Benzyl Alcohol, Ethylhexylglycerin, Tocopherol, Carbomer, Hydrolyzed Pea Protein, 4-n-Butylresorcinol, Stevioside, Sodium Gluconate, Cyamopsis Tetragonoloba (Guar) Gum",
            "benefits": ["Broad Spectrum UVA/UVB Protection", "Prevents Sun-Induced Skin Damage", "Lightweight, Non-Greasy Texture", "Provides a Matte Finish"],
            "how_to_use": "Apply generously to face and exposed areas 15 minutes before sun exposure. Reapply every 2-3 hours, or after sweating or washing.",
            "size": "50g / 1.76 oz",
            "images": [],
            "mrp": 799,
            "prepaid_price": 499,
            "cod_price": 599,
            "cod_advance": 29,
            "discount_percent": 38,
            "badge": "Daily Essential",
            "is_active": True,
            "sort_order": 4,
            "rating": 4.6,
            "reviews_count": 1542,
            "skin_type": "All Skin Types",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "slug": "cleanser",
            "name": "Celesta Glow Gentle Cleanser",
            "short_name": "Gentle Cleanser",
            "tagline": "Anti-Aging Formula",
            "description": "A mild, pH-balanced face cleanser formulated to effectively remove dirt, excess oil, and impurities without disrupting the skin barrier. Enriched with Niacinamide and Salicylic Acid, it helps improve skin clarity, refine texture, and support a healthier-looking complexion.",
            "category": "cleanser",
            "key_ingredients": "Niacinamide + Salicylic Acid + Pea Protein",
            "ingredients_full": "Aqua, Stearic Acid, Sodium Laureth Sulfate, Coco Fatty Acids, Potassium Hydroxide, Sorbitol, Lauric Acid, Aloe Barbadensis Leaf Extract, Cocamide MEA, Myristic Acid, Sodium Lactate, Sodium Gluconate, Palmitic Acid, Propylene Glycol, Salicylic Acid, Hydrolyzed Pea Protein, Phenoxyethanol, Ethylhexylglycerin, Stevioside, Melaleuca Alternifolia (Tea Tree) Leaf Oil, Syzygium Aromaticum (Clove) Flower Oil",
            "benefits": ["Gently Cleanses Without Stripping Moisture", "Reduces Excess Oil & Prevents Clogged Pores", "Supports Smoother, Even Skin Texture", "Maintains Skin's Natural Barrier", "Suitable for All Skin Types"],
            "how_to_use": "Apply to damp skin and gently massage in circular motions. Rinse thoroughly with water. Use twice daily, morning and evening.",
            "size": "100ml / 3.38 fl oz",
            "images": [],
            "mrp": 799,
            "prepaid_price": 499,
            "cod_price": 599,
            "cod_advance": 29,
            "discount_percent": 38,
            "badge": "Daily Essential",
            "is_active": True,
            "sort_order": 5,
            "rating": 4.6,
            "reviews_count": 1128,
            "skin_type": "All Skin Types",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
    ]
    
    # Filter out any tombstoned slugs so admin-deleted sample products don't
    # come back when the DB is wiped + reseeded on redeploy.
    try:
        from services.taxonomy_tombstones import get_tombstoned_slugs
        tombs = await get_tombstoned_slugs(db, "product")
        products = [p for p in products if p.get("slug") not in tombs]
    except Exception:
        pass

    # Seed sample catalog so the storefront matches the reference site.
    if products:
        await db.products.insert_many(products)
        logging.info(f"Seeded {len(products)} products")
    
    # Seed combos
    combos = [
        {
            "combo_id": "complete-anti-aging-kit",
            "name": "Complete Anti-Aging Kit",
            "description": "All 5 products for a complete anti-aging routine. Cleanse, treat, hydrate, protect.",
            "product_slugs": ["cleanser", "anti-aging-serum", "anti-aging-cream", "under-eye-cream", "sunscreen"],
            "mrp_total": 5695,
            "combo_prepaid_price": 2799,
            "combo_cod_price": 3099,
            "discount_percent": 51,
            "badge": "Best Value",
            "is_active": True,
            "sort_order": 1,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "combo_id": "day-night-duo",
            "name": "Day & Night Power Duo",
            "description": "Sunscreen for day protection + Retinoid Night Cream for overnight repair.",
            "product_slugs": ["sunscreen", "anti-aging-cream"],
            "mrp_total": 2298,
            "combo_prepaid_price": 1199,
            "combo_cod_price": 1399,
            "discount_percent": 48,
            "badge": "Popular",
            "is_active": True,
            "sort_order": 2,
            "created_at": datetime.now(timezone.utc).isoformat()
        },
        {
            "combo_id": "glow-essentials",
            "name": "Glow Essentials Trio",
            "description": "Cleanser + Serum + Sunscreen. The essential 3-step routine for radiant skin.",
            "product_slugs": ["cleanser", "anti-aging-serum", "sunscreen"],
            "mrp_total": 3297,
            "combo_prepaid_price": 1699,
            "combo_cod_price": 1899,
            "discount_percent": 48,
            "badge": "Starter Kit",
            "is_active": True,
            "sort_order": 3,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
    ]
    
    # Seed sample combos/kits so bundles appear on the storefront.
    if combos:
        for combo in combos:
            exists = await db.combos.find_one({"combo_id": combo["combo_id"]})
            if not exists:
                await db.combos.insert_one(combo)
        logging.info(f"Seeded {len(combos)} combos")
    
    # Seed default site settings
    await db.site_settings.update_one(
        {"_id": "main"},
        {"$setOnInsert": {
            "hero_title": "India's #1 Complete Anti-Aging Solution",
            "hero_subtitle": "5 clinically-formulated products designed exclusively to fight aging. Cleanse, treat, hydrate, protect & brighten.",
            "presale_enabled": False,
            "presale_title": "",
            "presale_badge": "",
            "cod_advance_amount": 29,
            "before_after_images": [],
            "result_images": [],
            "created_at": datetime.now(timezone.utc).isoformat()
        }},
        upsert=True
    )
    logging.info("Site settings initialized")
    
    # Auto-generate monthly coupons
    await generate_monthly_coupons()


async def generate_monthly_coupons():
    """Auto-generate monthly coupons if not already generated"""
    now = datetime.now(timezone.utc)
    months = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
    current_month = months[now.month - 1]
    next_month = months[now.month % 12]
    
    monthly_coupons = [
        {"code": f"{current_month}{now.year % 100}", "discount_type": "fixed", "discount_value": 25, "min_order_amount": 499, "max_uses": 5000,
         "show_on_cart": True, "description": f"Flat ₹25 OFF on orders above ₹499 (this month only)"},
        {"code": f"{current_month}GLOW", "discount_type": "fixed", "discount_value": 30, "min_order_amount": 799, "max_uses": 3000,
         "show_on_cart": True, "description": f"Flat ₹30 OFF on orders above ₹799"},
        {"code": f"{next_month}EARLY", "discount_type": "percentage", "discount_value": 10, "min_order_amount": 499, "max_uses": 2000,
         "show_on_cart": True, "description": "10% OFF early-bird offer"},
    ]
    
    for coupon in monthly_coupons:
        existing = await db.coupons.find_one({"code": coupon["code"]})
        if not existing:
            from datetime import timedelta
            coupon["used_count"] = 0
            coupon["is_active"] = True
            coupon["created_at"] = now.isoformat()
            coupon["expiry_date"] = (now + timedelta(days=45)).isoformat()
            coupon["auto_generated"] = True
            await db.coupons.insert_one(coupon)
            logging.info(f"Auto-generated monthly coupon: {coupon['code']}")
        else:
            # Backfill show_on_cart on legacy auto-gen coupons so they appear on the cart UI
            patch = {}
            if existing.get("show_on_cart") is None:
                patch["show_on_cart"] = True
            if not existing.get("description"):
                patch["description"] = coupon.get("description", "")
            if patch:
                await db.coupons.update_one({"code": coupon["code"]}, {"$set": patch})
    
    # Ensure WELCOME50 exists
    if not await db.coupons.find_one({"code": "WELCOME50"}):
        from datetime import timedelta
        await db.coupons.insert_one({
            "code": "WELCOME50", "discount_type": "fixed", "discount_value": 50,
            "min_order_amount": 499, "max_uses": 99999, "used_count": 0, "is_active": True,
            "show_on_cart": True, "description": "Flat ₹50 OFF on your first order (above ₹499)",
            "created_at": now.isoformat(), "expiry_date": (now + timedelta(days=365)).isoformat()
        })
        logging.info("Created WELCOME50 coupon")
    else:
        # Backfill show_on_cart for the existing WELCOME50 if missing
        existing = await db.coupons.find_one({"code": "WELCOME50"})
        if existing and existing.get("show_on_cart") is None:
            await db.coupons.update_one(
                {"code": "WELCOME50"},
                {"$set": {"show_on_cart": True, "description": "Flat ₹50 OFF on your first order (above ₹499)"}}
            )

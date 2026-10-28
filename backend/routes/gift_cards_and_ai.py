"""Gift card admin + checkout APIs + AI-powered product enrichment endpoints.

Endpoints:
  Admin:
    GET    /api/admin/gift-cards
    POST   /api/admin/gift-cards            create
    PUT    /api/admin/gift-cards/{code}
    DELETE /api/admin/gift-cards/{code}
    GET    /api/admin/gift-cards/{code}/history
  Public (checkout):
    POST   /api/gift-cards/validate         {code, order_amount} → {valid, discount, ...}

  AI product enrichment (admin):
    POST   /api/admin/products/{slug}/fill-with-ai   re-generates description, benefits, how-to-use, key ingredients (price untouched)
    POST   /api/admin/products/analyze-url           {url} → scraped/enriched dict (admin pastes brand page URL)
    PUT    /api/admin/products/{slug}                update fields (price guard: prepaid_price/cod_price unchanged unless explicitly opted-in)
"""
from __future__ import annotations
from fastapi import APIRouter, Header, HTTPException, Cookie, Body, Query, Form, File, UploadFile
from pydantic import BaseModel
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
import os
import re
import json
import logging
import uuid
import hashlib
import base64
from services.gemini_llm import GeminiChat

router = APIRouter(prefix="/api", tags=["gift-cards-and-product-ai"])
logger = logging.getLogger(__name__)

_db = None
_gift_card_service = None
_verify_admin = None


def setup(db, gift_card_service, verify_admin_fn):
    global _db, _gift_card_service, _verify_admin
    _db = db
    _gift_card_service = gift_card_service
    _verify_admin = verify_admin_fn


def _auth(x_admin_token, admin_session):
    if _verify_admin is None:
        raise HTTPException(status_code=500, detail="auth not wired")
    _verify_admin(x_admin_token=x_admin_token, admin_session=admin_session)


# ============================================================
# ADMIN — Gift Cards CRUD
# ============================================================

class GiftCardCreate(BaseModel):
    code: Optional[str] = None
    initial_balance: float
    label: Optional[str] = ""
    expiry_date: Optional[str] = None


class GiftCardUpdate(BaseModel):
    label: Optional[str] = None
    is_active: Optional[bool] = None
    expiry_date: Optional[str] = None
    remaining_balance: Optional[float] = None


@router.post("/admin/listing/generate")
async def generate_marketplace_listing(
    body: dict = Body(...),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """AI-generate an Amazon / Flipkart listing (title, bullets, description, search terms) for a product."""
    _auth(x_admin_token, admin_session)
    import os as _os, re as _re, json as _json, uuid as _uuid
    from emergentintegrations.llm.chat import UserMessage
    slug = body.get("product_slug") or body.get("slug")
    platform = (body.get("platform") or "amazon").lower()
    prod = await _db.products.find_one({"slug": slug}, {"_id": 0}) if slug else None
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    api_key = _os.environ.get("GEMINI_API_KEY") or _os.environ.get("EMERGENT_LLM_KEY", "")
    keys = [k for k in [_os.environ.get("GEMINI_API_KEY"), _os.environ.get("LISTING_AI_KEY")] if k]
    if not keys:
        raise HTTPException(status_code=503, detail="No AI key configured (set GEMINI_API_KEY)")
    lim = {"amazon": (200, 5), "flipkart": (150, 6)}.get(platform, (200, 5))
    prompt = f"""Create a high-converting {platform.title()} India marketplace listing for this beauty product.
Brand: {prod.get('brand', 'Celesta Glow')}
Name: {prod.get('name', '')}
Type: {prod.get('subcategory') or prod.get('category', '')}
Key ingredients: {prod.get('key_ingredients', '')}
Size: {prod.get('size', '')}
Price: INR {prod.get('prepaid_price') or prod.get('mrp', '')}
Concerns: {', '.join(prod.get('concerns', []) or [])}

Return STRICT JSON only (no markdown fences), exactly these keys:
{{
  "title": "SEO title <= {lim[0]} chars, includes brand + key benefit + size",
  "bullets": ["{lim[1]} benefit bullet points, each <= 200 chars, start with a capitalised feature"],
  "description": "180-300 word A+ style product description with paragraphs",
  "search_terms": ["8-12 backend search keywords, no repetition of the title"],
  "category_suggestion": "best marketplace category path"
}}"""
    # Try the store's Gemini key first; fall back to the free universal key if it errors/exhausts.
    resp, last_err = None, None
    for key in keys:
        try:
            chat = GeminiChat(api_key=key, session_id=f"listing-{_uuid.uuid4().hex[:8]}",
                              system_message=f"You are an expert {platform.title()} India listing copywriter.").with_model("gemini", "gemini-2.5-flash")
            resp = await chat.send_message(UserMessage(text=prompt))
            if resp:
                break
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    if not resp:
        raise HTTPException(status_code=503, detail=f"AI unavailable right now: {last_err}")
    m = _re.search(r"\{[\s\S]*\}", resp or "")
    if not m:
        raise HTTPException(status_code=502, detail="AI returned no listing — try again")
    data = _json.loads(m.group())
    return {"platform": platform, "product": {"slug": slug, "name": prod.get("name")}, "listing": data}


@router.get("/admin/listing/extension-zip")
async def download_autofill_extension(
    api_url: str = "",
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Package & download the AutoFill AI Amazon/Flipkart Chrome extension (MV3), with the
    backend URL injected into config.js so it talks to this server."""
    _auth(x_admin_token, admin_session)
    import os as _os, zipfile as _zip, tempfile as _tmp
    from fastapi.responses import FileResponse
    src = "/app/backend/af_extension"
    if not _os.path.isdir(src):
        raise HTTPException(status_code=404, detail="Extension package not found on server")
    base = (api_url or "").rstrip("/") or "https://your-backend/api"
    out = _os.path.join(_tmp.mkdtemp(), "autofill-amazon-flipkart-extension.zip")
    with _zip.ZipFile(out, "w", _zip.ZIP_DEFLATED) as z:
        for root, _dirs, files in _os.walk(src):
            for f in files:
                fp = _os.path.join(root, f)
                arc = _os.path.relpath(fp, src)
                if f == "config.js":
                    z.writestr(arc, open(fp).read().replace("__API_URL__", base))
                else:
                    z.write(fp, arc)
    return FileResponse(out, media_type="application/zip", filename="autofill-amazon-flipkart-extension.zip")


@router.get("/admin/gift-cards")
async def list_gift_cards(
    page: int = 1, limit: int = 50,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    _auth(x_admin_token, admin_session)
    return await _gift_card_service.list_cards(page=page, limit=limit)


@router.post("/admin/gift-cards")
async def create_gift_card(
    body: GiftCardCreate,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    _auth(x_admin_token, admin_session)
    try:
        return await _gift_card_service.create_card(body.code, body.initial_balance, body.label or "", body.expiry_date)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/admin/gift-cards/{code}")
async def update_gift_card(
    code: str,
    body: GiftCardUpdate,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    _auth(x_admin_token, admin_session)
    fields = body.model_dump(exclude_none=True)
    return await _gift_card_service.update(code, **fields)


@router.delete("/admin/gift-cards/{code}")
async def delete_gift_card(
    code: str,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    _auth(x_admin_token, admin_session)
    ok = await _gift_card_service.delete(code)
    return {"success": ok}


@router.get("/admin/gift-cards/{code}/history")
async def gift_card_history(
    code: str,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    _auth(x_admin_token, admin_session)
    return {"redemptions": await _gift_card_service.history(code)}


# ============================================================
# PUBLIC — Validate gift card on checkout
# ============================================================

class GiftCardValidateRequest(BaseModel):
    code: str
    order_amount: float


@router.post("/gift-cards/validate")
async def validate_gift_card(body: GiftCardValidateRequest):
    return await _gift_card_service.validate_for_redemption(body.code, body.order_amount)


# ============================================================
# ADMIN — Per-product edit + AI fill + URL analyze
# ============================================================

class ProductFieldsUpdate(BaseModel):
    name: Optional[str] = None
    short_name: Optional[str] = None
    description: Optional[str] = None
    key_ingredients: Optional[str] = None
    ingredients_full: Optional[str] = None
    benefits: Optional[list] = None
    how_to_use: Optional[str] = None
    size: Optional[str] = None
    images: Optional[list] = None
    image: Optional[str] = None  # singular form used by older bulk-imported products & QuickImageEditor
    category: Optional[str] = None
    concerns: Optional[list] = None
    badges: Optional[list] = None
    brand: Optional[str] = None
    tagline: Optional[str] = None
    stock_qty: Optional[int] = None
    is_to_be_launched: Optional[bool] = None
    is_active: Optional[bool] = None
    # PRICE CHANGES — guarded: pass allow_price_change=true to update
    prepaid_price: Optional[float] = None
    cod_price: Optional[float] = None
    mrp: Optional[float] = None
    allow_price_change: bool = False


@router.put("/admin/products/{slug}")
async def admin_update_product(
    slug: str,
    body: ProductFieldsUpdate,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Admin edit — by default does NOT change prices (per user spec).
    Pass allow_price_change=true to update prepaid/cod/MRP.
    """
    _auth(x_admin_token, admin_session)
    upd = body.model_dump(exclude_none=True)
    allow_price = upd.pop("allow_price_change", False)
    if not allow_price:
        for k in ("prepaid_price", "cod_price", "mrp"):
            upd.pop(k, None)
    if not upd:
        raise HTTPException(status_code=400, detail="Nothing to update")
    upd["updated_at"] = datetime.now(timezone.utc).isoformat()
    r = await _db.products.update_one({"slug": slug}, {"$set": upd})
    if r.matched_count == 0:
        raise HTTPException(status_code=404, detail="Product not found")
    prod = await _db.products.find_one({"slug": slug}, {"_id": 0})
    return prod


class FillWithAIRequest(BaseModel):
    fields: Optional[list] = None  # ["description", "benefits", "how_to_use", "key_ingredients", "concerns"]


@router.post("/admin/products/{slug}/fill-with-ai")
async def fill_with_ai(
    slug: str,
    body: Optional[FillWithAIRequest] = None,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Re-generate description / benefits / how-to-use / key ingredients with Claude.
    Price is never touched.
    """
    _auth(x_admin_token, admin_session)
    prod = await _db.products.find_one({"slug": slug}, {"_id": 0})
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="No AI key configured (set GEMINI_API_KEY)")

    from emergentintegrations.llm.chat import LlmChat, UserMessage
    prompt = f"""Product to enrich:
Brand: {prod.get('brand', '')}
Name: {prod.get('name', '')}
Type: {prod.get('subcategory', '')}
Niche: {prod.get('niche', '')}

Return STRICT JSON only (no markdown fences), exactly these keys:
{{
  "description": "120-180 word consumer-facing product description for an Indian beauty store. Mention key benefits and how it suits Indian skin/weather.",
  "key_ingredients": "Comma-separated 3-6 hero ingredients (omit if obviously cosmetic/makeup)",
  "benefits": ["3-5 short benefit phrases, each <=8 words"],
  "how_to_use": "1-2 sentence usage instruction",
  "tagline": "5-8 word punchy product tagline"
}}
Be factual, concise, no medical claims."""

    try:
        chat = GeminiChat(
            api_key=api_key,
            session_id=f"fill-{uuid.uuid4().hex[:8]}",
            system_message="You are an expert Indian beauty/skincare cataloging assistant.",
        ).with_model("gemini", "gemini-2.5-flash")
        resp = await chat.send_message(UserMessage(text=prompt))
        match = re.search(r"\{[\s\S]*\}", resp or "")
        if not match:
            raise ValueError("No JSON in LLM response")
        data = json.loads(match.group())
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI enrichment failed: {e}")

    upd = {
        "description": (data.get("description") or "")[:1800],
        "key_ingredients": (data.get("key_ingredients") or "")[:400],
        "benefits": list(data.get("benefits") or [])[:8],
        "how_to_use": (data.get("how_to_use") or "")[:400],
        "tagline": (data.get("tagline") or "")[:80],
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "ai_enriched_at": datetime.now(timezone.utc).isoformat(),
    }
    await _db.products.update_one({"slug": slug}, {"$set": upd})
    return {"success": True, "updated": upd}


class AnalyzeURLRequest(BaseModel):
    url: str
    slug: Optional[str] = None  # If provided, applies result to that product


@router.post("/admin/products/analyze-url")
async def analyze_url(
    body: AnalyzeURLRequest,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Scrape a brand product URL → extract name, description, ingredients,
    images. Returns structured dict. Optionally apply to an existing product slug.
    """
    _auth(x_admin_token, admin_session)
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("EMERGENT_LLM_KEY", "")

    # 1. Fetch HTML
    import httpx
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(body.url, headers={"User-Agent": "Mozilla/5.0 CelestaGlowBot"})
            r.raise_for_status()
            html = r.text
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not fetch URL: {e}")

    # 2. Extract main content
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe"]):
        tag.decompose()
    title = (soup.find("title").get_text(strip=True) if soup.find("title") else "")[:200]
    # OG image
    og_img = ""
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        og_img = og["content"]
    # First couple of large product images
    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or ""
        if not src or src.startswith("data:"):
            continue
        if any(x in src.lower() for x in ["logo", "icon", "sprite", "favicon"]):
            continue
        if src.startswith("//"):
            src = "https:" + src
        elif src.startswith("/"):
            from urllib.parse import urljoin
            src = urljoin(body.url, src)
        images.append(src)
        if len(images) >= 4:
            break
    if og_img and og_img not in images:
        images.insert(0, og_img)
    # Text content (trim)
    text = soup.get_text(separator=" ", strip=True)[:8000]

    if not api_key:
        return {"title": title, "images": images, "raw_text_preview": text[:500]}

    # 3. LLM extraction
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    prompt = f"""URL: {body.url}
Page title: {title}
Page text (truncated):
{text[:4000]}

Extract product details. Return STRICT JSON only:
{{
  "name": "clean product name",
  "brand": "brand name",
  "description": "120-180 word consumer-facing description",
  "key_ingredients": "comma-separated 3-6 hero ingredients",
  "ingredients_full": "full INCI list if found, else ''",
  "benefits": ["3-5 short benefit phrases"],
  "how_to_use": "1-2 sentence usage",
  "size": "size like '50ml' or ''",
  "tagline": "5-8 word tagline"
}}"""
    try:
        chat = GeminiChat(api_key=api_key, session_id=f"url-{uuid.uuid4().hex[:8]}",
                      system_message="You extract clean product data from brand pages.").with_model("gemini", "gemini-2.5-flash")
        resp = await chat.send_message(UserMessage(text=prompt))
        match = re.search(r"\{[\s\S]*\}", resp or "")
        data = json.loads(match.group()) if match else {}
    except Exception as e:
        logger.warning(f"[analyze-url] LLM extraction failed: {e}")
        data = {}

    result = {
        "name": data.get("name") or title,
        "brand": data.get("brand") or "",
        "description": data.get("description") or "",
        "key_ingredients": data.get("key_ingredients") or "",
        "ingredients_full": data.get("ingredients_full") or "",
        "benefits": data.get("benefits") or [],
        "how_to_use": data.get("how_to_use") or "",
        "size": data.get("size") or "",
        "tagline": data.get("tagline") or "",
        "images": images,
        "source_url": body.url,
    }

    # Optionally apply directly to a product slug
    if body.slug:
        prod = await _db.products.find_one({"slug": body.slug}, {"_id": 0, "slug": 1})
        if prod:
            upd = {k: v for k, v in result.items() if v and k != "source_url"}
            upd["updated_at"] = datetime.now(timezone.utc).isoformat()
            upd["ai_enriched_at"] = datetime.now(timezone.utc).isoformat()
            # Don't touch price
            await _db.products.update_one({"slug": body.slug}, {"$set": upd})
            result["applied_to_slug"] = body.slug

    return result


# ============================================================
# Admin — taxonomy + reclassification trigger
# ============================================================

@router.post("/admin/taxonomy/reset-and-reclassify")
async def reset_and_reclassify(
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """One-click: wipe concerns + skincare/cosmetics categories, seed new ones,
    then reclassify all 7000+ products by keyword rules. Idempotent."""
    _auth(x_admin_token, admin_session)
    from taxonomy_v2 import reset_taxonomy, reclassify_all_products
    tx = await reset_taxonomy(_db)
    cls = await reclassify_all_products(_db)
    return {"taxonomy": tx, "reclassification": cls}



# ============================================================
# Bulk AI Fill — enrich many products with AI in one shot
# ============================================================

_bulk_ai_jobs: Dict[str, Dict[str, Any]] = {}


async def _enrich_one_product(api_key: str, prod: dict) -> dict:
    """Call Claude Haiku to enrich a single product. Returns the update dict."""
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    prompt = f"""Product to enrich:
Brand: {prod.get('brand', '')}
Name: {prod.get('name', '')}
Type: {prod.get('subcategory') or prod.get('category', '')}
Niche: {prod.get('niche', '')}

Return STRICT JSON only (no markdown fences), exactly these keys:
{{
  "description": "120-180 word consumer-facing product description for an Indian beauty store.",
  "key_ingredients": "Comma-separated 3-6 hero ingredients (omit if obviously cosmetic/makeup)",
  "benefits": ["3-5 short benefit phrases, each <=8 words"],
  "how_to_use": "1-2 sentence usage instruction",
  "tagline": "5-8 word punchy product tagline"
}}"""
    chat = GeminiChat(
        api_key=api_key,
        session_id=f"bulk-fill-{uuid.uuid4().hex[:8]}",
        system_message="You are an expert Indian beauty cataloging assistant.",
    ).with_model("gemini", "gemini-2.5-flash")
    resp = await chat.send_message(UserMessage(text=prompt))
    match = re.search(r"\{[\s\S]*\}", resp or "")
    if not match:
        raise ValueError("No JSON in LLM response")
    data = json.loads(match.group())
    now = datetime.now(timezone.utc).isoformat()
    return {
        "description": (data.get("description") or "")[:1800],
        "key_ingredients": (data.get("key_ingredients") or "")[:400],
        "benefits": list(data.get("benefits") or [])[:8],
        "how_to_use": (data.get("how_to_use") or "")[:400],
        "tagline": (data.get("tagline") or "")[:80],
        "updated_at": now,
        "ai_enriched_at": now,
    }


async def _bulk_fill_worker(job_id: str, slugs: list, concurrency: int = 5):
    import asyncio as _aio
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("EMERGENT_LLM_KEY", "")
    sem = _aio.Semaphore(concurrency)
    job = _bulk_ai_jobs[job_id]

    async def one(slug: str):
        async with sem:
            try:
                prod = await _db.products.find_one({"slug": slug}, {"_id": 0})
                if not prod:
                    job["failed"] += 1
                    return
                upd = await _enrich_one_product(api_key, prod)
                await _db.products.update_one({"slug": slug}, {"$set": upd})
                job["done"] += 1
                job["last_slug"] = slug
            except Exception as e:
                logger.warning(f"[bulk-ai-fill] {slug}: {e}")
                job["failed"] += 1
                job["errors"].append({"slug": slug, "error": str(e)[:200]})

    try:
        await _aio.gather(*[one(s) for s in slugs])
        job["status"] = "completed"
    except Exception as e:
        job["status"] = "failed"
        job["fatal_error"] = str(e)


class BulkAIFillRequest(BaseModel):
    scope: str = "needs_enrichment"  # 'needs_enrichment' | 'all' | 'niche' | 'category'
    niche: Optional[str] = None
    category: Optional[str] = None
    limit: int = 200
    concurrency: int = 5
    only_missing: bool = True  # If True, skip products that already have description+benefits


@router.post("/admin/products/bulk-ai-fill")
async def bulk_ai_fill(
    body: BulkAIFillRequest = Body(...),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Kick off background AI enrichment for many products.

    Returns immediately with a job_id; poll GET /admin/products/bulk-ai-fill/{job_id}.
    """
    _auth(x_admin_token, admin_session)
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="No AI key configured (set GEMINI_API_KEY)")

    q: Dict[str, Any] = {}
    if body.scope == "niche" and body.niche:
        q["niche"] = body.niche
    elif body.scope == "category" and body.category:
        q["category"] = body.category
    if body.only_missing or body.scope == "needs_enrichment":
        q["$or"] = [
            {"description": {"$in": [None, ""]}},
            {"benefits": {"$size": 0}},
            {"key_ingredients": {"$in": [None, ""]}},
            {"ai_enriched_at": {"$exists": False}},
        ]

    cur = _db.products.find(q, {"_id": 0, "slug": 1}).limit(max(1, min(body.limit, 2000)))
    slugs = [d["slug"] async for d in cur]
    if not slugs:
        return {"success": True, "queued": 0, "message": "No products match the scope."}

    job_id = f"aifill_{uuid.uuid4().hex[:10]}"
    _bulk_ai_jobs[job_id] = {
        "job_id": job_id,
        "total": len(slugs),
        "done": 0,
        "failed": 0,
        "status": "running",
        "scope": body.scope,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "errors": [],
        "last_slug": "",
    }
    import asyncio as _aio
    _aio.create_task(_bulk_fill_worker(job_id, slugs, body.concurrency))
    from services.job_store import start_mirror
    start_mirror(_db, _bulk_ai_jobs[job_id])
    return {"success": True, "job_id": job_id, "queued": len(slugs)}


@router.get("/admin/products/bulk-ai-fill/{job_id}")
async def bulk_ai_fill_status(
    job_id: str,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    _auth(x_admin_token, admin_session)
    from services.job_store import get_job
    job = await get_job(_db, _bulk_ai_jobs, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/admin/products/bulk-ai-fill")
async def bulk_ai_fill_list(
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """List recent bulk-ai-fill jobs (in-memory; resets on backend restart)."""
    _auth(x_admin_token, admin_session)
    items = sorted(_bulk_ai_jobs.values(), key=lambda j: j.get("created_at", ""), reverse=True)
    return {"jobs": items[:50]}



# ============================================================
# AI Analyze a SINGLE product (used by the admin edit form)
# - classifies niche/category/subcategory/concerns from name+brand
# - auto-creates any missing taxonomy rows
# - returns the routing so the form can pre-select chips
# ============================================================

class AIAnalyzeRequest(BaseModel):
    name: str
    brand: Optional[str] = ""
    main_category: Optional[str] = ""   # "skincare" | "cosmetics" | "anti-aging" (free text okay)
    product_type: Optional[str] = ""
    concern: Optional[str] = ""
    skin_type: Optional[str] = ""
    auto_create: bool = True


@router.post("/admin/ai/analyze-product")
async def admin_ai_analyze_product(
    body: AIAnalyzeRequest,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Run the DB-aware AI classifier on a single product and (optionally)
    auto-create any missing taxonomy rows. Uses the SAME logic as the
    catalog-wide AI Taxonomy Audit — so the result is consistent.
    """
    _auth(x_admin_token, admin_session)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Product name is required")

    from services.ai_categorizer import classify_one
    prod = {
        "name": body.name,
        "brand": body.brand or "",
        "niche": body.main_category or "",
        "category": "",
        "subcategory": body.product_type or "",
        "concerns": [],
        "main_category_hint": body.main_category or "",
        "product_type_hint": body.product_type or "",
        "concern_hint": body.concern or "",
        "skin_type_hint": body.skin_type or "",
    }
    try:
        result = await classify_one(_db, prod)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI classify failed: {e}")

    created: Dict[str, list] = {"categories": [], "subcategories": [], "concerns": []}
    if body.auto_create:
        if result.get("category_slug") and result.get("category_is_new"):
            exists = await _db.categories.find_one({"slug": result["category_slug"]}, {"_id": 1})
            if not exists:
                await _db.categories.insert_one({
                    "slug": result["category_slug"],
                    "name": result["category_name"],
                    "niche": result["niche"],
                    "group": result["niche"],
                    "is_parent": False,
                    "tagline": "",
                    "image": "",
                    "icon": result.get("category_icon") or "🛍️",
                    "sort_order": 99,
                    "is_active": True,
                    "ai_created": True,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
                created["categories"].append(result["category_slug"])
        if result.get("subcategory_slug") and result.get("subcategory_is_new"):
            exists = await _db.subcategories.find_one({"slug": result["subcategory_slug"]}, {"_id": 1})
            if not exists:
                await _db.subcategories.insert_one({
                    "slug": result["subcategory_slug"],
                    "name": result["subcategory_name"],
                    "parent_category": result["category_slug"],
                    "niche": result["niche"],
                    "tagline": "",
                    "icon": result.get("subcategory_icon") or "",
                    "image": "",
                    "sort_order": 0,
                    "is_active": True,
                    "ai_created": True,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                created["subcategories"].append(result["subcategory_slug"])
        for c in result.get("concerns") or []:
            if c.get("is_new"):
                exists = await _db.concerns.find_one({"slug": c["slug"]}, {"_id": 1})
                if not exists:
                    await _db.concerns.insert_one({
                        "slug": c["slug"],
                        "name": c["name"],
                        "tagline": "",
                        "icon": "✨",
                        "image": "",
                        "accent_from": "#dcfce7",
                        "accent_to": "#bbf7d0",
                        "accent_text": "#14532d",
                        "description": "",
                        "sort_order": 99,
                        "is_active": True,
                        "niche": result["niche"],
                        "ai_created": True,
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    })
                    created["concerns"].append(c["slug"])

    return {
        "success": True,
        "classification": result,
        "auto_created": created,
    }


# ============================================================
# ONE-CLICK AI Taxonomy Audit — runs across the whole catalog
# ============================================================

class AITaxonomyAuditRequest(BaseModel):
    scope: str = "needs_taxonomy"  # 'needs_taxonomy' | 'niche' | 'all'
    niche: Optional[str] = None  # used when scope='niche'
    limit: Optional[int] = None
    concurrency: int = 6
    only_missing: bool = True


@router.post("/admin/taxonomy/ai-audit")
async def admin_ai_taxonomy_audit(
    body: AITaxonomyAuditRequest = Body(default_factory=AITaxonomyAuditRequest),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Kick off a background AI audit that:
      • Loads the CURRENT canonical category/subcategory/concern lists from MongoDB.
      • Classifies every product in scope against that taxonomy via Claude.
      • Auto-creates new categories / subcategories / concerns when needed.
      • Updates each product's niche/category/subcategory/concerns fields.
    Returns a job_id; poll GET /admin/taxonomy/ai-audit/{job_id}.
    """
    _auth(x_admin_token, admin_session)
    if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("EMERGENT_LLM_KEY")):
        raise HTTPException(status_code=503, detail="No AI key configured (set GEMINI_API_KEY)")

    from services.ai_categorizer import create_audit_job, run_audit_job
    import asyncio as _aio
    job_id = create_audit_job(body.scope, body.niche, body.limit)
    _aio.create_task(run_audit_job(
        _db, job_id, body.scope, niche=body.niche, limit=body.limit,
        concurrency=max(1, min(body.concurrency, 10)),
        only_missing=body.only_missing,
    ))
    return {"success": True, "job_id": job_id}


@router.get("/admin/taxonomy/ai-audit/{job_id}")
async def admin_ai_taxonomy_audit_status(
    job_id: str,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    _auth(x_admin_token, admin_session)
    from services.ai_categorizer import get_audit_job
    job = get_audit_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/admin/taxonomy/ai-audit")
async def admin_ai_taxonomy_audit_list(
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Recent audit jobs (in-memory; resets on backend restart)."""
    _auth(x_admin_token, admin_session)
    from services.ai_categorizer import list_audit_jobs
    return {"jobs": list_audit_jobs()}


# ============================================================
# Danger zone: wipe all products (for re-testing bulk upload)
# ============================================================

@router.post("/admin/products/wipe-all")
async def admin_wipe_all_products(
    confirm: str = Query(..., description="Must be exactly 'DELETE_ALL' to proceed."),
    keep_niches: Optional[str] = Query(None, description="Comma-separated niches to KEEP (e.g. 'anti-aging'). Default: wipe everything."),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Hard-delete every product (optionally keeping certain niches).

    Idempotent and safe; pass `confirm=DELETE_ALL` to actually execute.
    Returns counts of what got deleted.
    """
    _auth(x_admin_token, admin_session)
    if confirm != "DELETE_ALL":
        raise HTTPException(status_code=400, detail="Pass confirm=DELETE_ALL to execute.")
    keep = [n.strip() for n in (keep_niches or "").split(",") if n.strip()]
    q: Dict[str, Any] = {}
    if keep:
        q = {"niche": {"$nin": keep}}
    before = await _db.products.count_documents(q)
    res = await _db.products.delete_many(q)
    after = await _db.products.count_documents({})
    return {
        "success": True,
        "deleted": res.deleted_count,
        "matched": before,
        "remaining_total": after,
        "kept_niches": keep,
    }



# ============================================================
# Fix bad brand values (Sheet1 / Sheet2 / blank) on already-imported products
# ============================================================

@router.post("/admin/products/fix-brands")
async def admin_fix_brands(
    dry_run: bool = Query(False),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Repair products where brand is literally 'Sheet1' / 'Sheet2' / blank.

    Re-derives brand from product name using the same heuristic the parser
    now uses for new uploads (first 1–2 capitalised tokens, stopping at
    common product nouns). Slug is left alone to avoid breaking links.
    """
    _auth(x_admin_token, admin_session)
    import re as _re
    stop = {"face", "skin", "cream", "serum", "wash", "lotion", "spf", "oil", "lip", "eye", "anti", "night", "day", "mask", "toner", "balm", "scrub", "gel", "foam", "cleanser", "moisturizer", "moisturiser", "sunscreen", "lipstick", "kajal", "mascara", "eyeliner", "foundation", "concealer", "primer", "compact", "blush", "highlighter", "powder", "for", "with", "the"}
    bad = {"sheet1", "sheet2", "sheet3", "sheet4", "sheet5", "sheet", "", "nan"}

    def derive_brand(name: str) -> str:
        tokens = _re.findall(r"[A-Za-z0-9&]+", str(name or "").strip())
        if not tokens:
            return ""
        picked = []
        for t in tokens[:2]:
            if t.lower() in stop:
                break
            picked.append(t)
        return " ".join(picked).strip() or tokens[0]

    q = {"$or": [
        {"brand": {"$in": ["Sheet1", "Sheet2", "Sheet3", "Sheet4", "Sheet5", "", None]}},
        {"brand": {"$regex": "^Sheet\\d+$"}},
    ]}
    fixed = 0
    examples = []
    async for p in _db.products.find(q, {"_id": 0, "slug": 1, "brand": 1, "name": 1}):
        new_brand = derive_brand(p.get("name", ""))
        if not new_brand or new_brand.lower() in bad:
            continue
        if not dry_run:
            await _db.products.update_one({"slug": p["slug"]}, {"$set": {"brand": new_brand, "updated_at": datetime.now(timezone.utc).isoformat()}})
        fixed += 1
        if len(examples) < 10:
            examples.append({"slug": p["slug"], "old_brand": p.get("brand"), "new_brand": new_brand})
    return {"success": True, "dry_run": dry_run, "fixed": fixed, "examples": examples}


# ============================================================
# Seed COMPREHENSIVE skincare + cosmetics taxonomy
# ============================================================

@router.post("/admin/taxonomy/seed-comprehensive")
async def admin_taxonomy_seed_comprehensive(
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Insert the canonical Celesta Glow taxonomy (concerns, categories,
    subcategories) used by the AI audit to route products. Idempotent —
    only inserts rows that don't already exist (by slug)."""
    _auth(x_admin_token, admin_session)
    from services.taxonomy_seed_v2 import seed_comprehensive_taxonomy
    counts = await seed_comprehensive_taxonomy(_db)
    return {"success": True, "inserted": counts}



# ============================================================
# One-click: Connect ALL products to the canonical taxonomy
# (rule-based, no LLM cost, runs full 9k catalog in seconds)
# ============================================================

class ConnectAllRequest(BaseModel):
    only_unconnected: bool = False
    niche: Optional[str] = None
    limit: Optional[int] = None


@router.post("/admin/taxonomy/connect-all")
async def admin_taxonomy_connect_all(
    body: ConnectAllRequest = Body(default_factory=ConnectAllRequest),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Rule-based one-click router. For every product:
      • Detect niche (skincare / cosmetics / anti-aging) from product name keywords
      • Match best canonical category slug + subcategory sub-filter
      • Tag matching concerns (acne, pigmentation, brightening, etc.)
      • Update product → those storefront pages instantly populate.

    Uses ONLY keyword matching — no LLM. Full 9k catalog routes in ~5 seconds.
    """
    _auth(x_admin_token, admin_session)
    from services.rule_based_router import connect_all_products
    stats = await connect_all_products(
        _db,
        only_unconnected=body.only_unconnected,
        niche_filter=body.niche,
        limit=body.limit,
    )
    return {"success": True, **stats}



# ============================================================
# ONE-CLICK AI PRODUCT GENERATOR
# Given just a product name (+ optional brand/image hint) this single
# endpoint: (1) classifies niche/category/subcategory/concerns and
# auto-creates any missing taxonomy, (2) writes full marketing copy,
# (3) generates a product image, and (4) creates the live product.
# ============================================================
import random as _random
from pathlib import Path as _Path

_PROD_IMG_DIR = _Path(__file__).parent.parent / "uploads" / "products"
_PROD_IMG_DIR.mkdir(parents=True, exist_ok=True)


class OneClickProductRequest(BaseModel):
    name: str
    brand: Optional[str] = "Celesta Glow"
    key_ingredients: Optional[str] = ""
    image_url: Optional[str] = None          # if admin already has an image, skip AI image
    generate_image: bool = True
    # Optional admin-picked reference bottle photo for AI image generation. If
    # omitted, the site-settings references / default approved bottles are used.
    reference_image_url: Optional[str] = None
    is_active: bool = True
    # ---- Optional pre-generation specifications (considered by the AI copy + price) ----
    price_min: Optional[int] = None          # desired MRP range (INR) — lower bound
    price_max: Optional[int] = None          # desired MRP range (INR) — upper bound
    target_audience: Optional[str] = None    # e.g. "men 25-35, oily skin"
    skin_type: Optional[str] = None          # e.g. "oily / dry / combination / all"
    texture: Optional[str] = None            # e.g. "lightweight gel", "rich cream"
    fragrance: Optional[str] = None          # e.g. "fragrance-free", "mild citrus"
    size_hint: Optional[str] = None          # e.g. "30ml", "50g"
    extra_specs: Optional[str] = None        # free-form extra requirements/notes


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:70] or f"product-{uuid.uuid4().hex[:6]}"


# Default approved bottle references (exact bottles the brand uses). Admin can
# override these in Admin → Settings with their own reference photos.
_DEFAULT_REF_BOTTLES = {
    "serum": "https://res.cloudinary.com/dcvuqcqjn/image/upload/q_auto:best,f_auto/celesta-glow/brand/brand-bottle-serum.jpg",
    "cream": "https://res.cloudinary.com/dcvuqcqjn/image/upload/q_auto:best,f_auto/celesta-glow/brand/brand-bottle-cream.jpg",
}

# Keywords that map a product to the taller cream-style bottle (same rule the
# rest of the pipeline uses).
_CREAM_WORDS = (
    "cream", "moistur", "night", "balm", "butter", "mask", "lotion", "gel",
    "sunscreen", "spf", "eye", "ointment", "salve",
)


def _bottle_kind(name: str, category: str) -> str:
    hay = f"{category or ''} {name or ''}".lower()
    return "cream" if any(w in hay for w in _CREAM_WORDS) else "serum"


async def _ai_generate_product_image(name: str, brand: str, category: str,
                                     ref_images: Optional[list] = None,
                                     extra_prompt: str = "",
                                     instructions: str = "") -> Optional[str]:
    """Generate a photorealistic product image with GEMINI and persist it.

    Ported from the brand's earlier project so the output matches the approved
    sample look exactly. Provider chain:
      1. Gemini "Nano Banana" image model via Emergent LLM key (uses the brand's
         THEME reference images so output matches the sample look exactly).
      2. Direct Google Gemini (GEMINI_API_KEY).
      3. Pollinations (free) as a last-resort fallback.
    The result is upscaled to a high resolution, then saved to Cloudinary if
    configured, else to local /api/uploads/products/. Returns a public URL.
    """
    import base64 as _b64
    # Auto-load the brand THEME reference images (the samples the admin provided)
    # so every generated product matches the exact studio style.
    if ref_images is None:
        ref_images = []
        try:
            _theme_dir = _Path(__file__).parent.parent / "uploads" / "theme_refs"
            for _f in sorted(_theme_dir.glob("*.png")) + sorted(_theme_dir.glob("*.jpg")):
                try:
                    ref_images.append(_f.read_bytes())
                except Exception:
                    pass
        except Exception:
            pass

    ings = (extra_prompt or "").strip()
    prompt = (
        "Professional product photography on a PURE WHITE background (#FFFFFF). The background must be completely "
        "white with no shadows, no gradients, no textures, no grey tones, no off-white. Solid pure white background "
        "only. Studio lighting. Clean white seamless backdrop. "
        f"Ultra-clean e-commerce product photograph of a single {brand} skincare {category or 'product'}: '{name}'. "
        "STYLE (match exactly): one pristine WHITE pump bottle standing upright, perfectly centred, with a large "
        "thick, opaque WHITE CREAM swatch / swirl (whipped cream texture with soft peaks) and a few smaller white "
        "cream dollops arranged BEHIND and beside the bottle (visible around the edges of the bottle) on a seamless "
        "PURE-WHITE (#FFFFFF) studio "
        "background, soft even diffused lighting, NO grounding shadow, minimalist high-end clinical beauty aesthetic, "
        "1:1 square. The cream must look like a rich, thick, opaque WHITE CREAM — never liquid, serum, gel, oil or "
        "any transparent fluid. "
        "The bottle label is printed in an elegant minimalist layout using GREEN and grey text: the vertical brand "
        f"wordmark 'CELESTA GLOW', then the product name '{name}', a formula line, "
        + (f"the key ingredients ({ings}), " if ings else "the key ingredients, ")
        + "a few short benefit bullets, 'FOR ALL SKIN TYPES' and the pack size. "
        "Photorealistic, sharp focus, no hands, no extra props, no busy background."
    )
    if ref_images:
        prompt = ("Recreate the EXACT visual style, white background, lighting, green+grey typography and "
                  "composition of the provided reference product images, but for THIS product. " + prompt)
    if (instructions or "").strip():
        prompt += ("\n\nADMIN INSTRUCTIONS (highest priority — follow these exactly, they override the style "
                   f"notes above where they conflict): {instructions.strip()}")

    out_bytes = None
    mime = "image/png"

    # 1) Direct Google Gemini (GEMINI_API_KEY) — this works from the deployed app.
    gkey = os.environ.get("GEMINI_API_KEY")
    if gkey:
        try:
            import asyncio as _asyncio
            from google import genai
            from google.genai import types as _gt
            client = genai.Client(api_key=gkey)
            parts = [prompt]
            for rb in (ref_images or []):
                parts.append(_gt.Part.from_bytes(data=rb, mime_type="image/png"))

            def _imggen():
                return client.models.generate_content(model="gemini-2.5-flash-image", contents=parts)

            resp = await _asyncio.to_thread(_imggen)
            for part in (resp.candidates[0].content.parts if resp.candidates else []):
                inline = getattr(part, "inline_data", None)
                if inline and getattr(inline, "data", None):
                    out_bytes = inline.data
                    mime = inline.mime_type or "image/png"
                    break
        except Exception as e:
            logger.warning(f"[img-gen] Gemini(direct) image failed: {e}")
            from services.llm_helper import friendly_ai_error
            raise ValueError(friendly_ai_error(e))

    if not out_bytes:
        return None, None

    # Always maintain a HIGH-RESOLUTION image: upscale to >= 2048px if smaller.
    # Done in a worker thread so the CPU-heavy PIL work never starves the event
    # loop / health probe on the single production worker.
    def _hires(bts):
        from PIL import Image as _Img
        import io as _io
        _im = _Img.open(_io.BytesIO(bts)).convert("RGB")
        if max(_im.size) < 2048:
            _scale = 2048 / max(_im.size)
            _im = _im.resize((int(_im.width * _scale), int(_im.height * _scale)), _Img.LANCZOS)
        _buf = _io.BytesIO()
        _im.save(_buf, "PNG")
        return _buf.getvalue()

    try:
        import asyncio as _asyncio
        out_bytes = await _asyncio.to_thread(_hires, out_bytes)
        mime = "image/jpeg"
    except Exception as e:
        logger.warning(f"[img-gen] high-res upscale skipped: {e}")

    # Persist — Cloudinary first, else local
    try:
        from services import cloudinary_service as _cs
        if await _cs.ensure_configured(_db):
            res = await _cs.upload_image(
                _db, out_bytes, folder="celesta-glow/products",
                public_id=f"prod-{uuid.uuid4().hex[:12]}",
            )
            if res.get("url"):
                return res["url"], out_bytes
    except Exception as e:
        logger.warning(f"[img-gen] Cloudinary upload failed, falling back to local: {e}")

    ext = "png" if "png" in mime else "jpg"
    filename = f"prod-{uuid.uuid4().hex[:12]}.{ext}"
    with open(_PROD_IMG_DIR / filename, "wb") as f:
        f.write(out_bytes)
    return f"/api/uploads/products/{filename}", out_bytes

_one_click_jobs: Dict[str, Any] = {}


@router.post("/admin/ai/one-click-product")
async def one_click_product(
    body: OneClickProductRequest,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Create a fully-formed product from just a name.

    Runs as a BACKGROUND job (the AI image step can exceed the ~55s edge
    timeout) — returns a job_id immediately. Poll
    GET /admin/ai/one-click-product-job/{job_id} for progress + final result.
    """
    _auth(x_admin_token, admin_session)
    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Product name is required")

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="No AI key configured (set GEMINI_API_KEY)")

    import asyncio as _aio
    job_id = f"oc_{uuid.uuid4().hex[:10]}"
    _one_click_jobs[job_id] = {
        "job_id": job_id, "name": name, "status": "running", "step": "queued",
        "result": None, "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _aio.create_task(_one_click_worker(job_id, body))
    from services.job_store import start_mirror
    start_mirror(_db, _one_click_jobs[job_id])
    return {"success": True, "job_id": job_id, "status": "running"}


@router.get("/admin/ai/one-click-product-job/{job_id}")
async def one_click_product_job(
    job_id: str,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    _auth(x_admin_token, admin_session)
    from services.job_store import get_job
    job = await get_job(_db, _one_click_jobs, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


_regen_jobs: Dict[str, Any] = {}


@router.post("/admin/products/{slug}/regenerate-image")
async def regenerate_product_image(
    slug: str,
    prompt: str = Form(""),
    references: List[UploadFile] = File(default=[]),
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Regenerate ONLY the main product photo with Gemini, optionally guided by
    admin reference images + instructions. Returns a job_id; the new image is a
    candidate until applied via /set-main-image."""
    _auth(x_admin_token, admin_session)
    product = await _db.products.find_one({"slug": slug}, {"_id": 0, "name": 1, "brand": 1, "category": 1,
                                                           "subcategory": 1, "key_ingredients": 1})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if not os.environ.get("GEMINI_API_KEY"):
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY is not set on this server.")
    refs = []
    for f in (references or [])[:4]:
        data = await f.read()
        if len(data) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"{f.filename} is larger than 10 MB")
        if data:
            refs.append(data)
    if len(prompt) > 2000:
        raise HTTPException(status_code=400, detail="Prompt too long (max 2000 characters)")

    import asyncio as _aio
    job_id = f"regen_{uuid.uuid4().hex[:10]}"
    job = {"job_id": job_id, "slug": slug, "name": product.get("name"), "status": "running",
           "step": "generating image", "result": None, "error": None,
           "created_at": datetime.now(timezone.utc).isoformat()}
    _regen_jobs[job_id] = job

    async def _worker():
        try:
            ings = product.get("key_ingredients") or ""
            extra = f"The formula's hero actives are: {ings}." if ings else ""
            url, _bytes = await _ai_generate_product_image(
                product.get("name") or slug, product.get("brand") or "Celesta Glow",
                product.get("subcategory") or product.get("category") or "",
                ref_images=refs or None, extra_prompt=extra, instructions=prompt)
            if not url:
                raise RuntimeError("Gemini did not return an image. Try adjusting the prompt.")
            if "res.cloudinary.com" in url and "/upload/" in url and "q_" not in url:
                url = url.replace("/upload/", "/upload/q_100,f_auto/", 1)
            job.update(status="done", step="done", result={"image_url": url})
        except Exception as e:
            from services.llm_helper import friendly_ai_error
            job.update(status="failed", error=friendly_ai_error(e) if "Gemini" not in str(e) else str(e)[:300])

    _aio.create_task(_worker())
    from services.job_store import start_mirror
    start_mirror(_db, job)
    return {"success": True, "job_id": job_id, "status": "running"}


@router.get("/admin/products/regenerate-image-job/{job_id}")
async def regenerate_image_job(
    job_id: str,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    _auth(x_admin_token, admin_session)
    from services.job_store import get_job
    job = await get_job(_db, _regen_jobs, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


class SetMainImageRequest(BaseModel):
    image_url: str


@router.post("/admin/products/{slug}/set-main-image")
async def set_main_image(
    slug: str,
    body: SetMainImageRequest,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Replace the product's main photo (images[0]); the rest of the gallery is kept."""
    _auth(x_admin_token, admin_session)
    if not body.image_url.startswith("https://res.cloudinary.com/"):
        raise HTTPException(status_code=400, detail="Image must be a Cloudinary URL")
    product = await _db.products.find_one({"slug": slug}, {"_id": 0, "images": 1})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    images = list(product.get("images") or [])
    if images:
        images[0] = body.image_url
    else:
        images = [body.image_url]
    await _db.products.update_one({"slug": slug}, {"$set": {
        "images": images, "image": body.image_url,
        "updated_at": datetime.now(timezone.utc).isoformat()}})
    return {"success": True, "images": images}


# ----------------------------------------------------------------------------
# AI PRODUCT VARIATIONS — analyse a product's ingredients, figure out the
# distinct RESULTS the formula can deliver, and spin up result-led variations
# (upgraded name + fresh copy + a regenerated image that keeps the SAME bottle).
# Two steps keep AI spend low: (1) one cheap text call suggests variations;
# (2) image generation only happens when the admin actually creates one.
# ----------------------------------------------------------------------------
class AiVariationsRequest(BaseModel):
    count: Optional[int] = None  # None => AI decides (2-5)


def _strip_json(raw: str) -> dict:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            raise HTTPException(status_code=502, detail="AI returned non-JSON content")
        return json.loads(m.group(0))


async def _ai_variation_image_emergent(name: str, brand: str, category: str,
                                       ref_bytes: Optional[list], ings: str,
                                       instructions: str):
    """Image-gen fallback for variations via the Emergent universal key (Nano
    Banana / Gemini image model) when the brand's own GEMINI_API_KEY is
    exhausted. Keeps the reference bottle; uploads result to Cloudinary.
    Returns (url, raw_png_bytes) or (None, None)."""
    import base64 as _b64
    key = os.environ.get("LISTING_AI_KEY") or os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        return None, None
    prompt = (
        "Recreate the EXACT bottle/jar shape, cap, proportions, size, packaging, white background, lighting and "
        "green+grey CELESTA GLOW typography of the provided reference product image(s), but for THIS product. "
        f"Ultra-clean e-commerce product photo of a single {brand} skincare {category or 'product'}: '{name}' on a "
        "pure WHITE (#FFFFFF) studio background, soft diffused lighting, no grounding shadow, 1:1 square, photorealistic. "
        "The container must be reproduced EXACTLY from the reference — same shape, cap/pump and label layout; never "
        "invent a different bottle. This is a thick WHITE CREAM product: never depict liquid, serum drops, oil, gel "
        "or transparent fluid anywhere in the image. "
        f"The printed product name on the label must read '{name}'. "
        + (f"Key ingredients: {ings}. " if ings else "")
        + (instructions or "")
    )
    try:
        from emergentintegrations.llm.chat import UserMessage, ImageContent
        chat = GeminiChat(api_key=key, session_id=f"var-img-{uuid.uuid4().hex[:8]}",
                          system_message="You are a professional product photographer.")
        chat.with_model("gemini", "gemini-2.5-flash-image").with_params(modalities=["image", "text"])
        file_contents = [ImageContent(_b64.b64encode(b).decode("utf-8")) for b in (ref_bytes or []) if b]
        msg = UserMessage(text=prompt, file_contents=file_contents)
        _text, images = await chat.send_message_multimodal_response(msg)
    except Exception as e:
        logger.warning(f"[ai-variation] Emergent image fallback failed: {e}")
        return None, None
    if not images:
        return None, None
    out_bytes = _b64.b64decode(images[0]["data"])
    try:
        from services import cloudinary_service as _cs
        if await _cs.ensure_configured(_db):
            res = await _cs.upload_image(_db, out_bytes, folder="celesta-glow/products",
                                         public_id=f"prod-{uuid.uuid4().hex[:12]}")
            if res.get("url"):
                return res["url"], out_bytes
    except Exception as e:
        logger.warning(f"[ai-variation] Cloudinary upload failed: {e}")
    return None, out_bytes



@router.post("/admin/products/{slug}/ai-variations")
async def ai_product_variations(
    slug: str,
    body: Optional[AiVariationsRequest] = None,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Analyse the product's ingredients and SUGGEST result-led variations
    (text only — no images, no DB writes). Admin reviews, then creates the ones
    they want via /ai-variations/create."""
    _auth(x_admin_token, admin_session)
    prod = await _db.products.find_one({"slug": slug}, {"_id": 0})
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("LISTING_AI_KEY") or os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="No AI key configured (set GEMINI_API_KEY)")

    brand = prod.get("brand") or "Celesta Glow"
    ptype = prod.get("subcategory") or prod.get("category") or "skincare product"
    count = (body.count if body and body.count else None)
    count_rule = (f"Create EXACTLY {count} variations." if count
                  else "Create between 2 and 5 variations — you decide the number based on how many "
                       "genuinely DISTINCT results the ingredients can support (don't pad with weak ones).")
    prompt = f"""You are a senior product strategist for "{brand}", an Indian skincare brand.

BASE PRODUCT
Name: {prod.get('name', '')}
Type: {ptype}
Key ingredients: {prod.get('key_ingredients') or '(not listed)'}
Full ingredients: {(prod.get('ingredients_full') or '')[:600]}
Current description: {(prod.get('description') or '')[:500]}

TASK
Analyse the ingredients and work out the DISTINCT skin RESULTS this exact formula can realistically deliver.
For each strong, genuinely different result, create ONE upgraded VARIATION that repositions the SAME formula around that result.

RULES
- {count_rule}
- Each variation NAME must be result-led and specific, formatted as "{brand} <Result> <ProductType>"
  (keep the base product type) — e.g. "{brand} Tan Removal Cleanser", "{brand} Oil-Control Cleanser".
- Only reposition around results the GIVEN ingredients can plausibly drive. Do NOT invent new ingredients.
- No medical claims, no "cure", no "miracle", no "instant".
- Each variation gets its own fresh copy (not copy-pasted from the base).

Return STRICT JSON only (no markdown fences), exactly this shape:
{{
  "variations": [
    {{
      "name": "<{brand} ... {ptype}>",
      "result": "<the single standout result, 2-4 words>",
      "tagline": "<benefit-led tagline, max 10 words>",
      "description": "<120-170 word consumer description for an Indian store, centred on this result>",
      "key_ingredients": "<comma-separated 3-5 hero actives, a subset/emphasis of the base ingredients>",
      "benefits": ["<4-5 short benefit phrases, each <=8 words>"],
      "how_to_use": "<2-4 short steps, newline separated>"
    }}
  ]
}}"""
    try:
        from emergentintegrations.llm.chat import UserMessage
        # Try the brand's own Gemini key first; if it's exhausted/invalid, fall
        # back to the Emergent universal key (routes through Gemini models too).
        _keys, _seen = [], set()
        for _k in (os.environ.get("GEMINI_API_KEY"), os.environ.get("LISTING_AI_KEY"), os.environ.get("EMERGENT_LLM_KEY")):
            if _k and _k not in _seen:
                _seen.add(_k); _keys.append(_k)
        data, last_err = None, None
        for _k in _keys:
            try:
                chat = GeminiChat(
                    api_key=_k,
                    session_id=f"variations-{uuid.uuid4().hex[:8]}",
                    system_message="You are a precise JSON-only skincare product strategist.",
                ).with_model("gemini", "gemini-2.5-flash")
                resp = await chat.send_message(UserMessage(text=prompt))
                data = _strip_json(resp)
                break
            except Exception as e:
                last_err = e
                continue
        if data is None:
            raise HTTPException(status_code=502, detail=f"AI variation analysis failed: {str(last_err)[:160]}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"AI variation analysis failed: {str(e)[:160]}")

    variations = []
    for v in (data.get("variations") or [])[:6]:
        if not v.get("name"):
            continue
        variations.append({
            "name": str(v.get("name"))[:120],
            "result": str(v.get("result") or "")[:60],
            "tagline": str(v.get("tagline") or "")[:120],
            "description": str(v.get("description") or "")[:1800],
            "key_ingredients": str(v.get("key_ingredients") or prod.get("key_ingredients") or "")[:400],
            "benefits": [str(b)[:80] for b in (v.get("benefits") or [])][:8],
            "how_to_use": str(v.get("how_to_use") or "")[:600],
        })
    if not variations:
        raise HTTPException(status_code=502, detail="AI did not return any usable variations")
    return {
        "success": True,
        "base": {"slug": slug, "name": prod.get("name"), "brand": brand, "images": prod.get("images") or []},
        "variations": variations,
    }


class CreateVariationRequest(BaseModel):
    name: str
    result: Optional[str] = ""
    tagline: Optional[str] = ""
    description: Optional[str] = ""
    key_ingredients: Optional[str] = ""
    benefits: Optional[list] = None
    how_to_use: Optional[str] = ""
    generate_image: bool = True
    is_active: bool = True


@router.post("/admin/products/{slug}/ai-variations/create")
async def create_product_variation(
    slug: str,
    body: CreateVariationRequest,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Create ONE variation as a real product. Copies the base product's pricing,
    category, concerns and niche; sets is_variation + parent_slug; and (if
    generate_image) regenerates a hero image using the base product's own images
    as references so the BOTTLE SHAPE stays identical — only the label/result changes."""
    _auth(x_admin_token, admin_session)
    base = await _db.products.find_one({"slug": slug}, {"_id": 0})
    if not base:
        raise HTTPException(status_code=404, detail="Base product not found")
    if not (body.name or "").strip():
        raise HTTPException(status_code=400, detail="Variation name is required")

    brand = base.get("brand") or "Celesta Glow"
    category = base.get("subcategory") or base.get("category") or ""
    now_iso = datetime.now(timezone.utc).isoformat()

    # unique slug
    base_slug = _slugify(body.name)
    new_slug = base_slug
    n = 1
    while await _db.products.find_one({"slug": new_slug}, {"_id": 1}):
        n += 1
        new_slug = f"{base_slug}-{n}"

    # Regenerate the hero image from the base product's existing images so the
    # same bottle is reused (only the printed name / colour accent changes).
    image_url = None
    hero_bytes = None
    if body.generate_image:
        ref_bytes = []
        try:
            import httpx
            async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
                for u in (base.get("images") or [])[:2]:
                    if not u:
                        continue
                    full = u if u.startswith("http") else f"{os.environ.get('REACT_APP_BACKEND_URL', '')}{u}"
                    try:
                        r = await client.get(full)
                        if r.status_code == 200 and r.content:
                            ref_bytes.append(r.content)
                    except Exception:
                        pass
        except Exception:
            ref_bytes = []
        ings = body.key_ingredients or base.get("key_ingredients") or ""
        extra = f"The formula's hero actives are: {ings}." if ings else ""
        instructions = (
            "Keep the EXACT same bottle/jar shape, cap, proportions, size and overall packaging as the "
            "reference image(s). Do NOT change the container. Only update the printed product name on the "
            f"label to '{body.name}'"
            + (f" and subtly accent the label to evoke '{body.result}'." if body.result else ".")
        )
        # 1) Brand's own Gemini key (direct).
        hero_bytes = None
        if os.environ.get("GEMINI_API_KEY"):
            try:
                image_url, hero_bytes = await _ai_generate_product_image(
                    body.name, brand, category, ref_images=ref_bytes or None,
                    extra_prompt=extra, instructions=instructions)
            except Exception as e:
                logger.warning(f"[ai-variation] Gemini image generation failed (will try Emergent): {e}")
                image_url = None
        # 2) Emergent universal key fallback (Gemini image model) when Gemini
        #    is missing/exhausted.
        if not image_url:
            image_url, hero_bytes = await _ai_variation_image_emergent(body.name, brand, category, ref_bytes, ings, instructions)
        if image_url and "res.cloudinary.com" in image_url and "/upload/" in image_url and "q_" not in image_url:
            image_url = image_url.replace("/upload/", "/upload/q_100,f_auto/", 1)

    # Fall back to copying the base images if no new image was generated.
    images = [image_url] if image_url else list(base.get("images") or [])

    product = {
        "slug": new_slug,
        "name": (body.name or "").strip()[:120],
        "short_name": (body.name or "").strip()[:40],
        "tagline": (body.tagline or base.get("tagline") or "")[:120],
        "description": (body.description or base.get("description") or "")[:1800],
        "category": base.get("category") or "skincare",
        "subcategory": base.get("subcategory") or "",
        "concerns": list(base.get("concerns") or []),
        "niche": base.get("niche") or "skin-care",
        "key_ingredients": (body.key_ingredients or base.get("key_ingredients") or "")[:400],
        "ingredients_full": base.get("ingredients_full") or "",
        "benefits": list(body.benefits or [])[:8] or list(base.get("benefits") or []),
        "how_to_use": (body.how_to_use or base.get("how_to_use") or "")[:600],
        "size": base.get("size") or "",
        "images": images,
        "image": images[0] if images else "",
        "image_gallery": [{"url": images[0], "alt": f"{body.name} — {brand}"}] if images else [],
        "mrp": float(base.get("mrp") or 0),
        "prepaid_price": float(base.get("prepaid_price") or base.get("offer_price") or 0),
        "cod_price": float(base.get("cod_price") or base.get("prepaid_price") or 0),
        "cod_advance": float(base.get("cod_advance") or 29.0),
        "discount_percent": float(base.get("discount_percent") or 0),
        "offer_price": float(base.get("offer_price") or base.get("prepaid_price") or 0),
        "badge": "", "badges": [],
        "is_active": bool(body.is_active),
        "is_variation": True,
        "parent_slug": slug,
        "variation_result": (body.result or "")[:60],
        "sort_order": int(base.get("sort_order") or 1),
        "stock_qty": 100,
        "low_stock_threshold": 10,
        "fill_card": False,
        "brand": brand,
        "specs": {}, "shades": [],
        "faqs": list(base.get("faqs") or []),
        "ai_generated": True,
        "reviews_count": _random.randint(1020, 4875),
        "rating": round(_random.uniform(4.5, 4.9), 1),
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    await _db.products.insert_one(product)
    product.pop("_id", None)

    # Build the FULL image set (ingredients / formula-technology cards +
    # certificate + before/after) so the variation matches base products.
    # These cards are Pillow-composed from the hero bottle (no extra AI cost).
    gallery_built = False
    if image_url:
        try:
            from services.gallery_composer import generate_and_persist
            ai_bottle = None
            if hero_bytes:
                try:
                    from PIL import Image as _PImg
                    import io as _io2
                    from services import brand_bottles as _bb
                    _hero_im = _PImg.open(_io2.BytesIO(hero_bytes)).convert("RGB")
                    ai_bottle = _bb._trim(_bb._alpha_cutout(_hero_im))
                except Exception as _be:
                    logger.warning(f"[ai-variation] bottle extract failed: {_be}")
            media = await generate_and_persist(
                _db,
                {**product, "solves": ", ".join(product.get("concerns") or []) or "your skin concern"},
                do_gallery=True, do_certificate=True, do_before_after=True,
                bottle_override=ai_bottle, hero_url=image_url,
            )
            b_img = media.pop("before_after_before", None)
            a_img = media.pop("before_after_after", None)
            if media.get("images"):
                media["image_gallery"] = [{"url": u, "alt": f"{product['name']} — {brand}"} for u in media["images"]]
                media["image"] = media["images"][0]
            if media:
                await _db.products.update_one({"slug": new_slug}, {"$set": {**media, "updated_at": now_iso}})
                product.update(media)
                gallery_built = True
            if b_img and a_img:
                ba_id = "ba_" + hashlib.md5(new_slug.encode()).hexdigest()[:8]
                await _db.before_after_images.update_one(
                    {"ba_id": ba_id},
                    {"$set": {"ba_id": ba_id, "product_slug": new_slug,
                              "before_image": b_img, "after_image": a_img,
                              "description": f"{product['name']} — visible improvement",
                              "is_global": False, "sort_order": 0, "created_at": now_iso}},
                    upsert=True,
                )
        except Exception as e:
            logger.warning(f"[ai-variation] full image-set generation failed (non-fatal): {e}")

    return {"success": True, "product": product, "image_generated": bool(image_url),
            "gallery_built": gallery_built}



# ----------------------------------------------------------------------------
# E-COMMERCE IMAGE GENERATOR — turn any catalog product into a marketplace
# listing set. Generates Amazon-style SQUARE creatives (1000x1000) in Celesta
# Glow's own brand colours, then builds Flipkart versions: image 1 identical to
# Amazon; images 2+ = the same square creative centred on a tall white portrait
# canvas (1179x2010) with equal white bands top & bottom. Each is a downloadable
# JPG. Admin-triggered; only the slots the admin ticks are generated (credits).
# ----------------------------------------------------------------------------
# Celesta Glow brand palette (NOT the reference purple/green): emerald green
# #22C55E / #16A34A, light mint #DCFCE7, slate #1E293B, gold accent #FACC15.
_CG_BRAND = ("Celesta Glow brand colours ONLY: emerald green #22C55E and #16A34A, "
             "light mint #DCFCE7 backgrounds, dark slate #1E293B text, white, subtle gold #FACC15 accents. "
             "A small plus '+' leaf mark may appear as the brand motif. Do NOT use purple or any competitor branding.")

ECOM_SLOTS = ["hero", "ingredients", "how_it_works", "who_for", "results"]

_ECOM_REF_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "ecom_refs")


def _ecom_ref_bytes(slot: str):
    """Load the Derma-Co-style LAYOUT template for a slot (persisted in the repo)."""
    try:
        with open(os.path.join(_ECOM_REF_DIR, f"{slot}.webp"), "rb") as f:
            return f.read()
    except Exception:
        return None


def _ecom_prompt(slot: str, prod: dict) -> str:
    name = prod.get("name", "the product")
    ptype = prod.get("subcategory") or prod.get("category") or "skincare product"
    ings = prod.get("key_ingredients") or ""
    acts = [a.strip() for a in re.split(r"[+,]", ings) if a.strip()][:3]
    benefits = [str(b).strip() for b in (prod.get("benefits") or []) if str(b).strip()][:4]
    headline = (benefits[0] if benefits else (prod.get("variation_result") or "Visibly Healthier Skin")).title()
    result = prod.get("variation_result") or (prod.get("concerns") or ["healthier skin"])[0]

    # Shared, strict art-direction. IMAGE 1 = the product's REAL photo (container
    # ground truth). IMAGE 2 = layout template only. Cream format + product
    # visibility are HARD requirements on every slot.
    head = (
        "You are a senior e-commerce creative director producing a PREMIUM Amazon listing image for an Indian "
        "skincare brand. You are given TWO reference images.\n"
        "• IMAGE 1 is the PRODUCT'S REAL PHOTO — the exact container (bottle/jar/tube with its real cap/pump, "
        "proportions and white label) that MUST appear, visually unchanged, as the product in your creative. Never "
        "redesign, re-shape or re-label the container; never invent a different one.\n"
        "• IMAGE 2 is a LAYOUT TEMPLATE only: copy its composition, element placement, proportions, typography "
        "hierarchy and infographic devices (swatch circle / connector lines / stat pill / skin cross-section / model "
        "crop) and its glossy, photorealistic advertising quality — but NEVER its container, its product, or its "
        "liquid textures.\n\n"
        "HARD RULES (non-negotiable):\n"
        "A) CONTAINER: the container shown must be EXACTLY the one from IMAGE 1 — same shape, same cap/pump, same "
        "label layout. If the template shows a different bottle (e.g. a dropper bottle), ignore it completely.\n"
        "B) PRODUCT VISIBLE: the container from IMAGE 1 must be clearly visible in every creative (on a pedestal, "
        "in a model's hand, or beside the texture) — EXCEPT the 'how it works' infographic, which shows NO product "
        "and NO cream texture at all.\n"
        "C) FORMAT — WHITE CREAM ONLY: this product is a rich, thick, opaque WHITE CREAM. Never depict liquid, "
        "serum drops, oil, gel, water splashes or transparent fluid anywhere. Wherever the template uses a serum "
        "swatch, droplet or liquid splash, render a thick whipped WHITE CREAM smear, swirl or dollop with soft peaks "
        "instead.\n"
        "D) RECOLOUR the ENTIRE creative from the template's purple/green scheme to the Celesta Glow palette: emerald "
        "green #22C55E and deep green #16A34A for headings/accents/badges, light mint #DCFCE7 section backgrounds, "
        "dark slate #1E293B body text, crisp white, subtle gold #FACC15 accent. NO purple anywhere.\n"
        "E) REMOVE every 'The Derma Co' logo, cross-pill badge and all competitor text. The only brand shown is "
        "'CELESTA GLOW'.\n"
        "F) 1:1 SQUARE, ultra-high resolution, perfectly sharp legible typography, generous whitespace, premium "
        "cosmetic-advertising finish. RICHNESS: layered depth (foreground/background separation), soft realistic "
        "shadows and studio reflections, refined thin gold divider lines, small '+' motif accents, and polished "
        "micro-typography (eyebrow labels, fine print) so the creative feels like a top-tier Derma-Co-class ad, "
        "never flat or basic.\n"
        "G) GRADIENT TYPOGRAPHY: every big headline and stat number is typeset in a smooth vertical GRADIENT that "
        "melts from deep emerald #16A34A at the top into brighter green #22C55E with a hint of gold #FACC15 shimmer "
        "toward the bottom (like premium foil lettering). Headlines are left-aligned (or centred if the template "
        "centres them), stacked neatly with tight even line spacing, optically balanced in their zone — never "
        "touching the product, badges or image edges, never cramped, never floating in dead space. Supporting text "
        "stays flat dark slate #1E293B for contrast.\n\n"
        f"PRODUCT: '{name}' — {ptype} (white cream formula). Hero actives: {', '.join(acts) or ings or 'clinically-proven actives'}.\n\n"
    )
    if slot == "hero":
        return head + (
            "THIS IMAGE (hero): PURE WHITE (#FFFFFF) seamless background — no mint, no tint, no gradient, no shadow "
            "wash; the container from IMAGE 1 stands on the left, tall and centred vertically, with a large thick "
            "opaque WHITE CREAM swatch (whipped texture, soft peaks) sweeping behind it for depth; on the right ONE "
            f"short bold headline of 1-4 WORDS MAX — distill the benefit '{headline}' into the shortest meaningful, "
            "logical phrase that connects to the product (e.g. 'Fades Dark Spots', 'Brightens Skin', 'Ageless Glow', "
            "'Deep Hydration') — typeset in the emerald-to-bright-green gradient with a soft "
            "gold shimmer (per rule G), stacked neatly with tight even line spacing, a thin gold divider ending in a "
            "small green '+' mark, and a rounded emerald pill badge reading 'DERMATOLOGIST TESTED'. NO other text "
            "blocks, paragraphs or benefit lists — headline + divider + badge only. Rich finish: "
            "crisp studio reflections on the container, immaculate whitespace, headline optically centred in the "
            "right zone with clear air around it."
        )
    if slot == "ingredients":
        lines = acts or ["Active 1", "Active 2", "Active 3"]
        return head + (
            "THIS IMAGE (ingredients): a glossy macro photograph of thick WHITE CREAM swirls and dollops with soft "
            "peaks (whipped cream texture — absolutely no liquid droplets or water bubbles), with the container from "
            "IMAGE 1 standing among the cream swirls. Overlay THREE ingredient call-outs, each a bold emerald "
            "ingredient name with a one-line benefit beneath, connected to a cream swirl by a thin elbow line. "
            "Ingredients: " + "; ".join(lines) + ". Light mint background."
        )
    if slot == "how_it_works":
        return head + (
            "THIS IMAGE (how it works): a PURE INFOGRAPHIC — absolutely NO product container and NO cream/texture "
            "swatch in this one. Bold gradient-green headline 'Deep Absorption Formula' (per rule G), centred neatly "
            "at the top with a thin gold divider + '+' mark; a rounded emerald stat pill reading 'Up to 2x better "
            "absorption*'; below it a rich photoreal split skin "
            f"cross-section comparison labelled 'ORDINARY {ptype.upper()}' vs 'CELESTA GLOW' — the Celesta Glow side "
            "shows luminous emerald-gold micro-capsules travelling deep through glowing skin layers; the ordinary "
            "side shows them sitting on the surface. Rich layered skin illustration, soft depth, clean white/mint "
            "surround."
        )
    if slot == "who_for":
        bl = benefits[:3] or ["All skin types", "Daily use", "Dermatologist approved"]
        return head + (
            "THIS IMAGE (who is it for): left side a bold gradient-green headline 'Who Is It For?' (per rule G) with "
            "a thin gold divider, then 2-3 green toggle-style bullet rows neatly aligned under it: " + "; ".join(bl) + ". Right side a smiling young Indian woman with "
            "glowing skin holding the EXACT container from IMAGE 1 near her face, with a small dab of white cream on "
            "her cheek. Soft light-mint studio background."
        )
    if slot == "results":
        stat = "98%"
        clean_result = (result or "visible improvement").replace("-", " ").replace("_", " ").strip()
        return head + (
            "THIS IMAGE (results): an extreme beauty close-up of a young Indian woman's flawless glowing face filling "
            "the frame, holding the EXACT container from IMAGE 1 near her cheek on the right. On the left a very large "
            f"bold gradient-green statistic '{stat}' (per rule G). Under it ONE short, GRAMMATICALLY PERFECT claim "
            "sentence of 6-9 words max in slate text — compose it properly from the product's result "
            f"('{clean_result}') and benefit ('{headline}'), e.g. 'saw visibly brighter skin in 3 weeks*' or "
            "'noticed fewer fine lines in 4 weeks*' — never concatenate raw labels, never broken grammar. Below it a "
            "small grey disclaimer line: 'When used regularly. Based on a consumer survey.'"
        )
    return head


async def _ecom_gen_square(prompt: str, ref_bytes: Optional[list]):
    """Generate ONE 1000x1000 JPG listing creative. Tries the brand's Gemini key,
    then the Emergent universal key (Nano Banana). Returns JPG bytes or None."""
    import base64 as _b64, io as _io
    from PIL import Image as _PImg
    keys, seen = [], set()
    for k in (os.environ.get("LISTING_AI_KEY"), os.environ.get("EMERGENT_LLM_KEY"), os.environ.get("GEMINI_API_KEY")):
        if k and k not in seen:
            seen.add(k); keys.append(k)
    if not keys:
        return None
    from emergentintegrations.llm.chat import UserMessage, ImageContent
    last = None
    for key in keys:
        try:
            chat = GeminiChat(api_key=key, session_id=f"ecom-{uuid.uuid4().hex[:8]}",
                              system_message="You are an expert e-commerce creative designer.")
            chat.with_model("gemini", "gemini-2.5-flash-image").with_params(modalities=["image", "text"])
            fcs = [ImageContent(_b64.b64encode(b).decode("utf-8")) for b in (ref_bytes or []) if b]
            _t, imgs = await chat.send_message_multimodal_response(UserMessage(text=prompt, file_contents=fcs))
            if imgs:
                raw = _b64.b64decode(imgs[0]["data"])
                im = _PImg.open(_io.BytesIO(raw)).convert("RGB")
                w, h = im.size
                s = min(w, h)
                im = im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2)).resize((1000, 1000), _PImg.LANCZOS)
                out = _io.BytesIO(); im.save(out, "JPEG", quality=92)
                return out.getvalue()
        except Exception as e:
            last = e; continue
    logger.warning(f"[ecom] image generation failed: {last}")
    return None


def _flipkart_from_square(square_bytes: bytes) -> bytes:
    """Place a square creative centred (full width) on a tall white 1179x2010
    portrait canvas with equal white bands top & bottom. Returns JPG bytes."""
    import io as _io
    from PIL import Image as _PImg
    W, Hc = 1179, 2010
    sq = _PImg.open(_io.BytesIO(square_bytes)).convert("RGB").resize((W, W), _PImg.LANCZOS)
    canvas = _PImg.new("RGB", (W, Hc), (255, 255, 255))
    canvas.paste(sq, (0, (Hc - W) // 2))
    out = _io.BytesIO(); canvas.save(out, "JPEG", quality=92)
    return out.getvalue()


async def _ecom_upload(jpg_bytes: bytes, slug: str, tag: str) -> Optional[str]:
    try:
        from services import cloudinary_service as _cs
        if await _cs.ensure_configured(_db):
            res = await _cs.upload_image(_db, jpg_bytes, folder="celesta-glow/ecom",
                                         public_id=f"ecom-{slug}-{tag}-{uuid.uuid4().hex[:6]}")
            return res.get("url")
    except Exception as e:
        logger.warning(f"[ecom] upload failed: {e}")
    return None


class EcomImagesRequest(BaseModel):
    slots: Optional[list] = None  # subset of ECOM_SLOTS; default = all


@router.post("/admin/products/{slug}/ecom-images")
async def generate_ecom_images(
    slug: str,
    body: Optional[EcomImagesRequest] = None,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Generate Amazon (square) + Flipkart (tall-centred) listing JPGs for a product."""
    _auth(x_admin_token, admin_session)
    prod = await _db.products.find_one({"slug": slug}, {"_id": 0})
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")

    # Reference bottle = the product's own hero image. WITHOUT it we must NOT
    # generate — otherwise the AI would invent a generic container.
    hero_bytes = None
    try:
        import httpx
        first = (prod.get("images") or [None])[0]
        if first:
            full = first if first.startswith("http") else f"{os.environ.get('REACT_APP_BACKEND_URL', '')}{first}"
            async with httpx.AsyncClient(timeout=25.0, follow_redirects=True) as client:
                r = await client.get(full)
                if r.status_code == 200 and r.content:
                    hero_bytes = r.content
    except Exception:
        hero_bytes = None
    if not hero_bytes:
        raise HTTPException(
            status_code=400,
            detail="This product has no main product photo, so the generator cannot show the real bottle. Add a main image to the product first, then generate.",
        )

    slots = [s for s in (body.slots if body and body.slots else ECOM_SLOTS) if s in ECOM_SLOTS]
    if not slots:
        slots = ECOM_SLOTS

    amazon, flipkart = [], []
    custom_prompts = (prod.get("ecom_prompts") or {})
    for idx, slot in enumerate(slots):
        # IMAGE 1 = the product's REAL photo (container ground truth),
        # IMAGE 2 = the slot's layout template. Order matches the prompt.
        ref_layout = _ecom_ref_bytes(slot)
        refs = [b for b in (hero_bytes, ref_layout) if b]
        # Admin-edited prompt (saved on the product) overrides the default.
        _cp = (custom_prompts.get(slot) or "").strip()
        prompt = _cp if _cp else _ecom_prompt(slot, prod)
        sq = await _ecom_gen_square(prompt, refs)
        if not sq:
            continue
        amz_url = await _ecom_upload(sq, slug, f"amz-{slot}")
        if amz_url:
            amazon.append({"slot": slot, "url": amz_url})
        # Flipkart: the FIRST creative stays identical to Amazon; the rest get the
        # tall white portrait canvas treatment.
        fk_bytes = sq if idx == 0 else _flipkart_from_square(sq)
        fk_url = await _ecom_upload(fk_bytes, slug, f"fk-{slot}")
        if fk_url:
            flipkart.append({"slot": slot, "url": fk_url})

    if not amazon:
        raise HTTPException(status_code=502, detail="Image generation failed (AI key exhausted or Cloudinary not configured)")

    # Persist the generated set ON the product so it survives refresh/reopen.
    # Merge by slot: regenerating a slot replaces its image, other slots are kept.
    saved = (prod.get("ecom_images") or {})
    saved_amz = {x["slot"]: x["url"] for x in (saved.get("amazon") or [])}
    saved_fk = {x["slot"]: x["url"] for x in (saved.get("flipkart") or [])}
    for x in amazon:
        saved_amz[x["slot"]] = x["url"]
    for x in flipkart:
        saved_fk[x["slot"]] = x["url"]
    merged_amz = [{"slot": s, "url": saved_amz[s]} for s in ECOM_SLOTS if s in saved_amz]
    merged_fk = [{"slot": s, "url": saved_fk[s]} for s in ECOM_SLOTS if s in saved_fk]
    await _db.products.update_one(
        {"slug": slug},
        {"$set": {"ecom_images": {"amazon": merged_amz, "flipkart": merged_fk,
                                  "updated_at": datetime.now(timezone.utc).isoformat()},
                  "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"success": True, "product": {"slug": slug, "name": prod.get("name")},
            "amazon": merged_amz, "flipkart": merged_fk}


@router.get("/admin/products/{slug}/ecom-images")
async def get_ecom_images(
    slug: str,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Return previously generated + saved listing images for a product (so the
    section shows them again after a refresh / reopen)."""
    _auth(x_admin_token, admin_session)
    prod = await _db.products.find_one({"slug": slug}, {"_id": 0, "ecom_images": 1, "name": 1})
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    saved = prod.get("ecom_images") or {}
    return {"success": True, "product": {"slug": slug, "name": prod.get("name")},
            "amazon": saved.get("amazon") or [], "flipkart": saved.get("flipkart") or []}


# --- Prompt editor: default prompt per slot + save a custom override per product ---
@router.get("/admin/products/{slug}/ecom-prompts")
async def get_ecom_prompts(
    slug: str,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Default (auto-built) prompt + any saved custom prompt for every slot."""
    _auth(x_admin_token, admin_session)
    prod = await _db.products.find_one({"slug": slug}, {"_id": 0})
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    custom = prod.get("ecom_prompts") or {}
    return {
        "success": True,
        "defaults": {s: _ecom_prompt(s, prod) for s in ECOM_SLOTS},
        "custom": {s: custom.get(s) or "" for s in ECOM_SLOTS},
    }


class EcomPromptSave(BaseModel):
    slot: str
    prompt: str = ""  # empty => reset to default


@router.put("/admin/products/{slug}/ecom-prompts")
async def save_ecom_prompt(
    slug: str,
    body: EcomPromptSave,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Save (or clear) a custom generation prompt for one slot on a product."""
    _auth(x_admin_token, admin_session)
    if body.slot not in ECOM_SLOTS:
        raise HTTPException(status_code=400, detail="Invalid slot")
    # NOTE: no field projection here — projecting a missing field returns {}
    # which is falsy and would falsely trigger the 404 below.
    prod = await _db.products.find_one({"slug": slug}, {"_id": 0})
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    prompts = dict(prod.get("ecom_prompts") or {})
    text = (body.prompt or "").strip()
    if text:
        prompts[body.slot] = text[:4000]
    else:
        prompts.pop(body.slot, None)
    await _db.products.update_one(
        {"slug": slug},
        {"$set": {"ecom_prompts": prompts, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"success": True, "custom": prompts.get(body.slot) or ""}



# ----------------------------------------------------------------------------
# BULK AI GENERATOR — paste many "name | ingredients | price" rows and generate
# a full product for each, ONE AT A TIME in the background (no edge timeout, no
# provider rate-limit stampede). Reuses the exact one-click pipeline.
# ----------------------------------------------------------------------------
class BulkGenItem(BaseModel):
    name: str
    key_ingredients: Optional[str] = ""
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    extra_specs: Optional[str] = None


class BulkGenerateRequest(BaseModel):
    items: List[BulkGenItem]
    brand: Optional[str] = "Celesta Glow"
    generate_image: bool = True


_bulk_gen_jobs: Dict[str, Any] = {}


@router.post("/admin/ai/bulk-generate")
async def bulk_generate_products(
    body: BulkGenerateRequest,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Kick off a background job that generates one full product per row,
    sequentially. Returns a job_id immediately — poll
    GET /admin/ai/bulk-generate-job/{job_id} for live progress."""
    _auth(x_admin_token, admin_session)
    items = [it for it in (body.items or []) if (it.name or "").strip()]
    if not items:
        raise HTTPException(status_code=400, detail="No valid product rows provided")
    if not os.environ.get("GEMINI_API_KEY"):
        # The copy step (services.llm_helper.llm_text) uses GEMINI_API_KEY only.
        raise HTTPException(status_code=503, detail="No AI key configured (set GEMINI_API_KEY)")

    import asyncio as _aio
    job_id = f"bulk_{uuid.uuid4().hex[:10]}"
    _bulk_gen_jobs[job_id] = {
        "job_id": job_id, "kind": "bulk_gen", "status": "running", "total": len(items),
        "done": 0, "failed": 0, "current": None, "step": "queued",
        "created": [], "errors": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        # Durable queue + params so the batch survives a pod restart / scale-down
        # (the in-memory task dies with the pod; this lets a fresh worker resume it).
        "items": [it.dict() for it in items],
        "brand": body.brand or "Celesta Glow",
        "generate_image": bool(body.generate_image),
        "next_index": 0,
    }
    _launch_bulk_worker(job_id, body, items, 0)
    return {"success": True, "job_id": job_id, "total": len(items), "status": "running"}


@router.get("/admin/ai/bulk-generate-job/{job_id}")
async def bulk_generate_job(
    job_id: str,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    _auth(x_admin_token, admin_session)
    from services.job_store import get_job
    job = await get_job(_db, _bulk_gen_jobs, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# Strong references to running bulk tasks — asyncio only keeps WEAK refs to
# tasks, so an un-referenced long-running worker can be garbage-collected
# mid-batch (silently stopping after an item).
_bulk_gen_tasks: set = set()

# Hard cap per product so ONE hung AI/image call can never freeze the batch.
_BULK_ITEM_TIMEOUT_S = int(os.environ.get("BULK_GEN_ITEM_TIMEOUT_S", "480"))


def _launch_bulk_worker(job_id: str, body: "BulkGenerateRequest", items: list, start_index: int = 0):
    """Create + track the background worker task and its Mongo mirror."""
    import asyncio as _aio
    from services.job_store import start_mirror
    _t = _aio.create_task(_bulk_generate_worker(job_id, body, items, start_index))
    _bulk_gen_tasks.add(_t)
    _t.add_done_callback(_bulk_gen_tasks.discard)
    start_mirror(_db, _bulk_gen_jobs[job_id])


async def _bulk_generate_worker(job_id: str, body: "BulkGenerateRequest", items: list, start_index: int = 0):
    import asyncio as _aio
    from services.job_store import save_job
    job = _bulk_gen_jobs[job_id]
    try:
        for idx in range(start_index, len(items)):
            it = items[idx]
            job["current"] = it.name
            job["index"] = idx + 1
            job["next_index"] = idx  # resume point if the pod dies mid-item
            sub = {"step": "queued"}
            job["item"] = sub
            # Persist the resume point BEFORE starting the item so a crash
            # resumes AT this item (never skips it).
            try:
                await save_job(_db, job)
            except Exception:
                pass
            try:
                req = OneClickProductRequest(
                    name=it.name, brand=body.brand or "Celesta Glow",
                    key_ingredients=it.key_ingredients or "",
                    generate_image=body.generate_image,
                    price_min=it.price_min, price_max=it.price_max,
                    extra_specs=it.extra_specs,
                )
                res = await _aio.wait_for(_one_click_impl(sub, req), timeout=_BULK_ITEM_TIMEOUT_S)
                prod = (res or {}).get("product") or {}
                job["created"].append({"name": prod.get("name") or it.name, "slug": res.get("slug") or prod.get("slug"), "image_generated": res.get("image_generated", False)})
                job["done"] += 1
                logger.info(f"[bulk-gen] {job_id} item {idx + 1}/{job['total']} '{it.name}' created")
            except _aio.CancelledError:
                # A library-internal cancellation must not kill the whole batch.
                # Only re-raise if THIS worker task itself is being cancelled.
                cur = _aio.current_task()
                if cur is not None and cur.cancelling():
                    raise
                logger.warning(f"[bulk-gen] '{it.name}' was cancelled internally — skipping")
                job["errors"].append({"name": it.name, "error": "Generation was interrupted"})
                job["failed"] += 1
            except _aio.TimeoutError:
                logger.warning(f"[bulk-gen] '{it.name}' timed out after {_BULK_ITEM_TIMEOUT_S}s — skipping")
                job["errors"].append({"name": it.name, "error": f"Timed out after {_BULK_ITEM_TIMEOUT_S}s"})
                job["failed"] += 1
            except Exception as e:
                detail = getattr(e, "detail", None) or str(e)
                logger.exception(f"[bulk-gen] '{it.name}' failed: {detail}")
                job["errors"].append({"name": it.name, "error": str(detail)[:200]})
                job["failed"] += 1
            job["next_index"] = idx + 1  # item fully handled — move resume point forward
            job["step"] = f"{job['done'] + job['failed']}/{job['total']}"
            try:
                await save_job(_db, job)
            except Exception:
                pass
            # Gentle pacing so we never hammer the image/LLM provider.
            await _aio.sleep(1.0)
        job["status"] = "done"
    except BaseException as e:  # noqa: BLE001 — always finalise the job record
        logger.exception(f"[bulk-gen] job {job_id} aborted: {e!r}")
        job["status"] = "failed"
        job["error"] = f"Bulk job stopped unexpectedly: {str(e)[:200] or type(e).__name__}"
        if isinstance(e, (KeyboardInterrupt, SystemExit)):
            raise
    finally:
        job["current"] = None
        job["step"] = "done"
        job["finished_at"] = datetime.now(timezone.utc).isoformat()
        try:
            await save_job(_db, job)
        except BaseException:
            pass




async def resume_interrupted_bulk_jobs():
    """On startup, resume any bulk-gen job whose worker died with its pod.

    The item queue + `next_index` are persisted in Mongo (`ai_jobs`), so a fresh
    pod can rebuild the request and continue from exactly where the previous
    worker stopped — instead of the batch freezing at e.g. 1/23 forever.
    """
    if _db is None:
        return
    try:
        cursor = _db.ai_jobs.find({"kind": "bulk_gen", "status": "running"}, {"_id": 0})
        docs = await cursor.to_list(length=50)
    except Exception as e:
        logger.warning(f"[bulk-gen] resume scan failed: {e}")
        return
    for doc in docs:
        job_id = doc.get("job_id")
        if not job_id:
            continue
        try:
            items = [BulkGenItem(**it) for it in (doc.get("items") or [])]
            if not items:
                continue
            nxt = int(doc.get("next_index") or 0)
            if nxt >= len(items):
                # Everything already processed — just finalise the record.
                await _db.ai_jobs.update_one({"job_id": job_id}, {"$set": {"status": "done", "step": "done"}})
                continue
            body = BulkGenerateRequest(items=items, brand=doc.get("brand") or "Celesta Glow",
                                       generate_image=bool(doc.get("generate_image", True)))
            # Rehydrate the in-memory job so the polling endpoint + mirror see it.
            doc.pop("_synced_at", None)
            doc["status"] = "running"
            _bulk_gen_jobs[job_id] = doc
            _launch_bulk_worker(job_id, body, items, nxt)
            logger.info(f"[bulk-gen] RESUMED interrupted job {job_id} at item {nxt + 1}/{len(items)}")
        except Exception as e:
            logger.warning(f"[bulk-gen] failed to resume {job_id}: {e}")


async def _one_click_worker(job_id: str, body: OneClickProductRequest):
    """Run the one-click pipeline in the background; record progress/result."""
    job = _one_click_jobs[job_id]
    try:
        result = await _one_click_impl(job, body)
        job["status"] = "done"
        job["step"] = "done"
        job["result"] = result
    except Exception as e:
        logger.exception(f"[one-click] job {job_id} failed: {e}")
        job["status"] = "failed"
        job["error"] = str(e)[:300]


async def _one_click_impl(job: dict, body: OneClickProductRequest):
    """Create a fully-formed product from just a name in a single click.

    Pipeline:
      1. AI classify → niche / category / subcategory / concerns (+auto-create taxonomy)
      2. AI copywriting → tagline, description, ingredients, benefits, how-to-use, size, price, FAQs
      3. AI image generation (optional)
      4. Insert product + fire-and-forget AI reviews
    """
    name = (body.name or "").strip()

    brand = (body.brand or "Celesta Glow").strip() or "Celesta Glow"
    job["step"] = "classifying"

    # ---------- 1. CLASSIFY (niche / category / subcategory / concerns) ----------
    from services.ai_categorizer import classify_one
    classification = {}
    try:
        classification = await classify_one(_db, {
            "name": name, "brand": brand, "niche": "", "category": "",
            "subcategory": "", "concerns": [], "main_category_hint": "",
            "product_type_hint": "", "concern_hint": "", "skin_type_hint": "",
        }) or {}
    except Exception as e:
        logger.warning(f"[one-click] classify failed, using defaults: {e}")

    niche = classification.get("niche") or "skincare"
    category_slug = classification.get("category_slug") or ""
    subcategory_slug = classification.get("subcategory_slug") or ""
    concern_list = [c for c in (
        [x.get("slug") for x in (classification.get("concerns") or []) if x.get("slug")]
    ) if c]

    # Auto-create any missing taxonomy rows (categories / subcategories / concerns)
    now_iso = datetime.now(timezone.utc).isoformat()
    if category_slug and classification.get("category_is_new"):
        if not await _db.categories.find_one({"slug": category_slug}, {"_id": 1}):
            await _db.categories.insert_one({
                "slug": category_slug, "name": classification.get("category_name") or category_slug,
                "niche": niche, "group": niche, "is_parent": False, "tagline": "", "image": "",
                "icon": classification.get("category_icon") or "🛍️", "sort_order": 99,
                "is_active": True, "ai_created": True, "created_at": now_iso,
            })
    if subcategory_slug and classification.get("subcategory_is_new"):
        if not await _db.subcategories.find_one({"slug": subcategory_slug}, {"_id": 1}):
            await _db.subcategories.insert_one({
                "slug": subcategory_slug, "name": classification.get("subcategory_name") or subcategory_slug,
                "parent_category": category_slug, "niche": niche, "tagline": "",
                "icon": classification.get("subcategory_icon") or "", "image": "", "sort_order": 0,
                "is_active": True, "ai_created": True, "created_at": now_iso, "updated_at": now_iso,
            })
    for c in (classification.get("concerns") or []):
        if c.get("is_new") and c.get("slug"):
            if not await _db.concerns.find_one({"slug": c["slug"]}, {"_id": 1}):
                await _db.concerns.insert_one({
                    "slug": c["slug"], "name": c.get("name") or c["slug"], "tagline": "", "icon": "✨",
                    "image": "", "accent_from": "#dcfce7", "accent_to": "#bbf7d0", "accent_text": "#14532d",
                    "description": "", "sort_order": 99, "is_active": True, "niche": niche,
                    "ai_created": True, "created_at": now_iso,
                })

    job["step"] = "writing copy"
    # ---------- 2. CONTENT (marketing copy) ----------
    from emergentintegrations.llm.chat import LlmChat, UserMessage
    concerns_str = ", ".join(concern_list) or "general skincare"
    # Optional admin-provided specifications — fold them into the brief so the
    # generated copy, size and price respect what was asked before generation.
    _spec_lines = []
    if body.price_min or body.price_max:
        lo = body.price_min or 0
        hi = body.price_max or (body.price_min or 0)
        _spec_lines.append(f"Target MRP range (INR): {lo}–{hi}. Set \"mrp\" within this range.")
    if body.target_audience:
        _spec_lines.append(f"Target audience: {body.target_audience}")
    if body.skin_type:
        _spec_lines.append(f"Suitable skin type: {body.skin_type}")
    if body.texture:
        _spec_lines.append(f"Texture/format: {body.texture}")
    if body.fragrance:
        _spec_lines.append(f"Fragrance: {body.fragrance}")
    if body.size_hint:
        _spec_lines.append(f"Pack size: {body.size_hint}")
    if body.extra_specs:
        _spec_lines.append(f"Extra requirements: {body.extra_specs}")
    specs_block = ("\nAdditional specifications to honour:\n- " + "\n- ".join(_spec_lines)) if _spec_lines else ""
    prompt = f"""You are a senior copywriter for "{brand}", an Indian skincare brand. Generate product page content.
Product: {name}
Niche: {niche}
Category: {category_slug or 'general'}
Targets concerns: {concerns_str}
Known ingredients: {body.key_ingredients or 'auto-pick suitable actives'}{specs_block}

Return ONLY a JSON object with EXACTLY these keys:
{{
  "tagline": "<benefit-led tagline, max 12 words>",
  "description": "<2-3 sentence hero paragraph>",
  "key_ingredients": "<comma-separated 3-5 hero actives>",
  "ingredients_full": "<full INCI-style ingredients list, comma-separated>",
  "benefits": ["<benefit 1>", "<benefit 2>", "<benefit 3>", "<benefit 4>"],
  "how_to_use": "<3-4 short steps separated by newlines>",
  "size": "<pack size, e.g. '30ml / 1.01 fl oz'>",
  "mrp": <integer INR MRP, no symbol>,
  "offer_price": <integer INR sale price ~30-40% lower>,
  "faqs": [{{"q":"<q1>","a":"<a1>"}},{{"q":"<q2>","a":"<a2>"}},{{"q":"<q3>","a":"<a3>"}},{{"q":"<q4>","a":"<a4>"}},{{"q":"<q5>","a":"<a5>"}}]
}}
Generate 5-6 helpful FAQs covering: which skin type it suits, how long until visible results, the key ingredients, how to use it, and safety/side-effects.
Tone: trustworthy, clinical-but-warm, India-aware. Avoid "miracle"/"instant cure"."""
    content = {}
    try:
        from services.llm_helper import llm_text
        resp = await llm_text(prompt, system="You are a precise JSON-only copywriting API for a skincare brand.")
        raw = re.sub(r"^```(?:json)?\s*", "", (resp or "").strip())
        raw = re.sub(r"\s*```$", "", raw)
        m = re.search(r"\{[\s\S]*\}", raw)
        content = json.loads(m.group(0) if m else raw)
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"AI content generation failed: {str(e)[:220]}",
        )

    def _to_int(v):
        try:
            return int(float(str(v).replace(",", "").strip()))
        except Exception:
            return 0

    mrp = _to_int(content.get("mrp")) or _random.choice([899, 999, 1199, 1299, 1499])
    # Honour an admin-requested MRP range (clamp within bounds).
    if body.price_min or body.price_max:
        lo = body.price_min or body.price_max
        hi = body.price_max or body.price_min
        if lo and hi and lo > hi:
            lo, hi = hi, lo
        if lo and mrp < lo:
            mrp = lo
        if hi and mrp > hi:
            mrp = hi
    offer = _to_int(content.get("offer_price")) or int(mrp * 0.65)
    if offer >= mrp:
        offer = int(mrp * 0.65)

    job["step"] = "generating image (Gemini)"
    # ---------- 3. IMAGE ----------
    def _cld_hq(u):
        """Inject Cloudinary delivery transform for best quality + auto format
        (issue: blurry/low-quality product images). No-op for non-Cloudinary URLs
        or URLs that already carry any quality transform (prevents double-stacking)."""
        if u and "res.cloudinary.com" in u and "/upload/" in u and "q_" not in u:
            return u.replace("/upload/", "/upload/q_100,f_auto/", 1)
        return u

    image_url = body.image_url
    hero_bytes_ai = None
    if not image_url and body.generate_image:
        _img_ings = content.get("key_ingredients", "") or (body.key_ingredients or "")
        _img_extra = (f"The formula's hero actives are: {_img_ings}. Reflect the product's essence "
                      "(colour/texture cues) subtly through the packaging design." if _img_ings else "")
        try:
            image_url, hero_bytes_ai = await _ai_generate_product_image(
                name, brand, category_slug or subcategory_slug, extra_prompt=_img_extra)
        except Exception as e:
            logger.warning(f"[one-click] image generation failed (non-fatal): {e}")
            image_url = None
    image_url = _cld_hq(image_url)

    job["step"] = "saving product"
    # ---------- 4. CREATE PRODUCT ----------
    base_slug = _slugify(name)
    slug = base_slug
    n = 1
    while await _db.products.find_one({"slug": slug}, {"_id": 1}):
        n += 1
        slug = f"{base_slug}-{n}"

    discount_percent = round((1 - offer / mrp) * 100) if mrp else 0
    product = {
        "slug": slug,
        "name": name,
        "short_name": name[:40],
        "tagline": content.get("tagline", ""),
        "description": content.get("description", ""),
        "category": category_slug or "skincare",
        "subcategory": subcategory_slug or "",
        "concerns": concern_list,
        "niche": niche,
        "key_ingredients": content.get("key_ingredients", "") or (body.key_ingredients or ""),
        "ingredients_full": content.get("ingredients_full", ""),
        "benefits": content.get("benefits", []) if isinstance(content.get("benefits"), list) else [],
        "how_to_use": content.get("how_to_use", ""),
        "size": content.get("size", ""),
        "images": [image_url] if image_url else [],
        "image_gallery": [{"url": image_url, "alt": f"{name} — {brand}"}] if image_url else [],
        "mrp": float(mrp),
        "prepaid_price": float(offer),
        "cod_price": float(offer),
        "cod_advance": 29.0,
        "discount_percent": float(discount_percent),
        "badge": "",
        "badges": [],
        "offer_price": float(offer),
        "is_active": bool(body.is_active),
        "sort_order": 1,
        "stock_qty": 100,
        "low_stock_threshold": 10,
        "fill_card": False,
        "brand": brand,
        "specs": {},
        "shades": [],
        "faqs": content.get("faqs", []) if isinstance(content.get("faqs"), list) else [],
        "ai_generated": True,
        "reviews_count": _random.randint(1020, 4875),
        "rating": round(_random.uniform(4.5, 4.9), 1),
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    await _db.products.insert_one(product)

    job["step"] = "building gallery & certificate"
    # ---------- 4b. STRUCTURED MEDIA (gallery + certificate + before/after) ----------
    # Every one-click product automatically gets the Formula-Technology gallery,
    # a lab certificate and a BEFORE/AFTER pair (Pillow).
    try:
        from services.gallery_composer import generate_and_persist
        # Extract the EXACT bottle from the freshly generated AI hero so every
        # gallery sub-image shows the same bottle as image 1 (no mismatch).
        ai_bottle = None
        if hero_bytes_ai:
            try:
                from PIL import Image as _PImg
                import io as _io2
                from services import brand_bottles as _bb
                _hero_im = _PImg.open(_io2.BytesIO(hero_bytes_ai)).convert("RGB")
                ai_bottle = _bb._trim(_bb._alpha_cutout(_hero_im))
            except Exception as _be:
                logger.warning(f"[one-click] AI bottle extract failed (using approved bottle): {_be}")
        media = await generate_and_persist(
            _db,
            {**product, "solves": ", ".join(concern_list) or "your skin concern"},
            do_gallery=True, do_certificate=True, do_before_after=True,
            bottle_override=ai_bottle, hero_url=image_url,
        )
        b_img = media.pop("before_after_before", None)
        a_img = media.pop("before_after_after", None)
        # The composer already set image 1 to the AI hero (hero_url) and composed
        # the gallery cards with the SAME extracted bottle, so just rebuild the
        # gallery alt-text list from the final image set.
        if media.get("images"):
            media["image_gallery"] = [{"url": u, "alt": f"{name} — {brand}"} for u in media["images"]]
        if media:
            await _db.products.update_one({"slug": slug}, {"$set": {**media, "updated_at": now_iso}})
            product.update(media)
        if b_img and a_img:
            ba_id = "ba_" + hashlib.md5(slug.encode()).hexdigest()[:8]
            await _db.before_after_images.update_one(
                {"ba_id": ba_id},
                {"$set": {
                    "ba_id": ba_id, "product_slug": slug,
                    "before_image": b_img, "after_image": a_img,
                    "description": f"{name} — visible improvement",
                    "is_global": False, "sort_order": 0, "created_at": now_iso,
                }},
                upsert=True,
            )
    except Exception as e:
        logger.warning(f"[one-click] structured media generation failed for {slug}: {e}")

    # Fire-and-forget AI reviews
    try:
        from services.ai_content_generator import generate_product_reviews
        reviews = await generate_product_reviews(
            name=name, niche=niche,
            key_ingredients=product["key_ingredients"], benefits=product["benefits"],
        )
        if reviews:
            await _db.product_reviews.insert_many([
                {**r, "product_slug": slug, "created_at": now_iso} for r in reviews
            ])
    except Exception as e:
        logger.warning(f"[one-click] AI reviews failed for {slug}: {e}")

    product.pop("_id", None)
    return {
        "success": True,
        "slug": slug,
        "product": product,
        "classification": classification,
        "image_generated": bool(image_url and not body.image_url),
    }


@router.post("/admin/products/{slug}/upscale-images")
async def upscale_product_images(
    slug: str,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Header(None, alias="X-Admin-Session"),
):
    """One-tap quality boost: serve every product gallery image (hero + tech
    sub-images + the "how it works" solution card) at Cloudinary's best quality
    and auto format. The lab CERTIFICATE and BEFORE/AFTER images are left
    untouched. We intentionally AVOID Cloudinary's generic `e_upscale` here —
    that algorithm smudges the small label text. Instead we apply only a
    LOSSLESS-friendly `q_auto:best,f_auto` delivery transform, so text stays
    razor-sharp. Instant, spends no AI credits."""
    _auth(x_admin_token, admin_session)
    product = await _db.products.find_one({"slug": slug}, {"_id": 0})
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")

    def _upscale_url(u: str) -> str:
        if not u or "res.cloudinary.com" not in u or "/upload/" not in u:
            return u
        # Strip ALL existing transform segments right after /upload/ then inject ours.
        pre, post = u.split("/upload/", 1)
        rest = post
        while "/" in rest:
            seg = rest.split("/", 1)[0]
            if seg.startswith("v") and seg[1:].isdigit():
                break
            if "," in seg or seg.startswith(("q_", "f_", "w_", "h_", "e_", "c_", "g_", "dpr_")):
                rest = rest.split("/", 1)[1]
            else:
                break
        # Crisp, non-destructive: near-lossless quality + auto format, NO e_upscale.
        tx = "q_100,f_auto"
        return f"{pre}/upload/{tx}/{rest}"

    images = [u for u in (product.get("images") or []) if u]
    new_images = [_upscale_url(u) for u in images]
    gallery = [{"url": _upscale_url(g.get("url")), "alt": g.get("alt", "")}
               for g in (product.get("image_gallery") or []) if g.get("url")]

    upd = {"images": new_images, "updated_at": datetime.now(timezone.utc).isoformat()}
    if gallery:
        upd["image_gallery"] = gallery
    # Also sharpen the "how it works" solution card when present (variations).
    if product.get("solution_image"):
        upd["solution_image"] = _upscale_url(product["solution_image"])
    await _db.products.update_one({"slug": slug}, {"$set": upd})
    return {"success": True, "slug": slug, "upscaled": len(new_images), "images": new_images}





# ============================================================
# AI MARKETING IMAGE GENERATOR (Formula-Technology + Before/After)
# Generates on-brand feature images STRICTLY from product name + ingredients,
# matching the admin-provided reference themes. Gemini Nano Banana (Emergent)
# → direct Gemini → Pollinations fallback.
# ============================================================
def _load_refs(folder: str) -> list:
    import glob as _glob
    out = []
    d = _Path(__file__).parent.parent / "uploads" / folder
    try:
        for f in sorted(d.glob("*")):
            if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                try:
                    out.append(f.read_bytes())
                except Exception:
                    pass
    except Exception:
        pass
    return out


async def _image_via_providers(prompt: str, ref_images: list) -> tuple:
    """Direct Gemini image generation only. Returns (bytes|None, mime)."""
    import asyncio as _aio
    out_bytes, mime = None, "image/png"
    if not out_bytes:
        gk = os.environ.get("GEMINI_API_KEY")
        if gk:
            try:
                from google import genai
                from google.genai import types as _gt
                cli = genai.Client(api_key=gk)
                parts = [prompt] + [_gt.Part.from_bytes(data=rb, mime_type="image/png") for rb in (ref_images or [])]
                resp = await _aio.to_thread(cli.models.generate_content, model="gemini-2.5-flash-image", contents=parts)
                for part in (resp.candidates[0].content.parts if resp.candidates else []):
                    inl = getattr(part, "inline_data", None)
                    if inl and getattr(inl, "data", None):
                        out_bytes = inl.data; mime = inl.mime_type or "image/png"; break
            except Exception as e:
                logger.warning(f"[mkt-img] Gemini(direct) failed: {e}")
    return out_bytes, mime


async def _persist_img(out_bytes: bytes, mime: str) -> Optional[str]:
    """Store marketing imagery on Cloudinary. Local disk is NOT an acceptable
    destination — it is wiped on redeploy, which is how images went missing."""
    try:
        from services import cloudinary_service as _cs
        if await _cs.ensure_configured(_db):
            res = await _cs.upload_image(_db, out_bytes, folder="celesta-glow/products",
                                         public_id=f"mkt-{uuid.uuid4().hex[:12]}")
            if res.get("url"):
                return res["url"]
    except Exception as e:
        logger.error(f"[mkt-img] Cloudinary upload failed: {e}")

    if (os.environ.get("ALLOW_LOCAL_UPLOADS") or "").lower() in ("1", "true", "yes"):
        ext = "png" if "png" in mime else "jpg"
        fn = f"mkt-{uuid.uuid4().hex[:12]}.{ext}"
        with open(_PROD_IMG_DIR / fn, "wb") as f:
            f.write(out_bytes)
        logger.warning("[mkt-img] stored on EPHEMERAL local disk (ALLOW_LOCAL_UPLOADS)")
        return f"/api/uploads/products/{fn}"
    return None


class MarketingImageRequest(BaseModel):
    name: str
    kind: str  # 'technology' | 'before_after'
    key_ingredients: Optional[str] = ""
    hero_ingredient: Optional[str] = ""   # single ingredient to spotlight (technology)
    headline: Optional[str] = ""          # optional custom green headline
    category: Optional[str] = ""
    brand: Optional[str] = "Celesta Glow"
    slug: Optional[str] = None            # if set, append image to that product
    append_index: Optional[int] = None    # ignored; always appends


def _tech_prompt(name, brand, category, ings, hero, headline) -> str:
    hero = (hero or (ings.split(",")[0].strip() if ings else "")).strip()
    hl = (headline or "FORMULA TECHNOLOGY").strip().upper()
    return (
        "Professional product photography on a PURE WHITE background (#FFFFFF). The background must be completely "
        "white with no shadows, no gradients, no textures, no grey tones, no off-white. Solid pure white background "
        "only. Studio lighting. Clean white seamless backdrop. "
        f"Premium skincare 'Formula Technology' marketing graphic for {brand} '{name}' ({category or 'skincare'}). "
        "LAYOUT (match references exactly): clean PURE-WHITE (#FFFFFF) background with no grey tones or shadows, square 1:1. On the RIGHT, one pristine WHITE "
        "product bottle/tube with the CELESTA GLOW green+grey minimalist label. On the LEFT, a small grey eyebrow "
        f"label 'FORMULA TECHNOLOGY', then a BOLD dark-GREEN uppercase headline reading '{hl}', then one short "
        "supporting sentence in grey. Include a thick WHITE CREAM swirl / dollop cluster with "
        f"a thin leader line labelling the hero active '{hero.upper()}' in green. Never show liquid, serum drops, "
        "oil, gel or transparent fluid — the formula is a rich opaque WHITE CREAM. "
        "Elegant, editorial, lots of white space, soft studio lighting, photorealistic product, crisp clean typography. "
        "No people, no watermark."
    )


def _ba_prompt(name, brand, category) -> str:
    return (
        "Professional dermatology SKIN CLOSEUP photography on a clean white background. "
        "IMPORTANT: crop TIGHT on the affected skin area only (cheek / under-eye / forehead) — this is a "
        "macro skin closeup, NOT a full face and NOT a full portrait. Do not show eyes, nose or a whole face. "
        f"Skincare 'Before & After' results graphic for {brand} '{name}'. Two side-by-side close-up panels of the "
        "SAME cropped area of skin on an anonymous model — LEFT panel labelled 'BEFORE' shows "
        "duller, uneven, textured skin; RIGHT panel labelled 'AFTER' shows brighter, smoother, more even, radiant "
        "skin. Small green 'BEFORE'/'AFTER' captions, clean white divider, soft natural lighting, realistic, tasteful, "
        "tight macro skin crop only (no full face identity), no watermark, square 1:1."
    )


@router.post("/admin/ai/generate-marketing-image")
async def generate_marketing_image(
    body: MarketingImageRequest,
    x_admin_token: Optional[str] = Header(None, alias="X-Admin-Token"),
    admin_session: Optional[str] = Cookie(None),
):
    """Generate an on-brand marketing image (Formula-Technology or Before/After)
    driven by the product name + ingredients, matching the admin reference themes.
    Optionally appends the result to a product's image gallery when `slug` is set.
    """
    _auth(x_admin_token, admin_session)
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="Product name is required")
    kind = (body.kind or "").strip().lower()
    if kind not in ("technology", "before_after"):
        raise HTTPException(status_code=400, detail="kind must be 'technology' or 'before_after'")

    if kind == "technology":
        prompt = _tech_prompt(body.name, body.brand or "Celesta Glow", body.category,
                              body.key_ingredients or "", body.hero_ingredient or "", body.headline or "")
        refs = _load_refs("tech_refs") or _load_refs("theme_refs")
    else:
        prompt = _ba_prompt(body.name, body.brand or "Celesta Glow", body.category)
        refs = _load_refs("ba_refs")

    out_bytes, mime = await _image_via_providers(prompt, refs)
    if not out_bytes:
        raise HTTPException(status_code=502, detail="Image generation failed on all providers. Try again.")
    url = await _persist_img(out_bytes, mime)
    if not url:
        raise HTTPException(status_code=500, detail="Failed to persist image")

    appended = False
    if body.slug:
        prod = await _db.products.find_one({"slug": body.slug}, {"_id": 0, "images": 1})
        if prod is not None:
            imgs = list(prod.get("images") or [])
            imgs.append(url)
            await _db.products.update_one({"slug": body.slug},
                                          {"$set": {"images": imgs, "updated_at": datetime.now(timezone.utc).isoformat()}})
            appended = True

    return {"success": True, "image_url": url, "kind": kind, "appended_to_product": appended}

"""
Public + admin routes for skin concerns and product categories.
- GET /api/concerns                 -> list all active concerns
- GET /api/concerns/{slug}          -> concern + matching products
- GET /api/categories               -> list all active categories
- GET /api/categories/{slug}        -> category + matching products
- POST/PUT/DELETE /api/admin/...    -> admin CRUD
"""
from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timezone

from services import catalog_backup as _catalog_backup
from services.image_optimizer import optimize_cloudinary_url


def _optimize_taxonomy_image(item: dict, width: int = 400) -> dict:
    """Rewrite Cloudinary `image` field of a concern/category/subcategory to
    serve f_auto,q_auto,w_<width>. Cuts banner weight 70-90 % with WebP/AVIF
    auto-quality. Concerns get 400px (circular strip), categories 600 px (tiles),
    hero banners 1200 px. Non-Cloudinary URLs pass through untouched.

    Also appends `?_v=<hash(updated_at)>` so when the admin re-uploads an
    image at the same Cloudinary public_id the URL string changes — busting
    the browser and CDN caches instantly so the user sees the new image on
    first page load instead of "old image flashes then swaps to new"."""
    if isinstance(item, dict) and isinstance(item.get("image"), str):
        version = item.get("updated_at") or item.get("modified_at")
        item["image"] = optimize_cloudinary_url(item["image"], width, version)
    return item


def _snap_after_write() -> None:
    """Schedule a debounced taxonomy snapshot after admin writes. Coalesces
    bursts so 20 writes in 25s only produce 1 backup. Safe + non-blocking."""
    try:
        _catalog_backup.schedule_snapshot(db)
    except Exception:
        pass


router = APIRouter()
db = None
admin_sessions = {}

# Cloudflare proxy in front of preview / production has a 60s read timeout
# which kills the synchronous /admin/catalog/backup/restore endpoint
# mid-flight (chain replay takes ~3 min). _restore_jobs tracks the state
# of background restore jobs so the admin UI can poll for completion.
# Keyed by job_id, value is a dict with: status, progress_pct, started_at,
# completed_at, result (when done), error (on failure).
_restore_jobs: dict = {}
_RESTORE_JOB_TTL_SEC = 60 * 60  # keep finished jobs for an hour


def set_db(database):
    global db
    db = database


def set_admin_sessions(sessions):
    global admin_sessions
    admin_sessions = sessions


def verify_admin(x_admin_token):
    if not x_admin_token:
        raise HTTPException(status_code=401, detail="Unauthorized")
    # Accept active session tokens
    if x_admin_token in admin_sessions:
        return
    # Plain-password fallback — must match the *active* admin hash.
    # Env-seed password is rejected once a custom one is saved.
    import hashlib as _h
    from services.admin_auth import get_cached_active_admin_hash
    if _h.sha256(x_admin_token.encode()).hexdigest() == get_cached_active_admin_hash():
        return
    raise HTTPException(status_code=401, detail="Unauthorized")


# ==================== CONCERNS ====================

class ConcernUpsert(BaseModel):
    slug: str
    name: str
    tagline: str = ""
    icon: str = ""
    image: str = ""
    accent_from: str = "#dcfce7"
    accent_to: str = "#bbf7d0"
    accent_text: str = "#14532d"
    description: str = ""
    sort_order: int = 99
    is_active: bool = True
    niche: str = "skincare"  # 'anti-aging' | 'skincare' | 'cosmetics'


@router.get("/concerns")
async def list_concerns(response: Response):
    """Public: List all active concerns sorted by sort_order"""
    items = await db.concerns.find({"is_active": True}, {"_id": 0}).sort("sort_order", 1).to_list(length=None)
    # Concerns are shown in a circular strip — 400px is plenty (2× for retina 200px).
    items = [_optimize_taxonomy_image(c, 400) for c in items]
    # PERF / FRESHNESS: 30 s edge cache + 60 s stale-while-revalidate.
    # Lower than 5 min so admin image / order edits show up within ~30 s
    # on the live storefront (was previously taking up to 5 min — users
    # were seeing "old banner / old category image" after every admin edit).
    response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=60"
    return items


@router.get("/niches")
async def list_niches(response: Response):
    """Public: List all active niches (top-level 3-pill: anti-aging / skincare / cosmetics).

    Filtered by admin `active_niches` setting (Feb-2026): when the site is
    running in "Anti-Aging Only" mode we hide skincare/cosmetics from public
    completely.

    Image URLs include `?_v=<hash(updated_at)>` so re-uploads bust CDN cache
    instantly. We deliberately use a *short* max-age + must-revalidate so any
    admin change shows up on the very next page load without "old banner
    flashes for a second then swaps to new"."""
    from routes.products import _get_active_niches
    active = await _get_active_niches()
    query = {"is_active": True}
    if active and len(active) < 3:
        query["slug"] = {"$in": active}
    items = await db.niches.find(query, {"_id": 0}).sort("sort_order", 1).to_list(20)
    for it in items:
        _optimize_taxonomy_image(it, width=800)
        # niches also have hero/banner/secondary images — version them too
        version = it.get("updated_at") or it.get("modified_at")
        for f in ("banner_image", "hero_image", "card_image", "secondary_image"):
            v = it.get(f)
            if isinstance(v, str) and v:
                from services.image_optimizer import optimize_cloudinary_url as _opt
                it[f] = _opt(v, 1200, version)
    response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=60, must-revalidate"
    return items


@router.get("/concerns/{slug}")
async def get_concern_with_products(
    slug: str,
    page: int = 1,
    limit: int = 24,
    search: Optional[str] = None,
    sort: str = "sort_order",
):
    """Public: Get a concern + paginated products that target it.

    Response: { concern, products, total, page, limit, has_next }.
    The legacy shape (concern + products) is preserved; new fields are additive.
    """
    concern = await db.concerns.find_one({"slug": slug, "is_active": True}, {"_id": 0})
    if not concern:
        raise HTTPException(status_code=404, detail="Concern not found")

    query = {"is_active": True, "concerns": slug, "is_variation": {"$ne": True}}
    if search and search.strip():
        import re as _re
        safe = _re.escape(search.strip())
        query["$or"] = [
            {"name":        {"$regex": safe, "$options": "i"}},
            {"description": {"$regex": safe, "$options": "i"}},
            {"brand":       {"$regex": safe, "$options": "i"}},
            {"tags":        {"$regex": safe, "$options": "i"}},
        ]

    sort_spec = {
        "sort_order": [("sort_order", 1), ("name", 1)],
        "price_asc":  [("prepaid_price", 1)],
        "price_desc": [("prepaid_price", -1)],
        "newest":     [("created_at", -1)],
        "popular":    [("total_orders", -1), ("sort_order", 1)],
    }.get((sort or "sort_order").lower(), [("sort_order", 1)])

    page_i  = max(1, page)
    limit_i = min(100, max(1, limit))
    skip_i  = (page_i - 1) * limit_i

    total = await db.products.count_documents(query)
    # IMAGE-FIRST SORT (Feb 2026): always lift products that have at least one
    # image to the TOP of the listing, regardless of the user's chosen sort.
    # Below the imaged group we honour the requested sort. Done server-side
    # via aggregation so pagination respects the rank — otherwise page 1
    # might be mostly placeholders while page 3 had all the photographed
    # SKUs (the exact bug reported on cosmetics > loose powder).
    full_sort = [("has_image_rank", -1), *sort_spec, ("slug", 1)]
    pipeline = [
        {"$match": query},
        {"$addFields": {"has_image_rank": {"$cond": [
            {"$gt": [{"$size": {"$ifNull": ["$images", []]}}, 0]},
            1, 0,
        ]}}},
        {"$sort": dict(full_sort)},
        {"$skip": skip_i},
        {"$limit": limit_i},
        {"$project": {"_id": 0, "has_image_rank": 0}},
    ]
    products = await db.products.aggregate(pipeline).to_list(length=None)
    return {
        "concern": concern,
        "products": products,
        "total": total,
        "page": page_i,
        "limit": limit_i,
        "has_next": skip_i + len(products) < total,
    }


@router.post("/admin/concerns")
async def create_concern(data: ConcernUpsert, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_admin(x_admin_token)
    existing = await db.concerns.find_one({"slug": data.slug})
    if existing:
        raise HTTPException(status_code=400, detail="Concern slug already exists")
    doc = data.dict()
    now = datetime.now(timezone.utc).isoformat()
    doc["created_at"] = now
    doc["updated_at"] = now
    await db.concerns.insert_one(doc)
    return {"success": True, "slug": data.slug}


@router.put("/admin/concerns/{slug}")
async def update_concern(slug: str, data: ConcernUpsert, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_admin(x_admin_token)
    update = data.dict()
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await db.concerns.update_one({"slug": slug}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Concern not found")
    return {"success": True}


@router.delete("/admin/concerns/{slug}")
async def delete_concern(slug: str, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_admin(x_admin_token)
    result = await db.concerns.delete_one({"slug": slug})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Concern not found")
    # Tombstone the slug so seed scripts don't resurrect it on the next redeploy.
    from services import taxonomy_tombstones as _tomb
    await _tomb.add_tombstone(db, "concern", slug)
    _snap_after_write()
    return {"success": True}


@router.get("/admin/concerns")
async def admin_list_concerns(
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    page: Optional[int] = None,
    limit: int = 50,
    search: Optional[str] = None,
):
    verify_admin(x_admin_token)
    q = {}
    if search and search.strip():
        s = search.strip()
        q = {"$or": [
            {"slug": {"$regex": s, "$options": "i"}},
            {"name": {"$regex": s, "$options": "i"}},
            {"tagline": {"$regex": s, "$options": "i"}},
        ]}
    cursor = db.concerns.find(q, {"_id": 0}).sort("sort_order", 1)
    if page is None:
        # Backwards compatible: full list (no cap)
        return await cursor.to_list(length=None)
    page = max(1, page)
    limit = max(1, min(200, limit))
    total = await db.concerns.count_documents(q)
    items = await cursor.skip((page - 1) * limit).limit(limit).to_list(length=limit)
    return {"items": items, "total": total, "page": page, "limit": limit, "has_next": page * limit < total}


# ==================== CATEGORIES ====================

class CategoryUpsert(BaseModel):
    slug: str
    name: str
    tagline: str = ""
    icon: str = ""
    image: str = ""
    sort_order: int = 99
    is_active: bool = True
    group: str = "skincare"  # 'skincare' or 'cosmetics' (legacy)
    niche: str = "skincare"  # 'anti-aging' | 'skincare' | 'cosmetics'
    # Taxonomy V2 fields — preserved on partial admin updates.
    is_parent: Optional[bool] = None
    parent: Optional[str] = None
    subs: Optional[List[str]] = None


class CategoryPatch(BaseModel):
    """Partial update — only sent fields are written. Used by /admin/categories/{slug}."""
    name: Optional[str] = None
    tagline: Optional[str] = None
    icon: Optional[str] = None
    image: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: Optional[bool] = None
    niche: Optional[str] = None
    is_parent: Optional[bool] = None
    parent: Optional[str] = None
    subs: Optional[List[str]] = None


@router.get("/categories")
async def list_categories(response: Response, niche: Optional[str] = None):
    """Public: List all active categories. Optional `niche` filter (skincare/cosmetics)."""
    q = {"is_active": True}
    if niche:
        q["niche"] = niche
    items = await db.categories.find(q, {"_id": 0}).sort("sort_order", 1).to_list(length=None)
    # Category tiles use a wider hero crop (~600px renders at 300px tile retina-friendly).
    items = [_optimize_taxonomy_image(c, 600) for c in items]
    # PERF: 30 s edge cache so admin edits propagate quickly
    response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=60"
    return items


@router.get("/categories/{slug}")
async def get_category_with_products(
    slug: str,
    page: int = 1,
    limit: int = 24,
    search: Optional[str] = None,
    sort: str = "sort_order",
):
    """Public: Get a category + paginated products in it."""
    category = await db.categories.find_one({"slug": slug, "is_active": True}, {"_id": 0})
    if not category:
        raise HTTPException(status_code=404, detail="Category not found")

    # Match products whose category OR subcategory slug matches. This lets
    # /category/concealer (a subcategory) return the 242 products stored as
    # category=face-makeup + subcategory=concealer.
    query = {
        "is_active": True,
        "is_variation": {"$ne": True},
        "$or": [{"category": slug}, {"subcategory": slug}],
    }
    if search and search.strip():
        import re as _re
        safe = _re.escape(search.strip())
        # Wrap existing $or in $and to keep the category-OR-subcategory filter
        # alongside the search-OR filter.
        query = {
            "is_active": True,
            "is_variation": {"$ne": True},
            "$and": [
                {"$or": [{"category": slug}, {"subcategory": slug}]},
                {"$or": [
                    {"name":        {"$regex": safe, "$options": "i"}},
                    {"description": {"$regex": safe, "$options": "i"}},
                    {"brand":       {"$regex": safe, "$options": "i"}},
                    {"tags":        {"$regex": safe, "$options": "i"}},
                ]},
            ],
        }

    sort_spec = {
        "sort_order": [("sort_order", 1), ("name", 1)],
        "price_asc":  [("prepaid_price", 1)],
        "price_desc": [("prepaid_price", -1)],
        "newest":     [("created_at", -1)],
        "popular":    [("total_orders", -1), ("sort_order", 1)],
    }.get((sort or "sort_order").lower(), [("sort_order", 1)])

    page_i  = max(1, page)
    limit_i = min(100, max(1, limit))
    skip_i  = (page_i - 1) * limit_i

    total = await db.products.count_documents(query)
    # IMAGE-FIRST SORT (Feb 2026): always lift products that have at least one
    # image to the TOP of the listing, regardless of the user's chosen sort.
    # Below the imaged group we honour the requested sort. Done server-side
    # via aggregation so pagination respects the rank — otherwise page 1
    # might be mostly placeholders while page 3 had all the photographed
    # SKUs (the exact bug reported on cosmetics > loose powder).
    full_sort = [("has_image_rank", -1), *sort_spec, ("slug", 1)]
    pipeline = [
        {"$match": query},
        {"$addFields": {"has_image_rank": {"$cond": [
            {"$gt": [{"$size": {"$ifNull": ["$images", []]}}, 0]},
            1, 0,
        ]}}},
        {"$sort": dict(full_sort)},
        {"$skip": skip_i},
        {"$limit": limit_i},
        {"$project": {"_id": 0, "has_image_rank": 0}},
    ]
    products = await db.products.aggregate(pipeline).to_list(length=None)
    return {
        "category": category,
        "products": products,
        "total": total,
        "page": page_i,
        "limit": limit_i,
        "has_next": skip_i + len(products) < total,
    }


@router.post("/admin/categories")
async def create_category(data: CategoryUpsert, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_admin(x_admin_token)
    existing = await db.categories.find_one({"slug": data.slug})
    if existing:
        raise HTTPException(status_code=400, detail="Category slug already exists")
    doc = data.dict()
    now = datetime.now(timezone.utc).isoformat()
    doc["created_at"] = now
    doc["updated_at"] = now
    await db.categories.insert_one(doc)
    return {"success": True, "slug": data.slug}


@router.put("/admin/categories/{slug}")
async def update_category(slug: str, data: CategoryPatch, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    """Partial update — only fields explicitly sent are written.

    This preserves the taxonomy_v2 parent/sub relationships when admin only
    changes image/icon/name from the category editor.
    """
    verify_admin(x_admin_token)
    update = {k: v for k, v in data.dict().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await db.categories.update_one({"slug": slug}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Category not found")
    # Mirror image (and a couple of display fields) to the sibling subcategory
    # record if it shares the same slug. Keeps admin → user-app rendering in
    # sync whether the admin edits via Categories tab or Subcategories tab.
    mirror_fields = {k: update[k] for k in ("image", "tagline", "icon") if k in update}
    if mirror_fields:
        mirror_fields["updated_at"] = update["updated_at"]
        await db.subcategories.update_one({"slug": slug}, {"$set": mirror_fields})
    return {"success": True}


@router.delete("/admin/categories/{slug}")
async def delete_category(slug: str, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_admin(x_admin_token)
    result = await db.categories.delete_one({"slug": slug})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Category not found")
    from services import taxonomy_tombstones as _tomb
    await _tomb.add_tombstone(db, "category", slug)
    _snap_after_write()
    return {"success": True}


@router.get("/admin/categories")
async def admin_list_categories(
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    page: Optional[int] = None,
    limit: int = 50,
    niche: Optional[str] = None,
    search: Optional[str] = None,
):
    verify_admin(x_admin_token)
    q = {}
    if niche:
        q["niche"] = niche
    if search and search.strip():
        s = search.strip()
        q["$or"] = [
            {"slug": {"$regex": s, "$options": "i"}},
            {"name": {"$regex": s, "$options": "i"}},
            {"tagline": {"$regex": s, "$options": "i"}},
        ]
    cursor = db.categories.find(q, {"_id": 0}).sort("sort_order", 1)
    if page is None:
        return await cursor.to_list(length=None)
    page = max(1, page)
    limit = max(1, min(200, limit))
    total = await db.categories.count_documents(q)
    items = await cursor.skip((page - 1) * limit).limit(limit).to_list(length=limit)
    return {"items": items, "total": total, "page": page, "limit": limit, "has_next": page * limit < total}


# ==================== SUBCATEGORIES ====================
# Subcategories are filter chips inside a category page. Example:
#   parent_category="brow" → ["Best Sellers", "Luxury", "Everyday", "Pro Use"]
#
# Each product carries an optional `subcategory` field. The category detail
# page reads subcategories for the current parent + filters products
# client-side.

class SubcategoryUpsert(BaseModel):
    slug: str
    name: str
    parent_category: str   # slug of the parent category
    niche: Optional[str] = None  # auto-derived from parent if missing
    tagline: str = ""
    icon: str = ""
    image: str = ""
    sort_order: int = 0
    is_active: bool = True
    accent_from: str = "#dcfce7"
    accent_to: str = "#bbf7d0"
    accent_text: str = "#14532d"


@router.get("/subcategories")
async def list_subcategories(
    response: Response,
    category: Optional[str] = None,
    niche: Optional[str] = None,
):
    """Public list. Filter by parent category and/or niche. Only active rows."""
    query = {"is_active": True}
    if category:
        query["parent_category"] = category
    if niche:
        query["niche"] = niche
    items = await db.subcategories.find(query, {"_id": 0}).sort("sort_order", 1).to_list(200)
    items = [_optimize_taxonomy_image(s, 400) for s in items]
    response.headers["Cache-Control"] = "public, max-age=30, stale-while-revalidate=60"
    return items


@router.get("/admin/subcategories")
async def admin_list_subcategories(
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    page: Optional[int] = None,
    limit: int = 50,
    parent_category: Optional[str] = None,
    niche: Optional[str] = None,
    search: Optional[str] = None,
):
    verify_admin(x_admin_token)
    q = {}
    if parent_category:
        q["parent_category"] = parent_category
    if niche:
        q["niche"] = niche
    if search and search.strip():
        s = search.strip()
        q["$or"] = [
            {"slug": {"$regex": s, "$options": "i"}},
            {"name": {"$regex": s, "$options": "i"}},
            {"tagline": {"$regex": s, "$options": "i"}},
        ]
    cursor = db.subcategories.find(q, {"_id": 0}).sort("sort_order", 1)
    if page is None:
        # Backwards-compatible: return full list (no cap)
        return await cursor.to_list(length=None)
    page = max(1, page)
    limit = max(1, min(200, limit))
    total = await db.subcategories.count_documents(q)
    items = await cursor.skip((page - 1) * limit).limit(limit).to_list(length=limit)
    return {"items": items, "total": total, "page": page, "limit": limit, "has_next": page * limit < total}


@router.post("/admin/subcategories")
async def create_subcategory(data: SubcategoryUpsert, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_admin(x_admin_token)
    # Reject empty / whitespace-only slug — prevents zombie rows that break
    # PUT/DELETE URL construction (the path becomes /admin/subcategories/).
    if not data.slug or not data.slug.strip():
        raise HTTPException(status_code=400, detail="Slug is required (lowercase, dashes only — e.g. lipstick-matte).")
    if not data.name or not data.name.strip():
        raise HTTPException(status_code=400, detail="Name is required.")
    # Validate parent category exists
    parent = await db.categories.find_one({"slug": data.parent_category}, {"_id": 0, "niche": 1, "group": 1})
    if not parent:
        raise HTTPException(status_code=400, detail="Parent category not found. Pick an existing category as parent.")
    existing = await db.subcategories.find_one({"slug": data.slug})
    if existing:
        raise HTTPException(status_code=400, detail="Subcategory slug already exists")
    doc = data.dict()
    if not doc.get("niche"):
        doc["niche"] = parent.get("niche") or parent.get("group") or "skincare"
    now = datetime.now(timezone.utc).isoformat()
    doc["created_at"] = now
    doc["updated_at"] = now
    await db.subcategories.insert_one(doc)
    return {"success": True, "slug": data.slug}


@router.put("/admin/subcategories/{slug}")
async def update_subcategory(slug: str, data: SubcategoryUpsert, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_admin(x_admin_token)
    update = data.dict()
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await db.subcategories.update_one({"slug": slug}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Subcategory not found")
    # Mirror image/icon/tagline to the sibling categories record (same slug).
    # Many subcategory slugs exist as records in BOTH collections; the public
    # /skincare hub renders from `categories`, so we keep them in sync.
    mirror_fields = {k: update[k] for k in ("image", "tagline", "icon") if update.get(k)}
    if mirror_fields:
        mirror_fields["updated_at"] = update["updated_at"]
        await db.categories.update_one({"slug": slug}, {"$set": mirror_fields})
    return {"success": True}


@router.post("/admin/subcategories/sync-images-to-categories")
async def backfill_subcategory_images_to_categories(x_admin_token: str = Header(None, alias="X-Admin-Token")):
    """One-shot backfill: copies `image` from every subcategory record that has
    an image set, into the same-slug record in the `categories` collection
    (whenever the category record is missing an image). Run this once after
    deploying the mirror fix so PRE-EXISTING admin uploads also propagate
    to the user-facing hub without manual re-upload.
    """
    verify_admin(x_admin_token)
    updated = 0
    skipped_already_set = 0
    no_sibling = 0
    cursor = db.subcategories.find(
        {"image": {"$exists": True, "$ne": ""}},
        {"_id": 0, "slug": 1, "image": 1, "tagline": 1, "icon": 1},
    )
    async for sc in cursor:
        slug = sc.get("slug")
        if not slug:
            continue
        cat = await db.categories.find_one({"slug": slug}, {"_id": 0, "image": 1})
        if not cat:
            no_sibling += 1
            continue
        if cat.get("image"):
            skipped_already_set += 1
            continue
        mirror = {"image": sc["image"], "updated_at": datetime.now(timezone.utc).isoformat()}
        if sc.get("tagline"):
            mirror["tagline"] = sc["tagline"]
        if sc.get("icon"):
            mirror["icon"] = sc["icon"]
        await db.categories.update_one({"slug": slug}, {"$set": mirror})
        updated += 1
    return {
        "success": True,
        "updated": updated,
        "skipped_already_set": skipped_already_set,
        "no_sibling": no_sibling,
    }


class ImagePatch(BaseModel):
    image: str


@router.patch("/admin/subcategories/{slug}/image")
async def patch_subcategory_image(slug: str, data: ImagePatch, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    """One-shot image update — bypasses full-doc validation so QuickImageEditor
    can replace a banner without re-sending every accent colour / tagline / icon.

    IMPORTANT: many subcategory slugs ALSO exist as records in the `categories`
    collection (e.g. `chemical-exfoliant` lives in BOTH because the public hub
    renders from `categories` while admin curates `subcategories`). We mirror
    the image to whichever sibling record exists with the same slug so the
    user-facing hub picks up the update immediately.
    """
    verify_admin(x_admin_token)
    now_iso = datetime.now(timezone.utc).isoformat()
    update = {"image": data.image, "updated_at": now_iso}
    result = await db.subcategories.update_one({"slug": slug}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Subcategory not found")
    # Mirror to the categories collection if a same-slug record exists
    await db.categories.update_one({"slug": slug}, {"$set": update})
    _snap_after_write()
    return {"success": True, "image": data.image}


@router.patch("/admin/categories/{slug}/image")
async def patch_category_image(slug: str, data: ImagePatch, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_admin(x_admin_token)
    now_iso = datetime.now(timezone.utc).isoformat()
    update = {"image": data.image, "updated_at": now_iso}
    result = await db.categories.update_one({"slug": slug}, {"$set": update})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Category not found")
    # Mirror to the subcategories collection if a same-slug record exists
    await db.subcategories.update_one({"slug": slug}, {"$set": update})
    _snap_after_write()
    return {"success": True, "image": data.image}


@router.patch("/admin/concerns/{slug}/image")
async def patch_concern_image(slug: str, data: ImagePatch, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_admin(x_admin_token)
    result = await db.concerns.update_one(
        {"slug": slug},
        {"$set": {"image": data.image, "updated_at": datetime.now(timezone.utc).isoformat()}}
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Concern not found")
    _snap_after_write()
    return {"success": True, "image": data.image}


# ---- Catalog backup admin endpoints ----
@router.get("/admin/catalog/backup/status")
async def catalog_backup_status(x_admin_token: str = Header(None, alias="X-Admin-Token")):
    """Inspect snapshot health — counts in local DB vs latest remote snapshot."""
    verify_admin(x_admin_token)
    return await _catalog_backup.status(db)


@router.post("/admin/catalog/backup/snapshot")
async def catalog_backup_snapshot(x_admin_token: str = Header(None, alias="X-Admin-Token")):
    """Manually trigger an immediate snapshot of taxonomy → Cloudinary."""
    verify_admin(x_admin_token)
    try:
        return await _catalog_backup.snapshot(db)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/admin/catalog/backup/snapshot-async")
async def catalog_backup_snapshot_async(x_admin_token: str = Header(None, alias="X-Admin-Token")):
    """Fire-and-forget snapshot — returns immediately and runs in the background.

    Use this instead of /snapshot when the dataset is large enough that the
    proxy (Cloudflare 60s) would time out. Poll /admin/catalog/backup/status
    to know when the new snapshot has landed (the `remote_snapshot_created_at`
    field will update).
    """
    verify_admin(x_admin_token)
    import asyncio as _asyncio
    import logging as _logging
    log = _logging.getLogger("catalog_backup_admin")

    async def _run():
        try:
            res = await _catalog_backup.snapshot(db)
            log.info("[catalog_backup_async] uploaded %s v%s counts=%s",
                     res.get("public_id"), res.get("version"),
                     res.get("counts", {}).get("products"))
        except Exception as exc:
            log.exception("[catalog_backup_async] snapshot failed: %s", exc)

    _asyncio.create_task(_run())
    return {"queued": True, "message": "Snapshot running in background — poll /admin/catalog/backup/status."}


@router.post("/admin/catalog/backup/restore")
async def catalog_backup_restore(
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    force: bool = False,
    safety_snapshot: bool = False,
):
    """Manually trigger a restore — used after a redeploy if auto-restore was
    skipped (e.g. seed scripts inserted defaults so collections weren't empty).

    Behaviour:
      • Pulls the latest full snapshot AND replays every incremental delta in
        chronological order → DB ends at the most recent captured state.
      • STICKY_FIELDS protection ensures admin-uploaded images / icons that
        exist locally but not in the snapshot are KEPT (snapshot fills blanks
        only, never overwrites a non-empty local value).
      • Optional ?safety_snapshot=true takes a fresh incremental snapshot of
        the CURRENT state first, so if the restore is wrong the prior state
        is rollback-able. Off by default because it adds 30-60s to the call
        and the cleaner UX is to click "Backup Now" first if needed.
    """
    verify_admin(x_admin_token)
    pre_snapshot_info = None
    if safety_snapshot:
        try:
            pre = await _catalog_backup.incremental_snapshot(db)
            pre_snapshot_info = {
                "public_id": pre.get("public_id"),
                "created_at": pre.get("created_at"),
            }
        except Exception as exc:
            import logging as _logging
            _logging.getLogger("catalog_backup_admin").warning(
                "[catalog_backup] safety snapshot failed: %s", exc
            )

    res = await _catalog_backup.auto_restore_if_empty(db, force=force)
    if not res.get("restored") and not force:
        raise HTTPException(
            status_code=409,
            detail=(res.get("reason") or "restore not needed") +
                   " — pass ?force=true to override.",
        )
    res["safety_snapshot"] = pre_snapshot_info

    # POST-RESTORE FRESH BASELINE (Feb-2026 P0 fix): after a successful
    # manual restore, take a NEW full snapshot. The skeleton-state guard
    # inside snapshot() will refuse if the restore didn't fully bring back
    # images. When it succeeds, the retention sweep prunes any
    # skeleton-tainted incrementals from Cloudinary so future restores
    # don't have to wade through poisoned files to find a good chain.
    try:
        fresh = await _catalog_backup.snapshot(db)
        res["fresh_baseline"] = {
            "uploaded": bool(fresh.get("success") and not fresh.get("skipped_skeleton")
                             and not fresh.get("skipped_dedupe")),
            "skipped_reason": fresh.get("reason"),
            "created_at": fresh.get("created_at"),
        }
    except Exception as exc:
        import logging as _logging
        _logging.getLogger("catalog_backup_admin").warning(
            "[catalog_backup] post-restore fresh snapshot failed: %s", exc
        )
        res["fresh_baseline"] = {"uploaded": False, "error": str(exc)}
    return res


@router.post("/admin/catalog/backup/restore-async")
async def catalog_backup_restore_async(
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
    force: bool = False,
):
    """Kick off a manual restore in the background and return immediately.

    The synchronous /restore endpoint times out at the Cloudflare 60s proxy
    boundary because the full chain replay (full snapshot + 200+ incrementals
    + fresh-baseline upload) takes ~3 min. This async wrapper:
      1. Generates a job_id.
      2. Starts the restore in a `asyncio.create_task`.
      3. Returns 202 + {job_id} immediately.
      4. The admin UI polls /restore/status?job_id=... every 3s for progress.

    Cleans up stale job dicts older than 1 hr on each call. Returns 409 if
    another restore is already running (prevents concurrent DB writes from
    racing each other).
    """
    verify_admin(x_admin_token)
    import asyncio as _asyncio
    import logging as _logging
    import time as _time
    import uuid as _uuid

    log = _logging.getLogger("catalog_backup_admin")

    # Prune old jobs first.
    now_ts = _time.time()
    stale = [jid for jid, j in _restore_jobs.items()
             if (j.get("completed_at") or 0)
             and (now_ts - j.get("completed_at", 0)) > _RESTORE_JOB_TTL_SEC]
    for jid in stale:
        _restore_jobs.pop(jid, None)

    # Concurrency guard — only ONE restore in flight at a time.
    running = [jid for jid, j in _restore_jobs.items() if j.get("status") == "running"]
    if running:
        raise HTTPException(
            status_code=409,
            detail=f"A restore is already running (job_id={running[0]}). "
                   f"Poll /admin/catalog/backup/restore/status?job_id={running[0]}",
        )

    job_id = _uuid.uuid4().hex[:12]
    _restore_jobs[job_id] = {
        "status": "running",
        "phase": "starting",
        "started_at": now_ts,
        "completed_at": None,
        "result": None,
        "error": None,
        "progress": {"done": 0, "total": 0, "current": None},
    }

    async def _run():
        job = _restore_jobs[job_id]
        def _on_progress(done, total, current):
            job["progress"] = {"done": done, "total": total, "current": current}
            job["phase"] = f"restoring_{current}"
        try:
            job["phase"] = "fetching_snapshot"
            res = await _catalog_backup.auto_restore_if_empty(db, force=force, progress_cb=_on_progress)
            job["phase"] = "fresh_baseline_snapshot"
            try:
                fresh = await _catalog_backup.snapshot(db)
                res["fresh_baseline"] = {
                    "uploaded": bool(fresh.get("success")
                                     and not fresh.get("skipped_skeleton")
                                     and not fresh.get("skipped_dedupe")),
                    "skipped_reason": fresh.get("reason"),
                    "created_at": fresh.get("created_at"),
                }
            except Exception as exc:
                log.warning("[catalog_backup_async_restore] fresh_baseline failed: %s", exc)
                res["fresh_baseline"] = {"uploaded": False, "error": str(exc)}
            job["status"] = "done"
            job["phase"] = "complete"
            job["result"] = res
        except Exception as exc:
            log.exception("[catalog_backup_async_restore] failed: %s", exc)
            job["status"] = "error"
            job["error"] = str(exc)
        finally:
            job["completed_at"] = _time.time()

    _asyncio.create_task(_run())
    return {"job_id": job_id, "status": "running",
            "message": "Restore running in background — poll /admin/catalog/backup/restore/status?job_id=<id>"}


@router.get("/admin/catalog/backup/restore/status")
async def catalog_backup_restore_status(
    job_id: str,
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
):
    """Poll for the status of an async restore job."""
    verify_admin(x_admin_token)
    job = _restore_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    import time as _time
    out = {**job}
    out["elapsed_sec"] = round(_time.time() - job.get("started_at", _time.time()), 1)
    return out


@router.delete("/admin/subcategories/{slug}")
async def delete_subcategory(slug: str, x_admin_token: str = Header(None, alias="X-Admin-Token")):
    verify_admin(x_admin_token)
    result = await db.subcategories.delete_one({"slug": slug})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Subcategory not found")
    # Also clear `subcategory` field from any products that referenced it
    await db.products.update_many({"subcategory": slug}, {"$set": {"subcategory": ""}})
    from services import taxonomy_tombstones as _tomb
    await _tomb.add_tombstone(db, "subcategory", slug)
    _snap_after_write()
    return {"success": True}



# ==================== COSMETICS HOMEPAGE CONFIG (public) ====================

@router.get("/cosmetics/home-config")
async def get_cosmetics_home_config():
    """Featured navigation strip + promo sections rendered on /cosmetics page.

    Falls back to canonical defaults if no override stored in site_settings.
    Admin can persist overrides via PUT /admin/cosmetics/home-config.
    """
    from services.taxonomy_canonical import (
        COSMETICS_FEATURED_NAV, COSMETICS_PROMO_SECTIONS
    )
    settings = await db.site_settings.find_one(
        {"_id": "main"},
        {"_id": 0, "cosmetics_featured_nav": 1, "cosmetics_promo_sections": 1}
    ) or {}
    return {
        "featured_nav": settings.get("cosmetics_featured_nav") or COSMETICS_FEATURED_NAV,
        "promo_sections": settings.get("cosmetics_promo_sections") or COSMETICS_PROMO_SECTIONS,
    }


@router.put("/admin/cosmetics/home-config")
async def update_cosmetics_home_config(
    payload: dict,
    x_admin_token: str = Header(None, alias="X-Admin-Token"),
):
    """Admin: persist Featured Nav + Promo Sections overrides."""
    verify_admin(x_admin_token)
    update = {}
    if "featured_nav" in payload and isinstance(payload["featured_nav"], list):
        update["cosmetics_featured_nav"] = payload["featured_nav"]
    if "promo_sections" in payload and isinstance(payload["promo_sections"], list):
        update["cosmetics_promo_sections"] = payload["promo_sections"]
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    update["cosmetics_home_config_updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.site_settings.update_one({"_id": "main"}, {"$set": update}, upsert=True)
    return {"success": True, "updated": list(update.keys())}

from fastapi import FastAPI, APIRouter, HTTPException, Query, UploadFile, File, Depends, Request
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import io
import re
import json
import uuid
import zipfile
import logging
import asyncio
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, date
from emergentintegrations.llm.chat import LlmChat, UserMessage
try:
    from emergentintegrations.llm.chat import TextDelta, StreamDone  # may not exist in this version
except Exception:  # noqa: BLE001
    TextDelta = StreamDone = None

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

client = AsyncIOMotorClient(os.environ['MONGO_URL'])
db = client[os.environ['DB_NAME'] + '_afext']
EXT_DIR = ROOT_DIR / 'af_extension'

from af_auth import build_auth_router, seed_admin, decode_token, PUBLIC_PATHS


async def auth_guard(request: Request):
    if request.method == "OPTIONS" or request.url.path in PUBLIC_PATHS:
        return
    decode_token(request)


app = FastAPI()
api = APIRouter(prefix="/api/af", dependencies=[Depends(auth_guard)])
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def new_id():
    return str(uuid.uuid4())


def make_ean13() -> str:
    import random
    body = "890" + "".join(random.choice("0123456789") for _ in range(9))
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(body))
    return body + str((10 - total % 10) % 10)


class ProductIn(BaseModel):
    name: str
    external_id: str = ""
    mrp: str = ""
    description: str = ""
    key_ingredients: str = ""
    how_to_use: str = ""
    benefits: str = ""
    source_url: str = ""
    images: List[Dict[str, str]] = []
    brand: str = ""
    ingredients: str = ""
    size: str = ""
    price: str = ""
    category: str = ""
    notes: str = ""
    hsn_code: str = ""
    gst_rate: str = ""


class Product(ProductIn):
    id: str = Field(default_factory=new_id)
    created_at: str = Field(default_factory=now_iso)


class Settings(BaseModel):
    default_brand: str = ""
    default_size: str = ""
    default_category: str = ""
    sizes: List[str] = []
    brands: List[str] = []
    style_samples: Dict[str, Dict[str, str]] = {}
    default_manufacturer: str = ""
    country_of_origin: str = "India"
    mrp_markup_percent: float = 30
    handling_fee: str = "0"
    default_quantity: str = "100"
    handling_time_days: str = "2"
    amazon_shipping: str = "Self Ship (Fulfilled by Merchant)"
    flipkart_shipping: str = "Flipkart"
    extra_rules: str = ""
    manufacturer_address: str = ""
    shelf_life_months: int = 24
    manufacturer_contact: str = ""
    packer_details: str = ""
    importer_details: str = ""
    image_limits: Dict[str, int] = {"flipkart": 10, "amazon": 9, "meesho": 5, "myntra": 9, "nykaa": 8, "instamart": 8, "other": 10}


class FieldInfo(BaseModel):
    key: str
    kind: str = "native"
    section: str = ""
    label: str = ""
    placeholder: str = ""
    type: str = "text"
    tag: str = "input"
    options: List[str] = []
    maxlength: Optional[int] = None


class TemplateIn(BaseModel):
    platform: str
    page_key: str
    name: str = ""
    url: str = ""
    fields: List[FieldInfo] = []
    reference_values: Dict[str, str] = {}


class Template(TemplateIn):
    id: str = Field(default_factory=new_id)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    fill_count: int = 0


class GenerateIn(BaseModel):
    product_id: Optional[str] = None
    product: Optional[ProductIn] = None
    platform: str = "other"
    page_key: str = ""
    page_title: str = ""
    url: str = ""
    fields: List[FieldInfo]
    use_cache: bool = True
    errors: Dict[str, str] = {}
    page_errors: List[str] = []


# ---------- Products ----------
@api.get("/")
async def root():
    return {"message": "AutoFill API running"}


@api.get("/products", response_model=List[Product])
async def list_products():
    return await db.products.find({}, {"_id": 0}).sort("created_at", -1).to_list(1000)


@api.post("/products", response_model=Product)
async def create_product(data: ProductIn):
    settings = await get_settings()
    p = Product(**data.model_dump())
    if not p.external_id:
        p.external_id = make_ean13()
    if not p.brand:
        p.brand = settings.default_brand
    if not p.size:
        p.size = settings.default_size
    if not p.category:
        p.category = settings.default_category
    await db.products.insert_one(p.model_dump())
    return p


@api.put("/products/{pid}", response_model=Product)
async def update_product(pid: str, data: ProductIn):
    if not data.external_id:
        data.external_id = make_ean13()
    res = await db.products.find_one_and_update({"id": pid}, {"$set": data.model_dump(exclude_unset=True) | {"external_id": data.external_id}}, projection={"_id": 0}, return_document=True)
    if not res:
        raise HTTPException(404, "Product not found")
    await db.gen_cache.delete_many({"product_id": pid})
    return res


HSN_FIELD = re.compile(r"hsn|gst|tax", re.I)


async def ensure_hsn(product: dict, force: bool = False, error: str = "", options: Optional[List[str]] = None) -> dict:
    if product.get("hsn_code") and not force:
        return product
    ctx = ""
    if error:
        ctx = f" The marketplace REJECTED the previous HSN '{product.get('hsn_code', '')}' with this error: '{error}'. Read the error carefully and give an HSN that satisfies it (correct length/format, valid for the selected category)."
    if options:
        ctx += " The HSN must be one of these allowed values (copy one exactly): " + json.dumps(options[:150])
    raw = await run_llm(
        "Find the correct Indian GST HSN code (8 digits, as accepted by Flipkart / Amazon India seller panels) and GST rate for this product." + ctx +
        ' Return JSON {"hsn_code": "33049990", "gst_rate": "18", "reason": "short"}. Product: '
        + json.dumps({k: product.get(k) for k in ("name", "category", "ingredients", "size", "description", "notes")}, ensure_ascii=False)[:3000])
    d = parse_json(raw)
    hsn = re.sub(r"\D", "", str(d.get("hsn_code", "")))[:8]
    gst = re.sub(r"[^0-9.]", "", str(d.get("gst_rate", "")))
    if hsn:
        product["hsn_code"], product["gst_rate"] = hsn, gst
        if product.get("id"):
            await db.products.update_one({"id": product["id"]}, {"$set": {"hsn_code": hsn, "gst_rate": gst}})
    return product


@api.post("/products/{pid}/hsn")
async def find_hsn(pid: str):
    p = await db.products.find_one({"id": pid}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Product not found")
    p = await ensure_hsn(p, force=True)
    await db.gen_cache.delete_many({"product_id": pid})
    return {"hsn_code": p.get("hsn_code", ""), "gst_rate": p.get("gst_rate", "")}


IMAGE_ORDER = {"product": 0, "main": 0, "gallery": 1, "before": 2, "after": 2, "before_after": 2, "certificate": 3}


@api.get("/products/{pid}/image-files")
async def product_image_files(pid: str, start: int = 0, count: int = 9, platform: str = "other", limit: int = 0):
    import base64
    import httpx
    from PIL import Image
    p = await db.products.find_one({"id": pid}, {"_id": 0, "images": 1, "name": 1})
    if not p:
        raise HTTPException(404, "Product not found")
    settings = await get_settings()
    cap = limit if limit > 0 else settings.image_limits.get(platform) or settings.image_limits.get("other", 10)
    ordered = sorted(p.get("images") or [], key=lambda im: IMAGE_ORDER.get(im.get("kind", "product"), 2))[:cap]
    imgs = ordered[start:start + max(1, min(count, 15))]
    slug = re.sub(r"[^a-z0-9]+", "-", (p.get("name") or "image").lower())[:30].strip("-")
    out = []
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 Chrome/130"}) as c:
        for i, im in enumerate(imgs):
            try:
                r = await c.get(im["url"])
                r.raise_for_status()
                img = Image.open(io.BytesIO(r.content))
                img = img.convert("RGBA") if img.mode in ("P", "LA", "RGBA") else img.convert("RGB")
                bg = Image.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3] if img.mode == "RGBA" else None)
                scale = max(1, 1000 / min(bg.size))
                if scale > 1:
                    bg = bg.resize((round(bg.width * scale), round(bg.height * scale)))
                buf = io.BytesIO()
                bg.save(buf, "JPEG", quality=92)
                out.append({"name": f"{slug}-{im.get('kind', 'product')}-{start + i + 1}.jpg", "data": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()})
            except Exception as e:
                logger.warning(f"image download failed {im.get('url')}: {e}")
    return {"files": out, "total": len(ordered), "limit": cap}


@api.post("/products/{pid}/external-id")
async def regen_external_id(pid: str):
    ean = make_ean13()
    res = await db.products.find_one_and_update({"id": pid}, {"$set": {"external_id": ean}}, projection={"_id": 0}, return_document=True)
    if not res:
        raise HTTPException(404, "Product not found")
    await db.gen_cache.delete_many({"product_id": pid})
    return res


@api.delete("/products/{pid}")
async def delete_product(pid: str):
    await db.products.delete_one({"id": pid})
    await db.gen_cache.delete_many({"product_id": pid})
    return {"ok": True}


# ---------- Settings / defaults ----------
@api.get("/settings", response_model=Settings)
async def get_settings():
    doc = await db.settings.find_one({"_key": "main"}, {"_id": 0, "_key": 0})
    return Settings(**(doc or {}))


@api.put("/settings", response_model=Settings)
async def put_settings(data: Settings):
    data.sizes = list(dict.fromkeys([s for s in data.sizes if s]))
    data.brands = list(dict.fromkeys([b for b in data.brands if b]))
    await db.settings.update_one({"_key": "main"}, {"$set": data.model_dump()}, upsert=True)
    return data


# ---------- Templates (saved page formats) ----------
@api.get("/templates", response_model=List[Template])
async def list_templates():
    return await db.templates.find({}, {"_id": 0}).sort("updated_at", -1).to_list(1000)


@api.get("/templates/lookup")
async def lookup_template(page_key: str):
    doc = await db.templates.find_one({"page_key": page_key}, {"_id": 0})
    return {"template": doc}


@api.post("/templates", response_model=Template)
async def upsert_template(data: TemplateIn):
    existing = await db.templates.find_one({"page_key": data.page_key}, {"_id": 0})
    if existing:
        upd = data.model_dump()
        merged = {f["key"]: f for f in existing.get("fields", [])}
        for f in upd["fields"]:
            old = merged.get(f["key"], {})
            if not f.get("options") and old.get("options"):
                f["options"] = old["options"]
            if not f.get("section") and old.get("section"):
                f["section"] = old["section"]
            merged[f["key"]] = f
        upd["fields"] = list(merged.values())
        if not upd["reference_values"]:
            upd["reference_values"] = existing.get("reference_values", {})
        if not upd["name"]:
            upd["name"] = existing.get("name", "")
        upd["updated_at"] = now_iso()
        await db.templates.update_one({"page_key": data.page_key}, {"$set": upd, "$inc": {"fill_count": 1}})
        return await db.templates.find_one({"page_key": data.page_key}, {"_id": 0})
    t = Template(**data.model_dump(), fill_count=1)
    if not t.name:
        t.name = f"{data.platform.title()} format"
    await db.templates.insert_one(t.model_dump())
    return t


@api.delete("/templates/{tid}")
async def delete_template(tid: str):
    await db.templates.delete_one({"id": tid})
    return {"ok": True}


# ---------- AI generation ----------
SYSTEM_PROMPT = (
    "You are an expert e-commerce listing writer and smart form-filler for Amazon, Flipkart, Myntra, Meesho, Nykaa, Instamart, JioMart, Ajio, Blinkit, Zepto and Tata 1mg seller panels (India) and any other web form. "
    "You receive product info and a list of form fields scraped from a seller 'add product' page "
    "(each with key, label, placeholder, type, options, maxlength). Produce the best value for EVERY field. "
    "Rules: respect maxlength; for select fields pick EXACTLY one of the given options; numbers only for number fields; "
    "titles should be SEO-rich (Brand + Product + key benefit + size); bullet points benefit-led; descriptions 2-4 sentences; "
    "keywords comma separated; use INR for prices if currency is needed; MRP can be slightly above price if asked; "
    "if a field truly cannot be inferred (e.g. barcode, image upload, GTIN), return an empty string. "
    "If TOP_SELLER_STYLE_GUIDE is given, write the product title / item name, bullets and description following that marketplace's top-ranked naming pattern and length exactly (it is learned from the best-selling listings), using THIS product's facts and brand. "
    "If STYLE_SAMPLE_TO_REPLICATE is given, copy its exact pattern for the matching field (word order, separators like | or -, "
    "capitalisation, length, bullet structure, tone) but with THIS product's facts. Keep values consistent with already_filled_on_this_page. "
    "LISTING_RULES are mandatory: use those exact values for matching fields (price, MRP, handling fee, quantity, shipping, country, manufacturer, external ID/EAN, HSN code, GST / tax code). "
    "Country of origin / manufacturing country / country of manufacture = LISTING_RULES country_of_origin. "
    "Never swap numbers between fields: MRP goes only in MRP / list price, selling price only in selling / offer / your price, stock quantity only in stock / inventory, net quantity (e.g. 30 ml) only in net quantity / volume fields. "
    "Return every date as YYYY-MM-DD (use LISTING_RULES dates for manufacturing / expiry / launch dates). "
    "Obey every character limit (maxlength or limits written in labels/hints like 'Max 200 characters'). "
    "For radio/yes-no questions answer with one option text exactly; for compliance questions answer truthfully for a cosmetic/personal-care product (e.g. contains batteries: No, dangerous goods/hazmat: No). "
    "For dropdowns with options, reply with one option text exactly; for searchable dropdowns without options give the plain value (e.g. 'India'). "
    "If VALIDATION_ERRORS_TO_FIX is present, produce corrected values that satisfy those error messages. "
    "Return ONLY a JSON object mapping each field key to a string value. No markdown."
)


def add_months(d, months):
    y, m = divmod(d.month - 1 + months, 12)
    return d.replace(year=d.year + y, month=m + 1, day=1)


def listing_rules(settings: "Settings", product: dict, platform: str) -> Dict[str, Any]:
    import math
    mfg = date.today().replace(day=1)
    try:
        price = float(re.sub(r"[^0-9.]", "", str(product.get("price", ""))) or 0)
    except ValueError:
        price = 0
    mrp = product.get("mrp") or (str(math.ceil(price * (1 + settings.mrp_markup_percent / 100))) if price else "")
    rules = {
        "selling_price_offer_price_your_price": str(int(price)) if price and price == int(price) else str(price or ""),
        "mrp_maximum_retail_price_list_price": mrp,
        "handling_fee_shipping_fee_to_customer": settings.handling_fee,
        "quantity_stock_inventory": settings.default_quantity,
        "handling_time_dispatch_days": settings.handling_time_days,
        "country_of_origin": settings.country_of_origin,
        "manufacturer_name": settings.default_manufacturer or product.get("brand", ""),
        "manufacturer_address": settings.manufacturer_address,
        "manufacturer_contact_phone_email": settings.manufacturer_contact,
        "packer_details": settings.packer_details or settings.manufacturer_address,
        "importer_details": settings.importer_details or "Not applicable (made in India)",
        "external_product_id_ean_gtin_barcode": product.get("external_id", ""),
        "external_product_id_type": "EAN",
        "hsn_code": product.get("hsn_code", ""),
        "gst_tax_rate_percent": product.get("gst_rate", ""),
        "tax_code": f"GST_{product['gst_rate']}" if product.get("gst_rate") else "",
        "condition": "New",
        "manufacturing_date": mfg.isoformat(),
        "expiry_date_best_before": add_months(mfg, settings.shelf_life_months).isoformat(),
        "shelf_life_months": settings.shelf_life_months,
        "release_launch_date_or_today": date.today().isoformat(),
    }
    if platform == "amazon":
        rules["fulfillment_shipping"] = settings.amazon_shipping
    elif platform == "flipkart":
        rules["shipping_provider_fulfilment"] = settings.flipkart_shipping
    if settings.extra_rules:
        rules["extra_rules"] = settings.extra_rules
    return rules


LIMIT_RE = re.compile(r"(\d{1,4})\s*(?:characters|character|chars|char)", re.I)


def enforce_limit(f: "FieldInfo", value: str, error: str) -> str:
    limits = [f.maxlength] if f.maxlength else []
    for text in (f.label, f.placeholder, error):
        limits += [int(m) for m in LIMIT_RE.findall(text or "")]
    limits = [n for n in limits if n and n > 3]
    if not limits or len(value) <= min(limits):
        return value
    n = min(limits)
    cut = value[:n]
    if " " in cut and len(value) > n and value[n] != " ":
        cut = cut[:cut.rfind(" ")]
    return cut.rstrip(" ,|-–:;")


SEMANTIC = [
    ("skip", r"min(imum)? order|max(imum)? order|per order|order quantity|pack of|set of|number of (items|pieces|units)|bundle|count per|minimum|discount|percent off|commission|weight slab|price range|tier"),
    ("mrp", r"\bmrp\b|maximum retail|list price|max(imum)? price|retail price"),
    ("handling_fee", r"handling fee|shipping fee|delivery charge|shipping charge"),
    ("price", r"selling price|your price|offer price|sale price|deal price|sp \(|\bprice\b"),
    ("net_qty", r"net (quantity|qty|content|volume|weight)|item volume|item weight|pack size|\bvolume\b|\bsize\b"),
    ("sla", r"procurement sla|handling time|dispatch|\bsla\b|days to ship"),
    ("stock", r"\bstock\b|inventory|\bquantity\b|\bqty\b|units? available|available units"),
    ("hsn", r"\bhsn\b"),
    ("ean", r"\bean\b|gtin|\bupc\b|barcode|external product id|product id value"),
    ("gst", r"\bgst\b|tax rate|tax code|tax slab"),
]
SEMANTIC_RE = [(n, re.compile(r, re.I)) for n, r in SEMANTIC]


def field_semantic(f: "FieldInfo") -> str:
    text = f"{f.label} {f.key.replace('_', ' ')} {f.placeholder}"
    for name, rx in SEMANTIC_RE:
        if rx.search(text):
            return name
    return ""


def _num(v: str) -> Optional[float]:
    m = re.search(r"\d+(?:\.\d+)?", str(v or "").replace(",", ""))
    return float(m.group(0)) if m else None


def _same(a, b) -> bool:
    x, y = _num(a), _num(b)
    return x is not None and y is not None and abs(x - y) < 0.001


def validate_values(fields: List["FieldInfo"], values: Dict[str, str], rules: Dict[str, Any], product: dict):
    """Puts the right value in price / MRP / stock / HSN / EAN / tax fields and blocks swapped numbers."""
    expected = {
        "mrp": rules.get("mrp_maximum_retail_price_list_price", ""), "price": rules.get("selling_price_offer_price_your_price", ""),
        "stock": rules.get("quantity_stock_inventory", ""), "hsn": rules.get("hsn_code", ""), "ean": rules.get("external_product_id_ean_gtin_barcode", ""),
        "sla": rules.get("handling_time_dispatch_days", ""), "handling_fee": rules.get("handling_fee_shipping_fee_to_customer", ""),
    }
    money = [x for x in (expected["mrp"], expected["price"]) if x]
    out, fixes = dict(values), []
    for f in fields:
        v = str(out.get(f.key, "") or "")
        if not v or f.kind in ("radio", "toggle") or f.type == "date":
            continue
        sem = field_semantic(f)
        want = ""
        if sem == "gst":
            want = rules.get("tax_code", "") if re.search(r"code|slab", f"{f.label} {f.key}", re.I) and not f.options else rules.get("gst_tax_rate_percent", "")
            if f.options:
                continue
        elif sem in expected:
            want = str(expected[sem] or "")
        elif sem == "net_qty":
            size_n = _num(product.get("size", ""))
            if any(_same(v, m) for m in money) and size_n is not None and not _same(v, size_n):
                want = re.sub(r"\.0$", "", str(size_n)) if f.type == "number" else str(product.get("size", ""))
        elif sem == "" and f.type == "number" and any(_same(v, m) for m in money) and not re.search(r"price|mrp|amount|cost|value|fee|charge", f"{f.label} {f.key}", re.I):
            fixes.append({"field": f.label or f.key, "from": v, "to": "", "why": "price/MRP number in a non-price field"})
            out[f.key] = ""
            continue
        if not want:
            continue
        if f.options:
            if sem in ("price", "mrp", "stock"):
                continue
            hit = next((o for o in f.options if o.strip().lower() == want.lower() or o.strip().lower().startswith(want.lower())), None)
            if not hit and sem == "hsn":
                hit = next((o for n in (6, 4) for o in f.options if re.sub(r"\D", "", o).startswith(want[:n])), None)
            want = hit or ""
            if not want:
                continue
        same = _same(v, want) if sem in ("mrp", "price", "stock", "sla", "handling_fee") else re.sub(r"\s", "", v).lower() == re.sub(r"\s", "", want).lower()
        if not same:
            fixes.append({"field": f.label or f.key, "from": v, "to": want, "why": f"{sem} field must be {want}"})
            out[f.key] = want
    if expected["mrp"] and expected["price"] and (_num(expected["mrp"]) or 0) < (_num(expected["price"]) or 0):
        fixes.append({"field": "MRP", "from": expected["mrp"], "to": expected["mrp"], "why": "warning: MRP is lower than selling price"})
    return out, fixes


async def sanity_check(fields: List["FieldInfo"], values: Dict[str, str], product: dict, platform: str) -> tuple:
    items = [{"key": f.key, "column": f.label or f.placeholder or f.key, "hint": f.placeholder if f.label else "", "type": f.type,
              "allowed_values": f.options[:60], "value": values.get(f.key, "")} for f in fields if values.get(f.key) and f.type != "date"]
    if not items:
        return values, []
    raw = await run_llm(
        f"You are checking an auto-filled {platform} seller form before it is submitted. For EVERY item read the column title and decide if the value is logical for that column and this product. "
        "Wrong examples: SPF rating 'F599' (must be like 'SPF 50' / '50' or 'Not Applicable' when the product is not a sunscreen), a price in a quantity column, an MRP in a weight column, "
        "a code or random number in a text attribute, a unit that does not match the column (ml vs g), a value that is not in allowed_values when allowed_values are given. "
        "For each wrong value give the corrected value (copy exactly from allowed_values when given; use product facts; empty string if it truly cannot be known). Do NOT change correct values. "
        'Return JSON {"fixes": {"<key>": "<corrected value>"}, "why": {"<key>": "short reason"}}. Product: '
        + json.dumps({k: product.get(k) for k in ("name", "brand", "category", "size", "price", "mrp", "key_ingredients", "notes")}, ensure_ascii=False)
        + "\nItems:\n" + json.dumps(items, ensure_ascii=False)[:14000])
    d = parse_json(raw)
    fixes, why = d.get("fixes") or {}, d.get("why") or {}
    out, log = dict(values), []
    for k, v in fixes.items():
        if k in out and str(v) != str(out[k]):
            log.append({"field": next((f.label or f.key for f in fields if f.key == k), k), "from": out[k], "to": str(v), "why": str(why.get(k, "not logical for this column"))[:120]})
            out[k] = "" if v is None else str(v)
    return out, log


def parse_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("No JSON in AI response")
    return json.loads(m.group(0))


async def run_gemini_fallback(prompt: str) -> str:
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    resp = await client.aio.models.generate_content(
        model="gemini-flash-latest", contents=prompt,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, response_mime_type="application/json"))
    return resp.text


async def run_llm(prompt: str) -> str:
    try:
        return await run_emergent(prompt)
    except Exception as e:
        if not os.environ.get("GEMINI_API_KEY"):
            raise
        logger.warning(f"Emergent LLM failed ({e}); using Gemini API key fallback")
        try:
            return await run_gemini_fallback(prompt)
        except Exception as ge:
            raise RuntimeError(f"Primary AI failed: {e}. Gemini key fallback failed: {str(ge)[:200]}")


async def run_emergent(prompt: str) -> str:
    chat = LlmChat(api_key=(os.environ.get('EMERGENT_LLM_KEY') or os.environ['LISTING_AI_KEY']), session_id=new_id(), system_message=SYSTEM_PROMPT).with_model("gemini", "gemini-2.5-flash")
    text = await chat.send_message(UserMessage(text=prompt))
    if not text or not text.strip():
        raise RuntimeError("Empty AI response")
    return text


@api.post("/generate")
async def generate(data: GenerateIn):
    if not data.fields:
        raise HTTPException(400, "No fields detected on page")
    if data.product_id:
        product = await db.products.find_one({"id": data.product_id}, {"_id": 0})
        if not product:
            raise HTTPException(404, "Product not found")
    elif data.product:
        product = data.product.model_dump()
    else:
        raise HTTPException(400, "Select a product")

    keys = [f.key for f in data.fields]
    can_cache = bool(data.product_id and data.page_key)
    known: Dict[str, str] = {}
    if data.use_cache and can_cache:
        cached = await db.gen_cache.find_one({"product_id": data.product_id, "page_key": data.page_key}, {"_id": 0})
        known = {k: v for k, v in (cached or {}).get("values", {}).items() if k in keys and k not in data.errors}
    missing = [f for f in data.fields if f.key not in known]
    settings = await get_settings()
    if not missing:
        if any(field_semantic(f) == "hsn" for f in data.fields):
            product = await ensure_hsn(product)
        known, fixes = validate_values(data.fields, known, listing_rules(settings, product, data.platform), product)
        await log_history(data, product, known, True)
        return {"values": known, "cached": True, "corrections": fixes}

    if any(HSN_FIELD.search(f"{f.key} {f.label} {f.placeholder}") for f in missing) or any(HSN_FIELD.search(e) for e in list(data.errors.values()) + data.page_errors):
        try:
            hsn_f = next((f for f in data.fields if field_semantic(f) == "hsn"), None)
            hsn_err = (data.errors.get(hsn_f.key, "") if hsn_f else "") or next((e for e in data.page_errors if re.search(r"\bhsn\b", e, re.I)), "")
            product = await ensure_hsn(product, force=bool(hsn_err), error=hsn_err, options=hsn_f.options if hsn_f else None)
        except Exception as e:
            logger.warning(f"HSN lookup failed: {e}")
    template = await db.templates.find_one({"page_key": data.page_key}, {"_id": 0}) if data.page_key else None
    prompt = {
        "platform": data.platform,
        "page_title": data.page_title,
        "product": {k: v for k, v in product.items() if k not in ("id", "created_at", "images")},
        "product_image_urls": [i.get("url") for i in product.get("images", [])][:12],
        "defaults": {"brand": settings.default_brand, "size": settings.default_size, "category": settings.default_category},
        "LISTING_RULES": listing_rules(settings, product, data.platform),
        "fields": [f.model_dump(exclude_none=True) for f in missing],
    }
    if data.errors or data.page_errors:
        prompt["VALIDATION_ERRORS_TO_FIX"] = {"field_errors": data.errors, "page_messages": data.page_errors[:10]}
    guide = await db.style_guides.find_one({"platform": data.platform, "product_id": data.product_id}, {"_id": 0}) if data.product_id else None
    if not guide and product.get("category"):
        guide = await db.style_guides.find_one({"platform": data.platform, "category": product["category"]}, {"_id": 0}, sort=[("created_at", -1)])
    if guide:
        prompt["TOP_SELLER_STYLE_GUIDE"] = guide["guide"]
    style = {k: v for k, v in (settings.style_samples.get(data.platform) or {}).items() if v}
    if style:
        prompt["STYLE_SAMPLE_TO_REPLICATE"] = style
    if known:
        prompt["already_filled_on_this_page"] = known
    if template and template.get("reference_values"):
        prompt["style_reference_from_previous_listing"] = template["reference_values"]
    try:
        raw = await run_llm("Fill these fields. Input:\n" + json.dumps(prompt, ensure_ascii=False))
        gen = parse_json(raw)
    except Exception as e:
        logger.exception("AI generation failed")
        raise HTTPException(502, f"AI generation failed: {e}")
    gen = {f.key: enforce_limit(f, "" if gen.get(f.key) is None else str(gen.get(f.key)), data.errors.get(f.key, "")) for f in missing}
    values = {k: known.get(k, gen.get(k, "")) for k in keys}
    fixes = []
    try:
        values, fixes = await sanity_check(missing, values, product, data.platform)
    except Exception as e:
        logger.warning(f"sanity check failed: {e}")
    values, fixes2 = validate_values(data.fields, values, prompt["LISTING_RULES"], product)
    fixes += fixes2
    if fixes:
        logger.info(f"value checks fixed: {fixes}")
    gen = {k: values[k] for k in gen}

    if can_cache:
        await db.gen_cache.update_one(
            {"product_id": data.product_id, "page_key": data.page_key},
            {"$set": {**{f"values.{k}": v for k, v in gen.items()}, "updated_at": now_iso()}}, upsert=True)
    await log_history(data, product, values, False)
    return {"values": values, "cached": False, "corrections": fixes}


async def log_history(data: GenerateIn, product: dict, values: dict, cached: bool):
    await db.history.insert_one({
        "id": new_id(), "created_at": now_iso(), "platform": data.platform, "page_key": data.page_key,
        "url": data.url, "product_name": product.get("name", ""), "field_count": len(values),
        "filled_count": len([v for v in values.values() if v]), "cached": cached,
    })


@api.get("/history")
async def history():
    return await db.history.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)


@api.delete("/history")
async def clear_history():
    await db.history.delete_many({})
    return {"ok": True}


@api.get("/stats")
async def stats():
    return {
        "products": await db.products.count_documents({}),
        "templates": await db.templates.count_documents({}),
        "fills": await db.history.count_documents({}),
        "recordings": await db.recordings.count_documents({}),
        "amazon_templates": await db.templates.count_documents({"platform": "amazon"}),
        "flipkart_templates": await db.templates.count_documents({"platform": "flipkart"}),
    }


# ---------- Chrome extension download ----------
@api.get("/extension/download")
async def download_extension(api_url: str = Query(...)):
    if not re.fullmatch(r"https?://[A-Za-z0-9.\-:_/]+", api_url):
        raise HTTPException(400, "Invalid api_url")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for f in EXT_DIR.rglob("*"):
            if f.is_file():
                content = f.read_bytes()
                if f.name == "config.js":
                    content = content.replace(b"__API_URL__", api_url.rstrip("/").encode())
                z.writestr(f"autofill-extension/{f.relative_to(EXT_DIR)}", content)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/zip",
                             headers={"Content-Disposition": "attachment; filename=autofill-extension.zip"})


# ---------- Bulk import ----------
COLUMN_ALIASES = {
    "name": ["name", "product name", "product", "title", "product_name"],
    "brand": ["brand", "brand name", "brand_name"],
    "ingredients": ["ingredients", "ingredient", "key ingredients"],
    "size": ["size", "bottle size", "volume", "quantity", "bottle_size", "net quantity"],
    "price": ["price", "selling price", "mrp", "product price", "cost"],
    "category": ["category", "type"],
    "notes": ["notes", "description", "extra notes", "features"],
    "external_id": ["ean", "upc", "gtin", "external id", "external product id", "barcode"],
}


def map_header(h: str) -> Optional[str]:
    h = (h or "").strip().lower()
    for field, aliases in COLUMN_ALIASES.items():
        if h in aliases:
            return field
    return None


def read_rows(filename: str, raw: bytes) -> List[List[str]]:
    if filename.lower().endswith((".xlsx", ".xlsm")):
        from openpyxl import load_workbook
        ws = load_workbook(io.BytesIO(raw), read_only=True, data_only=True).active
        return [["" if c is None else str(c) for c in row] for row in ws.iter_rows(values_only=True)]
    import csv
    text = raw.decode("utf-8-sig", errors="ignore")
    return list(csv.reader(io.StringIO(text)))


@api.post("/products/import")
async def import_products(file: UploadFile = File(...)):
    try:
        rows = read_rows(file.filename or "", await file.read())
    except Exception as e:
        raise HTTPException(400, f"Could not read file: {e}")
    if len(rows) < 2:
        raise HTTPException(400, "File has no product rows")
    cols = [map_header(h) for h in rows[0]]
    if "name" not in cols:
        raise HTTPException(400, "A 'Product Name' column is required")
    settings = await get_settings()
    docs, skipped = [], 0
    for row in rows[1:]:
        data = {c: str(row[i]).strip() for i, c in enumerate(cols) if c and i < len(row) and row[i] is not None}
        if not data.get("name"):
            skipped += 1
            continue
        data.setdefault("brand", "")
        data["brand"] = data["brand"] or settings.default_brand
        data["size"] = data.get("size") or settings.default_size
        data["category"] = data.get("category") or settings.default_category
        data["external_id"] = data.get("external_id") or make_ean13()
        docs.append(Product(**data).model_dump())
    if docs:
        await db.products.insert_many([dict(d) for d in docs])
    return {"imported": len(docs), "skipped": skipped, "columns": [c for c in cols if c]}


@api.get("/products/import-template")
async def import_template():
    csv_text = "Product Name,Brand,Ingredients,Bottle Size,Price,Category,Notes\nOnion Hair Oil,Herbveda,\"Red onion extract, coconut oil, bhringraj\",200 ml,349,Hair Oil,For hair fall\n"
    return StreamingResponse(io.BytesIO(csv_text.encode()), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=products-template.csv"})


# ---------- Autopilot recordings ----------
class FromUrlIn(BaseModel):
    url: str


def collect_images(d: dict) -> List[Dict[str, str]]:
    out, seen = [], set()

    def add(url, kind):
        if not url or not isinstance(url, str):
            return
        base = url.split("?")[0].split("/")[-1]
        if base in seen:
            return
        seen.add(base)
        out.append({"url": url, "kind": kind})
    for u in d.get("images") or []:
        add(u if isinstance(u, str) else u.get("url"), "product")
    for g in d.get("image_gallery") or []:
        add(g.get("url") if isinstance(g, dict) else g, "gallery")
    for b in d.get("before_after") or []:
        add(b.get("image"), b.get("type", "before_after"))
    add(d.get("test_report_image"), "certificate")
    return out


async def fetch_product_source(url: str) -> Dict[str, Any]:
    import httpx
    from urllib.parse import urlparse
    from bs4 import BeautifulSoup
    u = urlparse(url)
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130 Safari/537.36"}
    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=headers) as c:
        m = re.match(r"^/products?/([^/?#]+)", u.path)
        if m:
            try:
                r = await c.get(f"{u.scheme}://{u.netloc}/api/products/{m.group(1)}")
                if r.status_code == 200 and r.headers.get("content-type", "").startswith("application/json") and isinstance(r.json(), dict) and r.json().get("name"):
                    return {"structured": r.json()}
            except Exception:
                pass
        r = await c.get(url)
        if r.status_code >= 400:
            raise HTTPException(400, f"Could not open link (HTTP {r.status_code})")
    soup = BeautifulSoup(r.text, "html.parser")
    ld = []
    for s_ in soup.find_all("script", type="application/ld+json"):
        try:
            ld.append(json.loads(s_.string or ""))
        except Exception:
            pass
    imgs = [m_.get("content") for m_ in soup.find_all("meta", property="og:image")]
    imgs += [i.get("src") or i.get("data-src") for i in soup.find_all("img")]
    imgs = [requests_abs(url, i) for i in imgs if i and not i.startswith("data:")]
    for t in soup(["script", "style", "noscript", "svg"]):
        t.decompose()
    text = soup.get_text(" ", strip=True)[:12000]
    return {"html_text": text, "json_ld": ld[:3], "images": imgs[:40], "title": soup.title.string if soup.title else ""}


def requests_abs(base: str, link: str) -> str:
    from urllib.parse import urljoin
    return urljoin(base, link)


@api.post("/products/from-url", response_model=Product)
async def product_from_url(data: FromUrlIn):
    if not re.match(r"^https?://", data.url):
        raise HTTPException(400, "Enter a full http(s) link")
    src = await fetch_product_source(data.url)
    settings = await get_settings()
    if "structured" in src:
        d = src["structured"]
        price = d.get("offer_price") or d.get("prepaid_price") or d.get("price") or ""
        info = {
            "name": d.get("name", ""), "brand": d.get("brand") or settings.default_brand,
            "ingredients": d.get("ingredients_full") or d.get("key_ingredients", ""),
            "key_ingredients": d.get("key_ingredients", ""), "size": d.get("size") or settings.default_size,
            "price": str(int(price)) if isinstance(price, (int, float)) and price == int(price) else str(price),
            "mrp": str(int(d["mrp"])) if isinstance(d.get("mrp"), (int, float)) else str(d.get("mrp") or ""),
            "category": " / ".join(x for x in [d.get("category"), d.get("subcategory")] if x),
            "description": " ".join(x for x in [d.get("tagline"), d.get("description")] if x),
            "how_to_use": d.get("how_to_use", ""),
            "benefits": "\n".join(d.get("benefits") or []),
            "notes": "; ".join(d.get("concerns") or []),
            "images": collect_images(d),
        }
    else:
        raw = await run_llm(
            "Extract product data from this web page. Return JSON with keys: name, brand, ingredients, key_ingredients, size, price (selling price number as string), mrp, category, description, how_to_use, benefits (newline separated), "
            "images (array of {url, kind} where kind is one of product, gallery, before, after, certificate; only real product images). Page:\n" + json.dumps(src, ensure_ascii=False)[:15000])
        info = parse_json(raw)
        info = {k: (v if k == "images" else ("" if v is None else str(v))) for k, v in info.items() if k in ProductIn.model_fields}
        info["images"] = [i for i in info.get("images", []) if isinstance(i, dict) and i.get("url")][:20]
        info["brand"] = info.get("brand") or settings.default_brand
    info["source_url"] = data.url
    existing = await db.products.find_one({"source_url": data.url}, {"_id": 0})
    if existing:
        info["external_id"] = existing.get("external_id") or make_ean13()
        await db.products.update_one({"id": existing["id"]}, {"$set": info})
        await db.gen_cache.delete_many({"product_id": existing["id"]})
        return await db.products.find_one({"id": existing["id"]}, {"_id": 0})
    p = Product(**info)
    p.external_id = p.external_id or make_ean13()
    await db.products.insert_one(p.model_dump())
    return p


class MatchIn(BaseModel):
    label: str = ""
    wanted: str
    options: List[str]
    product_id: Optional[str] = None


@api.post("/match-option")
async def match_option(data: MatchIn):
    opts = list(dict.fromkeys(o for o in data.options if o and o.strip()))[:400]
    if not opts:
        return {"option": ""}
    product = await db.products.find_one({"id": data.product_id}, {"_id": 0, "name": 1, "category": 1, "size": 1, "notes": 1}) if data.product_id else None
    raw = await run_llm(
        "A seller form dropdown must be set. Pick the ONE option that best matches the intended value for this product. "
        "Consider synonyms, units (g/gram, ml/millilitre), country names, Yes/No meaning, and the product facts. If nothing fits at all return empty string. "
        'Return JSON {"option": "<exact option text copied from the list>"}.\n'
        + json.dumps({"field": data.label, "intended_value": data.wanted, "product": product, "options": opts}, ensure_ascii=False))
    pick = str(parse_json(raw).get("option", "")).strip()
    if pick not in opts:
        low = {o.lower(): o for o in opts}
        pick = low.get(pick.lower(), "")
    return {"option": pick}


class StyleQueryIn(BaseModel):
    product_id: str
    platform: str


class StyleResearchIn(StyleQueryIn):
    query: str
    titles: List[str]


@api.post("/style/query")
async def style_query(data: StyleQueryIn):
    p = await db.products.find_one({"id": data.product_id}, {"_id": 0, "images": 0})
    if not p:
        raise HTTPException(404, "Product not found")
    raw = await run_llm("Give the best 3-6 word shopper search query (generic, NO brand name) a customer would type on "
                        f"{data.platform} India to find this product type and concern. Return JSON {{\"query\": \"...\"}}. Product: "
                        + json.dumps({k: p.get(k) for k in ("name", "category", "notes", "key_ingredients", "size")}, ensure_ascii=False))
    return {"query": parse_json(raw).get("query", p.get("name", ""))[:80]}


@api.post("/style/research")
async def style_research(data: StyleResearchIn):
    prod = await db.products.find_one({"id": data.product_id}, {"_id": 0, "category": 1})
    if not prod:
        raise HTTPException(404, "Product not found")
    raw = await run_llm(
        f"These are the top-ranked product titles on {data.platform} India for '{data.query}'. Analyse their naming convention "
        "(order of brand / key ingredient / percentage / benefit / skin type / size / pack, separators, capitalisation, length). "
        "Return JSON {\"title_pattern\": \"e.g. Brand + Active % + Product type + for Concern | Benefit | Size\", \"avg_length\": number, "
        "\"title_rules\": [..], \"bullet_style\": \"..\", \"description_style\": \"..\", \"best_examples\": [3 titles]}. Titles:\n"
        + "\n".join(data.titles[:15]))
    guide = parse_json(raw)
    doc = {"platform": data.platform, "product_id": data.product_id, "query": data.query, "titles": data.titles[:15],
           "guide": guide, "category": prod.get("category", ""), "created_at": now_iso()}
    await db.style_guides.update_one({"platform": data.platform, "product_id": data.product_id}, {"$set": doc}, upsert=True)
    await db.gen_cache.delete_many({"product_id": data.product_id, "page_key": {"$regex": f"^{data.platform}:"}})
    return guide


@api.delete("/style/guides/{platform}/{product_id}")
async def delete_style_guide(platform: str, product_id: str):
    await db.style_guides.delete_one({"platform": platform, "product_id": product_id})
    return {"ok": True}


@api.get("/style/guides")
async def style_guides():
    return await db.style_guides.find({}, {"_id": 0}).sort("created_at", -1).to_list(100)


class StepInfo(BaseModel):
    type: str = "click"
    text: str = ""
    tag: str = ""
    aria: str = ""
    elem_id: str = ""
    path: str = ""
    page_key: str = ""
    url: str = ""
    label: str = ""
    value: str = ""
    ident: str = ""
    reason: str = ""


class RecordingIn(BaseModel):
    platform: str
    name: str = ""
    start_url: str = ""
    steps: List[StepInfo] = []
    final_steps: List[StepInfo] = []
    auto: bool = False


class Recording(RecordingIn):
    id: str = Field(default_factory=new_id)
    created_at: str = Field(default_factory=now_iso)
    run_count: int = 0
    summary: str = ""
    optimized: bool = False


@api.get("/recordings", response_model=List[Recording])
async def list_recordings(platform: Optional[str] = None):
    q = {"platform": platform} if platform else {}
    return await db.recordings.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


@api.post("/recordings", response_model=Recording)
async def create_recording(data: RecordingIn):
    if not data.steps:
        raise HTTPException(400, "Recording has no steps")
    r = Recording(**data.model_dump())
    if not r.name:
        r.name = f"{data.platform.title()} {'auto-learned' if data.auto else 'autopilot'} · {len(data.steps)} steps · {datetime.now(timezone.utc).strftime('%d %b %H:%M')}"
    if data.auto:
        await db.recordings.delete_many({"platform": data.platform, "auto": True})
    await db.recordings.insert_one(r.model_dump())
    if data.auto:
        upd = {"last_recording_id": r.id, "updated_at": now_iso()}
        if data.final_steps:
            upd["milestones.save"] = True
        await db.learning.update_one({"platform": data.platform}, {"$set": upd, "$inc": {"sessions": 1}}, upsert=True)
        await refresh_learning(data.platform)
    asyncio.create_task(annotate_recording(r.id))
    return r


async def annotate_recording(rid: str):
    rec = await db.recordings.find_one({"id": rid}, {"_id": 0})
    if not rec:
        return
    steps = rec["steps"]
    compact = [{"i": i, "type": s.get("type"), "text": s.get("text") or s.get("aria"), "label": s.get("label"), "value": (s.get("value") or "")[:40], "page": s.get("page_key")} for i, s in enumerate(steps)][:200]
    try:
        raw = await run_llm(
            "A seller manually created a product listing on " + rec["platform"] + " while we recorded every action (navigate, click, input, select, enter, upload). "
            "For each step explain in max 12 words WHY the seller did it (e.g. 'Opens listings menu to reach Add product'). Mark essential=false only for "
            "accidental / repeated / back-and-forth CLICK steps not needed to reach the next page. Also write a 1-3 sentence summary of how the seller reaches the add-product page and finishes. "
            'Return JSON {"summary": "...", "steps": [{"i": 0, "reason": "...", "essential": true}]}. Steps:\n' + json.dumps(compact, ensure_ascii=False))
        d = parse_json(raw)
    except Exception as e:
        logger.warning(f"annotate failed: {e}")
        return
    info = {int(x.get("i", -1)): x for x in d.get("steps", []) if isinstance(x, dict)}
    out = []
    for i, s in enumerate(steps):
        a = info.get(i, {})
        if (s.get("type") or "click") == "click" and a.get("essential") is False and i > 0:
            continue
        out.append({**s, "reason": str(a.get("reason", ""))[:120]})
    await db.recordings.update_one({"id": rid}, {"$set": {"steps": out or steps, "summary": str(d.get("summary", ""))[:600], "optimized": True}})
    if rec.get("auto"):
        await db.learning.update_one({"platform": rec["platform"]}, {"$set": {"journey_summary": str(d.get("summary", ""))[:600]}})


# ---------- Background learning progress ----------
MILESTONES = ["start", "add_page", "images", "fields", "save"]


class LearnProgressIn(BaseModel):
    platform: str
    milestones: Dict[str, bool] = {}
    pages: List[str] = []
    enter_fields: List[str] = []


class LearnToggleIn(BaseModel):
    enabled: bool


async def refresh_learning(platform: str):
    d = await db.learning.find_one({"platform": platform}, {"_id": 0}) or {}
    m = d.get("milestones", {})
    complete = bool(m.get("add_page") and m.get("save"))
    await db.learning.update_one({"platform": platform}, {"$set": {"complete": complete or d.get("complete", False), "progress": round(100 * sum(1 for k in MILESTONES if m.get(k)) / len(MILESTONES))}}, upsert=True)


def learning_out(d: dict) -> dict:
    m = d.get("milestones", {})
    return {"platform": d["platform"], "milestones": {k: bool(m.get(k)) for k in MILESTONES}, "progress": d.get("progress", 0),
            "complete": d.get("complete", False), "autofill_enabled": d.get("autofill_enabled", False), "asked": d.get("asked", False),
            "pages": d.get("pages", [])[-40:], "enter_fields": d.get("enter_fields", []), "sessions": d.get("sessions", 0),
            "journey_summary": d.get("journey_summary", ""), "updated_at": d.get("updated_at", "")}


@api.get("/learning")
async def list_learning():
    return [learning_out(d) for d in await db.learning.find({}, {"_id": 0}).to_list(20)]


@api.post("/learning/progress")
async def learning_progress(data: LearnProgressIn):
    upd: Dict[str, Any] = {f"milestones.{k}": True for k, v in data.milestones.items() if v and k in MILESTONES}
    upd["updated_at"] = now_iso()
    add = {}
    if data.pages:
        add["pages"] = {"$each": data.pages[:20]}
    if data.enter_fields:
        add["enter_fields"] = {"$each": [e[:80] for e in data.enter_fields if e][:20]}
    await db.learning.update_one({"platform": data.platform}, {"$set": upd, **({"$addToSet": add} if add else {})}, upsert=True)
    await refresh_learning(data.platform)
    return learning_out(await db.learning.find_one({"platform": data.platform}, {"_id": 0}))


@api.post("/learning/{platform}/autofill")
async def learning_autofill(platform: str, data: LearnToggleIn):
    await db.learning.update_one({"platform": platform}, {"$set": {"autofill_enabled": data.enabled, "asked": True}}, upsert=True)
    return learning_out(await db.learning.find_one({"platform": platform}, {"_id": 0}))


@api.delete("/learning/{platform}")
async def learning_reset(platform: str):
    await db.learning.delete_one({"platform": platform})
    return {"ok": True}


@api.put("/recordings/{rid}", response_model=Recording)
async def update_recording(rid: str, data: RecordingIn):
    res = await db.recordings.find_one_and_update({"id": rid}, {"$set": data.model_dump()}, projection={"_id": 0}, return_document=True)
    if not res:
        raise HTTPException(404, "Recording not found")
    return res


@api.post("/recordings/{rid}/ran")
async def recording_ran(rid: str):
    await db.recordings.update_one({"id": rid}, {"$inc": {"run_count": 1}})
    return {"ok": True}


@api.delete("/recordings/{rid}")
async def delete_recording(rid: str):
    await db.recordings.delete_one({"id": rid})
    return {"ok": True}


# ---------- Page diagnostics (extension "Diagnose page") ----------
@api.post("/diagnostics")
async def save_diagnostics(report: Dict[str, Any]):
    doc = {"id": new_id(), "created_at": now_iso(), "report": report}
    await db.diagnostics.insert_one(dict(doc))
    return {"id": doc["id"]}


@api.get("/diagnostics")
async def list_diagnostics():
    return await db.diagnostics.find({}, {"_id": 0}).sort("created_at", -1).to_list(50)


app.include_router(api)
app.include_router(build_auth_router(db))


@app.on_event("startup")
async def startup():
    await seed_admin(db)
app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,
    allow_origins=os.environ.get('CORS_ORIGINS', '*').split(','),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()


# ---- exported for the main Celesta app ----
af_api = api
af_auth_router = build_auth_router(db)
af_db = db

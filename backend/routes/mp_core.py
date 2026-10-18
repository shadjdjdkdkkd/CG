"""Marketplace core: module config, categories, service catalogue,
doctor/partner applications + admin review, provider auth, public discovery."""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel

from services import mp_common as mp

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mp", tags=["marketplace-core"])

Db = None


def setup(db, verify_admin_token, razorpay_client=None):
    global Db
    Db = db
    mp.setup(db, verify_admin_token, razorpay_client)


CAT_IMAGES = {
    "Acne & Pimples": "https://res.cloudinary.com/dcvuqcqjn/image/upload/f_auto,q_100/v1791584204/celesta-glow/live-import/e79771ce3094ac47.png",
    "Pigmentation": "https://res.cloudinary.com/dcvuqcqjn/image/upload/f_auto,q_100/v1791584202/celesta-glow/live-import/d7ac756b1b8d2d47.jpg",
    "Anti-Aging": "https://res.cloudinary.com/dcvuqcqjn/image/upload/f_auto,q_100/v1791584205/celesta-glow/live-import/4e7c13e62ce815d1.png",
    "Hair & Scalp": "https://res.cloudinary.com/dcvuqcqjn/image/upload/f_auto,q_100/v1791584206/celesta-glow/live-import/f357226754bd94ff.jpg",
    "Sensitive Skin": "https://res.cloudinary.com/dcvuqcqjn/image/upload/f_auto,q_100/v1791584203/celesta-glow/live-import/98dc57dd4992a552.jpg",
    "Skin Concerns": "https://res.cloudinary.com/dcvuqcqjn/image/upload/f_auto,q_100/v1791584351/celesta-glow/live-import/ef09d168d290e156.jpg",
    "General Dermatology": "https://res.cloudinary.com/dcvuqcqjn/image/upload/f_auto,q_100/v1791584242/celesta-glow/live-import/aee18ad731c92205.jpg",
    "View All": "https://res.cloudinary.com/dcvuqcqjn/image/upload/f_auto,q_100/v1791584210/celesta-glow/live-import/d43fd484b8902506.jpg",
    "Facials": "https://res.cloudinary.com/dcvuqcqjn/image/upload/f_auto,q_100/v1791584241/celesta-glow/live-import/afc492aef3a0a01f.jpg",
    "Hair Colouring": "https://res.cloudinary.com/dcvuqcqjn/image/upload/f_auto,q_100/v1791584209/celesta-glow/live-import/4f79b3bec7799cb3.jpg",
    "Hair Spa": "https://res.cloudinary.com/dcvuqcqjn/image/upload/f_auto,q_100/v1791584265/celesta-glow/live-import/e3c8947ff2032de8.jpg",
    "Hair & Scalp Care": "https://res.cloudinary.com/dcvuqcqjn/image/upload/f_auto,q_100/v1791584251/celesta-glow/live-import/d0fa1cf0ac42dac1.jpg",
    "Skin Cleansing": "https://res.cloudinary.com/dcvuqcqjn/image/upload/f_auto,q_100/v1791584286/celesta-glow/live-import/b031fd68d734d659.png",
    "Beauty & Grooming": "https://res.cloudinary.com/dcvuqcqjn/image/upload/f_auto,q_100/v1791584250/celesta-glow/live-import/87c04c5f3aa7abfd.jpg",
    "Wellness Treatments": "https://res.cloudinary.com/dcvuqcqjn/image/upload/f_auto,q_100/v1791584251/celesta-glow/live-import/6a6512ea684c1068.jpg",
    "View All Services": "https://res.cloudinary.com/dcvuqcqjn/image/upload/f_auto,q_100/v1791584354/celesta-glow/live-import/b0f9b4140fb8f849.jpg",
}


async def seed_defaults(db):
    """Idempotent seed of module categories + sample services (admin-editable)."""
    await mp.migrate_pricing_v2()
    if await db.mp_categories.count_documents({}) == 0:
        doctor_cats = ["Acne & Pimples", "Pigmentation", "Anti-Aging", "Hair & Scalp",
                       "Sensitive Skin", "Skin Concerns", "General Dermatology", "View All"]
        service_cats = ["Facials", "Hair Colouring", "Hair Spa", "Hair & Scalp Care",
                        "Skin Cleansing", "Beauty & Grooming", "Wellness Treatments", "View All Services"]
        docs = []
        for i, t in enumerate(doctor_cats):
            docs.append({"cat_id": mp.uid("cat"), "module": "doctor", "title": t, "image": "",
                         "order": i, "active": True, "created_at": mp.now()})
        for i, t in enumerate(service_cats):
            docs.append({"cat_id": mp.uid("cat"), "module": "service", "title": t, "image": "",
                         "order": i, "active": True, "created_at": mp.now()})
        await db.mp_categories.insert_many(docs)
        logger.info("[mp] seeded module categories")
    if await db.mp_services.count_documents({}) == 0:
        svc_cats = await db.mp_categories.find({"module": "service"}, {"_id": 0}).to_list(50)
        cat_map = {c["title"]: c["cat_id"] for c in svc_cats}
        img = "https://res.cloudinary.com/dcvuqcqjn/image/upload/f_auto,q_100/v1791584205/celesta-glow/live-import/4e7c13e62ce815d1.png"
        samples = [
            ("Facials", "Signature Glow Facial", "A deep-cleansing facial tailored to your skin type.", 60, 1499),
            ("Hair Spa", "Repair Hair Spa Ritual", "Nourishing hair spa with scalp massage and steam.", 75, 1199),
            ("Hair Colouring", "Global Hair Colour", "Ammonia-free global colour with post-care serum.", 120, 2499),
            ("Skin Cleansing", "Deep Cleansing & De-tan", "Gentle de-tan cleanse for face and neck.", 45, 899),
        ]
        for cat, name, desc, dur, price in samples:
            await db.mp_services.insert_one({
                "service_id": mp.uid("svc"), "name": name, "category_id": cat_map.get(cat, ""),
                "category_title": cat, "short_desc": desc, "full_desc": desc,
                "includes": ["Professional products", "Sanitised equipment"], "excludes": [],
                "duration_min": dur, "mode": "home", "price": price,
                "price_range": {"min": int(price * 0.8), "max": int(price * 1.3)},
                "commission_pct": 20.0, "tax_pct": 18.0, "offer_eligible": True,
                "cancellation_policy": "Free cancellation up to 4 hours before the slot.",
                "qualifications": [], "equipment": "", "prep": "", "aftercare": "",
                "warnings": "", "patch_test": cat == "Hair Colouring", "materials_included": True,
                "locations": [], "age_restriction": "", "images": [img], "thumbnail": img,
                "status": "active", "created_at": mp.now(), "updated_at": mp.now(),
            })
        logger.info("[mp] seeded sample services")
    async for c in db.mp_categories.find({"$or": [{"image": ""}, {"image": {"$exists": False}}]}):
        url = CAT_IMAGES.get(c.get("title", ""))
        if url:
            await db.mp_categories.update_one({"_id": c["_id"]}, {"$set": {"image": url}})
    if await db.mp_doctors.count_documents({"personal.email": {"$regex": "sample.celestaglow.com"}}) == 0:
        samples = [
            ("dr.meera@sample.celestaglow.com", "Meera Krishnan", "MBBS, MD (Dermatology)", "Anti-Aging", 12, 799, 12.9716, 77.5946),
            ("dr.arjun@sample.celestaglow.com", "Arjun Rao", "MBBS, DVD", "Acne & Hair", 9, 699, 12.9352, 77.6245),
            ("dr.sana@sample.celestaglow.com", "Sana Sheikh", "MBBS, MD (Dermatology)", "Sensitive Skin", 7, 899, 12.9698, 77.7500),
        ]
        for email, name, qual, spec, yrs, fee, slat, slng in samples:
            did = mp.uid("doc")
            await db.mp_doctors.insert_one({
                "doctor_id": did, "application_status": "approved", "active": True,
                "personal": {"name": name, "mobile": "9800000000", "email": email,
                             "address": "", "city": "Bengaluru", "state": "KA", "pincode": "560001",
                             "lat": slat, "lng": slng},
                "professional": {"qualification": qual, "institution": "Sample Medical College",
                                 "graduation_year": "2012", "postgrad": "", "specialisation": spec,
                                 "experience_years": yrs, "bio": f"{yrs}+ years of clinical dermatology practice.",
                                 "registration_number": f"SAMPLE-{did[-5:]}", "issuing_authority": "KMC"},
                "consultation": {"fee": fee, "duration_min": 20,
                                 "weekly_slots": {d: ["10:00", "11:00", "12:00", "16:00", "17:00"]
                                                  for d in ["mon", "tue", "wed", "thu", "fri", "sat"]},
                                 "languages": ["English", "Hindi"], "video_enabled": True,
                                 "followup_policy": "One free follow-up within 7 days"},
                "documents": [], "photo": {}, "decisions": [{"by": "system", "action": "seed", "at": mp.now()}],
                "created_at": mp.now()})
            await db.mp_accounts.insert_one({"account_id": mp.uid("acc"), "role": "doctor", "email": email,
                                             "name": name, "ref_id": did, "email_verified": True,
                                             "created_at": mp.now()})
        logger.info("[mp] seeded 3 sample doctors")
    if await db.mp_services.count_documents({}) <= 4:
        svc_cats = await db.mp_categories.find({"module": "service"}, {"_id": 0}).to_list(50)
        cat_map = {c["title"]: c["cat_id"] for c in svc_cats}
        extras = [
            ("Beauty & Grooming", "Head-to-Toe Grooming", "Complete grooming session: trim, threading and clean-up.", 90, 999),
            ("Wellness Treatments", "Relaxation Body Massage", "Full-body relaxation massage with aromatic oils.", 60, 1599),
            ("Hair & Scalp Care", "Scalp Detox Treatment", "Deep scalp cleanse with anti-dandruff care.", 45, 799),
            ("Facials", "Classic Clean-Up", "Quick express clean-up for instant freshness.", 30, 499),
        ]
        for cat, name, desc, dur, price in extras:
            await db.mp_services.insert_one({
                "service_id": mp.uid("svc"), "name": name, "category_id": cat_map.get(cat, ""),
                "category_title": cat, "short_desc": desc, "full_desc": desc,
                "includes": ["Professional products", "Sanitised equipment"], "excludes": [],
                "duration_min": dur, "mode": "home", "price": price,
                "price_range": {"min": int(price * 0.8), "max": int(price * 1.3)},
                "commission_pct": 20.0, "tax_pct": 18.0, "offer_eligible": True,
                "cancellation_policy": "Free cancellation up to 4 hours before the slot.",
                "qualifications": [], "equipment": "", "prep": "", "aftercare": "",
                "warnings": "", "patch_test": False, "materials_included": True,
                "locations": [], "age_restriction": "", "images": [], "thumbnail": "",
                "status": "active", "created_at": mp.now(), "updated_at": mp.now()})
        logger.info("[mp] seeded 4 extra sample services")
    spec_map = {"Anti-Aging": ["Skin", "Anti-Aging"], "Acne & Hair": ["Acne", "Hair"], "Sensitive Skin": ["Skin", "Allergy & Eczema"]}
    async for d in db.mp_doctors.find({"professional.specialties": {"$exists": False}}):
        spec = (d.get("professional") or {}).get("specialisation") or ""
        await db.mp_doctors.update_one({"_id": d["_id"]}, {"$set": {
            "professional.specialties": spec_map.get(spec, [s.strip() for s in spec.split("&") if s.strip()] or ["Skin"])}})
    if not await db.mp_partners.find_one({"applicant.email": "partner@sample.celestaglow.com"}):
        svcs = await db.mp_services.find({"status": "active"}, {"_id": 0, "service_id": 1, "name": 1, "price": 1}).to_list(50)
        pid = mp.uid("prt")
        await db.mp_partners.insert_one({
            "partner_id": pid, "application_status": "approved", "active": True, "paused": False,
            "applicant": {"name": "Priya Nair", "mobile": "9800000001", "email": "partner@sample.celestaglow.com",
                          "business_name": "Glow Home Studio", "applicant_type": "business", "id_proof": "", "qualifications": ""},
            "staff": {"total": 4, "female": 3, "male": 1},
            "location": {"address": "MG Road", "city": "Bengaluru", "state": "KA", "pincode": "560001",
                         "lat": 12.9756, "lng": 77.6050, "coverage_area": "Bengaluru"},
            "payout": {}, "documents": [], "decisions": [{"by": "system", "action": "seed", "at": mp.now()}],
            "services": [{"service_id": s["service_id"], "service_name": s["name"], "mode": "home",
                          "price": s.get("price") or 999, "coverage": "", "qualifications": "",
                          "approval_status": "approved"} for s in svcs],
            "created_at": mp.now()})
        await db.mp_accounts.insert_one({"account_id": mp.uid("acc"), "role": "partner",
                                         "email": "partner@sample.celestaglow.com", "name": "Priya Nair",
                                         "ref_id": pid, "email_verified": True, "created_at": mp.now()})
        logger.info("[mp] seeded sample partner")


# ================================================================ public config
@router.get("/config")
async def public_config():
    c = await mp.cfg()
    online_docs = sum(1 for d in await Db.mp_doctors.find(
        {"application_status": "approved", "active": True}, {"online": 1, "last_seen": 1}).to_list(500) if mp.is_online(d))
    online_prts = sum(1 for p in await Db.mp_partners.find(
        {"application_status": "approved", "active": True}, {"online": 1, "last_seen": 1}).to_list(500) if mp.is_online(p))
    return {
        "dermatologist_enabled": c["dermatologist_enabled"],
        "home_services_enabled": c["home_services_enabled"],
        "payments_configured": mp.razorpay() is not None,
        "ai_photo_configured": mp.emergent_key() is not None,
        "support_email": c["support_email"],
        "online_doctors": online_docs,
        "online_partners": online_prts,
    }


@router.get("/categories")
async def list_categories(module: str = "service"):
    docs = await Db.mp_categories.find(
        {"module": module, "active": True}, {"_id": 0}).sort("order", 1).to_list(100)
    return docs


@router.get("/services")
async def list_services(category_id: str = "", q: str = "", subcategory_id: str = "", gender: str = "",
                        lat: float = 0, lng: float = 0, radius_km: float = 0):
    query: Dict[str, Any] = {"status": "active"}
    if category_id:
        query["category_id"] = category_id
    if subcategory_id:
        query["subcategory_id"] = subcategory_id
    if gender in ("women", "men"):
        query["gender"] = {"$in": [gender, "unisex", None]}
    if q:
        query["name"] = {"$regex": q, "$options": "i"}
    svcs = await Db.mp_services.find(query, {"_id": 0}).sort("created_at", -1).to_list(200)
    c = await mp.cfg()
    radius = radius_km or float(c.get("service_radius_km", 10))
    has_loc = bool(lat and lng)
    out = []
    for s in svcs:
        partners = await Db.mp_partners.find(
            {"application_status": "approved", "active": True, "paused": {"$ne": True},
             "services": {"$elemMatch": {"service_id": s["service_id"], "approval_status": "approved"}}},
            {"services.$": 1, "location": 1}).to_list(200)
        if has_loc:
            # Only count partners registered within the serviceable radius of the customer.
            nearby = []
            for p in partners:
                loc = p.get("location") or {}
                if loc.get("lat") and loc.get("lng") and mp.haversine_km(lat, lng, loc["lat"], loc["lng"]) <= radius:
                    nearby.append(p)
            partners = nearby
            if not partners:
                continue  # hide services with no nearby partner — customer sees "not available"
        s["partner_count"] = len(partners)
        prices = [p["services"][0].get("price") for p in partners if p.get("services") and p["services"][0].get("price")]
        _apply_price(s, min(prices) if prices else s.get("price"), c, s["service_id"])
        out.append(s)
    return out


def _apply_price(s: Dict[str, Any], base: Any, c: Dict[str, Any], seed: str = ""):
    pv = mp.price_view(base, c, seed)
    s.update({"price": pv["price"], "from_price": pv["price"], "mrp": pv["mrp"], "discount_pct": pv["discount_pct"]})
    s.pop("commission_pct", None)
    s.pop("price_range", None)


@router.get("/services/{service_id}")
async def get_service(service_id: str, lat: float = 0, lng: float = 0):
    s = await Db.mp_services.find_one({"service_id": service_id}, {"_id": 0})
    if not s or s.get("status") != "active":
        raise HTTPException(404, "Service not available")
    partners = await Db.mp_partners.find(
        {"application_status": "approved", "active": True, "paused": {"$ne": True},
         "services": {"$elemMatch": {"service_id": service_id, "approval_status": "approved"}}},
        {"_id": 0, "partner_id": 1, "applicant.business_name": 1, "applicant.name": 1, "services.$": 1,
         "staff": 1, "location.lat": 1, "location.lng": 1}).to_list(100)
    c = await mp.cfg()
    out = []
    for p in partners:
        pv = mp.price_view((p.get("services") or [{}])[0].get("price") or s.get("price"), c, f"{p['partner_id']}:{service_id}")
        loc = p.get("location") or {}
        dist = round(mp.haversine_km(lat, lng, loc["lat"], loc["lng"]), 1) if lat and lng and loc.get("lat") and loc.get("lng") else None
        if dist is not None and dist > float(c.get("service_radius_km", 10)):
            continue
        staff = p.get("staff") or {}
        out.append({"partner_id": p["partner_id"],
                    "name": (p.get("applicant") or {}).get("business_name") or (p.get("applicant") or {}).get("name"),
                    "price": pv["price"], "mrp": pv["mrp"], "discount_pct": pv["discount_pct"], "_base": pv["base"],
                    "female_staff": int(staff.get("female") or 0), "male_staff": int(staff.get("male") or 0),
                    "distance_km": dist, "eta_minutes": mp.eta_minutes(dist)})
    out.sort(key=lambda x: x["_base"])
    _apply_price(s, out[0]["_base"] if out else s.get("price"), c, service_id)
    for o in out:
        o.pop("_base", None)
    s["partners"] = out
    s["service_radius_km"] = c.get("service_radius_km", 10)
    return s


@router.get("/doctors")
async def list_doctors(category: str = "", lat: float = 0, lng: float = 0, radius_km: float = 0, city: str = ""):
    query: Dict[str, Any] = {"application_status": "approved", "active": True}
    radius_km = radius_km or float((await mp.cfg()).get("doctor_radius_km", 30))
    if category and category.lower() not in ("view all", ""):
        query["$or"] = [{"professional.specialisation": {"$regex": category, "$options": "i"}},
                        {"professional.specialties": {"$regex": category, "$options": "i"}}]
    docs = await Db.mp_doctors.find(query, {"_id": 0}).to_list(200)
    c = await mp.cfg()
    out = []
    for d in docs:
        pub = _public_doctor(d, c)
        pub["online"] = mp.is_online(d)
        loc = d.get("personal") or {}
        dlat, dlng = loc.get("lat"), loc.get("lng")
        if lat and lng:
            if dlat and dlng:
                dist = mp.haversine_km(lat, lng, dlat, dlng)
                pub["distance_km"] = round(dist, 1)
                pub["eta_minutes"] = mp.eta_minutes(dist)
                if dist > radius_km:
                    continue
            else:
                pub["distance_km"] = None
        out.append(pub)
    cl = city.strip().lower()
    out.sort(key=lambda x: (bool(cl) and (x.get("city") or "").lower() != cl,
                            x.get("distance_km") is None, x.get("distance_km") or 0))
    return out


def _public_doctor(d: Dict[str, Any], c: Dict[str, Any]) -> Dict[str, Any]:
    photo = (d.get("photo") or {})
    pv = mp.price_view((d.get("consultation") or {}).get("fee"), c, d["doctor_id"])
    return {
        "mrp": pv["mrp"], "discount_pct": pv["discount_pct"],
        "doctor_id": d["doctor_id"],
        "name": (d.get("personal") or {}).get("name"),
        "qualification": (d.get("professional") or {}).get("qualification"),
        "specialisation": (d.get("professional") or {}).get("specialisation"),
        "specialties": (d.get("professional") or {}).get("specialties") or [],
        "city": (d.get("personal") or {}).get("city", ""),
        "experience_years": (d.get("professional") or {}).get("experience_years"),
        "bio": (d.get("professional") or {}).get("bio"),
        "languages": (d.get("consultation") or {}).get("languages", []),
        "fee": pv["price"],
        "duration_min": (d.get("consultation") or {}).get("duration_min", 20),
        "verified": True,
        "photo": photo.get("chosen") or photo.get("processed") or photo.get("original_url") or "",
        "weekly_slots": (d.get("consultation") or {}).get("weekly_slots", {}),
    }


@router.get("/doctors/{doctor_id}")
async def get_doctor(doctor_id: str):
    d = await Db.mp_doctors.find_one({"doctor_id": doctor_id, "application_status": "approved", "active": True}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Doctor not found")
    out = _public_doctor(d, await mp.cfg())
    out["online"] = mp.is_online(d)
    out["engaged"] = bool(await Db.mp_consultations.find_one(
        {"doctor_id": doctor_id, "status": {"$in": ["in_progress", "completion_pending"]}}))
    booked = await Db.mp_consultations.find(
        {"doctor_id": doctor_id, "status": {"$in": ["confirmed", "pending_payment", "in_progress"]}},
        {"_id": 0, "date": 1, "slot": 1}).to_list(500)
    out["booked_slots"] = booked
    return out


# ================================================================ provider auth
class SendOtp(BaseModel):
    email: str
    role: str
    portal: bool = False


class VerifyOtp(BaseModel):
    email: str
    role: str
    otp: str


@router.post("/auth/send-otp")
async def provider_send_otp(body: SendOtp):
    if body.role not in ("doctor", "partner"):
        raise HTTPException(400, "Invalid role")
    acc = await Db.mp_accounts.find_one({"role": body.role, "email": body.email.lower()})
    if not acc:
        raise HTTPException(404, "No approved account for this email. Apply first or wait for approval.")
    if body.portal:
        coll, key = (Db.mp_doctors, "doctor_id") if body.role == "doctor" else (Db.mp_partners, "partner_id")
        prof = await coll.find_one({key: acc.get("ref_id")}, {"_id": 0, "application_status": 1}) if acc.get("ref_id") else None
        if not prof or prof.get("application_status") != "approved":
            raise HTTPException(403, "Your application is still under review — dashboard login opens once you are approved.")
    code = mp.otp_code()
    import datetime as _dt
    await Db.mp_otps.update_one(
        {"email": body.email.lower(), "role": body.role},
        {"$set": {"otp_hash": mp.hash_otp(code), "attempts": 0,
                  "expires_at": (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=10)).isoformat()}},
        upsert=True)
    sent = await mp.send_mail(body.email, "Celesta Glow partner login code",
                              f"Your login code is {code}. It expires in 10 minutes.",
                              f"<h2 style='font-family:sans-serif'>Your login code: <b>{code}</b></h2><p>Expires in 10 minutes.</p>")
    return {"success": True, "email_sent": sent, "dev_otp": None if sent else code}


@router.post("/auth/verify-otp")
async def provider_verify_otp(body: VerifyOtp):
    rec = await Db.mp_otps.find_one({"email": body.email.lower(), "role": body.role})
    if not rec or rec.get("expires_at", "") < mp.now():
        raise HTTPException(400, "Code expired — request a new one")
    if (rec.get("attempts") or 0) >= 5:
        raise HTTPException(429, "Too many attempts — request a new code")
    if rec.get("otp_hash") != mp.hash_otp(body.otp):
        await Db.mp_otps.update_one({"_id": rec["_id"]}, {"$inc": {"attempts": 1}})
        raise HTTPException(400, "Incorrect code")
    acc = await Db.mp_accounts.find_one({"role": body.role, "email": body.email.lower()})
    if not acc:
        raise HTTPException(404, "Account not found")
    import secrets as _s
    import datetime as _dt
    token = _s.token_hex(24)
    await Db.mp_sessions.insert_one({
        "token": token, "account_id": acc.get("account_id"),
        "role": body.role,
        "expires_at": (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=14)).isoformat()})
    await Db.mp_otps.delete_one({"_id": rec["_id"]})
    return {"success": True, "token": token, "role": body.role, "ref_id": acc.get("ref_id"), "name": acc.get("name")}


@router.get("/auth/me")
async def provider_me(authorization: str = Header(None)):
    token = (authorization or "").split()[-1] if authorization else ""
    sess = await Db.mp_sessions.find_one({"token": token}, {"_id": 0})
    if not sess:
        raise HTTPException(401, "Not logged in")
    acc = await Db.mp_accounts.find_one({"account_id": sess["account_id"]}, {"_id": 0})
    if not acc:
        acc = await Db.mp_accounts.find_one({"_id": sess["account_id"]}, {"_id": 0})
    if not acc:
        raise HTTPException(401, "Account not found")
    coll = Db.mp_doctors if acc["role"] == "doctor" else Db.mp_partners
    prof = await coll.find_one({"doctor_id" if acc["role"] == "doctor" else "partner_id": acc["ref_id"]}, {"_id": 0})
    return {"role": acc["role"], "email": acc["email"], "name": acc.get("name"), "ref_id": acc["ref_id"], "profile": prof}


# ================================================================ applications
class DoctorApplication(BaseModel):
    name: str
    mobile: str
    email: str
    address: str = ""
    city: str = ""
    state: str = ""
    pincode: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    languages: List[str] = []
    qualification: str = ""
    institution: str = ""
    graduation_year: str = ""
    postgrad: str = ""
    specialisation: str = ""
    specialties: List[str] = []
    experience_years: int = 0
    bio: str = ""
    registration_number: str = ""
    issuing_authority: str = ""
    fee: float = 999
    duration_min: int = 20
    weekly_slots: Dict[str, List[str]] = {}
    video_enabled: bool = True
    followup_policy: str = ""


@router.post("/doctors/apply")
async def doctor_apply(app: DoctorApplication):
    cfg = await mp.cfg()
    if not cfg["dermatologist_enabled"]:
        raise HTTPException(403, "Dermatologist onboarding is currently closed")
    if not app.registration_number:
        raise HTTPException(400, "Medical registration number is required")
    existing = await Db.mp_doctors.find_one({"personal.email": app.email.lower(),
                                             "application_status": {"$in": ["pending", "approved", "info_requested"]}})
    if existing:
        raise HTTPException(409, "An application already exists for this email")
    doc = {
        "doctor_id": mp.uid("doc"),
        "application_status": "pending", "active": False,
        "personal": {"name": app.name, "mobile": app.mobile, "email": app.email.lower(),
                     "address": app.address, "city": app.city, "state": app.state, "pincode": app.pincode,
                         "lat": getattr(app, "lat", None), "lng": getattr(app, "lng", None)},
        "professional": {"qualification": app.qualification, "institution": app.institution,
                         "graduation_year": app.graduation_year, "postgrad": app.postgrad,
                         "specialisation": app.specialisation, "experience_years": app.experience_years,
                         "bio": app.bio, "registration_number": app.registration_number,
                         "issuing_authority": app.issuing_authority,
                         "specialties": app.specialties},
        "consultation": {"fee": app.fee, "duration_min": app.duration_min, "weekly_slots": app.weekly_slots,
                         "languages": app.languages, "video_enabled": app.video_enabled,
                         "followup_policy": app.followup_policy},
        "documents": [], "photo": {}, "decisions": [], "created_at": mp.now(),
    }
    await Db.mp_doctors.insert_one(doc)
    await mp.notify("admin", "all", "New dermatologist application", f"{app.name} applied", "/admin/doctors-crm")
    await mp.send_mail(app.email, "Celesta Glow — application received",
                       f"Hi {app.name}, your dermatologist application {doc['doctor_id']} was received and is under review.")
    return {"success": True, "application_id": doc["doctor_id"], "status": "pending"}


class PartnerServiceSelection(BaseModel):
    service_id: str
    mode: str = "home"
    price: Optional[float] = None
    coverage: str = ""
    qualifications: str = ""


class PartnerApplication(BaseModel):
    name: str
    mobile: str
    email: str
    business_name: str = ""
    applicant_type: str = "individual"
    address: str
    city: str
    state: str
    pincode: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    coverage_area: str = ""
    id_proof: str = ""
    qualifications: str = ""
    account_holder: str = ""
    bank_account: str = ""
    ifsc: str = ""
    upi: str = ""
    staff_total: int = 1
    staff_female: int = 0
    staff_male: int = 0
    availability: Dict[str, List[str]] = {}
    services: List[PartnerServiceSelection] = []


def _staff(app: "PartnerApplication") -> Dict[str, int]:
    f, m = max(0, app.staff_female), max(0, app.staff_male)
    return {"total": max(app.staff_total, f + m, 1), "female": f, "male": m}


@router.post("/partners/apply")
async def partner_apply(app: PartnerApplication):
    cfg = await mp.cfg()
    if not cfg["home_services_enabled"]:
        raise HTTPException(403, "Partner onboarding is currently closed")
    if not app.services:
        raise HTTPException(400, "Select at least one service from the catalogue")
    valid = []
    for sel in app.services:
        svc = await Db.mp_services.find_one({"service_id": sel.service_id, "status": "active"}, {"_id": 0})
        if not svc:
            raise HTTPException(400, f"Service {sel.service_id} is not an active catalogue service")
        price = sel.price if sel.price is not None else svc.get("price")
        if price is None or float(price) <= 0:
            raise HTTPException(400, f"Set your price for {svc['name']}")
        valid.append({"service_id": sel.service_id, "service_name": svc["name"], "mode": sel.mode,
                      "price": price, "coverage": sel.coverage, "qualifications": sel.qualifications,
                      "approval_status": "pending"})
    existing = await Db.mp_partners.find_one({"applicant.email": app.email.lower(),
                                              "application_status": {"$in": ["pending", "approved", "info_requested"]}})
    if existing:
        raise HTTPException(409, "An application already exists for this email")
    doc = {
        "partner_id": mp.uid("prt"), "application_status": "pending", "active": False, "paused": False,
        "applicant": {"name": app.name, "mobile": app.mobile, "email": app.email.lower(),
                      "business_name": app.business_name, "applicant_type": app.applicant_type,
                      "id_proof": app.id_proof, "qualifications": app.qualifications},
        "staff": _staff(app), "availability": app.availability,
        "location": {"address": app.address, "city": app.city, "state": app.state, "pincode": app.pincode,
                     "lat": app.lat, "lng": app.lng, "coverage_area": app.coverage_area},
        "payout": {"account_holder": app.account_holder, "bank_account": app.bank_account,
                   "ifsc": app.ifsc, "upi": app.upi},
        "services": valid, "documents": [], "decisions": [], "created_at": mp.now(),
    }
    await Db.mp_partners.insert_one(doc)
    await mp.notify("admin", "all", "New service partner application", f"{app.name} applied", "/admin/partners-crm")
    await mp.send_mail(app.email, "Celesta Glow — partner application received",
                       f"Hi {app.name}, your partner application {doc['partner_id']} was received and is under review.")
    return {"success": True, "application_id": doc["partner_id"], "status": "pending"}


# ================================================================ media
@router.get("/media/{name}")
async def serve_media(name: str):
    safe = name.replace("/", "").replace("..", "")
    path = mp.UPLOAD_DIR / safe
    if not path.exists():
        raise HTTPException(404, "Not found")
    return FileResponse(str(path))


# ================================================================ admin
@router.get("/admin/config")
async def admin_get_config(x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    c = await mp.cfg()
    c.pop("_id", None)
    c["payments_configured"] = mp.razorpay() is not None
    c["ai_photo_configured"] = mp.emergent_key() is not None
    return c


async def _check_admin(x_admin_token: Optional[str]):
    verifier = mp.verify_admin_dep()
    try:
        res = verifier(x_admin_token=x_admin_token, admin_session=None)
        if hasattr(res, "__await__"):
            await res
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(401, f"Admin auth failed: {exc}")


class ConfigUpdate(BaseModel):
    dermatologist_enabled: Optional[bool] = None
    home_services_enabled: Optional[bool] = None
    platform_commission_pct: Optional[float] = None
    customer_fee_pct: Optional[float] = None
    display_markup_pct: Optional[float] = None
    doctor_contact_policy: Optional[str] = None
    support_email: Optional[str] = None
    doctor_radius_km: Optional[float] = None
    service_radius_km: Optional[float] = None
    offer_expiry_minutes: Optional[int] = None


@router.put("/admin/config")
async def admin_update_config(body: ConfigUpdate, x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if updates:
        await Db.mp_config.update_one({"_id": "main"}, {"$set": updates}, upsert=True)
        await mp.audit("admin", "config_update", "mp_config", "main", new=updates)
    return {"success": True, **updates}


class CategoryIn(BaseModel):
    module: str
    title: str
    description: str = ""
    image: str = ""
    order: int = 0
    active: bool = True
    show_on_home: bool = True
    show_in_onboarding: bool = True


CONTENT_FIELDS = {
    "service": (lambda: Db.mp_services, "service_id", {"name", "short_desc", "full_desc"}),
    "category": (lambda: Db.mp_categories, "cat_id", {"title", "description"}),
    "doctor": (lambda: Db.mp_doctors, "doctor_id", {"professional.bio", "professional.specialties", "professional.specialisation"}),
}


@router.patch("/admin/content/{kind}/{item_id}")
async def admin_edit_content(kind: str, item_id: str, body: Dict[str, Any], x_admin_token: str = Header(None)):
    """Edit display text of a service / category / doctor from the admin content manager."""
    await _check_admin(x_admin_token)
    if kind not in CONTENT_FIELDS:
        raise HTTPException(400, "Unknown content type")
    coll_fn, key, allowed = CONTENT_FIELDS[kind]
    updates = {k: v for k, v in body.items() if k in allowed}
    if not updates:
        raise HTTPException(400, "Nothing to update")
    res = await coll_fn().update_one({key: item_id}, {"$set": {**updates, "updated_at": mp.now()}})
    if not res.matched_count:
        raise HTTPException(404, "Item not found")
    if kind == "service" and "name" in updates:
        await Db.mp_partners.update_many({"services.service_id": item_id},
                                         {"$set": {"services.$[s].service_name": updates["name"]}},
                                         array_filters=[{"s.service_id": item_id}])
    await mp.audit("admin", "content_edit", kind, item_id, new=updates)
    return {"success": True, **updates}


@router.get("/admin/categories")
async def admin_list_categories(module: str = "", x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    q = {"module": module} if module else {}
    return await Db.mp_categories.find(q, {"_id": 0}).sort([("module", 1), ("order", 1)]).to_list(300)


@router.post("/admin/categories")
async def admin_create_category(body: CategoryIn, x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    doc = {"cat_id": mp.uid("cat"), **body.dict(), "created_at": mp.now()}
    await Db.mp_categories.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.put("/admin/categories/{cat_id}")
async def admin_update_category(cat_id: str, body: CategoryIn, x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    await Db.mp_categories.update_one({"cat_id": cat_id}, {"$set": body.dict()})
    return {"success": True}


@router.delete("/admin/categories/{cat_id}")
async def admin_delete_category(cat_id: str, x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    await Db.mp_categories.delete_one({"cat_id": cat_id})
    return {"success": True}


@router.post("/admin/categories/{cat_id}/image")
async def admin_upload_category_image(cat_id: str, file: UploadFile = File(...), x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    cat = await Db.mp_categories.find_one({"cat_id": cat_id}, {"_id": 0})
    if not cat:
        raise HTTPException(404, "Category not found")
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "Image must be under 8MB")
    if (file.content_type or "") not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(400, "Only JPG, PNG or WebP images are allowed")
    ext = (file.filename or "img.jpg").rsplit(".", 1)[-1].lower()
    url = await mp.store_image(data, f"cat-{cat_id}-{len(cat.get('title',''))}", ext)
    await Db.mp_categories.update_one({"cat_id": cat_id}, {"$set": {"image": url}})
    return {"success": True, "url": url}


@router.post("/admin/doctors/{doctor_id}/photo")
async def admin_doctor_photo(doctor_id: str, file: UploadFile = File(...), x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    d = await Db.mp_doctors.find_one({"doctor_id": doctor_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Doctor not found")
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "Photo must be under 8MB")
    ext = (file.filename or "photo.jpg").rsplit(".", 1)[-1].lower()
    url = await mp.store_image(data, f"doc-{doctor_id}-admin-{__import__('secrets').token_hex(3)}", ext)
    photo = d.get("photo") or {}
    photo.update({"original_url": url, "chosen": url, "status": "approved", "uploaded_at": mp.now()})
    await Db.mp_doctors.update_one({"doctor_id": doctor_id}, {"$set": {"photo": photo}})
    return {"success": True, "url": url}


@router.post("/admin/partners/{partner_id}/photo")
async def admin_partner_photo(partner_id: str, file: UploadFile = File(...), x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    p = await Db.mp_partners.find_one({"partner_id": partner_id}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Partner not found")
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "Photo must be under 8MB")
    ext = (file.filename or "photo.jpg").rsplit(".", 1)[-1].lower()
    url = await mp.store_image(data, f"prt-{partner_id}-admin-{__import__('secrets').token_hex(3)}", ext)
    await Db.mp_partners.update_one({"partner_id": partner_id}, {"$set": {
        "photo": {"original_url": url, "chosen": url, "status": "approved", "uploaded_at": mp.now()}}})
    return {"success": True, "url": url}


@router.get("/admin/reviews")
async def admin_reviews(module: str = "", x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    q = {"module": module} if module else {}
    return await Db.mp_reviews.find(q, {"_id": 0}).sort("at", -1).to_list(300)


class ServiceIn(BaseModel):
    name: str
    category_id: str = ""
    category_title: str = ""
    short_desc: str = ""
    full_desc: str = ""
    includes: List[str] = []
    excludes: List[str] = []
    duration_min: int = 60
    mode: str = "home"
    price: float = 0
    price_range: Dict[str, float] = {"min": 0, "max": 0}
    commission_pct: float = 20.0
    tax_pct: float = 18.0
    offer_eligible: bool = True
    cancellation_policy: str = ""
    qualifications: List[str] = []
    equipment: str = ""
    prep: str = ""
    aftercare: str = ""
    warnings: str = ""
    patch_test: bool = False
    materials_included: bool = True
    locations: List[str] = []
    age_restriction: str = ""
    status: str = "draft"


@router.get("/admin/services")
async def admin_list_services(status: str = "", x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    q = {"status": status} if status else {}
    return await Db.mp_services.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


@router.post("/admin/services")
async def admin_create_service(body: ServiceIn, x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    doc = {"service_id": mp.uid("svc"), **body.dict(), "images": [], "thumbnail": "",
           "created_at": mp.now(), "updated_at": mp.now()}
    await Db.mp_services.insert_one(doc)
    await mp.audit("admin", "create", "service", doc["service_id"], new=doc["name"])
    doc.pop("_id", None)
    return doc


@router.put("/admin/services/{service_id}")
async def admin_update_service(service_id: str, body: ServiceIn, x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    data = body.dict()
    data["updated_at"] = mp.now()
    res = await Db.mp_services.update_one({"service_id": service_id}, {"$set": data})
    if not res.matched_count:
        raise HTTPException(404, "Service not found")
    await mp.audit("admin", "update", "service", service_id, new=data.get("name"))
    return {"success": True}


@router.post("/admin/services/{service_id}/status")
async def admin_service_status(service_id: str, body: Dict[str, str], x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    status = body.get("status")
    if status not in ("draft", "active", "inactive", "pending", "archived"):
        raise HTTPException(400, "Invalid status")
    svc = await Db.mp_services.find_one({"service_id": service_id}, {"_id": 0})
    if not svc:
        raise HTTPException(404, "Service not found")
    if status == "active" and not svc.get("thumbnail") and not svc.get("images"):
        raise HTTPException(400, "Add at least one service image before publishing")
    await Db.mp_services.update_one({"service_id": service_id}, {"$set": {"status": status, "updated_at": mp.now()}})
    await mp.audit("admin", f"status:{status}", "service", service_id, prev=svc.get("status"), new=status)
    return {"success": True, "status": status}


@router.post("/admin/services/{service_id}/images")
async def admin_upload_service_image(service_id: str, file: UploadFile = File(...), replace: bool = False,
                                     x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    svc = await Db.mp_services.find_one({"service_id": service_id}, {"_id": 0})
    if not svc:
        raise HTTPException(404, "Service not found")
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "Image must be under 8MB")
    if (file.content_type or "") not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(400, "Only JPG, PNG or WebP images are allowed")
    ext = (file.filename or "img.jpg").rsplit(".", 1)[-1].lower()
    url = await mp.store_image(data, f"svc-{service_id}-{len(svc.get('images', []))}", ext)
    images = svc.get("images", []) + [url]
    await Db.mp_services.update_one({"service_id": service_id},
                                    {"$set": {"images": images,
                                              "thumbnail": url if replace else (svc.get("thumbnail") or url),
                                              "updated_at": mp.now()}})
    return {"success": True, "url": url, "images": images}


@router.delete("/admin/services/{service_id}/images")
async def admin_delete_service_image(service_id: str, url: str, x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    svc = await Db.mp_services.find_one({"service_id": service_id}, {"_id": 0})
    if not svc:
        raise HTTPException(404, "Service not found")
    images = [i for i in svc.get("images", []) if i != url]
    thumb = svc.get("thumbnail") if svc.get("thumbnail") in images else (images[0] if images else "")
    await Db.mp_services.update_one({"service_id": service_id}, {"$set": {"images": images, "thumbnail": thumb}})
    return {"success": True, "images": images}


@router.post("/admin/services/{service_id}/thumbnail")
async def admin_set_thumbnail(service_id: str, body: Dict[str, str], x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    await Db.mp_services.update_one({"service_id": service_id}, {"$set": {"thumbnail": body.get("url", "")}})
    return {"success": True}


# ------------------------------------------------------- admin: CRM review
class ReviewDecision(BaseModel):
    action: str  # approve | reject | request_info | suspend | reactivate
    reason: str = ""


@router.get("/admin/doctors")
async def admin_list_doctors(status: str = "", x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    q = {"application_status": status} if status else {}
    return await Db.mp_doctors.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


@router.post("/admin/doctors/{doctor_id}/review")
async def admin_review_doctor(doctor_id: str, body: ReviewDecision, x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    d = await Db.mp_doctors.find_one({"doctor_id": doctor_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Doctor not found")
    mapping = {"approve": "approved", "reject": "rejected", "request_info": "info_requested",
               "suspend": "suspended", "reactivate": "approved"}
    if body.action not in mapping:
        raise HTTPException(400, "Invalid action")
    new_status = mapping[body.action]
    prev = d["application_status"]
    decision = {"by": "admin", "action": body.action, "reason": body.reason,
                "prev": prev, "new": new_status, "at": mp.now()}
    await Db.mp_doctors.update_one({"doctor_id": doctor_id}, {
        "$set": {"application_status": new_status,
                 "active": new_status == "approved"},
        "$push": {"decisions": decision}})
    await mp.audit("admin", f"doctor:{body.action}", "doctor", doctor_id, prev=prev, new=new_status, reason=body.reason)
    if body.action == "approve":
        await Db.mp_accounts.update_one(
            {"role": "doctor", "email": d["personal"]["email"]},
            {"$set": {"role": "doctor", "email": d["personal"]["email"],
                      "name": d["personal"]["name"], "ref_id": doctor_id},
             "$setOnInsert": {"account_id": mp.uid("acc"), "created_at": mp.now(), "email_verified": True}},
            upsert=True)
        await mp.send_mail(d["personal"]["email"], "Celesta Glow — application approved",
                           f"Congratulations Dr. {d['personal']['name']}! Your profile is approved. "
                           f"Log in to your doctor dashboard with this email to set availability and receive bookings.")
    elif body.action in ("reject", "request_info"):
        await mp.send_mail(d["personal"]["email"], f"Celesta Glow — application {new_status.replace('_', ' ')}",
                           f"Your application status is now: {new_status.replace('_',' ')}. Reason: {body.reason or '—'}")
    return {"success": True, "status": new_status}


@router.put("/admin/doctors/{doctor_id}/details")
async def admin_edit_doctor_details(doctor_id: str, body: Dict[str, Any], x_admin_token: str = Header(None)):
    """Full edit of every dermatologist field from the 'All Dermatologists' admin section."""
    await _check_admin(x_admin_token)
    d = await Db.mp_doctors.find_one({"doctor_id": doctor_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Doctor not found")
    FMAP = {
        "name": "personal.name", "email": "personal.email", "mobile": "personal.mobile",
        "city": "personal.city", "state": "personal.state", "pincode": "personal.pincode",
        "qualification": "professional.qualification", "institution": "professional.institution",
        "specialisation": "professional.specialisation", "registration_number": "professional.registration_number",
        "issuing_authority": "professional.issuing_authority", "bio": "professional.bio",
    }
    updates: Dict[str, Any] = {FMAP[k]: body[k] for k in FMAP if k in body}
    if "experience_years" in body:
        try:
            updates["professional.experience_years"] = int(body["experience_years"])
        except (TypeError, ValueError):
            pass
    for src, path in (("specialties", "professional.specialties"), ("languages", "consultation.languages")):
        if src in body:
            v = body[src]
            updates[path] = v if isinstance(v, list) else [s.strip() for s in str(v).split(",") if s.strip()]
    if "fee" in body:
        try:
            updates["consultation.fee"] = float(body["fee"])
        except (TypeError, ValueError):
            pass
    if "duration_min" in body:
        try:
            updates["consultation.duration_min"] = int(body["duration_min"])
        except (TypeError, ValueError):
            pass
    if not updates:
        raise HTTPException(400, "Nothing to update")
    updates["updated_at"] = mp.now()
    await Db.mp_doctors.update_one({"doctor_id": doctor_id}, {"$set": updates})
    await mp.audit("admin", "doctor_edit_details", "doctor", doctor_id, new=list(updates.keys()))
    return {"success": True}


@router.delete("/admin/doctors/{doctor_id}")
async def admin_remove_doctor(doctor_id: str, x_admin_token: str = Header(None)):
    """Soft-remove a dermatologist from the user app (reversible via re-approve)."""
    await _check_admin(x_admin_token)
    d = await Db.mp_doctors.find_one({"doctor_id": doctor_id}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Doctor not found")
    await Db.mp_doctors.update_one({"doctor_id": doctor_id}, {"$set": {
        "active": False, "application_status": "removed", "removed": True, "removed_at": mp.now()}})
    await Db.mp_accounts.update_many({"role": "doctor", "ref_id": doctor_id}, {"$set": {"disabled": True}})
    await mp.audit("admin", "doctor_remove", "doctor", doctor_id)
    return {"success": True}


@router.get("/admin/partners")
async def admin_list_partners(status: str = "", x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    q = {"application_status": status} if status else {}
    return await Db.mp_partners.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)


@router.post("/admin/partners/{partner_id}/review")
async def admin_review_partner(partner_id: str, body: ReviewDecision, x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    p = await Db.mp_partners.find_one({"partner_id": partner_id}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Partner not found")
    mapping = {"approve": "approved", "reject": "rejected", "request_info": "info_requested",
               "suspend": "suspended", "reactivate": "approved"}
    if body.action not in mapping:
        raise HTTPException(400, "Invalid action")
    new_status = mapping[body.action]
    prev = p["application_status"]
    decision = {"by": "admin", "action": body.action, "reason": body.reason,
                "prev": prev, "new": new_status, "at": mp.now()}
    svc_updates = {}
    if body.action == "approve":
        svc_updates["services"] = [{**s, "approval_status": "approved"} for s in p.get("services", [])]
    await Db.mp_partners.update_one({"partner_id": partner_id}, {
        "$set": {"application_status": new_status, "active": new_status == "approved", **svc_updates},
        "$push": {"decisions": decision}})
    await mp.audit("admin", f"partner:{body.action}", "partner", partner_id, prev=prev, new=new_status, reason=body.reason)
    if body.action == "approve":
        await Db.mp_accounts.update_one(
            {"role": "partner", "email": p["applicant"]["email"]},
            {"$set": {"role": "partner", "email": p["applicant"]["email"],
                      "name": p["applicant"]["name"], "ref_id": partner_id},
             "$setOnInsert": {"account_id": mp.uid("acc"), "created_at": mp.now(), "email_verified": True}},
            upsert=True)
        await mp.send_mail(p["applicant"]["email"], "Celesta Glow — partner application approved",
                           f"Congratulations {p['applicant']['name']}! You can now log in to your partner dashboard and start receiving bookings.")
    return {"success": True, "status": new_status}


@router.post("/admin/partners/{partner_id}/services/{service_id}/decision")
async def admin_partner_service_decision(partner_id: str, service_id: str, body: Dict[str, str],
                                         x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    decision = body.get("decision")
    if decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision must be approved|rejected")
    res = await Db.mp_partners.update_one(
        {"partner_id": partner_id, "services.service_id": service_id},
        {"$set": {"services.$.approval_status": decision}})
    if not res.matched_count:
        raise HTTPException(404, "Partner service mapping not found")
    await mp.audit("admin", f"partner_service:{decision}", "partner", partner_id, new=service_id)
    return {"success": True, "decision": decision}


# ------------------------------------------------------- admin: withdrawals
@router.get("/admin/refunds")
async def admin_refunds(status: str = "", x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    q = {"status": status} if status else {}
    return await Db.mp_refunds.find(q, {"_id": 0}).sort("at", -1).to_list(300)


@router.post("/admin/refunds/{refund_id}/process")
async def admin_process_refund(refund_id: str, body: Dict[str, Any], x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    r = await Db.mp_refunds.find_one({"refund_id": refund_id}, {"_id": 0})
    if not r:
        raise HTTPException(404, "Refund not found")
    action = body.get("action", "refunded")
    if action == "refunded" and body.get("to", "wallet") == "wallet" and r.get("customer_email"):
        await mp.wallet_move("customer", r["customer_email"], float(r.get("amount", 0)), "credit",
                             f"Refund for {r['booking_id']}", r["booking_id"])
    await Db.mp_refunds.update_one({"refund_id": refund_id}, {"$set": {
        "status": "refunded" if action == "refunded" else "rejected",
        "reference": body.get("reference", ""), "processed_at": mp.now()}})
    coll = Db.mp_consultations if r.get("module") == "consultation" else Db.mp_home_bookings
    if action == "refunded":
        await coll.update_one({"booking_id": r["booking_id"]}, {"$set": {"status": "refunded", "updated_at": mp.now()}})
    return {"success": True}


@router.get("/admin/withdrawals")
async def admin_withdrawals(status: str = "", owner_type: str = "", x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if owner_type:
        q["owner_type"] = owner_type
    rows = await Db.mp_withdrawals.find(q, {"_id": 0}).sort("at", -1).to_list(300)
    # enrich with provider name for the admin table
    for w in rows:
        coll = Db.mp_doctors if w.get("owner_type") == "doctor" else Db.mp_partners
        key = "doctor_id" if w.get("owner_type") == "doctor" else "partner_id"
        prov = await coll.find_one({key: w.get("owner_id")}, {"_id": 0})
        w["owner_name"] = (prov or {}).get("name") or ((prov or {}).get("applicant") or {}).get("name") or w.get("owner_id")
        w["owner_balance"] = await mp.wallet_balance(w["owner_type"], w["owner_id"])
    return rows


@router.post("/admin/withdrawals/{withdrawal_id}/process")
async def admin_process_withdrawal(withdrawal_id: str, body: Dict[str, str], x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    w = await Db.mp_withdrawals.find_one({"withdrawal_id": withdrawal_id}, {"_id": 0})
    if not w or w["status"] != "pending":
        raise HTTPException(404, "Pending withdrawal not found")
    action = body.get("action")
    if action == "paid":
        await Db.mp_withdrawals.update_one({"withdrawal_id": withdrawal_id}, {"$set": {
            "status": "paid", "reference": body.get("reference", ""), "processed_by": "admin", "processed_at": mp.now()}})
    elif action == "rejected":
        await mp.wallet_move(w["owner_type"], w["owner_id"], w["amount"], "credit",
                             f"withdrawal {withdrawal_id} rejected — refund")
        await Db.mp_withdrawals.update_one({"withdrawal_id": withdrawal_id}, {"$set": {
            "status": "rejected", "reason": body.get("reason", ""), "processed_by": "admin", "processed_at": mp.now()}})
    else:
        raise HTTPException(400, "action must be paid|rejected")
    await mp.audit("admin", f"withdrawal:{action}", "withdrawal", withdrawal_id)
    await mp.notify(w["owner_type"], w["owner_id"], f"Withdrawal {action}",
                    f"Your withdrawal of ₹{w['amount']} was {action}.", "")
    return {"success": True, "status": action}


# ------------------------------------------------------- admin: support
@router.get("/admin/support")
async def admin_support(status: str = "", category: str = "", user_type: str = "", x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if category:
        q["category"] = category
    if user_type:
        q["user_type"] = user_type
    return await Db.mp_support.find(q, {"_id": 0}).sort("updated_at", -1).to_list(500)


@router.patch("/admin/support/{ticket_id}")
async def admin_support_patch(ticket_id: str, body: Dict[str, Any], x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    updates = {k: body[k] for k in ("status", "assigned", "priority", "resolution_notes") if k in body}
    updates["updated_at"] = mp.now()
    res = await Db.mp_support.update_one({"ticket_id": ticket_id}, {"$set": updates})
    if not res.matched_count:
        raise HTTPException(404, "Ticket not found")
    return {"success": True}


@router.post("/admin/support/{ticket_id}/reply")
async def admin_support_reply(ticket_id: str, body: Dict[str, str], x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    reply = {"by": "support", "message": body.get("message", ""), "at": mp.now()}
    res = await Db.mp_support.update_one({"ticket_id": ticket_id},
                                         {"$push": {"responses": reply},
                                          "$set": {"updated_at": mp.now(), "status": body.get("status", "in_progress")}})
    if not res.matched_count:
        raise HTTPException(404, "Ticket not found")
    t = await Db.mp_support.find_one({"ticket_id": ticket_id}, {"_id": 0})
    if t and t.get("user_ref"):
        await mp.send_mail(t["user_ref"], f"Re: {t['subject']} [{ticket_id}]",
                           f"Support replied: {reply['message']}")
    return {"success": True}


# ------------------------------------------------------- admin: bookings
@router.get("/admin/bookings")
async def admin_bookings(module: str = "consultation", page: int = 1, per_page: int = 20,
                         status: str = "", booking_id: str = "", customer: str = "",
                         provider: str = "", date_from: str = "", date_to: str = "",
                         x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    coll = Db.mp_consultations if module == "consultation" else Db.mp_home_bookings
    q: Dict[str, Any] = {}
    if status:
        q["status"] = status
    if booking_id:
        q["booking_id"] = {"$regex": booking_id, "$options": "i"}
    if customer:
        q["customer.email"] = {"$regex": customer, "$options": "i"}
    if provider:
        key = "doctor_id" if module == "consultation" else "partner_id"
        q[key] = {"$regex": provider, "$options": "i"}
    if date_from:
        q.setdefault("date", {})["$gte"] = date_from
    if date_to:
        q.setdefault("date", {})["$lte"] = date_to
    total = await coll.count_documents(q)
    items = await coll.find(q, {"_id": 0}).sort("created_at", -1).skip((page - 1) * per_page).limit(per_page).to_list(per_page)
    return {"total": total, "page": page, "per_page": per_page, "items": items}


@router.post("/admin/bookings/{module}/{booking_id}/action")
async def admin_booking_action(module: str, booking_id: str, body: Dict[str, Any], x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    coll = Db.mp_consultations if module == "consultation" else Db.mp_home_bookings
    b = await coll.find_one({"booking_id": booking_id}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking not found")
    action = body.get("action")
    if action == "mark_paid":
        await coll.update_one({"booking_id": booking_id}, {"$set": {"payment_status": "paid", "status": "confirmed",
                                                                    "paid_by": "admin_manual", "updated_at": mp.now()}})
        await mp.notify("customer", b["customer"]["email"], "Booking confirmed",
                        f"Your booking {booking_id} is confirmed.", "/my/bookings")
        if module == "consultation":
            from routes.mp_ops import on_consult_confirmed
            await on_consult_confirmed({**b, "payment_status": "paid", "status": "confirmed"})
    elif action == "cancel":
        await coll.update_one({"booking_id": booking_id}, {"$set": {"status": "cancelled", "updated_at": mp.now(),
                                                                    "cancel_reason": body.get("reason", "")}})
        await mp.notify("customer", b["customer"]["email"], "Booking cancelled",
                        f"Your booking {booking_id} was cancelled. {body.get('reason','')}", "/my/bookings")
    elif action == "rebroadcast" and module == "home":
        from routes.mp_ops import broadcast_offers
        await coll.update_one({"booking_id": booking_id}, {"$set": {"status": "pending_assignment", "partner_id": None}})
        await broadcast_offers({**b, "status": "pending_assignment", "partner_id": None})
    else:
        raise HTTPException(400, "Unsupported action")
    await mp.audit("admin", f"booking:{action}", module, booking_id, reason=body.get("reason", ""))
    return {"success": True}


# ================================================================ provider onboarding (/pro)
class ProviderRegisterIn(BaseModel):
    role: str
    name: str
    email: str
    mobile: str = ""


@router.post("/provider/register")
async def provider_register(body: ProviderRegisterIn):
    if body.role not in ("doctor", "partner"):
        raise HTTPException(400, "role must be doctor|partner")
    email = body.email.lower()
    coll = Db.mp_doctors if body.role == "doctor" else Db.mp_partners
    email_key = "personal.email" if body.role == "doctor" else "applicant.email"
    existing = await coll.find_one({email_key: email,
                                    "application_status": {"$in": ["pending", "approved", "info_requested"]}})
    if existing:
        raise HTTPException(409, "An application already exists for this email — log in instead.")
    await Db.mp_accounts.update_one(
        {"role": body.role, "email": email},
        {"$set": {"name": body.name, "mobile": body.mobile},
         "$setOnInsert": {"account_id": mp.uid("acc"), "role": body.role, "email": email,
                          "created_at": mp.now(), "ref_id": None, "email_verified": False}},
        upsert=True)
    code = mp.otp_code()
    import datetime as _dt
    await Db.mp_otps.update_one(
        {"email": email, "role": body.role},
        {"$set": {"otp_hash": mp.hash_otp(code), "attempts": 0,
                  "expires_at": (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(minutes=10)).isoformat()}},
        upsert=True)
    sent = await mp.send_mail(email, "Celesta Glow — verify your email",
                              f"Your verification code is {code}. It expires in 10 minutes.",
                              f"<h2 style='font-family:sans-serif'>Verification code: <b>{code}</b></h2><p>Valid 10 minutes.</p>")
    return {"success": True, "email_sent": sent, "dev_otp": None if sent else code}


class ProviderVerifyIn(BaseModel):
    role: str
    email: str
    otp: str


@router.post("/provider/verify-email")
async def provider_verify_email(body: ProviderVerifyIn):
    email = body.email.lower()
    rec = await Db.mp_otps.find_one({"email": email, "role": body.role})
    if not rec or rec.get("expires_at", "") < mp.now():
        raise HTTPException(400, "Code expired — request a new one")
    if (rec.get("attempts") or 0) >= 5:
        raise HTTPException(429, "Too many attempts — request a new code")
    if rec.get("otp_hash") != mp.hash_otp(body.otp):
        await Db.mp_otps.update_one({"_id": rec["_id"]}, {"$inc": {"attempts": 1}})
        raise HTTPException(400, "Incorrect code")
    acc = await Db.mp_accounts.find_one({"role": body.role, "email": email})
    if not acc:
        raise HTTPException(404, "Register first")
    await Db.mp_accounts.update_one({"_id": acc["_id"]}, {"$set": {"email_verified": True}})
    import secrets as _s
    import datetime as _dt
    token = _s.token_hex(24)
    await Db.mp_sessions.insert_one({"token": token, "account_id": acc.get("account_id"), "role": body.role,
                                     "expires_at": (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=14)).isoformat()})
    await Db.mp_otps.delete_one({"_id": rec["_id"]})
    return {"success": True, "token": token, "role": body.role}


async def _account_from_token(authorization: Optional[str]) -> Dict[str, Any]:
    token = (authorization or "").split()[-1] if authorization else ""
    sess = await Db.mp_sessions.find_one({"token": token})
    if not sess or sess.get("expires_at", "") < mp.now():
        raise HTTPException(401, "Session expired — log in again")
    acc = await Db.mp_accounts.find_one({"account_id": sess["account_id"]}, {"_id": 0})
    if not acc:
        raise HTTPException(401, "Account not found")
    return acc


@router.get("/provider/status")
async def provider_status(authorization: str = Header(None)):
    acc = await _account_from_token(authorization)
    coll = Db.mp_doctors if acc["role"] == "doctor" else Db.mp_partners
    email_key = "personal.email" if acc["role"] == "doctor" else "applicant.email"
    app = await coll.find_one({email_key: acc["email"]}, {"_id": 0})
    application = None
    if app:
        application = {
            "id": app.get("doctor_id") or app.get("partner_id"),
            "status": app["application_status"],
            "submitted_at": app.get("created_at"),
            "decisions": (app.get("decisions") or [])[-3:],
        }
    return {"role": acc["role"], "email": acc["email"], "name": acc.get("name"),
            "email_verified": bool(acc.get("email_verified")),
            "application": application,
            "approved": bool(app and app["application_status"] == "approved"),
            "dashboard": f"/{acc['role']}"}


@router.post("/provider/apply")
async def provider_apply_authed(body: Dict[str, Any], authorization: str = Header(None)):
    acc = await _account_from_token(authorization)
    if not acc.get("email_verified"):
        raise HTTPException(403, "Verify your email first")
    cfg = await mp.cfg()
    if acc["role"] == "doctor":
        if not cfg["dermatologist_enabled"]:
            raise HTTPException(403, "Dermatologist onboarding is currently closed")
        app = DoctorApplication(**{**body, "email": acc["email"], "name": body.get("name") or acc.get("name") or "",
                                   "mobile": body.get("mobile") or acc.get("mobile") or ""})
        existing = await Db.mp_doctors.find_one({"personal.email": acc["email"],
                                                 "application_status": {"$in": ["pending", "approved", "info_requested"]}})
        if existing:
            raise HTTPException(409, "Application already submitted")
        if not app.registration_number:
            raise HTTPException(400, "Medical registration number is required")
        doc = {
            "doctor_id": mp.uid("doc"), "application_status": "pending", "active": False,
            "personal": {"name": app.name, "mobile": app.mobile, "email": acc["email"],
                         "address": app.address, "city": app.city, "state": app.state, "pincode": app.pincode,
                         "lat": getattr(app, "lat", None), "lng": getattr(app, "lng", None)},
            "professional": {"qualification": app.qualification, "institution": app.institution,
                             "graduation_year": app.graduation_year, "postgrad": app.postgrad,
                             "specialisation": app.specialisation, "experience_years": app.experience_years,
                             "bio": app.bio, "registration_number": app.registration_number,
                             "issuing_authority": app.issuing_authority,
                         "specialties": app.specialties},
            "consultation": {"fee": app.fee, "duration_min": app.duration_min, "weekly_slots": app.weekly_slots,
                             "languages": app.languages, "video_enabled": app.video_enabled,
                             "followup_policy": app.followup_policy},
            "documents": [], "photo": {}, "decisions": [], "created_at": mp.now(),
        }
        await Db.mp_doctors.insert_one(doc)
        await Db.mp_accounts.update_one({"account_id": acc["account_id"]}, {"$set": {"ref_id": doc["doctor_id"]}})
        await mp.notify("admin", "all", "New dermatologist application", f"{app.name} applied", "/admin/doctors-crm")
        return {"success": True, "application_id": doc["doctor_id"], "status": "pending"}
    if not cfg["home_services_enabled"]:
        raise HTTPException(403, "Partner onboarding is currently closed")
    app = PartnerApplication(**{**body, "email": acc["email"], "name": body.get("name") or acc.get("name") or "",
                                "mobile": body.get("mobile") or acc.get("mobile") or ""})
    if not app.services:
        raise HTTPException(400, "Select at least one service from the catalogue")
    existing = await Db.mp_partners.find_one({"applicant.email": acc["email"],
                                              "application_status": {"$in": ["pending", "approved", "info_requested"]}})
    if existing:
        raise HTTPException(409, "Application already submitted")
    valid = []
    for sel in app.services:
        svc = await Db.mp_services.find_one({"service_id": sel.service_id, "status": "active"}, {"_id": 0})
        if not svc:
            raise HTTPException(400, f"Service {sel.service_id} is not an active catalogue service")
        price = sel.price if sel.price is not None else svc.get("price")
        if price is None or float(price) <= 0:
            raise HTTPException(400, f"Set your price for {svc['name']}")
        valid.append({"service_id": sel.service_id, "service_name": svc["name"], "mode": sel.mode,
                      "price": price, "coverage": sel.coverage, "qualifications": sel.qualifications,
                      "approval_status": "pending"})
    doc = {
        "partner_id": mp.uid("prt"), "application_status": "pending", "active": False, "paused": False,
        "applicant": {"name": app.name, "mobile": app.mobile, "email": acc["email"],
                      "business_name": app.business_name, "applicant_type": app.applicant_type,
                      "id_proof": app.id_proof, "qualifications": app.qualifications},
        "staff": _staff(app), "availability": app.availability,
        "location": {"address": app.address, "city": app.city, "state": app.state, "pincode": app.pincode,
                     "lat": app.lat, "lng": app.lng, "coverage_area": app.coverage_area},
        "payout": {"account_holder": app.account_holder, "bank_account": app.bank_account,
                   "ifsc": app.ifsc, "upi": app.upi},
        "services": valid, "documents": [], "decisions": [], "created_at": mp.now(),
    }
    await Db.mp_partners.insert_one(doc)
    await Db.mp_accounts.update_one({"account_id": acc["account_id"]}, {"$set": {"ref_id": doc["partner_id"]}})
    await mp.notify("admin", "all", "New service partner application", f"{app.name} applied", "/admin/partners-crm")
    return {"success": True, "application_id": doc["partner_id"], "status": "pending"}


# ------------------------------------------------------- admin: pricing overrides + custom services
@router.put("/admin/doctors/{doctor_id}/fee")
async def admin_doctor_fee(doctor_id: str, body: Dict[str, float], x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    fee = float(body.get("fee") or 0)
    if fee <= 0:
        raise HTTPException(400, "Fee must be positive")
    res = await Db.mp_doctors.update_one({"doctor_id": doctor_id}, {"$set": {"consultation.fee": fee}})
    if not res.matched_count:
        raise HTTPException(404, "Doctor not found")
    await mp.audit("admin", "doctor_fee", "doctor", doctor_id, new=fee)
    return {"success": True, "fee": fee, "pricing": mp.price_view(fee, await mp.cfg())}


@router.put("/admin/partners/{partner_id}/services/{service_id}/price")
async def admin_partner_service_price(partner_id: str, service_id: str, body: Dict[str, float],
                                      x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    price = float(body.get("price") or 0)
    if price <= 0:
        raise HTTPException(400, "Price must be positive")
    res = await Db.mp_partners.update_one({"partner_id": partner_id, "services.service_id": service_id},
                                          {"$set": {"services.$.price": price}})
    if not res.matched_count:
        raise HTTPException(404, "Partner service not found")
    await mp.audit("admin", "partner_service_price", "partner", partner_id, new={service_id: price})
    return {"success": True, "price": price}


@router.get("/admin/pricing-preview")
async def admin_pricing_preview(base: float = 1000, x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    return mp.price_view(base, await mp.cfg())


@router.get("/admin/custom-services")
async def admin_custom_services(status: str = "", x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    q: Dict[str, Any] = {"created_by": {"$exists": True}}
    if status:
        q["status"] = status
    return await Db.mp_services.find(q, {"_id": 0}).sort("created_at", -1).to_list(300)


@router.post("/admin/custom-services/{service_id}/decision")
async def admin_custom_service_decision(service_id: str, body: Dict[str, str], x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    decision = body.get("decision")
    if decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision must be approved|rejected")
    svc = await Db.mp_services.find_one({"service_id": service_id, "created_by": {"$exists": True}}, {"_id": 0})
    if not svc:
        raise HTTPException(404, "Custom service not found")
    if decision == "approved" and not (svc.get("thumbnail") or svc.get("images")):
        raise HTTPException(400, "Add an image before approving")
    await Db.mp_services.update_one({"service_id": service_id}, {"$set": {
        "status": "active" if decision == "approved" else "rejected", "review_note": body.get("reason", ""),
        "updated_at": mp.now()}})
    await Db.mp_partners.update_one({"partner_id": svc["created_by"], "services.service_id": service_id},
                                    {"$set": {"services.$.approval_status": decision}})
    await mp.notify("partner", svc["created_by"], f"Custom service {decision}",
                    f"{svc['name']} was {decision}. {body.get('reason', '')}", "/partner")
    await mp.audit("admin", f"custom_service:{decision}", "service", service_id)
    return {"success": True, "status": decision}


class AnnounceIn(BaseModel):
    audience: str  # doctor | partner
    title: str
    body: str


@router.post("/admin/announcements")
async def admin_announce(body: AnnounceIn, x_admin_token: str = Header(None)):
    """Push an update/notice to every approved doctor or partner (shows in their app notifications)."""
    await _check_admin(x_admin_token)
    if body.audience not in ("doctor", "partner") or not body.title.strip():
        raise HTTPException(400, "Audience and title are required")
    coll, key = (Db.mp_doctors, "doctor_id") if body.audience == "doctor" else (Db.mp_partners, "partner_id")
    ids = [d[key] for d in await coll.find({"application_status": "approved"}, {"_id": 0, key: 1}).to_list(2000)]
    for i in ids:
        await mp.notify(body.audience, i, body.title.strip(), body.body.strip(), f"/{body.audience}")
    doc = {"ann_id": mp.uid("ann"), "audience": body.audience, "title": body.title.strip(), "body": body.body.strip(),
           "recipients": len(ids), "at": mp.now()}
    await Db.mp_announcements.insert_one(doc)
    doc.pop("_id", None)
    return doc


@router.get("/admin/announcements")
async def admin_announcements(audience: str = "", x_admin_token: str = Header(None)):
    await _check_admin(x_admin_token)
    return await Db.mp_announcements.find({"audience": audience} if audience else {}, {"_id": 0}).sort("at", -1).to_list(100)

"""Marketplace operations: bookings, payments, OTP completion, live tracking,
prescriptions, wallets, video rooms, notifications, support tickets."""
import base64
import datetime as dt
import io
import logging
import os
import secrets
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from services import mp_common as mp

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mp", tags=["marketplace-ops"])

Db = None


def setup(db, verify_admin_token=None, razorpay_client=None):
    global Db
    Db = db
    mp.setup(db, verify_admin_token, razorpay_client)


SLOT_DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


# ================================================================ helpers
async def broadcast_offers(booking: Dict[str, Any], online_only: bool = False, expiry_minutes: Optional[int] = None):
    if booking.get("target_partner_id"):
        return await _broadcast(booking, online_only, expiry_minutes, booking["target_partner_id"])
    return await _broadcast(booking, online_only, expiry_minutes, None)


async def _broadcast(booking: Dict[str, Any], online_only: bool, expiry_minutes: Optional[int], target: Optional[str]):
    """Offer a home-service booking to every eligible partner (first-accept wins).
    online_only=True restricts dispatch to partners who are online right now (instant bookings)."""
    svc = await Db.mp_services.find_one({"service_id": booking["service_id"]}, {"_id": 0})
    partners = await Db.mp_partners.find(
        {"application_status": "approved", "active": True, "paused": {"$ne": True},
         "services": {"$elemMatch": {"service_id": booking["service_id"], "approval_status": "approved"}},
         **({"partner_id": target} if target else {})},
        {"_id": 0}).to_list(200)
    if online_only:
        partners = [p for p in partners if mp.is_online(p)]
    partners = [p for p in partners if _gender_ok(p, booking.get("staff_gender") or "any")]
    cfg = await mp.cfg()
    partners = [p for p in partners if _within(p, booking.get("customer") or {}, float(cfg.get("service_radius_km", 10)))]
    minutes = expiry_minutes or cfg.get("offer_expiry_minutes", 5)
    expiry = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes)).isoformat()
    count = 0
    for p in partners:
        already = await Db.mp_booking_offers.find_one({"booking_id": booking["booking_id"], "partner_id": p["partner_id"]})
        if already:
            continue
        sel = next((s for s in p.get("services", []) if s["service_id"] == booking["service_id"]), {})
        await Db.mp_booking_offers.insert_one({
            "booking_id": booking["booking_id"], "partner_id": p["partner_id"],
            "expires_at": expiry, "status": "pending",
            "expected_earnings": booking.get("provider_earning") or round((sel.get("price") or booking.get("price", 0)) * (1 - cfg.get("platform_commission_pct", 15) / 100), 2),
            "created_at": mp.now()})
        await mp.notify("partner", p["partner_id"], "New booking request",
                        f"{booking.get('service_name')} on {booking.get('date')} {booking.get('slot')}",
                        "/partner")
        await mp.send_mail(p["applicant"]["email"], "Celesta Glow — new booking request",
                           f"You have a new request for {booking.get('service_name')} on {booking.get('date')} at {booking.get('slot')}. "
                           f"Open your partner dashboard to accept it first.")
        count += 1
    return count


async def _create_completion_otp(coll, booking_id: str, customer_email: str, label: str):
    code = mp.otp_code()
    await coll.update_one({"booking_id": booking_id}, {"$set": {
        "otp": {"hash": mp.hash_otp(code),
                "expires_at": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=30)).isoformat(),
                "attempts": 0, "used": False},
        "status": "completion_pending", "updated_at": mp.now()}})
    sent = await mp.send_mail(customer_email, f"Celesta Glow — {label} completion code",
                              f"Your {label} completion code is {code}. Share it only when you are satisfied. Valid 30 minutes.",
                              f"<h2 style='font-family:sans-serif'>Completion code: <b>{code}</b></h2>"
                              f"<p>Share this with your provider only after the {label} is complete. Valid 30 minutes.</p>")
    if not sent:
        logger.info(f"[mp] email NOT configured — completion code for {booking_id}: {code}")
    await mp.notify("customer", customer_email, f"{label} completion code sent",
                    "Check your email for the verification code.", "/my/bookings")
    return sent


async def _verify_completion_otp(coll, booking_id: str, code: str, actor: str) -> Dict[str, Any]:
    b = await coll.find_one({"booking_id": booking_id}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking not found")
    otp = b.get("otp") or {}
    if otp.get("used"):
        raise HTTPException(400, "This booking was already verified")
    if b.get("status") != "completion_pending":
        raise HTTPException(400, "Booking is not awaiting completion verification")
    if (otp.get("attempts") or 0) >= 5:
        raise HTTPException(429, "Too many attempts — contact support")
    if otp.get("expires_at", "") < mp.now():
        raise HTTPException(400, "Code expired — ask support for a new one")
    if otp.get("hash") != mp.hash_otp(code):
        await coll.update_one({"booking_id": booking_id}, {"$inc": {"otp.attempts": 1}})
        raise HTTPException(400, "Incorrect code")
    await coll.update_one({"booking_id": booking_id}, {"$set": {
        "status": "completed", "otp.used": True, "completed_at": mp.now(), "verified_by": actor, "updated_at": mp.now()}})
    return b


async def _settle(booking: Dict[str, Any], kind: str):
    """Ledger settlement after verified completion. Provider gets listed price minus commission;
    platform keeps the rest (commission + customer markup). Every entry carries a breakdown."""
    cfg = await mp.cfg()
    if await Db.mp_wallet_ledger.find_one({"booking_id": booking["booking_id"], "type": "credit", "ref": "settlement"}):
        return
    comm = cfg.get("platform_commission_pct", 15)
    if kind == "consultation":
        owner_type, owner_id = "doctor", booking["doctor_id"]
        paid = float(booking.get("fee", 0))
        base = float(booking.get("base_fee") or paid)
    else:
        owner_type, owner_id = "partner", booking["partner_id"]
        paid = float(booking.get("total_amount") or booking.get("price", 0))
        base = float(booking.get("price", 0))
    earning = float(booking.get("provider_earning") or round(base * (1 - comm / 100), 2))
    meta = {"customer_paid": paid, "listed_price": base, "commission_pct": booking.get("commission_pct", comm),
            "commission": round(base - earning, 2), "you_earn": earning,
            "partner_commission": round(base - earning, 2), "customer_commission": round(paid - base, 2),
            "platform_total": round(paid - earning, 2)}
    platform = round(paid - earning, 2)
    if kind == "home" and booking.get("payment_method") == "pay_after_service":
        meta["note"] = "Cash collected by you — platform commission owed is deducted from your wallet"
        if platform > 0:
            await mp.wallet_move(owner_type, owner_id, platform, "debit", "commission due (cash booking)",
                                 booking["booking_id"], meta, allow_negative=True)
            await mp.wallet_move("platform", "main", platform, "credit", "Celesta commission (cash booking — receivable)",
                                 booking["booking_id"], meta)
    else:
        if earning > 0:
            await mp.wallet_move(owner_type, owner_id, earning, "credit", "settlement", booking["booking_id"], meta)
        if platform > 0:
            await mp.wallet_move("platform", "main", platform, "credit", f"Celesta commission ({meta['commission_pct']:.0f}% + markup)",
                                 booking["booking_id"], meta)
    await mp.notify(owner_type, owner_id, "Booking completed",
                    f"Booking {booking['booking_id']} settled — ₹{earning} credited.", "/doctor" if kind == "consultation" else "/partner")


async def on_consult_confirmed(b: Dict[str, Any]):
    """Paid consultation: create video meeting, email + notify doctor and customer."""
    from services import zoom_service
    upd: Dict[str, Any] = {}
    if not b.get("zoom") and zoom_service.configured():
        start = None
        if b.get("slot") and b.get("slot") != "Instant":
            start = f"{b['date']}T{b['slot']}:00"
        z = await zoom_service.create_meeting(f"Celesta Glow consultation {b['booking_id']}", start, 30)
        if z:
            upd["zoom"] = z
    if upd:
        await Db.mp_consultations.update_one({"booking_id": b["booking_id"]}, {"$set": upd})
    d = await Db.mp_doctors.find_one({"doctor_id": b.get("doctor_id")}, {"_id": 0, "personal": 1}) if b.get("doctor_id") else None
    when = f"{b.get('date')} at {b.get('slot')}"
    if d:
        await mp.send_mail(d["personal"]["email"], f"New paid consultation [{b['booking_id']}]",
                           f"Dr. {d['personal']['name']}, {b['customer']['name']} booked and paid for a consultation on {when}. "
                           f"Open your doctor dashboard to join the call.")
        await mp.notify("doctor", b["doctor_id"], "New paid consultation", f"{b['customer']['name']} — {when}", "/doctor")
    await mp.send_mail(b["customer"]["email"], f"Consultation confirmed [{b['booking_id']}]",
                       f"Your consultation with Dr. {b.get('doctor_name') or 'your dermatologist'} on {when} is confirmed. "
                       f"Use 'Call doctor' in My Bookings at your slot time.")


# ================================================================ customer bookings
class ConsultBookIn(BaseModel):
    doctor_id: str
    date: str
    slot: str
    name: str
    email: str
    phone: str


@router.post("/consultations/book")
async def book_consultation(body: ConsultBookIn):
    cfg = await mp.cfg()
    if not cfg["dermatologist_enabled"]:
        raise HTTPException(403, "Dermatologist consultations are temporarily unavailable")
    d = await Db.mp_doctors.find_one({"doctor_id": body.doctor_id, "application_status": "approved", "active": True}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Doctor not available")
    lock_key = f"consult:{body.doctor_id}:{body.date}:{body.slot}"
    try:
        await Db.mp_slot_locks.insert_one({"key": lock_key, "at": mp.now()})
    except Exception:
        raise HTTPException(409, "This slot was just taken — pick another")
    booking_id = mp.uid("cns").upper().replace("CNS_", "CG-C-")
    cfg_ = await mp.cfg()
    pv = mp.price_view((d.get("consultation") or {}).get("fee", 0), cfg_, body.doctor_id)
    fee = pv["price"]
    booking = {
        "base_fee": pv["base"], "provider_earning": pv["provider_earning"], "platform_earning": pv["platform_earning"],
        "commission_pct": cfg_.get("platform_commission_pct", 15), "mrp": pv["mrp"],
        "booking_id": booking_id, "doctor_id": body.doctor_id,
        "doctor_name": d["personal"]["name"], "date": body.date, "slot": body.slot,
        "customer": {"name": body.name, "email": body.email.lower(), "phone": body.phone},
        "fee": fee, "status": "pending_payment", "payment_status": "unpaid",
        "room_secret": secrets.token_hex(4), "created_at": mp.now(), "updated_at": mp.now(),
    }
    rz = mp.razorpay()
    if rz is not None:
        try:
            order = rz.order.create({"amount": int(fee * 100), "currency": "INR",
                                     "receipt": booking_id, "payment_capture": 1})
            booking["razorpay_order_id"] = order["id"]
        except Exception as exc:
            logger.error(f"[mp] razorpay order failed: {exc}")
            await Db.mp_slot_locks.delete_one({"key": lock_key})
            raise HTTPException(502, "Payment gateway error — please try again")
    await Db.mp_consultations.insert_one(booking)
    booking.pop("_id", None)
    return {"success": True, "booking": booking, "payments_configured": rz is not None,
            "message": None if rz is not None else
            "Your slot is held. Consultations are prepaid — it confirms as soon as payment is received."}


class ConsultVerifyIn(BaseModel):
    booking_id: str
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


@router.post("/consultations/verify-payment")
async def verify_consult_payment(body: ConsultVerifyIn):
    rz = mp.razorpay()
    if rz is None:
        raise HTTPException(503, "Payments are not configured")
    b = await Db.mp_consultations.find_one({"booking_id": body.booking_id}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking not found")
    try:
        rz.utility.verify_payment_signature({
            "razorpay_order_id": body.razorpay_order_id,
            "razorpay_payment_id": body.razorpay_payment_id,
            "razorpay_signature": body.razorpay_signature})
    except Exception:
        raise HTTPException(400, "Payment signature verification failed")
    await Db.mp_consultations.update_one({"booking_id": body.booking_id}, {"$set": {
        "status": "confirmed" if b.get("type") != "instant" else "pending_assignment",
        "payment_status": "paid", "razorpay_payment_id": body.razorpay_payment_id,
        "updated_at": mp.now()}})
    if b.get("type") == "instant":
        notified = await _dispatch_instant(b)
        if notified == 0:
            await mp.notify("customer", b["customer"]["email"], "Finding your doctor",
                            "Payment received — no doctor is online right now; your request is queued.", "/my/bookings")
        return {"success": True, "status": "pending_assignment", "dispatched": notified}
    await on_consult_confirmed(b)
    return {"success": True, "status": "confirmed"}


class HomeBookIn(BaseModel):
    service_id: str
    date: str = ""
    slot: str = ""
    name: str
    email: str
    phone: str
    address: str
    city: str = ""
    pincode: str = ""
    lat: Optional[float] = None
    lng: Optional[float] = None
    notes: str = ""
    instant: bool = False
    payment_method: str = "online"  # online | pay_after_service
    partner_id: Optional[str] = None
    staff_gender: str = "any"  # female | male | any


def _within(p: Dict[str, Any], cust: Dict[str, Any], radius: float) -> bool:
    loc = p.get("location") or {}
    if not (cust.get("lat") and cust.get("lng") and loc.get("lat") and loc.get("lng")):
        return True
    return mp.haversine_km(cust["lat"], cust["lng"], loc["lat"], loc["lng"]) <= radius


def _gender_ok(p: Dict[str, Any], gender: str) -> bool:
    staff = p.get("staff") or {}
    if gender == "female":
        return int(staff.get("female") or 0) > 0
    if gender == "male":
        return not staff or int(staff.get("male") or 0) > 0
    return True


@router.post("/home/book")
async def book_home_service(body: HomeBookIn):
    cfg = await mp.cfg()
    if not cfg["home_services_enabled"]:
        raise HTTPException(403, "Home services are temporarily unavailable")
    svc = await Db.mp_services.find_one({"service_id": body.service_id, "status": "active"}, {"_id": 0})
    if not svc:
        raise HTTPException(404, "Service not available for new bookings")
    booking_id = mp.uid("hms").upper().replace("HMS_", "CG-H-")
    date = body.date or dt.datetime.now(dt.timezone.utc).date().isoformat()
    slot = body.slot or "ASAP"
    pq: Dict[str, Any] = {"application_status": "approved", "active": True, "paused": {"$ne": True},
                          "services": {"$elemMatch": {"service_id": body.service_id, "approval_status": "approved"}}}
    if body.partner_id:
        pq["partner_id"] = body.partner_id
    gender = body.staff_gender if body.staff_gender in ("female", "male") else "any"
    plist = await Db.mp_partners.find(pq, {"_id": 0, "partner_id": 1, "services.$": 1, "staff": 1, "location": 1}).to_list(100)
    if body.partner_id and not plist:
        raise HTTPException(404, "This professional is not available for this service")
    plist = [p for p in plist if _gender_ok(p, gender)
             and _within(p, {"lat": body.lat, "lng": body.lng}, float(cfg.get("service_radius_km", 10)))]
    if body.partner_id and not plist:
        raise HTTPException(409, f"This professional is outside the {cfg.get('service_radius_km', 10):g} km service area for your address")
    if not plist and gender != "any":
        raise HTTPException(409, f"No partner with {gender} staff is available for this service yet — try another option.")
    bases = [p["services"][0].get("price") for p in plist if p.get("services") and p["services"][0].get("price")]
    seed = f"{body.partner_id}:{body.service_id}" if body.partner_id else body.service_id
    pv = mp.price_view(min(bases) if bases else svc.get("price", 0), cfg, seed)
    price = pv["base"]
    fee_amount = pv["platform_earning"]
    total = pv["price"]
    method = body.payment_method if body.payment_method in ("online", "pay_after_service") else "online"
    rz = mp.razorpay()
    pay_online = method == "online" and rz is not None
    booking = {
        "booking_id": booking_id, "service_id": body.service_id, "service_name": svc["name"],
        "type": "instant" if body.instant else "scheduled",
        "partner_id": None, "partner_name": None, "date": date, "slot": slot,
        "customer": {"name": body.name, "email": body.email.lower(), "phone": body.phone,
                     "address": body.address, "city": body.city, "pincode": body.pincode,
                     "lat": body.lat, "lng": body.lng},
        "notes": body.notes, "price": price, "fee_amount": fee_amount, "total_amount": total,
        "provider_earning": pv["provider_earning"], "platform_earning": pv["platform_earning"], "mrp": pv["mrp"],
        "commission_pct": cfg.get("platform_commission_pct", 15), "target_partner_id": body.partner_id,
        "duration_min": svc.get("duration_min", 60), "payment_method": method, "staff_gender": gender,
        "status": "pending_payment" if pay_online else "pending_assignment",
        "payment_status": "unpaid",
        "tracking": {}, "timeline": [{"status": "created", "at": mp.now()}],
        "created_at": mp.now(), "updated_at": mp.now(),
    }
    if pay_online:
        try:
            order = rz.order.create({"amount": int(total * 100), "currency": "INR",
                                     "receipt": booking_id, "payment_capture": 1})
            booking["razorpay_order_id"] = order["id"]
        except Exception as exc:
            logger.error(f"[mp] razorpay order failed: {exc}")
            raise HTTPException(502, "Payment gateway error — please try again")
    await Db.mp_home_bookings.insert_one(booking)
    offered = 0
    if not pay_online:
        offered = await broadcast_offers({**booking, "service_name": svc["name"]},
                                         online_only=body.instant,
                                         expiry_minutes=3 if body.instant else None)
    booking.pop("_id", None)
    return {"success": True, "booking": booking, "partners_notified": offered,
            "payments_configured": rz is not None,
            "message": ("Complete payment to confirm your booking."
                        if pay_online else
                        "Booking confirmed — pay after the service. Partners are being notified.")}


@router.post("/home/verify-payment")
async def verify_home_payment(body: ConsultVerifyIn):
    rz = mp.razorpay()
    if rz is None:
        raise HTTPException(503, "Payments are not configured")
    b = await Db.mp_home_bookings.find_one({"booking_id": body.booking_id}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking not found")
    try:
        rz.utility.verify_payment_signature({
            "razorpay_order_id": body.razorpay_order_id,
            "razorpay_payment_id": body.razorpay_payment_id,
            "razorpay_signature": body.razorpay_signature})
    except Exception:
        raise HTTPException(400, "Payment signature verification failed")
    await Db.mp_home_bookings.update_one({"booking_id": body.booking_id}, {"$set": {
        "status": "pending_assignment", "payment_status": "paid",
        "razorpay_payment_id": body.razorpay_payment_id, "updated_at": mp.now()},
        "$push": {"timeline": {"status": "paid", "at": mp.now()}}})
    offered = await broadcast_offers({**b, "status": "pending_assignment"},
                                     online_only=b.get("type") == "instant",
                                     expiry_minutes=3 if b.get("type") == "instant" else None)
    return {"success": True, "status": "pending_assignment", "partners_notified": offered}


# --------------------------------------------------------------- customer views
@router.get("/my/bookings")
async def my_bookings(authorization: str = Header(None)):
    cust = await mp.current_customer(authorization)
    if not cust or not cust.get("email"):
        raise HTTPException(401, "Log in to view your bookings")
    email = cust["email"]
    consults = await Db.mp_consultations.find({"customer.email": email}, {"_id": 0, "otp": 0}).sort("created_at", -1).to_list(100)
    homes = await Db.mp_home_bookings.find({"customer.email": email}, {"_id": 0, "otp": 0}).sort("created_at", -1).to_list(100)
    rx = await Db.mp_prescriptions.find({"customer_email": email, "status": "final"}, {"_id": 0}).sort("finalized_at", -1).to_list(100)
    notifs = await Db.mp_notifications.find({"audience_type": "customer", "audience_ref": email}, {"_id": 0}).sort("at", -1).to_list(50)
    return {"consultations": consults, "home_bookings": homes, "prescriptions": rx, "notifications": notifs,
            "customer": cust}


@router.get("/my/notifications/read-all")
async def my_notifs_read(authorization: str = Header(None)):
    cust = await mp.current_customer(authorization)
    if cust and cust.get("email"):
        await Db.mp_notifications.update_many({"audience_type": "customer", "audience_ref": cust["email"]},
                                              {"$set": {"read": True}})
    return {"success": True}


@router.get("/bookings/{booking_id}/tracking")
async def get_tracking(booking_id: str, authorization: str = Header(None)):
    b = await Db.mp_home_bookings.find_one({"booking_id": booking_id}, {"_id": 0, "otp": 0})
    if not b:
        raise HTTPException(404, "Booking not found")
    tr = b.get("tracking") or {}
    stale = True
    if tr.get("at"):
        try:
            stale = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(tr["at"])).total_seconds() > 120
        except Exception:
            stale = True
    return {
        "booking_id": booking_id, "status": b["status"], "service_name": b.get("service_name"),
        "partner_name": b.get("partner_name"), "date": b.get("date"), "slot": b.get("slot"),
        "customer_email": b["customer"]["email"],
        "tracking_active": b["status"] == "en_route" and bool(tr.get("sharing")),
        "lat": tr.get("lat"), "lng": tr.get("lng"), "last_update": tr.get("at"),
        "stale": stale, "eta_minutes": tr.get("eta_minutes"),
    }


@router.get("/consultations/{booking_id}/room")
async def consult_room(booking_id: str, authorization: str = Header(None), email: str = ""):
    b = await Db.mp_consultations.find_one({"booking_id": booking_id}, {"_id": 0, "otp": 0})
    if not b:
        raise HTTPException(404, "Booking not found")
    token = (authorization or "").split()[-1] if authorization else ""
    allowed = False
    role = "guest"
    if email and email.lower() == b["customer"]["email"]:
        allowed, role = True, "customer"
    cust = await mp.current_customer(authorization)
    if cust and cust.get("email") == b["customer"]["email"]:
        allowed, role = True, "customer"
    if not allowed and token:
        sess = await Db.mp_sessions.find_one({"token": token, "role": "doctor"})
        if sess:
            acc = await Db.mp_accounts.find_one({"account_id": sess["account_id"]}, {"_id": 0})
            if acc and acc.get("ref_id") == b["doctor_id"]:
                allowed, role = True, "doctor"
    if not allowed:
        raise HTTPException(403, "Only the booked customer and doctor can join this room")
    if b["status"] not in ("confirmed", "in_progress", "completion_pending", "completed"):
        raise HTTPException(400, f"Consultation is {b['status']} — the room opens for confirmed bookings")
    from services import agora_service
    # Default to free Jitsi (no keys, works everywhere). Set VIDEO_PROVIDER=agora
    # to use Agora once valid production credentials are in place.
    video_provider = os.environ.get("VIDEO_PROVIDER", "jitsi").lower()
    if video_provider == "agora" and agora_service.configured():
        uid_ = 1001 if role == "doctor" else 2002
        channel = f"cg_{booking_id.lower()}_{b.get('room_secret', '')}"
        return {"provider": "agora", **agora_service.rtc_token(channel, uid_),
                "booking_id": booking_id, "doctor_name": b.get("doctor_name"), "customer_name": b["customer"]["name"],
                "date": b.get("date"), "slot": b.get("slot"), "status": b["status"], "role": role}
    z = b.get("zoom") or {}
    if z.get("join_url"):
        return {"provider": "zoom", "join_url": z["start_url"] if role == "doctor" and z.get("start_url") else z["join_url"],
                "web_url": f"https://app.zoom.us/wc/join/{z['meeting_id']}?pwd={z.get('password', '')}",
                "booking_id": booking_id, "doctor_name": b.get("doctor_name"), "date": b.get("date"),
                "slot": b.get("slot"), "status": b["status"], "role": role}
    return {"provider": "jitsi", "domain": "meet.jit.si",
            "room": f"celestaglow-{booking_id.lower()}-{b.get('room_secret', '')}",
            "booking_id": booking_id, "doctor_name": b.get("doctor_name"),
            "date": b.get("date"), "slot": b.get("slot"), "status": b["status"], "role": role,
            "note": "Rooms are unguessable and access-gated; join at your appointment time."}


# ================================================================ doctor portal
async def _doctor(authorization: str) -> Dict[str, Any]:
    acc = await mp.require_account(authorization, "doctor")
    d = await Db.mp_doctors.find_one({"doctor_id": acc["ref_id"]}, {"_id": 0})
    if not d:
        raise HTTPException(404, "Doctor profile not found")
    return d


@router.get("/doctor/profile")
async def doctor_profile(authorization: str = Header(None)):
    d = await _doctor(authorization)
    d.pop("decisions", None)
    return d


class DoctorProfileUpdate(BaseModel):
    fee: Optional[float] = None
    duration_min: Optional[int] = None
    weekly_slots: Optional[Dict[str, List[str]]] = None
    languages: Optional[List[str]] = None
    bio: Optional[str] = None
    followup_policy: Optional[str] = None
    video_enabled: Optional[bool] = None


@router.put("/doctor/profile")
async def doctor_update(body: DoctorProfileUpdate, authorization: str = Header(None)):
    d = await _doctor(authorization)
    updates: Dict[str, Any] = {}
    for k in ("fee", "duration_min", "weekly_slots", "languages", "followup_policy", "video_enabled"):
        v = getattr(body, k)
        if v is not None:
            updates[f"consultation.{k}"] = v
    if body.bio is not None:
        updates["professional.bio"] = body.bio
    if updates:
        await Db.mp_doctors.update_one({"doctor_id": d["doctor_id"]}, {"$set": updates})
    return {"success": True}


@router.post("/doctor/photo")
async def doctor_upload_photo(file: UploadFile = File(...), authorization: str = Header(None)):
    d = await _doctor(authorization)
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "Photo must be under 8MB")
    if (file.content_type or "") not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(400, "Only JPG, PNG or WebP photos are allowed")
    ext = (file.filename or "photo.jpg").rsplit(".", 1)[-1].lower()
    url = await mp.store_image(data, f"doc-{d['doctor_id']}-orig-{secrets.token_hex(3)}", ext)
    photo = d.get("photo") or {}
    photo.update({"original_url": url, "status": "uploaded", "processed": None, "chosen": None,
                  "uploaded_at": mp.now()})
    await Db.mp_doctors.update_one({"doctor_id": d["doctor_id"]}, {"$set": {"photo": photo}})
    return {"success": True, "photo": photo}


@router.post("/doctor/photo/process")
async def doctor_process_photo(authorization: str = Header(None)):
    d = await _doctor(authorization)
    photo = d.get("photo") or {}
    orig = photo.get("original_url")
    if not orig:
        raise HTTPException(400, "Upload a photo first")
    key = mp.emergent_key()
    if not key:
        raise HTTPException(503, "AI photo processing is not configured (EMERGENT_LLM_KEY missing). "
                                 "Your original photo is safe — ask support for a manual review.")
    try:
        if orig.startswith("/api/mp/media/"):
            raw = (mp.UPLOAD_DIR / orig.rsplit("/", 1)[-1]).read_bytes()
        else:
            import httpx
            raw = (await httpx.AsyncClient(timeout=60).get(orig)).content
        from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
        chat = LlmChat(api_key=key, session_id=f"photo-{d['doctor_id']}-{secrets.token_hex(3)}",
                       system_message="You are a professional photo editor.")
        chat.with_model("gemini", "gemini-3.1-flash-image-preview").with_params(modalities=["image", "text"])
        msg = UserMessage(
            text=("Edit this photograph: replace the background with a pure white studio background. "
                  "Keep the exact same person — identical face, skin tone, texture and expression. "
                  "Crop to a centered head-and-shoulders professional portrait. Natural lighting, realistic. "
                  "Do NOT add medical coats, badges, text or any objects that are not in the original."),
            file_contents=[ImageContent(base64.b64encode(raw).decode())])
        _, images = await chat.send_message_multimodal_response(msg)
        if not images:
            raise RuntimeError("AI returned no image")
        processed = base64.b64decode(images[0]["data"])
        url = await mp.store_image(processed, f"doc-{d['doctor_id']}-proc-{secrets.token_hex(3)}", "png")
        photo.update({"processed": url, "status": "processed", "processed_at": mp.now()})
        await Db.mp_doctors.update_one({"doctor_id": d["doctor_id"]}, {"$set": {"photo": photo}})
        return {"success": True, "photo": photo}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(f"[mp] AI photo failed for {d['doctor_id']}: {exc}")
        await Db.mp_doctors.update_one({"doctor_id": d["doctor_id"]},
                                       {"$set": {"photo.status": "failed", "photo.error": str(exc)[:200]}})
        raise HTTPException(502, "AI processing failed — your original photo is preserved. Retry or request manual review.")


@router.post("/doctor/photo/choose")
async def doctor_choose_photo(body: Dict[str, str], authorization: str = Header(None)):
    d = await _doctor(authorization)
    photo = d.get("photo") or {}
    use = body.get("use")
    if use == "processed" and not photo.get("processed"):
        raise HTTPException(400, "No processed photo yet")
    if use not in ("processed", "original"):
        raise HTTPException(400, "use must be processed|original")
    photo["chosen"] = photo.get("processed") if use == "processed" else photo.get("original_url")
    photo["status"] = "submitted"
    await Db.mp_doctors.update_one({"doctor_id": d["doctor_id"]}, {"$set": {"photo": photo}})
    return {"success": True, "photo": photo}


@router.get("/doctor/bookings")
async def doctor_bookings(status: str = "", authorization: str = Header(None)):
    d = await _doctor(authorization)
    q: Dict[str, Any] = {"doctor_id": d["doctor_id"], "payment_status": "paid"}
    if status:
        q["status"] = status
    items = await Db.mp_consultations.find(q, {"_id": 0, "otp": 0, "razorpay_order_id": 0, "platform_earning": 0}).sort("created_at", -1).to_list(300)
    return items


@router.post("/doctor/bookings/{booking_id}/start")
async def doctor_start(booking_id: str, authorization: str = Header(None)):
    d = await _doctor(authorization)
    res = await Db.mp_consultations.update_one(
        {"booking_id": booking_id, "doctor_id": d["doctor_id"], "status": "confirmed"},
        {"$set": {"status": "in_progress", "updated_at": mp.now()}})
    if not res.matched_count:
        raise HTTPException(400, "Booking not in a startable state")
    return {"success": True}


@router.post("/doctor/bookings/{booking_id}/request-completion")
async def doctor_request_completion(booking_id: str, authorization: str = Header(None)):
    d = await _doctor(authorization)
    b = await Db.mp_consultations.find_one({"booking_id": booking_id, "doctor_id": d["doctor_id"]}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking not found")
    if b["status"] not in ("in_progress", "confirmed"):
        raise HTTPException(400, f"Cannot complete a {b['status']} consultation")
    sent = await _create_completion_otp(Db.mp_consultations, booking_id, b["customer"]["email"], "consultation")
    return {"success": True, "email_sent": sent}


@router.post("/doctor/bookings/{booking_id}/verify")
async def doctor_verify(booking_id: str, body: Dict[str, str], authorization: str = Header(None)):
    d = await _doctor(authorization)
    b = await Db.mp_consultations.find_one({"booking_id": booking_id}, {"_id": 0})
    if not b or b["doctor_id"] != d["doctor_id"]:
        raise HTTPException(403, "You can only verify your own consultations")
    done = await _verify_completion_otp(Db.mp_consultations, booking_id, body.get("otp", ""), d["doctor_id"])
    await _settle(done, "consultation")
    return {"success": True, "status": "completed"}


class PrescriptionIn(BaseModel):
    assessment: str = ""
    medications: List[Dict[str, str]] = []
    precautions: str = ""
    followup: str = ""


@router.get("/doctor/bookings/{booking_id}/prescription")
async def get_prescription(booking_id: str, authorization: str = Header(None)):
    d = await _doctor(authorization)
    rx = await Db.mp_prescriptions.find_one({"booking_id": booking_id, "doctor_id": d["doctor_id"],
                                             "status": {"$ne": "superseded"}}, {"_id": 0})
    return rx or {}


@router.post("/doctor/bookings/{booking_id}/prescription")
async def save_prescription(booking_id: str, body: PrescriptionIn, authorization: str = Header(None)):
    d = await _doctor(authorization)
    b = await Db.mp_consultations.find_one({"booking_id": booking_id, "doctor_id": d["doctor_id"]}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking not found")
    existing = await Db.mp_prescriptions.find_one({"booking_id": booking_id, "status": "draft"})
    if existing:
        await Db.mp_prescriptions.update_one({"_id": existing["_id"]}, {"$set": {**body.dict(), "updated_at": mp.now()}})
        return {"success": True, "prescription_id": existing["prescription_id"], "status": "draft"}
    rx = {"prescription_id": mp.uid("rx"), "booking_id": booking_id, "doctor_id": d["doctor_id"],
          "doctor_name": d["personal"]["name"], "registration_number": d["professional"].get("registration_number"),
          "customer_email": b["customer"]["email"], "patient_name": b["customer"]["name"],
          "date": b["date"], **body.dict(), "version": 1, "status": "draft",
          "history": [], "created_at": mp.now(), "updated_at": mp.now()}
    await Db.mp_prescriptions.insert_one(rx)
    return {"success": True, "prescription_id": rx["prescription_id"], "status": "draft"}


@router.post("/doctor/bookings/{booking_id}/prescription/finalize")
async def finalize_prescription(booking_id: str, authorization: str = Header(None)):
    d = await _doctor(authorization)
    rx = await Db.mp_prescriptions.find_one({"booking_id": booking_id, "doctor_id": d["doctor_id"], "status": "draft"})
    if not rx:
        raise HTTPException(404, "No draft prescription found")
    await Db.mp_prescriptions.update_one({"_id": rx["_id"]}, {"$set": {
        "status": "final", "finalized_at": mp.now(),
        "signature": f"Dr. {d['personal']['name']} (Reg: {d['professional'].get('registration_number', '—')}) — digitally approved {mp.now()}"}})
    await mp.notify("customer", rx["customer_email"], "Prescription ready",
                    "Your prescription is available in My Bookings.", "/my/bookings")
    await mp.send_mail(rx["customer_email"], "Your Celesta Glow prescription is ready",
                       f"Dr. {d['personal']['name']} has issued your prescription. View it in My Bookings.")
    return {"success": True, "status": "final"}


@router.post("/doctor/bookings/{booking_id}/prescription/image")
async def upload_prescription_image(booking_id: str, file: UploadFile = File(...), authorization: str = Header(None)):
    """Doctor uploads a photo/scan of a handwritten or printed prescription."""
    d = await _doctor(authorization)
    b = await Db.mp_consultations.find_one({"booking_id": booking_id, "doctor_id": d["doctor_id"]}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking not found")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "Image must be under 10MB")
    if (file.content_type or "") not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(400, "Only JPG, PNG or WebP images are allowed")
    ext = (file.filename or "rx.jpg").rsplit(".", 1)[-1].lower()
    url = await mp.store_image(data, f"rx-{booking_id}-{secrets.token_hex(3)}", ext)
    rx = await Db.mp_prescriptions.find_one({"booking_id": booking_id, "status": {"$ne": "superseded"}})
    if rx:
        await Db.mp_prescriptions.update_one({"_id": rx["_id"]}, {"$push": {"images": url},
                                             "$set": {"updated_at": mp.now(), "status": "final", "finalized_at": mp.now()}})
        pid = rx["prescription_id"]
    else:
        pid = mp.uid("rx")
        await Db.mp_prescriptions.insert_one({"prescription_id": pid, "booking_id": booking_id, "doctor_id": d["doctor_id"],
            "doctor_name": d["personal"]["name"], "registration_number": d["professional"].get("registration_number"),
            "customer_email": b["customer"]["email"], "patient_name": b["customer"]["name"], "date": b["date"],
            "images": [url], "medicines": [], "advice": "", "diagnosis": "", "version": 1, "status": "final",
            "finalized_at": mp.now(), "history": [], "created_at": mp.now(), "updated_at": mp.now()})
    await mp.notify("customer", b["customer"]["email"], "Prescription uploaded",
                    "Your doctor uploaded a prescription. Download it from My Bookings.", "/my/bookings")
    return {"success": True, "url": url, "prescription_id": pid}


@router.get("/consultations/{booking_id}/prescription")
async def customer_prescription(booking_id: str, email: str = "", authorization: str = Header(None)):
    """Customer fetches their final prescription (text + uploaded images) for download."""
    b = await Db.mp_consultations.find_one({"booking_id": booking_id}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking not found")
    allowed = bool(email and email.lower() == b["customer"]["email"])
    cust = await mp.current_customer(authorization)
    if cust and cust.get("email") == b["customer"]["email"]:
        allowed = True
    if not allowed:
        raise HTTPException(403, "Not authorised")
    rx = (await Db.mp_prescriptions.find_one({"booking_id": booking_id, "status": "final"}, {"_id": 0})
          or await Db.mp_prescriptions.find_one({"booking_id": booking_id}, {"_id": 0}))
    return rx or {}


@router.get("/prescriptions/{prescription_id}/pdf")
async def prescription_pdf(prescription_id: str, authorization: str = Header(None),
                           x_admin_token: str = Header(None)):
    rx = await Db.mp_prescriptions.find_one({"prescription_id": prescription_id}, {"_id": 0})
    if not rx:
        raise HTTPException(404, "Prescription not found")
    allowed = False
    cust = await mp.current_customer(authorization)
    if cust and cust.get("email") == rx.get("customer_email"):
        allowed = True
    token = (authorization or "").split()[-1] if authorization else ""
    if not allowed and token:
        sess = await Db.mp_sessions.find_one({"token": token, "role": "doctor"})
        if sess:
            acc = await Db.mp_accounts.find_one({"account_id": sess["account_id"]}, {"_id": 0})
            if acc and acc.get("ref_id") == rx.get("doctor_id"):
                allowed = True
    if not allowed and x_admin_token:
        try:
            v = mp.verify_admin_dep()
            r = v(x_admin_token=x_admin_token, admin_session=None)
            if hasattr(r, "__await__"):
                await r
            allowed = True
        except Exception:
            pass
    if not allowed:
        raise HTTPException(403, "Not authorised to view this prescription")
    pdf = _render_rx_pdf(rx)
    return StreamingResponse(io.BytesIO(pdf), media_type="application/pdf",
                             headers={"Content-Disposition": f"inline; filename={prescription_id}.pdf"})


def _render_rx_pdf(rx: Dict[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    y = h - 60
    c.setFont("Helvetica-Bold", 18); c.drawString(60, y, "Celesta Glow — e-Prescription"); y -= 30
    c.setFont("Helvetica", 11)
    for line in [f"Prescription ID: {rx.get('prescription_id')}   Booking: {rx.get('booking_id')}",
                 f"Date: {rx.get('date')}",
                 f"Patient: {rx.get('patient_name')}",
                 f"Doctor: Dr. {rx.get('doctor_name')}  Reg: {rx.get('registration_number', '—')}"]:
        c.drawString(60, y, line); y -= 18
    y -= 10; c.line(60, y, w - 60, y); y -= 24
    c.setFont("Helvetica-Bold", 12); c.drawString(60, y, "Clinical Assessment"); y -= 16
    c.setFont("Helvetica", 10)
    for chunk in (rx.get("assessment") or "—").split("\n"):
        c.drawString(60, y, chunk[:95]); y -= 14
    y -= 10
    c.setFont("Helvetica-Bold", 12); c.drawString(60, y, "Medications (Rx)"); y -= 16
    c.setFont("Helvetica", 10)
    for m in rx.get("medications", []):
        line = f"• {m.get('name','')} {m.get('strength','')} — {m.get('dosage','')}, {m.get('frequency','')}, {m.get('duration','')} ({m.get('route','oral')})"
        c.drawString(60, y, line[:95]); y -= 14
    y -= 10
    for title, key in (("Precautions", "precautions"), ("Follow-up", "followup")):
        c.setFont("Helvetica-Bold", 12); c.drawString(60, y, title); y -= 16
        c.setFont("Helvetica", 10)
        c.drawString(60, y, (rx.get(key) or "—")[:95]); y -= 22
    y = 90
    c.setFont("Helvetica-Oblique", 9); c.drawString(60, y, rx.get("signature") or "")
    c.showPage(); c.save()
    return buf.getvalue()


@router.get("/doctor/wallet")
async def doctor_wallet(authorization: str = Header(None)):
    d = await _doctor(authorization)
    bal = await mp.wallet_balance("doctor", d["doctor_id"])
    ledger = await Db.mp_wallet_ledger.find({"owner_type": "doctor", "owner_id": d["doctor_id"]},
                                            {"_id": 0}).sort("at", -1).to_list(100)
    wdr = await Db.mp_withdrawals.find({"owner_type": "doctor", "owner_id": d["doctor_id"]},
                                       {"_id": 0}).sort("at", -1).to_list(50)
    return {"balance": bal, "ledger": ledger, "withdrawals": wdr, **(await _wallet_terms(ledger))}


async def _wallet_terms(ledger: List[Dict[str, Any]]) -> Dict[str, Any]:
    c = await mp.cfg()
    settled = [e.get("meta") or {} for e in ledger if e.get("ref") == "settlement"]
    return {"commission_pct": c.get("platform_commission_pct", 15),
            "total_listed": round(sum(m.get("listed_price", 0) for m in settled), 2),
            "total_commission": round(sum(m.get("commission", 0) for m in settled), 2),
            "total_earned": round(sum(m.get("you_earn", 0) for m in settled), 2)}


MIN_WITHDRAW = 100.0
MAX_WITHDRAW_PER_DAY = 2


async def _guard_withdraw(owner_type: str, owner_id: str, amount: float):
    """Shared withdrawal rules for doctors & partners: min ₹100, ≤ balance, max 2/day."""
    if amount < MIN_WITHDRAW:
        raise HTTPException(400, f"Minimum withdrawal is ₹{int(MIN_WITHDRAW)}")
    bal = await mp.wallet_balance(owner_type, owner_id)
    if amount > bal:
        raise HTTPException(400, f"You can withdraw at most ₹{bal:.2f}")
    day_start = mp.now()[:10] + "T00:00:00"
    today = await Db.mp_withdrawals.count_documents(
        {"owner_type": owner_type, "owner_id": owner_id, "at": {"$gte": day_start}})
    if today >= MAX_WITHDRAW_PER_DAY:
        raise HTTPException(400, "You can withdraw at most twice a day")


@router.post("/doctor/withdraw")
async def doctor_withdraw(body: Dict[str, Any], authorization: str = Header(None)):
    d = await _doctor(authorization)
    amount = round(float(body.get("amount", 0)), 2)
    await _guard_withdraw("doctor", d["doctor_id"], amount)
    entry = await mp.wallet_move("doctor", d["doctor_id"], amount, "debit", "withdrawal request")
    w = {"withdrawal_id": mp.uid("wdr"), "owner_type": "doctor", "owner_id": d["doctor_id"],
         "amount": amount, "status": "pending", "at": mp.now()}
    await Db.mp_withdrawals.insert_one(w)
    await mp.notify("admin", "all", "Withdrawal request", f"Doctor requested ₹{amount}", "/admin/doctors-crm")
    return {"success": True, "withdrawal_id": w["withdrawal_id"]}


@router.get("/doctor/notifications")
async def doctor_notifications(authorization: str = Header(None)):
    d = await _doctor(authorization)
    return await Db.mp_notifications.find({"audience_type": "doctor", "audience_ref": d["doctor_id"]},
                                          {"_id": 0}).sort("at", -1).to_list(50)


# ================================================================ partner portal
async def _partner(authorization: str) -> Dict[str, Any]:
    acc = await mp.require_account(authorization, "partner")
    p = await Db.mp_partners.find_one({"partner_id": acc["ref_id"]}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Partner profile not found")
    return p


@router.get("/partner/profile")
async def partner_profile(authorization: str = Header(None)):
    p = await _partner(authorization)
    p.pop("decisions", None)
    return p


class PartnerProfileUpdate(BaseModel):
    availability: Optional[Dict[str, List[str]]] = None
    staff_total: Optional[int] = None
    staff_female: Optional[int] = None
    staff_male: Optional[int] = None
    paused: Optional[bool] = None
    coverage_area: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None


@router.put("/partner/profile")
async def partner_update(body: PartnerProfileUpdate, authorization: str = Header(None)):
    p = await _partner(authorization)
    updates: Dict[str, Any] = {}
    if body.paused is not None:
        updates["paused"] = body.paused
    if body.availability is not None:
        updates["availability"] = body.availability
    if body.coverage_area is not None:
        updates["location.coverage_area"] = body.coverage_area
    if body.lat is not None:
        updates["location.lat"] = body.lat
    if body.lng is not None:
        updates["location.lng"] = body.lng
    if body.staff_female is not None or body.staff_male is not None or body.staff_total is not None:
        cur = p.get("staff") or {}
        f = max(0, body.staff_female if body.staff_female is not None else int(cur.get("female") or 0))
        m = max(0, body.staff_male if body.staff_male is not None else int(cur.get("male") or 0))
        t = max(body.staff_total if body.staff_total is not None else int(cur.get("total") or 0), f + m, 1)
        updates["staff"] = {"total": t, "female": f, "male": m}
    if updates:
        await Db.mp_partners.update_one({"partner_id": p["partner_id"]}, {"$set": updates})
    return {"success": True}


@router.get("/partner/requests")
async def partner_requests(authorization: str = Header(None)):
    p = await _partner(authorization)
    offers = await Db.mp_booking_offers.find(
        {"partner_id": p["partner_id"], "status": "pending", "expires_at": {"$gt": mp.now()}},
        {"_id": 0}).sort("created_at", -1).to_list(50)
    out = []
    for o in offers:
        b = await Db.mp_home_bookings.find_one({"booking_id": o["booking_id"]},
                                               {"_id": 0, "otp": 0})
        if b and b["status"] == "pending_assignment":
            out.append({**o, "booking": b})
    return out


@router.post("/partner/requests/{booking_id}/accept")
async def partner_accept(booking_id: str, authorization: str = Header(None)):
    p = await _partner(authorization)
    offer = await Db.mp_booking_offers.find_one({"booking_id": booking_id, "partner_id": p["partner_id"],
                                                 "status": "pending"})
    if not offer or offer.get("expires_at", "") < mp.now():
        raise HTTPException(410, "This request has expired")
    hb = await Db.mp_home_bookings.find_one({"booking_id": booking_id}, {"service_id": 1})
    if not hb:
        raise HTTPException(404, "Booking not found")
    sel = next((s for s in p.get("services", []) if s["service_id"] == hb["service_id"]), {})
    res = await Db.mp_home_bookings.find_one_and_update(
        {"booking_id": booking_id, "status": "pending_assignment"},
        {"$set": {"status": "assigned", "partner_id": p["partner_id"],
                  "partner_name": p["applicant"].get("business_name") or p["applicant"]["name"],
                  "assigned_at": mp.now(), "updated_at": mp.now()},
         "$push": {"timeline": {"status": "assigned", "at": mp.now(), "by": p["partner_id"]}}},
        return_document=True)
    if not res:
        raise HTTPException(409, "Another partner already accepted this booking")
    await Db.mp_booking_offers.update_many({"booking_id": booking_id, "partner_id": {"$ne": p["partner_id"]}},
                                           {"$set": {"status": "expired"}})
    await Db.mp_booking_offers.update_one({"booking_id": booking_id, "partner_id": p["partner_id"]},
                                          {"$set": {"status": "accepted"}})
    await mp.notify("customer", res["customer"]["email"], "Partner assigned",
                    f"{res['partner_name']} accepted your booking {booking_id}.", f"/track/{booking_id}")
    await mp.send_mail(res["customer"]["email"], "Partner assigned for your home service",
                       f"{res['partner_name']} will handle your {res.get('service_name')} on {res['date']} at {res['slot']}.")
    return {"success": True, "booking_id": booking_id}


@router.post("/partner/requests/{booking_id}/decline")
async def partner_decline(booking_id: str, authorization: str = Header(None)):
    p = await _partner(authorization)
    await Db.mp_booking_offers.update_one({"booking_id": booking_id, "partner_id": p["partner_id"]},
                                          {"$set": {"status": "declined"}})
    return {"success": True}


@router.get("/partner/bookings")
async def partner_bookings(status: str = "", authorization: str = Header(None)):
    p = await _partner(authorization)
    q: Dict[str, Any] = {"partner_id": p["partner_id"]}
    if status:
        q["status"] = status
    return await Db.mp_home_bookings.find(q, {"_id": 0, "otp": 0}).sort("created_at", -1).to_list(300)


async def _own_booking(booking_id: str, partner_id: str) -> Dict[str, Any]:
    b = await Db.mp_home_bookings.find_one({"booking_id": booking_id, "partner_id": partner_id}, {"_id": 0})
    if not b:
        raise HTTPException(404, "Booking not found")
    return b


def _tl(status: str, by: str) -> Dict[str, str]:
    return {"status": status, "at": mp.now(), "by": by}


@router.post("/partner/bookings/{booking_id}/start-journey")
async def partner_start_journey(booking_id: str, authorization: str = Header(None)):
    p = await _partner(authorization)
    b = await _own_booking(booking_id, p["partner_id"])
    if b["status"] != "assigned":
        raise HTTPException(400, f"Cannot start journey from status {b['status']}")
    await Db.mp_home_bookings.update_one({"booking_id": booking_id}, {
        "$set": {"status": "en_route", "tracking.sharing": True, "updated_at": mp.now()},
        "$push": {"timeline": _tl("en_route", p["partner_id"])}})
    await mp.notify("customer", b["customer"]["email"], "Partner on the way",
                    f"{b.get('partner_name')} started the journey. Live tracking is now available.",
                    f"/track/{booking_id}")
    return {"success": True, "status": "en_route"}


@router.post("/partner/bookings/{booking_id}/location")
async def partner_location(booking_id: str, body: Dict[str, Any], authorization: str = Header(None)):
    p = await _partner(authorization)
    b = await _own_booking(booking_id, p["partner_id"])
    if b["status"] != "en_route":
        raise HTTPException(400, "Location updates are only accepted while en route")
    lat, lng = body.get("lat"), body.get("lng")
    if lat is None or lng is None:
        raise HTTPException(400, "lat/lng required")
    await Db.mp_home_bookings.update_one({"booking_id": booking_id}, {"$set": {
        "tracking.lat": float(lat), "tracking.lng": float(lng), "tracking.at": mp.now(),
        "tracking.sharing": True, "tracking.eta_minutes": body.get("eta_minutes")}})
    return {"success": True}


@router.post("/partner/bookings/{booking_id}/stop-tracking")
async def partner_stop_tracking(booking_id: str, authorization: str = Header(None)):
    p = await _partner(authorization)
    await _own_booking(booking_id, p["partner_id"])
    await Db.mp_home_bookings.update_one({"booking_id": booking_id},
                                         {"$set": {"tracking.sharing": False, "updated_at": mp.now()}})
    return {"success": True}


@router.post("/partner/bookings/{booking_id}/arrived")
async def partner_arrived(booking_id: str, body: Dict[str, Any] = {}, authorization: str = Header(None)):
    p = await _partner(authorization)
    b = await _own_booking(booking_id, p["partner_id"])
    if b["status"] != "en_route":
        raise HTTPException(400, "Partner is not en route")
    cust = b.get("customer") or {}
    plat, plng = body.get("lat"), body.get("lng")
    if cust.get("lat") and cust.get("lng") and plat and plng and not body.get("force"):
        dist = mp.haversine_km(plat, plng, cust["lat"], cust["lng"])
        if dist > 0.5:
            raise HTTPException(400, f"You appear to be {dist:.1f} km from the customer address — move closer to confirm arrival (or contact support).")
    await Db.mp_home_bookings.update_one({"booking_id": booking_id}, {
        "$set": {"status": "arrived", "arrival_verified": bool(cust.get("lat") and plat), "updated_at": mp.now()},
        "$push": {"timeline": _tl("arrived", p["partner_id"])}})
    await mp.notify("customer", b["customer"]["email"], "Partner arrived",
                    f"{b.get('partner_name')} has arrived at your location.", f"/track/{booking_id}")
    return {"success": True}


@router.post("/partner/bookings/{booking_id}/arrival-photo")
async def partner_arrival_photo(booking_id: str, file: UploadFile = File(...), lat: Optional[float] = Form(None),
                                lng: Optional[float] = Form(None), force: bool = Form(False),
                                authorization: str = Header(None)):
    """Geo-tagged arrival photo — confirms arrival (if en route) and syncs partner location."""
    p = await _partner(authorization)
    b = await _own_booking(booking_id, p["partner_id"])
    if b["status"] not in ("en_route", "arrived"):
        raise HTTPException(400, "Arrival photo can be uploaded only when you reach the customer")
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "Photo must be under 8MB")
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(400, "Only image files are allowed")
    cust = b.get("customer") or {}
    dist = None
    if lat is not None and lng is not None and cust.get("lat") and cust.get("lng"):
        dist = round(mp.haversine_km(lat, lng, cust["lat"], cust["lng"]), 2)
        if dist > 0.5 and not force:
            raise HTTPException(400, f"You appear to be {dist:.1f} km from the customer address — move closer, or confirm anyway.")
    ext = (file.filename or "photo.jpg").rsplit(".", 1)[-1].lower()
    url = await mp.store_image(data, f"arr-{booking_id.lower()}-{secrets.token_hex(3)}", ext)
    photo = {"url": url, "lat": lat, "lng": lng, "distance_km": dist, "at": mp.now(), "forced": bool(force and (dist or 0) > 0.5)}
    upd: Dict[str, Any] = {"arrival_photo": photo, "updated_at": mp.now(),
                           "arrival_verified": dist is not None and dist <= 0.5}
    if lat is not None and lng is not None:
        upd.update({"tracking.lat": lat, "tracking.lng": lng, "tracking.at": mp.now()})
    push = {}
    if b["status"] == "en_route":
        upd["status"] = "arrived"
        push = {"$push": {"timeline": _tl("arrived", p["partner_id"])}}
        await mp.notify("customer", cust.get("email", ""), "Partner arrived",
                        f"{b.get('partner_name')} has arrived at your location.", f"/track/{booking_id}")
    await Db.mp_home_bookings.update_one({"booking_id": booking_id}, {"$set": upd, **push})
    return {"success": True, "arrival_photo": photo, "status": "arrived"}


@router.post("/partner/bookings/{booking_id}/cash-collected")
async def partner_cash_collected(booking_id: str, authorization: str = Header(None)):
    p = await _partner(authorization)
    b = await _own_booking(booking_id, p["partner_id"])
    if b.get("payment_method") != "pay_after_service":
        raise HTTPException(400, "This booking was paid online")
    if b["status"] not in ("in_service", "completion_pending", "completed"):
        raise HTTPException(400, "Cash can be marked collected only during or after the service")
    await Db.mp_home_bookings.update_one({"booking_id": booking_id}, {"$set": {
        "payment_status": "paid_cash", "cash_collected_by": p["partner_id"], "paid_at": mp.now()}})
    return {"success": True, "payment_status": "paid_cash"}


@router.post("/partner/bookings/{booking_id}/start-service")
async def partner_start_service(booking_id: str, authorization: str = Header(None)):
    p = await _partner(authorization)
    b = await _own_booking(booking_id, p["partner_id"])
    if b["status"] != "arrived":
        raise HTTPException(400, f"Confirm arrival with a location photo first (current: {b['status']})")
    if not b.get("arrival_photo"):
        raise HTTPException(400, "Upload an arrival photo from the customer location before starting the service")
    await Db.mp_home_bookings.update_one({"booking_id": booking_id}, {
        "$set": {"status": "in_service", "tracking.sharing": False, "updated_at": mp.now()},
        "$push": {"timeline": _tl("in_service", p["partner_id"])}})
    return {"success": True}


@router.post("/partner/bookings/{booking_id}/request-completion")
async def partner_request_completion(booking_id: str, authorization: str = Header(None)):
    p = await _partner(authorization)
    b = await _own_booking(booking_id, p["partner_id"])
    if b["status"] != "in_service":
        raise HTTPException(400, "Service is not in progress")
    sent = await _create_completion_otp(Db.mp_home_bookings, booking_id, b["customer"]["email"], "service")
    return {"success": True, "email_sent": sent}


@router.post("/partner/bookings/{booking_id}/verify")
async def partner_verify(booking_id: str, body: Dict[str, str], authorization: str = Header(None)):
    p = await _partner(authorization)
    b = await Db.mp_home_bookings.find_one({"booking_id": booking_id}, {"_id": 0})
    if not b or b.get("partner_id") != p["partner_id"]:
        raise HTTPException(403, "You can only verify your own bookings")
    done = await _verify_completion_otp(Db.mp_home_bookings, booking_id, body.get("otp", ""), p["partner_id"])
    # Cash bookings are confirmed paid the moment the customer code is verified — no separate step.
    if done.get("payment_method") == "pay_after_service":
        await Db.mp_home_bookings.update_one({"booking_id": booking_id}, {"$set": {
            "payment_status": "paid_cash", "cash_collected_by": p["partner_id"], "paid_at": mp.now()}})
        done["payment_status"] = "paid_cash"
    await _settle(done, "home")
    return {"success": True, "status": "completed"}


@router.get("/partner/services")
async def partner_services(authorization: str = Header(None)):
    p = await _partner(authorization)
    catalogue = await Db.mp_services.find({"status": "active", "created_by": {"$exists": False}},
                                          {"_id": 0, "commission_pct": 0, "price_range": 0}).to_list(300)
    custom = await Db.mp_services.find({"created_by": p["partner_id"]}, {"_id": 0}).to_list(100)
    mine = {s["service_id"]: s for s in p.get("services", [])}
    c = await mp.cfg()
    return {"catalogue": catalogue, "mine": list(mine.values()), "custom": custom,
            "commission_pct": c.get("platform_commission_pct", 15)}


@router.post("/partner/services/request")
async def partner_request_service(body: Dict[str, Any], authorization: str = Header(None)):
    p = await _partner(authorization)
    sid = body.get("service_id")
    svc = await Db.mp_services.find_one({"service_id": sid, "status": "active"}, {"_id": 0})
    if not svc:
        raise HTTPException(404, "Not an active catalogue service")
    if any(s["service_id"] == sid for s in p.get("services", [])):
        raise HTTPException(409, "Already requested")
    price = body.get("price") or svc.get("price")
    if not price or float(price) <= 0:
        raise HTTPException(400, "Set your price")
    sel = {"service_id": sid, "service_name": svc["name"], "mode": body.get("mode", "home"),
           "price": float(price), "coverage": body.get("coverage", ""),
           "qualifications": body.get("qualifications", ""), "approval_status": "pending"}
    await Db.mp_partners.update_one({"partner_id": p["partner_id"]}, {"$push": {"services": sel}})
    await mp.notify("admin", "all", "Partner service request",
                    f"{p['applicant']['name']} requested {svc['name']}", "/admin/partners-crm")
    return {"success": True, "status": "pending"}


@router.get("/partner/wallet")
async def partner_wallet(authorization: str = Header(None)):
    p = await _partner(authorization)
    bal = await mp.wallet_balance("partner", p["partner_id"])
    ledger = await Db.mp_wallet_ledger.find({"owner_type": "partner", "owner_id": p["partner_id"]},
                                            {"_id": 0}).sort("at", -1).to_list(100)
    wdr = await Db.mp_withdrawals.find({"owner_type": "partner", "owner_id": p["partner_id"]},
                                       {"_id": 0}).sort("at", -1).to_list(50)
    return {"balance": bal, "ledger": ledger, "withdrawals": wdr, **(await _wallet_terms(ledger))}


@router.post("/partner/withdraw")
async def partner_withdraw(body: Dict[str, Any], authorization: str = Header(None)):
    p = await _partner(authorization)
    amount = round(float(body.get("amount", 0)), 2)
    await _guard_withdraw("partner", p["partner_id"], amount)
    await mp.wallet_move("partner", p["partner_id"], amount, "debit", "withdrawal request")
    w = {"withdrawal_id": mp.uid("wdr"), "owner_type": "partner", "owner_id": p["partner_id"],
         "amount": amount, "status": "pending", "at": mp.now()}
    await Db.mp_withdrawals.insert_one(w)
    await mp.notify("admin", "all", "Withdrawal request", f"Partner requested ₹{amount}", "/admin/partners-crm")
    return {"success": True, "withdrawal_id": w["withdrawal_id"]}


@router.get("/partner/notifications")
async def partner_notifications(authorization: str = Header(None)):
    p = await _partner(authorization)
    return await Db.mp_notifications.find({"audience_type": "partner", "audience_ref": p["partner_id"]},
                                          {"_id": 0}).sort("at", -1).to_list(50)


# ================================================================ support (shared)
SUPPORT_CATEGORIES = ["Booking Issues", "Doctor Consultation", "Video Call Problems", "Prescription Access",
                      "Service Partner Delay", "Live Tracking Issues", "Service Quality", "Payment Failure",
                      "OTP Verification", "Refunds", "Account Access", "Partner Application", "Wallet and Withdrawal"]


class TicketIn(BaseModel):
    category: str
    subject: str
    description: str
    booking_id: str = ""
    email: str
    name: str = ""
    user_type: str = "customer"  # customer | doctor | partner


@router.get("/support/categories")
async def support_categories():
    return SUPPORT_CATEGORIES


@router.post("/support")
async def create_ticket(body: TicketIn):
    t = {"ticket_id": mp.uid("tkt").upper().replace("TKT_", "CG-T-"),
         **body.dict(), "email": body.email.lower(), "priority": "normal", "status": "open",
         "assigned": "", "responses": [], "resolution_notes": "",
         "created_at": mp.now(), "updated_at": mp.now()}
    await Db.mp_support.insert_one(t)
    await mp.notify("admin", "all", f"Support: {body.category}", body.subject, "/admin/support")
    return {"success": True, "ticket_id": t["ticket_id"]}


@router.get("/support")
async def my_tickets(email: str, authorization: str = Header(None)):
    return await Db.mp_support.find({"email": email.lower()}, {"_id": 0}).sort("updated_at", -1).to_list(100)


@router.post("/support/{ticket_id}/reply")
async def reply_ticket(ticket_id: str, body: Dict[str, str]):
    t = await Db.mp_support.find_one({"ticket_id": ticket_id}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Ticket not found")
    reply = {"by": body.get("by", "user"), "message": body.get("message", ""), "at": mp.now()}
    await Db.mp_support.update_one({"ticket_id": ticket_id},
                                   {"$push": {"responses": reply},
                                    "$set": {"updated_at": mp.now(), "status": "open"}})
    return {"success": True}


# ================================================================ presence (online/offline)
class PresenceIn(BaseModel):
    online: bool


@router.post("/doctor/presence")
async def doctor_presence(body: PresenceIn, authorization: str = Header(None)):
    d = await _doctor(authorization)
    await Db.mp_doctors.update_one({"doctor_id": d["doctor_id"]},
                                   {"$set": {"online": body.online, "last_seen": mp.now()}})
    return {"success": True, "online": body.online}


@router.post("/partner/presence")
async def partner_presence(body: PresenceIn, authorization: str = Header(None)):
    p = await _partner(authorization)
    await Db.mp_partners.update_one({"partner_id": p["partner_id"]},
                                    {"$set": {"online": body.online, "last_seen": mp.now()}})
    return {"success": True, "online": body.online}


# ================================================================ instant consultations
class InstantConsultIn(BaseModel):
    doctor_id: Optional[str] = None
    name: str
    email: str
    phone: str


async def _doctor_busy_now(doctor_id: str) -> bool:
    """True if the doctor is in a consult or has a booked slot within ±30 min (IST)."""
    ist = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5, minutes=30)
    rows = await Db.mp_consultations.find(
        {"doctor_id": doctor_id, "status": {"$in": ["confirmed", "in_progress", "completion_pending"]},
         "$or": [{"status": "in_progress"}, {"date": ist.date().isoformat()}]}, {"_id": 0, "slot": 1, "status": 1}).to_list(50)
    for b in rows:
        if b["status"] == "in_progress":
            return True
        try:
            h, m = map(int, str(b.get("slot", "")).split(":"))
        except ValueError:
            continue
        start = ist.replace(hour=h, minute=m, second=0, microsecond=0)
        if abs((ist - start).total_seconds()) <= 1800:
            return True
    return False


async def _dispatch_instant(booking: Dict[str, Any]):
    """Fan out a PAID instant consultation to online doctors (first-accept wins)."""
    cfg = await mp.cfg()
    q: Dict[str, Any] = {"application_status": "approved", "active": True}
    if booking.get("doctor_id"):
        q["doctor_id"] = booking["doctor_id"]
    candidates = [d for d in await Db.mp_doctors.find(q, {"_id": 0}).to_list(100) if mp.is_online(d)]
    candidates = [d for d in candidates if not await _doctor_busy_now(d["doctor_id"])]
    expiry = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=3)).isoformat()
    commission = cfg.get("platform_commission_pct", 20)
    for c in candidates:
        cfee = (c.get("consultation") or {}).get("fee", booking.get("fee", 0))
        await Db.mp_booking_offers.update_one(
            {"booking_id": booking["booking_id"], "doctor_id": c["doctor_id"]},
            {"$setOnInsert": {"booking_id": booking["booking_id"], "doctor_id": c["doctor_id"], "kind": "consult",
                              "expires_at": expiry, "status": "pending",
                              "expected_earnings": booking.get("provider_earning") or round(cfee * (1 - commission / 100), 2), "created_at": mp.now()}},
            upsert=True)
        await mp.notify("doctor", c["doctor_id"], "Instant consultation request",
                        f"{booking['customer']['name']} paid and is waiting — accept to connect.", "/doctor")
    return len(candidates)


@router.get("/consultations/online-doctors")
async def online_doctors(doctor_id: str = ""):
    """Rate card of dermatologists online RIGHT NOW so the patient can pick before paying."""
    cfg = await mp.cfg()
    q: Dict[str, Any] = {"application_status": "approved", "active": True}
    if doctor_id:
        q["doctor_id"] = doctor_id
    docs = [d for d in await Db.mp_doctors.find(q, {"_id": 0}).to_list(100) if mp.is_online(d)]
    out = []
    for d in docs:
        if await _doctor_busy_now(d["doctor_id"]):
            continue
        base = (d.get("consultation") or {}).get("fee", 999)
        pv = mp.price_view(base, cfg)
        prof = d.get("professional") or {}
        ph = d.get("photo") or {}
        out.append({"doctor_id": d["doctor_id"], "name": d["personal"]["name"],
                    "specialisation": prof.get("specialisation") or "Dermatologist",
                    "experience_years": prof.get("experience_years"),
                    "photo": ph.get("chosen") or ph.get("original_url") or "",
                    "fee": pv["price"], "mrp": pv["mrp"]})
    return {"doctors": out, "count": len(out)}


@router.post("/consultations/instant")
async def instant_consult(body: InstantConsultIn):
    cfg = await mp.cfg()
    if not cfg["dermatologist_enabled"]:
        raise HTTPException(403, "Dermatologist consultations are temporarily unavailable")
    q: Dict[str, Any] = {"application_status": "approved", "active": True}
    if body.doctor_id:
        q["doctor_id"] = body.doctor_id
    candidates = [d for d in await Db.mp_doctors.find(q, {"_id": 0}).to_list(100) if mp.is_online(d)]
    if not candidates:
        raise HTTPException(409, "No dermatologists are online right now — schedule a slot instead.")
    rz = mp.razorpay()
    if rz is None:
        raise HTTPException(503, "Instant consultations need online payment, which is being set up — please schedule a slot.")
    pv = mp.price_view(min((c.get("consultation") or {}).get("fee", 999) for c in candidates), cfg)
    fee = pv["price"]
    booking_id = mp.uid("cns").upper().replace("CNS_", "CG-C-")
    targeted = candidates[0] if body.doctor_id else None
    booking = {
        "booking_id": booking_id, "type": "instant",
        "doctor_id": targeted["doctor_id"] if targeted else None,
        "doctor_name": targeted["personal"]["name"] if targeted else None,
        "date": dt.datetime.now(dt.timezone.utc).date().isoformat(), "slot": "Instant",
        "customer": {"name": body.name, "email": body.email.lower(), "phone": body.phone},
        "fee": fee, "total_amount": fee, "status": "pending_payment",
        "base_fee": pv["base"], "provider_earning": pv["provider_earning"], "platform_earning": pv["platform_earning"],
        "commission_pct": cfg.get("platform_commission_pct", 15), "mrp": pv["mrp"],
        "payment_status": "unpaid", "payment_method": "online",
        "room_secret": secrets.token_hex(4), "created_at": mp.now(), "updated_at": mp.now(),
    }
    if rz is not None:
        try:
            order = rz.order.create({"amount": int(fee * 100), "currency": "INR",
                                     "receipt": booking_id, "payment_capture": 1})
            booking["razorpay_order_id"] = order["id"]
        except Exception as exc:
            logger.error(f"[mp] razorpay order failed: {exc}")
            raise HTTPException(502, "Payment gateway error — please try again")
    await Db.mp_consultations.insert_one(booking)
    notified = 0
    if rz is None:
        notified = await _dispatch_instant({**booking, "customer": booking["customer"]})
    booking.pop("_id", None)
    return {"success": True, "booking": booking, "doctors_notified": notified,
            "payments_configured": rz is not None,
            "message": ("Complete payment to connect with an online doctor."
                        if rz else f"{notified} online doctor(s) notified — the first to accept joins you.")}


@router.get("/doctor/requests")
async def doctor_instant_requests(authorization: str = Header(None)):
    d = await _doctor(authorization)
    offers = await Db.mp_booking_offers.find(
        {"doctor_id": d["doctor_id"], "kind": "consult", "status": "pending",
         "expires_at": {"$gt": mp.now()}}, {"_id": 0}).sort("created_at", -1).to_list(50)
    out = []
    for o in offers:
        b = await Db.mp_consultations.find_one({"booking_id": o["booking_id"]}, {"_id": 0, "otp": 0})
        if b and b["status"] == "pending_assignment":
            out.append({**o, "booking": b})
    return out


@router.post("/doctor/requests/{booking_id}/accept")
async def doctor_accept_instant(booking_id: str, authorization: str = Header(None)):
    d = await _doctor(authorization)
    offer = await Db.mp_booking_offers.find_one({"booking_id": booking_id, "doctor_id": d["doctor_id"],
                                                 "kind": "consult", "status": "pending"})
    if not offer or offer.get("expires_at", "") < mp.now():
        raise HTTPException(410, "This request has expired")
    res = await Db.mp_consultations.find_one_and_update(
        {"booking_id": booking_id, "status": "pending_assignment"},
        {"$set": {"status": "confirmed", "doctor_id": d["doctor_id"],
                  "doctor_name": d["personal"]["name"],
                  "assigned_at": mp.now(), "updated_at": mp.now()}},
        return_document=True)
    if not res:
        raise HTTPException(409, "Another doctor already accepted this request")
    await Db.mp_booking_offers.update_many({"booking_id": booking_id, "doctor_id": {"$ne": d["doctor_id"]}},
                                           {"$set": {"status": "expired"}})
    await Db.mp_booking_offers.update_one({"booking_id": booking_id, "doctor_id": d["doctor_id"]},
                                          {"$set": {"status": "accepted"}})
    await on_consult_confirmed(res)
    await mp.send_mail(res["customer"]["email"], "A dermatologist is ready for you",
                       f"Dr. {d['personal']['name']} accepted your instant consultation {booking_id}. Open the site and join your video room now.")
    await mp.notify("customer", res["customer"]["email"], "Doctor accepted",
                    f"Dr. {d['personal']['name']} is ready — join your consultation room.", f"/consult-room/{booking_id}")
    return {"success": True, "booking_id": booking_id}


@router.post("/doctor/requests/{booking_id}/decline")
async def doctor_decline_instant(booking_id: str, authorization: str = Header(None)):
    d = await _doctor(authorization)
    await Db.mp_booking_offers.update_one({"booking_id": booking_id, "doctor_id": d["doctor_id"], "kind": "consult"},
                                          {"$set": {"status": "declined"}})
    return {"success": True}


@router.post("/consultations/{booking_id}/cancel-refund")
async def consult_cancel_refund(booking_id: str, body: Dict[str, Any]):
    """No doctor connected: stop ringing and refund the paid fee to the customer's wallet."""
    email = (body.get("email") or "").lower()
    b = await Db.mp_consultations.find_one({"booking_id": booking_id}, {"_id": 0})
    if not b or b["customer"]["email"] != email:
        raise HTTPException(404, "Booking not found")
    if b["status"] in ("confirmed", "in_progress", "completed", "completion_pending"):
        raise HTTPException(400, "A doctor already connected — request a refund from support instead.")
    if b["status"] == "refunded":
        return {"success": True, "already": True, "refunded": b.get("refunded_amount", 0)}
    await Db.mp_booking_offers.update_many({"booking_id": booking_id}, {"$set": {"status": "expired"}})
    refunded = 0.0
    if b.get("payment_status") == "paid":
        refunded = float(b.get("fee", 0))
        await mp.wallet_move("customer", email, refunded, "credit",
                             "Instant consult refund — no doctor connected", booking_id)
    await Db.mp_consultations.update_one({"booking_id": booking_id}, {"$set": {
        "status": "refunded", "refunded_amount": refunded, "refunded_to": "wallet", "updated_at": mp.now()}})
    await mp.notify("customer", email, "Refunded to your wallet",
                    f"₹{refunded} was added to your Celesta Glow wallet for {booking_id}. Use it to call another doctor.", "/my/bookings")
    return {"success": True, "refunded": refunded}


@router.post("/consultations/{booking_id}/refund-request")
async def consult_refund_request(booking_id: str, body: Dict[str, Any]):
    """Customer asks the admin to review a refund (e.g. call issues after a doctor connected)."""
    email = (body.get("email") or "").lower()
    b = await Db.mp_consultations.find_one({"booking_id": booking_id}, {"_id": 0})
    if not b or b["customer"]["email"] != email:
        raise HTTPException(404, "Booking not found")
    if await Db.mp_refunds.find_one({"booking_id": booking_id, "status": "pending"}):
        return {"success": True, "already": True}
    await Db.mp_refunds.insert_one({"refund_id": mp.uid("rfd"), "booking_id": booking_id, "module": "consultation",
        "customer_email": email, "customer_name": b["customer"]["name"], "amount": float(b.get("fee", 0)),
        "reason": body.get("reason", ""), "status": "pending", "payment_status": b.get("payment_status"), "at": mp.now()})
    return {"success": True}


@router.post("/home-bookings/{booking_id}/cancel-refund")
async def home_cancel_refund(booking_id: str, body: Dict[str, Any]):
    """No partner accepted a home-service booking: stop broadcasting and refund to the customer wallet."""
    email = (body.get("email") or "").lower()
    b = await Db.mp_home_bookings.find_one({"booking_id": booking_id}, {"_id": 0})
    if not b or b["customer"]["email"] != email:
        raise HTTPException(404, "Booking not found")
    if b["status"] in ("assigned", "in_service", "completed", "completion_pending"):
        raise HTTPException(400, "A partner already accepted — request a refund from support instead.")
    if b["status"] == "refunded":
        return {"success": True, "already": True, "refunded": b.get("refunded_amount", 0)}
    await Db.mp_booking_offers.update_many({"booking_id": booking_id}, {"$set": {"status": "expired"}})
    refunded = 0.0
    if b.get("payment_status") == "paid":
        refunded = float(b.get("total_amount") or b.get("price") or 0)
        await mp.wallet_move("customer", email, refunded, "credit",
                             "Home service refund — no partner accepted", booking_id)
    await Db.mp_home_bookings.update_one({"booking_id": booking_id}, {"$set": {
        "status": "refunded", "refunded_amount": refunded, "refunded_to": "wallet", "updated_at": mp.now()}})
    await mp.notify("customer", email, "Refunded to your wallet",
                    f"₹{refunded} was added to your Celesta Glow wallet for {booking_id}.", "/my/bookings")
    return {"success": True, "refunded": refunded}


@router.post("/home-bookings/{booking_id}/refund-request")
async def home_refund_request(booking_id: str, body: Dict[str, Any]):
    """Customer asks the admin to review a refund for a home-service booking."""
    email = (body.get("email") or "").lower()
    b = await Db.mp_home_bookings.find_one({"booking_id": booking_id}, {"_id": 0})
    if not b or b["customer"]["email"] != email:
        raise HTTPException(404, "Booking not found")
    if await Db.mp_refunds.find_one({"booking_id": booking_id, "status": "pending"}):
        return {"success": True, "already": True}
    await Db.mp_refunds.insert_one({"refund_id": mp.uid("rfd"), "booking_id": booking_id, "module": "home",
        "customer_email": email, "customer_name": b["customer"]["name"],
        "amount": float(b.get("total_amount") or b.get("price") or 0),
        "reason": body.get("reason", ""), "status": "pending", "payment_status": b.get("payment_status"), "at": mp.now()})
    return {"success": True}


@router.post("/partner/photo")
async def partner_upload_photo(file: UploadFile = File(...), authorization: str = Header(None)):
    p = await _partner(authorization)
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "Photo must be under 8MB")
    if (file.content_type or "") not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(400, "Only JPG, PNG or WebP photos are allowed")
    ext = (file.filename or "photo.jpg").rsplit(".", 1)[-1].lower()
    url = await mp.store_image(data, f"prt-{p['partner_id']}-{secrets.token_hex(3)}", ext)
    await Db.mp_partners.update_one({"partner_id": p["partner_id"]}, {"$set": {
        "photo": {"original_url": url, "chosen": url, "status": "uploaded", "uploaded_at": mp.now()}}})
    return {"success": True, "url": url}


# ================================================================ reviews
class ReviewIn(BaseModel):
    booking_id: str
    module: str  # consultation | home
    rating: int
    comment: str = ""
    email: str


@router.post("/reviews")
async def create_review(body: ReviewIn):
    if not (1 <= body.rating <= 5):
        raise HTTPException(400, "Rating must be 1–5")
    coll = Db.mp_consultations if body.module == "consultation" else Db.mp_home_bookings
    b = await coll.find_one({"booking_id": body.booking_id}, {"_id": 0})
    if not b or b["customer"]["email"] != body.email.lower():
        raise HTTPException(404, "Booking not found for this email")
    if b["status"] != "completed":
        raise HTTPException(400, "You can review only completed bookings")
    existing = await Db.mp_reviews.find_one({"booking_id": body.booking_id})
    if existing:
        raise HTTPException(409, "You already reviewed this booking")
    target = b.get("doctor_id") if body.module == "consultation" else b.get("partner_id")
    target_name = b.get("doctor_name") if body.module == "consultation" else b.get("partner_name")
    doc = {"review_id": mp.uid("rev"), "booking_id": body.booking_id, "module": body.module,
           "target_id": target, "target_name": target_name,
           "service_name": b.get("service_name") or f"Consultation — Dr. {b.get('doctor_name', '')}",
           "customer_name": b["customer"]["name"], "rating": body.rating, "comment": body.comment,
           "at": mp.now()}
    await Db.mp_reviews.insert_one(doc)
    doc.pop("_id", None)
    return {"success": True, "review": doc}


@router.get("/admin/platform-wallet")
async def admin_platform_wallet(x_admin_token: str = Header(None)):
    v = mp.verify_admin_dep()
    r = v(x_admin_token=x_admin_token, admin_session=None)
    if hasattr(r, "__await__"):
        await r
    bal = await mp.wallet_balance("platform", "main")
    ledger = await Db.mp_wallet_ledger.find({"owner_type": "platform", "owner_id": "main"},
                                            {"_id": 0}).sort("at", -1).to_list(500)
    summary = {"customer_commission": 0.0, "partner_commission": 0.0, "doctor_commission": 0.0,
               "customer_paid": 0.0, "provider_payout": 0.0, "bookings": 0}
    for l in ledger:
        m = l.get("meta") or {}
        if not m:
            continue
        cust = m.get("customer_commission", round(float(m.get("customer_paid", 0)) - float(m.get("listed_price", 0)), 2))
        prov = m.get("partner_commission", m.get("commission", 0))
        m.setdefault("customer_commission", cust)
        m.setdefault("partner_commission", prov)
        summary["customer_commission"] += float(cust or 0)
        summary["doctor_commission" if str(l.get("booking_id", "")).startswith("CG-C") else "partner_commission"] += float(prov or 0)
        summary["customer_paid"] += float(m.get("customer_paid") or 0)
        summary["provider_payout"] += float(m.get("you_earn") or 0)
        summary["bookings"] += 1
    summary = {k: round(v, 2) if isinstance(v, float) else v for k, v in summary.items()}
    return {"balance": bal, "ledger": ledger[:200], "summary": summary}


# ================================================================ partner custom services + pricing
class CustomServiceIn(BaseModel):
    name: str
    category_id: str = ""
    short_desc: str = ""
    full_desc: str = ""
    duration_min: int = 60
    price: float
    includes: List[str] = []


@router.post("/partner/services/custom")
async def partner_create_custom_service(body: CustomServiceIn, authorization: str = Header(None)):
    p = await _partner(authorization)
    if body.price <= 0 or not body.name.strip():
        raise HTTPException(400, "Name and price are required")
    cat = await Db.mp_categories.find_one({"cat_id": body.category_id}, {"_id": 0}) if body.category_id else None
    sid = mp.uid("svc")
    await Db.mp_services.insert_one({
        "service_id": sid, "name": body.name.strip(), "category_id": body.category_id,
        "category_title": (cat or {}).get("title", ""), "short_desc": body.short_desc,
        "full_desc": body.full_desc or body.short_desc, "includes": body.includes, "excludes": [],
        "duration_min": body.duration_min, "mode": "home", "price": body.price, "tax_pct": 0,
        "offer_eligible": True, "cancellation_policy": "", "qualifications": [], "equipment": "", "prep": "",
        "aftercare": "", "warnings": "", "patch_test": False, "materials_included": True, "locations": [],
        "age_restriction": "", "images": [], "thumbnail": "", "status": "pending_review",
        "created_by": p["partner_id"],
        "created_by_name": p["applicant"].get("business_name") or p["applicant"]["name"],
        "created_at": mp.now(), "updated_at": mp.now()})
    await Db.mp_partners.update_one({"partner_id": p["partner_id"]}, {"$push": {"services": {
        "service_id": sid, "service_name": body.name.strip(), "mode": "home", "price": body.price,
        "coverage": "", "qualifications": "", "approval_status": "pending", "custom": True}}})
    await mp.notify("admin", "all", "Custom service for review", f"{p['applicant']['name']} created {body.name}",
                    "/admin/partners")
    return {"success": True, "service_id": sid, "status": "pending_review"}


@router.post("/partner/services/{service_id}/image")
async def partner_custom_service_image(service_id: str, file: UploadFile = File(...), authorization: str = Header(None)):
    p = await _partner(authorization)
    svc = await Db.mp_services.find_one({"service_id": service_id, "created_by": p["partner_id"]}, {"_id": 0})
    if not svc:
        raise HTTPException(404, "You can add images only to services you created")
    data = await file.read()
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(400, "Image must be under 8MB")
    if (file.content_type or "") not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(400, "Only JPG, PNG or WebP images are allowed")
    ext = (file.filename or "img.jpg").rsplit(".", 1)[-1].lower()
    url = await mp.store_image(data, f"svc-{service_id}-{secrets.token_hex(3)}", ext)
    images = (svc.get("images") or []) + [url]
    await Db.mp_services.update_one({"service_id": service_id}, {"$set": {
        "images": images, "thumbnail": svc.get("thumbnail") or url, "updated_at": mp.now()}})
    return {"success": True, "url": url}


@router.put("/partner/services/{service_id}/price")
async def partner_update_price(service_id: str, body: Dict[str, float], authorization: str = Header(None)):
    p = await _partner(authorization)
    price = float(body.get("price") or 0)
    if price <= 0:
        raise HTTPException(400, "Price must be positive")
    res = await Db.mp_partners.update_one({"partner_id": p["partner_id"], "services.service_id": service_id},
                                          {"$set": {"services.$.price": price}})
    if not res.matched_count:
        raise HTTPException(404, "Service not in your list")
    await Db.mp_services.update_one({"service_id": service_id, "created_by": p["partner_id"]}, {"$set": {"price": price}})
    return {"success": True, "price": price}


@router.get("/provider/pricing")
async def provider_pricing(base: float = 1000):
    """What a provider earns from a listed price (commission only — customer markup is not shown)."""
    c = await mp.cfg()
    pv = mp.price_view(base, c)
    return {"listed": pv["base"], "commission_pct": c.get("platform_commission_pct", 15),
            "you_earn": pv["provider_earning"]}

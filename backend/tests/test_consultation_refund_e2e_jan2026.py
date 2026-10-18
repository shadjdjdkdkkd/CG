"""End-to-end refund flow test: seed paid consult -> cancel-refund (wallet credit) + refund-request -> admin process."""
import os
import asyncio
import uuid
import datetime as dt
import pytest
import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME")
ADMIN_PASSWORD = "celestaglow2024"


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/admin/login", json={"password": ADMIN_PASSWORD}, timeout=15)
    return r.json()["token"]


@pytest.fixture(scope="module")
def seeded():
    """Seed a paid consultation directly in Mongo and clean up afterwards."""
    assert MONGO_URL and DB_NAME, "Mongo env missing"
    bid = f"CG-C-TEST-{uuid.uuid4().hex[:8].upper()}"
    email = f"test_{uuid.uuid4().hex[:6]}@celestaglow.test"
    doc = {
        "booking_id": bid, "doctor_id": "doc_TESTSEED", "doctor_name": "Test Doc",
        "type": "instant", "date": dt.date.today().isoformat(), "slot": "Instant",
        "customer": {"name": "Tester", "email": email, "phone": "9999999999"},
        "fee": 500, "base_fee": 500, "mrp": 500,
        "status": "pending_assignment", "payment_status": "paid",
        "payment_method": "online", "created_at": dt.datetime.utcnow().isoformat(),
        "updated_at": dt.datetime.utcnow().isoformat(),
    }

    async def _seed():
        c = AsyncIOMotorClient(MONGO_URL)
        db = c[DB_NAME]
        await db.mp_consultations.insert_one(doc)
        c.close()

    async def _cleanup():
        c = AsyncIOMotorClient(MONGO_URL)
        db = c[DB_NAME]
        await db.mp_consultations.delete_one({"booking_id": bid})
        await db.mp_wallet_ledger.delete_many({"owner_type": "customer", "owner_id": email})
        await db.mp_refunds.delete_many({"customer_email": email})
        c.close()

    asyncio.run(_seed())
    yield {"booking_id": bid, "email": email}
    asyncio.run(_cleanup())


def test_cancel_refund_credits_wallet(seeded):
    bid = seeded["booking_id"]
    email = seeded["email"]
    r = requests.post(f"{BASE_URL}/api/mp/consultations/{bid}/cancel-refund",
                      json={"email": email}, timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data.get("success") is True
    assert float(data.get("refunded", 0)) == 500.0

    # Verify wallet ledger via direct DB (no public endpoint for anon customer wallet)
    async def _check():
        c = AsyncIOMotorClient(MONGO_URL)
        db = c[DB_NAME]
        entries = await db.mp_wallet_ledger.find(
            {"owner_type": "customer", "owner_id": email, "type": "credit"}).to_list(10)
        booking = await db.mp_consultations.find_one({"booking_id": bid})
        c.close()
        return entries, booking

    entries, booking = asyncio.run(_check())
    assert len(entries) >= 1
    assert any(float(e.get("amount", 0)) == 500.0 for e in entries)
    assert booking["status"] == "refunded"


def test_refund_request_and_admin_process(admin_token):
    """Second seed: already-connected scenario → refund-request creates pending → admin processes."""
    bid = f"CG-C-TEST-{uuid.uuid4().hex[:8].upper()}"
    email = f"test_{uuid.uuid4().hex[:6]}@celestaglow.test"

    async def _seed():
        c = AsyncIOMotorClient(MONGO_URL)
        db = c[DB_NAME]
        await db.mp_consultations.insert_one({
            "booking_id": bid, "doctor_id": "doc_X", "doctor_name": "X",
            "type": "instant", "date": dt.date.today().isoformat(), "slot": "Instant",
            "customer": {"name": "Tester", "email": email, "phone": "9999"},
            "fee": 300, "status": "completed", "payment_status": "paid",
            "created_at": dt.datetime.utcnow().isoformat(),
            "updated_at": dt.datetime.utcnow().isoformat()})
        c.close()

    async def _cleanup():
        c = AsyncIOMotorClient(MONGO_URL)
        db = c[DB_NAME]
        await db.mp_consultations.delete_one({"booking_id": bid})
        await db.mp_wallet_ledger.delete_many({"owner_type": "customer", "owner_id": email})
        await db.mp_refunds.delete_many({"customer_email": email})
        c.close()

    asyncio.run(_seed())
    try:
        # Create refund request
        r = requests.post(f"{BASE_URL}/api/mp/consultations/{bid}/refund-request",
                          json={"email": email, "reason": "test"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json().get("success") is True

        # List pending refunds via admin
        headers = {"X-Admin-Token": admin_token}
        r2 = requests.get(f"{BASE_URL}/api/mp/admin/refunds",
                          params={"status": "pending"}, headers=headers, timeout=15)
        assert r2.status_code == 200
        rows = r2.json()
        ours = [x for x in rows if x.get("booking_id") == bid]
        assert len(ours) == 1
        refund_id = ours[0]["refund_id"]
        assert float(ours[0]["amount"]) == 300.0

        # Admin process to wallet
        r3 = requests.post(f"{BASE_URL}/api/mp/admin/refunds/{refund_id}/process",
                           json={"action": "refunded", "to": "wallet"},
                           headers=headers, timeout=15)
        assert r3.status_code == 200, r3.text
        assert r3.json().get("success") is True

        # Verify wallet credited
        async def _check():
            c = AsyncIOMotorClient(MONGO_URL)
            db = c[DB_NAME]
            entries = await db.mp_wallet_ledger.find(
                {"owner_type": "customer", "owner_id": email, "type": "credit"}).to_list(10)
            c.close()
            return entries

        entries = asyncio.run(_check())
        assert any(float(e.get("amount", 0)) == 300.0 for e in entries)
    finally:
        asyncio.run(_cleanup())

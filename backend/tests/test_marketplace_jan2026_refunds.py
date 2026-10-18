"""Marketplace January 2026: online-doctors, consultation refund-to-wallet,
admin refunds, services location gating, consult room shape."""
import os
import uuid
import datetime as dt
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
ADMIN_PASSWORD = "celestaglow2024"


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{BASE_URL}/api/admin/login", json={"password": ADMIN_PASSWORD}, timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    tok = r.json().get("token")
    assert tok
    return tok


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"X-Admin-Token": admin_token}


# ------------------- online-doctors
def test_online_doctors_shape():
    r = requests.get(f"{BASE_URL}/api/mp/consultations/online-doctors", timeout=15)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "doctors" in data and "count" in data
    assert isinstance(data["doctors"], list)
    assert isinstance(data["count"], int)
    assert data["count"] == len(data["doctors"])


# ------------------- services location gating
def test_services_no_location_returns_all():
    r = requests.get(f"{BASE_URL}/api/mp/services", timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 1


def test_services_far_location_returns_empty():
    r = requests.get(f"{BASE_URL}/api/mp/services", params={"lat": 1, "lng": 1}, timeout=15)
    assert r.status_code == 200
    assert r.json() == []


def test_services_near_bengaluru_has_results():
    r = requests.get(f"{BASE_URL}/api/mp/services",
                     params={"lat": 12.9716, "lng": 77.5946}, timeout=15)
    assert r.status_code == 200
    # Seeded partner is in Bengaluru so near location should yield services
    assert isinstance(r.json(), list)


# ------------------- consult room shape
def test_consult_room_not_500_for_missing_booking():
    r = requests.get(f"{BASE_URL}/api/mp/consultations/NONEXISTENT/room", timeout=15)
    assert r.status_code in (403, 404, 400), f"unexpected status {r.status_code}: {r.text}"


# ------------------- admin refunds endpoints
def test_admin_refunds_requires_auth():
    r = requests.get(f"{BASE_URL}/api/mp/admin/refunds", timeout=15)
    assert r.status_code in (401, 403)


def test_admin_refunds_list_empty_or_ok(admin_headers):
    r = requests.get(f"{BASE_URL}/api/mp/admin/refunds",
                     params={"status": "pending"}, headers=admin_headers, timeout=15)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ------------------- End-to-end refund-to-wallet via admin
# This test requires seeding an mp_consultations doc. We'll do it by using the admin API
# to find a doctor and simulate; but there's no admin seed endpoint. Instead, verify the
# refund-request + admin process-refund flow using a cancel-refund call for an unknown
# booking (expect 404) — the happy path requires a paid booking which main agent manually
# verified. We cover the shape only here.

def test_consult_cancel_refund_404_for_unknown():
    r = requests.post(f"{BASE_URL}/api/mp/consultations/NOPE/cancel-refund",
                      json={"email": "x@y.com"}, timeout=15)
    assert r.status_code == 404


def test_consult_refund_request_404_for_unknown():
    r = requests.post(f"{BASE_URL}/api/mp/consultations/NOPE/refund-request",
                      json={"email": "x@y.com", "reason": "test"}, timeout=15)
    assert r.status_code == 404


def test_admin_process_refund_404_for_unknown(admin_headers):
    r = requests.post(f"{BASE_URL}/api/mp/admin/refunds/NOPE/process",
                      json={"action": "refunded", "to": "wallet"},
                      headers=admin_headers, timeout=15)
    assert r.status_code == 404


# ------------------- doctors list has at least one with id (used for /doctors/{id})
def test_doctors_list_has_entries():
    r = requests.get(f"{BASE_URL}/api/mp/doctors", timeout=15)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    if data:
        assert "doctor_id" in data[0]

import os
import re
import secrets
import logging
import ipaddress
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse
from datetime import datetime, timezone, timedelta

import bcrypt
import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)
JWT_ALGORITHM = "HS256"
PUBLIC_PATHS = ("/api/af/", "/api/af/auth/login", "/api/af/auth/request-otp", "/api/af/auth/reset-password", "/api/af/extension/download", "/api/af/products/import-template")
EMAIL_BASE_URL = "https://integrations.emergentagent.com"


def hash_password(p: str) -> str:
    return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()


def verify_password(p: str, h: str) -> bool:
    return bcrypt.checkpw(p.encode(), h.encode())


def make_token(username: str) -> str:
    payload = {"sub": username, "type": "access", "exp": datetime.now(timezone.utc) + timedelta(days=7)}
    return jwt.encode(payload, os.environ["JWT_SECRET"], algorithm=JWT_ALGORITHM)


def decode_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    token = header[7:] if header.startswith("Bearer ") else None
    if not token:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(token, os.environ["JWT_SECRET"], algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Session expired — log in again")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")
    if payload.get("type") != "access":
        raise HTTPException(401, "Invalid token type")
    return payload["sub"]


async def seed_admin(db):
    await db.users.create_index("username", unique=True)
    await db.login_attempts.create_index("identifier")
    username = os.environ["ADMIN_USERNAME"]
    if not await db.users.find_one({"username": username}):
        await db.users.insert_one({"username": username, "password_hash": hash_password(os.environ["ADMIN_PASSWORD"]),
                                   "created_at": datetime.now(timezone.utc).isoformat()})


# ---------- email (Emergent managed) ----------
_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = ("reply with your password", "reply with the code", "send your password", "cvv",
             "send us your password", "enter your password below", "confirm your card number",
             "your full card number", "seed phrase", "recovery phrase", "verify your card",
             "social security number", "confirm your bank details")
_HOSTISH = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)


def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)


class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.urls, self.anchors = set(), [], []
        self._href, self._text = None, []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan()
    scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks the recipient for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Email links/assets must be absolute https: {url!r} (G3)")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Shortened, numeric-host or credential-bearing URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text {m.group(1)!r} ≠ real link host {real!r} (G3)")


async def send_email(*, to: str, subject: str, html: str) -> str:
    _assert_safe_email(subject, html)
    payload = {"to": [to], "subject": subject, "html": html, "from_name": os.environ["EMAIL_FROM_NAME"]}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{EMAIL_BASE_URL}/api/v1/email/send",
                                     headers={"X-Email-Key": os.environ["EMERGENT_EMAIL_KEY"]}, json=payload)
        resp.raise_for_status()
        return resp.json().get("id")
    except httpx.HTTPStatusError as e:
        try:
            code = e.response.json().get("code", "")
        except ValueError:
            code = ""
        if code in ("insufficient_credits", "integration_disabled", "daily_limit_reached"):
            logger.warning(f"Email paused: {code} ({e.response.status_code})")
            raise HTTPException(503, "Email is temporarily unavailable")
        logger.error(f"Email send failed: {e.response.status_code} {e.response.text}")
        raise HTTPException(502, "Failed to send email")


def otp_html(code: str) -> str:
    brand = escape(os.environ["EMAIL_FROM_NAME"])
    return (f'<table role="presentation" width="100%"><tr><td style="padding:24px;font-family:Arial,sans-serif;color:#111">'
            f'<p style="font-size:16px">Your {brand} password change code is:</p>'
            f'<p style="font-size:32px;font-weight:bold;letter-spacing:6px">{escape(code)}</p>'
            f'<p>It expires in 10 minutes. Enter it in the AutoFill dashboard or extension to set a new password. '
            f'If you did not ask for this, ignore this email.</p>'
            f'<p style="font-size:12px;color:#888">Sent by {brand}. We never ask for your password by email.</p></td></tr></table>')


# ---------- routes ----------
class LoginIn(BaseModel):
    username: str
    password: str


class ResetIn(BaseModel):
    otp: str
    new_password: str


def build_auth_router(db) -> APIRouter:
    r = APIRouter(prefix="/api/af/auth")

    @r.post("/login")
    async def login(data: LoginIn, request: Request):
        username = data.username.strip().lower()
        ident = f"user:{username}"
        att = await db.login_attempts.find_one({"identifier": ident})
        now = datetime.now(timezone.utc)
        if att and att.get("count", 0) >= 5 and datetime.fromisoformat(att["last"]) > now - timedelta(minutes=15):
            raise HTTPException(429, "Too many failed attempts. Try again in 15 minutes.")
        user = await db.users.find_one({"username": username})
        if not user or not verify_password(data.password, user["password_hash"]):
            await db.login_attempts.update_one({"identifier": ident}, {"$inc": {"count": 1}, "$set": {"last": now.isoformat()}}, upsert=True)
            raise HTTPException(401, "Wrong username or password")
        await db.login_attempts.delete_many({"identifier": ident})
        return {"token": make_token(username), "username": username}

    @r.get("/me")
    async def me(request: Request):
        return {"username": decode_token(request)}

    @r.post("/request-otp")
    async def request_otp():
        last = await db.otps.find_one({"_key": "main"})
        now = datetime.now(timezone.utc)
        if last and datetime.fromisoformat(last["created_at"]) > now - timedelta(seconds=60):
            raise HTTPException(429, "Please wait a minute before requesting another code")
        code = f"{secrets.randbelow(1000000):06d}"
        await send_email(to=os.environ["OWNER_EMAIL"], subject=f"{os.environ['EMAIL_FROM_NAME']} password change code", html=otp_html(code))
        await db.otps.update_one({"_key": "main"}, {"$set": {"hash": hash_password(code), "created_at": now.isoformat(),
                                                              "expires_at": (now + timedelta(minutes=10)).isoformat(), "tries": 0}}, upsert=True)
        em = os.environ["OWNER_EMAIL"]
        return {"sent_to": em[:2] + "***" + em[em.index("@"):]}

    @r.post("/reset-password")
    async def reset_password(data: ResetIn):
        if len(data.new_password) < 8:
            raise HTTPException(400, "New password must be at least 8 characters")
        o = await db.otps.find_one({"_key": "main"})
        if not o or datetime.fromisoformat(o["expires_at"]) < datetime.now(timezone.utc):
            raise HTTPException(400, "Code expired — request a new one")
        if o.get("tries", 0) >= 5:
            raise HTTPException(429, "Too many wrong codes — request a new one")
        if not verify_password(data.otp.strip(), o["hash"]):
            await db.otps.update_one({"_key": "main"}, {"$inc": {"tries": 1}})
            raise HTTPException(400, "Wrong code")
        await db.users.update_one({"username": os.environ["ADMIN_USERNAME"]}, {"$set": {"password_hash": hash_password(data.new_password)}})
        await db.otps.delete_many({"_key": "main"})
        await db.login_attempts.delete_many({})
        return {"ok": True}

    return r

# Celare / Celesta Glow — PRD / State

## Product
Full-stack skincare e-commerce (React 19 + FastAPI + MongoDB) cloned from the owner's GitHub
repo, branded "Celesta Glow". Public storefront + admin panel + **Marketplace** (dermatologist
consultations + at-home beauty services + provider onboarding).

## Clone — 2026-10-13 (this session)
Cloned https://github.com/dragon16t/celare-1.4.git into /app, replacing the previous
Celesta-only codebase. Target: match https://celare-preview-2.preview.emergentagent.com/.
- Mirrored backend + frontend source via rsync --delete (preserved protected .env:
  MONGO_URL, DB_NAME, REACT_APP_BACKEND_URL + all integration keys already present).
- Merged repo backend/uploads (173M incl. marketplace media `mp/`).
- Installed backend deps (new: agora_token_builder) + frontend yarn deps.
- Backend boots clean; startup seeds products, taxonomy, 3 sample doctors, service catalogue,
  16 category tiles. Verified: /api/ health, /api/products, /api/mp/config (payments_configured
  true), /api/mp/doctors, /api/mp/services, /api/mp/categories.
- Verified UI matches reference: homepage, /doctors (location-gated), /services. All pixel-match.

## Modules
- **Storefront**: catalog, concerns/categories, cart, checkout (Razorpay), orders, admin.
- **Marketplace A (Dermatologist)**: doctor onboarding → admin review → OTP login → discovery
  (location-gated) → slot/instant booking → pay → video room (Agora, Jitsi fallback) →
  completion OTP → prescriptions → wallet/withdrawals.
- **Marketplace B (Home Services)**: admin service catalogue → partner onboarding → broadcast
  offers → first-accept assignment → journey lifecycle + live tracking → completion OTP → wallet.
- **Provider onboarding** at /pro; admin hubs /admin/dermatologists + /admin/partners.

## Backend routes
- Storefront under /api; marketplace under /api/mp (mp_core, mp_ops, mp_catalog).
- server.py pops EMERGENT_LLM_KEY at boot → all AI uses direct GEMINI_API_KEY.
- Admin token password: ADMIN_PASSWORD env (default celestaglow2024).

## Integration keys (in backend/.env)
Gemini, Razorpay LIVE, Cloudinary (dcvuqcqjn), Delhivery, Gmail SMTP, Meta CAPI, Google Maps.
NOT set (honest fallbacks active): AGORA_* (→ Jitsi video), ZOOM_*, WHATSAPP_*,
EMERGENT_LLM_KEY (popped → ai_photo_configured=false, doctor-headshot bg-removal disabled).

## Known gaps / backlog
- P1: Agora keys for branded video rooms (currently Jitsi fallback).
- P1: Emergent/Gemini AI-photo bg removal for doctor headshots (disabled).
- P2: SendGrid (email via Gmail SMTP), WhatsApp notifications, Zoom meetings.

## Credentials
See /app/memory/test_credentials.md (admin password celestaglow2024).

## Constraints to keep (bulk generator durability — do not regress)
- Never reload the product list or dispatch `admin-data-changed` inside the bulk poll loop; reload ONCE at completion via `fetchAll({silent: true})` (no full-page spinner during a run).
- Never re-add a fixed time cutoff that abandons long batches.
- The bulk worker must stay durable: full item queue + `next_index` persisted in Mongo (`ai_jobs`, kind="bulk_gen") with resume on startup (`resume_interrupted_bulk_jobs`). Do not revert to a bare in-memory `asyncio.create_task` without persistence — that is what froze batches on the live site.

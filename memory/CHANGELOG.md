# Changelog — Celesta Glow marketplace

## 2026 — Re-clone celare-1.4 + marketplace overhaul
Re-cloned github.com/dragon16t/celare-1.4 into /app; matches reference celare-preview-2.

### Integrations
- Agora RTC video keys wired (AGORA_APP_ID + AGORA_APP_CERTIFICATE; REACT_APP_AGORA_APP_ID).
  AgoraCall uses app_id+token from the backend room endpoint. Video media itself needs a live
  2-party test (camera) — not scriptable here.
- SendGrid key user sent was truncated → email stays on live Gmail SMTP.

### Phases 1–4 (tested — iteration_7)
- Copy/titles, rich "not available at location" empty states, gender picker + badges,
  wallet cash-commission-as-negative, withdrawal rules (min ₹100 / ≤balance / 2/day),
  admin Withdrawals tabs (both hubs), support-ticket runtime crash fix, dermatologist photos,
  non-stop partner alarm, removed double cash step, rebook, service location gating,
  All Dermatologists admin section (edit-all + soft remove), consolidated Service Partner
  Manager to ONE "Service Catalog & Content" tab (removed 3 duplicate tabs; absorbed
  per-service image + description; Women/Men gender filter).

### Phase 5 — doctor instant-consult flow (tested — iteration_8, backend 13/13 pass)
- GET /consultations/online-doctors: rate card of dermatologists online now (name/title/photo/fee).
- InstantConsultModal rebuilt: SELECT online doctor (rate card) → form → pay → ring → ready;
  on no-answer, "Refund to my wallet" or "Keep waiting". Modal now renders regardless of the
  location gate on /doctors (bug fix — previously hidden until location granted).
- DoctorInstantRequests: ring loops every 2s until the doctor accepts/declines (was single beep).
- Refunds: POST /consultations/{id}/cancel-refund (no doctor → refund fee to customer wallet),
  POST /consultations/{id}/refund-request (→ admin), GET/POST /admin/refunds (+process → credits
  customer wallet). NEW admin "Refunds" tab in both hubs. Verified e2e via seeded paid booking.
- Prescription IMAGE: POST /doctor/bookings/{id}/prescription/image (doctor upload),
  GET /consultations/{id}/prescription (customer fetch incl images); upload button in consult room.
  Existing PDF download already works for the user.

### Remaining from latest bug report (NOT yet done) — Phase 6
- Live 2-party video-media test (confirm Agora joins; currently keys set + token issued).
- Service-PARTNER booking parity: same ring/refund flow for home bookings (consult done; home
  partly — admin refund supports module=home, but no customer cancel-refund-to-wallet for home yet).
- Shop by concern/category: auto-map new products to matching section; show the SAME homepage
  product card (one variation) on concern/category pages instead of 24 variations.
- Product page "Ingredients Spotlight": make layout linear/perfect.
- Instant booking payment ledger surfacing + recall polish (rejoin + rebook already exist).

### Phase 6 — Shop concern/category + Amazon/Flipkart section
- Concern/Category pages: backend /api/concerns/{slug} & /api/categories/{slug} now exclude
  variations (is_variation != true) so only the ONE main product shows (not 24 variations).
  Removed the big "Dermatologist Tested" badge from the listing ProductCard so cards match the
  homepage card exactly. Base products are tagged with concerns+category, so mapping works for
  existing and newly added products.
- Admin sidebar shortcut "Amazon & Flipkart Listing" (/admin/amazon-flipkart):
  - AI listing generator (title/bullets/description/search-terms) per product + platform, using
    the store Gemini key with a FREE Emergent universal-key fallback (LISTING_AI_KEY) since the
    user's Gemini credits are exhausted. Verified generating real Flipkart/Amazon copy.
  - "Download Chrome Extension (.zip)": packages the AutoFill AI MV3 extension from
    github.com/dragon16t/chrome-extension (/app/backend/af_extension) with the backend URL
    injected into config.js. Verified 10-file zip downloads.

### Honest constraint (chrome-extension full merge)
The repo is a STANDALONE full-stack app (its own 1155-line FastAPI /api backend + a separate CRA
dashboard using @/ path aliases). It cannot be merged in-place into the live Celesta store because
(a) its routes (/api/products, /api/settings, /api/auth…) collide with the store's own backend,
(b) it reads EMERGENT_LLM_KEY which the store pops at startup, and (c) the platform runs ONE
backend (8001) + ONE frontend (3000). Delivered the extension itself + an AI listing tool inside
admin. Recommended: deploy the chrome-extension repo as its OWN Emergent app and link it from the
shortcut. Not done this turn (budget): live video-media test, service-partner booking parity for
refunds, product "Ingredients Spotlight" linear layout.

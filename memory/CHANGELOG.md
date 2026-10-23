# Changelog — Celesta Glow marketplace

## 2026 — Re-clone celare-1.4 + marketplace overhaul
Re-cloned github.com/dragon16t/celare-1.4 into /app; matches reference celare-preview-2.

### Integrations
- Agora RTC video keys wired (AGORA_APP_ID + AGORA_APP_CERTIFICATE; REACT_APP_AGORA_APP_ID).
  AgoraCall uses app_id+token from the backend room endpoint.

## 2026-10-22 — AGORA KEYS RESET (iteration_10) — VERIFIED
- User again reported "connection failed". Root: a prior secret save accidentally put the
  CERTIFICATE value into AGORA_APP_ID (both became ebb1fcca…), so app_id was wrong.
- User supplied the real new pair via chat; set backend/.env AGORA_APP_ID=dde350…ce9e and
  AGORA_APP_CERTIFICATE=ebb1…302f (distinct), frontend REACT_APP_AGORA_APP_ID=dde350…ce9e.
- No Agora values are stored in the DB (scanned mp_config/site_settings/admin_settings) — env only.
- Verified via testing agent (iteration_10): two simultaneous browser contexts on the real
  /consult-room UI — both reach LIVE, each remote <video> playing (readyState=4), End call →
  ended screen, Rejoin re-establishes bidirectional video, room endpoint 403s bad tokens, zero
  CAN_NOT_GET_GATEWAY_SERVER / invalid-vendor-key errors. Bug fixed with new credentials.
- Also swallowed benign OPERATION_ABORTED (StrictMode double-mount) in AgoraCall error handler.
- NOTE for production: backend AGORA_* live values must match preview. The published secret store
  still had the wrong app_id at one point — user must keep Re-publish→Secrets AGORA_APP_ID =
  dde350…ce9e (NOT the certificate) so production matches, then re-publish.

## 2026-10-22 — AI VARIATIONS + E-COMMERCE IMAGE GENERATOR (iteration_11)
- Variation activation bug fixed: AdminProducts.updateProduct validated name/niche on partial
  patches → toggleActive blocked with "Please enter a product name". Fix: __skipValidation flag on
  toggle; control keys stripped before PUT.
- Variations now created ACTIVE by default (frontend + CreateVariationRequest.is_active=True) and
  build FULL image set via gallery_composer.generate_and_persist (hero + 4 formula cards +
  certificate + before/after), bottle extracted from the generated hero.
- AI keys: Gemini direct first; Emergent universal key fallback (LISTING_AI_KEY) since brand
  GEMINI_API_KEY is exhausted. Applies to variation text+image and ecom images.
- NEW: E-commerce Image Generator (/admin/ecom-images, sidebar "E-commerce Image Generator",
  page EcomImageGenerator.js, backend POST/GET /admin/products/{slug}/ecom-images).
  Amazon squares 1000x1000 + Flipkart tall 1179x2010 (img1 = Amazon hero identical; imgs 2+ =
  square creative centred on tall white canvas). Brand palette (emerald/mint/slate/gold), Derma-Co
  layout templates persisted in backend/assets/ecom_refs/*.webp fed as IMAGE 2; product's own hero
  photo fed as IMAGE 1 (container ground truth). Images persist on product doc (ecom_images,
  merged by slot) and reload on reopen. Per-slot prompt editor (pencil icon) saves custom prompts
  to product.ecom_prompts (GET/PUT /ecom-prompts; empty prompt resets to default).
- Picker uses admin-mode fetch (?active_only=false&include_variations=true) so inactive /
  out-of-stock / variation products all appear in search (was hiding them → "product not coming
  on search" bug).
- Product-photo bug fix (user-reported): container was sometimes invented / textures were serum.
  Now HARD RULES in _ecom_prompt: exact container from IMAGE 1 in every creative (except
  how_it_works which is a pure infographic — no product, no cream), WHITE CREAM format only (never
  liquid/serum/gel), no-image → 400 instead of generating a fake bottle. Same cream rule applied
  to _ai_generate_product_image (master hero) + _ai_variation_image_emergent + _ft_prompt.
- Refinements: hero slot = PURE WHITE background (both Amazon + Flipkart); how_it_works = no
  product/cream; richness clause (layered depth, gold dividers, '+' motifs, micro-typography).
- Refinement 2: gradient typography — rule G in _ecom_prompt makes every headline/stat a smooth
  vertical emerald→bright-green gradient with gold shimmer, neatly stacked/aligned, clear of
  product and edges; supporting text stays flat slate. Verified on hero + results creatives.
- Refinement 3: hero headline limited to 1-4 meaningful words (distilled from benefit/result,
  no other text blocks); results claim must be a grammatically perfect 6-9 word sentence composed
  from the product's benefit (fixes garbled "users saw barrier-brighter skin" text).
- Verified visually: retinoid cream hero = white bg + real container + cream swatch;
  how_it_works = infographic only; flipkart img2+ = tall centred canvas. iteration_11 = 100% pass.

## 2026-10-18 — VIDEO CALL BUG FIXED (iteration_9)
- User reported "connection failed" even with a real doctor live. RCA: old Agora App ID was
  rejected by Agora ("invalid vendor key, can not find appid") — dead/invalid project, NOT a code bug.
- User supplied NEW Agora App ID + Primary Certificate → updated backend/.env + frontend/.env,
  services restarted.
- AgoraCall.js instrumented to surface exact Agora error codes in console for future debugging.
- Verified end-to-end via testing agent with TWO simultaneous browser contexts (fake media):
  seeded confirmed consult (TESTVID001, cleaned up after). Both doctor (uid 1001) and customer
  (uid 2002) joined, exchanged live video (subscribe success both ways), mic/cam toggles work,
  End call → ended screen, Rejoin re-establishes bidirectional video. Room endpoint 403s bad tokens.
- Homepage, /doctors, /services regression-checked OK.
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

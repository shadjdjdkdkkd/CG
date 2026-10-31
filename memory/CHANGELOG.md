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

## 2026-10-23 — VIDEO CALLS SWITCHED TO FREE JITSI (production fix)
- User still saw "Connection failed" on LIVE celestaglow.com because production's Agora secret
  still held the wrong value, and agora_service.configured() was true so it never fell back.
- Per user request ("use any free service"): room endpoint (mp_ops.py GET /consultations/{id}/room)
  now honours VIDEO_PROVIDER env (default "jitsi"). Only uses Agora when VIDEO_PROVIDER=agora AND
  configured; otherwise returns provider=jitsi (meet.jit.si, no keys). Default = jitsi → works on
  preview AND production with zero credentials, immediately after deploy.
- Frontend already renders the Jitsi iframe; improved iframe config (disableDeepLinking,
  no prejoin, autoplay) for mobile. Verified in a real browser: room loads, camera works
  ("Your devices are working properly"), End call present — no connection-failed error.
- To go back to Agora later: set VIDEO_PROVIDER=agora and ensure valid AGORA_APP_ID/CERTIFICATE.


## 2026-10-28 — BULK GENERATOR DURABILITY FIX (stall-after-1 + constant refresh)
- Reported: bulk AI generate stops after product 1; admin screen refreshes every ~1.5s during a run.
- Bifrost fixed the constant refresh (frontend/src/pages/admin/AdminProducts.js): poll every 2.5s,
  update progress panel only on change, reload the product list ONCE at completion with
  fetchAll({silent:true}) (no full-page spinner), retry transient poll errors, no 30-min cutoff,
  remember job_id so a page reload resumes the panel.
- Deployer RCA (proven on live): the bulk job was a fire-and-forget in-memory asyncio task; pod
  liveness-kill (nginx /health 1s) and idle scale-down 2->1 destroyed it -> batch froze (1/23).
- Fix (gift_cards_and_ai.py): job now persists the FULL item queue + brand + generate_image +
  next_index to Mongo (ai_jobs) under kind="bulk_gen". Worker takes start_index, saves the resume
  point BEFORE and AFTER each item, and finalises via save_job. New _launch_bulk_worker() holds a
  strong task ref. New resume_interrupted_bulk_jobs() runs on startup (server.py startup_seed) and
  rehydrates any status=running bulk_gen job, rebuilding BulkGenItem list and resuming from
  next_index. Verified: seeded a running job at 1/3, resume completed items 2,3 without redoing 1.
- Also added missing services/ai_content_generator.generate_product_reviews (was imported by
  gift_cards_and_ai + products but never defined -> every product create threw). AI-first with a
  deterministic template fallback so it never blocks a batch or burns credits when key is exhausted.
- CONSTRAINTS TO KEEP: never reload list / dispatch admin-data-changed inside the poll loop; any
  reload during a running job must use fetchAll({silent:true}); never re-add a fixed time cutoff that
  abandons long batches; bulk worker must stay durable (queue+next_index in Mongo) — do not revert to
  a bare in-memory asyncio.create_task without persistence.
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

## 2026-07 — Storefront + admin + bulk generator batch (self-verified, no AI credits spent)

- Homepage: bestsellers section label changed to **"Celesta Glow Bestsellers"**.
- Concern/Category back link: now returns to that page's own shop home (`/skincare` or
  `/cosmetics`) instead of the generic home.
- **Prepaid-only mode**: new admin-dashboard toggle (PrepaidOnlyToggle). When ON, COD is
  hidden at checkout (incl. instant-delivery) and the backend order API rejects COD with
  400. Persists in `site_settings.prepaid_only`. Verified ON/OFF round-trip + COD rejection
  via curl.
- **Bulk AI generator**: durable Mongo-backed queue + `next_index` resume on restart;
  per-item timeout; cancel endpoint (terminal `cancelled`, never auto-resumed); job history
  endpoint; Bulk History modal + Cancel button in admin; polling resumes after page reload
  without a refresh loop. Verified via curl with zero AI calls (seeded dummy jobs, cancel,
  history). Prior production-frozen `1/23` job was caused by in-memory `asyncio` workers
  dying on pod restart — now durable.

- Concern/Category back link now returns to that range's shop home (`/shop?niche=skincare` /
  `/shop?niche=cosmetics`) — verified in browser (label "Back to Skincare", correct URL).
- Bulk generator: **Cancel Generation** button confirmed in admin UI; cancel endpoint sets the
  job to terminal `cancelled` (verified via curl, zero AI calls). Bulk History modal present.

- Shop page: products are now grouped under concern titles (e.g. "Aging", "Sun Protection",
  "Dryness"). Only concerns that have at least one tagged product appear; new AI-created
  products auto-file under their concern (and the concern auto-creates if new). Verified
  8 concern groups render on /shop with product cards beneath each.
- Bulk generator: skips rows whose product already exists (by slug or exact name) and drops
  duplicates within the pasted list, so no credits are spent re-generating them. Skipped
  items appear in Bulk History. Verified via curl (existing product skipped, no AI call).

- Bulk History modal: added a **Cancel** button on any running/queued job so you can stop a
  batch straight from the history panel (not just the live progress bar). Cancels via the
  same durable endpoint (sets job to terminal `cancelled`). Verified via curl, zero AI calls.

### Honest constraint (chrome-extension full merge)
The repo is a STANDALONE full-stack app (its own 1155-line FastAPI /api backend + a separate CRA
dashboard using @/ path aliases). It cannot be merged in-place into the live Celesta store because
(a) its routes (/api/products, /api/settings, /api/auth…) collide with the store's own backend,
(b) it reads EMERGENT_LLM_KEY which the store pops at startup, and (c) the platform runs ONE
backend (8001) + ONE frontend (3000). Delivered the extension itself + an AI listing tool inside
admin. Recommended: deploy the chrome-extension repo as its OWN Emergent app and link it from the
shortcut. Not done this turn (budget): live video-media test, service-partner booking parity for
refunds, product "Ingredients Spotlight" linear layout.

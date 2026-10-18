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

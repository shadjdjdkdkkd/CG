import React, { useEffect, useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import axios from 'axios';
import { ArrowRight, ChevronRight, Flame, Sparkles, ShoppingCart, Star, Truck, Shield, Check, Clock, ScanFace, ClipboardList, BarChart3, Lightbulb, ChevronLeft, TrendingUp } from 'lucide-react';
import { useTracking } from '../providers/TrackingProvider';
import SearchBar from '../components/SearchBar';
import TrustStrip from '../components/TrustStrip';
import SaleBadge from '../components/SaleBadge';
import HomepageSaleStrip from '../components/HomepageSaleStrip';
import NicheHero from '../components/NicheHero';
import InfluencerReelsSection from '../components/InfluencerReelsSection';
import BeforeAfterCarousel from '../components/BeforeAfterCarousel';
import CertificatesStrip from '../components/CertificatesStrip';
import TopBanner from '../components/TopBanner';
import NicheOffersGrid from '../components/NicheOffersGrid';
import HeroCarousel from '../components/HeroCarousel'; // eslint-disable-line no-unused-vars
import { ProductCard } from './ConcernCategoryPage';
import CircularCategoryStrip from '../components/CircularCategoryStrip';
import ServiceModuleCards from '../components/ServiceModuleCards';
import { playCartSound } from '../utils/cartSound';
import ReviewsCarousel from '../components/ReviewsCarousel';
import { cachedGet, peek } from '../utils/apiCache';
import SEOHead, { faqJsonLd, breadcrumbJsonLd } from '../components/SEOHead';
import { trackAddToCart as metaTrackAddToCart } from '../utils/metaPixel';

const API = process.env.REACT_APP_BACKEND_URL;
const ACCENT = '#0f766e';
const ACCENT_DARK = '#115e59';
const ACCENT_BG = '#d1fae5';

const BANNER_IMG = 'https://customer-assets.emergentagent.com/job_cg3-render/artifacts/uscaqcsg_217BA6A6-1F87-44A3-AD2C-F750B48A11EF.png';
/* Mobile-only tighter crop (clean wide cream/serum shot) */
const BANNER_IMG_MOBILE = 'https://images.unsplash.com/photo-1620916566398-39f1143ab7be?auto=format&fit=crop&w=1200&q=80';

/* ---- Cart helpers (preserved API for the rest of the app) ---- */
/* MIGRATED to localStorage so cart survives across tab/browser sessions.
   We still read sessionStorage on first load and copy it forward for users
   mid-session when the deploy ships. */
const _readCart = () => {
  try {
    const ls = localStorage.getItem('cart');
    if (ls) return JSON.parse(ls);
    const ss = sessionStorage.getItem('cart');
    if (ss) { localStorage.setItem('cart', ss); return JSON.parse(ss); }
  } catch {}
  return { items: [] };
};
const getCart = () => _readCart();
const saveCart = (cart) => {
  try { localStorage.setItem('cart', JSON.stringify(cart)); } catch {}
  try { sessionStorage.setItem('cart', JSON.stringify(cart)); } catch {}
  window.dispatchEvent(new Event('cartUpdated'));
};

/**
 * TBL guard helpers — read the apiCache (already populated by every page load)
 * so we can synchronously decide whether a slug/combo is TBL before mutating cart.
 * Falls back to "allow" if cache is empty so a never-visited product still works.
 */
const _readCachedProducts = () => {
  try {
    const raw = window.localStorage.getItem('apiCache_v2');
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    const all = [];
    Object.entries(parsed).forEach(([k, v]) => {
      if (k.includes('/api/products') && Array.isArray(v?.value)) all.push(...v.value);
    });
    return all;
  } catch { return []; }
};
const _readCachedCombos = () => {
  try {
    const raw = window.localStorage.getItem('apiCache_v2');
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    const all = [];
    Object.entries(parsed).forEach(([k, v]) => {
      if (k.includes('/api/combos') && Array.isArray(v?.value)) all.push(...v.value);
    });
    return all;
  } catch { return []; }
};
const isProductTbl = (slug) => {
  const p = _readCachedProducts().find(p => p.slug === slug);
  return p ? !!p.is_to_be_launched : false;
};
const isComboTbl = (comboId) => {
  const products = _readCachedProducts();
  const c = _readCachedCombos().find(c => c.combo_id === comboId);
  if (!c) return false;
  if (c.is_to_be_launched) return true;
  // A combo is also TBL if any of its underlying products is TBL
  return (c.product_slugs || []).some(s => {
    const prod = products.find(p => p.slug === s);
    return prod ? !!prod.is_to_be_launched : false;
  });
};
const _toast = (msg, variant = 'info') => {
  try {
    const t = document.createElement('div');
    t.textContent = msg;
    const colors = variant === 'success'
      ? 'background:#15803d;color:#fff;'
      : variant === 'error'
      ? 'background:#b91c1c;color:#fff;'
      : 'background:#92400e;color:#fff;';
    t.style.cssText = `position:fixed;bottom:84px;left:50%;transform:translateX(-50%);${colors}padding:10px 18px;border-radius:9999px;z-index:9999;font:600 13px system-ui;box-shadow:0 8px 24px rgba(0,0,0,0.18);display:flex;align-items:center;gap:6px;animation:cgToastIn 0.25s ease-out;`;
    document.body.appendChild(t);
    setTimeout(() => { t.style.opacity = '0'; t.style.transition = 'opacity 0.25s'; }, 1700);
    setTimeout(() => t.remove(), 2200);
  } catch {}
};

/**
 * pruneTblItemsFromCart — silently drop any TBL slug/combo from sessionStorage
 * cart so the count badge + cart page can never show TBL items. Idempotent.
 */
const pruneTblItemsFromCart = () => {
  const cart = getCart();
  const before = cart.items.length;
  cart.items = cart.items.filter(i => {
    if (i.product_slug) return !isProductTbl(i.product_slug);
    if (i.combo_id) return !isComboTbl(i.combo_id);
    return true;
  });
  if (cart.items.length !== before) {
    try { localStorage.setItem('cart', JSON.stringify(cart)); } catch {}
    try { sessionStorage.setItem('cart', JSON.stringify(cart)); } catch {}
    window.dispatchEvent(new Event('cartUpdated'));
  }
};
// Run once on module load + every time admin data changes (e.g., admin flips TBL)
if (typeof window !== 'undefined') {
  setTimeout(pruneTblItemsFromCart, 800);
  window.addEventListener('admin-data-changed', pruneTblItemsFromCart);
}

const addToCart = (slug, quantity = 1, shadeId = null, meta = {}) => {
  if (isProductTbl(slug)) {
    _toast('This product is coming soon — not available yet.');
    return false;
  }
  const cart = getCart();
  // Same slug + same shade = same line. Different shades = separate lines.
  const existing = cart.items.find(i => i.product_slug === slug && (i.shade_id || null) === (shadeId || null));
  if (existing) existing.quantity += quantity;
  else cart.items.push({ product_slug: slug, quantity, ...(shadeId ? { shade_id: shadeId } : {}) });
  saveCart(cart);
  playCartSound();
  _toast('✓ Added to bag', 'success');
  try { window.dispatchEvent(new Event('cart-bounce')); } catch {}
  // Meta Pixel — AddToCart. Callers with product context pass real price/name
  // via `meta` for accurate value reporting; other entry points use defaults.
  try { metaTrackAddToCart(meta.price, quantity, meta.name, [slug]); } catch {}
  return true;
};
const addComboToCart = (comboId, quantity = 1) => {
  if (isComboTbl(comboId)) {
    _toast('This kit is coming soon — not available yet.');
    return false;
  }
  const cart = getCart();
  const existing = cart.items.find(i => i.combo_id === comboId);
  if (existing) existing.quantity += quantity;
  else cart.items.push({ combo_id: comboId, quantity });
  saveCart(cart);
  playCartSound();
  _toast('✓ Combo added to bag', 'success');
  try { window.dispatchEvent(new Event('cart-bounce')); } catch {}
  // Meta Pixel — AddToCart for combos
  try { metaTrackAddToCart(undefined, quantity, 'Celesta Glow Combo', [comboId]); } catch {}
  return true;
};
const setProductQty = (slug, quantity, shadeId = null) => {
  if (quantity > 0 && isProductTbl(slug)) {
    _toast('This product is coming soon — not available yet.');
    return;
  }
  const cart = getCart();
  const idx = cart.items.findIndex(i => i.product_slug === slug && (i.shade_id || null) === (shadeId || null));
  const wasZero = idx === -1;
  if (quantity <= 0) {
    if (idx > -1) cart.items.splice(idx, 1);
  } else if (idx > -1) {
    cart.items[idx].quantity = quantity;
  } else {
    cart.items.push({ product_slug: slug, quantity, ...(shadeId ? { shade_id: shadeId } : {}) });
    playCartSound();
    _toast('✓ Added to bag', 'success');
    try { window.dispatchEvent(new Event('cart-bounce')); } catch {}
    try { metaTrackAddToCart(undefined, quantity, undefined, [slug]); } catch {}
  }
  saveCart(cart);
  // Side-effect: increasing quantity for an item already in cart should also nudge the cart icon
  if (!wasZero && quantity > 0 && idx > -1) {
    try { window.dispatchEvent(new Event('cart-bounce')); } catch {}
  }
};
const getProductQty = (slug, shadeId = null) => {
  const cart = getCart();
  // If shadeId specified, return only the matching shade quantity.
  // If shadeId is null, sum all quantities of the same slug (legacy callers).
  if (shadeId) {
    const item = cart.items.find(i => i.product_slug === slug && (i.shade_id || null) === shadeId);
    return item ? item.quantity : 0;
  }
  return cart.items.filter(i => i.product_slug === slug).reduce((s, i) => s + (i.quantity || 0), 0);
};
export { getCart, saveCart, addToCart, addComboToCart, setProductQty, getProductQty, isProductTbl, isComboTbl, pruneTblItemsFromCart };

/**
 * Homepage (Anti-Aging niche home for `/`).
 * Simplified to match Skincare/Cosmetics niche pages:
 *  1. Search bar
 *  2. Hero banner (image-as-background, text overlay left)
 *  3. Trust strip
 *  4. Anti-Aging bestsellers grid
 *  5. Complete Kit (flagship offer)
 *  6. CTA card
 */
function Homepage() {
  const { trackAction } = useTracking();
  // Seed from persistent cache so the page paints instantly on revisit
  const _cachedProducts = peek(`${API}/api/products?niche=skin-care&page=1&limit=20`) || peek(`${API}/api/products?niche=skin-care&page=1&limit=48`) || [];
  const _cachedProductsList = Array.isArray(_cachedProducts) ? _cachedProducts : (_cachedProducts?.items || []);
  const _cachedCombos = peek(`${API}/api/combos`) || [];
  const _cachedSettings = peek(`${API}/api/site-settings`) || {};
  const [products, setProducts] = useState(_cachedProductsList);
  const [combos, setCombos] = useState(_cachedCombos);
  const [settings, setSettings] = useState(_cachedSettings);
  const [concerns, setConcerns] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(_cachedProductsList.length === 0);

  useEffect(() => {
    // Meta Pixel — page-specific PageView event for Homepage
    if (typeof window !== 'undefined' && window.fbq) {
      window.fbq('track', 'PageView', { page_name: 'homepage', content_category: 'Skin Care' });
    }
  }, []);

  useEffect(() => {
    const ctrl = new AbortController();
    const sig = ctrl.signal;

    // ---- 1) Taxonomy + small data first (combos + settings — tiny + heavily cached) ----
    // Renders the page skeleton, hero, concern strip etc. immediately.
    // ---- 1) Taxonomy + small data first ----
    // Use allSettled so one aborted request doesn't block the rest.
    Promise.allSettled([
      cachedGet(`${API}/api/combos`, { ttl: 60_000, signal: sig }),
      cachedGet(`${API}/api/site-settings`, { force: true, signal: sig }),
      cachedGet(`${API}/api/concerns`, { force: true, signal: sig }),
      cachedGet(`${API}/api/categories`, { force: true, signal: sig }),
    ]).then(([c, s, con, cats]) => {
      if (sig.aborted) return;
      if (c.status === 'fulfilled') setCombos(c.value.data || []);
      if (s.status === 'fulfilled') setSettings(s.value.data || {});
      if (con.status === 'fulfilled') setConcerns(con.value.data || []);
      if (cats.status === 'fulfilled') setCategories(cats.value.data || []);
    });

    // ---- 2) Products second — only 20 (the full catalog lives at /shop?niche=skin-care) ----
    // Feb-2026: on the very first paint of a fresh visit, index.html has
    // already fired a top-5 fetch during HTML parse. If that promise
    // exists we hydrate from it immediately (200-500 ms saved on first
    // visit; no-op on cached revisits since setProducts is idempotent).
    if (window.__cgTopProductsPromise) {
      window.__cgTopProductsPromise
        .then((data) => {
          if (sig.aborted || !data) return;
          const items = Array.isArray(data) ? data : (data?.items || []);
          if (items.length) {
            setProducts((prev) => (prev && prev.length ? prev : items));
            setLoading(false);
          }
        })
        .catch(() => {});
    }
    cachedGet(`${API}/api/products?niche=skin-care&page=1&limit=20`, { signal: sig })
      .then((p) => {
        if (sig.aborted) return;
        const items = Array.isArray(p.data) ? p.data : (p.data?.items || []);
        setProducts(items);
      })
      .catch(() => {})
      .finally(() => { if (!sig.aborted) setLoading(false); });

    // Background-prefetch sibling data so categories/concerns are instant.
    const prefetch = () => {
      cachedGet(`${API}/api/concerns`).catch(() => {});
      cachedGet(`${API}/api/categories`).catch(() => {});
    };
    const idleHandle = (window.requestIdleCallback || window.setTimeout)(prefetch, { timeout: 1500 });
    return () => {
      ctrl.abort();
      if (window.cancelIdleCallback && typeof idleHandle === 'number') window.cancelIdleCallback(idleHandle);
    };
  }, []);

  // Per-niche customization (admin-editable). Falls back to hardcoded defaults if missing.
  // Homepage (`/`) is the Anti-Aging niche. Admin saves hero/sections under the
  // `anti-aging` key, so read that (fall back to legacy `skin-care` key if present).
  const niche = (settings?.niche_settings && (settings.niche_settings['anti-aging'] || settings.niche_settings['skin-care'])) || {};
  const hero = niche.hero || {};
  const bs = niche.bestsellers || {};
  const ctaCfg = niche.cta_section || {};
  const accent = hero.accent || ACCENT;
  const accentDark = hero.accent_dark || ACCENT_DARK;
  const accentBg = hero.accent_bg || ACCENT_BG;

  const sortedProducts = useMemo(() => {
    const arr = [...products];
    const by = bs.sort_by || 'reviews_count';
    const tieBreak = (a, b) =>
      ((a.sort_order ?? 99) - (b.sort_order ?? 99)) ||
      String(a.slug || '').localeCompare(String(b.slug || ''));
    if (by === 'reviews_count') {
      arr.sort((a, b) => ((b.reviews_count || 0) - (a.reviews_count || 0)) || tieBreak(a, b));
    } else if (by === 'rating') {
      arr.sort((a, b) => ((b.rating || 0) - (a.rating || 0)) || tieBreak(a, b));
    } else if (by === 'price_asc') {
      arr.sort((a, b) => ((a.prepaid_price || 0) - (b.prepaid_price || 0)) || tieBreak(a, b));
    } else if (by === 'price_desc') {
      arr.sort((a, b) => ((b.prepaid_price || 0) - (a.prepaid_price || 0)) || tieBreak(a, b));
    } else {
      arr.sort(tieBreak);
    }
    // Default to showing ALL products in the niche so newly added products from admin always appear.
    // Admin can still set a custom limit via niche_settings.bestsellers.limit if they want.
    // Always show every product in the niche so newly added admin products are immediately visible.
    return arr;
  }, [products, bs.sort_by]);

  const kit = combos.find(c => c.combo_id === 'complete-anti-aging-kit');

  const handleAddCombo = (id) => { addComboToCart(id); trackAction('add_combo', { combo_id: id }); };

  return (
    <div className="bg-stone-50/40" data-testid="homepage">
      {/* HomepageSaleStrip moved into Navigation so it renders above the
          LocationStrip on every page (was here below the niche banners). */}
      <SEOHead
        title="Dermatologist Recommended Skin Care Brand | Celesta Glow"
        description="Shop dermatologist-recommended vegan skin care products in Kerala, including face serums, cleansers, sunscreen, and moisturizers. Buy now!"
        canonicalPath="/"
        jsonLd={[
          breadcrumbJsonLd([{ name: 'Home', url: '/' }]),
          faqJsonLd([
            { q: 'What is the best skin care brand in India?',
              a: 'Celesta Glow is India\'s #1 complete skin care brand. Our range includes a clinically formulated Serum (Retinol + Niacinamide + Hyaluronic Acid), Night Cream, Under Eye Cream, Sunscreen and Gentle Cleanser, all dermatologist approved for Indian skin.' },
            { q: 'How long does Celesta Glow skin care serum take to work?',
              a: 'Most users notice softer, more hydrated skin within 1-2 weeks. Visible reduction in fine lines and dullness typically appears after 4-6 weeks of consistent daily use.' },
            { q: 'Is Celesta Glow safe for sensitive Indian skin?',
              a: 'Yes. Every formula is developed for Indian skin types and climate — humidity, sun exposure, pollution. Products are dermatologist approved and free of harsh chemicals.' },
            { q: 'What is the return policy?',
              a: 'We accept 7-day returns on unopened, factory-sealed items only. Once a bottle is opened it cannot be returned or refunded for hygiene reasons. Damaged-on-arrival or wrong-item shipments are always covered.' },
            { q: 'Does Celesta Glow ship across India and offer COD?',
              a: 'Yes. Free shipping across all of India with both prepaid and Cash on Delivery (COD) options.' },
          ]),
        ]}
      />
      <SearchBar accent={accent} niche="skin-care" testId="skin-care-search-bar" />

      {/* Top hero banner (independent from the niche hero card) — admin manages
          this via /admin/media-tools → Top Banner. Silent no-op if unset. */}
      <TopBanner />

      <SaleBadge cfg={niche.sale_badge} niche="skin-care" testIdPrefix="skin-care-sale-badge" />

      <NicheHero
        bgImage={hero.image_desktop || ''}
        mobileBgImage={hero.image_mobile || ''}
        eyebrow={null}
        eyebrowDot={accent}
        eyebrowText={accentDark}
        title={null}
        subtitle={null}
        cta1={{ label: hero.cta1_label || 'Shop the routine', to: hero.cta1_link || '/categories' }}
        cta2={{ label: hero.cta2_label || 'Shop With AI', to: hero.cta2_link || '/routine' }}
        accent={accent}
        accentDark={accentDark}
        testId="skin-care-hero"
      />

      <div className="pt-5 sm:pt-7">
        <TrustStrip accent={accent} accentBg={accentBg} />
      </div>

      {/* AI Skin Tracker promo — free 1 month (order ≥ ₹499) then ₹499/mo auto-pay */}
      <TrackerPromo />

      {/* Shop by Concern — circular icon strip like Skincare page */}
      {concerns.length > 0 && (
        <section className="bg-white border-b border-stone-100">
          <div className="max-w-7xl mx-auto px-3 sm:px-6 py-4 sm:py-7">
            <CircularCategoryStrip
              items={concerns}
              routePrefix="/concern"
              title={<>Shop by <span className="italic" style={{ color: accent }}>Concern</span></>}
              subtitle="Find the right solution for your skin"
              accent={accent}
              testIdPrefix="home-concern"
              eagerCount={6}
              showImages={false}
              blankCircles={true}
            />
          </div>
        </section>
      )}

      {/* Shop by Category — circular icon strip */}
      {categories.length > 0 && (
        <section className="bg-white border-b border-stone-100">
          <div className="max-w-7xl mx-auto px-3 sm:px-6 py-4 sm:py-7">
            <CircularCategoryStrip
              items={categories.filter(c => c.is_active !== false && (!c.niche || c.niche === 'skincare' || c.niche === 'skin-care'))}
              routePrefix="/category"
              title={<>Shop by <span className="italic" style={{ color: accent }}>Category</span></>}
              subtitle="Cleanse · Treat · Moisturize · Protect"
              accent={accent}
              testIdPrefix="home-category"
              showImages={false}
              blankCircles={true}
            />
          </div>
        </section>
      )}

      {/* Two-square feature cards — Dermatologist Consultation & Home Services (admin-toggled) */}
      <ServiceModuleCards />

      {/* Mega Bash — compact running-marquee offer strip. Positioned below
          the Search / Shop-by-Concern / Shop-by-Category strips per the
          Feb-2026 layout update. */}
      <section className="bg-white">
        <div className="max-w-7xl mx-auto px-3 sm:px-6 pt-4 sm:pt-6">
          <NicheOffersGrid niche="skin-care" categories={[]} theme="skin-care" />
        </div>
      </section>

      {/* Bestsellers — our 5 products come FIRST on the anti-aging landing,
          combo/Complete-Kit follows below (Feb-2026 user request). */}
      {bs.enabled !== false && (
      <section className="max-w-7xl mx-auto px-3 sm:px-6 pt-6 sm:pt-12" data-testid="skin-care-bestsellers-top">
        <div className="flex items-end justify-between mb-4 sm:mb-6 px-1 sm:px-0">
          <div>
            <p className="text-[10px] sm:text-[11px] font-bold tracking-[0.4em] uppercase mb-1 sm:mb-1.5 flex items-center gap-2" style={{ color: accent }}>
              <Flame size={11} style={{ fill: accent, color: accent }} /> {bs.eyebrow || 'Trending now'}
            </p>
            <h2 className="font-heading text-lg sm:text-2xl lg:text-3xl font-black text-gray-900 leading-tight">
              {(bs.title_prefix && !['Anti-Aging', 'Anti Aging', 'Skin Care', 'Skincare'].includes(bs.title_prefix)) ? bs.title_prefix : 'Celesta Glow'} <span className="italic" style={{ color: accent }}>{bs.title_highlight || 'Bestsellers'}</span>
            </h2>
          </div>
          <Link to="/shop?niche=skin-care" className="text-[11px] sm:text-xs font-bold flex items-center gap-1 hover:underline" style={{ color: accent }}>
            View all <ArrowRight size={12} />
          </Link>
        </div>
        {loading ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3 sm:gap-5 animate-pulse">
            {[...Array(5)].map((_, i) => <div key={i} className="aspect-[3/5] bg-gradient-to-br from-stone-100 to-stone-200 rounded-3xl" />)}
          </div>
        ) : sortedProducts.length === 0 ? (
          <div className="bg-white rounded-2xl p-8 text-center text-sm text-gray-500 ring-1 ring-emerald-100">No bestsellers yet — check back soon.</div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3 sm:gap-5">
            {sortedProducts.map((p, i) => <ProductCard key={p.slug} product={p} priority={i < 4} />)}
          </div>
        )}
      </section>
      )}

      {/* Complete Kit — flagship single-card offer (admin-toggleable) — premium brand-aligned design */}
      {niche.show_complete_kit !== false && kit && (
        <section className="max-w-7xl mx-auto px-3 sm:px-6 pt-6 sm:pt-12" data-testid="complete-kit-section">
          {/* Eyebrow strip */}
          <div className="flex items-center justify-center gap-3 mb-4 sm:mb-6">
            <span className="hidden sm:block h-px w-16 bg-gradient-to-r from-transparent to-emerald-300/70" />
            <span className="inline-flex items-center gap-2 bg-gradient-to-r from-emerald-50 to-amber-50 ring-1 ring-emerald-200/60 px-3.5 py-1.5 rounded-full">
              <Sparkles size={11} className="text-amber-600" />
              <span className="text-[10px] sm:text-[11px] font-black tracking-[0.32em] text-emerald-900 uppercase">Complete Kit · Best Value</span>
              <Sparkles size={11} className="text-amber-600" />
            </span>
            <span className="hidden sm:block h-px w-16 bg-gradient-to-l from-transparent to-emerald-300/70" />
          </div>

          <div className="relative group/kit">
            {/* Outer glow ring */}
            <div className="absolute -inset-px bg-gradient-to-br from-emerald-300/40 via-amber-200/30 to-emerald-300/40 rounded-[28px] blur-[2px] opacity-70 group-hover/kit:opacity-100 transition-opacity duration-700" />

            <div className="relative bg-gradient-to-br from-emerald-950 via-emerald-900 to-emerald-950 rounded-[26px] overflow-hidden shadow-[0_30px_80px_-20px_rgba(6,78,59,0.55)]">
              {/* Decorative pattern */}
              <div className="absolute inset-0 opacity-[0.06] pointer-events-none" style={{ backgroundImage: 'radial-gradient(circle at 1px 1px, #fff 1px, transparent 0)', backgroundSize: '24px 24px' }} />
              {/* Soft corner glows */}
              <div className="absolute -top-24 -right-24 w-72 h-72 rounded-full bg-amber-400/15 blur-3xl pointer-events-none" />
              <div className="absolute -bottom-24 -left-24 w-72 h-72 rounded-full bg-emerald-400/20 blur-3xl pointer-events-none" />
              {/* Animated shimmer line */}
              <div className="absolute top-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-amber-300/70 to-transparent" />

              {/* TOP — 16:9 landscape kit image (admin-managed). Image only, no text overlap. */}
              {(kit.image || settings.bundle_hero_image) && (
                <div className="relative w-full aspect-[16/9] bg-emerald-50 overflow-hidden">
                  <img
                    src={kit.image || settings.bundle_hero_image}
                    alt={kit.name}
                    className="absolute inset-0 w-full h-full object-cover group-hover/kit:scale-[1.02] transition-transform duration-700"
                    data-testid="home-kit-image"
                  />
                </div>
              )}

              {/* CONTENT — sits below the image, no overlap */}
              <div className="relative p-6 sm:p-8 lg:p-10 text-white">
                {/* Savings ribbon — top of content (no longer over the image) */}
                <div className="inline-flex mb-4">
                  <div className="relative bg-gradient-to-r from-amber-400 via-amber-500 to-orange-400 text-emerald-950 font-black text-[10px] sm:text-[11px] px-3 py-1.5 rounded-full shadow-lg shadow-amber-700/30 tracking-[0.16em] uppercase ring-1 ring-amber-300/60">
                    <span className="absolute inset-0 bg-[radial-gradient(circle_at_30%_30%,rgba(255,255,255,0.5),transparent_60%)] rounded-full pointer-events-none" />
                    <span className="relative">Save ₹{(kit.mrp_total - kit.combo_prepaid_price)?.toLocaleString()}</span>
                  </div>
                </div>

                {/* Title */}
                <h3 className="font-heading text-2xl sm:text-3xl lg:text-4xl font-black leading-[1.1] mb-2 sm:mb-3 tracking-tight">
                  {kit.name}
                </h3>

                  <p className="text-xs sm:text-sm text-emerald-100/80 mb-4 sm:mb-5 leading-relaxed line-clamp-2 max-w-xl">{kit.description}</p>

                  {/* Rating + reviews row */}
                  <div className="flex items-center gap-2 mb-4 sm:mb-5">
                    <div className="flex">
                      {[1,2,3,4,5].map(i => <Star key={i} size={13} className="fill-amber-300 text-amber-300" />)}
                    </div>
                    <span className="text-[11px] sm:text-xs text-emerald-100/90 font-bold">4.9</span>
                    <span className="w-px h-3 bg-emerald-300/40" />
                    <span className="text-[11px] sm:text-xs text-emerald-100/70 font-medium">12,000+ reviews</span>
                  </div>

                  {/* What's inside — pills */}
                  <div className="mb-4 sm:mb-5">
                    <p className="text-[9px] sm:text-[10px] font-black tracking-[0.3em] text-emerald-300/80 uppercase mb-2">What&rsquo;s inside</p>
                    <div className="flex flex-wrap gap-1.5">
                      {['Cleanser', 'Serum', 'Eye Cream', 'Night Cream', 'Sunscreen'].map((step) => (
                        <span key={step} className="inline-flex items-center gap-1 bg-white/8 ring-1 ring-emerald-300/25 backdrop-blur-sm px-2.5 py-1 rounded-full text-[10px] sm:text-[11px] font-bold text-emerald-50">
                          <Check size={9} className="text-amber-300" /> {step}
                        </span>
                      ))}
                    </div>
                  </div>

                  {/* Price + CTA row */}
                  <div className="flex flex-col sm:flex-row sm:items-end gap-3 sm:gap-5">
                    <div className="flex flex-col">
                      {/* Big price */}
                      <div className="flex items-baseline gap-2">
                        <span className="text-3xl sm:text-4xl lg:text-5xl font-black tracking-tight bg-gradient-to-r from-white via-amber-100 to-amber-200 bg-clip-text text-transparent leading-none">₹{kit.combo_prepaid_price?.toLocaleString()}</span>
                        <span className="text-[10px] sm:text-[11px] text-emerald-200/70 font-medium">all-inclusive</span>
                      </div>
                      {/* MRP under the price */}
                      <div className="flex items-center gap-2 mt-2">
                        <span className="text-xs sm:text-sm font-semibold text-emerald-300/60 line-through">₹{kit.mrp_total?.toLocaleString()}</span>
                      </div>
                    </div>

                    {(() => {
                      // The kit is TBL only if the combo itself is TBL, OR a
                      // RESOLVED underlying product is TBL. An empty/unresolved
                      // product list (e.g. members not in the limited homepage
                      // fetch, or still loading) must NOT force TBL — otherwise a
                      // live combo wrongly shows "coming soon" on the storefront.
                      const productsInKit = (kit.product_slugs || []).map(s => products.find(p => p.slug === s)).filter(Boolean);
                      const kitIsTbl = !!kit.is_to_be_launched || productsInKit.some(p => p.is_to_be_launched);
                      if (kitIsTbl) {
                        return (
                          <button
                            disabled
                            data-testid="complete-kit-tbl"
                            className="flex-1 sm:flex-none bg-gradient-to-r from-amber-500 via-amber-600 to-orange-500 text-white font-black py-3.5 px-8 sm:px-10 rounded-full text-sm tracking-[0.28em] uppercase shadow-[0_14px_36px_-8px_rgba(245,158,11,0.55)] ring-1 ring-amber-300/50 flex items-center justify-center gap-2 cursor-not-allowed"
                          >
                            <Clock size={16} className="animate-pulse" /> TBL
                          </button>
                        );
                      }
                      return (
                        <button
                          onClick={() => handleAddCombo(kit.combo_id)}
                          data-testid="add-complete-kit"
                          className="group/btn relative overflow-hidden flex-1 sm:flex-none bg-gradient-to-r from-amber-400 via-amber-500 to-orange-400 hover:from-amber-300 hover:via-amber-400 hover:to-orange-300 text-emerald-950 font-black py-3.5 px-6 sm:px-7 rounded-full text-sm tracking-wide shadow-[0_14px_36px_-8px_rgba(245,158,11,0.55)] transition-all hover:-translate-y-0.5 active:scale-[0.99] flex items-center justify-center gap-2 ring-1 ring-amber-200/50"
                        >
                          <span className="absolute inset-0 bg-[radial-gradient(circle_at_30%_30%,rgba(255,255,255,0.45),transparent_55%)] pointer-events-none" />
                          <span className="relative flex items-center gap-2">
                            <ShoppingCart size={16} /> Add Complete Kit <ArrowRight size={14} className="transition-transform group-hover/btn:translate-x-1" />
                          </span>
                        </button>
                      );
                    })()}
                  </div>

                  {/* Trust footer */}
                  <div className="mt-4 sm:mt-5 pt-4 border-t border-emerald-300/15 flex flex-wrap items-center gap-x-4 gap-y-2 text-[10px] sm:text-[11px] text-emerald-100/80">
                    <span className="flex items-center gap-1.5"><Truck size={11} className="text-amber-300" /> Free shipping</span>
                    <span className="flex items-center gap-1.5"><Shield size={11} className="text-amber-300" /> 7-day sealed return</span>
                    <span className="flex items-center gap-1.5"><Check size={11} className="text-amber-300" /> COD available</span>
                    <span className="flex items-center gap-1.5"><Sparkles size={11} className="text-amber-300" /> Free skin analysis</span>
                  </div>
                </div>

              {/* Bottom shimmer line */}
              <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-amber-300/70 to-transparent" />
            </div>
          </div>
        </section>
      )}

      {/* Bestsellers section moved above the Complete Kit (Feb-2026). */}

      {/* Customer transformations — auto-swiping strip of before/after
          photos uploaded via /admin/media-tools. Global rows show on the
          homepage; product-specific rows show on that PDP. Silent no-op when
          no images are on file. */}

      {/* Independent lab reports — horizontal grid of every product's
          certificate. Tap any card to zoom. Full list lives at /certificates. */}
      <CertificatesStrip />

      {/* Customer reviews — auto-scrolling carousel pulled from /admin/reviews */}
      {niche.show_reviews !== false && (
        <ReviewsCarousel
          title={niche.reviews_title || 'Loved by customers across India'}
          eyebrow={niche.reviews_eyebrow || 'Real reviews · Verified buyers'}
        />
      )}

      {/* Influencer Reels — replaces the static dermatologist section.
          Global reels (no product_slugs) show here on the homepage. Managed
          from /admin/reels. Silent no-op when the shop has no reels yet. */}
      <InfluencerReelsSection />

      {/* FAQ — admin-toggleable + admin-editable list */}
      {niche.show_faq !== false && <FaqSection accent={accent} accentDark={accentDark} faqs={niche.faqs} title={niche.faq_title} eyebrow={niche.faq_eyebrow} />}

      {/* Routine CTA — admin-editable */}
      {ctaCfg.enabled !== false && (
      <section className="relative overflow-hidden" style={{ background: `linear-gradient(to right, ${ctaCfg.bg_from || '#047857'}, ${ctaCfg.bg_via || '#065f46'}, ${ctaCfg.bg_to || '#115e59'})` }}>
        <div className="absolute inset-0 opacity-15 pointer-events-none" style={{ backgroundImage: 'radial-gradient(circle at 85% 15%, white 0%, transparent 50%), radial-gradient(circle at 15% 85%, white 0%, transparent 50%)' }} />
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 py-8 sm:py-12 text-center">
          <p className="text-[10px] sm:text-[11px] font-black tracking-[0.4em] text-emerald-200 uppercase mb-2">{ctaCfg.eyebrow || 'Build your routine'}</p>
          <h2 className="font-heading text-lg sm:text-2xl lg:text-3xl font-black text-white leading-tight mb-2">{ctaCfg.title || 'Not sure where to start?'}</h2>
          <p className="text-xs sm:text-sm text-emerald-100 max-w-xl mx-auto mb-4 sm:mb-5">{ctaCfg.subtitle || "Tell us your skin type — we'll build a personalized AM & PM ritual in 2 seconds."}</p>
          <Link to={ctaCfg.button_link || '/routine'} className="inline-flex items-center gap-2 bg-white hover:bg-emerald-50 text-emerald-900 px-5 py-2.5 rounded-full font-black text-xs sm:text-sm shadow-2xl hover:-translate-y-0.5 transition-all">
            <Sparkles size={13} className="text-emerald-700" /> {ctaCfg.button_label || 'Start Routine Builder'} <ChevronRight size={13} />
          </Link>
        </div>
      </section>
      )}
    </div>
  );
}

// Brand imagery served permanently from Cloudinary — these used to point at
// /api/uploads/assets/* on the pod's disposable disk, which 404s after a redeploy.
const CG_BRAND = 'https://res.cloudinary.com/dcvuqcqjn/image/upload';

const TRACKER_SKIN = {
  pores: 'https://images.unsplash.com/photo-1541752857837-f8a0154fd092?crop=entropy&cs=srgb&fm=jpg&q=85&w=400',
  pores2: 'https://images.unsplash.com/photo-1710580889701-9fa8f2cd5927?crop=entropy&cs=srgb&fm=jpg&q=85&w=400',
  acne: 'https://images.pexels.com/photos/5588000/pexels-photo-5588000.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=500&w=400',
  acne2: 'https://images.pexels.com/photos/5588000/pexels-photo-5588000.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=400&w=400',
  darkspot: 'https://images.unsplash.com/photo-1723540634462-528708cc17aa?crop=entropy&cs=srgb&fm=jpg&q=85&w=400',
  healthy: 'https://images.unsplash.com/photo-1728727267814-792db55ce678?crop=entropy&cs=srgb&fm=jpg&q=85&w=500',
  beforeModel: 'https://images.pexels.com/photos/5588000/pexels-photo-5588000.jpeg?auto=compress&cs=tinysrgb&dpr=2&h=600&w=500',
  afterModel: 'https://images.unsplash.com/photo-1728727267814-792db55ce678?crop=entropy&cs=srgb&fm=jpg&q=85&w=500',
  aiBeforeAfter: `${CG_BRAND}/f_webp,q_auto:good,w_1000/celesta-glow/brand/skin-analysis-before-after`,
};

const TRACKER_PRODUCTS = [
  { label: 'Cleanser', when: 'AM / PM', img: `${CG_BRAND}/f_webp,q_auto:good,w_400/celesta-glow/brand/rec-cleanser` },
  { label: 'Serum', when: 'AM / PM', img: `${CG_BRAND}/f_webp,q_auto:good,w_400/celesta-glow/brand/rec-serum` },
  { label: 'Moisturizer', when: 'AM / PM', img: `${CG_BRAND}/f_webp,q_auto:good,w_400/celesta-glow/brand/rec-moisturizer` },
  { label: 'Sunscreen', when: 'AM', img: `${CG_BRAND}/f_webp,q_auto:good,w_400/celesta-glow/brand/rec-sunscreen` },
];

function MetricRow({ icon: Icon, label, value, up }) {
  return (
    <div className="min-w-0">
      <div className="flex items-center justify-between gap-2 mb-1">
        <span className="flex items-center gap-1 text-[11px] text-stone-600 min-w-0">
          <Icon size={12} className="text-emerald-600 shrink-0" />
          <span className="truncate">{label}</span>
        </span>
        <span className="flex items-center gap-1 shrink-0">
          <span className="text-[11px] font-bold text-stone-800">{value}</span>
          <span className="text-[9px] font-semibold text-emerald-600">↑{up}</span>
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-stone-100 overflow-hidden">
        <div className="h-full rounded-full bg-gradient-to-r from-emerald-400 to-emerald-600" style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

function SkinScoreRing({ score = 85 }) {
  const r = 34, c = 2 * Math.PI * r, off = c - (score / 100) * c;
  return (
    <div className="relative w-[92px] h-[92px] shrink-0">
      <svg viewBox="0 0 80 80" className="w-full h-full -rotate-90">
        <circle cx="40" cy="40" r={r} fill="none" stroke="#e7f2ec" strokeWidth="7" />
        <circle cx="40" cy="40" r={r} fill="none" stroke="#059669" strokeWidth="7" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={off} />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-2xl font-black text-stone-900 leading-none">{score}</span>
        <span className="text-[10px] text-stone-400 font-semibold">/100</span>
      </div>
    </div>
  );
}

function DetailTile({ img, label, level, pct, warn }) {
  return (
    <div>
      <div className="relative rounded-xl overflow-hidden aspect-square bg-stone-100">
        <img src={img} alt={label} loading="lazy" className="w-full h-full object-cover" />
      </div>
      <div className="flex items-center justify-between mt-1.5">
        <span className="text-[11px] font-bold text-stone-800">{label}</span>
        <ChevronRight size={13} className="text-stone-400" />
      </div>
      <span className={`text-[10px] font-semibold ${warn ? 'text-amber-600' : 'text-emerald-600'}`}>{level}</span>
      <div className="h-1 rounded-full bg-stone-100 overflow-hidden mt-1">
        <div className={`h-full rounded-full ${warn ? 'bg-amber-500' : 'bg-emerald-500'}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function TrackerPromo() {
  const loggedIn = (typeof window !== 'undefined') && !!localStorage.getItem('cg_auth_token');
  const features = [
    { icon: ScanFace, label: 'Skin Analysis' },
    { icon: ClipboardList, label: 'Personalised Routine' },
    { icon: BarChart3, label: 'Track Progress' },
    { icon: Lightbulb, label: 'Tips & Suggestions' },
  ];
  const metrics = [
    { icon: ScanFace, label: 'Pores', value: 72, up: 28 },
    { icon: Sparkles, label: 'Acne', value: 80, up: 35 },
    { icon: Star, label: 'Dark Spots', value: 78, up: 32 },
    { icon: Check, label: 'Even Tone', value: 88, up: 40 },
    { icon: TrendingUp, label: 'Fine Lines', value: 76, up: 30 },
    { icon: Shield, label: 'Hydration', value: 82, up: 33 },
  ];
  const strip = [
    { img: TRACKER_SKIN.pores, label: 'Pores' },
    { img: TRACKER_SKIN.acne, label: 'Acne' },
    { img: TRACKER_SKIN.darkspot, label: 'Dark Spots' },
    { img: TRACKER_SKIN.pores2, label: 'Fine Lines' },
  ];

  return (
    <section className="max-w-7xl mx-auto px-3 sm:px-6 pt-6 sm:pt-10" data-testid="home-tracker-promo">
      <div className="rounded-[28px] border border-emerald-100 bg-gradient-to-b from-emerald-50/70 via-white to-white p-5 sm:p-6 max-w-md mx-auto">
        <div className="grid grid-cols-1 gap-4 items-stretch [&>*:nth-child(n+2)]:hidden">

          {/* ---------- Column 1: copy + features + CTA ---------- */}
          <div className="lg:col-span-4 flex flex-col">
            <div className="inline-flex items-center gap-1.5 self-start bg-white border border-emerald-200 rounded-full px-3 py-1 mb-4 shadow-sm">
              <Sparkles size={14} className="text-emerald-600" />
              <span className="text-[11px] font-black uppercase tracking-[0.12em] text-emerald-700">New · AI Skin Tracker</span>
            </div>
            <h2 className="font-heading text-3xl font-black leading-tight text-stone-900">
              Track your <span className="text-emerald-600">glow-up</span>
            </h2>
            <p className="text-[13px] text-stone-600 mt-3 leading-relaxed">
              AI analyses your skin, gives personalised routines and shows real results.
            </p>
            <p className="text-[12px] text-stone-500 mt-2 leading-relaxed">
              <b className="text-emerald-700">FREE for 1 month</b> on orders ≥ ₹499 — then just ₹499/month.
            </p>

            <div className="grid grid-cols-4 gap-2 mt-5">
              {features.map((f) => (
                <div key={f.label} className="flex flex-col items-center text-center">
                  <div className="w-10 h-10 rounded-xl bg-emerald-50 border border-emerald-100 flex items-center justify-center mb-1.5">
                    <f.icon size={18} className="text-emerald-600" />
                  </div>
                  <span className="text-[10px] font-bold text-stone-700 leading-tight">{f.label}</span>
                </div>
              ))}
            </div>

            <div className="mt-6">
              <Link to="/tracker" data-testid="home-tracker-cta"
                className="inline-flex w-full sm:w-auto items-center justify-center gap-2 bg-emerald-700 hover:bg-emerald-800 text-white font-black text-[15px] px-7 py-4 rounded-full transition-colors shadow-lg shadow-emerald-700/20">
                <Sparkles size={18} /> {loggedIn ? 'Open my tracker' : 'Start free tracker'} <ArrowRight size={18} />
              </Link>
              <div className="mt-3">
                <Link to="/tracker" data-testid="home-tracker-login" className="text-[13px] font-semibold text-emerald-700 hover:text-emerald-900 underline underline-offset-4">
                  {loggedIn ? 'View my progress' : 'Login to access your progress'}
                </Link>
              </div>
            </div>
          </div>

          {/* ---------- Column 2: photo strip ---------- */}
          <div className="hidden lg:flex lg:col-span-2 flex-col gap-3">
            {strip.map((s) => (
              <div key={s.label} className="relative flex-1 rounded-2xl overflow-hidden bg-stone-100 min-h-[88px]">
                <img src={s.img} alt={s.label} loading="lazy" className="absolute inset-0 w-full h-full object-cover" />
                <div className="absolute inset-0 bg-gradient-to-t from-black/45 to-transparent" />
                <span className="absolute left-3 bottom-2 text-white text-[12px] font-bold drop-shadow">{s.label}</span>
                <div className="absolute right-2 bottom-2 w-5 h-5 border-2 border-white/70 rounded-md" />
              </div>
            ))}
          </div>

          {/* ---------- Column 3: Skin Analysis card ---------- */}
          <div className="lg:col-span-3">
            <div className="bg-white rounded-3xl border border-stone-100 shadow-xl shadow-stone-200/50 p-3.5 h-full flex flex-col">
              <div className="flex items-center justify-between gap-2 px-0.5 pb-3">
                <ChevronLeft size={15} className="text-stone-300 shrink-0" />
                <span className="text-[13px] font-black text-stone-900 whitespace-nowrap">Skin Analysis</span>
                <span className="text-[10px] text-stone-400 font-semibold whitespace-nowrap shrink-0">12 Sep 2026</span>
              </div>
              {/* before / after — owner-supplied comparison photo. Square so the
                  full frame shows (the old 4:3 crop cut the faces), and the image
                  carries no baked-in captions, so the Day labels are added once here. */}
              <div className="relative rounded-2xl overflow-hidden aspect-square bg-stone-100">
                <img
                  src={TRACKER_SKIN.aiBeforeAfter}
                  alt="Skin before and after 30 days — acne, texture and tone improvement"
                  width="1000" height="1000"
                  loading="lazy" decoding="async"
                  className="absolute inset-0 w-full h-full object-cover"
                />
                <div className="absolute top-0 bottom-0 left-1/2 -translate-x-1/2 w-0.5 bg-white shadow-[0_0_0_1px_rgba(0,0,0,0.08)]" />
                <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-9 h-9 rounded-full bg-white shadow-lg ring-1 ring-black/5 flex items-center justify-center">
                  <ChevronLeft size={12} className="text-stone-500" /><ChevronRight size={12} className="text-stone-500 -ml-1.5" />
                </div>
                <span className="absolute left-2.5 bottom-2 text-white text-[11px] font-bold drop-shadow-lg bg-black/25 rounded px-1.5 py-0.5">Day 1</span>
                <span className="absolute right-2.5 bottom-2 text-white text-[11px] font-bold drop-shadow-lg bg-black/25 rounded px-1.5 py-0.5">Day 30</span>
              </div>
              {/* score header */}
              <div className="flex items-center gap-3 mt-4">
                <SkinScoreRing score={85} />
                <div className="min-w-0">
                  <p className="text-[11px] font-semibold text-stone-500">Overall Skin Score</p>
                  <p className="text-sm font-black text-stone-900 leading-tight">85 / 100</p>
                  <span className="inline-block mt-0.5 text-[10px] font-bold text-emerald-700 bg-emerald-50 rounded-full px-2 py-0.5">Improving</span>
                </div>
              </div>
              {/* metrics grid */}
              <div className="grid grid-cols-2 gap-x-4 gap-y-2.5 mt-4">
                {metrics.map((m) => <MetricRow key={m.label} {...m} />)}
              </div>
              {/* progress chart */}
              <div className="mt-4 pt-3.5 border-t border-stone-100">
                <div className="flex items-center justify-between mb-2 gap-2">
                  <span className="text-[12px] font-bold text-stone-800">Your Skin Progress</span>
                  <span className="inline-flex items-center gap-1 text-[10px] font-black text-white bg-emerald-600 rounded-full px-2 py-1 whitespace-nowrap">
                    <TrendingUp size={11} /> +42%
                  </span>
                </div>
                <svg viewBox="0 0 300 70" className="w-full h-[58px]">
                  <defs>
                    <linearGradient id="trk-grad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#059669" stopOpacity="0.25" />
                      <stop offset="100%" stopColor="#059669" stopOpacity="0" />
                    </linearGradient>
                  </defs>
                  <path d="M10,55 L100,42 L190,28 L290,12 L290,70 L10,70 Z" fill="url(#trk-grad)" />
                  <polyline points="10,55 100,42 190,28 290,12" fill="none" stroke="#059669" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
                  {[[10,55],[100,42],[190,28],[290,12]].map(([x,y],i)=>(<circle key={i} cx={x} cy={y} r="3.5" fill="#fff" stroke="#059669" strokeWidth="2" />))}
                </svg>
                <div className="flex justify-between text-[9px] text-stone-400 font-semibold px-1">
                  <span>Day 1</span><span>Day 7</span><span>Day 14</span><span>Day 30</span>
                </div>
              </div>
            </div>
          </div>

          {/* ---------- Column 4: Detailed Analysis + Recommended ---------- */}
          <div className="lg:col-span-3 flex flex-col gap-4">
            <div className="bg-white rounded-3xl border border-stone-100 shadow-xl shadow-stone-200/50 p-4">
              <span className="text-[13px] font-black text-stone-900">Detailed Analysis</span>
              <div className="grid grid-cols-2 gap-3 mt-3">
                <DetailTile img={TRACKER_SKIN.pores} label="Pores" level="Moderate" pct={55} warn />
                <DetailTile img={TRACKER_SKIN.acne2} label="Acne" level="Mild" pct={30} />
                <DetailTile img={TRACKER_SKIN.darkspot} label="Dark Spots" level="Moderate" pct={55} warn />
                <DetailTile img={TRACKER_SKIN.pores2} label="Fine Lines" level="Mild" pct={30} />
              </div>
            </div>
            <div className="bg-white rounded-3xl border border-stone-100 shadow-xl shadow-stone-200/50 p-4">
              <div className="flex items-center justify-between">
                <span className="text-[13px] font-black text-stone-900">Recommended For You</span>
                <Link to="/shop" className="text-[11px] font-bold text-emerald-700 underline underline-offset-2">See all</Link>
              </div>
              <div className="grid grid-cols-4 gap-2 mt-3">
                {TRACKER_PRODUCTS.map((p) => (
                  <div key={p.label} className="text-center">
                    <div className="rounded-xl bg-stone-50 border border-stone-100 aspect-square flex items-center justify-center p-1.5 overflow-hidden">
                      <img src={p.img} alt={p.label} loading="lazy" className="w-full h-full object-contain" />
                    </div>
                    <span className="block text-[10px] font-bold text-stone-700 mt-1 leading-tight truncate">{p.label}</span>
                    <span className="block text-[9px] text-stone-400 font-semibold">{p.when}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

        </div>
      </div>
    </section>
  );
}

export default Homepage;/* ===================== Anti-Aging-only sections ===================== */

import { ChevronDown, BadgeCheck } from 'lucide-react';

function DermatologistSection({ accent, accentDark, cfg = {} }) {
  const eyebrow = cfg.eyebrow || 'Dermatologically formulated';
  const titlePart1 = cfg.title_part1 || 'Built with';
  const titleHighlight = cfg.title_highlight || 'board-certified dermatologists';
  const titleSuffix = cfg.title_suffix || ' for Indian skin.';
  const body = cfg.body || 'Every formulation goes through a 3-stage review with dermatology experts who specialize in tropical-climate skin — so the actives that *should* irritate Indian skin (retinol, Vit-C, AHAs) actually work without flushing, peeling or post-inflammatory pigmentation.';
  const stats = (Array.isArray(cfg.stats) && cfg.stats.length > 0) ? cfg.stats : [
    { num: '4', label: 'Weeks to visible firming' },
    { num: '0', label: 'Parabens · Sulfates · Mineral oil' },
    { num: '98%', label: 'Reported softer skin in 30 days' },
  ];
  const cta_label = cfg.cta_label || 'Book free dermat consult';
  const cta_link = cfg.cta_link || '/consultation';
  const image = cfg.image || 'https://images.unsplash.com/photo-1559839734-2b71ea197ec2?auto=format&fit=crop&w=900&q=80';
  return (
    <section className="bg-gradient-to-br from-emerald-50 via-white to-teal-50/40 py-8 sm:py-12" data-testid="anti-aging-dermat">
      <div className="max-w-7xl mx-auto px-3 sm:px-6">
        <div className="bg-white rounded-2xl sm:rounded-3xl ring-1 ring-emerald-100 p-5 sm:p-8 lg:p-10 grid grid-cols-1 lg:grid-cols-12 gap-5 lg:gap-8 items-center">
          <div className="lg:col-span-5">
            <div className="aspect-[4/5] sm:aspect-[4/3] rounded-2xl overflow-hidden ring-1 ring-emerald-100 bg-gradient-to-br from-emerald-50 to-teal-50">
              <img src={image} alt="Board-certified dermatologist" className="w-full h-full object-cover object-top" />
            </div>
          </div>
          <div className="lg:col-span-7">
            <p className="text-[10px] sm:text-[11px] font-bold tracking-[0.4em] uppercase mb-1.5 flex items-center gap-2" style={{ color: accentDark }}>
              <BadgeCheck size={12} style={{ color: accentDark }} /> {eyebrow}
            </p>
            <h2 className="font-heading text-xl sm:text-2xl lg:text-3xl font-black leading-tight text-stone-900 mb-3">
              {titlePart1} <span className="italic" style={{ color: accent }}>{titleHighlight}</span>{titleSuffix}
            </h2>
            <p className="text-sm sm:text-base text-stone-600 leading-relaxed mb-5">{body}</p>
            <div className="grid grid-cols-3 gap-3 mb-5">
              {stats.map(s => (
                <div key={s.label} className="text-center p-3 rounded-xl bg-emerald-50/60 ring-1 ring-emerald-100">
                  <div className="font-heading text-2xl sm:text-3xl font-black leading-none" style={{ color: accentDark }}>{s.num}</div>
                  <p className="text-[10px] mt-1.5 leading-tight" style={{ color: accentDark }}>{s.label}</p>
                </div>
              ))}
            </div>
            <Link to={cta_link} className="inline-flex items-center gap-2 text-white font-black py-2.5 px-5 rounded-full text-xs sm:text-sm tracking-wide shadow-lg shadow-emerald-900/15 transition-all hover:-translate-y-0.5" style={{ background: accent }}>
              {cta_label} <ArrowRight size={13} />
            </Link>
          </div>
        </div>
      </div>
    </section>
  );
}

function FaqItem({ q, a, defaultOpen, accent }) {
  const [open, setOpen] = useState(!!defaultOpen);
  return (
    <div className="bg-white rounded-2xl ring-1 ring-stone-200 overflow-hidden" data-testid={`faq-item-${q.slice(0,16).toLowerCase().replace(/\s+/g,'-')}`}>
      <button onClick={() => setOpen(!open)} className="w-full flex items-center justify-between gap-3 px-4 sm:px-5 py-4 text-left hover:bg-stone-50/60 transition-colors">
        <span className="text-sm sm:text-base font-bold text-stone-900 leading-snug">{q}</span>
        <ChevronDown size={18} className={`flex-shrink-0 text-stone-500 transition-transform ${open ? 'rotate-180' : ''}`} style={open ? { color: accent } : undefined} />
      </button>
      {open && (
        <div className="px-4 sm:px-5 pb-4 text-[13px] sm:text-sm text-stone-600 leading-relaxed">{a}</div>
      )}
    </div>
  );
}

function FaqSection({ accent, accentDark, faqs: customFaqs, title, eyebrow }) {
  const defaults = [
    { q: 'How quickly will I see results from the Skin Care Kit?', a: 'Most users notice softer skin and a brighter complexion within 7–10 days. Visible firming and reduction in fine lines typically appear at 4 weeks of consistent AM + PM use.' },
    { q: 'Is retinol safe for Indian skin? Will it cause irritation?', a: 'Our retinol is encapsulated in a slow-release matrix specifically tested on melanin-rich, tropical skin types. It releases over 8 hours which dramatically reduces flushing, peeling and post-inflammatory pigmentation common with conventional retinols.' },
    { q: 'Can I use the Vitamin C serum and retinol together?', a: 'Yes — but apply Vitamin C in the AM (it pairs beautifully with sunscreen) and retinol at PM. Stacking both at the same time can over-exfoliate sensitive skin.' },
    { q: 'Are the products dermatologically tested?', a: 'Every formula passes a 3-stage review with board-certified dermatologists, plus independent lab testing for safety, efficacy and shelf stability under Indian climate conditions.' },
    { q: 'What if it doesn\'t work for me?', a: 'We accept 7-day returns on unopened, factory-sealed items only. Once a bottle is opened we cannot accept it back for hygiene reasons — please tell us your concern on WhatsApp first and our team will recommend the right product before you break the seal.' },
    { q: 'How is shipping & delivery?', a: 'Free shipping on orders over ₹499. Most metros receive their order within 2–3 business days. We also offer Cash on Delivery and 24-hour dispatch.' },
  ];
  const faqs = (Array.isArray(customFaqs) && customFaqs.length > 0) ? customFaqs : defaults;
  return (
    <section className="bg-white py-8 sm:py-12" data-testid="anti-aging-faq">
      <div className="max-w-3xl mx-auto px-3 sm:px-6">
        <div className="text-center mb-6 sm:mb-8">
          <p className="text-[10px] sm:text-[11px] font-bold tracking-[0.4em] uppercase mb-1.5" style={{ color: accent }}>{eyebrow || 'Frequently asked'}</p>
          <h2 className="font-heading text-xl sm:text-2xl lg:text-3xl font-black text-stone-900 leading-tight">
            {title ? (
              <>{title.split(' ').slice(0, -1).join(' ')} <span className="italic" style={{ color: accent }}>{title.split(' ').slice(-1)[0]}</span></>
            ) : (
              <>Got <span className="italic" style={{ color: accent }}>questions?</span></>
            )}
          </h2>
        </div>
        <div className="space-y-3">
          {faqs.map((f, i) => <FaqItem key={f.q} q={f.q} a={f.a} defaultOpen={i === 0} accent={accent} />)}
        </div>
      </div>
    </section>
  );
}

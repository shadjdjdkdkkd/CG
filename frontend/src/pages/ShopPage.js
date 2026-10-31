import React, { useState, useEffect, useMemo } from 'react';
import axios from 'axios';
import BackButton from '../components/BackButton';
import { Link, useSearchParams } from 'react-router-dom';
import { Star, ShoppingCart, Sparkles, ChevronRight, Package, Check, Clock, ArrowRight, Truck, Shield, Filter, Heart, Share2, BadgeCheck, Eye, Flame, Award } from 'lucide-react'; // eslint-disable-line no-unused-vars
import { addToCart, addComboToCart } from './Homepage';
import { ProductCard } from './ConcernCategoryPage';
import AddToBagButton from '../components/AddToBagButton';
import AntiAgingOfferHighlight from '../components/AntiAgingOfferHighlight';
import NicheOffersGrid from '../components/NicheOffersGrid';
import { shareProduct } from '../utils/shareProduct';
import { cachedGet } from '../utils/apiCache';
import { getSocialProof } from '../utils/socialProof';
import SEOHead, { breadcrumbJsonLd } from '../components/SEOHead';
import { cldOptim } from '../utils/productImage';
import { useSaleMode } from '../utils/saleMode';

const API = process.env.REACT_APP_BACKEND_URL;

const FILTERS = [
  { id: 'all',         label: 'All' },
  { id: 'bestsellers', label: 'Bestsellers' },
  { id: 'new',         label: 'New Launch' },
  { id: 'tbl',         label: 'Coming Soon' },
];

const NICHE_META = {
  'anti-aging': { label: 'Anti-Aging', kitId: 'complete-anti-aging-kit' },
  'skincare':   { label: 'Skincare',   kitId: null },
  'cosmetics':  { label: 'Cosmetics',  kitId: null },
};

function ShopPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const nicheParam = searchParams.get('niche'); // null | 'anti-aging' | 'skincare' | 'cosmetics'
  const nicheMeta = nicheParam ? NICHE_META[nicheParam] : null;
  const saleMode = useSaleMode();
  // Only the anti-aging niche has a dedicated landing banner (independent of the sale toggle).
  const antiAgingBanner = (nicheParam === 'anti-aging') ? {
    desktop: saleMode?.landing_banner_anti_aging_desktop || '',
    mobile: saleMode?.landing_banner_anti_aging_mobile || '',
  } : null;

  // URL-state filters (SH-1, SH-4, SH-5, SH-6, SH-7 fix)
  const filter = searchParams.get('filter') || 'all';
  const sortBy = searchParams.get('sort') || 'default';
  const skinType = searchParams.get('skin_type') || '';
  const ingredient = searchParams.get('ingredient') || '';
  const look = searchParams.get('look') || '';
  const minPrice = Number(searchParams.get('min_price') || 0);
  const maxPrice = Number(searchParams.get('max_price') || 0);
  const minRating = Number(searchParams.get('min_rating') || 0);

  const setParam = (k, v) => {
    const next = new URLSearchParams(searchParams);
    if (v && v !== 'all' && v !== 'default' && v !== '0' && v !== 0) next.set(k, String(v));
    else next.delete(k);
    setSearchParams(next, { replace: true });
  };
  const setFilter = (v) => setParam('filter', v);
  const clearAllFilters = () => {
    const next = new URLSearchParams();
    if (nicheParam) next.set('niche', nicheParam);
    setSearchParams(next, { replace: true });
  };

  const [products, setProducts] = useState([]);
  const [combos, setCombos] = useState([]);
  const [settings, setSettings] = useState({});
  const [loading, setLoading] = useState(true);
  // --- Pagination + server-side search state ---
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const PAGE_SIZE = 24;

  // Debounce the search box so we don't slam the server on every keystroke
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(searchTerm.trim()), 300);
    return () => clearTimeout(t);
  }, [searchTerm]);

  useEffect(() => {
    // Meta Pixel — niche/category PageView event for Shop / View All
    if (typeof window !== 'undefined' && window.fbq) {
      const pageName = nicheParam ? `shop_${nicheParam}` : 'shop_all';
      const category = nicheMeta?.label || 'All Products';
      window.fbq('track', 'PageView', { page_name: pageName, content_category: category });
    }
  }, [nicheParam, nicheMeta]);

  // Reset pagination whenever the niche or the search term changes
  useEffect(() => {
    setProducts([]);
    setPage(1);
    setHasMore(false);
    setTotal(0);
    setLoading(true);
  }, [nicheParam, debouncedSearch]);

  // Primary fetch (page 1 of products + combos + site-settings)
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const params = new URLSearchParams();
        if (nicheParam) params.set('niche', nicheParam);
        params.set('page', '1');
        params.set('limit', String(PAGE_SIZE));
        if (debouncedSearch) params.set('search', debouncedSearch);

        const productsUrl = `${API}/api/products?${params.toString()}`;
        const combosUrl = nicheParam
          ? `${API}/api/combos?niche=${encodeURIComponent(nicheParam)}`
          : `${API}/api/combos`;
        const [prodRes, comboRes, settRes] = await Promise.all([
          axios.get(productsUrl),
          cachedGet(combosUrl, { ttl: 60_000 }),
          cachedGet(`${API}/api/site-settings`, { ttl: 60_000 }),
        ]);
        if (cancelled) return;
        // Paginated response always returns { items, total, page, has_next }
        const payload = prodRes.data;
        const items = Array.isArray(payload) ? payload : (payload.items || []);
        setProducts(items);
        setTotal(Array.isArray(payload) ? items.length : (payload.total || items.length));
        setHasMore(Array.isArray(payload) ? false : !!payload.has_next);
        setPage(1);
        setCombos(comboRes.data);
        setSettings(settRes.data);
      } catch (err) { console.error(err); }
      if (!cancelled) setLoading(false);
    })();
    return () => { cancelled = true; };
  }, [nicheParam, debouncedSearch]);

  // Load-more handler — appends the next page to the list.
  const loadMore = async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const params = new URLSearchParams();
      if (nicheParam) params.set('niche', nicheParam);
      params.set('page', String(page + 1));
      params.set('limit', String(PAGE_SIZE));
      if (debouncedSearch) params.set('search', debouncedSearch);
      const res = await axios.get(`${API}/api/products?${params.toString()}`);
      const payload = res.data;
      const items = Array.isArray(payload) ? payload : (payload.items || []);
      setProducts((prev) => [...prev, ...items]);
      setHasMore(Array.isArray(payload) ? false : !!payload.has_next);
      setPage((p) => p + 1);
    } catch (e) {
      console.error(e);
    } finally {
      setLoadingMore(false);
    }
  };

  const completeKit = combos.find(c => c.combo_id === (nicheMeta?.kitId || 'complete-anti-aging-kit'));
  const otherCombos = combos.filter(c => c.combo_id !== (nicheMeta?.kitId || 'complete-anti-aging-kit'));

  const visibleProducts = useMemo(() => {
    let list = products.slice();
    if (filter === 'bestsellers') list = list.filter(p => p.badge === 'Bestseller');
    else if (filter === 'new') list = list.filter(p => p.badge === 'New Launch');
    else if (filter === 'tbl') list = list.filter(p => p.is_to_be_launched);
    if (skinType) list = list.filter(p => (p.skin_type || '').toLowerCase().includes(skinType.toLowerCase()));
    if (ingredient) {
      const needle = ingredient.toLowerCase().replace(/-/g, ' ');
      list = list.filter(p => (p.key_ingredients || '').toLowerCase().includes(needle) || (p.ingredients_full || '').toLowerCase().includes(needle));
    }
    if (look) list = list.filter(p => (p.concerns || []).some(c => String(c).toLowerCase().includes(look.toLowerCase())));
    if (minPrice > 0) list = list.filter(p => (p.prepaid_price || 0) >= minPrice);
    if (maxPrice > 0) list = list.filter(p => (p.prepaid_price || 0) <= maxPrice);
    if (minRating > 0) list = list.filter(p => (p.rating || 0) >= minRating);

    if (sortBy === 'price_asc') list.sort((a, b) => (a.prepaid_price || 0) - (b.prepaid_price || 0));
    else if (sortBy === 'price_desc') list.sort((a, b) => (b.prepaid_price || 0) - (a.prepaid_price || 0));
    else if (sortBy === 'rating') list.sort((a, b) => (b.rating || 0) - (a.rating || 0));
    else if (sortBy === 'newest') list.sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || '')));
    else if (sortBy === 'popular') list.sort((a, b) => (b.reviews_count || 0) - (a.reviews_count || 0));

    // Image-first override (Feb 2026): regardless of the user's chosen sort,
    // products that have at least one valid image always come before products
    // without an image. Otherwise the listing page interleaves blank
    // placeholder tiles with real product tiles which looks broken on the
    // customer site. (Reported by the merchant on the cosmetics niche.)
    const hasImg = (p) => !!(p && Array.isArray(p.images) && p.images[0]);
    list = list.slice().sort((a, b) => (hasImg(b) ? 1 : 0) - (hasImg(a) ? 1 : 0));
    return list;
  }, [products, filter, sortBy, skinType, ingredient, look, minPrice, maxPrice, minRating]);

  // Group visible products under their concern titles. Only concerns that at
  // least one product is tagged with get a section (a product can appear under
  // more than one concern — that's intended).
  const groupedByConcern = useMemo(() => {
    const groups = {};
    const title = (c) => (c || '').replace(/[-_]/g, ' ').replace(/\b\w/g, (ch) => ch.toUpperCase());
    visibleProducts.forEach((p) => {
      const cs = (p.concerns || []).filter(Boolean);
      if (!cs.length) { (groups['__other'] = groups.__other || []).push(p); return; }
      cs.forEach((c) => { (groups[c] = groups[c] || []).push(p); });
    });
    return Object.entries(groups)
      .map(([key, prods]) => ({ key, title: key === '__other' ? 'More Products' : title(key), prods }))
      .sort((a, b) => b.prods.length - a.prods.length || a.title.localeCompare(b.title));
  }, [visibleProducts]);

  const activeFilters = useMemo(() => {
    const out = [];
    if (filter !== 'all') out.push({ key: 'filter', label: filter, raw: filter });
    if (sortBy !== 'default') out.push({ key: 'sort', label: `sort: ${sortBy.replace('_', ' ')}`, raw: sortBy });
    if (skinType) out.push({ key: 'skin_type', label: skinType, raw: skinType });
    if (ingredient) out.push({ key: 'ingredient', label: ingredient, raw: ingredient });
    if (look) out.push({ key: 'look', label: `look: ${look}`, raw: look });
    if (minPrice) out.push({ key: 'min_price', label: `min ₹${minPrice}`, raw: String(minPrice) });
    if (maxPrice) out.push({ key: 'max_price', label: `max ₹${maxPrice}`, raw: String(maxPrice) });
    if (minRating) out.push({ key: 'min_rating', label: `${minRating}★ & up`, raw: String(minRating) });
    return out;
  }, [filter, sortBy, skinType, ingredient, look, minPrice, maxPrice, minRating]);

  // Per-product social proof: deterministic by (slug, current minute) so it
  // doesn't flicker on filter changes / re-renders, but ticks naturally over
  // the day. See utils/socialProof.js for the math.
  const [proofTick, setProofTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setProofTick((t) => t + 1), 60_000);
    return () => clearInterval(id);
  }, []);
  const socialProof = useMemo(() => {
    const map = {};
    products.forEach(p => {
      const sp = getSocialProof(p.slug || '');
      map[p.slug] = {
        orders: sp.soldToday,
        piecesLeft: sp.stockLeft,
        viewing: sp.viewingNow,
      };
    });
    return map;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [products, proofTick]);

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-stone-50 via-white to-stone-50" data-testid="shop-page-loading">
        <div className="max-w-7xl mx-auto px-3 sm:px-6 pt-3 sm:pt-4"><BackButton /></div>
        {/* Skeleton hero */}
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8 sm:py-12">
          <div className="h-5 w-28 bg-green-100 rounded-full animate-pulse mb-3" />
          <div className="h-10 sm:h-14 w-2/3 bg-stone-200 rounded-lg animate-pulse mb-3" />
          <div className="h-4 w-1/2 bg-stone-200 rounded animate-pulse" />
        </div>
        {/* Skeleton product grid */}
        <div className="max-w-7xl mx-auto px-4 sm:px-6 pb-12">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-5">
            {[...Array(8)].map((_, i) => (
              <div key={i} className="bg-white rounded-2xl ring-1 ring-stone-100 overflow-hidden">
                <div className="aspect-square bg-stone-100 animate-pulse" />
                <div className="p-3 space-y-2">
                  <div className="h-3 w-1/3 bg-stone-100 rounded animate-pulse" />
                  <div className="h-4 w-4/5 bg-stone-100 rounded animate-pulse" />
                  <div className="h-3 w-2/3 bg-stone-100 rounded animate-pulse" />
                  <div className="h-8 w-full bg-stone-100 rounded-full animate-pulse mt-3" />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  // ---- SEO: choose niche-aware title/description ----
  const _niche = nicheParam || null;
  const _meta = NICHE_META[_niche] || null;
  const seoTitle = _meta
    ? `Shop ${_meta.label} — Dermatologist-Approved Skincare | Celesta Glow | Kerala`
    : 'Shop Dermatologist-Approved Skincare | Celesta Glow | Kerala';
  const seoDesc = _meta
    ? `Explore dermatologist-approved vegan ${_meta.label.toLowerCase()} in Kerala, including face serum, cleanser, sunscreen, eye cream, and night cream. Shop now.`
    : 'Explore dermatologist-approved vegan skin care in Kerala, including face serum, cleanser, sunscreen, eye cream, and night cream. Shop now.';
  const seoCanonical = _niche ? `/shop?niche=${_niche}` : '/shop';

  return (
    <div className="min-h-screen bg-gradient-to-b from-stone-50 via-white to-stone-50" data-testid="shop-page">
      <SEOHead
        title={seoTitle}
        description={seoDesc}
        canonicalPath={seoCanonical}
        jsonLd={breadcrumbJsonLd([
          { name: 'Home', url: '/' },
          { name: _meta ? _meta.label : 'Shop', url: seoCanonical },
        ])}
      />
      {/* HERO HEADER */}
      <section className="relative overflow-hidden border-b border-green-100/60">
        {/* Anti-Aging landing banner — admin-uploaded, always shown on niche=anti-aging */}
        {antiAgingBanner && (antiAgingBanner.desktop || antiAgingBanner.mobile) && (
          <div className="w-full" data-testid="anti-aging-landing-banner">
            {antiAgingBanner.mobile && (
              <img
                src={antiAgingBanner.mobile}
                alt="Anti-aging landing banner"
                className="w-full h-auto block sm:hidden"
                loading="eager"
              />
            )}
            {antiAgingBanner.desktop && (
              <img
                src={antiAgingBanner.desktop}
                alt="Anti-aging landing banner"
                className="w-full h-auto hidden sm:block"
                loading="eager"
              />
            )}
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-br from-green-50/60 via-white to-amber-50/40" />
        <div className="absolute inset-0 opacity-50" style={{ backgroundImage: 'radial-gradient(circle at 12% 30%, rgba(34,197,94,0.15) 0%, transparent 42%), radial-gradient(circle at 88% 70%, rgba(250,204,21,0.10) 0%, transparent 45%)' }} />
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 py-10 sm:py-14">
          <nav className="flex items-center gap-2 text-xs sm:text-sm text-gray-500 mb-4">
            <Link to="/" className="hover:text-green-700">Home</Link>
            <ChevronRight size={13} />
            <span className="text-green-800 font-semibold">Shop</span>
          </nav>
          <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4">
            <div>
              <span className="inline-flex items-center gap-2 text-[11px] tracking-[0.3em] text-green-700 font-bold uppercase mb-2">
                <Sparkles size={12} /> Curated Collection
              </span>
              <h1 className="font-heading text-3xl sm:text-4xl lg:text-5xl font-black text-gray-900 leading-[1.05] tracking-tight">
                {nicheMeta ? (
                  <>Shop all <span className="italic text-green-700">{nicheMeta.label}</span></>
                ) : (
                  <>Shop the entire <span className="italic text-green-700">Celesta Glow</span> range</>
                )}
              </h1>
              <p className="text-sm sm:text-base text-gray-500 mt-3 max-w-2xl leading-relaxed">
                Clinically-formulated for Indian skin · Free shipping · Cash on Delivery · 7-day return on sealed items.
              </p>
            </div>
            <div className="flex items-center gap-3 text-xs">
              <div className="flex items-center gap-1.5 text-green-800 bg-white/70 backdrop-blur px-3 py-1.5 rounded-full border border-green-100"><Truck size={14} className="text-green-600" /> Free Ship</div>
              <div className="flex items-center gap-1.5 text-green-800 bg-white/70 backdrop-blur px-3 py-1.5 rounded-full border border-green-100"><Shield size={14} className="text-green-600" /> 7-Day Sealed Return</div>
              <div className="flex items-center gap-1.5 text-green-800 bg-white/70 backdrop-blur px-3 py-1.5 rounded-full border border-green-100"><Check size={14} className="text-green-600" /> COD</div>
            </div>
          </div>
        </div>
      </section>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8 sm:py-12">

        {/* Editorial "Age-Reversal Bash" offer grid — Top Deal + category tiles
            with real Up-to-X%-OFF badges + auto-scrolling price-band strip.
            Renders at the very top so it's the first thing customers see. */}
        {nicheParam === 'anti-aging' && (
          <NicheOffersGrid niche="anti-aging" categories={[]} theme="anti-aging" />
        )}

        {/* Anti-Aging perks highlight (FLAT 50% OFF + Zero Tax + Zero Delivery).
            Kept below the grid so the fees benefit is explicit. */}
        {nicheParam === 'anti-aging' && (
          <AntiAgingOfferHighlight niche="anti-aging" />
        )}

        {/* COMPLETE KIT — only for anti-aging niche (or no niche filter) */}
        {completeKit && (!nicheParam || nicheParam === 'anti-aging') && (
          <section id="shop-complete-kit-section" className="relative mb-10 sm:mb-14" data-testid="shop-complete-kit-section">
            <div className="text-center mb-6">
              <div className="inline-flex items-center gap-2 mb-3">
                <span className="h-px w-10 bg-green-600/40" />
                <span className="text-[11px] tracking-[0.4em] text-green-700 font-bold">SIGNATURE BUNDLE</span>
                <span className="h-px w-10 bg-green-600/40" />
              </div>
              <h2 className="font-heading text-2xl sm:text-3xl lg:text-4xl font-black text-gray-900 leading-tight">
                The Complete <span className="italic text-green-700">Anti-Aging</span> Ritual
              </h2>
            </div>

            <div className="relative rounded-[28px] overflow-hidden bg-white ring-1 ring-green-100 shadow-2xl shadow-green-900/[0.08]">
              {/* Top status bar */}
              <div className="flex items-center justify-between px-5 sm:px-7 py-3 border-b border-green-50 bg-gradient-to-r from-green-50/60 via-amber-50/30 to-transparent">
                <div className="flex items-center gap-2">
                  <span className="relative flex h-2 w-2">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-500 opacity-75" />
                    <span className="relative inline-flex rounded-full h-2 w-2 bg-green-600" />
                  </span>
                  <span className="text-[11px] tracking-widest text-green-800 font-bold">BEST SELLER · BEST VALUE</span>
                </div>
                <div className="flex items-center gap-1">
                  {[1,2,3,4,5].map(i => <Star key={i} size={13} className="fill-amber-400 text-amber-400" />)}
                  <span className="text-[11px] text-gray-600 ml-1 font-semibold">4.9 · 12k+</span>
                </div>
              </div>

              {/* TOP — Landscape kit image (admin-managed). Prefer the combo's own image, fall back to global bundle hero. Image-only — no text overlay. */}
              <div className="relative w-full aspect-[16/9] bg-gradient-to-br from-green-50 via-white to-amber-50/40 overflow-hidden">
                {(completeKit.image || settings.bundle_hero_image) ? (
                  <img
                    src={completeKit.image || settings.bundle_hero_image}
                    alt={completeKit.name}
                    className="absolute inset-0 w-full h-full object-cover"
                    data-testid="kit-landscape-image"
                  />
                ) : (
                  /* Minimal placeholder — no text. Just a soft brand mark when admin hasn't uploaded yet. */
                  <div className="absolute inset-0 flex items-center justify-center" data-testid="kit-image-placeholder">
                    <div className="inline-flex items-center justify-center w-16 h-16 rounded-full bg-white shadow-md ring-1 ring-emerald-100 opacity-60">
                      <Sparkles className="w-7 h-7 text-emerald-700/70" />
                    </div>
                  </div>
                )}
              </div>

              {/* DETAILS — full-width content under landscape image */}
              <div className="p-6 sm:p-8 lg:p-10 bg-gradient-to-br from-green-900 via-green-800 to-green-900 text-white relative">
                <div className="absolute inset-0 opacity-20 pointer-events-none" style={{ backgroundImage: 'radial-gradient(circle at 80% 20%, rgba(250,204,21,0.25) 0%, transparent 40%)' }} />
                <div className="relative grid grid-cols-1 lg:grid-cols-12 gap-6 lg:gap-10">
                  <div className="lg:col-span-7">
                    <h3 className="font-heading text-2xl sm:text-3xl font-black leading-tight">{completeKit.name}</h3>
                    <p className="text-sm text-green-100/80 mt-2 leading-relaxed">{completeKit.description}</p>

                    <div className="mt-5 space-y-2.5">
                      <p className="text-[11px] tracking-[0.25em] text-amber-300 font-bold">WHAT'S INSIDE</p>
                      {completeKit.product_slugs?.map(slug => {
                        const p = products.find(pr => pr.slug === slug);
                        return p ? (
                          <div key={slug} className="flex items-center gap-3">
                            <div className="w-9 h-9 bg-white/10 rounded-lg flex items-center justify-center flex-shrink-0 ring-1 ring-white/15 overflow-hidden">
                              {p.images?.[0] ? <img src={p.images[0]} alt="" className="w-7 h-7 object-contain" /> : <Sparkles size={12} className="text-amber-300" />}
                            </div>
                            <span className="text-sm text-white/95 font-medium flex-1 truncate">{p.short_name}</span>
                            <span className="text-xs text-green-200/60 line-through">₹{p.mrp}</span>
                          </div>
                        ) : null;
                      })}
                    </div>
                  </div>

                  <div className="lg:col-span-5 lg:border-l lg:border-white/10 lg:pl-10 flex flex-col justify-center">
                    <div className="pt-2">
                      <div className="flex items-end gap-3 mb-1">
                        <span className="text-4xl sm:text-5xl font-black text-white tracking-tight">₹{completeKit.combo_prepaid_price?.toLocaleString()}</span>
                        <span className="text-base text-white/40 line-through mb-1.5">₹{completeKit.mrp_total?.toLocaleString()}</span>
                      </div>
                      <p className="text-xs text-amber-300 font-semibold">You save ₹{(completeKit.mrp_total - completeKit.combo_prepaid_price)?.toLocaleString()} · ~₹{Math.round(completeKit.combo_prepaid_price/60)}/day for 60 days</p>
                    </div>

                    {(() => {
                      // The kit is TBL only if the combo itself is TBL, OR a
                      // RESOLVED underlying product is TBL. An unresolved product
                      // list must NOT force TBL (a live combo stays buyable).
                      const productsInKit = (completeKit.product_slugs || []).map(s => products.find(p => p.slug === s)).filter(Boolean);
                      const kitIsTbl = !!completeKit.is_to_be_launched || productsInKit.some(p => p.is_to_be_launched);
                      if (kitIsTbl) {
                        return (
                          <button
                            disabled
                            data-testid="shop-kit-tbl"
                            className="group/btn mt-5 w-full relative overflow-hidden bg-gradient-to-r from-amber-500 via-amber-600 to-orange-500 text-white font-black py-4 rounded-2xl text-sm tracking-[0.28em] uppercase shadow-2xl shadow-amber-900/20 ring-1 ring-amber-300/40 flex items-center justify-center gap-2 cursor-not-allowed"
                          >
                            <Clock size={16} className="animate-pulse" /> TBL
                          </button>
                        );
                      }
                      return (
                        <button
                          onClick={() => addComboToCart(completeKit.combo_id)}
                          className="group/btn mt-5 w-full relative overflow-hidden bg-amber-400 hover:bg-amber-300 text-green-950 font-black py-4 rounded-2xl text-sm tracking-wide shadow-2xl shadow-amber-900/20 transition-all hover:-translate-y-0.5 flex items-center justify-center gap-2"
                          data-testid="shop-add-kit"
                        >
                          <ShoppingCart size={18} />
                          <span>ADD COMPLETE KIT</span>
                          <ArrowRight size={16} className="transition-transform group-hover/btn:translate-x-1" />
                        </button>
                      );
                    })()}

                    <div className="mt-4 flex items-center justify-center gap-4 text-[11px] text-green-100/70">
                      <span className="flex items-center gap-1"><Truck size={11} /> Free shipping</span>
                      <span className="flex items-center gap-1"><Shield size={11} /> 7-day sealed return</span>
                      <span className="flex items-center gap-1"><Check size={11} /> COD avail.</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </section>
        )}

        {/* SECTION HEADER + FILTERS */}
        <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-4 mb-3">
          <div>
            <p className="text-[11px] font-bold text-green-700 uppercase tracking-[0.25em] mb-1">Our Range</p>
            <h2 className="font-heading text-2xl sm:text-3xl font-black text-gray-900">Individual Products</h2>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <Filter size={14} className="text-green-700/60 hidden sm:inline" />
            {FILTERS.map(f => (
              <button
                key={f.id}
                onClick={() => setFilter(f.id)}
                className={`px-3.5 py-1.5 rounded-full text-xs font-bold tracking-wide transition-all ${
                  filter === f.id
                    ? 'bg-green-700 text-white shadow-md shadow-green-900/20'
                    : 'bg-white text-gray-700 border border-green-100 hover:border-green-300 hover:bg-green-50/50'
                }`}
                data-testid={`shop-filter-${f.id}`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {/* SORT DROPDOWN + ACTIVE FILTER CHIPS (SH-4, SH-5 fix) */}
        <div className="flex flex-wrap items-center gap-2 mb-3" data-testid="shop-active-filters">
          {activeFilters.map(af => (
            <button
              key={af.key + af.raw}
              onClick={() => setParam(af.key, '')}
              className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-green-50 text-green-800 text-[11px] font-bold ring-1 ring-green-200 hover:bg-green-100 capitalize"
              data-testid={`active-filter-${af.key}`}
            >
              {af.label}
              <span className="text-green-600 leading-none text-base">×</span>
            </button>
          ))}
          {activeFilters.length > 0 && (
            <button
              onClick={clearAllFilters}
              className="text-[11px] font-bold text-red-600 underline hover:text-red-700"
              data-testid="clear-all-filters"
            >
              Clear all
            </button>
          )}
          <div className="flex-1" />
          <select
            value={sortBy}
            onChange={(e) => setParam('sort', e.target.value)}
            className="bg-white ring-1 ring-stone-200 rounded-full px-3 py-1.5 text-xs font-semibold text-stone-700 focus:ring-2 focus:ring-green-500"
            data-testid="shop-sort"
          >
            <option value="default">Sort: Recommended</option>
            <option value="popular">Most popular</option>
            <option value="rating">Top rated</option>
            <option value="price_asc">Price: low to high</option>
            <option value="price_desc">Price: high to low</option>
            <option value="newest">Newest</option>
          </select>
        </div>

        {/* PRODUCT SEARCH BAR — server-side, paginated */}
        <div className="mb-5 flex items-center gap-2" data-testid="shop-search-bar">
          <div className="relative flex-1 max-w-md">
            <input
              type="search"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder={`Search ${nicheMeta?.label || 'products'}…`}
              className="w-full pl-10 pr-3 h-11 rounded-xl bg-white ring-1 ring-gray-200 focus:ring-2 focus:ring-green-500 text-sm outline-none transition-colors"
              data-testid="shop-search-input"
              style={{ fontSize: '16px' }}
            />
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
          </div>
          {total > 0 && (
            <span className="text-[11px] font-bold text-gray-500 bg-gray-100 px-2.5 py-1 rounded-full">
              {total} {total === 1 ? 'product' : 'products'}
            </span>
          )}
        </div>

        {/* PRODUCT GRID — grouped under each concern title */}
        {visibleProducts.length === 0 ? (
          <div className="bg-white border border-green-100 rounded-2xl p-10 text-center text-sm text-gray-500">
            {debouncedSearch
              ? `No products matched "${debouncedSearch}".`
              : 'No products in this category yet.'}
          </div>
        ) : (
          <>
            {groupedByConcern.map((g, gi) => (
              <section key={g.key} className="mb-10" data-testid={`concern-group-${g.key}`}>
                <div className="flex items-center gap-3 mb-4">
                  <h3 className="font-heading text-xl sm:text-2xl font-black text-gray-900">{g.title}</h3>
                  <span className="text-[11px] font-bold text-green-700 bg-green-50 px-2 py-0.5 rounded-full ring-1 ring-green-100">{g.prods.length}</span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4 sm:gap-5">
                  {g.prods.map((product, i) => (
                    <ProductCard key={`${g.key}-${product.slug}`} product={product} priority={gi === 0 && i < 4} />
                  ))}
                </div>
              </section>
            ))}
            {hasMore && (
              <>
                {/* Sentinel for infinite scroll — auto-loads next page as user scrolls */}
                <InfiniteScrollSentinel onIntersect={loadMore} disabled={loadingMore} />
                <div className="flex justify-center mb-10">
                  <button
                    type="button"
                    onClick={loadMore}
                    disabled={loadingMore}
                    data-testid="shop-load-more"
                    className="px-6 h-11 rounded-full bg-white ring-1 ring-gray-300 text-sm font-bold text-gray-800 hover:bg-gray-50 disabled:opacity-60 transition-colors flex items-center gap-2"
                  >
                    {loadingMore ? (
                      <>
                        <span className="w-4 h-4 border-2 border-green-600 border-t-transparent rounded-full animate-spin" />
                        Loading…
                      </>
                    ) : (
                      <>Load more · {Math.max(0, total - visibleProducts.length)} remaining</>
                    )}
                  </button>
                </div>
              </>
            )}
          </>
        )}

        {/* MORE COMBO DEALS */}
        {otherCombos.length > 0 && (
          <section className="mt-2" data-testid="shop-more-combos">
            <div className="flex flex-col sm:flex-row sm:items-end sm:justify-between gap-3 mb-6">
              <div>
                <p className="text-[11px] font-bold text-green-700 uppercase tracking-[0.25em] mb-1.5 flex items-center gap-2">
                  <span className="h-px w-8 bg-green-600/40" /> Bundle &amp; Save
                </p>
                <h2 className="font-heading text-2xl sm:text-3xl lg:text-4xl font-black text-gray-900 leading-tight">
                  More <span className="italic text-green-700">Combo Deals</span>
                </h2>
                <p className="text-sm text-gray-500 mt-1.5">Targeted routines · Save up to 50%</p>
              </div>
              <div className="flex items-center gap-2 text-[11px] font-bold flex-wrap">
                <span className="bg-green-50 text-green-800 px-3 py-1.5 rounded-full ring-1 ring-green-100 flex items-center gap-1.5"><Truck size={12} /> Free shipping</span>
                <span className="bg-amber-50 text-amber-800 px-3 py-1.5 rounded-full ring-1 ring-amber-100 flex items-center gap-1.5"><Shield size={12} /> 7-Day sealed return</span>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-5 sm:gap-6">
              {otherCombos.map(combo => {
                const savings = (combo.mrp_total || 0) - (combo.combo_prepaid_price || 0);
                return (
                  <div
                    key={combo.combo_id}
                    className="group relative bg-white rounded-3xl ring-1 ring-gray-200/70 hover:ring-green-300 overflow-hidden hover:shadow-[0_20px_60px_-15px_rgba(34,197,94,0.25)] hover:-translate-y-1 transition-all duration-500"
                    data-testid={`shop-combo-card-${combo.combo_id}`}
                  >
                    <div className="grid grid-cols-1 sm:grid-cols-5">
                      {/* IMAGE */}
                      <div className="sm:col-span-2 relative aspect-[4/3] sm:aspect-auto bg-gradient-to-br from-green-50 via-white to-amber-50/40 overflow-hidden">
                        {combo.image ? (
                          <img src={combo.image} alt={combo.name} loading="lazy" className="w-full h-full object-cover transition-transform duration-700 group-hover:scale-105" />
                        ) : (
                          <div className="absolute inset-0 flex items-center justify-center">
                            <Package className="w-14 h-14 text-green-200" />
                          </div>
                        )}
                        <div className="absolute inset-x-0 top-0 p-2.5 flex flex-wrap gap-1.5 justify-between">
                          <div className="flex flex-wrap gap-1.5">
                            {combo.sale_active && (
                              <span
                                className="bg-gradient-to-br from-amber-400 via-yellow-500 to-amber-600 text-white text-[10px] font-black px-2.5 py-1 rounded-full shadow-lg ring-1 ring-amber-300/60 tracking-[0.12em] uppercase"
                                data-testid={`combo-sale-badge-${combo.combo_id}`}
                              >
                                {combo.sale_badge_label || 'FLAT 50% OFF'}
                              </span>
                            )}
                            {combo.badge && (
                              <span className={`text-[10px] font-black px-2.5 py-1 rounded-full shadow-md tracking-wide ${combo.badge === 'Popular' ? 'bg-amber-400 text-amber-950' : 'bg-green-700 text-white'}`}>
                                {combo.badge.toUpperCase()}
                              </span>
                            )}
                          </div>
                        </div>
                        <div className="absolute inset-x-0 bottom-0 p-2.5 flex justify-between items-end">
                          <span className="bg-white/95 backdrop-blur text-green-900 text-[10px] font-black px-2.5 py-1 rounded-full shadow-md flex items-center gap-1">
                            <Package size={10} /> {combo.product_slugs?.length} items
                          </span>
                        </div>
                      </div>

                      {/* DETAILS */}
                      <div className="sm:col-span-3 p-5 flex flex-col">
                        <div className="flex items-center gap-1 mb-1.5">
                          {[1,2,3,4,5].map(i => <Star key={i} size={11} className="fill-amber-400 text-amber-400" />)}
                          <span className="text-[10px] font-bold text-gray-700 ml-0.5">4.9</span>
                          <span className="text-[10px] text-gray-400">· 5k+ kits sold</span>
                        </div>
                        <h3 className="font-heading text-lg sm:text-xl font-black text-gray-900 leading-tight mb-1 group-hover:text-green-700 transition-colors">{combo.name}</h3>
                        <p className="text-xs sm:text-sm text-gray-500 line-clamp-2 mb-3">{combo.description}</p>

                        {/* Mini product list */}
                        {combo.product_slugs?.length > 0 && (
                          <div className="flex items-center gap-1 mb-3 flex-wrap">
                            {combo.product_slugs.slice(0, 4).map(slug => {
                              const p = products.find(pr => pr.slug === slug);
                              return p ? (
                                <span key={slug} className="text-[10px] bg-green-50 text-green-800 font-semibold px-2 py-0.5 rounded-full ring-1 ring-green-100 truncate max-w-[110px]">
                                  {p.short_name}
                                </span>
                              ) : null;
                            })}
                            {combo.product_slugs.length > 4 && (
                              <span className="text-[10px] bg-gray-100 text-gray-700 font-semibold px-2 py-0.5 rounded-full">+{combo.product_slugs.length - 4} more</span>
                            )}
                          </div>
                        )}

                        <div className="mt-auto flex items-end justify-between gap-3 pt-2 border-t border-gray-100">
                          <div>
                            <div className="flex items-baseline gap-1.5">
                              <span className="text-2xl sm:text-3xl font-black text-gray-900 tracking-tight">₹{combo.combo_prepaid_price?.toLocaleString()}</span>
                              <span className="text-xs text-gray-400 line-through">₹{combo.mrp_total?.toLocaleString()}</span>
                            </div>
                            <p className="text-[11px] text-green-700 font-bold mt-0.5">You save ₹{savings.toLocaleString()}</p>
                          </div>
                          {(() => {
                            const slugsInCombo = (combo.product_slugs || []).map(s => products.find(p => p.slug === s)).filter(Boolean);
                            // Only a RESOLVED TBL member (or the combo's own flag)
                            // marks it TBL — an unresolved list no longer forces it.
                            const comboIsTbl = combo.is_to_be_launched || slugsInCombo.some(p => p.is_to_be_launched);
                            if (comboIsTbl) {
                              return (
                                <button
                                  disabled
                                  data-testid={`shop-combo-tbl-${combo.combo_id}`}
                                  className="group/btn relative bg-gradient-to-r from-amber-500 via-amber-600 to-orange-500 text-white px-4 sm:px-5 py-2.5 rounded-full font-black text-xs sm:text-sm flex items-center gap-1.5 shadow-md shadow-amber-700/25 ring-1 ring-amber-300/40 cursor-not-allowed tracking-[0.22em]"
                                >
                                  <Clock size={13} className="animate-pulse" />
                                  <span>TBL</span>
                                </button>
                              );
                            }
                            return (
                              <button
                                onClick={() => addComboToCart(combo.combo_id)}
                                className="group/btn relative bg-gradient-to-r from-green-600 to-green-700 hover:from-green-700 hover:to-green-800 text-white px-4 sm:px-5 py-2.5 rounded-full font-black text-xs sm:text-sm flex items-center gap-1.5 shadow-md shadow-green-700/25 hover:shadow-lg hover:-translate-y-0.5 transition-all"
                                data-testid={`shop-add-combo-${combo.combo_id}`}
                              >
                                <ShoppingCart size={14} />
                                <span className="tracking-wide">ADD KIT</span>
                                <ArrowRight size={13} className="transition-transform group-hover/btn:translate-x-1" />
                              </button>
                            );
                          })()}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

export default ShopPage;

// IntersectionObserver-based sentinel for infinite scroll.
function InfiniteScrollSentinel({ onIntersect, disabled }) {
  const ref = React.useRef(null);
  React.useEffect(() => {
    if (disabled || !ref.current) return;
    const obs = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) onIntersect();
      });
    }, { rootMargin: '600px 0px' });
    obs.observe(ref.current);
    return () => obs.disconnect();
  }, [onIntersect, disabled]);
  return <div ref={ref} data-testid="infinite-scroll-sentinel" style={{ height: 1 }} />;
}

import React, { useEffect, useState, useMemo } from 'react';
import BackButton from '../components/BackButton';
import { Link, useParams } from 'react-router-dom';
import axios from 'axios';
import { Star, ArrowRight, BadgeCheck, Heart, Share2, ChevronLeft, Sparkles, Award, Clock, Check } from 'lucide-react';
import { resolveImageUrl } from '../utils/productImage';
import { addToCart } from './Homepage';
import AddToBagButton from '../components/AddToBagButton';
import CircularCategoryStrip from '../components/CircularCategoryStrip';
import AntiAgingOfferHighlight from '../components/AntiAgingOfferHighlight';
import NicheOffersGrid from '../components/NicheOffersGrid';
import { getProductBrand } from '../utils/brand';
import { prefetchHandlers } from '../utils/routePrefetch';
import { shareProduct } from '../utils/shareProduct';
import { isWishlisted, toggleWishlist } from '../utils/wishlist';
import { cachedGet, prime } from '../utils/apiCache';
import SEOHead, { breadcrumbJsonLd } from '../components/SEOHead';

const API = process.env.REACT_APP_BACKEND_URL;

/**
 * ConcernCategoryPage - shared component for /concern/:slug and /category/:slug.
 *
 * Concern mode:
 *   1. Hero with concern accent
 *   2. CIRCULAR CATEGORY STRIP — shows skincare categories that have products for this concern.
 *   3. (When ?cat=slug query is set OR no categories) - product grid for the selected category / all
 *
 * Category mode:
 *   1. Hero with category accent
 *   2. Product grid (all products in this category)
 */
export default function ConcernCategoryPage({ mode = 'concern' }) {
  const { slug } = useParams();
  const [data, setData] = useState(null);
  const [allCategories, setAllCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeCat, setActiveCat] = useState('all');
  const [activeSubcat, setActiveSubcat] = useState('all');
  const [subcategories, setSubcategories] = useState([]);
  // --- Pagination + server-side search (same pattern as ShopPage) ---
  const [searchTerm, setSearchTerm] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);
  const [total, setTotal] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const PAGE_SIZE = 24;

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(searchTerm.trim()), 300);
    return () => clearTimeout(t);
  }, [searchTerm]);

  // Re-fetch page 1 whenever slug/mode or search term changes
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setActiveCat('all');
    setActiveSubcat('all');
    setPage(1);
    const base = mode === 'concern'
      ? `${API}/api/concerns/${slug}`
      : `${API}/api/categories/${slug}`;
    const qs = new URLSearchParams({ page: '1', limit: String(PAGE_SIZE) });
    if (debouncedSearch) qs.set('search', debouncedSearch);
    const calls = [ axios.get(`${base}?${qs}`) ];
    if (mode === 'concern') {
      calls.push(cachedGet(`${API}/api/categories`));
    } else {
      // Category mode — fetch subcategories scoped to this parent so we can
      // show filter chips at the top of the page.
      calls.push(cachedGet(`${API}/api/subcategories?category=${encodeURIComponent(slug)}`));
    }
    Promise.all(calls)
      .then(([main, second]) => {
        if (cancelled) return;
        setData(main.data);
        setTotal(main.data?.total ?? (main.data?.products?.length || 0));
        setHasMore(!!main.data?.has_next);
        if (second) {
          if (mode === 'concern') setAllCategories(second.data || []);
          else setSubcategories(second.data || []);
        }
      })
      .catch(() => { if (!cancelled) setData(null); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [slug, mode, debouncedSearch]);

  // Fetch next page + append
  const loadMore = async () => {
    if (loadingMore || !hasMore) return;
    setLoadingMore(true);
    try {
      const base = mode === 'concern'
        ? `${API}/api/concerns/${slug}`
        : `${API}/api/categories/${slug}`;
      const qs = new URLSearchParams({ page: String(page + 1), limit: String(PAGE_SIZE) });
      if (debouncedSearch) qs.set('search', debouncedSearch);
      const r = await axios.get(`${base}?${qs}`);
      const next = r.data?.products || [];
      setData(prev => prev ? { ...prev, products: [...(prev.products || []), ...next] } : r.data);
      setHasMore(!!r.data?.has_next);
      setPage(p => p + 1);
    } catch {}
    finally { setLoadingMore(false); }
  };

  const products = data?.products || [];
  const head = mode === 'concern' ? data?.concern : data?.category;

  // For concern mode: categories that have at least 1 product for this concern (with metadata)
  const concernCategoryItems = useMemo(() => {
    if (mode !== 'concern' || !products.length) return [];
    // Count products per category once
    const counts = {};
    for (const p of products) {
      if (p.category) counts[p.category] = (counts[p.category] || 0) + 1;
    }
    const slugs = new Set(Object.keys(counts));

    // Canonical routine order used across the user app (same as SkincareHome
    // virtualGroups + Cosmetics parent order). Categories rendered on the
    // concern page now appear in the SAME order customers see on /skincare and
    // /cosmetics, so the structure is consistent end-to-end.
    const ROUTINE_ORDER = [
      // Skincare — Cleanse & Prep
      'cleansers', 'exfoliators', 'toners-mists',
      // Skincare — Treat
      'serums-treatments', 'essences-ampoules', 'spot-treatments',
      // Skincare — Moisturize
      'moisturizers', 'face-oils', 'barrier-care',
      // Skincare — Protect
      'sunscreens',
      // Skincare — Targeted Care
      'eye-care', 'lip-care', 'brightening-products', 'anti-aging-products',
      // Skincare — Masks & Body
      'masks-packs', 'body-skincare',
      // Cosmetics — Face
      'face-makeup', 'foundation', 'concealer', 'face-primer', 'blush',
      'highlighter', 'contour', 'setting-powder', 'setting-spray',
      // Cosmetics — Lips
      'lips', 'lipstick', 'lip-gloss', 'lip-liner', 'lip-balm',
      // Cosmetics — Eyes
      'eyes', 'eyeshadow', 'eyeliner', 'mascara', 'eyebrow-products',
      // Cosmetics — Nails
      'nails', 'nail-polish', 'nail-care',
      // Cosmetics — Tools & Kits
      'tools-brushes', 'makeup-kits',
    ];
    const orderIndex = Object.fromEntries(ROUTINE_ORDER.map((s, i) => [s, i]));

    return allCategories
      .filter(c => slugs.has(c.slug))
      .map(c => ({
        ...c,
        product_count: counts[c.slug] || 0,
        accent_from: head?.accent_from || '#dcfce7',
        accent_to: head?.accent_to || '#bbf7d0',
      }))
      .sort((a, b) => {
        const ai = orderIndex[a.slug] ?? 999;
        const bi = orderIndex[b.slug] ?? 999;
        if (ai !== bi) return ai - bi;
        // Tie-break: admin sort_order, then alphabetical
        return (a.sort_order ?? 99) - (b.sort_order ?? 99) || (a.name || '').localeCompare(b.name || '');
      });
  }, [products, allCategories, mode, head]);

  // Product grid filter based on activeCat (concern mode) or activeSubcat (category mode)
  const visibleProducts = useMemo(() => {
    let list;
    if (mode === 'concern' && activeCat !== 'all') {
      list = products.filter(p => p.category === activeCat);
    } else if (mode === 'category' && activeSubcat !== 'all') {
      list = products.filter(p => p.subcategory === activeSubcat);
    } else {
      list = products;
    }
    // Image-first override (Feb 2026): products with at least one image
    // always render before products without an image. Stable sort preserves
    // the original sort_order tie-break within each group.
    const hasImg = (p) => !!(p && Array.isArray(p.images) && p.images[0]);
    return list.slice().sort((a, b) => (hasImg(b) ? 1 : 0) - (hasImg(a) ? 1 : 0));
  }, [products, activeCat, activeSubcat, mode]);

  // All subcategories for this category (admin-defined), in sort order.
  // We show ALL of them as chips so the merchant + customer always see the
  // structure ("Best Sellers / Luxury / Everyday") even when products aren't
  // tagged yet. Empty chips are shown disabled with (0) count.
  const visibleSubcategories = useMemo(() => {
    if (mode !== 'category' || !subcategories.length) return [];
    return [...subcategories].sort((a, b) => (a.sort_order ?? 99) - (b.sort_order ?? 99));
  }, [subcategories, mode]);

  if (loading) {
    return (
      <div className="min-h-screen bg-gradient-to-b from-stone-50 via-white to-stone-50" data-testid={`${mode}-page-loading`}>
        <div className="max-w-7xl mx-auto px-3 sm:px-6 pt-3 sm:pt-4"><BackButton /></div>
        {/* Skeleton hero */}
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-8 sm:py-10">
          <div className="h-6 w-40 bg-stone-200 rounded-full animate-pulse mb-3" />
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
  if (!head) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center text-gray-500">
        <div className="text-center">
          <p>Page not found.</p>
          <Link to="/" className="text-green-700 underline mt-2 inline-block">Back to home</Link>
        </div>
      </div>
    );
  }

  const accentFrom = head.accent_from || '#dcfce7';
  const accentText = head.accent_text || '#14532d';

  // ---- SEO ----
  const seoModeLabel = mode === 'concern' ? 'Skin Concern' : 'Category';
  const seoTitle = `${head.name} ${seoModeLabel} | Shop Celesta Glow India`;
  const seoDesc = (head.tagline || head.description || `${head.name} products from Celesta Glow — dermatologist-approved formulas for Indian skin. Free shipping. 7-day sealed-bottle return.`).slice(0, 200);
  const seoPath = mode === 'concern' ? `/concern/${slug}` : `/category/${slug}`;

  return (
    <div className="min-h-screen bg-gradient-to-b from-stone-50 via-white to-stone-50" data-testid={`${mode}-page`}>
      <SEOHead
        title={seoTitle}
        description={seoDesc}
        canonicalPath={seoPath}
        ogImage={head.hero_image || head.image}
        jsonLd={breadcrumbJsonLd([
          { name: 'Home', url: '/' },
          { name: head?.niche === 'cosmetics' ? 'Cosmetics' : 'Skincare',
            url: head?.niche === 'cosmetics' ? '/cosmetics' : '/skincare' },
          { name: head.name, url: seoPath },
        ])}
      />
      {/* SLIM HEADER — same compact look for both concern and category modes */}
      <section className="bg-white border-b border-stone-100">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 py-4 sm:py-5">
          {/* Admin-managed banner image (reflects concern/category image edits) */}
          {(head.hero_image || head.banner_image || head.image) && (
            <div className="mb-3 sm:mb-4 rounded-2xl overflow-hidden ring-1 ring-stone-200 bg-stone-100" data-testid={`${mode}-banner-image`}>
              <img
                src={resolveImageUrl(head.hero_image || head.banner_image || head.image)}
                alt={`${head.name} banner`}
                loading="eager"
                className="w-full h-32 sm:h-52 object-cover"
                onError={(e) => { e.currentTarget.parentElement.style.display = 'none'; }}
              />
            </div>
          )}
          {(() => {
            // Branch the "Back to ..." link based on the page's actual niche.
            // For BOTH concern and category modes we read `head.niche` (the
            // canonical taxonomy niche stored on the document). Previously
            // category mode always fell back to cosmetics → bug when a user
            // landed on a skincare subcategory like "Chemical Exfoliants".
            const niche = head?.niche || (mode === 'category-cosmetics' ? 'cosmetics' : 'skincare');
            const isCosmetic = niche === 'cosmetics';
            const backTo = isCosmetic
              ? { path: '/cosmetics', label: 'Cosmetics' }
              : { path: '/skincare', label: 'Skincare' };
            return (
              <Link
                to={backTo.path}
                className="inline-flex items-center gap-1 text-[11px] sm:text-xs font-semibold mb-2 hover:underline"
                style={{ color: accentText }}
              >
                <ChevronLeft size={13} /> Back to {backTo.label}
              </Link>
            );
          })()}
          <h1 className="font-heading text-xl sm:text-3xl font-black leading-tight tracking-tight" style={{ color: accentText }}>
            {mode === 'concern'
              ? <>For {head.name.toLowerCase()}, choose a <span className="italic">product type</span></>
              : <>{head.name}</>
            }
          </h1>
          {mode === 'category' && head.tagline && (
            <p className="text-xs sm:text-sm font-medium mt-1.5" style={{ color: accentText, opacity: 0.7 }}>
              {head.tagline}
            </p>
          )}
        </div>
      </section>

      {/* CONCERN MODE: CIRCULAR CATEGORY PICKER (inline filter — no redirect).
          Order matches the canonical routine flow used on /skincare & /cosmetics
          so customers see the same structure end-to-end. */}
      {mode === 'concern' && concernCategoryItems.length > 0 && (
        <section className="bg-white border-b border-stone-100">
          <div className="max-w-7xl mx-auto px-3 sm:px-6 py-7 sm:py-10">
            <CircularCategoryStrip
              items={concernCategoryItems}
              title={<>Choose a <span className="italic" style={{ color: accentText }}>product type</span></>}
              subtitle={`Ordered by routine step · ${concernCategoryItems.length} types`}
              accent={accentText}
              testIdPrefix="concern-cat"
              onItemClick={(slug) => setActiveCat(prev => prev === slug ? 'all' : slug)}
              activeSlug={activeCat}
              eagerCount={6}
            />
            {activeCat !== 'all' && (
              <div className="flex items-center justify-center mt-5">
                <button
                  type="button"
                  onClick={() => setActiveCat('all')}
                  className="group inline-flex items-center gap-2 pl-4 pr-3 py-2 rounded-full text-xs sm:text-[13px] font-bold bg-white shadow-sm shadow-emerald-900/5 hover:shadow-md hover:shadow-emerald-900/10 ring-1 ring-stone-200 hover:ring-emerald-200 hover:bg-emerald-50/50 transition-all"
                  style={{ color: accentText }}
                  data-testid="concern-cat-clear"
                >
                  <span className="inline-flex items-center justify-center w-4 h-4 rounded-full" style={{ backgroundColor: accentText, color: '#fff' }}>
                    <svg width="9" height="9" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M2 2L10 10M10 2L2 10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
                    </svg>
                  </span>
                  <span>Showing <span className="capitalize">{(concernCategoryItems.find(i => i.slug === activeCat) || {}).name || activeCat}</span></span>
                  <span className="text-stone-400 font-medium hidden sm:inline">·</span>
                  <span className="text-stone-500 font-medium hidden sm:inline">tap to clear</span>
                </button>
              </div>
            )}
          </div>
        </section>
      )}

      {/* CATEGORY MODE: SUBCATEGORY CHIPS — only render when subcategories exist
          for this category, AND at least one product is tagged. This becomes the
          "Best Sellers / Luxury / Everyday" filter row inside e.g. /category/brow.
          Tap a chip to filter inline; tap "All" to clear. */}
      {mode === 'category' && visibleSubcategories.length > 0 && (
        <section className="bg-white border-b border-stone-100" data-testid="subcategory-chips-section">
          <div className="max-w-7xl mx-auto px-3 sm:px-6 py-5 sm:py-7">
            <p className="text-[10px] sm:text-[11px] font-black tracking-[0.2em] uppercase mb-2.5" style={{ color: accentText }}>
              Browse {head.name}
            </p>
            <div className="flex gap-2 sm:gap-2.5 overflow-x-auto hide-scrollbar pb-1 -mx-1 px-1">
              <button
                type="button"
                onClick={() => setActiveSubcat('all')}
                className={`flex-shrink-0 px-4 py-2 rounded-full text-xs sm:text-sm font-bold transition-all ${
                  activeSubcat === 'all'
                    ? 'text-white shadow-md'
                    : 'bg-stone-100 text-stone-700 hover:bg-stone-200'
                }`}
                style={activeSubcat === 'all' ? { backgroundColor: accentText } : undefined}
                data-testid="subcat-chip-all"
              >
                All ({products.length})
              </button>
              {visibleSubcategories.map(s => {
                const count = products.filter(p => p.subcategory === s.slug).length;
                const isActive = activeSubcat === s.slug;
                const isEmpty  = count === 0;
                return (
                  <button
                    key={s.slug}
                    type="button"
                    disabled={isEmpty}
                    onClick={() => setActiveSubcat(prev => prev === s.slug ? 'all' : s.slug)}
                    className={`flex-shrink-0 px-4 py-2 rounded-full text-xs sm:text-sm font-bold transition-all flex items-center gap-1.5 ${
                      isActive
                        ? 'text-white shadow-md'
                        : isEmpty
                        ? 'bg-stone-50 text-stone-300 cursor-not-allowed'
                        : 'bg-stone-100 text-stone-700 hover:bg-stone-200'
                    }`}
                    style={isActive ? { backgroundColor: accentText } : undefined}
                    data-testid={`subcat-chip-${s.slug}`}
                  >
                    {s.name} <span className="text-[10px] opacity-75">({count})</span>
                  </button>
                );
              })}
            </div>
          </div>
        </section>
      )}

      {/* PRODUCT GRID */}
      <div className="max-w-7xl mx-auto px-3 sm:px-6 py-7 sm:py-12">
        {/* Editorial "Age-Reversal Bash" offer grid — Top Deal + category tiles
            with real Up-to-X%-OFF badges + auto-scrolling price-band strip. */}
        {(slug === 'anti-aging' || String(head?.niche || '').toLowerCase() === 'anti-aging') && (
          <NicheOffersGrid niche="anti-aging" categories={[]} theme="anti-aging" />
        )}
        {/* Anti-Aging offer highlight — FLAT 50% OFF + Zero Tax + Zero Delivery.
            Renders only when admin has sale mode ON and this concern targets anti-aging. */}
        {(slug === 'anti-aging' || String(head?.niche || '').toLowerCase() === 'anti-aging') && (
          <AntiAgingOfferHighlight niche="anti-aging" />
        )}
        <div className="flex items-end justify-between mb-4 sm:mb-5 px-1">
          <h2 className="font-heading text-base sm:text-2xl font-black text-gray-900">
            {total} product{total === 1 ? '' : 's'}
            {mode === 'concern' ? ' for ' : ' in '}
            <span style={{ color: accentText }}>{head.name}</span>
            {visibleProducts.length < total && (
              <span className="ml-2 text-xs font-normal text-stone-500">
                (showing {visibleProducts.length})
              </span>
            )}
          </h2>
          <Link to="/shop" className="text-[11px] sm:text-xs font-bold hover:underline flex items-center gap-1" style={{ color: accentText }}>
            View entire shop <ArrowRight size={12} />
          </Link>
        </div>

        {/* Search bar — server-side, debounced, resets pagination on change */}
        <div className="mb-4 flex items-center gap-2" data-testid="ccp-search-bar">
          <div className="relative flex-1 max-w-md">
            <input
              type="search"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder={`Search in ${head?.name || (mode === 'concern' ? 'this concern' : 'this category')}…`}
              className="w-full pl-10 pr-3 h-11 rounded-xl bg-white ring-1 ring-stone-200 focus:ring-2 focus:ring-stone-500 text-sm outline-none transition-colors"
              data-testid="ccp-search-input"
              style={{ fontSize: '16px' }}
            />
            <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-stone-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
          </div>
          {total > 0 && (
            <span className="text-[11px] font-bold text-stone-500 bg-stone-100 px-2.5 py-1 rounded-full">
              {total} {total === 1 ? 'item' : 'items'}
            </span>
          )}
        </div>

        {visibleProducts.length === 0 ? (
          <div className="bg-white border rounded-2xl p-10 text-center text-sm text-gray-500" style={{ borderColor: accentFrom }}>
            {debouncedSearch
              ? `No products matched "${debouncedSearch}".`
              : `No products yet for this ${mode === 'concern' ? 'concern' : 'category'}. Check back soon!`}
          </div>
        ) : (
          <>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3 sm:gap-5">
              {visibleProducts.map((product, i) => <ProductCard key={product.slug} product={product} priority={i < 4} />)}
            </div>
            {hasMore && (
              <>
                <ConcernInfiniteSentinel onIntersect={loadMore} disabled={loadingMore} />
                <div className="flex justify-center mt-6">
                  <button
                    type="button"
                    onClick={loadMore}
                    disabled={loadingMore}
                    data-testid="ccp-load-more"
                    className="px-6 h-11 rounded-full bg-white ring-1 ring-stone-300 text-sm font-bold text-stone-800 hover:bg-stone-50 disabled:opacity-60 transition-colors flex items-center gap-2"
                  >
                    {loadingMore ? (
                      <>
                        <span className="w-4 h-4 border-2 border-stone-600 border-t-transparent rounded-full animate-spin" />
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
      </div>
    </div>
  );
}


/**
 * Reusable Product Card — clean, minimal layout (Nykaa-style).
 *  - Top ribbon: TBL countdown / Bestseller / New Launch / etc.
 *  - White image area with discount chip top-left + heart top-right.
 *  - Brand label (uppercase eyebrow) + product name + ingredients.
 *  - MRP struck + sale price + green % off.
 *  - Green "Get it for ₹X with WELCOME50" pill.
 *  - "Free Skin Analysis included" small accent line.
 *  - Star rating + review count.
 *  - Pill "ADD TO BAG" button in brand green at the bottom.
 */
export function ProductCard({ product, compact = false, priority = false }) {
  const [wished, setWished] = React.useState(() => isWishlisted(product.slug));
  React.useEffect(() => {
    const onUpd = () => setWished(isWishlisted(product.slug));
    window.addEventListener('wishlistUpdated', onUpd);
    return () => window.removeEventListener('wishlistUpdated', onUpd);
  }, [product.slug]);
  const handleWish = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setWished(toggleWishlist(product.slug));
  };
  return (
    <div
      className="group relative bg-white rounded-2xl ring-1 ring-gray-200/70 hover:ring-green-300 overflow-hidden hover:shadow-[0_18px_50px_-15px_rgba(34,197,94,0.22)] hover:-translate-y-0.5 transition-all duration-500 flex flex-col h-full"
      data-testid={`product-card-${product.slug}`}
    >
      {/* IMAGE — premium gallery card with gradient, dot pattern, floating chips, grounding shadow, hover halo */}
      <Link to={`/product/${product.slug}`} {...prefetchHandlers(`/product/${product.slug}`)} onMouseEnter={() => { prefetchHandlers(`/product/${product.slug}`).onMouseEnter(); prime(`${API}/api/products/${product.slug}`, product); }} onClick={() => prime(`${API}/api/products/${product.slug}`, product)} className="block">
        <div className="relative aspect-square overflow-hidden bg-white rounded-t-2xl">
          {/* Very subtle dot pattern (barely visible on white) */}
          <div
            className="absolute inset-0 opacity-[0.035] pointer-events-none"
            style={{ backgroundImage: 'radial-gradient(circle at 1px 1px, #0f766e 1px, transparent 0)', backgroundSize: '16px 16px' }}
          />

          {/* Hover green halo (subtle) */}
          <div
            className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500 pointer-events-none"
            style={{ background: 'radial-gradient(circle at 50% 55%, rgba(34,197,94,0.10) 0%, transparent 62%)' }}
          />

          {/* Single badge — only the primary badge chosen in admin (no discount %, no extras) */}
          <div className="absolute top-3 left-3 z-20 flex items-start gap-1.5">
            {!product.is_to_be_launched && product.badge && (
              product.badge === 'Bestseller' ? (
                <span className="bg-amber-100/95 text-amber-800 text-[9px] font-black px-2 py-0.5 rounded-full flex items-center gap-1 tracking-[0.12em] uppercase shadow-sm backdrop-blur-sm border border-amber-200/70" data-testid={`badge-${product.slug}`}>
                  <Award size={9} /> Bestseller
                </span>
              ) : product.badge === 'New Launch' ? (
                <span className="bg-green-100/95 text-green-800 text-[9px] font-black px-2 py-0.5 rounded-full flex items-center gap-1 tracking-[0.12em] uppercase shadow-sm backdrop-blur-sm border border-green-200/70" data-testid={`badge-${product.slug}`}>
                  <Sparkles size={9} /> New
                </span>
              ) : (
                <span className="bg-white/95 text-stone-700 text-[9px] font-black px-2 py-0.5 rounded-full flex items-center gap-1 tracking-[0.12em] uppercase shadow-sm backdrop-blur-sm border border-stone-200" data-testid={`badge-${product.slug}`}>
                  <BadgeCheck size={9} /> {product.badge}
                </span>
              )
            )}
          </div>

          {/* Share — floating top-right (replaces previous wishlist heart; bottom wishlist remains) */}
          <button
            type="button"
            aria-label="Share product"
            onClick={async (e) => {
              e.preventDefault();
              e.stopPropagation();
              const res = await shareProduct({ slug: product.slug, name: product.short_name || product.name });
              if (res && res.copied) {
                try {
                  // Tiny toast-free visual cue — flash the button briefly
                  e.currentTarget.classList.add('ring-2', 'ring-green-300');
                  setTimeout(() => e.currentTarget?.classList.remove('ring-2', 'ring-green-300'), 900);
                } catch {}
              }
            }}
            className="absolute top-3 right-3 z-20 w-8 h-8 rounded-full bg-white/90 backdrop-blur-sm ring-1 ring-stone-200/80 flex items-center justify-center text-stone-500 hover:text-green-600 hover:ring-green-200 hover:bg-white hover:scale-110 transition-all shadow-sm"
            data-testid={`share-top-${product.slug}`}
          >
            <Share2 size={14} />
          </button>

          {/* TBL pill — short, centered */}
          {product.is_to_be_launched && (
            <div className="absolute top-3 left-1/2 -translate-x-1/2 z-20 bg-gradient-to-r from-green-700 to-green-800 text-white text-[10px] font-black px-3 py-1 rounded-full flex items-center gap-1 shadow-lg shadow-green-900/25 tracking-[0.18em] uppercase whitespace-nowrap">
              <Clock size={9} /> TBL
            </div>
          )}

          {/* Product image — fits entirely inside a generous uniform square frame.
              Using object-contain (not cover) so tall bottles / wide jars aren't cropped.
              Light off-white background gives a clean catalog look. */}
          <div className="absolute inset-0 flex items-center justify-center p-3 sm:p-4 bg-gradient-to-br from-stone-50 via-white to-stone-50">
            {product.images?.[0] ? (
              <>
                <img
                  src={resolveImageUrl(product.images[0])}
                  alt={product.short_name}
                  loading={priority ? 'eager' : 'lazy'}
                  fetchpriority={priority ? 'high' : 'auto'}
                  decoding={priority ? 'sync' : 'async'}
                  width="400"
                  height="400"
                  className="relative z-[2] max-w-full max-h-full w-auto h-auto object-contain transition-all duration-700 ease-out group-hover:scale-[1.04]"
                />
                {/* Secondary image crossfade on hover — always lazy, hover-only */}
                {product.images?.[1] && (
                  <img
                    src={resolveImageUrl(product.images[1])}
                    alt=""
                    loading="lazy"
                    decoding="async"
                    className="absolute inset-0 m-auto max-w-[88%] max-h-[88%] w-auto h-auto object-contain opacity-0 group-hover:opacity-100 transition-opacity duration-500 z-[3]"
                  />
                )}
              </>
            ) : (
              <div className="w-20 h-20 rounded-full bg-green-50 flex items-center justify-center ring-1 ring-green-100">
                <Sparkles className="w-8 h-8 text-green-300" />
              </div>
            )}
          </div>

          {/* Corner accent glow */}
          <div className="absolute bottom-0 right-0 w-24 h-24 opacity-[0.08] pointer-events-none" style={{ background: 'radial-gradient(circle at 100% 100%, #0f766e 0%, transparent 70%)' }} />
        </div>
      </Link>

      {/* CONTENT — same structure for live and TBL products. Strict min-heights
           keep every row aligned across cards regardless of text length. */}
      <div className="px-3 sm:px-4 pb-3 sm:pb-4 pt-1 flex flex-col flex-1 border-t border-stone-100">
        {/* Golden 50% OFF ribbon — full-width above the brand eyebrow, so it
            never overlaps the image or the top-left badge, and reads clean on
            narrow 5-col grids. */}
        {product.sale_active && (
          <div
            className="mt-2 -mx-0 bg-gradient-to-r from-amber-400 via-yellow-500 to-amber-600 text-white text-[10px] font-black text-center py-1 rounded-md flex items-center justify-center gap-1 tracking-[0.15em] uppercase shadow-sm ring-1 ring-amber-300/60"
            data-testid={`sale-badge-${product.slug}`}
          >
            <Sparkles size={10} /> {product.sale_badge_label || 'FLAT 50% OFF'}
          </div>
        )}

        {/* Dermatologist test-report badge removed on listing cards (Jan 2026) so
            concern/category cards match the clean homepage card exactly. */}

        {/* BRAND EYEBROW (per-niche, with product.brand override) */}
        <p className="text-[9px] sm:text-[10px] font-black tracking-[0.22em] uppercase text-green-700 mb-0.5 mt-2 leading-none h-3">{getProductBrand(product)}</p>

        {/* TITLE — up to 2 lines, height shrinks to fit single-line titles so the
            gap to ingredients stays tight (grid still aligns rows to the tallest). */}
        <Link to={`/product/${product.slug}`}>
          <h3 className="font-semibold text-stone-900 text-[13px] sm:text-[14px] leading-snug mb-0.5 group-hover:text-green-700 line-clamp-2 transition-colors min-h-[17px] sm:min-h-[20px]" data-testid={`product-name-${product.slug}`}>
            {product.short_name}
          </h3>
        </Link>

        {/* INGREDIENTS / SIZE — hidden for cosmetics (ingredients aren't the hero);
            shown for skincare + anti-aging where actives matter. */}
        {product.niche === 'cosmetics' ? (
          <p className="text-[10px] sm:text-[11px] text-stone-500 line-clamp-1 mb-1 h-[14px] sm:h-[16px]">
            {product.size || product.tagline || ''}
          </p>
        ) : (
          <p className="text-[10px] sm:text-[11px] text-stone-500 line-clamp-1 mb-1 h-[14px] sm:h-[16px]">
            {product.key_ingredients || product.size || 'Clinically formulated'}
          </p>
        )}

        {/* PRICE ROW — fixed height so cards with no discount still align */}
        <div className="flex items-baseline flex-nowrap gap-x-1.5 sm:gap-x-2 mb-2 h-[22px] sm:h-[26px]">
          <span className="text-base sm:text-lg font-black text-stone-900 leading-none">₹{product.prepaid_price}</span>
          <span className="text-[11px] sm:text-xs text-stone-400 line-through">₹{product.mrp}</span>
        </div>

        {/* COUPON PILL — fixed height */}
        <div className="inline-flex items-center gap-1.5 self-start bg-green-50 border border-green-100 rounded-full px-2 mb-1.5 h-[22px] max-w-full">
          <span className="w-3.5 h-3.5 bg-green-600 rounded-full flex items-center justify-center flex-shrink-0">
            <Check size={8} className="text-white" strokeWidth={3} />
          </span>
          <p className="text-[10px] sm:text-[11px] text-green-800 font-bold leading-none truncate">
            Get it for ₹{product.prepaid_price - 50}
          </p>
        </div>

        {/* COMPLIMENTARY GIFT LINE — fixed height */}
        <p className="text-[10px] sm:text-[11px] text-emerald-700 font-bold mb-2 flex items-center gap-1 h-[14px] sm:h-[16px] leading-none">
          <Sparkles size={10} /> Free skin analysis included
        </p>

        {/* RATING — fixed height */}
        <div className="flex items-center gap-1 mb-2.5 h-[14px] leading-none">
          <div className="flex">
            {[1,2,3,4,5].map(i => (
              <Star key={i} size={11} className={i <= Math.floor(product.rating || 4.8) ? 'fill-amber-400 text-amber-400' : 'text-stone-200'} />
            ))}
          </div>
          <span className="text-[10px] sm:text-[11px] text-stone-500">({product.reviews_count?.toLocaleString() || '0'})</span>
        </div>

        {/* VIEW ALL VARIATIONS — appears only when this base product has generated
            variations. Opens the /customize page listing all of them. */}
        {product.variation_count > 0 && (
          <Link
            to={`/customize/${product.slug}`}
            onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-1 self-start text-[11px] font-bold text-sky-700 hover:text-sky-900 mb-2.5"
            data-testid={`view-variations-${product.slug}`}
          >
            View all {product.variation_count} variations <ArrowRight size={12} />
          </Link>
        )}

        {/* SHADE SWATCHES — show first 5 shades + "+N more" pill */}
        {Array.isArray(product.shades) && product.shades.length > 0 && (
          <div className="flex items-center gap-1.5 mb-2.5" data-testid={`shades-strip-${product.slug}`}>
            {product.shades.slice(0, 5).map(s => (
              <span
                key={s.id}
                title={s.name}
                aria-label={s.name}
                className="w-4 h-4 sm:w-[18px] sm:h-[18px] rounded-full ring-1 ring-stone-200 ring-offset-1 ring-offset-white inline-block"
                style={{ background: s.hex || '#ccc' }}
              />
            ))}
            {product.shades.length > 5 && (
              <span className="text-[10px] text-stone-500 font-semibold ml-1">+{product.shades.length - 5}</span>
            )}
          </div>
        )}

        {/* CTA ROW — TBL products are NEVER orderable (purely informational pill).
            Only when admin sets the product LIVE (is_to_be_launched=false) can users add to cart. */}
        {product.is_to_be_launched ? (
          <div className="mt-auto flex items-center gap-2">
            <button
              type="button"
              aria-label={wished ? 'Remove from wishlist' : 'Add to wishlist'}
              aria-pressed={wished}
              onClick={handleWish}
              className={`w-9 h-9 sm:w-10 sm:h-10 rounded-full ring-1 flex items-center justify-center transition-all flex-shrink-0 ${wished ? 'bg-rose-50 ring-rose-200 text-rose-500' : 'bg-white ring-stone-200 text-stone-400 hover:text-rose-500 hover:ring-rose-200'}`}
              data-testid={`wishlist-cta-${product.slug}`}
            >
              <Heart size={15} className={wished ? 'fill-rose-500 text-rose-500' : ''} />
            </button>
            <Link
              to={`/product/${product.slug}`}
              onClick={(e) => e.stopPropagation()}
              className="flex-1 relative overflow-hidden bg-gradient-to-r from-amber-500 via-amber-600 to-orange-500 hover:from-amber-600 hover:via-amber-700 hover:to-orange-600 text-white text-[12px] sm:text-sm font-black py-2.5 sm:py-3 rounded-full flex items-center justify-center gap-1.5 transition-all shadow-md shadow-amber-700/25 hover:shadow-lg hover:-translate-y-0.5 ring-1 ring-amber-400/40"
              data-testid={`tbl-cta-${product.slug}`}
              aria-label="View TBL product details"
            >
              <span className="absolute inset-0 bg-[radial-gradient(circle_at_30%_50%,rgba(255,255,255,0.35)_0%,transparent_60%)] pointer-events-none" />
              <span className="relative flex items-center justify-center gap-1.5">
                <Clock size={12} className="animate-pulse" />
                <span className="tracking-[0.22em] text-sm">TBL</span>
              </span>
            </Link>
          </div>
        ) : (
          <div className="mt-auto flex items-center gap-2">
            <button
              type="button"
              aria-label={wished ? 'Remove from wishlist' : 'Add to wishlist'}
              aria-pressed={wished}
              onClick={handleWish}
              className={`w-9 h-9 sm:w-10 sm:h-10 rounded-full ring-1 flex items-center justify-center transition-all flex-shrink-0 ${wished ? 'bg-rose-50 ring-rose-200 text-rose-500' : 'bg-white ring-stone-200 text-stone-400 hover:text-rose-500 hover:ring-rose-200'}`}
              data-testid={`wishlist-cta-${product.slug}`}
            >
              <Heart size={15} className={wished ? 'fill-rose-500 text-rose-500' : ''} />
            </button>
            <AddToBagButton slug={product.slug} />
          </div>
        )}
      </div>
    </div>
  );
}



/**
 * IntersectionObserver-based "load more" sentinel.
 * Fires `onIntersect` whenever the sentinel scrolls into view.
 */
export function ConcernInfiniteSentinel({ onIntersect, disabled = false }) {
  const ref = React.useRef(null);
  React.useEffect(() => {
    if (disabled) return;
    const el = ref.current;
    if (!el || typeof IntersectionObserver === 'undefined') return;
    const obs = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            onIntersect?.();
            break;
          }
        }
      },
      { rootMargin: '600px 0px' }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [onIntersect, disabled]);
  return <div ref={ref} aria-hidden="true" style={{ height: 1 }} data-testid="ccp-infinite-sentinel" />;
}

import React from 'react';
import { Link } from 'react-router-dom';
import { Leaf } from 'lucide-react';

/**
 * IngredientSpotlight — 3-card row showcasing hero actives (Retinol, Vit C,
 * Niacinamide). Tapping each card deep-links to /shop?niche=skincare&ingredient=...
 * so the merchandiser can curate ingredient-specific landing pages later.
 *
 * Self-contained with no API calls — content is admin-friendly (just edit the
 * INGREDIENTS array below). Renders only when the parent passes `enabled`.
 */
const INGREDIENTS = [
  {
    id: 'retinol',
    name: 'Retinol',
    tagline: 'Smooths fine lines',
    description: 'Clinical-grade vitamin A that boosts cell turnover.',
    gradient: 'linear-gradient(135deg, #fce7f3 0%, #fbcfe8 100%)',
    accent: '#9f1239',
  },
  {
    id: 'vitamin-c',
    name: 'Vitamin C',
    tagline: 'Brightens & evens tone',
    description: '20% L-Ascorbic Acid for radiance and dark spot reduction.',
    gradient: 'linear-gradient(135deg, #fef3c7 0%, #fde68a 100%)',
    accent: '#a16207',
  },
  {
    id: 'niacinamide',
    name: 'Niacinamide',
    tagline: 'Controls oil & pores',
    description: '10% concentration to minimize pores and balance sebum.',
    gradient: 'linear-gradient(135deg, #d1fae5 0%, #a7f3d0 100%)',
    accent: '#047857',
  },
];

export default function IngredientSpotlight({ accent = '#0e7490', items = null, subtitle = null }) {
  // When `items` is provided (e.g. from a product's key ingredients) we render
  // them in the brand green/white theme. Otherwise fall back to the curated set.
  const usingProduct = Array.isArray(items) && items.length > 0;
  const cards = usingProduct
    ? items.slice(0, 3).map((it, i) => ({
        id: `${it.name}-${i}`.toLowerCase().replace(/\s+/g, '-'),
        name: it.name,
        tagline: it.tagline || 'Key active',
        description: it.description || `${it.name} is a hero active in this formula.`,
        gradient: 'linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%)',
        accent: '#047857',
      }))
    : INGREDIENTS;

  // On a product page (items provided) render a clean LINEAR list aligned to the
  // column; on the homepage keep the 3-card grid.
  if (usingProduct) {
    return (
      <section className="mt-6" data-testid="ingredient-spotlight">
        <p className="text-xs font-bold text-gray-400 uppercase tracking-[0.15em] mb-3 flex items-center gap-2">
          <Leaf size={12} style={{ color: accent }} /> Ingredient Spotlight
        </p>
        <div className="rounded-2xl ring-1 ring-emerald-100 bg-white divide-y divide-emerald-50 overflow-hidden">
          {cards.map((ing) => (
            <div key={ing.id} data-testid={`ingredient-${ing.id}`} className="flex items-start gap-3 p-4">
              <span className="mt-1 shrink-0 w-2.5 h-2.5 rounded-full" style={{ background: accent }} />
              <div className="min-w-0">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <h3 className="font-heading text-base font-black text-stone-900">{ing.name}</h3>
                  <span className="text-[11px] font-bold uppercase tracking-wide" style={{ color: ing.accent || accent }}>{ing.tagline}</span>
                </div>
                <p className="text-sm text-stone-600 leading-relaxed mt-0.5">{ing.description}</p>
              </div>
            </div>
          ))}
        </div>
        {subtitle && <p className="text-xs text-stone-400 mt-2">{subtitle}</p>}
      </section>
    );
  }
  return (
    <section className="max-w-7xl mx-auto px-3 sm:px-6 py-8 sm:py-12" data-testid="ingredient-spotlight">
      <div className="flex items-end justify-between mb-4 sm:mb-6 px-1">
        <div>
          <p className="text-[10px] sm:text-[11px] font-bold tracking-[0.4em] uppercase mb-1 flex items-center gap-2" style={{ color: accent }}>
            <Leaf size={11} /> Hero Actives
          </p>
          <h2 className="font-heading text-lg sm:text-2xl lg:text-3xl font-black text-gray-900 leading-tight">
            Ingredient <span className="italic" style={{ color: accent }}>spotlight</span>
          </h2>
          {subtitle && <p className="text-xs sm:text-sm text-stone-500 mt-1">{subtitle}</p>}
        </div>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 sm:gap-5">
        {cards.map((ing) => (
          <div
            key={ing.id}
            data-testid={`ingredient-${ing.id}`}
            className="relative overflow-hidden rounded-3xl p-5 sm:p-6 ring-1 ring-emerald-100 hover:-translate-y-1 hover:shadow-2xl transition-all"
            style={{ background: ing.gradient }}
          >
            <p className="text-[10px] font-black tracking-[0.3em] uppercase mb-2" style={{ color: ing.accent }}>{ing.tagline}</p>
            <h3 className="font-heading text-2xl sm:text-3xl font-black text-stone-900 mb-2">{ing.name}</h3>
            <p className="text-xs sm:text-sm text-stone-700 leading-relaxed line-clamp-3">{ing.description}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

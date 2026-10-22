import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Images, Sparkles, Loader2, Download, Check, Search, ShoppingBag, Pencil, X, RotateCcw } from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;
const adminToken = () => sessionStorage.getItem('adminToken') || localStorage.getItem('adminToken') || '';
const hdr = () => ({ headers: { 'X-Admin-Token': adminToken() } });

const SLOTS = [
  { key: 'hero', label: 'Hero + Headline' },
  { key: 'ingredients', label: 'Key Ingredients' },
  { key: 'how_it_works', label: 'How It Works' },
  { key: 'who_for', label: "Who It's For" },
  { key: 'results', label: 'Results / Stat' },
];

const downloadImg = async (url, filename) => {
  try {
    const res = await fetch(url, { mode: 'cors' });
    const blob = await res.blob();
    const href = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = href; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(href), 1500);
  } catch {
    window.open(url, '_blank');
  }
};

// Admin tool: generate marketplace listing images (Amazon squares + Flipkart tall
// JPGs) for any store product, in Celesta Glow's own brand colours. Generated
// images persist on the product; each image type has an editable prompt.
export default function EcomImageGenerator() {
  const [products, setProducts] = useState([]);
  const [loadingProducts, setLoadingProducts] = useState(true);
  const [slug, setSlug] = useState('');
  const [q, setQ] = useState('');
  const [slots, setSlots] = useState(SLOTS.map((s) => s.key));
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  // prompt editor state
  const [defaults, setDefaults] = useState({});
  const [custom, setCustom] = useState({});
  const [editingSlot, setEditingSlot] = useState(null);
  const [draft, setDraft] = useState('');
  const [savingPrompt, setSavingPrompt] = useState(false);

  useEffect(() => {
    setLoadingProducts(true);
    // Admin picker must see EVERY product (inactive, out-of-stock and AI
    // variations too) — the public endpoint hides those by default.
    axios.get(`${API}/api/products?limit=1000&active_only=false&include_variations=true`, hdr()).then((r) => {
      const list = Array.isArray(r.data) ? r.data : (r.data.items || r.data.products || []);
      setProducts(list);
    }).catch(() => setProducts([]))
      .finally(() => setLoadingProducts(false));
  }, []);

  // Load saved images + prompts whenever a product is selected (so the section
  // shows previously generated images after refresh / reopen).
  useEffect(() => {
    if (!slug) return;
    setResult(null); setEditingSlot(null);
    axios.get(`${API}/api/admin/products/${slug}/ecom-images`, hdr())
      .then((r) => { if ((r.data?.amazon?.length) || (r.data?.flipkart?.length)) setResult(r.data); })
      .catch(() => {});
    axios.get(`${API}/api/admin/products/${slug}/ecom-prompts`, hdr())
      .then((r) => { setDefaults(r.data?.defaults || {}); setCustom(r.data?.custom || {}); })
      .catch(() => { setDefaults({}); setCustom({}); });
  }, [slug]);

  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase();
    return t ? products.filter((p) => `${p.name} ${p.brand}`.toLowerCase().includes(t)) : products;
  }, [products, q]);

  const selected = products.find((p) => p.slug === slug);
  const toggleSlot = (k) => setSlots((s) => (s.includes(k) ? s.filter((x) => x !== k) : [...s, k]));

  const openEditor = (k) => {
    setEditingSlot(k);
    setDraft((custom[k] || '').trim() ? custom[k] : (defaults[k] || ''));
  };

  const savePrompt = async () => {
    if (!slug || !editingSlot) return;
    setSavingPrompt(true);
    try {
      const res = await axios.put(`${API}/api/admin/products/${slug}/ecom-prompts`, { slot: editingSlot, prompt: draft }, hdr());
      setCustom((c) => ({ ...c, [editingSlot]: res.data?.custom || '' }));
      toast.success(res.data?.custom ? 'Custom prompt saved' : 'Reverted to default prompt');
      setEditingSlot(null);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Could not save prompt');
    } finally {
      setSavingPrompt(false);
    }
  };

  const generate = async () => {
    if (!slug) { toast.error('Pick a product first'); return; }
    if (!slots.length) { toast.error('Select at least one image type'); return; }
    setBusy(true);
    try {
      const res = await axios.post(`${API}/api/admin/products/${slug}/ecom-images`, { slots }, hdr());
      setResult(res.data);
      toast.success(`Generated ${res.data.amazon?.length || 0} Amazon + ${res.data.flipkart?.length || 0} Flipkart images — saved to this product`);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Generation failed (AI key / Cloudinary)');
    } finally {
      setBusy(false);
    }
  };

  const downloadAll = async (list, platform) => {
    for (let i = 0; i < list.length; i += 1) {
      // eslint-disable-next-line no-await-in-loop
      await downloadImg(list[i].url, `${slug}-${platform}-${i + 1}-${list[i].slot}.jpg`);
      // eslint-disable-next-line no-await-in-loop
      await new Promise((r) => setTimeout(r, 400));
    }
  };

  const Grid = ({ title, list, platform, tall }) => (
    <div data-testid={`ecom-${platform}-section`}>
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-bold text-gray-900 text-sm flex items-center gap-2"><ShoppingBag size={15} className="text-emerald-600" /> {title} <span className="text-[11px] font-normal text-gray-400">({list.length})</span></h3>
        {list.length > 0 && (
          <button onClick={() => downloadAll(list, platform)} className="flex items-center gap-1.5 text-xs font-bold text-emerald-700 hover:text-emerald-900" data-testid={`ecom-download-all-${platform}`}><Download size={13} /> Download all JPG</button>
        )}
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        {list.map((it, i) => (
          <div key={`${it.slot}-${i}`} className="group relative rounded-xl border border-gray-200 overflow-hidden bg-gray-50" data-testid={`ecom-${platform}-img-${i}`}>
            <img src={it.url} alt={it.slot} className={`w-full object-contain bg-white ${tall ? 'aspect-[1179/2010]' : 'aspect-square'}`} loading="lazy" />
            <div className="absolute top-1.5 left-1.5 text-[10px] font-bold bg-white/90 text-gray-700 rounded px-1.5 py-0.5">{(SLOTS.find((s) => s.key === it.slot) || {}).label || it.slot}</div>
            <button onClick={() => downloadImg(it.url, `${slug}-${platform}-${i + 1}-${it.slot}.jpg`)} className="absolute bottom-1.5 right-1.5 flex items-center gap-1 text-[11px] font-bold bg-gray-900/85 text-white rounded-md px-2 py-1 opacity-0 group-hover:opacity-100 transition-opacity" data-testid={`ecom-download-${platform}-${i}`}><Download size={12} /> JPG</button>
          </div>
        ))}
      </div>
    </div>
  );

  return (
    <div className="max-w-6xl mx-auto px-4 py-6" data-testid="ecom-image-generator">
      <div className="flex items-center gap-2 mb-1">
        <span className="w-9 h-9 rounded-lg bg-emerald-50 flex items-center justify-center"><Images size={18} className="text-emerald-600" /></span>
        <h1 className="text-xl font-bold text-gray-900">E-commerce Image Generator</h1>
      </div>
      <p className="text-sm text-gray-500 mb-5">Generate marketplace listing images for any product — Amazon squares (1000×1000) and Flipkart tall JPGs (1179×2010, creative centred) — in Celesta Glow brand colours. Results are saved to the product.</p>

      <div className="grid md:grid-cols-[320px_1fr] gap-5">
        {/* Picker */}
        <div className="bg-white rounded-xl border border-gray-200 p-4 h-fit">
          <div className="relative mb-3">
            <Search size={15} className="absolute left-2.5 top-2.5 text-gray-400" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search products…" className="w-full pl-8 pr-3 py-2 text-sm border border-gray-200 rounded-lg" data-testid="ecom-product-search" />
          </div>
          <div className="max-h-72 overflow-y-auto space-y-1 pr-1" data-testid="ecom-product-list">
            {loadingProducts ? (
              <p className="text-xs text-gray-400 text-center py-6 flex items-center justify-center gap-2"><Loader2 size={13} className="animate-spin" /> Loading products…</p>
            ) : (
              <>
                {filtered.map((p) => (
                  <button key={p.slug} onClick={() => setSlug(p.slug)} className={`w-full flex items-center gap-2 p-2 rounded-lg text-left text-sm ${slug === p.slug ? 'bg-emerald-50 ring-1 ring-emerald-300' : 'hover:bg-gray-50'}`} data-testid={`ecom-product-${p.slug}`}>
                    <img src={(p.images || [])[0] || p.image} alt="" className="w-9 h-9 rounded object-cover bg-gray-100 shrink-0" />
                    <span className="flex-1 min-w-0 truncate text-gray-800">{p.name}</span>
                    {slug === p.slug && <Check size={15} className="text-emerald-600 shrink-0" />}
                  </button>
                ))}
                {filtered.length === 0 && <p className="text-xs text-gray-400 text-center py-6">No products found</p>}
              </>
            )}
          </div>
        </div>

        {/* Controls + output */}
        <div className="space-y-5">
          <div className="bg-white rounded-xl border border-gray-200 p-4">
            <p className="text-xs font-bold text-gray-700 mb-2">Image types to generate <span className="font-normal text-gray-400">(tap ✎ to edit its prompt)</span></p>
            <div className="flex flex-wrap gap-2 mb-4">
              {SLOTS.map((s) => (
                <span key={s.key} className={`inline-flex items-center rounded-full border ${slots.includes(s.key) ? 'bg-emerald-600 border-emerald-600' : 'bg-white border-gray-200'}`}>
                  <button onClick={() => toggleSlot(s.key)} className={`text-xs font-semibold pl-3 pr-1.5 py-1.5 ${slots.includes(s.key) ? 'text-white' : 'text-gray-600'}`} data-testid={`ecom-slot-${s.key}`}>
                    {slots.includes(s.key) && <Check size={12} className="inline mr-1" />}{s.label}
                    {(custom[s.key] || '').trim() ? <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400 ml-1.5 align-middle" title="Custom prompt" /> : null}
                  </button>
                  <button onClick={() => openEditor(s.key)} disabled={!slug} title={slug ? 'Edit prompt' : 'Select a product first'}
                    className={`pr-2 py-1.5 rounded-r-full disabled:opacity-30 ${slots.includes(s.key) ? 'text-white/90 hover:text-white' : 'text-gray-400 hover:text-emerald-700'}`}
                    data-testid={`ecom-prompt-edit-${s.key}`}>
                    <Pencil size={12} />
                  </button>
                </span>
              ))}
            </div>

            {/* Prompt editor */}
            {editingSlot && (
              <div className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50/40 p-3" data-testid="ecom-prompt-editor">
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs font-bold text-gray-800">Prompt — {(SLOTS.find((s) => s.key === editingSlot) || {}).label}
                    {(custom[editingSlot] || '').trim() && <span className="ml-2 text-[10px] font-semibold text-amber-600 bg-amber-100 rounded-full px-2 py-0.5">Custom</span>}
                  </p>
                  <div className="flex items-center gap-1">
                    <button onClick={() => setDraft(defaults[editingSlot] || '')} className="flex items-center gap-1 text-[11px] font-semibold text-gray-500 hover:text-gray-800" data-testid="ecom-prompt-reset"><RotateCcw size={11} /> Reset</button>
                    <button onClick={() => setEditingSlot(null)} className="p-1 hover:bg-gray-100 rounded" data-testid="ecom-prompt-close"><X size={14} className="text-gray-500" /></button>
                  </div>
                </div>
                <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={7} className="w-full text-xs font-mono text-gray-800 border border-gray-200 rounded-lg p-2.5 leading-relaxed" data-testid="ecom-prompt-textarea" />
                <div className="flex justify-end gap-2 mt-2">
                  <button onClick={() => { setDraft(''); }} className="text-xs font-semibold text-gray-500 hover:text-gray-800" data-testid="ecom-prompt-clear">Clear (use default)</button>
                  <button onClick={savePrompt} disabled={savingPrompt} className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white rounded-lg text-xs font-bold" data-testid="ecom-prompt-save">
                    {savingPrompt ? <Loader2 size={12} className="animate-spin" /> : <Check size={12} />} Save prompt
                  </button>
                </div>
              </div>
            )}

            <div className="flex items-center justify-between gap-3">
              <p className="text-[11px] text-gray-400">{selected ? <>Selected: <b className="text-gray-600">{selected.name}</b></> : 'Pick a product on the left.'} Each image uses AI credits.</p>
              <button onClick={generate} disabled={busy || !slug} className="flex items-center gap-2 px-4 py-2.5 bg-gray-900 hover:bg-black disabled:opacity-40 text-white rounded-lg text-sm font-bold shrink-0" data-testid="ecom-generate-btn">
                {busy ? <><Loader2 size={15} className="animate-spin" /> Generating…</> : <><Sparkles size={15} /> Generate images</>}
              </button>
            </div>
            {busy && <p className="text-[11px] text-amber-600 mt-2">This can take ~15-25s per image — please wait.</p>}
          </div>

          {result && (
            <div className="space-y-6">
              <Grid title="Amazon (square 1000×1000)" list={result.amazon || []} platform="amazon" tall={false} />
              <Grid title="Flipkart (tall 1179×2010 — image 1 same as Amazon)" list={result.flipkart || []} platform="flipkart" tall />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

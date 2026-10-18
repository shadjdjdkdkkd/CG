import React, { useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { ShoppingBag, Sparkles, Copy, Loader2, Check } from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;
const adminToken = () => sessionStorage.getItem('adminToken') || localStorage.getItem('adminToken') || '';
const hdr = () => ({ headers: { 'X-Admin-Token': adminToken() } });

const CopyBtn = ({ text, id, copied, setCopied }) => (
  <button onClick={() => { navigator.clipboard.writeText(text); setCopied(id); setTimeout(() => setCopied(''), 1500); }}
    className="inline-flex items-center gap-1 text-[11px] font-bold text-emerald-700 hover:text-emerald-900" data-testid={`copy-${id}`}>
    {copied === id ? <Check size={13} /> : <Copy size={13} />} {copied === id ? 'Copied' : 'Copy'}
  </button>
);

// Admin AI tool: generate an Amazon / Flipkart marketplace listing for any store product.
export default function AmazonFlipkartListing() {
  const [products, setProducts] = useState([]);
  const [slug, setSlug] = useState('');
  const [platform, setPlatform] = useState('amazon');
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [copied, setCopied] = useState('');

  useEffect(() => {
    axios.get(`${API}/api/products?limit=300`).then((r) => {
      const list = Array.isArray(r.data) ? r.data : (r.data.products || []);
      setProducts(list);
    }).catch(() => setProducts([]));
  }, []);

  const filtered = useMemo(() => {
    const t = q.trim().toLowerCase();
    return t ? products.filter((p) => `${p.name} ${p.brand}`.toLowerCase().includes(t)) : products;
  }, [products, q]);

  const generate = async () => {
    if (!slug) { toast.error('Pick a product first'); return; }
    setBusy(true); setResult(null);
    try {
      const r = await axios.post(`${API}/api/admin/listing/generate`, { product_slug: slug, platform }, hdr());
      setResult(r.data.listing);
      toast.success('Listing generated');
    } catch (e) { toast.error(e.response?.data?.detail || 'Generation failed'); }
    finally { setBusy(false); }
  };

  return (
    <div className="max-w-4xl mx-auto px-4 sm:px-6 py-8" data-testid="amazon-flipkart-listing">
      <div className="flex items-center gap-2.5 mb-1">
        <div className="w-10 h-10 rounded-xl bg-amber-100 text-amber-700 flex items-center justify-center"><ShoppingBag size={20} /></div>
        <div>
          <h1 className="text-2xl font-extrabold text-stone-900">Amazon &amp; Flipkart Listing</h1>
          <p className="text-sm text-stone-500">AI-generate a ready-to-paste marketplace listing for any product.</p>
        </div>
      </div>

      <div className="mt-6 bg-white rounded-2xl ring-1 ring-stone-200 p-5">
        <div className="flex gap-2 mb-4">
          {[['amazon', 'Amazon'], ['flipkart', 'Flipkart']].map(([k, l]) => (
            <button key={k} onClick={() => setPlatform(k)} data-testid={`platform-${k}`}
              className={`px-5 py-2 rounded-full text-sm font-bold ${platform === k ? 'bg-amber-500 text-white' : 'bg-stone-100 text-stone-600'}`}>{l}</button>
          ))}
        </div>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search products…"
          className="w-full rounded-xl border border-stone-200 px-4 py-2.5 text-sm mb-3" data-testid="listing-search" />
        <select value={slug} onChange={(e) => setSlug(e.target.value)} data-testid="listing-product-select"
          className="w-full rounded-xl border border-stone-200 px-4 py-3 text-sm bg-white">
          <option value="">Select a product…</option>
          {filtered.map((p) => <option key={p.slug} value={p.slug}>{p.name}</option>)}
        </select>
        <button onClick={generate} disabled={busy || !slug} data-testid="listing-generate"
          className="mt-4 w-full bg-emerald-700 hover:bg-emerald-800 disabled:opacity-50 text-white font-extrabold rounded-full py-3.5 text-sm inline-flex items-center justify-center gap-2">
          {busy ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />} Generate {platform === 'amazon' ? 'Amazon' : 'Flipkart'} listing
        </button>
      </div>

      {result && (
        <div className="mt-6 space-y-4" data-testid="listing-result">
          <div className="bg-white rounded-2xl ring-1 ring-stone-200 p-5">
            <div className="flex items-center justify-between mb-1"><h3 className="font-bold text-stone-900">Title</h3><CopyBtn text={result.title} id="title" copied={copied} setCopied={setCopied} /></div>
            <p className="text-sm text-stone-700">{result.title}</p>
          </div>
          <div className="bg-white rounded-2xl ring-1 ring-stone-200 p-5">
            <div className="flex items-center justify-between mb-2"><h3 className="font-bold text-stone-900">Bullet points</h3><CopyBtn text={(result.bullets || []).join('\n')} id="bullets" copied={copied} setCopied={setCopied} /></div>
            <ul className="list-disc pl-5 space-y-1 text-sm text-stone-700">{(result.bullets || []).map((b, i) => <li key={i}>{b}</li>)}</ul>
          </div>
          <div className="bg-white rounded-2xl ring-1 ring-stone-200 p-5">
            <div className="flex items-center justify-between mb-1"><h3 className="font-bold text-stone-900">Description</h3><CopyBtn text={result.description} id="desc" copied={copied} setCopied={setCopied} /></div>
            <p className="text-sm text-stone-700 whitespace-pre-line">{result.description}</p>
          </div>
          {result.search_terms?.length > 0 && (
            <div className="bg-white rounded-2xl ring-1 ring-stone-200 p-5">
              <div className="flex items-center justify-between mb-2"><h3 className="font-bold text-stone-900">Backend search terms</h3><CopyBtn text={(result.search_terms || []).join(', ')} id="terms" copied={copied} setCopied={setCopied} /></div>
              <div className="flex flex-wrap gap-1.5">{result.search_terms.map((t, i) => <span key={i} className="text-xs bg-stone-100 rounded-full px-2.5 py-1 text-stone-600">{t}</span>)}</div>
            </div>
          )}
          {result.category_suggestion && <p className="text-xs text-stone-500">Suggested category: <span className="font-semibold text-stone-700">{result.category_suggestion}</span></p>}
        </div>
      )}
    </div>
  );
}

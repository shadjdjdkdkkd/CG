import React, { useState, useEffect, useRef, useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import axios from 'axios';
import { Package, Plus, Edit, Trash2, Image as ImageIcon, DollarSign, Eye, EyeOff, Save, X, ChevronDown, Tag, Settings, Layers, Upload, Trash, Clock, Rocket, GripVertical, ArrowUp, ArrowDown, ArrowLeft, LayoutDashboard, Sparkles, Crop } from 'lucide-react';
import { List } from 'react-window';
import ImageCropperModal from '../../components/admin/ImageCropperModal';
import ShadeEditor from '../../components/admin/ShadeEditor';
import { resolveImageUrl } from '../../utils/productImage';
import { GenerationProgress } from '../../components/admin/GenerationProgress';
import { RegenerateImageModal } from '../../components/admin/RegenerateImageModal';
import { AiVariationsModal } from '../../components/admin/AiVariationsModal';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Reusable image uploader/replacer
// - Multi-file selection (3-6 at once) with parallel upload
// - Per-image progress and instant local preview while uploading
// - Drag-to-reorder + up/down/first/last arrow buttons
// - Position badges so the merchant always knows the gallery order
function ImageManager({ images = [], onChange, label = 'Images', single = false, headers, maxImages = 8, slug = null, onGenerated = null }) {
  const fileRef = useRef(null);
  const [uploading, setUploading] = useState(false);
  const [pending, setPending] = useState([]); // [{ id, previewUrl, progress, error }]
  const [removingBgIndex, setRemovingBgIndex] = useState(-1);
  const [dragIndex, setDragIndex] = useState(-1);
  const [overIndex, setOverIndex] = useState(-1);
  // Crop modal state — `cropTarget` is one of:
  //   { mode: 'add', src }                        → cropping a fresh upload
  //   { mode: 'replace', src, index }             → cropping a replacement file
  //   { mode: 'edit',    src, index }             → re-cropping an existing tile
  const [cropTarget, setCropTarget] = useState(null);
  const [generating, setGenerating] = useState(false);
  const [upscaling, setUpscaling] = useState(false);

  const handleUpscale = async () => {
    if (!slug) { alert('Save the product first.'); return; }
    setUpscaling(true);
    try {
      const res = await axios.post(
        `${API}/admin/products/${slug}/upscale-images`, {}, { headers }
      );
      if (res.data?.images) onChange(res.data.images);
      alert(`Upscaled ${res.data?.upscaled || 0} image(s) to high resolution (certificate & before/after left untouched).`);
    } catch (e) {
      alert(e.response?.data?.detail || 'Upscale failed.');
    } finally {
      setUpscaling(false);
    }
  };

  const handleGenerate = async () => {
    if (!slug) { alert('Save the product first (it needs a slug), then upload a hero image before generating.'); return; }
    if (!(images && images.length)) { alert('Upload a hero product image first — the bottle in it is used as the source for every generated image.'); return; }
    setGenerating(true);
    try {
      const res = await axios.post(
        `${API}/admin/products/${slug}/generate-images`,
        { gallery: true, certificate: true },
        { headers }
      );
      if (res.data?.images) onChange(res.data.images);
      if (onGenerated) onGenerated(res.data);
    } catch (e) {
      alert(e.response?.data?.detail || 'Image generation failed.');
    } finally {
      setGenerating(false);
    }
  };

  const uploadBlob = async (blob, onProgress) => {
    if (!blob) return null;
    const fd = new FormData();
    fd.append('file', blob, blob.name || `cropped_${Date.now()}.jpg`);
    try {
      const res = await axios.post(`${API}/admin/upload-image`, fd, {
        headers: { ...headers, 'Content-Type': 'multipart/form-data' },
        onUploadProgress: (ev) => {
          if (typeof onProgress === 'function' && ev.total) {
            onProgress(Math.round((ev.loaded * 100) / ev.total));
          }
        },
      });
      return res.data.url;
    } catch (e) {
      throw new Error(e.response?.data?.detail || 'Upload failed');
    }
  };
  const upload = uploadBlob; // backward compatible alias used below

  const handleAdd = async (e) => {
    const files = Array.from(e.target.files || []);
    e.target.value = '';
    if (!files.length) return;

    // Single-image mode: just take the first
    if (single) {
      setUploading(true);
      try {
        const url = await upload(files[0]);
        if (url) onChange(url);
      } catch (err) {
        alert(err.message || 'Upload failed');
      } finally {
        setUploading(false);
      }
      return;
    }

    // Multi-image mode: cap at maxImages total, upload in parallel
    const currentCount = (images || []).length;
    const allowed = Math.max(0, maxImages - currentCount);
    const slice = files.slice(0, allowed);
    if (slice.length < files.length) {
      alert(`You can have at most ${maxImages} images. Adding the first ${slice.length}.`);
    }
    if (!slice.length) return;

    // Show optimistic local previews while uploads are in flight
    const queued = slice.map((f) => ({
      id: `${Date.now()}_${Math.random().toString(36).slice(2)}`,
      previewUrl: URL.createObjectURL(f),
      progress: 0,
      error: null,
    }));
    setPending((p) => [...p, ...queued]);
    setUploading(true);

    try {
      const results = await Promise.allSettled(
        slice.map((file, i) =>
          upload(file, (pct) => {
            setPending((p) => p.map((q) => (q.id === queued[i].id ? { ...q, progress: pct } : q)));
          }).then((url) => ({ id: queued[i].id, url }))
        )
      );

      const newUrls = [];
      const failures = [];
      results.forEach((r, i) => {
        if (r.status === 'fulfilled' && r.value?.url) newUrls.push(r.value.url);
        else failures.push({ id: queued[i].id, message: r.reason?.message || 'Upload failed' });
      });

      // Append all successful uploads in their original selection order
      if (newUrls.length) onChange([...(images || []), ...newUrls]);
      // Mark failures so user can see them briefly, then clear
      if (failures.length) {
        setPending((p) =>
          p.map((q) => {
            const f = failures.find((x) => x.id === q.id);
            return f ? { ...q, error: f.message } : q;
          })
        );
        setTimeout(() => setPending((p) => p.filter((q) => !q.error)), 4000);
        alert(`${failures.length} image(s) failed: ${failures[0].message}`);
      }
    } finally {
      // Drop the previews that were successfully uploaded
      setPending((p) => p.filter((q) => q.error));
      setUploading(false);
      // Revoke any object URLs we no longer need
      queued.forEach((q) => URL.revokeObjectURL(q.previewUrl));
    }
  };

  const handleReplace = async (index, e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setUploading(true);
    try {
      const url = await upload(file);
      if (!url) return;
      const next = [...images];
      next[index] = url;
      onChange(next);
    } catch (err) {
      alert(err.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const handleRemove = (index) => {
    if (single) { onChange(''); return; }
    onChange(images.filter((_, i) => i !== index));
  };

  // ---- Reorder helpers ----
  const move = (from, to) => {
    if (from === to || from < 0 || to < 0 || from >= images.length || to >= images.length) return;
    const next = [...images];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    onChange(next);
  };
  const moveUp    = (i) => move(i, i - 1);
  const moveDown  = (i) => move(i, i + 1);
  const moveFirst = (i) => move(i, 0);
  const moveLast  = (i) => move(i, images.length - 1);

  // ---- HTML5 drag-and-drop ----
  const onDragStart = (i) => (e) => {
    setDragIndex(i);
    try { e.dataTransfer.effectAllowed = 'move'; } catch {}
  };
  const onDragOver = (i) => (e) => {
    e.preventDefault();
    if (overIndex !== i) setOverIndex(i);
  };
  const onDragLeave = () => setOverIndex(-1);
  const onDrop = (i) => (e) => {
    e.preventDefault();
    if (dragIndex >= 0 && dragIndex !== i) move(dragIndex, i);
    setDragIndex(-1);
    setOverIndex(-1);
  };
  const onDragEnd = () => { setDragIndex(-1); setOverIndex(-1); };

  const handleRemoveBg = async (index, mode = 'white') => {
    const imgUrl = images[index];
    if (!imgUrl) return;
    const absoluteUrl = imgUrl.startsWith('http') ? imgUrl : `${process.env.REACT_APP_BACKEND_URL}${imgUrl}`;
    setRemovingBgIndex(index);
    try {
      const res = await axios.post(
        `${API}/admin/ai/remove-bg`,
        { image_url: absoluteUrl, mode },
        { headers }
      );
      if (res.data?.image_url) {
        const next = [...images];
        next[index] = res.data.image_url;
        onChange(next);
      }
    } catch (e) {
      alert(e.response?.data?.detail || 'AI background removal failed. Check GEMINI_API_KEY in backend settings.');
    } finally {
      setRemovingBgIndex(-1);
    }
  };

  // Single-image mode (for hero banner / bundle hero) — unchanged behaviour
  if (single) {
    const url = images;
    return (
      <div>
        <label className="text-xs font-semibold text-gray-500 block mb-1.5">{label}</label>
        <div className="flex items-center gap-3">
          <div className="w-20 h-20 bg-gray-100 rounded-xl overflow-hidden flex items-center justify-center border border-gray-200">
            {url ? <img src={url} alt="" className="w-full h-full object-cover" data-testid="single-image-preview" /> : <ImageIcon className="w-6 h-6 text-gray-400" />}
          </div>
          <div className="flex flex-col gap-1.5">
            <input type="file" accept="image/*" ref={fileRef} onChange={handleAdd} className="hidden" data-testid={`upload-${label}`} />
            <button type="button" onClick={() => fileRef.current?.click()} disabled={uploading} className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 text-white rounded-lg text-xs font-semibold disabled:opacity-50">
              <Upload size={12} /> {uploading ? 'Uploading...' : (url ? 'Replace' : 'Upload')}
            </button>
            {url && <button type="button" onClick={() => onChange('')} className="flex items-center gap-1 px-3 py-1.5 bg-red-50 text-red-600 rounded-lg text-xs font-semibold"><Trash size={12} /> Remove</button>}
          </div>
        </div>
      </div>
    );
  }

  // Multi-image mode (product images) — multi-upload + drag-reorder
  const total = (images?.length || 0) + pending.length;
  const remaining = Math.max(0, maxImages - (images?.length || 0));

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label className="text-xs font-semibold text-gray-500">
          {label || 'Images'} ({total}/{maxImages})
        </label>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleGenerate}
            disabled={generating}
            title="Auto-build the Formula-Technology gallery cards + lab certificate from the hero image"
            className="flex items-center gap-1.5 px-2.5 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-[11px] font-bold disabled:opacity-50"
            data-testid="generate-gallery-btn"
          >
            <Sparkles size={12} className={generating ? 'animate-pulse' : ''} />
            {generating ? 'Generating…' : 'Generate Gallery + Certificate'}
          </button>
          <button
            type="button"
            onClick={handleUpscale}
            disabled={upscaling}
            title="One-tap AI upscale of all generated product images (certificate & before/after are left untouched)"
            className="flex items-center gap-1.5 px-2.5 py-1.5 bg-violet-600 hover:bg-violet-700 text-white rounded-lg text-[11px] font-bold disabled:opacity-50"
            data-testid="upscale-images-btn"
          >
            <Sparkles size={12} className={upscaling ? 'animate-pulse' : ''} />
            {upscaling ? 'Upscaling…' : 'AI Upscale Images'}
          </button>
          <p className="hidden sm:block text-[10px] text-gray-400">Drag or ▲▼ to reorder · 1st = cover</p>
        </div>
      </div>

      <div className="grid grid-cols-3 sm:grid-cols-4 gap-2" data-testid="image-manager-grid">
        {(images || []).map((url, i) => {
          const isDragSource = dragIndex === i;
          const isDropTarget = overIndex === i && dragIndex !== i;
          return (
            <div
              key={`${url}-${i}`}
              draggable
              onDragStart={onDragStart(i)}
              onDragOver={onDragOver(i)}
              onDragLeave={onDragLeave}
              onDrop={onDrop(i)}
              onDragEnd={onDragEnd}
              data-testid={`image-tile-${i}`}
              className={`relative group aspect-square bg-gray-100 rounded-xl overflow-hidden border-2 transition-all ${
                isDropTarget ? 'border-green-500 scale-[1.02]' : 'border-gray-200'
              } ${isDragSource ? 'opacity-40' : ''}`}
            >
              <img src={resolveImageUrl(url)} alt="" className="w-full h-full object-cover pointer-events-none" />

              {/* Position badge (1, 2, 3 ...) */}
              <div className="absolute top-1.5 left-1.5 bg-black/70 text-white text-[10px] font-black w-5 h-5 rounded-full flex items-center justify-center shadow-md">
                {i + 1}
              </div>
              {/* Cover badge for the first image */}
              {i === 0 && (
                <div className="absolute top-1.5 right-1.5 bg-emerald-600 text-white text-[9px] font-black px-1.5 py-0.5 rounded-md uppercase tracking-wide shadow-md">
                  Cover
                </div>
              )}

              {removingBgIndex === i && (
                <div className="absolute inset-0 bg-white/90 flex flex-col items-center justify-center gap-1 z-10">
                  <div className="w-6 h-6 border-2 border-green-500 border-t-transparent rounded-full animate-spin" />
                  <span className="text-[10px] font-bold text-green-700">AI cleaning...</span>
                </div>
              )}

              {/* Hover toolbar */}
              <div className="absolute inset-0 bg-black/0 group-hover:bg-black/55 transition-colors flex flex-wrap items-center justify-center gap-1 p-1 opacity-0 group-hover:opacity-100">
                {/* Drag handle hint */}
                <span className="absolute top-1 left-7 p-1 text-white/80 cursor-grab" title="Drag to reorder">
                  <GripVertical size={12} />
                </span>
                {/* Up / Down */}
                <button type="button" onClick={() => moveUp(i)} disabled={i === 0} className="p-1.5 bg-white rounded-lg shadow-md disabled:opacity-40" title="Move up" data-testid={`img-up-${i}`}>
                  <ArrowUp size={12} className="text-gray-700" />
                </button>
                <button type="button" onClick={() => moveDown(i)} disabled={i === images.length - 1} className="p-1.5 bg-white rounded-lg shadow-md disabled:opacity-40" title="Move down" data-testid={`img-down-${i}`}>
                  <ArrowDown size={12} className="text-gray-700" />
                </button>
                {/* Replace */}
                <label className="cursor-pointer p-1.5 bg-white rounded-lg shadow-md" title="Replace this image">
                  <Upload size={12} className="text-gray-700" />
                  <input type="file" accept="image/*" onChange={(e) => handleReplace(i, e)} className="hidden" />
                </label>
                {/* Crop existing image */}
                <button
                  type="button"
                  onClick={() => setCropTarget({ mode: 'edit', src: url, index: i })}
                  className="p-1.5 bg-white rounded-lg shadow-md"
                  title="Crop / re-frame this image"
                  data-testid={`crop-${i}`}
                >
                  <Crop size={12} className="text-emerald-700" />
                </button>
                {/* AI clean bg */}
                <button
                  type="button"
                  onClick={() => handleRemoveBg(i, 'white')}
                  disabled={removingBgIndex !== -1}
                  className="p-1.5 bg-white rounded-lg shadow-md disabled:opacity-50"
                  title="AI: clean background → pure white"
                  data-testid={`remove-bg-${i}`}
                >
                  <Sparkles size={12} className="text-fuchsia-600" />
                </button>
                {/* Remove */}
                <button type="button" onClick={() => handleRemove(i)} className="p-1.5 bg-white rounded-lg shadow-md" title="Remove">
                  <Trash size={12} className="text-red-600" />
                </button>
              </div>
            </div>
          );
        })}

        {/* In-flight upload tiles (instant preview + per-file progress) */}
        {pending.map((q) => (
          <div key={q.id} className="relative aspect-square bg-gray-100 rounded-xl overflow-hidden border-2 border-dashed border-green-300" data-testid={`pending-${q.id}`}>
            <img src={q.previewUrl} alt="" className="w-full h-full object-cover opacity-60" />
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 bg-white/40">
              {q.error ? (
                <span className="text-[10px] font-bold text-rose-700 px-1.5 text-center">{q.error}</span>
              ) : (
                <>
                  <div className="w-5 h-5 border-2 border-green-600 border-t-transparent rounded-full animate-spin" />
                  <span className="text-[10px] font-bold text-green-700">{q.progress}%</span>
                </>
              )}
            </div>
          </div>
        ))}

        {/* Add tile (only if under maxImages) */}
        {remaining > 0 && (
          <button
            type="button"
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            className="aspect-square border-2 border-dashed border-gray-300 rounded-xl flex flex-col items-center justify-center gap-1 text-gray-400 hover:border-green-400 hover:text-green-600 transition-colors text-xs disabled:opacity-50"
            data-testid="image-add-tile"
          >
            <Upload size={18} />
            <span>{uploading ? 'Uploading…' : `Add (${remaining} left)`}</span>
            <span className="text-[9px] text-gray-400">Pick up to {Math.min(remaining, 6)} at once</span>
          </button>
        )}

        <input
          type="file"
          accept="image/*"
          multiple
          ref={fileRef}
          onChange={handleAdd}
          className="hidden"
          data-testid="image-multi-input"
        />
      </div>

      {/* Image cropper — opens when admin clicks the Crop icon on any tile */}
      <ImageCropperModal
        open={!!cropTarget}
        imageSrc={cropTarget?.src || ''}
        defaultAspect={1}
        onCancel={() => setCropTarget(null)}
        onConfirm={async (blob) => {
          const target = cropTarget;
          setCropTarget(null);
          if (!target || !blob) return;
          setUploading(true);
          try {
            const url = await uploadBlob(blob);
            if (!url) return;
            if (target.mode === 'edit' || target.mode === 'replace') {
              const next = [...images];
              next[target.index] = url;
              onChange(next);
            } else {
              // 'add' — append
              onChange([...(images || []), url]);
            }
          } catch (err) {
            alert(err.message || 'Crop upload failed');
          } finally {
            setUploading(false);
          }
        }}
      />
    </div>
  );
}

// Chip-style ingredients input — type then press Enter/comma to chip, X to remove.
// Stores as a comma-separated string so it's compatible with the existing
// product.key_ingredients field on the customer side (we just split on "+" / "," to render).
function IngredientsChipInput({ value = '', onChange }) {
  const [draft, setDraft] = useState('');
  const tokens = (value || '')
    .split(/[,+]/g)
    .map(s => s.trim())
    .filter(Boolean);
  const setTokens = (arr) => onChange(arr.filter(Boolean).join(', '));
  const commit = () => {
    const t = draft.trim().replace(/,+$/, '').trim();
    if (!t) { setDraft(''); return; }
    if (!tokens.includes(t)) setTokens([...tokens, t]);
    setDraft('');
  };
  const onKey = (e) => {
    if (e.key === 'Enter' || e.key === ',') { e.preventDefault(); commit(); }
    else if (e.key === 'Backspace' && !draft && tokens.length) {
      setTokens(tokens.slice(0, -1));
    }
  };
  return (
    <div className="w-full px-2 py-2 border rounded-lg text-sm bg-white flex flex-wrap gap-1.5 items-center" data-testid="ingredients-chip-input">
      {tokens.map((t, i) => (
        <span key={i} className="inline-flex items-center gap-1 bg-emerald-50 text-emerald-800 border border-emerald-200 rounded-full px-2.5 py-0.5 text-xs font-semibold">
          {t}
          <button type="button" className="text-emerald-600 hover:text-emerald-900" onClick={() => setTokens(tokens.filter((_, j) => j !== i))} data-testid={`remove-ingredient-${i}`}>×</button>
        </span>
      ))}
      <input
        value={draft}
        onChange={(e) => {
          const v = e.target.value;
          // If user pastes a comma-separated list, split on commas and add each
          if (v.includes(',')) {
            const parts = v.split(',').map(s => s.trim()).filter(Boolean);
            const merged = [...tokens];
            parts.forEach(p => { if (p && !merged.includes(p)) merged.push(p); });
            setTokens(merged);
            setDraft('');
          } else {
            setDraft(v);
          }
        }}
        onKeyDown={onKey}
        onBlur={commit}
        placeholder={tokens.length ? 'Add more…' : 'e.g. Retinol, Vitamin C, Niacinamide'}
        className="flex-1 min-w-[140px] px-1 py-1 outline-none bg-transparent"
      />
    </div>
  );
}



// Predefined badges with color mapping
const BADGE_PRESETS = [
  { key: 'Bestseller',       color: 'bg-amber-100 text-amber-900 ring-amber-300' },
  { key: 'New Launch',       color: 'bg-emerald-100 text-emerald-900 ring-emerald-300' },
  { key: 'Daily Essential',  color: 'bg-sky-100 text-sky-900 ring-sky-300' },
  { key: 'Limited Edition',  color: 'bg-rose-100 text-rose-900 ring-rose-300' },
  { key: 'Trending',         color: 'bg-fuchsia-100 text-fuchsia-900 ring-fuchsia-300' },
  { key: 'Premium',          color: 'bg-violet-100 text-violet-900 ring-violet-300' },
  { key: 'Combo Deal',       color: 'bg-orange-100 text-orange-900 ring-orange-300' },
  { key: 'Eco-Friendly',     color: 'bg-lime-100 text-lime-900 ring-lime-300' },
];

function BadgeChips({ value = [], onChange }) {
  const [custom, setCustom] = useState('');
  const has = (k) => value.includes(k);
  const toggle = (k) => onChange(has(k) ? value.filter(x => x !== k) : [...value, k]);
  const addCustom = () => {
    const v = (custom || '').trim();
    if (!v || has(v)) return;
    onChange([...value, v]);
    setCustom('');
  };
  return (
    <div className="rounded-xl border border-amber-100 bg-amber-50/40 p-3 space-y-2" data-testid="badges-section">
      <div className="flex items-center gap-2">
        <Tag size={14} className="text-amber-700" />
        <span className="text-xs font-bold text-amber-900 tracking-wide">BADGES (multi-select)</span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {BADGE_PRESETS.map(b => (
          <button
            key={b.key}
            type="button"
            onClick={() => toggle(b.key)}
            className={`px-2.5 py-1 rounded-full text-[11px] font-bold ring-1 transition-all ${has(b.key) ? b.color : 'bg-white text-gray-500 ring-gray-200 hover:bg-gray-50'}`}
            data-testid={`badge-chip-${b.key.toLowerCase().replace(/\s+/g,'-')}`}
          >
            {has(b.key) ? '✓ ' : ''}{b.key}
          </button>
        ))}
        {value.filter(v => !BADGE_PRESETS.find(p => p.key === v)).map(v => (
          <button
            key={v}
            type="button"
            onClick={() => toggle(v)}
            className="px-2.5 py-1 rounded-full text-[11px] font-bold ring-1 bg-stone-200 text-stone-900 ring-stone-300"
          >
            ✓ {v} ×
          </button>
        ))}
      </div>
      <div className="flex gap-1.5">
        <input
          type="text"
          value={custom}
          onChange={e => setCustom(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && (e.preventDefault(), addCustom())}
          placeholder="Custom badge…"
          className="flex-1 px-2.5 py-1.5 text-xs border rounded-lg bg-white"
          data-testid="badge-custom-input"
        />
        <button type="button" onClick={addCustom} className="px-3 py-1.5 text-xs font-bold bg-amber-600 text-white rounded-lg" data-testid="badge-custom-add">Add</button>
      </div>
    </div>
  );
}

function URLAnalyzerModal({ open, onClose, onApply, headers }) {
  const [url, setUrl] = useState('');
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');

  if (!open) return null;

  const analyze = async () => {
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const res = await axios.post(`${API}/admin/scrape/product`, { url }, { headers });
      if (!res.data?.success) {
        setError(res.data?.error || 'Could not extract product data');
      } else {
        setResult(res.data);
      }
    } catch (e) {
      setError(e.response?.data?.detail || e.message || 'Network error');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4" data-testid="url-analyzer-modal">
      <div className="bg-white rounded-2xl shadow-2xl max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="p-5 border-b border-gray-100 flex items-center justify-between">
          <h3 className="font-black text-gray-900 flex items-center gap-2"><DollarSign size={16} className="text-green-600" /> Analyze product URL</h3>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg" data-testid="analyzer-close"><X size={16} /></button>
        </div>
        <div className="p-5 space-y-4">
          <div>
            <label className="text-xs font-semibold text-gray-500">Paste product URL (Amazon, Flipkart, Nykaa, Myntra, Meesho, or any product page)</label>
            <div className="flex gap-2 mt-1">
              <input
                type="url"
                value={url}
                onChange={e => setUrl(e.target.value)}
                placeholder="https://www.amazon.in/dp/…"
                className="flex-1 px-3 py-2.5 border rounded-lg text-sm"
                data-testid="analyzer-url-input"
              />
              <button
                onClick={analyze}
                disabled={!url || loading}
                className="px-4 py-2.5 bg-green-600 hover:bg-green-700 disabled:bg-gray-300 text-white rounded-lg text-sm font-bold whitespace-nowrap"
                data-testid="analyzer-analyze-btn"
              >
                {loading ? 'Analyzing…' : 'Analyze'}
              </button>
            </div>
          </div>
          {error && <div className="bg-red-50 border border-red-200 text-red-800 text-sm rounded-lg p-3" data-testid="analyzer-error">{error}</div>}
          {result && (
            <div className="space-y-3" data-testid="analyzer-result">
              <div className="bg-emerald-50 border border-emerald-200 text-emerald-900 text-xs rounded-lg p-2.5">
                ✓ Found <strong>{result.name}</strong>{result.source_domain && <> from <strong>{result.source_domain}</strong></>}
              </div>
              <pre className="bg-gray-900 text-emerald-200 rounded-lg p-3 overflow-x-auto text-[11px] leading-tight max-h-72">{JSON.stringify(result, null, 2)}</pre>
              <button
                onClick={() => { onApply(result); onClose(); }}
                className="w-full px-4 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-sm font-bold"
                data-testid="analyzer-apply"
              >
                Auto-fill product fields
              </button>
            </div>
          )}
          <div className="text-[11px] text-gray-500 leading-relaxed border-t border-gray-100 pt-3">
            Tries <strong>JSON-LD</strong> first → site-specific selectors (Amazon / Flipkart / Nykaa) → <strong>AI fallback (Claude)</strong> for any unstructured page.
            Some sites (Amazon especially) may block backend scraping; if that happens, paste the URL into the AI fallback or fill manually.
          </div>
        </div>
      </div>
    </div>
  );
}


// Stable row component for the virtualized products list. Receives the
// pre-computed `items` array and a `renderRow` function via `rowProps`, plus
// `index` and `style` from react-window. The `style` prop carries the absolute
// positioning the virtualizer relies on — never override `top`/`height`.
function VirtualProductRow({ index, style, items, renderRow }) {
  const product = items[index];
  if (!product) return null;
  return (
    <div style={style} className="pb-4">
      {renderRow(product)}
    </div>
  );
}

function AdminProducts() {
  const navigate = useNavigate();
  const [products, setProducts] = useState([]);
  const [combos, setCombos] = useState([]);
  const [coupons, setCoupons] = useState([]);
  const [settings, setSettings] = useState({});
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('products');
  const [editProduct, setEditProduct] = useState(null);
  const [editCombo, setEditCombo] = useState(null);
  const [newCombo, setNewCombo] = useState(null);   // null = closed; object = create form open
  const [newCoupon, setNewCoupon] = useState({ code: '', discount_type: 'percentage', discount_value: 10, min_order_amount: 0, max_uses: 100, expiry_days: 30, description: '', show_on_cart: true, is_active: true });
  const [editCoupon, setEditCoupon] = useState(null); // currently edited coupon code (null = none)
  const [editCouponDraft, setEditCouponDraft] = useState({});
  const [editSettings, setEditSettings] = useState(null);
  const [concerns, setConcerns] = useState([]);
  const [categories, setCategories] = useState([]);
  const [subcategories, setSubcategories] = useState([]);
  // One-click Variation Generator modal
  const [varOpen, setVarOpen] = useState(false);
  const [varProductSlug, setVarProductSlug] = useState('');
  const [varConcernSlug, setVarConcernSlug] = useState('');
  const [varRunning, setVarRunning] = useState(false);
  const [varResult, setVarResult] = useState(null);
  // Filters
  const [filterNiche, setFilterNiche] = useState('all');
  const [filterStatus, setFilterStatus] = useState('all'); // all | active | inactive | tbl | live | low_stock
  const [searchTerm, setSearchTerm] = useState('');
  const [analyzerOpen, setAnalyzerOpen] = useState(false);
  const [aiGenerating, setAiGenerating] = useState(false);
  const [aiStep, setAiStep] = useState('');
  const [ocInfo, setOcInfo] = useState(null);
  const [regenProduct, setRegenProduct] = useState(null);
  const [aiVarProduct, setAiVarProduct] = useState(null);
  const [bulkGen, setBulkGen] = useState({ running: false });
  // Bulk-selection state — used by the "select multiple to delete" checkbox UX.
  const [selectedSlugs, setSelectedSlugs] = useState(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  // Hoisted filter pipeline so the bulk-action checkbox can `Select all visible`
  const filteredProducts = useMemo(() => products
    .filter(p => filterNiche === 'all' || p.niche === filterNiche)
    .filter(p => {
      if (filterStatus === 'all') return true;
      if (filterStatus === 'active') return p.is_active;
      if (filterStatus === 'inactive') return !p.is_active;
      if (filterStatus === 'tbl') return p.is_to_be_launched;
      if (filterStatus === 'live') return !p.is_to_be_launched;
      if (filterStatus === 'low_stock') return (p.stock_qty ?? 100) <= (p.low_stock_threshold ?? 10);
      return true;
    })
    .filter(p => {
      if (!searchTerm.trim()) return true;
      const q = searchTerm.toLowerCase();
      return (p.name || '').toLowerCase().includes(q) || (p.slug || '').toLowerCase().includes(q);
    })
  , [products, filterNiche, filterStatus, searchTerm]);
  const adminToken = sessionStorage.getItem('adminToken');

  const [imagesFirst, setImagesFirst] = useState(true);

  const headers = { 'X-Admin-Token': adminToken };

  const fetchAll = async () => {
    setLoading(true);
    try {
      // Use allSettled so a single 401 (e.g. employees lacking access to
      // /admin/coupons) doesn't blank out the entire products list.
      // Default sort = images_first so SKUs with photos surface to the top
      // and the gaps (missing-image rows) cluster at the bottom for batch
      // uploading. Toggle available via the "Images first" pill in the
      // toolbar.
      const sortParam = imagesFirst ? '&sort=images_first' : '';
      const [pR, cR, cpR, sR, cnR, ctR, scR] = await Promise.allSettled([
        // include_variations=true so the admin can see & manage all generated
        // variation SKUs (they are hidden from the public catalog by default).
        axios.get(`${API}/products?active_only=false&include_variations=true${sortParam}`, { headers }),
        axios.get(`${API}/combos?active_only=false`, { headers }),
        axios.get(`${API}/admin/coupons`, { headers }),
        axios.get(`${API}/site-settings`),
        axios.get(`${API}/concerns`),
        axios.get(`${API}/categories`),
        axios.get(`${API}/subcategories`),
      ]);
      if (pR.status === 'fulfilled') setProducts(pR.value.data);
      if (cR.status === 'fulfilled') setCombos(cR.value.data);
      if (cpR.status === 'fulfilled') setCoupons(cpR.value.data);
      if (sR.status === 'fulfilled') setSettings(sR.value.data);
      if (cnR.status === 'fulfilled') setConcerns(cnR.value.data || []);
      if (ctR.status === 'fulfilled') setCategories(ctR.value.data || []);
      if (scR.status === 'fulfilled') setSubcategories(scR.value.data || []);
    } catch (err) { console.error(err); }
    setLoading(false);
  };

  useEffect(() => {
    if (!adminToken) { navigate('/admin'); return; }
    fetchAll();
  }, [imagesFirst]);

  // Refresh taxonomy (concerns/categories/subcategories) every time the product
  // modal opens. Admins often add a new concern or subcategory in another tab
  // and come back here — without this refetch, the chip list would be stale.
  useEffect(() => {
    if (!editProduct) return;
    (async () => {
      try {
        const [cnR, ctR, scR] = await Promise.allSettled([
          axios.get(`${API}/concerns`),
          axios.get(`${API}/categories`),
          axios.get(`${API}/subcategories`),
        ]);
        if (cnR.status === 'fulfilled') setConcerns(cnR.value.data || []);
        if (ctR.status === 'fulfilled') setCategories(ctR.value.data || []);
        if (scR.status === 'fulfilled') setSubcategories(scR.value.data || []);
      } catch { /* non-fatal */ }
    })();
  }, [editProduct?.__isNew, editProduct?.slug]);

  const updateProduct = async (slug, data) => {
    try {
      // Mandatory category check on both create and edit. We only enforce
      // this on real product saves (the cropper / image uploads route through
      // their own helpers).
      if (data && !data.__skipValidation) {
        if (!data.name || !data.name.trim()) {
          alert('Please enter a product name.');
          return;
        }
        if (!data.niche) {
          alert('Please pick a niche (Anti-Aging / Skincare / Cosmetics).');
          return;
        }
        // Category is OPTIONAL — many niches (esp. flagship Anti-Aging products
        // like full kits / serums) don't fit a single category. The product
        // page + niche pages render fine with category=null.
      }
      if (data && data.__isNew) {
        // CREATE flow
        const payload = { ...data };
        delete payload.__isNew;
        // Auto-derive slug if empty
        if (!payload.slug) {
          payload.slug = (payload.name || `product-${Date.now()}`).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
        }
        if (!payload.short_name) payload.short_name = payload.name;
        await axios.post(`${API}/admin/products`, payload, { headers });
        fetchAll();
        setEditProduct(null);
        return;
      }
      await axios.put(`${API}/admin/products/${slug}`, (() => { const d = { ...data }; delete d.__skipValidation; delete d.__isNew; return d; })(), { headers });
      fetchAll();
      setEditProduct(null);
    } catch (err) { alert(err.response?.data?.detail || 'Update failed'); }
  };

  const moveProductInList = async (slug, dir) => {
    // dir: -1 (up) or +1 (down) — bulk reorder current full list
    const idx = products.findIndex(p => p.slug === slug);
    const target = idx + dir;
    if (idx < 0 || target < 0 || target >= products.length) return;
    const reordered = [...products];
    [reordered[idx], reordered[target]] = [reordered[target], reordered[idx]];
    const items = reordered.map((p, i) => ({ slug: p.slug, sort_order: i + 1 }));
    try {
      await axios.post(`${API}/admin/products/reorder`, { items }, { headers });
      fetchAll();
    } catch (err) { alert(err.response?.data?.detail || 'Reorder failed'); }
  };

  const reorderBySlugs = async (orderedSlugs) => {
    const items = orderedSlugs.map((slug, i) => ({ slug, sort_order: i + 1 }));
    try {
      await axios.post(`${API}/admin/products/reorder`, { items }, { headers });
      fetchAll();
    } catch (err) { alert(err.response?.data?.detail || 'Reorder failed'); }
  };

  // Drag & drop state — only the slug being dragged
  const [draggingSlug, setDraggingSlug] = useState(null);
  const [dragOverSlug, setDragOverSlug] = useState(null);
  const handleDrop = (targetSlug) => {
    if (!draggingSlug || draggingSlug === targetSlug) { setDraggingSlug(null); setDragOverSlug(null); return; }
    const arr = [...products];
    const fromIdx = arr.findIndex(p => p.slug === draggingSlug);
    const toIdx = arr.findIndex(p => p.slug === targetSlug);
    if (fromIdx < 0 || toIdx < 0) return;
    const [moved] = arr.splice(fromIdx, 1);
    arr.splice(toIdx, 0, moved);
    setDraggingSlug(null); setDragOverSlug(null);
    reorderBySlugs(arr.map(p => p.slug));
  };

  const deleteProduct = async (slug) => {
    if (!window.confirm(`Delete product "${slug}"?`)) return;
    try {
      await axios.delete(`${API}/admin/products/${slug}`, { headers });
      fetchAll();
    } catch (err) { alert(err.response?.data?.detail || 'Delete failed'); }
  };

  // ---- Bulk operations ----
  const toggleSelect = (slug) => {
    setSelectedSlugs(prev => {
      const next = new Set(prev);
      if (next.has(slug)) next.delete(slug); else next.add(slug);
      return next;
    });
  };
  const selectAllVisible = (slugs, on) => {
    setSelectedSlugs(prev => {
      const next = new Set(prev);
      if (on) slugs.forEach(s => next.add(s));
      else slugs.forEach(s => next.delete(s));
      return next;
    });
  };
  const clearSelection = () => setSelectedSlugs(new Set());
  const bulkDeleteSelected = async () => {
    if (selectedSlugs.size === 0) return;
    if (!window.confirm(`Permanently DELETE ${selectedSlugs.size} selected product(s)? This cannot be undone.`)) return;
    setBulkBusy(true);
    try {
      const res = await axios.post(`${API}/admin/products/bulk-delete`, { slugs: Array.from(selectedSlugs) }, { headers });
      alert(`Deleted ${res.data.deleted}. ${res.data.not_found ? 'Not found: ' + res.data.not_found : ''}`);
      clearSelection();
      fetchAll();
    } catch (err) {
      alert(err.response?.data?.detail || 'Bulk delete failed');
    } finally {
      setBulkBusy(false);
    }
  };
  const bulkDeactivateSelected = async () => {
    if (selectedSlugs.size === 0) return;
    if (!window.confirm(`Deactivate ${selectedSlugs.size} product(s)? They will stop showing on the storefront.`)) return;
    setBulkBusy(true);
    try {
      const res = await axios.post(`${API}/admin/products/bulk-update`, { slugs: Array.from(selectedSlugs), patch: { is_active: false } }, { headers });
      alert(`Deactivated ${res.data.modified}.`);
      clearSelection();
      fetchAll();
    } catch (err) {
      alert(err.response?.data?.detail || 'Bulk update failed');
    } finally {
      setBulkBusy(false);
    }
  };

  // Bulk offer generator — take a % from the admin, recompute
  // prepaid_price = mrp * (1 - %/100) for every selected SKU. `mrp` stays
  // untouched so the strike-through price on cards keeps working.
  const bulkApplyDiscount = async (pct) => {
    if (selectedSlugs.size === 0) return;
    const value = Number(pct);
    if (Number.isNaN(value) || value < 0 || value > 95) {
      alert('Enter a discount between 0 and 95');
      return;
    }
    const label = value === 0 ? 'clear the discount' : `apply ${value}% OFF`;
    if (!window.confirm(`${label} on ${selectedSlugs.size} selected product(s)? Sale price will be recomputed from each product's MRP.`)) return;
    setBulkBusy(true);
    // Optimistic update — recompute prepaid_price / cod_price / discount_percent
    // in the local products state so the % OFF badge appears instantly on every
    // selected row, without waiting for the round-trip + fetchAll refresh.
    const selected = selectedSlugs;
    setProducts(prev => prev.map(p => {
      if (!selected.has(p.slug)) return p;
      const mrp = Number(p.mrp || p.prepaid_price || 0);
      if (mrp <= 0) return p;
      if (value <= 0) {
        return { ...p, prepaid_price: Math.round(mrp), cod_price: Math.round(mrp), discount_percent: 0 };
      }
      const newPrice = Math.max(1, Math.round(mrp * (100 - value) / 100));
      return { ...p, prepaid_price: newPrice, cod_price: newPrice, discount_percent: Math.round(value) };
    }));
    try {
      const res = await axios.post(
        `${API}/admin/products/bulk-apply-discount`,
        { slugs: Array.from(selected), discount_percent: value },
        { headers },
      );
      alert(`Updated ${res.data.updated} product(s). ${res.data.skipped ? `Skipped ${res.data.skipped} without MRP.` : ''}`);
      clearSelection();
      fetchAll();
    } catch (err) {
      alert(err.response?.data?.detail || 'Bulk discount failed');
      // Rollback optimistic state by re-fetching fresh data
      fetchAll();
    } finally {
      setBulkBusy(false);
    }
  };


  const toggleProductActive = async (slug, isActive) => {
    await updateProduct(slug, { is_active: !isActive, __skipValidation: true });
  };

  const updateCombo = async (comboId, data) => {
    try {
      await axios.put(`${API}/admin/combos/${comboId}`, data, { headers });
      fetchAll();
      setEditCombo(null);
    } catch (err) { alert('Update failed'); }
  };

  // Create new combo — niche dropdown lets admin pin combos to anti-aging / skincare /
  // cosmetics so they only appear on the matching `/{niche}/shop` page (or universal).
  const createCombo = async () => {
    if (!newCombo.combo_id?.trim() || !newCombo.name?.trim()) {
      alert('combo_id and name are required');
      return;
    }
    if (!Array.isArray(newCombo.product_slugs) || newCombo.product_slugs.length === 0) {
      alert('Pick at least one product for this combo');
      return;
    }
    try {
      await axios.post(`${API}/admin/combos`, {
        ...newCombo,
        combo_id: newCombo.combo_id.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''),
        niche: newCombo.niche || null,
      }, { headers });
      setNewCombo(null);
      fetchAll();
    } catch (err) {
      alert(err.response?.data?.detail || 'Combo creation failed');
    }
  };

  const deleteCombo = async (comboId) => {
    if (!window.confirm(`Delete combo "${comboId}"? This cannot be undone.`)) return;
    try {
      await axios.delete(`${API}/admin/combos/${comboId}`, { headers });
      fetchAll();
    } catch (err) {
      alert(err.response?.data?.detail || 'Delete failed');
    }
  };

  const createCoupon = async () => {
    if (!newCoupon.code.trim()) return;
    try {
      await axios.post(`${API}/admin/coupons`, { ...newCoupon, code: newCoupon.code.toUpperCase() }, { headers });
      setNewCoupon({ code: '', discount_type: 'percentage', discount_value: 10, min_order_amount: 0, max_uses: 100, expiry_days: 30, description: '', show_on_cart: true, is_active: true });
      fetchAll();
    } catch (err) { alert(err.response?.data?.detail || 'Coupon creation failed'); }
  };

  const startEditCoupon = (coupon) => {
    setEditCoupon(coupon.code);
    setEditCouponDraft({
      discount_type: coupon.discount_type || 'percentage',
      discount_value: coupon.discount_value || 0,
      min_order_amount: coupon.min_order_amount || 0,
      max_uses: coupon.max_uses || 100,
      description: coupon.description || '',
      is_active: coupon.is_active !== false,
      show_on_cart: coupon.show_on_cart !== false,
    });
  };

  const saveEditCoupon = async () => {
    if (!editCoupon) return;
    try {
      await axios.put(`${API}/admin/coupons/${editCoupon}`, editCouponDraft, { headers });
      setEditCoupon(null);
      setEditCouponDraft({});
      fetchAll();
    } catch (err) { alert(err.response?.data?.detail || 'Coupon update failed'); }
  };

  const toggleCouponActive = async (coupon) => {
    try {
      await axios.put(`${API}/admin/coupons/${coupon.code}`, { is_active: !(coupon.is_active !== false) }, { headers });
      fetchAll();
    } catch (err) { alert(err.response?.data?.detail || 'Toggle failed'); }
  };

  const toggleCouponShowOnCart = async (coupon) => {
    try {
      await axios.put(`${API}/admin/coupons/${coupon.code}`, { show_on_cart: !(coupon.show_on_cart !== false) }, { headers });
      fetchAll();
    } catch (err) { alert(err.response?.data?.detail || 'Toggle failed'); }
  };

  const deleteCoupon = async (code) => {
    if (!window.confirm('Delete this coupon?')) return;
    await axios.delete(`${API}/admin/coupons/${code}`, { headers });
    fetchAll();
  };

  const updateSiteSettings = async () => {
    try {
      await axios.put(`${API}/admin/site-settings`, editSettings, { headers });
      setEditSettings(null);
      fetchAll();
    } catch (err) { alert('Update failed'); }
  };

  if (loading) return <div className="flex items-center justify-center h-64"><div className="w-8 h-8 border-4 border-green-500 border-t-transparent rounded-full animate-spin" /></div>;

  const tabs = [
    { key: 'products', label: 'Products', icon: Package },
    { key: 'banners', label: 'Banners', icon: ImageIcon },
    { key: 'combos', label: 'Combos', icon: Layers },
    { key: 'coupons', label: 'Coupons', icon: Tag },
    { key: 'settings', label: 'Site Settings', icon: Settings },
  ];

  // Helper: toggle a product's TBL status quickly (without entering edit mode)
  const toggleTbl = async (slug, current) => {
    try {
      const newStatus = !current;
      await axios.put(`${API}/admin/products/${slug}/launch-status`,
        { is_to_be_launched: newStatus, preorder_enabled: newStatus },
        { headers });
      // Invalidate frontend cache so the change is visible on home/view-all immediately
      try { window.dispatchEvent(new Event('admin-data-changed')); } catch {}
      fetchAll();
    } catch (err) { alert(err.response?.data?.detail || 'Failed to toggle launch status'); }
  };

  return (
    <div className="space-y-6" data-testid="admin-products">
      {regenProduct && (
        <RegenerateImageModal product={regenProduct} headers={headers} onClose={() => setRegenProduct(null)} onApplied={() => { try { window.dispatchEvent(new Event('admin-data-changed')); } catch {} fetchAll(); }} />
      )}
      {aiVarProduct && (
        <AiVariationsModal product={aiVarProduct} headers={headers} onClose={() => setAiVarProduct(null)} onCreated={() => { try { window.dispatchEvent(new Event('admin-data-changed')); } catch {} fetchAll(); }} />
      )}
      {varOpen && (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/50 p-4" data-testid="variation-modal">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg overflow-hidden">
            <div className="px-6 py-4 bg-gradient-to-r from-green-700 to-emerald-600 text-white flex items-center justify-between">
              <div className="flex items-center gap-2 font-bold"><Layers size={18} /> One-Click Gallery + Certificate</div>
              <button type="button" onClick={() => !varRunning && setVarOpen(false)} className="hover:opacity-80"><X size={18} /></button>
            </div>
            <div className="p-6 space-y-5">
              {!varResult ? (
                <>
                  <p className="text-sm text-gray-500">Pick a source product and the concern it solves. One click generates <b>24 targeted variations</b> (2 genders × 3 skin types × 4 age groups) — each with a pure-white gallery, unique copy and its own certificate.</p>
                  <div>
                    <label className="block text-xs font-bold text-gray-600 uppercase tracking-wide mb-1.5">Source Product</label>
                    <select
                      value={varProductSlug}
                      onChange={(e) => setVarProductSlug(e.target.value)}
                      data-testid="variation-product-select"
                      className="w-full border border-gray-300 rounded-xl px-3 py-2.5 text-sm focus:ring-2 focus:ring-green-500 focus:border-green-500 outline-none"
                    >
                      <option value="">— Select a product —</option>
                      {products.filter(p => !p.is_variation).map(p => (
                        <option key={p.slug} value={p.slug}>{p.name}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="block text-xs font-bold text-gray-600 uppercase tracking-wide mb-1.5">Concern this product solves</label>
                    <select
                      value={varConcernSlug}
                      onChange={(e) => setVarConcernSlug(e.target.value)}
                      data-testid="variation-concern-select"
                      className="w-full border border-gray-300 rounded-xl px-3 py-2.5 text-sm focus:ring-2 focus:ring-green-500 focus:border-green-500 outline-none"
                    >
                      <option value="">— Select a concern —</option>
                      {concerns.map(c => (
                        <option key={c.slug} value={c.slug}>{c.name}</option>
                      ))}
                    </select>
                    <p className="text-[11px] text-gray-400 mt-1.5">The concern is highlighted in every variation's name, description, how-to-use and certificate.</p>
                  </div>
                  <div className="flex justify-end gap-2 pt-2">
                    <button type="button" onClick={() => setVarOpen(false)} className="px-4 py-2 rounded-xl text-sm font-semibold text-gray-600 hover:bg-gray-100">Cancel</button>
                    <button
                      type="button"
                      disabled={!varProductSlug || !varConcernSlug || varRunning}
                      data-testid="variation-generate-confirm"
                      onClick={async () => {
                        setVarRunning(true);
                        try {
                          const concernObj = concerns.find(c => c.slug === varConcernSlug);
                          const { data } = await axios.post(
                            `${API}/admin/products/${varProductSlug}/generate-variations`,
                            { concern: varConcernSlug, concern_label: concernObj?.name || '' },
                            { headers }
                          );
                          // Background job — poll until it finishes (24 cards +
                          // certificates can take ~30-60s; this avoids proxy timeouts).
                          const jobId = data?.job_id;
                          let final = data?.result || null;
                          if (jobId && !final) {
                            for (let i = 0; i < 90; i++) {
                              await new Promise(r => setTimeout(r, 2000));
                              let st;
                              try {
                                st = await axios.get(`${API}/admin/products/variations-job/${jobId}`, { headers });
                              } catch { continue; }
                              if (st.data?.status === 'completed') { final = st.data.result; break; }
                              if (st.data?.status === 'failed') { throw new Error(st.data.error || 'Variation generation failed.'); }
                            }
                          }
                          if (!final) throw new Error('Variation generation timed out. Please check the products list — some may have been created.');
                          setVarResult(final);
                          try { window.dispatchEvent(new Event('admin-data-changed')); } catch {}
                          fetchAll();
                        } catch (e) {
                          alert(e.response?.data?.detail || e.message || 'Variation generation failed.');
                        } finally {
                          setVarRunning(false);
                        }
                      }}
                      className="px-4 py-2 rounded-xl text-sm font-bold text-white bg-gradient-to-r from-green-700 to-emerald-600 hover:from-green-800 hover:to-emerald-700 disabled:opacity-50 inline-flex items-center gap-1.5"
                    >
                      <Sparkles size={15} /> {varRunning ? 'Generating 24…' : 'Generate 24 Variations'}
                    </button>
                  </div>
                </>
              ) : (
                <div className="text-center py-4" data-testid="variation-result">
                  <div className="w-14 h-14 rounded-full bg-green-100 text-green-600 flex items-center justify-center mx-auto mb-3"><Sparkles size={26} /></div>
                  <h3 className="text-lg font-bold text-gray-900">Done — {varResult.created} created, {varResult.updated} updated</h3>
                  <p className="text-sm text-gray-500 mt-1">{varResult.total} targeted variations for <b>{varResult.concern_label}</b> are now live with galleries + certificates.</p>
                  <button type="button" onClick={() => setVarOpen(false)} className="mt-5 px-5 py-2 rounded-xl text-sm font-bold text-white bg-green-700 hover:bg-green-800">Close</button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
      {/* Header with back button */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <button
            type="button"
            onClick={() => navigate('/admin')}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-white border border-gray-200 hover:border-green-500 hover:text-green-700 text-gray-700 transition-colors text-sm font-semibold shadow-sm"
            title="Back to dashboard"
            data-testid="admin-back-btn"
          >
            <ArrowLeft size={16} /> <span className="hidden sm:inline">Dashboard</span>
          </button>
          <div className="min-w-0">
            <h1 className="text-2xl font-bold text-gray-900 truncate">Catalog Management</h1>
            <p className="text-gray-500 text-sm">{products.length} products · {combos.length} combos · {coupons.length} coupons</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => { setVarResult(null); setVarProductSlug(''); setVarConcernSlug(''); setVarOpen(true); }}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-gradient-to-r from-green-700 to-emerald-600 hover:from-green-800 hover:to-emerald-700 text-white text-sm font-bold shadow-md hover:shadow-lg"
            data-testid="generate-variations-btn"
            title="Pick a product + the concern it solves — one click generates 24 targeted variations (gender × skin type × age) each with its own gallery + certificate."
          >
            <Layers size={16} /> Generate Gallery + Certificate
          </button>
          <button
            type="button"
            disabled={aiGenerating}
            onClick={async () => {
              const name = window.prompt(
                '⚡ One-Click AI Product Generator (Gemini)\n\n' +
                'STEP 1 of 2 — Type the PRODUCT NAME and click OK.\n' +
                'e.g. "Vitamin C Brightening Serum"',
                ''
              );
              if (!name || !name.trim()) return;
              const ingredients = window.prompt(
                '⚡ One-Click AI Product Generator (Gemini)\n\n' +
                'STEP 2 of 2 — Type the KEY INGREDIENTS (comma separated).\n' +
                'The product image + copy are generated STRICTLY from the name + these ingredients.\n\n' +
                'e.g. "Niacinamide, Alpha Arbutin, Vitamin C, Hyaluronic Acid"\n\n' +
                '(Leave blank to let AI auto-pick suitable actives.)',
                ''
              );
              if (ingredients === null) return; // cancelled
              const priceRange = window.prompt(
                '⚡ One-Click AI Product Generator (Gemini)\n\n' +
                'STEP 3 — Desired PRICE RANGE (MRP in ₹), e.g. "699-999".\n' +
                '(Leave blank to let AI decide.)',
                ''
              );
              if (priceRange === null) return; // cancelled
              let price_min = null, price_max = null;
              if (priceRange && priceRange.trim()) {
                const nums = priceRange.replace(/[^0-9-]/g, '').split('-').map(n => parseInt(n, 10)).filter(n => !isNaN(n));
                if (nums.length >= 1) price_min = nums[0];
                if (nums.length >= 2) price_max = nums[1];
              }
              const specs = window.prompt(
                '⚡ One-Click AI Product Generator (Gemini)\n\n' +
                'STEP 4 — Extra SPECIFICATIONS (optional). One line, free-form:\n' +
                'e.g. "for men 25-35, oily skin, lightweight gel, fragrance-free, 30ml"\n\n' +
                'The AI copy, size & price will honour these. (Leave blank to skip.)',
                ''
              );
              if (specs === null) return; // cancelled
              setAiGenerating(true);
              setAiStep('starting');
              setOcInfo({ name: name.trim(), startedAt: Date.now() });
              try {
                const { data } = await axios.post(`${API}/admin/ai/one-click-product`, {
                  name: name.trim(), brand: 'Celesta Glow',
                  key_ingredients: (ingredients || '').trim(), generate_image: true,
                  price_min, price_max,
                  extra_specs: (specs || '').trim() || null,
                }, { headers });
                if (!data?.job_id) { alert('Failed to start generation'); return; }
                // Poll the background job — AI image generation takes ~1-2 min,
                // beyond the edge timeout of a single synchronous request.
                const jobId = data.job_id;
                const deadline = Date.now() + 5 * 60 * 1000;
                let job = null;
                while (Date.now() < deadline) {
                  await new Promise(r => setTimeout(r, 1500));
                  const { data: j } = await axios.get(`${API}/admin/ai/one-click-product-job/${jobId}`, { headers });
                  job = j;
                  setAiStep(j.step || 'working');
                  if (j.status !== 'running') break;
                }
                if (!job || job.status === 'running') {
                  alert('Still generating in the background — refresh this page in a minute to see the new product.');
                } else if (job.status === 'failed') {
                  alert(`❌ Generation failed: ${job.error || 'unknown error'}`);
                } else {
                  const res = job.result || {};
                  const p = res.product || {};
                  alert(
                    `✅ Product created: ${p.name}\n\n` +
                    `Niche: ${p.niche}\nCategory: ${p.category || '—'}${p.subcategory ? ' / ' + p.subcategory : ''}\n` +
                    `Concerns: ${(p.concerns || []).join(', ') || '—'}\n` +
                    `Price: ₹${p.offer_price} (MRP ₹${p.mrp})\n` +
                    `Image: ${res.image_generated ? 'AI-generated ✓' : (p.images?.length ? 'attached' : 'none')}`
                  );
                  try { window.dispatchEvent(new Event('admin-data-changed')); } catch {}
                  fetchAll();
                }
              } catch (e) {
                alert(e.response?.data?.detail || 'One-click generation failed');
              } finally {
                setAiGenerating(false);
                setAiStep('');
                setOcInfo(null);
              }
            }}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-700 hover:to-teal-700 disabled:opacity-60 text-white text-sm font-bold shadow-md hover:shadow-lg"
            data-testid="one-click-ai-generate-btn"
            title="Type a product name — AI generates a full product (copy + image + niche/concern routing) in one click."
          >
            <Sparkles size={16} /> {ocInfo ? 'Generating…' : 'One-Click AI Product'}
          </button>
          <button
            type="button"
            disabled={bulkGen.running}
            onClick={async () => {
              const raw = window.prompt(
                '⚡ Bulk AI Product Generator (Gemini)\n\n' +
                'Paste ONE PRODUCT PER LINE in this format:\n' +
                '   Product Name | ingredients | price\n\n' +
                'Examples:\n' +
                '   Vitamin C Brightening Serum | Vitamin C, Ferulic Acid | 699\n' +
                '   Niacinamide 10% Serum | Niacinamide, Zinc | 499-599\n' +
                '   Hyaluronic Moisturizer | Hyaluronic Acid | \n\n' +
                '(ingredients & price are optional — leave blank for AI to decide)',
                ''
              );
              if (!raw || !raw.trim()) return;
              const items = raw.split('\n').map(line => {
                const parts = line.split('|').map(s => s.trim());
                const name = parts[0];
                if (!name) return null;
                const ing = parts[1] || '';
                let price_min = null, price_max = null;
                if (parts[2]) {
                  const nums = parts[2].replace(/[^0-9-]/g, '').split('-').map(n => parseInt(n, 10)).filter(n => !isNaN(n));
                  if (nums.length >= 1) price_min = nums[0];
                  if (nums.length >= 2) price_max = nums[1];
                }
                return { name, key_ingredients: ing, price_min, price_max };
              }).filter(Boolean);
              if (!items.length) { alert('No valid rows found'); return; }
              if (!window.confirm(`Generate ${items.length} product(s) with AI? This runs in the background, one at a time.`)) return;
              setBulkGen({ running: true, done: 0, failed: 0, total: items.length, current: items[0].name, step: 'queued', startedAt: Date.now() });
              try {
                const { data } = await axios.post(`${API}/admin/ai/bulk-generate`, { items, brand: 'Celesta Glow', generate_image: true }, { headers });
                if (!data?.job_id) { alert('Failed to start bulk generation'); setBulkGen({ running: false }); return; }
                const jobId = data.job_id;
                const deadline = Date.now() + 30 * 60 * 1000;
                let job = null;
                while (Date.now() < deadline) {
                  await new Promise(r => setTimeout(r, 1500));
                  const { data: j } = await axios.get(`${API}/admin/ai/bulk-generate-job/${jobId}`, { headers });
                  job = j;
                  setBulkGen(prev => ({ ...prev, running: j.status === 'running', done: j.done ?? 0, failed: j.failed ?? 0, total: j.total ?? prev.total, current: j.current, step: j.item?.step || 'queued' }));
                  if (j.status !== 'running') break;
                  try { window.dispatchEvent(new Event('admin-data-changed')); } catch {}
                  fetchAll();
                }
                const created = (job?.created || []).length;
                const failed = (job?.failed || 0);
                alert(`✅ Bulk generation complete.\n\nCreated: ${created}\nFailed: ${failed}` + (job?.errors?.length ? `\n\nErrors:\n${job.errors.map(e => `• ${e.name}: ${e.error}`).join('\n')}` : ''));
                try { window.dispatchEvent(new Event('admin-data-changed')); } catch {}
                fetchAll();
              } catch (e) {
                alert(e.response?.data?.detail || 'Bulk generation failed');
              } finally {
                setBulkGen({ running: false });
              }
            }}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-700 hover:to-purple-700 disabled:opacity-60 text-white text-sm font-bold shadow-md hover:shadow-lg"
            data-testid="bulk-ai-generate-btn"
            title="Paste many product names (one per line) — AI generates each full product in the background, one at a time."
          >
            <Sparkles size={16} /> {bulkGen.running ? 'Bulk running…' : 'Bulk AI Generate'}
          </button>
          {ocInfo && <GenerationProgress mode="single" name={ocInfo.name} step={aiStep} startedAt={ocInfo.startedAt} />}
          {bulkGen.running && (
            <GenerationProgress mode="bulk" name={bulkGen.current} step={bulkGen.step} done={bulkGen.done} failed={bulkGen.failed} total={bulkGen.total} startedAt={bulkGen.startedAt} />
          )}

          <button
            type="button"
            onClick={async () => {
              const scopeChoice = window.prompt(
                'AI Taxonomy Audit — runs Gemini across the catalog to:\n' +
                '  • Route every product into the right niche / category / subcategory\n' +
                '  • Auto-create new sub-categories, concerns and filters as needed\n' +
                '  • Connect everything to the matching storefront tabs\n\n' +
                'Type a scope and click OK:\n' +
                '  needs   = products with missing taxonomy (recommended after bulk upload)\n' +
                '  all     = re-audit EVERY product (use sparingly, uses more LLM credits)\n' +
                '  niche:cosmetics  = only that niche\n' +
                '  niche:skincare   = only that niche',
                'needs'
              );
              if (!scopeChoice) return;
              let payload = { scope: 'needs_taxonomy', only_missing: true, concurrency: 6 };
              if (scopeChoice.trim() === 'all') payload = { scope: 'all', only_missing: false, concurrency: 6 };
              else if (scopeChoice.startsWith('niche:')) payload = { scope: 'niche', niche: scopeChoice.split(':')[1].trim(), only_missing: false, concurrency: 6 };
              try {
                const { data } = await axios.post(`${API}/admin/taxonomy/ai-audit`, payload, { headers });
                if (!data.job_id) { alert('Failed to start audit'); return; }
                const jobId = data.job_id;
                alert(`Audit started. Job: ${jobId}\nThis page will keep polling for progress in the console — feel free to keep browsing.`);
                // Poll for up to 10 minutes; show one-shot alert on completion
                const poll = setInterval(async () => {
                  try {
                    const { data: j } = await axios.get(`${API}/admin/taxonomy/ai-audit/${jobId}`, { headers });
                    console.log(`[ai-audit ${jobId}] ${j.status} ${j.done}/${j.total} done · ${j.failed} failed · cats+${j.created_categories?.length||0} subs+${j.created_subcategories?.length||0} concerns+${j.created_concerns?.length||0}`);
                    if (j.status === 'completed' || j.status === 'failed') {
                      clearInterval(poll);
                      alert(
                        `Audit ${j.status}!\n` +
                        `Updated: ${j.done}/${j.total}  ·  Failed: ${j.failed}\n` +
                        `New categories: ${j.created_categories?.length || 0}\n` +
                        `New subcategories: ${j.created_subcategories?.length || 0}\n` +
                        `New concerns: ${j.created_concerns?.length || 0}`
                      );
                      fetchAll();
                    }
                  } catch (e) { /* keep polling */ }
                }, 4000);
              } catch (e) {
                alert(e.response?.data?.detail || e.message);
              }
            }}
            className="flex items-center gap-1.5 px-3 py-2 rounded-xl bg-gradient-to-r from-violet-600 to-fuchsia-600 hover:from-violet-700 hover:to-fuchsia-700 text-white text-sm font-bold shadow-md hover:shadow-lg"
            data-testid="ai-taxonomy-audit-btn"
            title="One-click AI audit — re-routes every product into the right category/subcategory/concerns and creates missing taxonomy."
          >
            <Sparkles size={16} /> AI Audit Catalog
          </button>
          <button
            type="button"
            onClick={async () => {
              const keep = window.prompt(
                'DANGER — this DELETES products from the catalog.\n\n' +
                'Type a comma-separated list of niches to KEEP (e.g. "anti-aging") and click OK,\n' +
                'or leave empty to wipe EVERY product.\n\n' +
                'Cancel to abort.',
                'anti-aging'
              );
              if (keep === null) return; // cancelled
              if (!window.confirm(`This will hard-delete all products${keep.trim() ? ` EXCEPT niches: ${keep}` : ' from every niche'}.\n\nProceed?`)) return;
              try {
                const url = `${API}/admin/products/wipe-all?confirm=DELETE_ALL${keep.trim() ? `&keep_niches=${encodeURIComponent(keep.trim())}` : ''}`;
                const res = await axios.post(url, {}, { headers });
                alert(`Done. Deleted ${res.data.deleted} products. Remaining: ${res.data.remaining_total}.`);
                fetchAll();
              } catch (e) {
                alert(e.response?.data?.detail || e.message);
              }
            }}
            className="hidden sm:flex items-center gap-1.5 px-3 py-2 rounded-xl bg-rose-50 hover:bg-rose-100 text-rose-700 text-sm font-semibold"
            data-testid="wipe-all-products-btn"
            title="Hard-delete products (with optional niche preserve) — for re-testing bulk upload"
          >
            <Trash size={16} /> Wipe All
          </button>
          <button
            type="button"
            onClick={() => navigate('/admin')}
            className="hidden sm:flex items-center gap-1.5 px-3 py-2 rounded-xl bg-gray-50 hover:bg-gray-100 text-gray-700 text-sm font-medium"
            title="Open dashboard"
          >
            <LayoutDashboard size={16} /> Dashboard
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 bg-gray-100 p-1 rounded-xl">
        {tabs.map(tab => (
          <button key={tab.key} onClick={() => setActiveTab(tab.key)} className={`flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors ${activeTab === tab.key ? 'bg-white text-gray-900 shadow-sm' : 'text-gray-500 hover:text-gray-700'}`} data-testid={`tab-${tab.key}`}>
            <tab.icon size={16} /> {tab.label}
          </button>
        ))}
      </div>

      {/* Products Tab */}
      {activeTab === 'products' && (
        <div className="space-y-4">
          {/* New product editor (only when __isNew) */}
          {editProduct?.__isNew && (
            <div className="bg-white rounded-2xl border-2 border-green-300 p-4" data-testid="new-product-editor">
              <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                <h3 className="font-black text-gray-900 flex items-center gap-2"><Plus size={16} className="text-green-600" /> Create New Product</h3>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    disabled={!editProduct.name || aiGenerating}
                    onClick={async () => {
                      if (!editProduct.name) { alert('Enter the product name first, then click AI Analyze'); return; }
                      setAiGenerating(true);
                      try {
                        const res = await axios.post(`${API}/admin/ai/analyze-product`, {
                          name: editProduct.name,
                          brand: editProduct.brand || '',
                          main_category: editProduct.niche || '',
                          product_type: editProduct.subcategory || editProduct.category || '',
                          concern: (editProduct.concerns || [])[0] || '',
                          auto_create: true,
                        }, { headers });
                        if (res.data?.success) {
                          const c = res.data.classification || {};
                          setEditProduct({
                            ...editProduct,
                            niche: c.niche || editProduct.niche,
                            category: c.category_slug || editProduct.category,
                            subcategory: c.subcategory_slug || editProduct.subcategory,
                            concerns: [
                              ...(editProduct.concerns || []),
                              ...(c.concerns || []).map(x => x.slug),
                            ].filter((v, i, a) => v && a.indexOf(v) === i),
                          });
                          try {
                            const [cnR, ctR, scR] = await Promise.allSettled([
                              axios.get(`${API}/concerns`),
                              axios.get(`${API}/categories`),
                              axios.get(`${API}/subcategories`),
                            ]);
                            if (cnR.status === 'fulfilled') setConcerns(cnR.value.data || []);
                            if (ctR.status === 'fulfilled') setCategories(ctR.value.data || []);
                            if (scR.status === 'fulfilled') setSubcategories(scR.value.data || []);
                          } catch { /* non-fatal */ }
                          const created = res.data.auto_created || {};
                          const total = (created.categories?.length || 0) + (created.subcategories?.length || 0) + (created.concerns?.length || 0);
                          alert(`AI Analyze: routed to ${c.niche} → ${c.category_slug}${c.subcategory_slug ? ' / ' + c.subcategory_slug : ''}\n${total > 0 ? `Auto-created ${total} taxonomy row(s).` : 'All taxonomy already existed.'}`);
                        }
                      } catch (e) {
                        alert(e.response?.data?.detail || 'AI Analyze failed');
                      } finally {
                        setAiGenerating(false);
                      }
                    }}
                    className="px-3 py-1.5 bg-violet-600 hover:bg-violet-700 disabled:bg-gray-300 text-white rounded-lg text-xs font-bold flex items-center gap-1.5"
                    data-testid="ai-analyze-new-product"
                    title="AI classifies niche / category / subcategory / concerns from the product name and auto-creates missing taxonomy."
                  >
                    <Sparkles size={12} /> {aiGenerating ? 'Analyzing…' : 'AI Analyze'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setAnalyzerOpen(true)}
                    className="px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-bold flex items-center gap-1.5"
                    data-testid="open-url-analyzer"
                    title="Paste a product URL — we'll auto-fill name, price, image, ingredients & description"
                  >
                    ⚡ Analyze URL (optional)
                  </button>
                </div>
              </div>
              <p className="text-[11px] text-gray-500 mb-3">Fill fields top-to-bottom. Fields marked <span className="text-red-500">*</span> are required.</p>
              <div className="space-y-3">
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {/* 1. Brand */}
                  <div>
                    <label className="text-xs font-semibold text-gray-500">1. Brand <span className="text-red-500">*</span></label>
                    <input value={editProduct.brand || ''} onChange={e => setEditProduct({...editProduct, brand: e.target.value})} placeholder={(settings?.niche_settings?.[editProduct.niche || 'anti-aging']?.brand_name) || 'Celesta Glow'} className="w-full px-3 py-2 border rounded-lg text-sm" data-testid="new-brand" />
                  </div>
                  {/* 2. Product Name */}
                  <div>
                    <label className="text-xs font-semibold text-gray-500">2. Product Name <span className="text-red-500">*</span></label>
                    <div className="flex gap-1.5">
                      <input value={editProduct.name} onChange={e => setEditProduct({...editProduct, name: e.target.value, short_name: editProduct.short_name || e.target.value})} className="flex-1 px-3 py-2 border rounded-lg text-sm" data-testid="new-name" placeholder="e.g. Vitamin C Brightening Serum" />
                      <button
                        type="button"
                        disabled={!editProduct.name || aiGenerating}
                        onClick={async () => {
                          if (!editProduct.name) return;
                          setAiGenerating(true);
                          try {
                            const res = await axios.post(`${API}/admin/ai/generate-product-content`, {
                              name: editProduct.name,
                              niche: editProduct.niche || 'skincare',
                              category: editProduct.category || '',
                              concerns: editProduct.concerns || [],
                              brand: editProduct.brand || '',
                              key_ingredients: editProduct.key_ingredients || '',
                            }, { headers });
                            if (res.data?.success) {
                              setEditProduct({
                                ...editProduct,
                                tagline: res.data.tagline || editProduct.tagline,
                                description: res.data.description || editProduct.description,
                                key_ingredients: res.data.key_ingredients || editProduct.key_ingredients,
                                ingredients_full: res.data.ingredients_full || editProduct.ingredients_full,
                                benefits: res.data.benefits?.length ? res.data.benefits : (editProduct.benefits || []),
                                how_to_use: res.data.how_to_use || editProduct.how_to_use,
                                size: res.data.size || editProduct.size,
                                faqs: res.data.faqs?.length ? res.data.faqs : (editProduct.faqs || []),
                                // Only fill prices if the admin hasn't entered them yet, so AI never
                                // overwrites real numbers an admin has already typed.
                                mrp: editProduct.mrp || res.data.mrp || editProduct.mrp,
                                prepaid_price: editProduct.prepaid_price || res.data.offer_price || editProduct.prepaid_price,
                                cod_price: editProduct.cod_price || res.data.offer_price || editProduct.cod_price,
                                brand: editProduct.brand || res.data.brand_suggestion || editProduct.brand,
                              });
                            }
                          } catch (e) {
                            alert(e.response?.data?.detail || 'AI generation failed');
                          } finally {
                            setAiGenerating(false);
                          }
                        }}
                        className="px-2.5 py-2 bg-fuchsia-600 hover:bg-fuchsia-700 disabled:bg-gray-300 disabled:cursor-not-allowed text-white rounded-lg text-xs font-bold flex items-center gap-1 whitespace-nowrap"
                        data-testid="ai-fill-from-name"
                        title="Type a product name and let AI fill tagline / description / benefits / ingredients / FAQs"
                      >
                        <Sparkles size={12} /> {aiGenerating ? 'AI…' : 'AI Fill'}
                      </button>
                    </div>
                  </div>
                  {/* 3. Niche */}
                  <div>
                    <label className="text-xs font-semibold text-gray-500">3. Niche <span className="text-red-500">*</span></label>
                    <select value={editProduct.niche || 'skin-care'} onChange={e => {
                      const newNiche = e.target.value;
                      const brandFromNiche = (settings?.niche_settings?.[newNiche]?.brand_name) || '';
                      setEditProduct({...editProduct, niche: newNiche, brand: editProduct.brand || brandFromNiche, category: ''});
                    }} className="w-full px-3 py-2 border rounded-lg text-sm bg-white" data-testid="new-niche">
                      <option value="skin-care">✨ Skin Care</option>
                    </select>
                  </div>
                  {/* 4. Category */}
                  <div>
                    <label className="text-xs font-semibold text-gray-500">4. Category <span className="text-gray-400 font-normal">(optional)</span></label>
                    <select value={editProduct.category || ''} onChange={e => setEditProduct({...editProduct, category: e.target.value, subcategory: ''})} className="w-full px-3 py-2 border rounded-lg text-sm bg-white" data-testid="new-category">
                      <option value="">— No category —</option>
                      {categories.filter(c => { const n = editProduct.niche || 'skin-care'; if (!c.niche) return true; if (c.niche === n) return true; if (n === 'skin-care' && c.niche === 'skincare') return true; return false; }).map(c => <option key={c.slug} value={c.slug}>{c.icon} {c.name}</option>)}
                    </select>
                    {categories.filter(c => { const n = editProduct.niche || 'skin-care'; if (!c.niche) return true; if (c.niche === n) return true; if (n === 'skin-care' && c.niche === 'skincare') return true; return false; }).length === 0 && (
                      <p className="text-[11px] text-amber-700 mt-1">No category for this niche yet. <Link to="/admin/categories" className="underline font-bold">Create one</Link>.</p>
                    )}
                  </div>
                  {/* 4b. Subcategory — cascades from chosen Category. Hidden until a category is picked. */}
                  {editProduct.category && (() => {
                    const subs = subcategories.filter(s => s.parent_category === editProduct.category && s.is_active !== false);
                    const parentName = (categories.find(c => c.slug === editProduct.category)?.name) || editProduct.category;
                    return (
                      <div>
                        <label className="text-xs font-semibold text-gray-500">
                          4b. Subcategory <span className="text-gray-400 font-normal">(optional · only those under "{parentName}")</span>
                        </label>
                        {subs.length > 0 ? (
                          <select
                            value={editProduct.subcategory || ''}
                            onChange={e => setEditProduct({ ...editProduct, subcategory: e.target.value })}
                            className="w-full px-3 py-2 border rounded-lg text-sm bg-white"
                            data-testid="new-subcategory"
                          >
                            <option value="">— None —</option>
                            {subs.map(s => (
                              <option key={s.slug} value={s.slug}>{s.icon} {s.name}</option>
                            ))}
                          </select>
                        ) : (
                          <p className="text-[11px] text-amber-700 mt-1 bg-amber-50 ring-1 ring-amber-200 rounded-lg px-2.5 py-1.5" data-testid="new-subcategory-empty">
                            No subcategories under "{parentName}" yet. <Link to="/admin/categories" className="underline font-bold">Add some</Link> (e.g. Matte / Glossy under Lipstick) — products created without a subcategory simply skip this filter.
                          </p>
                        )}
                      </div>
                    );
                  })()}
                  {/* 5. MRP */}
                  <div>
                    <label className="text-xs font-semibold text-gray-500">5. MRP (₹) <span className="text-red-500">*</span></label>
                    <input type="number" value={editProduct.mrp || 0} onChange={e => { const mrp = Number(e.target.value); setEditProduct({...editProduct, mrp, discount_percent: mrp && editProduct.prepaid_price ? Math.round((mrp - editProduct.prepaid_price) * 100 / mrp) : editProduct.discount_percent}); }} className="w-full px-3 py-2 border rounded-lg text-sm" data-testid="new-mrp" />
                  </div>
                  {/* 6. Offer / Sale price → saved as prepaid_price */}
                  <div>
                    <label className="text-xs font-semibold text-gray-500">6. Offer Price (₹) <span className="text-red-500">*</span> <span className="text-gray-400 font-normal">(sale price)</span></label>
                    <input type="number" value={editProduct.prepaid_price || 0} onChange={e => { const pp = Number(e.target.value); setEditProduct({...editProduct, prepaid_price: pp, cod_price: pp, discount_percent: editProduct.mrp ? Math.round((editProduct.mrp - pp) * 100 / editProduct.mrp) : 0}); }} className="w-full px-3 py-2 border rounded-lg text-sm" data-testid="new-offer-price" placeholder="What customer pays" />
                  </div>
                  {/* 7. Stock */}
                  <div className="sm:col-span-2">
                    <label className="text-xs font-semibold text-gray-500">7. Stock Quantity <span className="text-red-500">*</span></label>
                    <input type="number" value={editProduct.stock_qty ?? 100} onChange={e => setEditProduct({...editProduct, stock_qty: Number(e.target.value)})} className="w-full px-3 py-2 border rounded-lg text-sm" data-testid="new-stock" />
                  </div>
                  {/* 8. Tagline */}
                  <div className="sm:col-span-2"><label className="text-xs font-semibold text-gray-500">8. Tagline</label><input value={editProduct.tagline || ''} onChange={e => setEditProduct({...editProduct, tagline: e.target.value})} className="w-full px-3 py-2 border rounded-lg text-sm" placeholder="One-line benefit shown under the product name" /></div>
                  {/* 9. Description */}
                  <div className="sm:col-span-2"><label className="text-xs font-semibold text-gray-500">9. Description</label><textarea value={editProduct.description || ''} onChange={e => setEditProduct({...editProduct, description: e.target.value})} className="w-full px-3 py-2 border rounded-lg text-sm" rows={3} placeholder="2-3 sentences about the product" /></div>
                  {/* 10. Key Ingredients — auto chip on comma / Enter */}
                  <div className="sm:col-span-2">
                    <label className="text-xs font-semibold text-gray-500">10. Key Ingredients <span className="text-gray-400 font-normal">(type then press Enter or comma — each one becomes a chip)</span></label>
                    <IngredientsChipInput
                      value={editProduct.key_ingredients || ''}
                      onChange={(v) => setEditProduct({...editProduct, key_ingredients: v})}
                    />
                  </div>
                  {/* 11. Packaging size */}
                  <div className="sm:col-span-2"><label className="text-xs font-semibold text-gray-500">11. Packaging Size</label><input value={editProduct.size || ''} onChange={e => setEditProduct({...editProduct, size: e.target.value})} placeholder="e.g. 30ml / 50g / 15ml pack" className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                </div>
                {/* 12. Product Images */}
                <div>
                  <p className="text-xs font-semibold text-gray-500 mb-1">12. Product Images</p>
                  <ImageManager images={editProduct.images || []} onChange={(imgs) => setEditProduct({...editProduct, images: imgs})} label="" headers={headers} slug={editProduct.slug} onGenerated={(d) => setEditProduct(prev => ({...prev, images: d.images || prev.images, test_report_image: d.test_report_image || prev.test_report_image, test_report_lab: d.test_report_lab || prev.test_report_lab, tech_stories: d.tech_stories || prev.tech_stories}))} />
                </div>
                {/* 12b. Shades — cosmetics only */}
                {(editProduct.niche === 'cosmetics') && (
                  <div>
                    <p className="text-xs font-semibold text-gray-500 mb-1">12b. Shade Variants</p>
                    <ShadeEditor
                      shades={editProduct.shades || []}
                      onChange={(shades) => setEditProduct({ ...editProduct, shades })}
                    />
                  </div>
                )}
                {/* 13. Badges */}
                <div>
                  <p className="text-xs font-semibold text-gray-500 mb-1">13. Badges <span className="text-gray-400 font-normal">(shown on card — pick any)</span></p>
                  <BadgeChips value={editProduct.badges || (editProduct.badge ? [editProduct.badge] : [])} onChange={(arr) => setEditProduct({...editProduct, badges: arr, badge: arr[0] || ''})} />
                </div>
                {/* Hidden advanced — slug auto-derived */}
                <input type="hidden" value={editProduct.slug} data-testid="new-slug" />

                {/* Concerns multi-select — REQUIRED so product appears on /concern pages */}
                <div className="rounded-xl border border-pink-100 bg-pink-50/40 p-3">
                  <div className="flex items-center gap-2 mb-2">
                    <Tag size={14} className="text-pink-700" />
                    <span className="text-xs font-bold text-pink-900 tracking-wide">SKIN CONCERNS (multi-select)</span>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {concerns.filter(c => { const n = editProduct.niche || 'skin-care'; if (!c.niche) return true; if (c.niche === n) return true; if (n === 'skin-care' && c.niche === 'skincare') return true; return false; }).map(cn => {
                      const selected = (editProduct.concerns || []).includes(cn.slug);
                      return (
                        <button
                          key={cn.slug}
                          type="button"
                          onClick={() => {
                            const cur = editProduct.concerns || [];
                            const next = selected ? cur.filter(s => s !== cn.slug) : [...cur, cn.slug];
                            setEditProduct({ ...editProduct, concerns: next });
                          }}
                          className={`text-xs font-bold px-2.5 py-1.5 rounded-full border transition-all ${selected ? 'bg-green-600 text-white border-green-600' : 'bg-white text-gray-700 border-gray-200 hover:border-green-400'}`}
                          data-testid={`new-product-concern-${cn.slug}`}
                        >
                          {cn.icon} {cn.name}
                        </button>
                      );
                    })}
                  </div>
                  {(!editProduct.concerns || editProduct.concerns.length === 0) && (
                    <p className="text-[11px] text-amber-700 mt-1.5">⚠️ No concerns selected — this product won't appear on any /concern page.</p>
                  )}
                </div>

                <div className="flex gap-2">
                  <button onClick={() => updateProduct(editProduct.slug, editProduct)} className="flex items-center gap-1 px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-semibold" data-testid="save-new-product"><Save size={14} /> Create Product</button>
                  <button onClick={() => setEditProduct(null)} className="flex items-center gap-1 px-4 py-2 bg-gray-200 text-gray-700 rounded-lg text-sm"><X size={14} /> Cancel</button>
                </div>
              </div>
            </div>
          )}

          {/* Bulk-action bar — appears only when ≥1 product is selected via checkbox.
              Sticky so it stays visible as the admin scrolls through hundreds of products. */}
          {selectedSlugs.size > 0 && (
            <div className="sticky top-16 z-30 bg-red-600 text-white rounded-2xl px-4 py-3 flex flex-wrap items-center gap-3 shadow-lg" data-testid="bulk-action-bar">
              <span className="font-black text-sm" data-testid="bulk-selected-count">
                {selectedSlugs.size} selected
              </span>
              <BulkDiscountInput onApply={bulkApplyDiscount} disabled={bulkBusy} />
              <button
                onClick={bulkDeactivateSelected}
                disabled={bulkBusy}
                className="text-xs font-bold px-3 py-1.5 rounded-lg bg-white/15 hover:bg-white/25 disabled:opacity-60"
                data-testid="bulk-deactivate"
              >
                Deactivate
              </button>
              <button
                onClick={bulkDeleteSelected}
                disabled={bulkBusy}
                className="text-xs font-black px-3 py-1.5 rounded-lg bg-white text-red-700 hover:bg-red-50 disabled:opacity-60"
                data-testid="bulk-delete"
              >
                {bulkBusy ? 'Working…' : 'Delete selected'}
              </button>
              <button
                onClick={clearSelection}
                className="ml-auto text-xs font-bold px-3 py-1.5 rounded-lg bg-white/15 hover:bg-white/25"
                data-testid="bulk-clear"
              >
                Clear selection
              </button>
            </div>
          )}

          {/* Filters bar */}
          <div className="bg-white rounded-2xl border border-gray-200 p-3 flex flex-wrap items-center gap-2" data-testid="products-filter-bar">
            <label className="flex items-center gap-2 text-xs font-semibold text-gray-600 px-2 cursor-pointer select-none" title="Select all currently filtered products">
              <input
                type="checkbox"
                checked={filteredProducts.length > 0 && filteredProducts.every(p => selectedSlugs.has(p.slug))}
                onChange={(e) => selectAllVisible(filteredProducts.map(p => p.slug), e.target.checked)}
                className="w-4 h-4 accent-red-600 cursor-pointer"
                data-testid="select-all-checkbox"
              />
              Select all
            </label>
            <input
              type="search"
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              placeholder="Search by name or slug…"
              className="px-3 py-2 border rounded-lg text-sm flex-1 min-w-[180px]"
              data-testid="products-search"
            />
            <div className="flex gap-1">
              {[{k:'all',l:'All'},{k:'skin-care',l:'✨ Skin Care'}].map(o => (
                <button key={o.k} onClick={() => setFilterNiche(o.k)} className={`px-3 py-1.5 rounded-full text-xs font-bold ${filterNiche === o.k ? 'bg-green-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`} data-testid={`filter-niche-${o.k}`}>{o.l}</button>
              ))}
            </div>
            <div className="flex gap-1">
              {[{k:'all',l:'All status'},{k:'active',l:'Active'},{k:'inactive',l:'Inactive'},{k:'tbl',l:'TBL'},{k:'live',l:'Live'},{k:'low_stock',l:'Low stock'}].map(o => (
                <button key={o.k} onClick={() => setFilterStatus(o.k)} className={`px-3 py-1.5 rounded-full text-xs font-bold ${filterStatus === o.k ? 'bg-purple-600 text-white' : 'bg-gray-100 text-gray-700 hover:bg-gray-200'}`} data-testid={`filter-status-${o.k}`}>{o.l}</button>
              ))}
            </div>
            <button
              onClick={() => setImagesFirst(v => !v)}
              className={`ml-auto mr-2 px-3 py-2 rounded-lg text-xs font-bold flex items-center gap-1.5 border transition ${imagesFirst ? 'bg-emerald-100 text-emerald-800 border-emerald-300' : 'bg-white text-gray-600 border-gray-300 hover:bg-gray-50'}`}
              title="Sort SKUs with images first, missing-image rows at the bottom"
              data-testid="images-first-toggle"
            >
              {imagesFirst ? '✓ ' : ''}Images first
            </button>
            <button
              onClick={() => {
                const fresh = {
                  slug: '', name: 'New Product', short_name: '', tagline: '', description: '',
                  niche: filterNiche === 'all' ? 'skin-care' : filterNiche,
                  category: '', concerns: [],
                  mrp: 0, prepaid_price: 0, cod_price: 0, cod_advance: 29, discount_percent: 0,
                  badge: '', images: [], is_active: true, sort_order: 99,
                  stock_qty: 100, low_stock_threshold: 10,
                  is_to_be_launched: false, launch_date: null, preorder_enabled: false,
                  __isNew: true,
                };
                setEditProduct(fresh);
              }}
              className="ml-auto px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-xs font-bold flex items-center gap-1.5"
              data-testid="add-product-btn"
            >
              <Plus size={14} /> Add Product
            </button>
          </div>
          {(() => {
            const filtered = products
              .filter(p => filterNiche === 'all' || p.niche === filterNiche)
              .filter(p => {
                if (filterStatus === 'all') return true;
                if (filterStatus === 'active') return p.is_active;
                if (filterStatus === 'inactive') return !p.is_active;
                if (filterStatus === 'tbl') return p.is_to_be_launched;
                if (filterStatus === 'live') return !p.is_to_be_launched;
                if (filterStatus === 'low_stock') return (p.stock_qty ?? 100) <= (p.low_stock_threshold ?? 10);
                return true;
              })
              .filter(p => {
                if (!searchTerm.trim()) return true;
                const q = searchTerm.toLowerCase();
                return (p.name || '').toLowerCase().includes(q) || (p.slug || '').toLowerCase().includes(q);
              });
            if (filtered.length === 0) {
              return <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 text-center text-sm text-amber-800">No products match the current filters.</div>;
            }
            const renderRow = (product) => (
            <div
              key={product.slug}
              draggable
              onDragStart={(e) => { setDraggingSlug(product.slug); e.dataTransfer.effectAllowed = 'move'; }}
              onDragOver={(e) => { e.preventDefault(); if (draggingSlug && draggingSlug !== product.slug) setDragOverSlug(product.slug); }}
              onDragLeave={() => setDragOverSlug(null)}
              onDrop={(e) => { e.preventDefault(); handleDrop(product.slug); }}
              onDragEnd={() => { setDraggingSlug(null); setDragOverSlug(null); }}
              className={`bg-white rounded-2xl border ${product.is_active ? 'border-gray-200' : 'border-red-200 bg-red-50/50'} ${draggingSlug === product.slug ? 'opacity-40 scale-[0.98]' : ''} ${dragOverSlug === product.slug ? 'ring-2 ring-emerald-400' : ''} p-4 transition-all cursor-move`}
              data-testid={`admin-product-${product.slug}`}
            >
              {editProduct?.slug === product.slug ? (
                /* Edit Mode */
                <div className="space-y-3">
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {editProduct.__isNew && (
                      <div className="sm:col-span-2"><label className="text-xs font-semibold text-gray-500">Slug (URL-safe — auto from name if empty)</label><input value={editProduct.slug} onChange={e => setEditProduct({...editProduct, slug: e.target.value.toLowerCase().replace(/[^a-z0-9]+/g, '-')})} className="w-full px-3 py-2 border rounded-lg text-sm font-mono" placeholder="anti-aging-cream" data-testid="new-product-slug" /></div>
                    )}
                    <div><label className="text-xs font-semibold text-gray-500">Product Name</label><input value={editProduct.name} onChange={e => setEditProduct({...editProduct, name: e.target.value})} className="w-full px-3 py-2 border rounded-lg text-sm" data-testid="edit-product-name" /></div>
                    <div><label className="text-xs font-semibold text-gray-500">Short Name</label><input value={editProduct.short_name} onChange={e => setEditProduct({...editProduct, short_name: e.target.value})} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                    <div><label className="text-xs font-semibold text-gray-500">MRP (₹)</label><input type="number" value={editProduct.mrp} onChange={e => { const mrp = Number(e.target.value); setEditProduct({...editProduct, mrp, discount_percent: mrp && editProduct.prepaid_price ? Math.max(0, Math.round((mrp - editProduct.prepaid_price) * 100 / mrp)) : editProduct.discount_percent}); }} className="w-full px-3 py-2 border rounded-lg text-sm" data-testid="edit-mrp" /></div>
                    <div><label className="text-xs font-semibold text-gray-500">Prepaid Price (₹)</label><input type="number" value={editProduct.prepaid_price} onChange={e => { const pp = Number(e.target.value); setEditProduct({...editProduct, prepaid_price: pp, cod_price: editProduct.cod_price === editProduct.prepaid_price ? pp : editProduct.cod_price, discount_percent: editProduct.mrp ? Math.max(0, Math.round((editProduct.mrp - pp) * 100 / editProduct.mrp)) : 0}); }} className="w-full px-3 py-2 border rounded-lg text-sm" data-testid="edit-prepaid-price" /></div>
                    <div><label className="text-xs font-semibold text-gray-500">COD Price (₹)</label><input type="number" value={editProduct.cod_price} onChange={e => setEditProduct({...editProduct, cod_price: Number(e.target.value)})} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                    <div><label className="text-xs font-semibold text-gray-500">COD Advance (₹)</label><input type="number" value={editProduct.cod_advance} onChange={e => setEditProduct({...editProduct, cod_advance: Number(e.target.value)})} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                    <div><label className="text-xs font-semibold text-emerald-700">Discount % <span className="text-emerald-600 text-[10px] font-bold">AUTO-CALCULATED</span></label><input type="number" value={editProduct.discount_percent} onChange={e => setEditProduct({...editProduct, discount_percent: Number(e.target.value)})} className="w-full px-3 py-2 border-2 border-emerald-200 bg-emerald-50/50 rounded-lg text-sm font-bold text-emerald-700" data-testid="edit-discount" title="Auto-calculated from MRP and Prepaid Price. You can override manually." /></div>
                    <div><label className="text-xs font-semibold text-gray-500">Offer Price (₹) <span className="text-amber-600 font-normal">(optional flash deal)</span></label><input type="number" value={editProduct.offer_price ?? ''} onChange={e => setEditProduct({...editProduct, offer_price: e.target.value === '' ? null : Number(e.target.value)})} placeholder="Lower than prepaid price" className="w-full px-3 py-2 border rounded-lg text-sm" data-testid="edit-offer-price" /></div>
                    <div><label className="text-xs font-semibold text-gray-500">Offer Label</label><input value={editProduct.offer_label || ''} onChange={e => setEditProduct({...editProduct, offer_label: e.target.value})} placeholder="e.g., Festive Sale" className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                    <div><label className="text-xs font-semibold text-gray-500">Stock Qty</label><input type="number" value={editProduct.stock_qty ?? 100} onChange={e => setEditProduct({...editProduct, stock_qty: Number(e.target.value)})} className="w-full px-3 py-2 border rounded-lg text-sm" data-testid="edit-stock-qty" /></div>
                    <div><label className="text-xs font-semibold text-gray-500">Low-stock threshold</label><input type="number" value={editProduct.low_stock_threshold ?? 10} onChange={e => setEditProduct({...editProduct, low_stock_threshold: Number(e.target.value)})} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                    <div className="col-span-2"><label className="text-xs font-semibold text-blue-700">Sort order <span className="text-blue-600 text-[10px] font-bold">(LOWER NUMBER = APPEARS FIRST)</span></label><input type="number" value={editProduct.sort_order ?? 99} onChange={e => setEditProduct({...editProduct, sort_order: Number(e.target.value)})} className="w-full px-3 py-2 border-2 border-blue-200 bg-blue-50/50 rounded-lg text-sm font-bold text-blue-700" data-testid="edit-sort-order" title="1 = first, 2 = second, etc. Tip: drag products on the list to set order automatically." /></div>
                  </div>
                  <BadgeChips value={editProduct.badges || (editProduct.badge ? [editProduct.badge] : [])} onChange={(arr) => setEditProduct({...editProduct, badges: arr, badge: arr[0] || ''})} />
                  <div><label className="text-xs font-semibold text-gray-500">Tagline</label><input value={editProduct.tagline || ''} onChange={e => setEditProduct({...editProduct, tagline: e.target.value})} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                  <div><label className="text-xs font-semibold text-gray-500">Description</label><textarea value={editProduct.description || ''} onChange={e => setEditProduct({...editProduct, description: e.target.value})} className="w-full px-3 py-2 border rounded-lg text-sm" rows={3} /></div>

                  {/* Product Content Block — content rendered on the product detail page */}
                  <div className="rounded-xl border border-emerald-100 bg-emerald-50/40 p-3 space-y-3" data-testid="edit-content-block">
                    <div className="flex items-center gap-2">
                      <Sparkles size={14} className="text-emerald-700" />
                      <span className="text-xs font-bold text-emerald-900 tracking-wide">PRODUCT CONTENT (shown on product page)</span>
                    </div>
                    <div>
                      <label className="text-xs font-semibold text-gray-500 mb-1 block">Active / Key Ingredients <span className="text-gray-400 font-normal">(press Enter or comma to chip)</span></label>
                      <IngredientsChipInput
                        value={editProduct.key_ingredients || ''}
                        onChange={(v) => setEditProduct({...editProduct, key_ingredients: v})}
                      />
                    </div>
                    <div>
                      <label className="text-xs font-semibold text-gray-500 mb-1 block">Benefits <span className="text-gray-400 font-normal">(one per line — shown as bullets)</span></label>
                      <textarea
                        value={(editProduct.benefits || []).join('\n')}
                        onChange={e => setEditProduct({...editProduct, benefits: e.target.value.split('\n').map(s => s.trim()).filter(Boolean)})}
                        className="w-full px-3 py-2 border rounded-lg text-sm font-mono"
                        rows={4}
                        placeholder={'Reduces fine lines\nBrightens & evens skin tone\nDeeply hydrates'}
                        data-testid="edit-benefits"
                      />
                    </div>
                    <div>
                      <label className="text-xs font-semibold text-gray-500 mb-1 block">Full Ingredients List (INCI)</label>
                      <textarea
                        value={editProduct.ingredients_full || ''}
                        onChange={e => setEditProduct({...editProduct, ingredients_full: e.target.value})}
                        className="w-full px-3 py-2 border rounded-lg text-sm"
                        rows={3}
                        placeholder="Aqua, Niacinamide, Glycerin, Sodium Hyaluronate…"
                        data-testid="edit-ingredients-full"
                      />
                    </div>
                    <div>
                      <label className="text-xs font-semibold text-gray-500 mb-1 block">How to Use</label>
                      <textarea
                        value={editProduct.how_to_use || ''}
                        onChange={e => setEditProduct({...editProduct, how_to_use: e.target.value})}
                        className="w-full px-3 py-2 border rounded-lg text-sm"
                        rows={3}
                        placeholder="Apply to clean, dry skin morning and evening…"
                        data-testid="edit-how-to-use"
                      />
                    </div>
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <label className="text-xs font-semibold text-gray-500 mb-1 block">Packaging Size</label>
                        <input
                          value={editProduct.size || ''}
                          onChange={e => setEditProduct({...editProduct, size: e.target.value})}
                          placeholder="e.g. 30ml / 50g"
                          className="w-full px-3 py-2 border rounded-lg text-sm"
                          data-testid="edit-size"
                        />
                      </div>
                      <div>
                        <label className="text-xs font-semibold text-gray-500 mb-1 block">Brand</label>
                        <input
                          value={editProduct.brand || ''}
                          onChange={e => setEditProduct({...editProduct, brand: e.target.value})}
                          placeholder="e.g. Celesta Glow"
                          className="w-full px-3 py-2 border rounded-lg text-sm"
                        />
                      </div>
                    </div>
                  </div>

                  <ImageManager images={editProduct.images || []} onChange={(imgs) => setEditProduct({...editProduct, images: imgs})} label="Product Images" headers={headers} slug={editProduct.slug} onGenerated={(d) => setEditProduct(prev => ({...prev, images: d.images || prev.images, test_report_image: d.test_report_image || prev.test_report_image, test_report_lab: d.test_report_lab || prev.test_report_lab, tech_stories: d.tech_stories || prev.tech_stories}))} />

                  {/* Shade Variants — surfaced only when niche === 'cosmetics' to keep the
                      skincare/anti-aging forms clean. Admins can still toggle niche to
                      reveal it for products that span both worlds (e.g., tinted SPF). */}
                  {(editProduct.niche === 'cosmetics') && (
                    <ShadeEditor
                      shades={editProduct.shades || []}
                      onChange={(shades) => setEditProduct({ ...editProduct, shades })}
                    />
                  )}

                  {/* Category + Concerns assignment */}
                  <div className="rounded-xl border border-pink-100 bg-pink-50/40 p-3 space-y-3">
                    <div className="flex items-center gap-2">
                      <Tag size={14} className="text-pink-700" />
                      <span className="text-xs font-bold text-pink-900 tracking-wide">NICHE · CATEGORY · CONCERNS</span>
                    </div>
                    <div>
                      <label className="text-xs font-semibold text-gray-500 mb-1 block">Niche (top-level 3-pill destination)</label>
                      <select
                        value={editProduct.niche || 'skin-care'}
                        onChange={e => setEditProduct({ ...editProduct, niche: e.target.value })}
                        className="w-full px-3 py-2 border rounded-lg text-sm bg-white"
                        data-testid="edit-product-niche"
                      >
                        <option value="skin-care">✨ Skin Care</option>
                      </select>
                    </div>
                    <div>
                      <label className="text-xs font-semibold text-gray-500 mb-1 block">Category <span className="text-gray-400 font-normal">(optional)</span></label>
                      <select
                        value={editProduct.category || ''}
                        onChange={e => setEditProduct({ ...editProduct, category: e.target.value, subcategory: '' })}
                        className="w-full px-3 py-2 border rounded-lg text-sm bg-white"
                        data-testid="edit-product-category"
                      >
                        <option value="">— No category —</option>
                        {categories.filter(c => { const n = editProduct.niche || 'skin-care'; if (!c.niche) return true; if (c.niche === n) return true; if (n === 'skin-care' && c.niche === 'skincare') return true; return false; }).map(c => (
                          <option key={c.slug} value={c.slug}>{c.icon} {c.name}</option>
                        ))}
                      </select>
                    </div>
                    {/* Subcategory — cascades from chosen Category. Always visible once a category is picked. */}
                    {editProduct.category && (() => {
                      const subs = subcategories.filter(s => s.parent_category === editProduct.category && s.is_active !== false);
                      const parentName = (categories.find(c => c.slug === editProduct.category)?.name) || editProduct.category;
                      return (
                        <div>
                          <label className="text-xs font-semibold text-gray-500 mb-1 block">
                            Subcategory <span className="text-gray-400 font-normal">(optional · only those under "{parentName}")</span>
                          </label>
                          {subs.length > 0 ? (
                            <select
                              value={editProduct.subcategory || ''}
                              onChange={e => setEditProduct({ ...editProduct, subcategory: e.target.value })}
                              className="w-full px-3 py-2 border rounded-lg text-sm bg-white"
                              data-testid="edit-product-subcategory"
                            >
                              <option value="">— None —</option>
                              {subs.map(s => (
                                <option key={s.slug} value={s.slug}>{s.icon} {s.name}</option>
                              ))}
                            </select>
                          ) : (
                            <p className="text-[11px] text-amber-700 mt-1 bg-amber-50 ring-1 ring-amber-200 rounded-lg px-2.5 py-1.5" data-testid="edit-product-subcategory-empty">
                              No subcategories under "{parentName}" yet. <Link to="/admin/categories" className="underline font-bold">Add some</Link> (e.g. Matte / Glossy under Lipstick) — products without a subcategory simply skip this filter.
                            </p>
                          )}
                        </div>
                      );
                    })()}
                    <div>
                      <label className="text-xs font-semibold text-gray-500 mb-1 block">Skin Concerns (multi-select)</label>
                      <div className="flex flex-wrap gap-1.5">
                        {concerns.filter(c => { const n = editProduct.niche || 'skin-care'; if (!c.niche) return true; if (c.niche === n) return true; if (n === 'skin-care' && c.niche === 'skincare') return true; return false; }).map(cn => {
                          const selected = (editProduct.concerns || []).includes(cn.slug);
                          return (
                            <button
                              key={cn.slug}
                              type="button"
                              onClick={() => {
                                const cur = editProduct.concerns || [];
                                const next = selected ? cur.filter(s => s !== cn.slug) : [...cur, cn.slug];
                                setEditProduct({ ...editProduct, concerns: next });
                              }}
                              className={`text-xs font-bold px-2.5 py-1.5 rounded-full border transition-all ${selected ? 'bg-green-600 text-white border-green-600' : 'bg-white text-gray-700 border-gray-200 hover:border-green-400'}`}
                              data-testid={`edit-product-concern-${cn.slug}`}
                            >
                              {cn.icon} {cn.name}
                            </button>
                          );
                        })}
                      </div>
                      {(!editProduct.concerns || editProduct.concerns.length === 0) && (
                        <p className="text-[11px] text-amber-700 mt-1.5">⚠️ No concerns selected — this product won't appear on any concern page.</p>
                      )}
                    </div>
                  </div>

                  {/* TBL / Preorder Controls */}
                  <div className="rounded-xl border border-purple-100 bg-purple-50/40 p-3">
                    <div className="flex items-center gap-2 mb-2">
                      <Clock size={14} className="text-purple-700" />
                      <span className="text-xs font-bold text-purple-900 tracking-wide">LAUNCH STATUS</span>
                    </div>
                    <div className="flex flex-wrap items-center gap-3">
                      <button
                        type="button"
                        onClick={() => setEditProduct({
                          ...editProduct,
                          is_to_be_launched: !editProduct.is_to_be_launched,
                          launch_date: !editProduct.is_to_be_launched
                            ? (editProduct.launch_date || new Date(Date.now() + 25*86400000).toISOString())
                            : null,
                          preorder_enabled: !editProduct.is_to_be_launched ? true : false,
                        })}
                        className={`px-4 py-2 rounded-full text-xs font-bold transition-colors ${editProduct.is_to_be_launched ? 'bg-purple-600 text-white' : 'bg-green-100 text-green-800'}`}
                        data-testid="tbl-toggle"
                      >
                        {editProduct.is_to_be_launched ? 'TBL — To Be Launched' : 'Live — Available Now'}
                      </button>
                      {editProduct.is_to_be_launched && (
                        <>
                          <div className="flex items-center gap-1.5">
                            <label className="text-xs text-gray-600">Launch:</label>
                            <input
                              type="date"
                              value={editProduct.launch_date ? editProduct.launch_date.slice(0, 10) : ''}
                              onChange={e => setEditProduct({ ...editProduct, launch_date: e.target.value ? new Date(e.target.value).toISOString() : null })}
                              className="px-2 py-1.5 border rounded-lg text-xs"
                              data-testid="tbl-launch-date"
                            />
                          </div>
                          <button
                            type="button"
                            onClick={() => setEditProduct({ ...editProduct, preorder_enabled: !editProduct.preorder_enabled })}
                            className={`px-3 py-1.5 rounded-full text-xs font-bold ${editProduct.preorder_enabled ? 'bg-amber-500 text-white' : 'bg-gray-200 text-gray-600'}`}
                            data-testid="preorder-toggle"
                          >
                            Preorder: {editProduct.preorder_enabled ? 'ON' : 'OFF'}
                          </button>
                        </>
                      )}
                    </div>
                    <p className="text-[11px] text-gray-500 mt-2">
                      When TBL: customers see "Coming Soon" + countdown. With Preorder ON, they can place a preorder.
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button onClick={() => updateProduct(product.slug, editProduct)} className="flex items-center gap-1 px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-semibold"><Save size={14} /> Save</button>
                    <button onClick={() => setEditProduct(null)} className="flex items-center gap-1 px-4 py-2 bg-gray-200 text-gray-700 rounded-lg text-sm"><X size={14} /> Cancel</button>
                    <button
                      type="button"
                      onClick={async () => {
                        if (!editProduct.name) { alert('Enter product name first'); return; }
                        setAiGenerating(true);
                        try {
                          const res = await axios.post(`${API}/admin/ai/analyze-product`, {
                            name: editProduct.name,
                            brand: editProduct.brand || '',
                            main_category: editProduct.niche || '',
                            product_type: editProduct.subcategory || editProduct.category || '',
                            concern: (editProduct.concerns || [])[0] || '',
                            auto_create: true,
                          }, { headers });
                          if (res.data?.success) {
                            const c = res.data.classification || {};
                            const merged = {
                              ...editProduct,
                              niche: c.niche || editProduct.niche,
                              category: c.category_slug || editProduct.category,
                              subcategory: c.subcategory_slug || editProduct.subcategory,
                              concerns: [
                                ...(editProduct.concerns || []),
                                ...(c.concerns || []).map(x => x.slug),
                              ].filter((v, i, a) => v && a.indexOf(v) === i),
                            };
                            setEditProduct(merged);
                            // Refresh taxonomy so the new chips/options appear
                            try {
                              const [cnR, ctR, scR] = await Promise.allSettled([
                                axios.get(`${API}/concerns`),
                                axios.get(`${API}/categories`),
                                axios.get(`${API}/subcategories`),
                              ]);
                              if (cnR.status === 'fulfilled') setConcerns(cnR.value.data || []);
                              if (ctR.status === 'fulfilled') setCategories(ctR.value.data || []);
                              if (scR.status === 'fulfilled') setSubcategories(scR.value.data || []);
                            } catch { /* non-fatal */ }
                            const created = res.data.auto_created || {};
                            const total = (created.categories?.length || 0) + (created.subcategories?.length || 0) + (created.concerns?.length || 0);
                            if (total > 0) {
                              alert(`AI Analyze: routed to ${c.niche} → ${c.category_slug}${c.subcategory_slug ? ' / ' + c.subcategory_slug : ''}\nAuto-created ${total} new taxonomy row(s).`);
                            }
                          }
                        } catch (e) {
                          alert(e.response?.data?.detail || 'AI Analyze failed');
                        } finally {
                          setAiGenerating(false);
                        }
                      }}
                      disabled={aiGenerating || !editProduct.name}
                      className="flex items-center gap-1 px-4 py-2 bg-violet-600 hover:bg-violet-700 disabled:opacity-60 text-white rounded-lg text-sm font-semibold"
                      data-testid="ai-analyze-product"
                      title="AI classifies niche / category / subcategory / concerns from the product name and auto-creates missing taxonomy."
                    >
                      <Sparkles size={14} /> {aiGenerating ? 'Analyzing…' : 'AI Analyze'}
                    </button>
                    <button
                      type="button"
                      onClick={async () => {
                        if (!editProduct.name) { alert('Enter product name first'); return; }
                        setAiGenerating(true);
                        try {
                          const res = await axios.post(`${API}/admin/ai/generate-product-content`, {
                            name: editProduct.name,
                            niche: editProduct.niche || 'skincare',
                            category: editProduct.category || '',
                            concerns: editProduct.concerns || [],
                            brand: editProduct.brand || '',
                            key_ingredients: editProduct.key_ingredients || '',
                          }, { headers });
                          if (res.data?.success) {
                            setEditProduct({
                              ...editProduct,
                              tagline: res.data.tagline || editProduct.tagline,
                              description: res.data.description || editProduct.description,
                              key_ingredients: res.data.key_ingredients || editProduct.key_ingredients,
                              ingredients_full: res.data.ingredients_full || editProduct.ingredients_full,
                              benefits: res.data.benefits?.length ? res.data.benefits : (editProduct.benefits || []),
                              how_to_use: res.data.how_to_use || editProduct.how_to_use,
                              size: res.data.size || editProduct.size,
                              faqs: res.data.faqs?.length ? res.data.faqs : (editProduct.faqs || []),
                              mrp: editProduct.mrp || res.data.mrp || editProduct.mrp,
                              prepaid_price: editProduct.prepaid_price || res.data.offer_price || editProduct.prepaid_price,
                              cod_price: editProduct.cod_price || res.data.offer_price || editProduct.cod_price,
                              brand: editProduct.brand || res.data.brand_suggestion || editProduct.brand,
                            });
                          }
                        } catch (e) {
                          alert(e.response?.data?.detail || 'AI generation failed');
                        } finally {
                          setAiGenerating(false);
                        }
                      }}
                      disabled={aiGenerating}
                      className="flex items-center gap-1 px-4 py-2 bg-fuchsia-600 hover:bg-fuchsia-700 disabled:opacity-60 text-white rounded-lg text-sm font-semibold"
                      data-testid="ai-generate-content-edit"
                      title="Auto-fill tagline / description / benefits / how-to-use / FAQs using AI"
                    >
                      <Sparkles size={14} /> {aiGenerating ? 'Generating…' : 'AI Auto-fill'}
                    </button>
                    <button
                      type="button"
                      onClick={async () => {
                        if (!editProduct.slug) { alert('Save the product first, then generate its Formula-Technology image.'); return; }
                        setAiGenerating(true);
                        try {
                          const res = await axios.post(`${API}/admin/ai/generate-marketing-image`, {
                            name: editProduct.name,
                            kind: 'technology',
                            key_ingredients: editProduct.key_ingredients || '',
                            hero_ingredient: (editProduct.key_ingredients || '').split(',')[0]?.trim() || '',
                            category: editProduct.category || editProduct.subcategory || '',
                            brand: editProduct.brand || 'Celesta Glow',
                            slug: editProduct.slug,
                          }, { headers });
                          if (res.data?.success) {
                            setEditProduct({ ...editProduct, images: [...(editProduct.images || []), res.data.image_url] });
                            alert('Formula-Technology image generated & added to the gallery.');
                          }
                        } catch (e) {
                          alert(e.response?.data?.detail || 'Formula-Tech image failed');
                        } finally { setAiGenerating(false); }
                      }}
                      disabled={aiGenerating}
                      className="flex items-center gap-1 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-60 text-white rounded-lg text-sm font-semibold"
                      data-testid="ai-tech-image-edit"
                      title="Generate an on-brand Formula-Technology feature image (green headline + molecule + product) from the name & ingredients."
                    >
                      <Sparkles size={14} /> {aiGenerating ? '…' : 'AI Formula-Tech'}
                    </button>
                    <button
                      type="button"
                      onClick={async () => {
                        if (!editProduct.slug) { alert('Save the product first, then generate its Before/After image.'); return; }
                        setAiGenerating(true);
                        try {
                          const res = await axios.post(`${API}/admin/ai/generate-marketing-image`, {
                            name: editProduct.name,
                            kind: 'before_after',
                            category: editProduct.category || editProduct.subcategory || '',
                            brand: editProduct.brand || 'Celesta Glow',
                            slug: editProduct.slug,
                          }, { headers });
                          if (res.data?.success) {
                            setEditProduct({ ...editProduct, images: [...(editProduct.images || []), res.data.image_url] });
                            alert('Before/After image generated & added to the gallery.');
                          }
                        } catch (e) {
                          alert(e.response?.data?.detail || 'Before/After image failed');
                        } finally { setAiGenerating(false); }
                      }}
                      disabled={aiGenerating}
                      className="flex items-center gap-1 px-4 py-2 bg-teal-600 hover:bg-teal-700 disabled:opacity-60 text-white rounded-lg text-sm font-semibold"
                      data-testid="ai-beforeafter-image-edit"
                      title="Generate a Before/After results image for this product."
                    >
                      <Sparkles size={14} /> {aiGenerating ? '…' : 'AI Before/After'}
                    </button>
                  </div>
                </div>
              ) : (
                /* View Mode */
                <div className="flex items-center gap-4">
                  <input
                    type="checkbox"
                    checked={selectedSlugs.has(product.slug)}
                    onChange={() => toggleSelect(product.slug)}
                    className="w-4 h-4 accent-red-600 cursor-pointer flex-shrink-0"
                    title="Select for bulk actions"
                    data-testid={`select-${product.slug}`}
                    onClick={(e) => e.stopPropagation()}
                  />
                  <div className="text-gray-300 hover:text-gray-500 cursor-grab" title="Drag to reorder" data-testid={`drag-handle-${product.slug}`}>
                    <GripVertical size={18} />
                  </div>
                  <div className="w-16 h-16 bg-gray-100 rounded-xl flex items-center justify-center flex-shrink-0 overflow-hidden">
                    {product.images?.[0] ? <img src={resolveImageUrl(product.images[0])} alt="" className="w-full h-full object-cover" /> : <Package className="w-6 h-6 text-gray-400" />}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-bold text-gray-900 text-sm truncate">{product.name}</h3>
                      {product.is_to_be_launched && (
                        <span className="text-[10px] px-2 py-0.5 bg-purple-100 text-purple-700 rounded-full font-bold flex items-center gap-1">
                          <Clock size={10} /> TBL{product.days_to_launch != null ? ` · ${product.days_to_launch}d` : ''}
                        </span>
                      )}
                      {product.badge && <span className="text-xs px-2 py-0.5 bg-amber-100 text-amber-800 rounded-full font-medium">{product.badge}</span>}
                      {!product.is_active && <span className="text-xs px-2 py-0.5 bg-red-100 text-red-700 rounded-full">Inactive</span>}
                    </div>
                    <p className="text-xs text-gray-500 mt-0.5">{product.key_ingredients} | {product.size} <span className="ml-1.5 text-gray-400">· niche:</span> <span className="font-bold text-gray-700">{product.niche || '—'}</span> {product.category && <><span className="text-gray-400">· cat:</span> <span className="font-bold text-gray-700">{product.category}</span></>}</p>
                    <div className="flex items-center gap-3 mt-1 text-sm flex-wrap">
                      <span className="font-bold text-gray-900">Prepaid: ₹{product.prepaid_price}</span>
                      <span className="text-gray-500">COD: ₹{product.cod_price}</span>
                      <span className="text-gray-400 line-through">MRP: ₹{product.mrp}</span>
                      {Number(product.discount_percent) > 0 && (
                        <span
                          key={`disc-${product.slug}-${product.discount_percent}`}
                          className="text-white text-[10px] font-black px-2 py-0.5 rounded-full bg-emerald-600 shadow-sm animate-[pulse_1.2s_ease-out_1]"
                          data-testid={`discount-badge-${product.slug}`}
                        >
                          {Math.round(Number(product.discount_percent))}% OFF
                        </span>
                      )}
                      {(() => {
                        const sq = product.stock_qty ?? 100;
                        const lt = product.low_stock_threshold ?? 10;
                        const cls = sq <= 0 ? 'bg-red-100 text-red-700' : sq <= lt ? 'bg-amber-100 text-amber-800' : 'bg-emerald-50 text-emerald-700';
                        const lbl = sq <= 0 ? 'Out of stock' : sq <= lt ? `Low: ${sq}` : `Stock: ${sq}`;
                        return <span className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${cls}`} data-testid={`stock-indicator-${product.slug}`}>{lbl}</span>;
                      })()}
                    </div>
                  </div>
                  <div className="flex items-center gap-1 flex-shrink-0">
                    <button onClick={() => moveProductInList(product.slug, -1)} className="p-1.5 hover:bg-gray-100 rounded-lg" title="Move up" data-testid={`move-up-${product.slug}`}><ArrowUp size={14} className="text-gray-500" /></button>
                    <button onClick={() => moveProductInList(product.slug, 1)} className="p-1.5 hover:bg-gray-100 rounded-lg" title="Move down" data-testid={`move-down-${product.slug}`}><ArrowDown size={14} className="text-gray-500" /></button>
                    <button
                      onClick={() => toggleTbl(product.slug, product.is_to_be_launched)}
                      className={`p-2 rounded-lg ${product.is_to_be_launched ? 'bg-green-50 hover:bg-green-100 text-green-700' : 'bg-purple-50 hover:bg-purple-100 text-purple-700'}`}
                      title={product.is_to_be_launched ? 'Mark as Launched' : 'Mark as TBL (To Be Launched)'}
                      data-testid={`quick-tbl-${product.slug}`}
                    >
                      {product.is_to_be_launched ? <Rocket size={16} /> : <Clock size={16} />}
                    </button>
                    <button onClick={() => setRegenProduct(product)} className="p-2 hover:bg-emerald-50 rounded-lg" title="Regenerate image with AI" data-testid={`regen-image-${product.slug}`}><Sparkles size={16} className="text-emerald-600" /></button>
                    {!product.is_variation && (
                      <button onClick={() => setAiVarProduct(product)} className="p-2 hover:bg-violet-50 rounded-lg" title="Generate AI variations from ingredients" data-testid={`ai-variations-${product.slug}`}><Layers size={16} className="text-violet-600" /></button>
                    )}
                    <button onClick={() => setEditProduct({...product})} className="p-2 hover:bg-gray-100 rounded-lg" title="Edit" data-testid={`edit-${product.slug}`}><Edit size={16} className="text-gray-500" /></button>
                    <button onClick={() => toggleProductActive(product.slug, product.is_active)} className="p-2 hover:bg-gray-100 rounded-lg" title={product.is_active ? 'Deactivate' : 'Activate'} data-testid={`toggle-active-${product.slug}`}>
                      {product.is_active ? <Eye size={16} className="text-green-500" /> : <EyeOff size={16} className="text-red-500" />}
                    </button>
                    <button onClick={() => deleteProduct(product.slug)} className="p-2 hover:bg-red-50 rounded-lg" title="Delete" data-testid={`delete-${product.slug}`}><Trash2 size={16} className="text-red-500" /></button>
                  </div>
                </div>
              )}
            </div>
            );
            // The product currently in the editor (if any). New-product flow
            // (__isNew) is handled separately above the filter bar, so we
            // exclude it here.
            const editingSlug = editProduct && !editProduct.__isNew ? editProduct.slug : null;
            const editingInList = editingSlug ? filtered.find(p => p.slug === editingSlug) : null;
            const listItems = editingInList
              ? filtered.filter(p => p.slug !== editingSlug)
              : filtered;

            // Virtualization kicks in only when the catalog gets meaningful.
            // For tiny lists we render the classic non-virtualized layout so
            // small merchants get the cleanest look (no scroll container).
            const VIRTUALIZATION_THRESHOLD = 40;
            const useVirtual = listItems.length > VIRTUALIZATION_THRESHOLD;

            return (
              <>
                {/* Editing card always rendered above (never inside the
                    virtualized list) — its variable height would otherwise
                    break the fixed-row-height assumption. */}
                {editingInList && (
                  <div data-testid="admin-product-edit-pinned">
                    {renderRow(editingInList)}
                  </div>
                )}
                {!useVirtual && (
                  <div className="space-y-4" data-testid="admin-products-list-classic">
                    {listItems.map(p => renderRow(p))}
                  </div>
                )}
                {useVirtual && (
                  <div
                    className="bg-gray-50/40 rounded-2xl border border-gray-100 p-2"
                    style={{ height: 'min(72vh, 820px)' }}
                    data-testid="admin-products-list-virtual"
                  >
                    <List
                      rowCount={listItems.length}
                      rowHeight={120}
                      overscanCount={4}
                      rowProps={{ items: listItems, renderRow }}
                      rowComponent={VirtualProductRow}
                    />
                    <p className="text-[10px] text-gray-400 text-center mt-1" data-testid="virtualization-hint">
                      Showing {listItems.length} products · virtualized for performance
                    </p>
                  </div>
                )}
              </>
            );
          })()}
        </div>
      )}

      {/* Banners Tab — Multi-banner Hero Carousel manager */}
      {activeTab === 'banners' && (
        <BannerCarouselManager
          settings={settings}
          headers={headers}
          onSaved={fetchAll}
        />
      )}

      {/* Combos Tab */}
      {activeTab === 'combos' && (
        <div className="space-y-4">
          {/* Create new combo button + form */}
          <div className="flex items-center justify-between bg-white rounded-2xl border border-dashed border-green-300 p-4">
            <div>
              <h3 className="font-bold text-gray-900 text-sm">Combos &amp; bundles</h3>
              <p className="text-xs text-gray-500">Create a new bundle and assign it to a niche so it shows up on that niche&apos;s Shop All page.</p>
            </div>
            {!newCombo && (
              <button
                onClick={() => setNewCombo({
                  combo_id: '',
                  name: '',
                  description: '',
                  badge: 'Popular',
                  niche: 'anti-aging',
                  image: '',
                  product_slugs: [],
                  mrp_total: 0,
                  combo_prepaid_price: 0,
                  combo_cod_price: 0,
                  discount_percent: 0,
                  is_active: true,
                  is_to_be_launched: false,
                  sort_order: combos.length + 1,
                })}
                className="bg-green-600 hover:bg-green-700 text-white text-xs font-bold px-4 py-2 rounded-lg flex items-center gap-1.5"
                data-testid="create-combo-btn"
              >
                <Plus size={14} /> Create combo
              </button>
            )}
          </div>

          {newCombo && (
            <div className="bg-white rounded-2xl border-2 border-green-400 p-4 space-y-3" data-testid="new-combo-form">
              <div className="flex items-center justify-between">
                <h4 className="font-bold text-green-700 text-sm">New combo</h4>
                <button onClick={() => setNewCombo(null)} className="text-gray-400 hover:text-gray-700 text-xl leading-none">×</button>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-semibold text-gray-500">Combo ID (slug, lowercase, no spaces)</label>
                  <input
                    value={newCombo.combo_id}
                    onChange={e => setNewCombo({ ...newCombo, combo_id: e.target.value })}
                    placeholder="e.g. lip-eye-essentials"
                    className="w-full px-3 py-2 border rounded-lg text-sm font-mono"
                    data-testid="new-combo-id"
                  />
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-500">Name (display)</label>
                  <input value={newCombo.name} onChange={e => setNewCombo({ ...newCombo, name: e.target.value })} placeholder="Lip + Eye Essentials Kit" className="w-full px-3 py-2 border rounded-lg text-sm" data-testid="new-combo-name" />
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-500">Niche (which Shop page shows this combo)</label>
                  <select value={newCombo.niche || ''} onChange={e => setNewCombo({ ...newCombo, niche: e.target.value || null })} className="w-full px-3 py-2 border rounded-lg text-sm bg-white" data-testid="new-combo-niche">
                    <option value="">— Universal (every niche) —</option>
                    <option value="anti-aging">✨ Anti-Aging</option>
                    <option value="skincare">💧 Skincare</option>
                    <option value="cosmetics">💄 Cosmetics</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-500">Badge (optional)</label>
                  <input value={newCombo.badge || ''} onChange={e => setNewCombo({ ...newCombo, badge: e.target.value })} placeholder="Popular / Bestseller / New" className="w-full px-3 py-2 border rounded-lg text-sm" />
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-500">MRP Total (₹)</label>
                  <input type="number" value={newCombo.mrp_total} onChange={e => setNewCombo({ ...newCombo, mrp_total: Number(e.target.value) })} className="w-full px-3 py-2 border rounded-lg text-sm" />
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-500">Prepaid Price (₹)</label>
                  <input type="number" value={newCombo.combo_prepaid_price} onChange={e => setNewCombo({ ...newCombo, combo_prepaid_price: Number(e.target.value) })} className="w-full px-3 py-2 border rounded-lg text-sm" />
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-500">COD Price (₹)</label>
                  <input type="number" value={newCombo.combo_cod_price} onChange={e => setNewCombo({ ...newCombo, combo_cod_price: Number(e.target.value) })} className="w-full px-3 py-2 border rounded-lg text-sm" />
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-500">Discount %</label>
                  <input type="number" value={newCombo.discount_percent} onChange={e => setNewCombo({ ...newCombo, discount_percent: Number(e.target.value) })} className="w-full px-3 py-2 border rounded-lg text-sm" />
                </div>
              </div>

              <div>
                <label className="text-xs font-semibold text-gray-500">Description</label>
                <textarea value={newCombo.description} onChange={e => setNewCombo({ ...newCombo, description: e.target.value })} className="w-full px-3 py-2 border rounded-lg text-sm" rows={2} placeholder="A 30-second pitch the customer will read on the combo card" />
              </div>

              <div>
                <label className="text-xs font-semibold text-gray-500 mb-1.5 block">Products in this combo (pick from existing catalogue)</label>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 max-h-48 overflow-y-auto bg-gray-50 rounded-xl p-2">
                  {products.filter(p => !newCombo.niche || p.niche === newCombo.niche).map(p => {
                    const checked = newCombo.product_slugs.includes(p.slug);
                    return (
                      <label key={p.slug} className={`flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-pointer text-xs ${checked ? 'bg-green-100 text-green-800 font-semibold' : 'bg-white border'}`}>
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={e => {
                            const next = e.target.checked
                              ? [...newCombo.product_slugs, p.slug]
                              : newCombo.product_slugs.filter(s => s !== p.slug);
                            setNewCombo({ ...newCombo, product_slugs: next });
                          }}
                          data-testid={`new-combo-product-${p.slug}`}
                        />
                        <span className="truncate">{p.short_name || p.name}</span>
                      </label>
                    );
                  })}
                </div>
                <p className="text-[10px] text-gray-400 mt-1">{newCombo.product_slugs.length} product{newCombo.product_slugs.length === 1 ? '' : 's'} selected.</p>
              </div>

              <ImageManager
                images={newCombo.image || ''}
                onChange={url => setNewCombo({ ...newCombo, image: url })}
                label="Combo packshot (Cloudinary)"
                single
                headers={headers}
              />

              <div className="flex gap-2 pt-1">
                <button onClick={createCombo} className="flex items-center gap-1 px-4 py-2 bg-green-600 hover:bg-green-700 text-white rounded-lg text-sm font-bold" data-testid="new-combo-save">
                  <Save size={14} /> Save combo
                </button>
                <button onClick={() => setNewCombo(null)} className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg text-sm">Cancel</button>
              </div>
            </div>
          )}

          {combos.map(combo => (
            <div key={combo.combo_id} className="bg-white rounded-2xl border border-gray-200 p-4" data-testid={`admin-combo-${combo.combo_id}`}>
              {editCombo?.combo_id === combo.combo_id ? (
                <div className="space-y-3">
                  <div className="grid grid-cols-2 gap-3">
                    <div><label className="text-xs font-semibold text-gray-500">Name</label><input value={editCombo.name} onChange={e => setEditCombo({...editCombo, name: e.target.value})} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                    <div><label className="text-xs font-semibold text-gray-500">Badge</label><input value={editCombo.badge || ''} onChange={e => setEditCombo({...editCombo, badge: e.target.value})} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                    <div>
                      <label className="text-xs font-semibold text-gray-500">Niche <span className="text-gray-400 font-normal">(controls which niche page shows this combo)</span></label>
                      <select value={editCombo.niche || ''} onChange={e => setEditCombo({...editCombo, niche: e.target.value || null})} className="w-full px-3 py-2 border rounded-lg text-sm bg-white" data-testid={`combo-niche-${combo.combo_id}`}>
                        <option value="">— Universal (shows everywhere) —</option>
                        <option value="anti-aging">✨ Anti-Aging</option>
                        <option value="skincare">💧 Skincare</option>
                        <option value="cosmetics">💄 Cosmetics</option>
                      </select>
                    </div>
                    <div><label className="text-xs font-semibold text-gray-500">MRP Total (₹)</label><input type="number" value={editCombo.mrp_total} onChange={e => setEditCombo({...editCombo, mrp_total: Number(e.target.value)})} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                    <div><label className="text-xs font-semibold text-gray-500">Prepaid Price (₹)</label><input type="number" value={editCombo.combo_prepaid_price} onChange={e => setEditCombo({...editCombo, combo_prepaid_price: Number(e.target.value)})} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                    <div><label className="text-xs font-semibold text-gray-500">COD Price (₹)</label><input type="number" value={editCombo.combo_cod_price} onChange={e => setEditCombo({...editCombo, combo_cod_price: Number(e.target.value)})} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                    <div><label className="text-xs font-semibold text-gray-500">Discount %</label><input type="number" value={editCombo.discount_percent} onChange={e => setEditCombo({...editCombo, discount_percent: Number(e.target.value)})} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                  </div>
                  <div><label className="text-xs font-semibold text-gray-500">Description</label><textarea value={editCombo.description || ''} onChange={e => setEditCombo({...editCombo, description: e.target.value})} className="w-full px-3 py-2 border rounded-lg text-sm" rows={2} /></div>

                  {/* Image upload for combo */}
                  <ImageManager
                    images={editCombo.image || ''}
                    onChange={(url) => setEditCombo({...editCombo, image: url})}
                    label="Combo Image (kit packaging shot)"
                    single
                    headers={headers}
                  />

                  {/* TBL controls for combos */}
                  <div className="rounded-xl border border-purple-100 bg-purple-50/40 p-3">
                    <div className="flex items-center gap-2 mb-2">
                      <Clock size={14} className="text-purple-700" />
                      <span className="text-xs font-bold text-purple-900 tracking-wide">LAUNCH STATUS</span>
                    </div>
                    <div className="flex flex-wrap items-center gap-3">
                      <button
                        type="button"
                        onClick={() => setEditCombo({
                          ...editCombo,
                          is_to_be_launched: !editCombo.is_to_be_launched,
                          launch_date: !editCombo.is_to_be_launched
                            ? (editCombo.launch_date || new Date(Date.now() + 25 * 86400000).toISOString())
                            : null,
                          preorder_enabled: !editCombo.is_to_be_launched ? true : false,
                        })}
                        className={`px-4 py-2 rounded-full text-xs font-bold transition-colors ${editCombo.is_to_be_launched ? 'bg-purple-600 text-white' : 'bg-green-100 text-green-800'}`}
                        data-testid={`combo-tbl-toggle-${combo.combo_id}`}
                      >
                        {editCombo.is_to_be_launched ? 'TBL — To Be Launched' : 'Live — Available Now'}
                      </button>
                      {editCombo.is_to_be_launched && (
                        <>
                          <div className="flex items-center gap-1.5">
                            <label className="text-xs text-gray-600">Launch:</label>
                            <input
                              type="date"
                              value={editCombo.launch_date ? editCombo.launch_date.slice(0, 10) : ''}
                              onChange={e => setEditCombo({...editCombo, launch_date: e.target.value ? new Date(e.target.value).toISOString() : null})}
                              className="px-2 py-1.5 border rounded-lg text-xs"
                            />
                          </div>
                          <button
                            type="button"
                            onClick={() => setEditCombo({...editCombo, preorder_enabled: !editCombo.preorder_enabled})}
                            className={`px-3 py-1.5 rounded-full text-xs font-bold ${editCombo.preorder_enabled ? 'bg-amber-500 text-white' : 'bg-gray-200 text-gray-600'}`}
                          >
                            Preorder: {editCombo.preorder_enabled ? 'ON' : 'OFF'}
                          </button>
                        </>
                      )}
                    </div>
                  </div>

                  <div className="flex gap-2">
                    <button onClick={() => updateCombo(combo.combo_id, editCombo)} className="flex items-center gap-1 px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-semibold"><Save size={14} /> Save</button>
                    <button onClick={() => setEditCombo(null)} className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg text-sm">Cancel</button>
                  </div>
                </div>
              ) : (
                <div className="flex items-start justify-between gap-3">
                  {combo.image && <img src={combo.image} alt="" className="w-20 h-20 rounded-lg object-cover flex-shrink-0 border border-gray-100" />}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-bold text-gray-900">{combo.name}</h3>
                      {combo.is_to_be_launched && (
                        <span className="text-[10px] px-2 py-0.5 bg-purple-100 text-purple-700 rounded-full font-bold flex items-center gap-1">
                          <Clock size={10} /> TBL{combo.days_to_launch != null ? ` · ${combo.days_to_launch}d` : ''}
                        </span>
                      )}
                      {combo.badge && <span className="text-xs px-2 py-0.5 bg-amber-100 text-amber-800 rounded-full">{combo.badge}</span>}
                    </div>
                    <p className="text-sm text-gray-500 mt-1 truncate">{combo.product_slugs?.join(', ')} | {combo.discount_percent}% OFF</p>
                    <p className="text-sm font-bold text-gray-900 mt-1">Prepaid: ₹{combo.combo_prepaid_price} | COD: ₹{combo.combo_cod_price} <span className="text-gray-400 line-through ml-2">MRP: ₹{combo.mrp_total}</span></p>
                  </div>
                  <button onClick={() => setEditCombo({...combo})} className="p-2 hover:bg-gray-100 rounded-lg flex-shrink-0"><Edit size={16} className="text-gray-500" /></button>
                  <button onClick={() => deleteCombo(combo.combo_id)} className="p-2 hover:bg-red-50 rounded-lg flex-shrink-0" title="Delete combo" data-testid={`delete-combo-${combo.combo_id}`}><Trash2 size={16} className="text-red-500" /></button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Coupons Tab */}
      {activeTab === 'coupons' && (
        <div className="space-y-4" data-testid="admin-coupons-tab">
          {/* Stats summary */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3" data-testid="admin-coupons-stats">
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Total Coupons</p>
              <p className="text-2xl font-black text-gray-900 mt-1">{coupons.length}</p>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Active</p>
              <p className="text-2xl font-black text-green-600 mt-1">{coupons.filter(c => c.is_active !== false).length}</p>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Visible on Cart</p>
              <p className="text-2xl font-black text-orange-600 mt-1">{coupons.filter(c => c.show_on_cart !== false && c.is_active !== false).length}</p>
            </div>
            <div className="bg-white rounded-2xl border border-gray-200 p-4">
              <p className="text-[10px] font-bold uppercase tracking-wider text-gray-500">Total Redemptions</p>
              <p className="text-2xl font-black text-purple-600 mt-1">{coupons.reduce((s, c) => s + (c.used_count || 0), 0)}</p>
            </div>
          </div>

          {/* Create coupon */}
          <div className="bg-white rounded-2xl border border-gray-200 p-4" data-testid="create-coupon-card">
            <h3 className="font-bold text-gray-900 mb-3">Create Coupon</h3>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              <input value={newCoupon.code} onChange={e => setNewCoupon({...newCoupon, code: e.target.value.toUpperCase()})} placeholder="Code (e.g., SAVE10)" className="px-3 py-2 border rounded-lg text-sm uppercase" data-testid="coupon-code-input" />
              <select value={newCoupon.discount_type} onChange={e => setNewCoupon({...newCoupon, discount_type: e.target.value})} className="px-3 py-2 border rounded-lg text-sm" data-testid="coupon-type-input">
                <option value="percentage">Percentage</option>
                <option value="fixed">Fixed Amount</option>
              </select>
              <input type="number" value={newCoupon.discount_value} onChange={e => setNewCoupon({...newCoupon, discount_value: Number(e.target.value)})} placeholder="Value" className="px-3 py-2 border rounded-lg text-sm" data-testid="coupon-value-input" />
              <input type="number" value={newCoupon.min_order_amount} onChange={e => setNewCoupon({...newCoupon, min_order_amount: Number(e.target.value)})} placeholder="Min order ₹" className="px-3 py-2 border rounded-lg text-sm" />
              <input type="number" value={newCoupon.max_uses} onChange={e => setNewCoupon({...newCoupon, max_uses: Number(e.target.value)})} placeholder="Max uses" className="px-3 py-2 border rounded-lg text-sm" />
              <input type="number" value={newCoupon.expiry_days} onChange={e => setNewCoupon({...newCoupon, expiry_days: Number(e.target.value)})} placeholder="Expiry (days)" className="px-3 py-2 border rounded-lg text-sm" />
              <input value={newCoupon.description || ''} onChange={e => setNewCoupon({...newCoupon, description: e.target.value})} placeholder="Description (e.g. 20% off on serums)" className="sm:col-span-3 px-3 py-2 border rounded-lg text-sm" data-testid="coupon-description-input" />
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <label className="inline-flex items-center gap-2 text-xs font-semibold text-gray-700 cursor-pointer">
                <input type="checkbox" checked={newCoupon.show_on_cart} onChange={e => setNewCoupon({...newCoupon, show_on_cart: e.target.checked})} className="w-4 h-4 rounded text-green-600 focus:ring-green-500" data-testid="coupon-show-on-cart-input" />
                Show on cart page (so users can tap-apply)
              </label>
              <label className="inline-flex items-center gap-2 text-xs font-semibold text-gray-700 cursor-pointer">
                <input type="checkbox" checked={newCoupon.is_active} onChange={e => setNewCoupon({...newCoupon, is_active: e.target.checked})} className="w-4 h-4 rounded text-green-600 focus:ring-green-500" data-testid="coupon-active-input" />
                Active
              </label>
              <button onClick={createCoupon} className="ml-auto flex items-center gap-1 px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-semibold hover:bg-green-700" data-testid="create-coupon-btn"><Plus size={14} /> Create Coupon</button>
            </div>
          </div>

          {/* Existing coupons list */}
          {coupons.length === 0 ? (
            <div className="bg-white rounded-2xl border border-gray-200 p-8 text-center text-sm text-gray-500" data-testid="no-coupons-msg">
              No coupons yet — create your first coupon above.
            </div>
          ) : coupons.map(coupon => (
            <div key={coupon.code} className="bg-white rounded-2xl border border-gray-200 p-4" data-testid={`admin-coupon-${coupon.code}`}>
              {editCoupon === coupon.code ? (
                /* Edit mode */
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-bold text-gray-900 text-lg">{coupon.code}</span>
                    <span className="text-xs text-gray-500">Editing — code is permanent, delete & recreate to change</span>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                    <select value={editCouponDraft.discount_type} onChange={e => setEditCouponDraft({...editCouponDraft, discount_type: e.target.value})} className="px-3 py-2 border rounded-lg text-sm">
                      <option value="percentage">Percentage</option>
                      <option value="fixed">Fixed Amount</option>
                    </select>
                    <input type="number" value={editCouponDraft.discount_value} onChange={e => setEditCouponDraft({...editCouponDraft, discount_value: Number(e.target.value)})} placeholder="Value" className="px-3 py-2 border rounded-lg text-sm" data-testid={`edit-coupon-value-${coupon.code}`} />
                    <input type="number" value={editCouponDraft.min_order_amount} onChange={e => setEditCouponDraft({...editCouponDraft, min_order_amount: Number(e.target.value)})} placeholder="Min order ₹" className="px-3 py-2 border rounded-lg text-sm" />
                    <input type="number" value={editCouponDraft.max_uses} onChange={e => setEditCouponDraft({...editCouponDraft, max_uses: Number(e.target.value)})} placeholder="Max uses" className="px-3 py-2 border rounded-lg text-sm" />
                    <input value={editCouponDraft.description || ''} onChange={e => setEditCouponDraft({...editCouponDraft, description: e.target.value})} placeholder="Description" className="sm:col-span-2 px-3 py-2 border rounded-lg text-sm" />
                  </div>
                  <div className="flex flex-wrap items-center gap-3">
                    <label className="inline-flex items-center gap-2 text-xs font-semibold text-gray-700 cursor-pointer">
                      <input type="checkbox" checked={editCouponDraft.show_on_cart !== false} onChange={e => setEditCouponDraft({...editCouponDraft, show_on_cart: e.target.checked})} className="w-4 h-4 rounded text-green-600" />
                      Show on cart
                    </label>
                    <label className="inline-flex items-center gap-2 text-xs font-semibold text-gray-700 cursor-pointer">
                      <input type="checkbox" checked={editCouponDraft.is_active !== false} onChange={e => setEditCouponDraft({...editCouponDraft, is_active: e.target.checked})} className="w-4 h-4 rounded text-green-600" />
                      Active
                    </label>
                    <button onClick={saveEditCoupon} className="ml-auto flex items-center gap-1 px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-semibold hover:bg-green-700" data-testid={`save-coupon-${coupon.code}`}><Save size={14} /> Save</button>
                    <button onClick={() => { setEditCoupon(null); setEditCouponDraft({}); }} className="flex items-center gap-1 px-4 py-2 bg-gray-200 text-gray-700 rounded-lg text-sm"><X size={14} /> Cancel</button>
                  </div>
                </div>
              ) : (
                /* View mode */
                <div className="flex items-center justify-between gap-3 flex-wrap">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono font-bold text-gray-900 text-lg">{coupon.code}</span>
                      {coupon.is_active === false && <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-red-100 text-red-700">Inactive</span>}
                      {coupon.is_active !== false && <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-green-100 text-green-700">Active</span>}
                      {coupon.show_on_cart !== false && coupon.is_active !== false && <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-orange-100 text-orange-700">Cart-visible</span>}
                    </div>
                    <p className="text-sm text-gray-600 mt-1">
                      <span className="font-bold">{coupon.discount_type === 'percentage' ? `${coupon.discount_value}% off` : `₹${coupon.discount_value} off`}</span>
                      {coupon.min_order_amount > 0 && <span className="text-gray-500"> · Min order ₹{coupon.min_order_amount}</span>}
                      <span className="text-gray-500"> · Used {coupon.used_count || 0}/{coupon.max_uses}</span>
                    </p>
                    {coupon.description && <p className="text-xs text-gray-500 mt-1 italic">{coupon.description}</p>}
                  </div>
                  <div className="flex items-center gap-1.5">
                    <button onClick={() => toggleCouponActive(coupon)} className={`p-2 rounded-lg ${coupon.is_active !== false ? 'hover:bg-gray-100 text-green-600' : 'hover:bg-gray-100 text-gray-400'}`} title={coupon.is_active !== false ? 'Deactivate' : 'Activate'} data-testid={`toggle-active-${coupon.code}`}>
                      {coupon.is_active !== false ? <Eye size={16} /> : <EyeOff size={16} />}
                    </button>
                    <button onClick={() => startEditCoupon(coupon)} className="p-2 hover:bg-gray-100 rounded-lg text-blue-600" title="Edit" data-testid={`edit-coupon-${coupon.code}`}><Edit size={16} /></button>
                    <button onClick={() => deleteCoupon(coupon.code)} className="p-2 hover:bg-red-50 rounded-lg text-red-500" title="Delete" data-testid={`delete-coupon-${coupon.code}`}><Trash2 size={16} /></button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Settings Tab */}
      {activeTab === 'settings' && (
        <div className="bg-white rounded-2xl border border-gray-200 p-5 space-y-4">
          <h3 className="font-bold text-gray-900">Site Settings</h3>
          {editSettings ? (
            <>
              <div><label className="text-xs font-semibold text-gray-500">Hero Title</label><input value={editSettings.hero_title || ''} onChange={e => setEditSettings({...editSettings, hero_title: e.target.value})} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
              <div><label className="text-xs font-semibold text-gray-500">Hero Subtitle</label><textarea value={editSettings.hero_subtitle || ''} onChange={e => setEditSettings({...editSettings, hero_subtitle: e.target.value})} className="w-full px-3 py-2 border rounded-lg text-sm" rows={2} /></div>
              <ImageManager images={editSettings.hero_banner_image || ''} onChange={(url) => setEditSettings({...editSettings, hero_banner_image: url})} label="Hero Banner Image (under main heading)" single headers={headers} />
              <ImageManager images={editSettings.bundle_hero_image || ''} onChange={(url) => setEditSettings({...editSettings, bundle_hero_image: url})} label="Anti-Aging Kit Landscape Image (Shop View All — top of kit card)" single headers={headers} />
              <p className="text-[11px] text-gray-500 -mt-2">Use a wide 16:5 or 16:6 landscape image. Shows on /shop and /shop?niche=anti-aging at the top of the Complete Anti-Aging Kit card.</p>

              {/* NEW: Homepage Feature Banner (replaces 3-product side panel on hero) */}
              <div className="rounded-xl border border-green-100 bg-green-50/40 p-3 space-y-2">
                <div className="flex items-center gap-2">
                  <ImageIcon size={14} className="text-green-700" />
                  <span className="text-xs font-bold text-green-900 tracking-wide">HOMEPAGE FEATURE BANNER (right of "India's #1" section)</span>
                </div>
                <ImageManager images={editSettings.homepage_feature_image || ''} onChange={(url) => setEditSettings({...editSettings, homepage_feature_image: url})} label="Landscape Feature Image" single headers={headers} />
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  <div><label className="text-xs font-semibold text-gray-500">Feature Title</label><input value={editSettings.homepage_feature_title || ''} onChange={e => setEditSettings({...editSettings, homepage_feature_title: e.target.value})} className="w-full px-3 py-2 border rounded-lg text-sm" placeholder="e.g., Complete Skin Renewal System" /></div>
                  <div><label className="text-xs font-semibold text-gray-500">Feature Subtitle</label><input value={editSettings.homepage_feature_subtitle || ''} onChange={e => setEditSettings({...editSettings, homepage_feature_subtitle: e.target.value})} className="w-full px-3 py-2 border rounded-lg text-sm" placeholder="e.g., 5 clinical products. One transformation." /></div>
                </div>
              </div>
              <div><label className="text-xs font-semibold text-gray-500">COD Advance Amount (₹)</label><input type="number" value={editSettings.cod_advance_amount || 29} onChange={e => setEditSettings({...editSettings, cod_advance_amount: Number(e.target.value)})} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
              <div className="flex items-center gap-3">
                <label className="text-xs font-semibold text-gray-500">Pre-Sale Mode</label>
                <button onClick={() => setEditSettings({...editSettings, presale_enabled: !editSettings.presale_enabled})} className={`px-4 py-1.5 rounded-full text-sm font-bold ${editSettings.presale_enabled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'}`}>
                  {editSettings.presale_enabled ? 'ENABLED' : 'DISABLED'}
                </button>
              </div>
              {editSettings.presale_enabled && (
                <>
                  <div><label className="text-xs font-semibold text-gray-500">Pre-Sale Title</label><input value={editSettings.presale_title || ''} onChange={e => setEditSettings({...editSettings, presale_title: e.target.value})} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                  <div><label className="text-xs font-semibold text-gray-500">Pre-Sale Badge</label><input value={editSettings.presale_badge || ''} onChange={e => setEditSettings({...editSettings, presale_badge: e.target.value})} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                  <div><label className="text-xs font-semibold text-gray-500">Pre-Sale Price (₹)</label><input type="number" value={editSettings.presale_price || ''} onChange={e => setEditSettings({...editSettings, presale_price: Number(e.target.value)})} placeholder="e.g., 2 or 20" className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                </>
              )}
              <div className="flex gap-2">
                <button onClick={updateSiteSettings} className="flex items-center gap-1 px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-semibold"><Save size={14} /> Save</button>
                <button onClick={() => setEditSettings(null)} className="px-4 py-2 bg-gray-200 text-gray-700 rounded-lg text-sm">Cancel</button>
              </div>
            </>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="bg-gray-50 rounded-lg p-3"><p className="text-xs text-gray-500">Hero Title</p><p className="font-medium">{settings.hero_title || 'Not set'}</p></div>
                <div className="bg-gray-50 rounded-lg p-3"><p className="text-xs text-gray-500">COD Advance</p><p className="font-medium">₹{settings.cod_advance_amount || 29}</p></div>
                <div className="bg-gray-50 rounded-lg p-3"><p className="text-xs text-gray-500">Pre-Sale</p><p className="font-medium">{settings.presale_enabled ? 'ENABLED' : 'Disabled'}</p></div>
              </div>
              <button onClick={() => setEditSettings({...settings})} className="flex items-center gap-1 px-4 py-2 bg-gray-900 text-white rounded-lg text-sm font-semibold"><Edit size={14} /> Edit Settings</button>
            </>
          )}
        </div>
      )}

      {/* URL Analyzer modal — usable from any tab when creating a new product */}
      <URLAnalyzerModal
        open={analyzerOpen}
        onClose={() => setAnalyzerOpen(false)}
        headers={headers}
        onApply={(d) => {
          setEditProduct(prev => {
            const base = prev || { __isNew: true, slug: '', niche: 'anti-aging', is_active: true, sort_order: 99, stock_qty: 100, low_stock_threshold: 10, cod_advance: 29, badges: [] };
            return {
              ...base,
              name: d.name || base.name || '',
              short_name: d.name ? d.name.split(' ').slice(0, 4).join(' ') : (base.short_name || ''),
              tagline: d.tagline || base.tagline || '',
              description: d.description || base.description || '',
              key_ingredients: d.key_ingredients || base.key_ingredients || '',
              benefits: Array.isArray(d.benefits) && d.benefits.length ? d.benefits : (base.benefits || []),
              size: d.size || base.size || '',
              images: Array.isArray(d.images) && d.images.length ? d.images : (base.images || []),
              mrp: Number(d.mrp || base.mrp || d.price || 0),
              prepaid_price: Number(d.price || base.prepaid_price || 0),
              cod_price: Number(d.price ? Math.round(d.price * 1.05) : (base.cod_price || 0)),
              source_url: d.source_url || '',
              slug: base.slug || (d.name ? d.name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60) : ''),
            };
          });
        }}
      />
    </div>
  );
}

/* ============================================================
   Banner Carousel Manager
   - List existing banners
   - Add new (upload image, set title/subtitle/CTA)
   - Reorder (move up/down)
   - Delete
   - Set autoplay interval
   ============================================================ */
function BannerCarouselManager({ settings, headers, onSaved }) {
  const API = process.env.REACT_APP_BACKEND_URL;
  const [banners, setBanners] = useState([]);
  const [autoplayMs, setAutoplayMs] = useState(2000);
  const [draft, setDraft] = useState({ image: '', title: '', subtitle: '', cta_text: 'Shop Now', cta_link: '/shop' });
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef(null);

  useEffect(() => {
    const sorted = (settings?.banner_carousel || []).slice().sort((a, b) => (a.sort_order || 0) - (b.sort_order || 0));
    setBanners(sorted);
    setAutoplayMs(settings?.carousel_autoplay_ms || 2000);
  }, [settings]);

  const persist = async (newBanners, newAutoplay) => {
    try {
      const ordered = newBanners.map((b, i) => ({ ...b, sort_order: i + 1 }));
      await axios.put(`${API}/admin/site-settings`,
        { banner_carousel: ordered, carousel_autoplay_ms: newAutoplay ?? autoplayMs },
        { headers });
      onSaved();
    } catch (err) { alert(err.response?.data?.detail || 'Save failed'); }
  };

  const handleFileUpload = async (file) => {
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const res = await axios.post(`${API}/admin/upload-image`, fd, {
        headers: { ...headers, 'Content-Type': 'multipart/form-data' }
      });
      setDraft(d => ({ ...d, image: res.data.url }));
    } catch (err) {
      alert(err.response?.data?.detail || 'Upload failed');
    }
    setUploading(false);
  };

  const addBanner = async () => {
    if (!draft.image) { alert('Please upload an image first'); return; }
    const newBanner = {
      id: `banner-${Date.now()}`,
      image: draft.image,
      title: draft.title || '',
      subtitle: draft.subtitle || '',
      cta_text: draft.cta_text || '',
      cta_link: draft.cta_link || '/shop',
      sort_order: banners.length + 1,
    };
    const updated = [...banners, newBanner];
    setBanners(updated);
    await persist(updated);
    setDraft({ image: '', title: '', subtitle: '', cta_text: 'Shop Now', cta_link: '/shop' });
    if (fileRef.current) fileRef.current.value = '';
  };

  const deleteBanner = async (id) => {
    if (!window.confirm('Delete this banner?')) return;
    const updated = banners.filter(b => b.id !== id);
    setBanners(updated);
    await persist(updated);
  };

  const moveBanner = async (id, dir) => {
    const idx = banners.findIndex(b => b.id === id);
    const target = idx + dir;
    if (target < 0 || target >= banners.length) return;
    const updated = [...banners];
    [updated[idx], updated[target]] = [updated[target], updated[idx]];
    setBanners(updated);
    await persist(updated);
  };

  const updateBannerField = (id, field, value) => {
    setBanners(prev => prev.map(b => b.id === id ? { ...b, [field]: value } : b));
  };

  const saveBannerEdits = async () => { await persist(banners); };

  return (
    <div className="space-y-5" data-testid="banner-manager">
      {/* Settings row */}
      <div className="bg-white rounded-2xl border border-gray-200 p-4 flex flex-col sm:flex-row sm:items-center gap-3">
        <div className="flex items-center gap-2">
          <ImageIcon size={18} className="text-green-600" />
          <h3 className="font-bold text-gray-900">Hero Banner Carousel</h3>
        </div>
        <div className="flex-1" />
        <div className="flex items-center gap-2">
          <label className="text-xs text-gray-600">Autoplay (ms):</label>
          <input
            type="number"
            min="1500"
            step="500"
            value={autoplayMs}
            onChange={e => setAutoplayMs(Number(e.target.value))}
            onBlur={() => persist(banners, autoplayMs)}
            className="w-24 px-2 py-1.5 border rounded-lg text-sm"
            data-testid="banner-autoplay-input"
          />
        </div>
      </div>

      {/* Add new banner */}
      <div className="bg-white rounded-2xl border border-gray-200 p-5">
        <h4 className="font-bold text-gray-900 mb-3 flex items-center gap-2"><Plus size={16} /> Add New Banner</h4>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div>
            <label className="text-xs font-semibold text-gray-500">Image</label>
            <div className="mt-1 flex items-center gap-3">
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                onChange={e => handleFileUpload(e.target.files?.[0])}
                className="text-xs flex-1"
                data-testid="banner-upload-input"
              />
              {uploading && <span className="text-xs text-gray-500">Uploading...</span>}
            </div>
            {draft.image && (
              <div className="mt-2 relative">
                <img src={draft.image} alt="preview" className="w-full h-32 object-cover rounded-lg border border-gray-100" />
              </div>
            )}
          </div>
          <div className="space-y-2">
            <div><label className="text-xs font-semibold text-gray-500">Title</label><input value={draft.title} onChange={e => setDraft({...draft, title: e.target.value})} placeholder="e.g., Clinically Proven Anti-Aging" className="w-full px-3 py-2 border rounded-lg text-sm" data-testid="banner-title-input" /></div>
            <div><label className="text-xs font-semibold text-gray-500">Subtitle</label><input value={draft.subtitle} onChange={e => setDraft({...draft, subtitle: e.target.value})} placeholder="e.g., Visible results in 4 weeks" className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
            <div className="grid grid-cols-2 gap-2">
              <div><label className="text-xs font-semibold text-gray-500">CTA Text</label><input value={draft.cta_text} onChange={e => setDraft({...draft, cta_text: e.target.value})} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
              <div><label className="text-xs font-semibold text-gray-500">CTA Link</label><input value={draft.cta_link} onChange={e => setDraft({...draft, cta_link: e.target.value})} placeholder="/shop" className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
            </div>
          </div>
        </div>
        <button onClick={addBanner} disabled={uploading || !draft.image} className="mt-3 px-4 py-2 bg-green-600 hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed text-white rounded-lg text-sm font-semibold flex items-center gap-1" data-testid="banner-add-btn">
          <Plus size={14} /> Add Banner
        </button>
      </div>

      {/* Existing banners list */}
      {banners.length === 0 ? (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 text-center text-sm text-amber-800">
          No banners yet. Add at least one to populate the homepage hero carousel.
        </div>
      ) : (
        <div className="space-y-3">
          {banners.map((b, i) => (
            <div key={b.id} className="bg-white rounded-2xl border border-gray-200 p-4 flex flex-col md:flex-row gap-4 items-start" data-testid={`banner-item-${i}`}>
              <img src={b.image} alt={b.title} className="w-full md:w-44 h-28 object-cover rounded-lg flex-shrink-0 border border-gray-100" />
              <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-2 w-full">
                <div><label className="text-xs font-semibold text-gray-500">Title</label><input value={b.title || ''} onChange={e => updateBannerField(b.id, 'title', e.target.value)} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                <div><label className="text-xs font-semibold text-gray-500">Subtitle</label><input value={b.subtitle || ''} onChange={e => updateBannerField(b.id, 'subtitle', e.target.value)} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                <div><label className="text-xs font-semibold text-gray-500">CTA Text</label><input value={b.cta_text || ''} onChange={e => updateBannerField(b.id, 'cta_text', e.target.value)} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
                <div><label className="text-xs font-semibold text-gray-500">CTA Link</label><input value={b.cta_link || ''} onChange={e => updateBannerField(b.id, 'cta_link', e.target.value)} className="w-full px-3 py-2 border rounded-lg text-sm" /></div>
              </div>
              <div className="flex md:flex-col gap-1 flex-shrink-0">
                <button onClick={() => moveBanner(b.id, -1)} disabled={i === 0} className="p-1.5 rounded-lg bg-gray-100 hover:bg-gray-200 disabled:opacity-40" title="Move up"><ArrowUp size={14} /></button>
                <button onClick={() => moveBanner(b.id, 1)} disabled={i === banners.length - 1} className="p-1.5 rounded-lg bg-gray-100 hover:bg-gray-200 disabled:opacity-40" title="Move down"><ArrowDown size={14} /></button>
                <button onClick={saveBannerEdits} className="p-1.5 rounded-lg bg-green-600 text-white hover:bg-green-700" title="Save edits"><Save size={14} /></button>
                <button onClick={() => deleteBanner(b.id)} className="p-1.5 rounded-lg bg-red-50 text-red-600 hover:bg-red-100" title="Delete"><Trash2 size={14} /></button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default AdminProducts;

// ─── Inline helper: bulk % OFF applier for the sticky bulk-action bar ────────
function BulkDiscountInput({ onApply, disabled }) {
  const [pct, setPct] = React.useState('');
  const submit = () => {
    if (pct === '' || pct === null) return;
    onApply(pct);
  };
  return (
    <div className="flex items-center gap-1.5 bg-white/15 rounded-lg px-2 py-1" data-testid="bulk-discount-widget">
      <span className="text-[10px] font-black uppercase tracking-wider text-white/90">Apply</span>
      <input
        type="number"
        min="0"
        max="95"
        step="1"
        value={pct}
        onChange={e => setPct(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter') {
            e.preventDefault();
            submit();
          }
        }}
        placeholder="%"
        disabled={disabled}
        className="w-14 px-2 py-1 rounded-md text-xs font-bold text-gray-900 outline-none focus:ring-2 focus:ring-white/60 disabled:opacity-60"
        data-testid="bulk-discount-input"
      />
      <span className="text-[10px] font-black text-white/90">% OFF</span>
      <button
        onClick={submit}
        disabled={disabled || pct === ''}
        className="text-xs font-black px-2.5 py-1 rounded-md bg-white text-red-700 hover:bg-red-50 disabled:opacity-60"
        data-testid="bulk-discount-apply"
        title="Recomputes prepaid_price = MRP × (1 − %/100). Press Enter to apply."
      >
        Apply
      </button>
    </div>
  );
}


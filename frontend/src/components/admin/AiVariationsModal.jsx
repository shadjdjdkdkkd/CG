import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { X, Sparkles, Loader2, Check, AlertTriangle, RefreshCw, ImagePlus } from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Analyse a product's ingredients → AI suggests result-led variations → admin
// reviews & creates the ones they want (each create optionally regenerates a
// hero image that keeps the same bottle).
export const AiVariationsModal = ({ product, headers, onClose, onCreated }) => {
  const [status, setStatus] = useState('loading'); // loading | ready | error
  const [error, setError] = useState('');
  const [variations, setVariations] = useState([]);
  const slug = product?.slug;

  const suggest = async () => {
    setStatus('loading'); setError('');
    try {
      const res = await axios.post(`${API}/admin/products/${slug}/ai-variations`, {}, { headers });
      const list = (res.data?.variations || []).map((v) => ({
        ...v,
        generate_image: true,
        _state: 'idle', // idle | creating | created | error
        _msg: '',
      }));
      setVariations(list);
      setStatus(list.length ? 'ready' : 'error');
      if (!list.length) setError('AI could not find distinct variations for this product.');
    } catch (e) {
      setStatus('error');
      setError(e.response?.data?.detail || 'AI analysis failed. Check GEMINI_API_KEY / quota.');
    }
  };

  useEffect(() => { if (slug) suggest(); /* eslint-disable-next-line */ }, [slug]);

  const patch = (i, upd) => setVariations((vs) => vs.map((v, j) => (j === i ? { ...v, ...upd } : v)));

  const createOne = async (i) => {
    const v = variations[i];
    if (v._state === 'creating' || v._state === 'created') return;
    patch(i, { _state: 'creating', _msg: v.generate_image ? 'Generating image…' : 'Creating…' });
    try {
      const res = await axios.post(`${API}/admin/products/${slug}/ai-variations/create`, {
        name: v.name, result: v.result, tagline: v.tagline, description: v.description,
        key_ingredients: v.key_ingredients, benefits: v.benefits, how_to_use: v.how_to_use,
        generate_image: v.generate_image, is_active: false,
      }, { headers });
      patch(i, { _state: 'created', _msg: res.data?.image_generated ? 'Created with new image' : 'Created' });
      onCreated && onCreated();
    } catch (e) {
      patch(i, { _state: 'error', _msg: e.response?.data?.detail || 'Create failed' });
    }
  };

  const createAll = async () => {
    for (let i = 0; i < variations.length; i += 1) {
      // eslint-disable-next-line no-await-in-loop
      if (variations[i]._state !== 'created') await createOne(i);
    }
  };

  const anyBusy = variations.some((v) => v._state === 'creating');

  return (
    <div className="fixed inset-0 bg-black/50 z-[60] flex items-start justify-center p-4 overflow-y-auto" data-testid="ai-variations-modal">
      <div className="bg-white rounded-2xl w-full max-w-3xl my-8 shadow-xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 sticky top-0 bg-white rounded-t-2xl">
          <div className="flex items-center gap-2">
            <span className="w-8 h-8 rounded-lg bg-emerald-50 flex items-center justify-center"><Sparkles size={16} className="text-emerald-600" /></span>
            <div>
              <h3 className="font-bold text-gray-900 text-sm">AI Variations</h3>
              <p className="text-[11px] text-gray-500">From ingredients of <b>{product?.name}</b></p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={suggest} disabled={status === 'loading' || anyBusy} className="flex items-center gap-1 text-xs font-semibold text-gray-600 hover:text-emerald-700 disabled:opacity-40" data-testid="ai-variations-refresh"><RefreshCw size={13} /> New ideas</button>
            <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg" data-testid="ai-variations-close"><X size={18} className="text-gray-500" /></button>
          </div>
        </div>

        <div className="p-5">
          {status === 'loading' && (
            <div className="py-16 text-center" data-testid="ai-variations-loading">
              <Loader2 size={30} className="mx-auto animate-spin text-emerald-600" />
              <p className="text-sm text-gray-500 mt-3">Analysing ingredients & designing variations…</p>
            </div>
          )}

          {status === 'error' && (
            <div className="py-12 text-center" data-testid="ai-variations-error">
              <AlertTriangle size={28} className="mx-auto text-amber-500" />
              <p className="text-sm text-gray-700 mt-3">{error}</p>
              <button onClick={suggest} className="mt-4 px-4 py-2 bg-emerald-600 text-white rounded-lg text-sm font-semibold">Try again</button>
            </div>
          )}

          {status === 'ready' && (
            <>
              <div className="flex items-center justify-between mb-3">
                <p className="text-xs text-gray-500">{variations.length} suggested · each new variation is created <b>inactive</b> so you can review before publishing.</p>
                <button onClick={createAll} disabled={anyBusy} className="flex items-center gap-1.5 px-3 py-2 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white rounded-lg text-xs font-bold" data-testid="ai-variations-create-all"><ImagePlus size={13} /> Create all</button>
              </div>
              <div className="space-y-3">
                {variations.map((v, i) => (
                  <div key={i} className={`rounded-xl border p-4 ${v._state === 'created' ? 'border-emerald-300 bg-emerald-50/40' : 'border-gray-200'}`} data-testid={`ai-variation-${i}`}>
                    <div className="flex items-start gap-3">
                      <div className="flex-1 min-w-0">
                        <input
                          value={v.name}
                          onChange={(e) => patch(i, { name: e.target.value })}
                          disabled={v._state === 'created'}
                          className="w-full font-bold text-gray-900 text-sm border border-transparent hover:border-gray-200 focus:border-emerald-400 rounded-md px-1.5 py-1 -ml-1.5 disabled:bg-transparent"
                          data-testid={`ai-variation-name-${i}`}
                        />
                        {v.result && <span className="inline-block mt-1 text-[10px] font-bold uppercase tracking-wide text-emerald-700 bg-emerald-100 rounded-full px-2 py-0.5">{v.result}</span>}
                        {v.tagline && <p className="text-xs text-gray-600 italic mt-1.5">“{v.tagline}”</p>}
                        <p className="text-xs text-gray-600 mt-2 line-clamp-3">{v.description}</p>
                        {v.benefits?.length > 0 && (
                          <ul className="flex flex-wrap gap-1.5 mt-2">
                            {v.benefits.slice(0, 5).map((b, k) => (
                              <li key={k} className="text-[10px] bg-gray-100 text-gray-700 rounded-full px-2 py-0.5">{b}</li>
                            ))}
                          </ul>
                        )}
                        {v.key_ingredients && <p className="text-[11px] text-gray-500 mt-2"><b>Actives:</b> {v.key_ingredients}</p>}
                      </div>
                      <div className="shrink-0 w-32 flex flex-col gap-2">
                        <label className="flex items-center gap-1.5 text-[11px] text-gray-600 cursor-pointer">
                          <input type="checkbox" checked={v.generate_image} disabled={v._state === 'created'}
                            onChange={(e) => patch(i, { generate_image: e.target.checked })}
                            data-testid={`ai-variation-genimg-${i}`} />
                          Regenerate image
                        </label>
                        {v._state === 'created' ? (
                          <span className="inline-flex items-center justify-center gap-1 text-xs font-bold text-emerald-700" data-testid={`ai-variation-created-${i}`}><Check size={14} /> {v._msg}</span>
                        ) : (
                          <button onClick={() => createOne(i)} disabled={v._state === 'creating' || !v.name.trim()}
                            className="flex items-center justify-center gap-1.5 px-3 py-2 bg-gray-900 hover:bg-black disabled:opacity-50 text-white rounded-lg text-xs font-bold"
                            data-testid={`ai-variation-create-${i}`}>
                            {v._state === 'creating' ? <><Loader2 size={13} className="animate-spin" /> {v._msg}</> : <><Sparkles size={13} /> Create</>}
                          </button>
                        )}
                        {v._state === 'error' && <span className="text-[10px] text-red-600" data-testid={`ai-variation-err-${i}`}>{v._msg}</span>}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default AiVariationsModal;

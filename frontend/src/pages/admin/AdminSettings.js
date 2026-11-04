/**
 * AdminSettings — Cloudinary credentials + admin password change.
 *
 * Cloudinary section lets the admin save cloud_name / api_key / api_secret.
 * The api_secret is sent to the server but never displayed once saved (we only
 * ever fetch the masked version back).
 *
 * Password section calls /api/admin/change-password and forces a re-login on success.
 */
import React, { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import axios from 'axios';
import { ArrowLeft, Cloud, Save, KeyRound, CheckCircle2, AlertCircle, Eye, EyeOff, Package, Image as ImageIcon, Upload, Loader2, Sparkles, Pencil } from 'lucide-react';
import { getAdminToken, clearAdminToken } from '../../utils/adminAuth';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export default function AdminSettings() {
  const navigate = useNavigate();
  const token = getAdminToken();

  // Cloudinary state
  const [cdn, setCdn] = useState({ cloud_name: '', api_key: '', api_secret: '', api_secret_masked: '', configured: false });
  const [cdnSaving, setCdnSaving] = useState(false);
  const [cdnMsg, setCdnMsg] = useState({ type: '', text: '' });
  const [showSecret, setShowSecret] = useState(false);

  // Password state
  const [pw, setPw] = useState({ current: '', next: '', confirm: '' });
  const [pwSaving, setPwSaving] = useState(false);
  const [pwMsg, setPwMsg] = useState({ type: '', text: '' });

  // Storefront state (other-brands availability + product-image reference bottles)
  const [otherBrands, setOtherBrands] = useState(null); // null=loading
  const [obSaving, setObSaving] = useState(false);
  const [refSerum, setRefSerum] = useState('');
  const [refCream, setRefCream] = useState('');
  const [refUploading, setRefUploading] = useState(''); // 'serum' | 'cream' | ''
  const [refMsg, setRefMsg] = useState({ type: '', text: '' });

  // AI generation (Gemini) key state — masked display, edit → save
  const [aiKey, setAiKey] = useState({ masked: '', source: 'none', configured: false, autoGen: true });
  const [aiEditing, setAiEditing] = useState(false);
  const [aiInput, setAiInput] = useState('');
  const [aiSaving, setAiSaving] = useState(false);
  const [aiMsg, setAiMsg] = useState({ type: '', text: '' });

  const loadAiKey = async () => {
    try {
      const r = await axios.get(`${API}/admin/ai-key`, { headers: { 'X-Admin-Token': token } });
      setAiKey({ masked: r.data.masked || '', source: r.data.source || 'none', configured: !!r.data.configured, autoGen: r.data.auto_product_gen_enabled !== false });
    } catch { /* ignore */ }
  };

  const saveAiKey = async (e) => {
    e.preventDefault();
    if (!aiInput.trim()) { setAiMsg({ type: 'err', text: 'Paste the new API key first.' }); return; }
    setAiSaving(true);
    setAiMsg({ type: '', text: '' });
    try {
      await axios.put(`${API}/admin/ai-key`, { gemini_api_key: aiInput.trim() }, { headers: { 'X-Admin-Token': token } });
      setAiMsg({ type: 'ok', text: 'AI key updated — all generation now uses the new key.' });
      setAiInput('');
      setAiEditing(false);
      loadAiKey();
    } catch (err) {
      setAiMsg({ type: 'err', text: err.response?.data?.detail || 'Failed to save the key.' });
    } finally {
      setAiSaving(false);
    }
  };

  const toggleAutoGen = async () => {
    const next = !aiKey.autoGen;
    setAiKey(k => ({ ...k, autoGen: next }));
    try {
      await axios.put(`${API}/admin/ai-key/auto-gen`, { enabled: next }, { headers: { 'X-Admin-Token': token } });
    } catch { setAiKey(k => ({ ...k, autoGen: !next })); }
  };

  useEffect(() => {
    if (!token) {
      navigate('/admin');
      return;
    }
    (async () => {
      try {
        const r = await axios.get(`${API}/admin/cloudinary/settings`, { headers: { 'X-Admin-Token': token } });
        setCdn({
          cloud_name: r.data.cloud_name || '',
          api_key: r.data.api_key || '',
          api_secret: '',
          api_secret_masked: r.data.api_secret_masked || '',
          configured: !!r.data.configured,
        });
      } catch {
        // ignore
      }
      loadAiKey();
      try {
        const s = await axios.get(`${API}/site-settings`);
        setOtherBrands(!!s.data?.other_brands_in_stock);
        setRefSerum(s.data?.product_image_reference_serum_url || s.data?.product_image_reference_url || '');
        setRefCream(s.data?.product_image_reference_cream_url || '');
      } catch {
        setOtherBrands(false);
      }
    })();
  }, [token, navigate]);

  const toggleOtherBrands = async () => {
    if (otherBrands === null) return;
    const next = !otherBrands;
    setObSaving(true);
    setOtherBrands(next);
    try {
      await axios.put(`${API}/admin/site-settings`, { other_brands_in_stock: next }, { headers: { 'X-Admin-Token': token } });
    } catch (err) {
      setOtherBrands(!next); // revert
    } finally {
      setObSaving(false);
    }
  };

  const uploadReference = async (kind, e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setRefMsg({ type: '', text: '' });
    setRefUploading(kind);
    try {
      const fd = new FormData();
      fd.append('file', file);
      fd.append('folder', `celesta-glow/brand-reference`);
      const up = await axios.post(`${API}/admin/upload-image`, fd, { headers: { 'X-Admin-Token': token } });
      const url = up.data?.url || up.data?.secure_url || '';
      if (!url) throw new Error('No URL returned');
      await axios.put(`${API}/admin/site-settings`, { [`product_image_reference_${kind}_url`]: url }, { headers: { 'X-Admin-Token': token } });
      if (kind === 'serum') setRefSerum(url); else setRefCream(url);
      setRefMsg({ type: 'ok', text: `${kind === 'serum' ? 'Serum' : 'Cream'} reference bottle saved. AI will now generate products on this bottle.` });
    } catch (err) {
      setRefMsg({ type: 'err', text: err.response?.data?.detail || 'Upload failed. Make sure Cloudinary is configured.' });
    } finally {
      setRefUploading('');
      e.target.value = '';
    }
  };

  const clearReference = async (kind) => {
    setRefUploading(kind);
    try {
      await axios.put(`${API}/admin/site-settings`, { [`product_image_reference_${kind}_url`]: '' }, { headers: { 'X-Admin-Token': token } });
      if (kind === 'serum') setRefSerum(''); else setRefCream('');
      setRefMsg({ type: 'ok', text: 'Reference removed. Generation falls back to the default approved bottles.' });
    } catch (err) {
      setRefMsg({ type: 'err', text: 'Could not clear the reference.' });
    } finally {
      setRefUploading('');
    }
  };

  const saveCloudinary = async (e) => {
    e.preventDefault();
    setCdnMsg({ type: '', text: '' });
    if (!cdn.cloud_name.trim() || !cdn.api_key.trim() || !cdn.api_secret.trim()) {
      setCdnMsg({ type: 'err', text: 'cloud_name, api_key and api_secret are all required.' });
      return;
    }
    setCdnSaving(true);
    try {
      await axios.post(`${API}/admin/cloudinary/settings`, {
        cloud_name: cdn.cloud_name.trim(),
        api_key: cdn.api_key.trim(),
        api_secret: cdn.api_secret.trim(),
      }, { headers: { 'X-Admin-Token': token } });
      setCdnMsg({ type: 'ok', text: 'Cloudinary credentials saved. Image uploads now go to Cloudinary.' });
      setCdn(prev => ({ ...prev, api_secret: '', configured: true }));
      // Refresh masked view
      const r = await axios.get(`${API}/admin/cloudinary/settings`, { headers: { 'X-Admin-Token': token } });
      setCdn(prev => ({ ...prev, api_secret_masked: r.data.api_secret_masked || '' }));
    } catch (err) {
      setCdnMsg({ type: 'err', text: err.response?.data?.detail || 'Failed to save credentials.' });
    } finally {
      setCdnSaving(false);
    }
  };

  const changePassword = async (e) => {
    e.preventDefault();
    setPwMsg({ type: '', text: '' });
    if (pw.next.length < 8) { setPwMsg({ type: 'err', text: 'New password must be at least 8 characters.' }); return; }
    if (pw.next !== pw.confirm) { setPwMsg({ type: 'err', text: 'New passwords do not match.' }); return; }
    setPwSaving(true);
    try {
      await axios.post(`${API}/admin/change-password`, {
        current_password: pw.current,
        new_password: pw.next,
      }, { headers: { 'X-Admin-Token': token } });
      setPwMsg({ type: 'ok', text: 'Password updated. Please sign in again with the new password.' });
      setTimeout(() => {
        clearAdminToken();
        navigate('/admin');
      }, 1800);
    } catch (err) {
      setPwMsg({ type: 'err', text: err.response?.data?.detail || 'Failed to change password.' });
    } finally {
      setPwSaving(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50" data-testid="admin-settings-page">
      <div className="max-w-3xl mx-auto px-4 py-8 lg:ml-64">
        <Link to="/admin/dashboard" className="inline-flex items-center gap-2 text-gray-500 hover:text-gray-900 text-sm mb-4" data-testid="settings-back">
          <ArrowLeft size={16} /> Back to dashboard
        </Link>
        <h1 className="text-2xl font-bold text-gray-900 mb-1">Settings</h1>
        <p className="text-sm text-gray-500 mb-6">Image hosting credentials and admin password.</p>

        {/* Cloudinary */}
        <section className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-6" data-testid="cloudinary-section">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-9 h-9 rounded-lg bg-blue-50 flex items-center justify-center"><Cloud size={18} className="text-blue-600" /></div>
            <div>
              <h2 className="text-lg font-bold text-gray-900">Cloudinary (Image hosting)</h2>
              <p className="text-xs text-gray-500">All product / routine / consultation images upload here for fast delivery.</p>
            </div>
            {cdn.configured ? (
              <span className="ml-auto inline-flex items-center gap-1 text-xs font-bold text-green-700 bg-green-50 px-2.5 py-1 rounded-full"><CheckCircle2 size={12} /> Configured</span>
            ) : (
              <span className="ml-auto inline-flex items-center gap-1 text-xs font-bold text-amber-700 bg-amber-50 px-2.5 py-1 rounded-full"><AlertCircle size={12} /> Needs cloud_name</span>
            )}
          </div>

          <form onSubmit={saveCloudinary} className="space-y-4">
            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1">Cloud name</label>
              <input
                type="text"
                value={cdn.cloud_name}
                onChange={(e) => setCdn({ ...cdn, cloud_name: e.target.value })}
                placeholder="e.g. celesta-glow"
                className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm bg-stone-50 focus:bg-white focus:ring-2 focus:ring-blue-200"
                data-testid="cdn-cloud-name"
              />
              <p className="text-[11px] text-gray-400 mt-1">Find this on your Cloudinary dashboard (Account → Account Details).</p>
            </div>
            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1">API key</label>
              <input
                type="text"
                value={cdn.api_key}
                onChange={(e) => setCdn({ ...cdn, api_key: e.target.value })}
                className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm bg-stone-50 focus:bg-white focus:ring-2 focus:ring-blue-200 font-mono"
                data-testid="cdn-api-key"
              />
            </div>
            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1">API secret</label>
              <div className="relative">
                <input
                  type={showSecret ? 'text' : 'password'}
                  value={cdn.api_secret}
                  onChange={(e) => setCdn({ ...cdn, api_secret: e.target.value })}
                  placeholder={cdn.api_secret_masked || 'Enter API secret'}
                  className="w-full border border-gray-200 rounded-xl px-3 py-2.5 pr-11 text-sm bg-stone-50 focus:bg-white focus:ring-2 focus:ring-blue-200 font-mono"
                  data-testid="cdn-api-secret"
                />
                <button type="button" onClick={() => setShowSecret(s => !s)} className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-700" aria-label="Toggle secret visibility">
                  {showSecret ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
              {cdn.api_secret_masked && !cdn.api_secret && (
                <p className="text-[11px] text-gray-400 mt-1">Currently saved: {cdn.api_secret_masked}. Re-enter to replace.</p>
              )}
            </div>

            {cdnMsg.text && (
              <div className={`px-3 py-2 rounded-lg text-xs ${cdnMsg.type === 'ok' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}`} data-testid="cdn-msg">
                {cdnMsg.text}
              </div>
            )}

            <button type="submit" disabled={cdnSaving} className="inline-flex items-center gap-2 bg-gray-900 text-white text-sm font-bold px-4 py-2.5 rounded-xl hover:bg-black disabled:opacity-50" data-testid="cdn-save">
              <Save size={14} /> {cdnSaving ? 'Saving…' : 'Save Cloudinary credentials'}
            </button>
          </form>
        </section>

        {/* AI generation (Gemini) API key */}
        <section className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-6" data-testid="ai-key-section">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-9 h-9 rounded-lg bg-indigo-50 flex items-center justify-center"><Sparkles size={18} className="text-indigo-600" /></div>
            <div className="flex-1">
              <h2 className="text-lg font-bold text-gray-900">AI generation key (Gemini)</h2>
              <p className="text-xs text-gray-500">Powers bulk product generation, one-click products, AI images and listing copy.</p>
            </div>
            {aiKey.configured ? (
              <span className="inline-flex items-center gap-1 text-xs font-bold text-green-700 bg-green-50 px-2.5 py-1 rounded-full"><CheckCircle2 size={12} /> Active</span>
            ) : (
              <span className="inline-flex items-center gap-1 text-xs font-bold text-red-700 bg-red-50 px-2.5 py-1 rounded-full"><AlertCircle size={12} /> Missing</span>
            )}
          </div>

          <div className="flex items-center justify-between rounded-xl bg-stone-50 border border-stone-200 px-4 py-3 mb-3">
            <div className="min-w-0">
              <p className="text-sm font-bold text-gray-900 font-mono truncate" data-testid="ai-key-current">
                {aiKey.configured ? aiKey.masked : 'No key set'}
              </p>
              <p className="text-[11px] text-gray-400">Source: {aiKey.source === 'saved' ? 'saved here (survives redeploys)' : aiKey.source === 'environment' ? 'server environment' : 'none'}</p>
            </div>
            <button
              type="button"
              onClick={() => { setAiEditing(e => !e); setAiInput(''); setAiMsg({ type: '', text: '' }); }}
              className="inline-flex items-center gap-1.5 text-xs font-bold text-indigo-700 bg-indigo-50 hover:bg-indigo-100 px-3 py-2 rounded-lg shrink-0 ml-3"
              data-testid="ai-key-edit"
            >
              <Pencil size={12} /> {aiEditing ? 'Close' : 'Edit'}
            </button>
          </div>

          {aiEditing && (
            <form onSubmit={saveAiKey} className="space-y-3">
              <input
                type="password"
                value={aiInput}
                onChange={(e) => setAiInput(e.target.value)}
                placeholder="Paste new Gemini API key"
                className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm bg-stone-50 focus:bg-white focus:ring-2 focus:ring-indigo-200 font-mono"
                data-testid="ai-key-input"
              />
              {aiMsg.text && (
                <div className={`px-3 py-2 rounded-lg text-xs ${aiMsg.type === 'ok' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}`} data-testid="ai-key-msg">
                  {aiMsg.text}
                </div>
              )}
              <button type="submit" disabled={aiSaving} className="inline-flex items-center gap-2 bg-indigo-600 text-white text-sm font-bold px-4 py-2.5 rounded-xl hover:bg-indigo-700 disabled:opacity-50" data-testid="ai-key-save">
                <Save size={14} /> {aiSaving ? 'Saving…' : 'Save new key'}
              </button>
            </form>
          )}

          <div className="flex items-center justify-between rounded-xl bg-stone-50 border border-stone-200 px-4 py-3 mt-4">
            <div>
              <p className="text-sm font-bold text-gray-900">Daily auto product generation</p>
              <p className="text-[11px] text-gray-400">Adds ~5 new cream-style SKUs every day (₹599–₹899), skipping anything that already exists.</p>
            </div>
            <button
              type="button"
              onClick={toggleAutoGen}
              className={`relative w-12 h-7 rounded-full transition-colors flex-shrink-0 ml-3 ${aiKey.autoGen ? 'bg-emerald-500' : 'bg-stone-300'}`}
              data-testid="auto-gen-toggle"
            >
              <span className={`absolute top-0.5 w-6 h-6 rounded-full bg-white shadow transition-transform ${aiKey.autoGen ? 'translate-x-5' : 'translate-x-0.5'}`} />
            </button>
          </div>
        </section>

        {/* Storefront: Other Brands availability */}
        <section className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-6" data-testid="other-brands-section">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-9 h-9 rounded-lg bg-stone-900 flex items-center justify-center"><Package size={18} className="text-white" /></div>
            <div className="flex-1">
              <h2 className="text-lg font-bold text-gray-900">Other Brands availability</h2>
              <p className="text-xs text-gray-500">When OFF, non-Celesta-Glow products stay visible but are blocked at checkout.</p>
            </div>
          </div>
          <div className="flex items-center justify-between rounded-xl bg-stone-50 border border-stone-200 px-4 py-3">
            <div>
              <p className="text-sm font-bold text-gray-900">
                {otherBrands === null ? 'Loading…' : otherBrands ? 'In stock — purchasable' : 'Out of stock (blocked at checkout)'}
              </p>
              <p className="text-[11px] text-gray-400">Master switch for all other-brand SKUs.</p>
            </div>
            <button
              onClick={toggleOtherBrands}
              disabled={obSaving || otherBrands === null}
              className={`relative w-12 h-7 rounded-full transition-colors flex-shrink-0 ${otherBrands ? 'bg-emerald-500' : 'bg-stone-300'} disabled:opacity-60`}
              data-testid="other-brands-toggle"
              title={otherBrands ? 'Click to mark OUT of stock' : 'Click to mark IN stock'}
            >
              {obSaving ? (
                <Loader2 size={13} className="absolute inset-0 m-auto text-white animate-spin" />
              ) : (
                <span className={`absolute top-0.5 w-6 h-6 rounded-full bg-white shadow transition-transform ${otherBrands ? 'translate-x-5' : 'translate-x-0.5'}`} />
              )}
            </button>
          </div>
        </section>

        {/* Storefront: Product image reference bottles */}
        <section className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6 mb-6" data-testid="product-ref-section">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-9 h-9 rounded-lg bg-violet-50 flex items-center justify-center"><ImageIcon size={18} className="text-violet-600" /></div>
            <div className="flex-1">
              <h2 className="text-lg font-bold text-gray-900">Product image reference bottles</h2>
              <p className="text-xs text-gray-500">Upload your two bottle photos (white backdrop). The AI reuses the exact bottle and prints each product&apos;s own name on the label — only the label changes.</p>
            </div>
          </div>

          <div className="grid sm:grid-cols-2 gap-4">
            {[
              { key: 'serum', title: 'Serum / Pump bottle', url: refSerum, fileId: 'ref-file-serum' },
              { key: 'cream', title: 'Cream / Night bottle', url: refCream, fileId: 'ref-file-cream' },
            ].map((b) => (
              <div key={b.key} className="rounded-xl border border-stone-200 bg-stone-50 p-3 flex items-center gap-3">
                <div className="w-20 h-24 rounded-lg border border-stone-200 bg-white overflow-hidden flex items-center justify-center shrink-0">
                  {b.url ? <img src={b.url} alt={`${b.title} reference`} className="w-full h-full object-contain" /> : <ImageIcon size={22} className="text-stone-300" />}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-[13px] font-bold text-gray-900">{b.title}</p>
                  <p className="text-[11px] text-gray-400 mb-2">{b.url ? 'Custom reference active' : 'Using default approved bottle'}</p>
                  <input id={b.fileId} type="file" accept="image/*" onChange={(e) => uploadReference(b.key, e)} className="hidden" />
                  <div className="flex flex-wrap gap-2">
                    <label htmlFor={b.fileId} className="inline-flex items-center gap-1.5 bg-violet-600 text-white text-xs font-bold px-3 py-2 rounded-lg hover:bg-violet-700 cursor-pointer" data-testid={`ref-upload-${b.key}`}>
                      {refUploading === b.key ? <Loader2 size={13} className="animate-spin" /> : <Upload size={13} />} {b.url ? 'Replace' : 'Upload'}
                    </label>
                    {b.url && (
                      <button onClick={() => clearReference(b.key)} disabled={refUploading === b.key} className="inline-flex items-center gap-1.5 bg-white border border-stone-200 text-stone-600 text-xs font-bold px-3 py-2 rounded-lg hover:bg-stone-50 disabled:opacity-50" data-testid={`ref-clear-${b.key}`}>
                        Remove
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
          {refMsg.text && (
            <div className={`mt-3 px-3 py-2 rounded-lg text-xs ${refMsg.type === 'ok' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}`} data-testid="ref-msg">
              {refMsg.text}
            </div>
          )}
        </section>

        {/* Password */}
        <section className="bg-white rounded-2xl border border-gray-200 shadow-sm p-6" data-testid="password-section">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-9 h-9 rounded-lg bg-rose-50 flex items-center justify-center"><KeyRound size={18} className="text-rose-600" /></div>
            <div>
              <h2 className="text-lg font-bold text-gray-900">Admin password</h2>
              <p className="text-xs text-gray-500">After changing, sign in again with the new password.</p>
            </div>
          </div>

          <form onSubmit={changePassword} className="space-y-3">
            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1">Current password</label>
              <input type="password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm bg-stone-50 focus:bg-white focus:ring-2 focus:ring-rose-200" data-testid="pw-current" />
            </div>
            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1">New password</label>
              <input type="password" value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm bg-stone-50 focus:bg-white focus:ring-2 focus:ring-rose-200" data-testid="pw-new" />
            </div>
            <div>
              <label className="block text-xs font-bold text-gray-700 mb-1">Confirm new password</label>
              <input type="password" value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm bg-stone-50 focus:bg-white focus:ring-2 focus:ring-rose-200" data-testid="pw-confirm" />
            </div>

            {pwMsg.text && (
              <div className={`px-3 py-2 rounded-lg text-xs ${pwMsg.type === 'ok' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}`} data-testid="pw-msg">
                {pwMsg.text}
              </div>
            )}

            <button type="submit" disabled={pwSaving} className="inline-flex items-center gap-2 bg-rose-600 text-white text-sm font-bold px-4 py-2.5 rounded-xl hover:bg-rose-700 disabled:opacity-50" data-testid="pw-save">
              <Save size={14} /> {pwSaving ? 'Updating…' : 'Change password'}
            </button>
          </form>
        </section>
      </div>
    </div>
  );
}

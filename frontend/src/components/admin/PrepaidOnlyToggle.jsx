import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { Wallet, Loader2 } from 'lucide-react';
import { getAdminToken } from '../../utils/adminAuth';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Store-wide "Prepaid only" master switch. When ON, Cash on Delivery is
// disabled everywhere (checkout hides COD; backend rejects COD orders).
export const PrepaidOnlyToggle = () => {
  const [on, setOn] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    axios.get(`${API}/site-settings`)
      .then((r) => setOn(!!r.data?.prepaid_only))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const toggle = async () => {
    const next = !on;
    setSaving(true);
    setOn(next); // optimistic
    try {
      await axios.put(`${API}/admin/site-settings`, { prepaid_only: next }, { headers: { 'X-Admin-Token': getAdminToken() } });
      toast.success(next ? 'Prepaid-only mode ON — COD disabled store-wide' : 'Prepaid-only mode OFF — COD allowed again');
    } catch (e) {
      setOn(!next); // revert
      toast.error('Could not update payment mode');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-white rounded-2xl p-4 mb-6 border border-gray-100 flex items-center justify-between gap-4" data-testid="prepaid-only-card">
      <div className="flex items-center gap-3">
        <span className="w-10 h-10 rounded-xl bg-emerald-50 flex items-center justify-center shrink-0"><Wallet className="w-5 h-5 text-emerald-600" /></span>
        <div>
          <p className="font-bold text-gray-900 text-sm">Prepaid-only mode</p>
          <p className="text-xs text-gray-500">{on ? 'Cash on Delivery is disabled — only online payment works.' : 'Cash on Delivery is available alongside prepaid.'}</p>
        </div>
      </div>
      <button
        onClick={toggle}
        disabled={loading || saving}
        role="switch"
        aria-checked={on}
        data-testid="prepaid-only-toggle"
        className={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${on ? 'bg-emerald-600' : 'bg-gray-300'}`}
      >
        {saving ? (
          <Loader2 className="w-3.5 h-3.5 animate-spin text-white mx-auto" />
        ) : (
          <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition-transform ${on ? 'translate-x-6' : 'translate-x-1'}`} />
        )}
      </button>
    </div>
  );
};

export default PrepaidOnlyToggle;

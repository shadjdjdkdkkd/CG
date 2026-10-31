import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { toast } from 'sonner';
import { BadgePercent, Loader2 } from 'lucide-react';
import { getAdminToken } from '../../utils/adminAuth';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

// Partial COD: customer pays a fixed advance (₹100) online via Razorpay, rest on delivery.
export const PartialCodToggle = () => {
  const [on, setOn] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    axios.get(`${API}/site-settings`)
      .then((r) => setOn(!!r.data?.partial_cod_enabled))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const toggle = async () => {
    const next = !on;
    setSaving(true);
    setOn(next);
    try {
      await axios.put(`${API}/admin/site-settings`, { partial_cod_enabled: next }, { headers: { 'X-Admin-Token': getAdminToken() } });
      toast.success(next ? 'Partial COD ON — customers pay ₹100 online, rest on delivery' : 'Partial COD OFF — full COD / prepaid');
    } catch (e) {
      setOn(!next);
      toast.error('Could not update partial COD');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-white rounded-2xl p-4 mb-6 border border-gray-100 flex items-center justify-between gap-4" data-testid="partial-cod-card">
      <div className="flex items-center gap-3">
        <span className="w-10 h-10 rounded-xl bg-amber-50 flex items-center justify-center shrink-0"><BadgePercent className="w-5 h-5 text-amber-600" /></span>
        <div>
          <p className="font-bold text-gray-900 text-sm">Partial COD mode</p>
          <p className="text-xs text-gray-500">{on ? 'COD orders pay ₹100 online now, balance on delivery.' : 'COD is full-on-delivery (no advance).'}</p>
        </div>
      </div>
      <button
        onClick={toggle}
        disabled={loading || saving}
        role="switch"
        aria-checked={on}
        data-testid="partial-cod-toggle"
        className={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition-colors disabled:opacity-50 ${on ? 'bg-amber-500' : 'bg-gray-300'}`}
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

export default PartialCodToggle;

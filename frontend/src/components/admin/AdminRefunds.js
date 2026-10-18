import React, { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import { RotateCcw, CheckCircle2, XCircle } from 'lucide-react';
import { mp, adminHdr, statusColor, fmtStatus } from '../../utils/mpApi';

// Refund request management (consultation + home). Approving credits the customer wallet.
export default function AdminRefunds() {
  const [rows, setRows] = useState([]);
  const [filter, setFilter] = useState('pending');
  const [busy, setBusy] = useState('');

  const load = useCallback(() => {
    mp.get('/admin/refunds', { ...adminHdr(), params: filter ? { status: filter } : {} })
      .then((r) => setRows(r.data)).catch(() => toast.error('Failed to load refunds'));
  }, [filter]);
  useEffect(() => { load(); }, [load]);

  const process = async (r, action) => {
    const extra = action === 'refunded'
      ? { to: 'wallet', reference: window.prompt('Reference / note (optional)') || '' }
      : { reference: window.prompt('Reason for rejection (optional)') || '' };
    setBusy(r.refund_id);
    try {
      await mp.post(`/admin/refunds/${r.refund_id}/process`, { action, ...extra }, adminHdr());
      toast.success(action === 'refunded' ? 'Refunded to customer wallet' : 'Rejected');
      load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
    finally { setBusy(''); }
  };

  return (
    <div data-testid="admin-refunds">
      <div className="flex items-center gap-2 mb-1"><RotateCcw size={18} className="text-emerald-700" />
        <h2 className="text-lg font-extrabold text-stone-900">Refund requests</h2></div>
      <p className="text-sm text-stone-500">Approve to credit the customer's wallet, or reject.</p>
      <div className="flex gap-2 mt-4 flex-wrap">
        {['pending', 'refunded', 'rejected', ''].map((s) => (
          <button key={s || 'all'} onClick={() => setFilter(s)} data-testid={`rfilter-${s || 'all'}`}
            className={`text-xs font-bold rounded-full px-4 py-2 ${filter === s ? 'bg-emerald-700 text-white' : 'bg-white border border-stone-200'}`}>{s ? fmtStatus(s) : 'All'}</button>
        ))}
      </div>
      <div className="mt-5 space-y-3" data-testid="refund-list">
        {rows.length === 0 && <p className="text-sm text-stone-400 text-center py-10">No refund requests in this view.</p>}
        {rows.map((r) => (
          <div key={r.refund_id} className="bg-white rounded-2xl border border-stone-200 p-5 flex flex-wrap items-center justify-between gap-3" data-testid={`refund-${r.refund_id}`}>
            <div className="min-w-0">
              <p className="font-bold text-stone-900 text-sm">{r.customer_name} <span className="text-stone-400 font-normal">· {r.booking_id}</span></p>
              <p className="text-xs text-stone-500">{r.module} • {new Date(r.at).toLocaleString('en-IN')}{r.reason ? ` • ${r.reason}` : ''}</p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-lg font-extrabold text-stone-900">₹{Number(r.amount).toFixed(2)}</span>
              <span className={`text-[11px] font-bold rounded-full px-2.5 py-1 ${statusColor(r.status)}`}>{fmtStatus(r.status)}</span>
              {r.status === 'pending' && (
                <>
                  <button disabled={busy === r.refund_id} onClick={() => process(r, 'refunded')} data-testid={`rpay-${r.refund_id}`}
                    className="inline-flex items-center gap-1 bg-emerald-700 hover:bg-emerald-800 disabled:opacity-50 text-white text-xs font-bold rounded-full px-3 py-1.5"><CheckCircle2 size={13} /> Refund to wallet</button>
                  <button disabled={busy === r.refund_id} onClick={() => process(r, 'rejected')} data-testid={`rreject-${r.refund_id}`}
                    className="inline-flex items-center gap-1 border border-rose-300 text-rose-600 text-xs font-bold rounded-full px-3 py-1.5"><XCircle size={13} /> Reject</button>
                </>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

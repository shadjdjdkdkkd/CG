import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { X, Clock, Loader2, CheckCircle2, AlertTriangle, RefreshCw } from 'lucide-react';

const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

const STATUS_STYLES = {
  done: 'bg-emerald-100 text-emerald-700',
  running: 'bg-blue-100 text-blue-700',
  cancelling: 'bg-amber-100 text-amber-700',
  cancelled: 'bg-gray-200 text-gray-600',
  failed: 'bg-red-100 text-red-700',
};

// Shows previously-run bulk generation batches: what completed, what's pending,
// and the products created in each (so already-generated products are findable).
export const BulkHistoryModal = ({ headers, onClose }) => {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(null);
  const [cancelling, setCancelling] = useState(null);

  const load = () => {
    setLoading(true);
    axios.get(`${API}/admin/ai/bulk-generate-history`, { headers })
      .then((r) => setJobs(r.data?.jobs || []))
      .catch(() => setJobs([]))
      .finally(() => setLoading(false));
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  const cancelJob = async (e, j) => {
    e.stopPropagation();
    if (!window.confirm(`Cancel "${j.job_id}"? Products already created are kept.`)) return;
    setCancelling(j.job_id);
    try {
      await axios.post(`${API}/admin/ai/bulk-generate-job/${j.job_id}/cancel`, {}, { headers });
      // Mark locally right away so it stops showing as running
      setJobs(prev => prev.map(x => x.job_id === j.job_id ? { ...x, status: 'cancelled' } : x));
    } catch {
      alert('Could not cancel this job');
    } finally {
      setCancelling(null);
      load();
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 z-[60] flex items-start justify-center p-4 overflow-y-auto" data-testid="bulk-history-modal">
      <div className="bg-white rounded-2xl w-full max-w-2xl my-8 shadow-xl">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 sticky top-0 bg-white rounded-t-2xl">
          <div className="flex items-center gap-2">
            <span className="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center"><Clock size={16} className="text-indigo-600" /></span>
            <h3 className="font-bold text-gray-900 text-sm">Bulk Generation History</h3>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={load} className="flex items-center gap-1 text-xs font-semibold text-gray-600 hover:text-indigo-700" data-testid="bulk-history-refresh"><RefreshCw size={13} /> Refresh</button>
            <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg" data-testid="bulk-history-close"><X size={18} className="text-gray-500" /></button>
          </div>
        </div>

        <div className="p-5">
          {loading ? (
            <div className="py-14 text-center"><Loader2 size={26} className="mx-auto animate-spin text-indigo-600" /></div>
          ) : jobs.length === 0 ? (
            <p className="text-sm text-gray-400 text-center py-14">No bulk generation batches yet.</p>
          ) : (
            <div className="space-y-3">
              {jobs.map((j) => (
                <div key={j.job_id} className="rounded-xl border border-gray-200" data-testid={`bulk-history-job-${j.job_id}`}>
                  <button onClick={() => setOpen(open === j.job_id ? null : j.job_id)} className="w-full flex items-center justify-between gap-3 p-3 text-left">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`text-[10px] font-bold uppercase rounded-full px-2 py-0.5 ${STATUS_STYLES[j.status] || 'bg-gray-100 text-gray-600'}`}>{j.status}</span>
                        <span className="text-xs text-gray-500">{j.created_at ? new Date(j.created_at).toLocaleString() : ''}</span>
                      </div>
                      <p className="text-sm font-semibold text-gray-800 mt-1">
                        <span className="text-emerald-600">{j.done} done</span> · <span className="text-amber-600">{j.pending} pending</span>{j.failed ? <> · <span className="text-red-600">{j.failed} failed</span></> : null} <span className="text-gray-400">of {j.total}</span>
                      </p>
                    </div>
                    <div className="flex flex-col items-end gap-2 shrink-0">
                      <div className="w-24">
                        <div className="h-1.5 rounded-full bg-gray-100 overflow-hidden">
                          <div className="h-full bg-emerald-500" style={{ width: `${j.total ? Math.round((j.done / j.total) * 100) : 0}%` }} />
                        </div>
                      </div>
                      {(j.status === 'running' || j.status === 'cancelling' || j.status === 'queued') && (
                        <button
                          type="button"
                          onClick={(e) => cancelJob(e, j)}
                          disabled={cancelling === j.job_id}
                          className="flex items-center gap-1 px-2.5 py-1 rounded-lg border border-red-200 text-red-600 hover:bg-red-50 text-[11px] font-bold disabled:opacity-50"
                          data-testid={`bulk-history-cancel-${j.job_id}`}
                        >
                          {cancelling === j.job_id ? <Loader2 size={11} className="animate-spin" /> : <X size={11} />}
                          {cancelling === j.job_id ? 'Cancelling…' : 'Cancel'}
                        </button>
                      )}
                    </div>
                  </button>
                  {open === j.job_id && (
                    <div className="px-3 pb-3 border-t border-gray-100 pt-2 space-y-1.5">
                      {(j.created || []).map((c, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs text-gray-700" data-testid={`bulk-history-created-${i}`}>
                          <CheckCircle2 size={13} className="text-emerald-500 shrink-0" />
                          {c.slug ? <a href={`/product/${c.slug}`} target="_blank" rel="noreferrer" className="hover:underline truncate">{c.name}</a> : <span className="truncate">{c.name}</span>}
                        </div>
                      ))}
                      {(j.errors || []).map((e, i) => (
                        <div key={`e${i}`} className="flex items-start gap-2 text-xs text-red-600" data-testid={`bulk-history-error-${i}`}>
                          <AlertTriangle size={13} className="shrink-0 mt-0.5" /> <span className="truncate">{e.name}: {e.error}</span>
                        </div>
                      ))}
                      {!(j.created || []).length && !(j.errors || []).length && <p className="text-xs text-gray-400">No items recorded.</p>}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default BulkHistoryModal;

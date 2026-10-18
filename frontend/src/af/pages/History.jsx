import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { api } from "@/af/lib/api";
import { PageHeader, PlatformBadge } from "@/af/components/Layout";

export default function History() {
  const [items, setItems] = useState([]);
  const load = () => api.get("/history").then((r) => setItems(r.data));
  useEffect(() => { load(); }, []);
  return (
    <div>
      <PageHeader kicker="Audit log" title="Fill history">
        <button data-testid="history-clear-button" onClick={async () => { await api.delete("/history"); load(); }} className="inline-flex items-center gap-2 px-4 py-2 rounded-full border border-[#1F2937] text-sm text-slate-400 hover:text-red-400 transition-colors"><Trash2 className="w-4 h-4" />Clear</button>
      </PageHeader>
      <div className="rounded-xl border border-[#1F2937] bg-[#111827] overflow-x-auto" data-testid="history-log-table">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-[10px] uppercase tracking-widest text-slate-500 border-b border-[#1F2937]">
            <th className="px-6 py-4">When</th><th className="px-6 py-4">Platform</th><th className="px-6 py-4">Product</th><th className="px-6 py-4">Page</th><th className="px-6 py-4">Filled</th><th className="px-6 py-4">Source</th>
          </tr></thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan={6} className="px-6 py-12 text-center text-slate-400">No fills yet.</td></tr>}
            {items.map((h) => (
              <tr key={h.id} className="border-b border-[#1F2937] last:border-0" data-testid={`history-row-${h.id}`}>
                <td className="px-6 py-4 text-xs text-slate-400 whitespace-nowrap">{new Date(h.created_at).toLocaleString()}</td>
                <td className="px-6 py-4"><PlatformBadge platform={h.platform} /></td>
                <td className="px-6 py-4">{h.product_name}</td>
                <td className="px-6 py-4 font-mono text-xs text-slate-500 max-w-xs truncate">{h.page_key}</td>
                <td className="px-6 py-4 font-mono">{h.filled_count}/{h.field_count}</td>
                <td className="px-6 py-4 text-xs">{h.cached ? <span className="text-slate-400">saved answers</span> : <span className="text-emerald-400">AI generated</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

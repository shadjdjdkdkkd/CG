import { useEffect, useState } from "react";
import { Trash2, ExternalLink } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/af/lib/api";
import { PageHeader, PlatformBadge } from "@/af/components/Layout";

export default function Formats() {
  const [items, setItems] = useState([]);
  const [tab, setTab] = useState("all");
  const [open, setOpen] = useState(null);
  const load = () => api.get("/templates").then((r) => setItems(r.data));
  useEffect(() => { load(); }, []);
  const del = async (id) => { await api.delete(`/templates/${id}`); toast.success("Format deleted"); load(); };
  const shown = items.filter((t) => tab === "all" || t.platform === tab);

  return (
    <div>
      <PageHeader kicker="Auto-saved after first fill" title="Saved page formats" />
      <div className="flex gap-2 mb-6">
        {["all", "amazon", "flipkart", "myntra", "meesho", "nykaa", "instamart", "jiomart", "ajio", "blinkit", "zepto", "tata1mg", "other"].map((t) => (
          <button key={t} data-testid={`${t}-template-tab`} onClick={() => setTab(t)} className={`px-4 py-2 rounded-full text-sm capitalize border transition-colors ${tab === t ? "border-emerald-500 text-emerald-300 bg-emerald-500/10" : "border-[#1F2937] text-slate-400 hover:text-white"}`}>{t}</button>
        ))}
      </div>
      {shown.length === 0 && <div className="p-12 rounded-xl border border-dashed border-[#1F2937] text-center text-slate-400" data-testid="formats-empty">No formats yet. Fill a seller page once with the extension (or the playground) and its format is saved here.</div>}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {shown.map((t) => (
          <div key={t.id} data-testid={`template-card-${t.id}`} className="p-6 rounded-xl bg-[#111827] border border-[#1F2937] hover:border-slate-600 transition-colors">
            <div className="flex justify-between items-start gap-4">
              <div className="min-w-0">
                <PlatformBadge platform={t.platform} />
                <h3 className="font-medium mt-3 truncate">{t.name}</h3>
                <p className="font-mono text-xs text-slate-500 truncate mt-1">{t.page_key}</p>
              </div>
              <div className="flex gap-1">
                {t.url?.startsWith("http") && <a href={t.url} target="_blank" rel="noreferrer" data-testid={`template-open-${t.id}`} className="p-2 rounded-md hover:bg-white/5 text-slate-400"><ExternalLink className="w-4 h-4" /></a>}
                <button data-testid={`template-delete-${t.id}`} onClick={() => del(t.id)} className="p-2 rounded-md hover:bg-red-500/10 text-slate-400 hover:text-red-400 transition-colors"><Trash2 className="w-4 h-4" /></button>
              </div>
            </div>
            <div className="flex gap-6 mt-5 text-sm">
              <div><span className="font-display text-2xl font-bold">{t.fields.length}</span> <span className="text-slate-400 text-xs">fields</span></div>
              <div><span className="font-display text-2xl font-bold">{t.fill_count}</span> <span className="text-slate-400 text-xs">fills</span></div>
              <div><span className="font-display text-2xl font-bold">{Object.keys(t.reference_values || {}).length}</span> <span className="text-slate-400 text-xs">learned</span></div>
            </div>
            <button data-testid={`template-toggle-fields-${t.id}`} onClick={() => setOpen(open === t.id ? null : t.id)} className="mt-4 text-xs text-emerald-400 hover:underline">{open === t.id ? "Hide fields" : "Show fields"}</button>
            {open === t.id && (
              <div className="mt-3 max-h-64 overflow-auto space-y-1">
                {t.fields.map((f) => (
                  <div key={f.key} className="flex justify-between gap-3 text-xs py-1.5 border-b border-[#1F2937]" data-testid={`template-field-${f.key}`}>
                    <span className="truncate">{f.section && <span className="text-slate-600 mr-2">[{f.section}]</span>}{f.label || f.placeholder || f.key}</span>
                    <span className="font-mono text-slate-500 shrink-0" title={(f.options || []).join(", ")}>{f.options?.length ? `dropdown · ${f.options.length} options` : f.tag === "select" ? "select" : f.type}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

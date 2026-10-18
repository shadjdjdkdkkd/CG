import { useEffect, useState } from "react";
import { toast } from "sonner";
import { api, errMsg } from "@/af/lib/api";
import { PageHeader, PlatformBadge } from "@/af/components/Layout";

const PLATFORMS = ["amazon", "flipkart", "myntra", "meesho", "nykaa", "jiomart", "ajio", "tata1mg"];
const FIELDS = [
  ["title", "Sample product title / name", "Herbveda Onion Hair Oil for Hair Growth | Red Onion & Bhringraj | Controls Hair Fall | 200 ml", 2],
  ["bullets", "Sample bullet points / highlights", "HAIR FALL CONTROL: ...\nNATURAL INGREDIENTS: ...", 4],
  ["description", "Sample description", "A short paragraph in the tone you like…", 3],
];
const inputCls = "w-full bg-[#0B1120] border border-[#1F2937] rounded-md px-3 py-2 text-sm focus:outline-none focus:border-emerald-500 transition-colors";

export default function Styles() {
  const [settings, setSettings] = useState(null);
  const [samples, setSamples] = useState({});
  useEffect(() => { api.get("/settings").then((r) => { setSettings(r.data); setSamples(r.data.style_samples || {}); }); }, []);
  const set = (p, k, v) => setSamples({ ...samples, [p]: { ...(samples[p] || {}), [k]: v } });

  const save = async (p) => {
    try {
      const { data } = await api.put("/settings", { ...settings, style_samples: samples });
      setSettings(data);
      toast.success(`${p} style saved — AI will replicate it`);
    } catch (e) { toast.error(errMsg(e)); }
  };

  if (!settings) return null;
  return (
    <div>
      <PageHeader kicker="Style replication" title="Writing style per platform" />
      <p className="text-slate-400 -mt-6 mb-10 max-w-2xl">Paste one sample listing you like for each marketplace. AI copies its pattern — word order, separators, capitalisation, length and tone — but with each product's own facts. Leave a platform empty to use the default style.</p>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {PLATFORMS.map((p) => (
          <div key={p} className="p-6 rounded-xl bg-[#111827] border border-[#1F2937] space-y-4" data-testid={`style-card-${p}`}>
            <div className="flex justify-between items-center"><PlatformBadge platform={p} />{samples[p]?.title && <span className="text-[11px] text-emerald-400">custom style active</span>}</div>
            {FIELDS.map(([k, label, ph, rows]) => (
              <div key={k}>
                <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-400 mb-1.5">{label}</label>
                <textarea data-testid={`style-${p}-${k}-input`} rows={rows} className={inputCls} placeholder={ph} value={samples[p]?.[k] || ""} onChange={(e) => set(p, k, e.target.value)} />
              </div>
            ))}
            <button data-testid={`style-${p}-save-button`} onClick={() => save(p)} className="px-5 py-2 rounded-full bg-emerald-500 text-[#04140D] text-sm font-semibold hover:bg-emerald-400 transition-colors">Save {p} style</button>
          </div>
        ))}
      </div>
    </div>
  );
}

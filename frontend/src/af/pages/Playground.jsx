import { useEffect, useRef, useState } from "react";
import { Sparkles, ScanLine, Loader2, CheckCircle2, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { api, errMsg } from "@/af/lib/api";
import { afScan, afFill } from "@/af/lib/formEngine";
import { PageHeader } from "@/af/components/Layout";
import { AmazonForm, FlipkartForm } from "@/af/components/MockForms";

const PLATFORMS = { amazon: { root: "#amazon-mock", key: "amazon:playground/add-product", title: "Amazon Seller Central - Add a Product" }, flipkart: { root: "#flipkart-mock", key: "flipkart:playground/add-listing", title: "Flipkart Seller Hub - Add Single Listing" } };
const toInfo = (f) => ({ key: f.key, label: f.label, placeholder: f.placeholder, type: f.type, tag: f.tag, options: f.options, maxlength: f.maxlength });

export default function Playground() {
  const [platform, setPlatform] = useState("amazon");
  const [products, setProducts] = useState([]);
  const [pid, setPid] = useState("");
  const [fields, setFields] = useState([]);
  const [values, setValues] = useState({});
  const [template, setTemplate] = useState(null);
  const [busy, setBusy] = useState(false);
  const [regen, setRegen] = useState(false);
  const [autoStep, setAutoStep] = useState(true);
  const busyRef = useRef(false);
  const P = PLATFORMS[platform];

  useEffect(() => { api.get("/products").then((r) => { setProducts(r.data); if (r.data[0]) setPid(r.data[0].id); }); }, []);
  useEffect(() => {
    setFields([]); setValues({});
    api.get("/templates/lookup", { params: { page_key: P.key } }).then((r) => setTemplate(r.data.template));
  }, [platform, P.key]);

  const scan = () => { const f = afScan(P.root); setFields(f); toast.success(`Found ${f.length} fields`); return f; };

  const generateFill = async (onlyEmpty = false) => {
    if (!pid) return toast.error("Add a product first (Products page)");
    busyRef.current = true;
    setBusy(true);
    try {
      const f = afScan(P.root);
      setFields(f);
      const { data } = await api.post("/generate", { product_id: pid, platform, page_key: P.key, page_title: P.title, url: "playground", fields: f.map(toInfo), use_cache: !regen });
      const map = Object.fromEntries(f.map((x) => [x.af_id, data.values[x.key]]));
      const n = afFill(map, onlyEmpty).filled;
      setValues(data.values);
      const t = await api.post("/templates", { platform, page_key: P.key, url: "playground", name: P.title, fields: f.map(toInfo), reference_values: {} });
      setTemplate(t.data);
      toast.success(`${onlyEmpty ? "New step detected · " : ""}Filled ${n}/${f.length} fields${data.cached ? " from saved answers" : " with AI"} · format saved`);
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); busyRef.current = false; }
  };

  const fillRef = useRef(generateFill);
  fillRef.current = generateFill;
  useEffect(() => {
    const root = document.querySelector(P.root);
    if (!autoStep || !root) return;
    let t;
    const obs = new MutationObserver(() => {
      clearTimeout(t);
      t = setTimeout(() => {
        const fresh = root.querySelectorAll("input:not([data-af-id]), textarea:not([data-af-id]), select:not([data-af-id])");
        if (fresh.length && !busyRef.current && root.querySelector("[data-af-id]")) fillRef.current(true);
      }, 800);
    });
    obs.observe(root, { childList: true, subtree: true });
    return () => { obs.disconnect(); clearTimeout(t); };
  }, [autoStep, P.root, platform]);

  const reset = () => { document.querySelectorAll(`${P.root} input, ${P.root} textarea, ${P.root} select`).forEach((el) => (el.value = "")); setValues({}); };

  return (
    <div>
      <PageHeader kicker="Test without leaving the dashboard" title="Fill playground" />
      <div className="grid grid-cols-1 lg:grid-cols-[1fr_380px] gap-6">
        <div>
          <div className="flex gap-2 mb-4">
            {Object.keys(PLATFORMS).map((p) => (
              <button key={p} data-testid={`playground-${p}-tab`} onClick={() => setPlatform(p)} className={`px-4 py-2 rounded-full text-sm capitalize border transition-colors ${platform === p ? (p === "amazon" ? "border-amber-500 text-amber-300 bg-amber-500/10" : "border-blue-500 text-blue-300 bg-blue-500/10") : "border-[#1F2937] text-slate-400 hover:text-white"}`}>{p} page</button>
            ))}
          </div>
          {platform === "amazon" ? <AmazonForm /> : <FlipkartForm />}
        </div>
        <aside className="lg:sticky lg:top-6 h-fit p-5 rounded-xl bg-[#111827] border border-[#1F2937] space-y-4" data-testid="sidepanel-simulator">
          <div className="flex items-center justify-between">
            <span className="font-display font-bold">AutoFill <span className="text-emerald-400">AI</span></span>
            <span data-testid="format-status" className="text-[11px] text-slate-400 flex items-center gap-1">{template ? <><CheckCircle2 className="w-3 h-3 text-emerald-400" />Saved format · {template.fields.length} fields</> : "New page"}</span>
          </div>
          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-400 mb-1.5">Product</label>
            <select data-testid="playground-product-select" value={pid} onChange={(e) => setPid(e.target.value)} className="w-full bg-[#0B1120] border border-[#1F2937] rounded-md px-3 py-2 text-sm">
              {products.length === 0 && <option value="">No products — add one first</option>}
              {products.map((p) => <option key={p.id} value={p.id}>{p.name} · {p.size}</option>)}
            </select>
          </div>
          <button data-testid="ai-generate-fill-button" onClick={() => generateFill(false)} disabled={busy} className="w-full py-3.5 rounded-lg bg-emerald-500 text-[#04140D] font-semibold flex items-center justify-center gap-2 hover:bg-emerald-400 disabled:opacity-60 transition-colors">
            {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />}{busy ? "Reading & generating…" : "AI Generate & Fill"}
          </button>
          <div className="flex gap-2">
            <button data-testid="scan-page-fields-button" onClick={scan} className="flex-1 py-2 rounded-md border border-[#374151] text-sm flex items-center justify-center gap-2 hover:bg-white/5 transition-colors"><ScanLine className="w-4 h-4" />Scan fields</button>
            <button data-testid="reset-form-button" onClick={reset} className="flex-1 py-2 rounded-md border border-[#374151] text-sm flex items-center justify-center gap-2 hover:bg-white/5 transition-colors"><RotateCcw className="w-4 h-4" />Clear form</button>
          </div>
          <label className="flex items-center gap-2 text-xs text-slate-300"><input data-testid="auto-step-checkbox" type="checkbox" checked={autoStep} onChange={(e) => setAutoStep(e.target.checked)} />Auto-detect new form steps &amp; fill them</label>
          <label className="flex items-center gap-2 text-xs text-slate-300"><input data-testid="regenerate-checkbox" type="checkbox" checked={regen} onChange={(e) => setRegen(e.target.checked)} />Regenerate (ignore saved answers)</label>
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 mb-2">Detected fields ({fields.length})</p>
            <div className="max-h-[420px] overflow-auto space-y-1.5" data-testid="detected-fields-list">
              {fields.map((f) => (
                <div key={f.af_id} className="p-2 rounded border border-[#1F2937] text-xs">
                  <div className="text-slate-400">{f.label || f.key} {f.placeholder && <span className="font-mono text-slate-600">· {f.placeholder}</span>}</div>
                  {values[f.key] && <div className="text-emerald-300 mt-1 line-clamp-2">{values[f.key]}</div>}
                </div>
              ))}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

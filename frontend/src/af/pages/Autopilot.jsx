import { useEffect, useState } from "react";
import { Trash2, MousePointerClick, Circle, Play, Save, Navigation, Keyboard, ListChecks, ImageUp, CornerDownLeft, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { api, errMsg } from "@/af/lib/api";
import { PageHeader, PlatformBadge } from "@/af/components/Layout";
import { Switch } from "@/af/components/ui/switch";

const HOW = [
  { icon: Circle, t: "Just work normally", d: "With the extension on, list a product yourself: open the seller panel, go to Add product, upload photos, fill fields, press Save. Every page, click, value, dropdown pick, Enter press and upload is recorded." },
  { icon: Save, t: "AI learns why", d: "When you press Save / Submit, AI writes the reason for each step, removes accidental clicks and saves the optimised path." },
  { icon: Play, t: "Auto-fill switches on", d: "Once a platform reaches 100% you are asked before full auto-fill is enabled. Photos are uploaded straight from the product link." },
];
const MILESTONES = { start: "Seller panel opened", add_page: "Add-product page reached", images: "Photo upload seen", fields: "Fields filled by you", save: "Saved / submitted" };
const STEP_ICON = { navigate: Navigation, input: Keyboard, select: ListChecks, upload: ImageUp, enter: CornerDownLeft, click: MousePointerClick };

const stepText = (s) => {
  const t = s.type || "click";
  if (t === "navigate") return `Opened ${s.text || s.page_key}`;
  if (t === "input") return `Typed in ${s.label || s.ident || "field"}${s.value ? `: ${s.value}` : ""}`;
  if (t === "select") return `Picked "${s.text || s.value}"${s.label ? ` in ${s.label}` : ""}`;
  if (t === "enter") return `Pressed Enter in ${s.label || s.ident}`;
  if (t === "upload") return `Uploaded photos (${s.text})`;
  return `Clicked "${s.text || s.aria || s.elem_id}"`;
};

const LearningCard = ({ l, onChange }) => {
  const toggle = async (on) => {
    try { await api.post(`/learning/${l.platform}/autofill`, { enabled: on }); toast.success(on ? `Auto-fill ON for ${l.platform}` : "Auto-fill off"); onChange(); } catch (e) { toast.error(errMsg(e)); }
  };
  const reset = async () => {
    try { await api.delete(`/learning/${l.platform}`); toast.success("Learning reset"); onChange(); } catch (e) { toast.error(errMsg(e)); }
  };
  return (
    <div className="p-6 rounded-xl bg-[#111827] border border-[#1F2937] fade-up" data-testid={`learning-card-${l.platform}`}>
      <div className="flex items-center justify-between gap-3">
        <PlatformBadge platform={l.platform} />
        <span className="font-mono text-sm text-emerald-400" data-testid={`learning-progress-${l.platform}`}>{l.progress}%</span>
      </div>
      <div className="h-1.5 mt-4 rounded-full bg-[#1F2937] overflow-hidden"><div className="h-full bg-emerald-500 transition-[width] duration-500" style={{ width: `${l.progress}%` }} /></div>
      <div className="flex flex-wrap gap-1.5 mt-4">
        {Object.entries(MILESTONES).map(([k, t]) => (
          <span key={k} data-testid={`learning-${l.platform}-${k}`} className={`text-[11px] px-2 py-0.5 rounded-full border ${l.milestones[k] ? "border-emerald-500/50 text-emerald-300 bg-emerald-500/10" : "border-[#374151] text-slate-500"}`}>{t}</span>
        ))}
      </div>
      {l.journey_summary && <p className="text-xs text-slate-400 mt-4 leading-relaxed">{l.journey_summary}</p>}
      <div className="flex items-center justify-between mt-5 pt-4 border-t border-[#1F2937]">
        <label className="flex items-center gap-3 text-sm">
          <Switch data-testid={`learning-autofill-switch-${l.platform}`} checked={l.autofill_enabled} disabled={!l.complete && !l.autofill_enabled} onCheckedChange={toggle} />
          {l.complete ? "Full auto-fill" : "Auto-fill unlocks at 100%"}
        </label>
        <button data-testid={`learning-reset-${l.platform}`} onClick={reset} className="p-2 rounded-md text-slate-400 hover:text-amber-300 hover:bg-amber-500/10 transition-colors" title="Reset learning"><RotateCcw className="w-4 h-4" /></button>
      </div>
    </div>
  );
};

export default function Autopilot() {
  const [items, setItems] = useState([]);
  const [learning, setLearning] = useState([]);
  const load = () => {
    api.get("/recordings").then((r) => setItems(r.data));
    api.get("/learning").then((r) => setLearning(r.data));
  };
  useEffect(() => { load(); }, []);
  const del = async (id) => { try { await api.delete(`/recordings/${id}`); toast.success("Recording deleted"); load(); } catch (e) { toast.error(errMsg(e)); } };
  const rename = async (r, el) => {
    const name = el.value.trim();
    if (!name) { el.value = r.name; return; }
    if (name === r.name) return;
    try { await api.put(`/recordings/${r.id}`, { ...r, name }); toast.success("Renamed"); load(); } catch (e) { toast.error(errMsg(e)); }
  };

  return (
    <div>
      <PageHeader kicker="Amazon · Flipkart · Myntra · Meesho" title="Autopilot" />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-10">
        {HOW.map(({ icon: Icon, t, d }, i) => (
          <div key={t} className="fade-up p-6 rounded-xl border border-[#1F2937] bg-[#0B1120]" style={{ animationDelay: `${i * 70}ms` }}>
            <Icon className="w-5 h-5 text-emerald-400 mb-4" /><h3 className="font-medium mb-2">{t}</h3><p className="text-sm text-slate-400 leading-relaxed">{d}</p>
          </div>
        ))}
      </div>
      <h2 className="text-lg font-medium mb-4">Learning progress</h2>
      {learning.length === 0 && <div className="p-8 mb-10 rounded-xl border border-dashed border-[#1F2937] text-sm text-slate-400" data-testid="learning-empty">Nothing learned yet. Turn the extension on and list one product manually on any marketplace.</div>}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4 mb-12">
        {learning.map((l) => <LearningCard key={l.platform} l={l} onChange={load} />)}
      </div>
      <h2 className="text-lg font-medium mb-4">Recorded flows</h2>
      {items.length === 0 && <div className="p-12 rounded-xl border border-dashed border-[#1F2937] text-center text-slate-400" data-testid="autopilot-empty">No autopilot recorded yet. Record one from the Chrome extension side panel.</div>}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {items.map((r) => (
          <div key={r.id} className="p-6 rounded-xl bg-[#111827] border border-[#1F2937]" data-testid={`recording-card-${r.id}`}>
            <div className="flex justify-between items-start gap-3">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2"><PlatformBadge platform={r.platform} />{r.optimized && <span className="text-[10px] uppercase tracking-widest text-emerald-400" data-testid={`recording-optimized-${r.id}`}>AI optimised</span>}</div>
                <input data-testid={`recording-name-${r.id}`} defaultValue={r.name} onBlur={(e) => rename(r, e.target)} className="mt-3 w-full bg-transparent font-medium focus:outline-none border-b border-transparent focus:border-emerald-500" />
                <p className="font-mono text-xs text-slate-500 truncate mt-1">{r.start_url}</p>
              </div>
              <button data-testid={`recording-delete-${r.id}`} onClick={() => del(r.id)} className="p-2 rounded-md hover:bg-red-500/10 text-slate-400 hover:text-red-400 transition-colors"><Trash2 className="w-4 h-4" /></button>
            </div>
            {r.summary && <p className="text-xs text-slate-400 mt-4 leading-relaxed" data-testid={`recording-summary-${r.id}`}>{r.summary}</p>}
            <ol className="mt-5 space-y-2 max-h-72 overflow-auto pr-2">
              {r.steps.map((s, i) => {
                const Icon = STEP_ICON[s.type || "click"] || MousePointerClick;
                return (
                  <li key={i} className="flex items-start gap-3 text-xs">
                    <span className="font-mono text-slate-600 w-5 shrink-0">{i + 1}</span><Icon className="w-3 h-3 mt-0.5 text-emerald-400 shrink-0" />
                    <span className="min-w-0"><span className="block truncate">{stepText(s)}</span>{s.reason && <span className="block text-slate-500">{s.reason}</span>}</span>
                  </li>
                );
              })}
            </ol>
            <p className="text-xs text-slate-500 mt-4">Ran {r.run_count} {r.run_count === 1 ? "time" : "times"}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

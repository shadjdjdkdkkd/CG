import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Package, LayoutTemplate, Zap, ArrowRight, Puzzle, ScanLine, Sparkles, Save, Bot } from "lucide-react";
import { api } from "@/af/lib/api";
import { PageHeader } from "@/af/components/Layout";

const STEPS = [
  { icon: Package, t: "Add a product", d: "Name, brand, ingredients, bottle size, price. Save brand & size as defaults." },
  { icon: ScanLine, t: "Open the seller page", d: "Go to Amazon / Flipkart 'Add product' yourself. The side panel reads every field + placeholder." },
  { icon: Sparkles, t: "Click AI Generate & Fill", d: "AI writes every answer and fills the whole form instantly." },
  { icon: Save, t: "Format auto-saved", d: "Next time: one click (or auto mode) fills that page for any product." },
];

export default function Dashboard() {
  const [s, setS] = useState(null);
  useEffect(() => { api.get("/stats").then((r) => setS(r.data)); }, []);
  const cards = [
    { label: "Products", v: s?.products, icon: Package, to: "/products", id: "stat-products" },
    { label: "Saved formats", v: s?.templates, icon: LayoutTemplate, to: "/formats", id: "stat-templates" },
    { label: "AI fills run", v: s?.fills, icon: Zap, to: "/history", id: "stat-fills" },
    { label: "Autopilots", v: s?.recordings, icon: Bot, to: "/autopilot", id: "stat-autopilots" },
  ];
  return (
    <div>
      <PageHeader kicker="Listing automation" title={<>Fill Amazon, Flipkart, Myntra & Meesho<br /><span className="text-slate-500 font-light">in one click.</span></>}>
        <Link to="/extension" data-testid="hero-get-extension-btn" className="inline-flex items-center gap-2 px-5 py-3 rounded-full bg-emerald-500 text-[#04140D] font-semibold hover:bg-emerald-400 transition-colors"><Puzzle className="w-4 h-4" />Get the extension</Link>
        <Link to="/playground" data-testid="hero-try-playground-btn" className="inline-flex items-center gap-2 px-5 py-3 rounded-full border border-slate-700 hover:border-slate-500 transition-colors">Try playground <ArrowRight className="w-4 h-4" /></Link>
      </PageHeader>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-12">
        {cards.map(({ label, v, icon: Icon, to, id }, i) => (
          <Link key={id} to={to} data-testid={id} style={{ animationDelay: `${i * 80}ms` }} className="fade-up group p-8 rounded-xl bg-[#111827] border border-[#1F2937] hover:border-emerald-500/40 transition-colors">
            <Icon className="w-5 h-5 text-slate-500 group-hover:text-emerald-400 transition-colors" />
            <div className="font-display text-5xl font-bold mt-6">{v ?? "–"}</div>
            <div className="text-xs uppercase tracking-widest text-slate-400 mt-2">{label}</div>
          </Link>
        ))}
      </div>
      <h2 className="font-display text-2xl font-semibold tracking-tight mb-6">How it works</h2>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {STEPS.map(({ icon: Icon, t, d }, i) => (
          <div key={t} className="fade-up p-6 rounded-xl border border-[#1F2937] bg-[#0B1120]" style={{ animationDelay: `${200 + i * 80}ms` }}>
            <div className="flex items-center justify-between mb-5"><Icon className="w-5 h-5 text-emerald-400" /><span className="font-mono text-xs text-slate-600">0{i + 1}</span></div>
            <h3 className="font-medium mb-2">{t}</h3>
            <p className="text-sm text-slate-400 leading-relaxed">{d}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

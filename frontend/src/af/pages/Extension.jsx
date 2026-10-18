import { Download, Chrome, FolderOpen, ToggleRight, MousePointerClick, Pin } from "lucide-react";
import { BACKEND_URL } from "@/af/lib/api";
import { PageHeader } from "@/af/components/Layout";

const STEPS = [
  { icon: Download, t: "Download & unzip", d: "Click the button above, then extract autofill-extension.zip to a folder." },
  { icon: Chrome, t: "Open chrome://extensions", d: "Paste it in the Chrome address bar." },
  { icon: ToggleRight, t: "Enable Developer mode", d: "Toggle in the top-right corner." },
  { icon: FolderOpen, t: "Load unpacked", d: "Select the extracted 'autofill-extension' folder." },
  { icon: Pin, t: "Pin the icon", d: "Pin 'AutoFill AI' from the puzzle menu for quick access." },
  { icon: MousePointerClick, t: "Open a seller page & click", d: "Go to Amazon / Flipkart add-product page, click the icon → side panel opens → AI Generate & Fill." },
];

export default function Extension() {
  const href = `${BACKEND_URL}/api/extension/download?api_url=${encodeURIComponent(BACKEND_URL)}`;
  return (
    <div>
      <PageHeader kicker="Chrome side panel" title="Install the extension">
        <a href={href} data-testid="download-extension-button" className="inline-flex items-center gap-2 px-6 py-3 rounded-full bg-emerald-500 text-[#04140D] font-semibold hover:bg-emerald-400 transition-colors"><Download className="w-4 h-4" />Download extension (.zip)</a>
      </PageHeader>
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-8">
        <ol className="lg:col-span-3 space-y-3">
          {STEPS.map(({ icon: Icon, t, d }, i) => (
            <li key={t} className="fade-up flex gap-5 p-5 rounded-xl border border-[#1F2937] bg-[#111827]" style={{ animationDelay: `${i * 60}ms` }}>
              <span className="font-mono text-xs text-slate-600 pt-1">0{i + 1}</span>
              <Icon className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
              <div><div className="font-medium">{t}</div><div className="text-sm text-slate-400 mt-1">{d}</div></div>
            </li>
          ))}
        </ol>
        <div className="lg:col-span-2 p-6 rounded-xl border border-[#1F2937] bg-[#0B1120] h-fit space-y-4 text-sm text-slate-300">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">Side panel features</p>
          {[
            "Reads every input, dropdown & text box with its label and placeholder",
            "AI Generate & Fill — writes and fills all answers in one click",
            "Format auto-saved per page after the first fill",
            "Auto mode — pages with a saved format fill themselves on load",
            "Auto-detect new form steps (Amazon multi-step) and fill only the new empty fields",
            "Autopilot — record your clicks once, replay with AI filling every step, for one or all products",
            "Works on Amazon, Flipkart, Myntra & Meesho; follows your saved writing style per platform",
            "Fill multiple pages — tick open Amazon/Flipkart tabs and fill all",
            "Learn page — saves your hand-edited values as a style reference",
            "Add products & set default brand / size right from the panel",
          ].map((x) => <div key={x} className="flex gap-3"><span className="w-1.5 h-1.5 rounded-full bg-emerald-500 mt-2 shrink-0" />{x}</div>)}
          <p className="text-xs text-slate-500 pt-2 border-t border-[#1F2937]">The extension talks to this dashboard: <span className="font-mono break-all">{BACKEND_URL}</span></p>
          <p className="text-[10px] font-semibold uppercase tracking-widest text-slate-400 pt-2">Practice pages (multi-step test forms)</p>
          <div className="flex flex-wrap gap-2">
            {["amazon", "flipkart", "meesho", "myntra", "generic"].map((m) => (
              <a key={m} href={`/mock/${m}.html`} target="_blank" rel="noreferrer" data-testid={`mock-page-link-${m}`} className="px-3 py-1.5 rounded-full border border-[#374151] text-xs capitalize hover:border-emerald-500 transition-colors">{m === "generic" ? "any website form" : m}</a>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

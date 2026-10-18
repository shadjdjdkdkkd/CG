import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { TOKEN_KEY } from "@/af/lib/api";
import { LayoutDashboard, Package, LayoutTemplate, FlaskConical, Puzzle, History, Zap, PenLine, Bot, UserRound, LogOut } from "lucide-react";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, id: "nav-dashboard-link" },
  { to: "/products", label: "Products", icon: Package, id: "nav-products-link" },
  { to: "/formats", label: "Saved Formats", icon: LayoutTemplate, id: "nav-templates-link" },
  { to: "/styles", label: "Writing Style", icon: PenLine, id: "nav-styles-link" },
  { to: "/autopilot", label: "Autopilot", icon: Bot, id: "nav-autopilot-link" },
  { to: "/playground", label: "Fill Playground", icon: FlaskConical, id: "nav-simulator-link" },
  { to: "/extension", label: "Chrome Extension", icon: Puzzle, id: "nav-extension-link" },
  { to: "/history", label: "Fill History", icon: History, id: "nav-history-link" },
  { to: "/account", label: "Account", icon: UserRound, id: "nav-account-link" },
];

export default function Layout() {
  const nav = useNavigate();
  const logout = () => { localStorage.removeItem(TOKEN_KEY); nav("/login"); };
  return (
    <div className="min-h-screen flex bg-[#090D16]">
      <aside className="w-64 shrink-0 border-r border-[#1F2937] bg-[#0B1120] hidden md:flex flex-col sticky top-0 h-screen">
        <div className="h-16 px-6 flex items-center gap-2 border-b border-[#1F2937]">
          <div className="w-8 h-8 rounded-md bg-emerald-500 grid place-items-center"><Zap className="w-4 h-4 text-[#04140D]" /></div>
          <span className="font-display text-lg font-bold tracking-tight">AutoFill<span className="text-emerald-400">AI</span></span>
        </div>
        <nav className="p-3 space-y-1 flex-1">
          {NAV.map(({ to, label, icon: Icon, id }) => (
            <NavLink key={to} to={to} end data-testid={id}
              className={({ isActive }) => `flex items-center gap-3 px-3 py-2.5 rounded-md text-sm transition-colors duration-150 ${isActive ? "bg-emerald-500/10 text-emerald-300 border border-emerald-500/20" : "text-slate-400 hover:text-white hover:bg-white/5 border border-transparent"}`}>
              <Icon className="w-4 h-4" />{label}
            </NavLink>
          ))}
        </nav>
        <button data-testid="logout-button" onClick={logout} className="mx-3 mb-1 flex items-center gap-3 px-3 py-2.5 rounded-md text-sm text-slate-400 hover:text-red-400 hover:bg-white/5 transition-colors"><LogOut className="w-4 h-4" />Log out</button>
        <div className="p-4 m-3 rounded-md border border-[#1F2937] text-xs text-slate-400 grid grid-cols-2 gap-2">
          {[["bg-amber-500", "Amazon"], ["bg-blue-600", "Flipkart"], ["bg-pink-500", "Myntra"], ["bg-fuchsia-600", "Meesho"]].map(([c, n]) => <span key={n}><span className={`inline-block w-2 h-2 rounded-full ${c} mr-2`} />{n}</span>)}
        </div>
      </aside>
      <div className="flex-1 min-w-0">
        <header className="md:hidden h-14 px-4 flex items-center gap-3 overflow-x-auto border-b border-[#1F2937] bg-[#0B1120]/80 backdrop-blur-xl sticky top-0 z-20">
          {NAV.map(({ to, label, id }) => (
            <NavLink key={to} to={to} end data-testid={`m-${id}`} className={({ isActive }) => `text-xs whitespace-nowrap ${isActive ? "text-emerald-300" : "text-slate-400"}`}>{label}</NavLink>
          ))}
        </header>
        <main className="grid-bg min-h-screen">
          <div className="max-w-7xl mx-auto p-6 md:p-10"><Outlet /></div>
        </main>
      </div>
    </div>
  );
}

export const PageHeader = ({ kicker, title, children }) => (
  <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 mb-10 fade-up">
    <div>
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-emerald-400 mb-2">{kicker}</p>
      <h1 className="font-display text-3xl sm:text-4xl lg:text-5xl font-bold tracking-tight">{title}</h1>
    </div>
    <div className="flex gap-2 flex-wrap">{children}</div>
  </div>
);

export const PlatformBadge = ({ platform }) => {
  const cls = { amazon: "bg-amber-500/15 text-amber-400", flipkart: "bg-blue-600/20 text-blue-300", myntra: "bg-pink-500/15 text-pink-400", meesho: "bg-fuchsia-600/20 text-fuchsia-300", nykaa: "bg-pink-600/20 text-pink-300", instamart: "bg-orange-500/15 text-orange-300", jiomart: "bg-sky-600/20 text-sky-300", ajio: "bg-slate-500/20 text-slate-200", blinkit: "bg-yellow-400/15 text-yellow-300", zepto: "bg-violet-600/20 text-violet-300", tata1mg: "bg-rose-500/15 text-rose-300" }[platform] || "bg-slate-700/40 text-slate-300";
  return <span className={`text-[10px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-full ${cls}`}>{platform}</span>;
};

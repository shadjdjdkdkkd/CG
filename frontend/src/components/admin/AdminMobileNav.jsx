import { useState, useEffect } from 'react';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import {
  Menu, X, LayoutDashboard, FileText, MapPin, Package, Sparkles, Globe, Phone,
  Star, Stethoscope, Users, Activity, Route, Gift, Shield, MessageSquare,
  Settings, LogOut, Upload, Warehouse, Percent,
} from 'lucide-react';

// One unified nav list — single source of truth (used by both desktop sidebar AND mobile drawer).
const NAV_ITEMS = [
  { to: '/admin/dashboard', label: 'Dashboard', icon: LayoutDashboard, color: 'green' },
  { to: '/admin/dermatologists', label: 'Dermatologist Manager', icon: Stethoscope, color: 'emerald', featured: true },
  { to: '/admin/partners', label: 'Service Partner Manager', icon: Users, color: 'cyan', featured: true },
  { to: '/admin/orders', label: 'Orders', icon: Package, color: 'amber' },
  { to: '/admin/warehouses', label: 'Warehouses', icon: Warehouse, color: 'emerald' },
  { to: '/admin/delivery-men', label: 'Delivery Men', icon: Users, color: 'emerald' },
  { to: '/admin/offers', label: 'Offers & Sale', icon: Percent, color: 'rose' },
  { to: '/admin/products', label: 'Products', icon: Package, color: 'green' },
  { to: '/admin/bulk-import', label: 'Bulk Import (Excel)', icon: Upload, color: 'indigo' },
  { to: '/admin/amazon-flipkart', label: 'Amazon & Flipkart Listing', icon: Package, color: 'amber', featured: true },
  { to: '/admin/master-tools', label: 'Master Tools', icon: Sparkles, color: 'emerald' },
  { to: '/admin/media-tools', label: 'Media, SEO & Splash', icon: Shield, color: 'purple' },
  { to: '/admin/reels', label: 'Influencer Reels', icon: Sparkles, color: 'rose' },
  { to: '/admin/concerns', label: 'Concerns & Categories', icon: Sparkles, color: 'pink' },
  { to: '/admin/niches', label: 'Niche Customization', icon: Settings, color: 'emerald' },
  { to: '/admin/categories-hub', label: 'Shop by Category Hub', icon: Sparkles, color: 'rose' },
  { to: '/admin/blogs', label: 'Blog Posts', icon: FileText, color: 'gray' },
  { to: '/admin/locations', label: 'Location Pages', icon: MapPin, color: 'gray' },
  { to: '/admin/ai-studio', label: 'AI Studio', icon: Sparkles, color: 'gray' },
  { to: '/admin/landing-pages', label: 'Landing Pages', icon: Globe, color: 'purple' },
  { to: '/admin/retention', label: 'Retention', icon: Phone, color: 'cyan' },
  { to: '/admin/reviews', label: 'Reviews', icon: Star, color: 'amber' },
  { to: '/admin/consultations', label: 'Consultations', icon: Stethoscope, color: 'gray' },
  { to: '/admin/routines', label: 'Routine Reports', icon: Sparkles, color: 'pink' },
  { to: '/admin/customers', label: 'Customers', icon: Users, color: 'blue' },
  { to: '/admin/live-visitors', label: 'Live Visitors', icon: Activity, color: 'green' },
  { to: '/admin/user-journey', label: 'User Journey', icon: Route, color: 'gray' },
  { to: '/admin/referrals', label: 'Referrals', icon: Gift, color: 'purple' },
  { to: '/admin/gift-cards', label: 'Gift Cards', icon: Gift, color: 'rose' },
  { to: '/admin/employees', label: 'Employees', icon: Shield, color: 'orange' },
  { to: '/admin/whatsapp', label: 'WhatsApp', icon: MessageSquare, color: 'green' },
  { to: '/admin/settings', label: 'Settings', icon: Settings, color: 'gray' },
];

const colorClass = (c) => ({
  green: 'text-green-600 hover:bg-green-50',
  amber: 'text-amber-600 hover:bg-amber-50',
  indigo: 'text-indigo-600 hover:bg-indigo-50',
  pink: 'text-pink-600 hover:bg-pink-50',
  emerald: 'text-emerald-600 hover:bg-emerald-50',
  rose: 'text-rose-600 hover:bg-rose-50',
  gray: 'text-gray-600 hover:bg-gray-50',
  purple: 'text-purple-600 hover:bg-purple-50',
  cyan: 'text-cyan-600 hover:bg-cyan-50',
  blue: 'text-blue-600 hover:bg-blue-50',
  orange: 'text-orange-600 hover:bg-orange-50',
}[c] || 'text-gray-600 hover:bg-gray-50');

const activeClass = (c) => ({
  green: 'bg-green-50 text-green-700',
  amber: 'bg-amber-50 text-amber-700',
  indigo: 'bg-indigo-50 text-indigo-700',
  pink: 'bg-pink-50 text-pink-700',
  emerald: 'bg-emerald-50 text-emerald-700',
  rose: 'bg-rose-50 text-rose-700',
  gray: 'bg-gray-100 text-gray-800',
  purple: 'bg-purple-50 text-purple-700',
  cyan: 'bg-cyan-50 text-cyan-700',
  blue: 'bg-blue-50 text-blue-700',
  orange: 'bg-orange-50 text-orange-700',
}[c] || 'bg-gray-100 text-gray-800');

const OWN_SIDEBAR = ['/admin/dashboard', '/admin/retention', '/admin/routines', '/admin/settings'];

export function AdminDesktopSidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  if (location.pathname === '/admin' || location.pathname === '/admin/' || OWN_SIDEBAR.includes(location.pathname)) return null;
  return (
    <>
      <aside className="hidden lg:flex lg:flex-col fixed left-0 top-0 w-64 h-full bg-white border-r border-gray-200 z-40" data-testid="admin-desktop-sidebar">
        <Link to="/admin/dashboard" className="p-6 block"><span className="text-xl font-bold text-green-600">Celesta Glow</span><span className="block text-sm text-gray-500">Admin Panel</span></Link>
        <nav className="flex-1 px-4 space-y-1 overflow-y-auto pb-4">
          {NAV_ITEMS.map((n) => {
            const Icon = n.icon;
            const active = location.pathname === n.to;
            return (
              <Link key={n.to} to={n.to} data-testid={`sidebar-${n.to.split('/').pop()}`}
                className={`flex items-center gap-3 px-4 py-2.5 rounded-xl text-sm ${n.featured ? 'font-bold ring-1 ring-emerald-200 bg-emerald-50/60 ' : ''}${active ? activeClass(n.color) : colorClass(n.color)}`}>
                <Icon size={18} /> {n.label}
              </Link>
            );
          })}
        </nav>
        <button onClick={() => { sessionStorage.removeItem('adminToken'); localStorage.removeItem('adminToken'); navigate('/admin'); }}
          className="m-4 flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm text-gray-600 hover:bg-gray-50" data-testid="sidebar-logout"><LogOut size={16} /> Sign out</button>
      </aside>
      <style>{`@media (min-width: 1024px) { [data-admin-content] { padding-left: 16rem; } }`}</style>
    </>
  );
}

export default function AdminMobileNav() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();

  // Auto-close drawer on route change
  useEffect(() => { setOpen(false); }, [location.pathname]);

  // Lock body scroll while drawer is open
  useEffect(() => {
    document.body.style.overflow = open ? 'hidden' : '';
    return () => { document.body.style.overflow = ''; };
  }, [open]);

  const handleLogout = () => {
    sessionStorage.removeItem('adminToken');
    navigate('/admin');
  };

  // Don't render the bar on the login page itself
  if (location.pathname === '/admin' || location.pathname === '/admin/') return null;

  return (
    <>
      {/* Top mobile bar — hidden on lg+ (desktop already has fixed sidebar) */}
      <div className="lg:hidden fixed top-0 left-0 right-0 z-50 bg-white border-b border-gray-200 px-4 h-14 flex items-center justify-between shadow-sm" data-testid="admin-mobile-topbar">
        <div className="flex items-center gap-3">
          <button
            onClick={() => setOpen(true)}
            className="p-2 -ml-2 rounded-lg hover:bg-gray-100 active:bg-gray-200"
            aria-label="Open menu"
            data-testid="admin-mobile-menu-btn"
          >
            <Menu size={22} className="text-gray-700" />
          </button>
          <Link to="/admin/dashboard" className="font-bold text-green-600 text-base">Celesta Glow</Link>
        </div>
        <button
          onClick={handleLogout}
          className="p-2 -mr-2 rounded-lg hover:bg-gray-100"
          aria-label="Sign out"
          data-testid="admin-mobile-logout"
        >
          <LogOut size={18} className="text-gray-600" />
        </button>
      </div>

      {/* Pad page top so content isn't hidden behind the bar */}
      <div className="lg:hidden h-14" aria-hidden="true" />

      {/* Slide-in drawer */}
      {open && (
        <div
          className="lg:hidden fixed inset-0 z-[60] bg-black/40 backdrop-blur-sm"
          onClick={() => setOpen(false)}
          data-testid="admin-mobile-drawer-overlay"
        >
          <aside
            onClick={(e) => e.stopPropagation()}
            className="absolute left-0 top-0 bottom-0 w-[82vw] max-w-[320px] bg-white shadow-2xl flex flex-col"
            data-testid="admin-mobile-drawer"
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 flex-shrink-0">
              <div>
                <h1 className="text-lg font-bold text-green-600">Celesta Glow</h1>
                <p className="text-xs text-gray-500">Admin Panel</p>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="p-2 rounded-lg hover:bg-gray-100"
                aria-label="Close menu"
                data-testid="admin-mobile-drawer-close"
              >
                <X size={20} className="text-gray-600" />
              </button>
            </div>

            <nav className="flex-1 overflow-y-auto px-3 py-3 space-y-0.5" data-testid="admin-mobile-nav-list">
              {NAV_ITEMS.map((it) => {
                const Icon = it.icon;
                const active = location.pathname.startsWith(it.to);
                return (
                  <Link
                    key={it.to}
                    to={it.to}
                    className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-colors ${active ? activeClass(it.color) : colorClass(it.color)}`}
                    data-testid={`mobile-nav-${it.to.replace('/admin/', '')}`}
                  >
                    <Icon size={18} />
                    <span className="flex-1">{it.label}</span>
                  </Link>
                );
              })}
            </nav>

            <div className="flex-shrink-0 px-3 py-3 border-t border-gray-100">
              <button
                onClick={handleLogout}
                className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-gray-50 hover:bg-gray-100 text-gray-700 rounded-xl text-sm font-medium"
                data-testid="admin-mobile-drawer-logout"
              >
                <LogOut size={16} /> Sign Out
              </button>
            </div>
          </aside>
        </div>
      )}
    </>
  );
}

import React, { useEffect, useState } from 'react';
import { Users, CalendarDays, LayoutGrid, Star, LifeBuoy, Settings, IndianRupee } from 'lucide-react';
import AdminMpCRM from './AdminMpCRM';
import AdminMpBookings from './AdminMpBookings';
import AdminSupport from './AdminSupport';
import MpSettings from '../../components/admin/MpSettings';
import MpReviews from '../../components/admin/MpReviews';
import MpCustomServices from '../../components/admin/MpCustomServices';
import { Wand2 } from 'lucide-react';
import HbCatalogManager from '../../components/admin/HbCatalogManager';
import MpWithdrawals from '../../components/admin/MpWithdrawals';
import AdminRefunds from '../../components/admin/AdminRefunds';
import MpUpdates from '../../components/admin/MpUpdates';
import { Megaphone, Wallet, RotateCcw } from 'lucide-react';
import { mp, adminHdr } from '../../utils/mpApi';

export const PlatformWallet = () => {
  const [w, setW] = useState(null);
  useEffect(() => { mp.get('/admin/platform-wallet', adminHdr()).then((r) => setW(r.data)).catch(() => {}); }, []);
  if (!w) return <div className="text-stone-400 text-sm p-4">Loading…</div>;
  return (
    <div className="space-y-4" data-testid="platform-wallet">
      <div className="bg-gradient-to-br from-emerald-700 to-teal-800 text-white rounded-3xl p-6">
        <p className="text-xs uppercase tracking-widest opacity-80">Celesta Glow platform earnings</p>
        <p className="text-4xl font-extrabold mt-1">₹{w.balance.toFixed(2)}</p>
        <p className="text-[11px] opacity-70 mt-1">Provider commission + customer markup from completed bookings (doctors & partners).</p>
      </div>
      {w.summary && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="platform-summary">
          {[['Customer commission', w.summary.customer_commission, 'customer'], ['Partner commission', w.summary.partner_commission, 'partner'],
            ['Doctor commission', w.summary.doctor_commission, 'doctor'], ['Paid out to providers', w.summary.provider_payout, 'payout']].map(([l, v, k]) => (
            <div key={k} className="bg-white rounded-2xl border border-stone-200 p-4" data-testid={`summary-${k}`}>
              <p className="text-[10px] font-bold uppercase tracking-wide text-stone-400">{l}</p>
              <p className="text-xl font-extrabold text-stone-900 mt-1">₹{Number(v || 0).toLocaleString('en-IN')}</p>
            </div>
          ))}
          <p className="col-span-full text-[11px] text-stone-400">{w.summary.bookings} settled bookings • customers paid ₹{Number(w.summary.customer_paid || 0).toLocaleString('en-IN')} in total</p>
        </div>
      )}
      <div className="bg-white rounded-2xl border border-stone-200 p-4">
        <p className="font-bold text-stone-800 text-sm mb-2">Ledger</p>
        {w.ledger.length === 0 && <p className="text-xs text-stone-400">No earnings yet — entries appear after OTP-verified completions.</p>}
        {w.ledger.map((l) => (
          <div key={l.entry_id} className="flex justify-between text-xs py-2 border-b border-stone-50 last:border-0">
            <span className="text-stone-600">{l.ref}{l.booking_id ? ` • ${l.booking_id}` : ''}
              {l.meta && (
                <span className="flex flex-wrap gap-1.5 mt-1">
                  <span className="text-[10px] bg-stone-100 rounded-full px-2 py-0.5">Customer paid ₹{l.meta.customer_paid}</span>
                  <span className="text-[10px] bg-sky-50 text-sky-800 rounded-full px-2 py-0.5" data-testid="row-customer-commission">Customer commission ₹{l.meta.customer_commission}</span>
                  <span className="text-[10px] bg-amber-50 text-amber-800 rounded-full px-2 py-0.5" data-testid="row-partner-commission">{String(l.booking_id || '').startsWith('CG-C') ? 'Doctor' : 'Partner'} commission {l.meta.commission_pct}% ₹{l.meta.partner_commission}</span>
                  <span className="text-[10px] bg-emerald-50 text-emerald-800 rounded-full px-2 py-0.5">Provider got ₹{l.meta.you_earn}</span>
                </span>
              )}
              <span className="block text-[10px] text-stone-400">{new Date(l.at).toLocaleString('en-IN')}</span></span>
            <span className={`font-extrabold ${l.type === 'credit' ? 'text-emerald-700' : 'text-rose-600'}`}>{l.type === 'credit' ? '+' : '−'}₹{l.amount}</span>
          </div>
        ))}
      </div>
    </div>
  );
};

const tabs = [
  ['partners', 'Partners & Applications', Users],
  ['hb', 'Service Catalog & Content', LayoutGrid],
  ['custom', 'Partner-created Services', Wand2],
  ['bookings', 'Home Service Bookings', CalendarDays],
  ['reviews', 'Reviews', Star],
  ['earnings', 'Platform Earnings', IndianRupee],
  ['withdrawals', 'Withdrawals', Wallet],
  ['refunds', 'Refunds', RotateCcw],
  ['support', 'Support Tickets', LifeBuoy],
  ['updates', 'Updates', Megaphone],
  ['settings', 'Settings', Settings],
];

const AdminPartnerHub = () => {
  const [tab, setTab] = useState('partners');
  return (
    <div className="p-4 sm:p-8 max-w-6xl mx-auto" data-testid="admin-partner-hub">
      <h1 className="text-2xl font-extrabold text-stone-900">Service Partner Manager</h1>
      <p className="text-sm text-stone-500">Partners, services, bookings, earnings and pricing.</p>
      <div className="flex gap-2 overflow-x-auto pb-2 mt-5 mb-6" data-testid="partner-hub-tabs">
        {tabs.map(([k, label, Icon]) => (
          <button key={k} onClick={() => setTab(k)} data-testid={`phub-${k}`}
            className={`px-4 py-2 rounded-full text-xs font-extrabold whitespace-nowrap inline-flex items-center gap-1.5 ${tab === k ? 'bg-emerald-700 text-white' : 'bg-white border border-stone-200 text-stone-600'}`}>
            <Icon size={13} /> {label}
          </button>
        ))}
      </div>
      {tab === 'partners' && <AdminMpCRM kind="partners" />}
      {tab === 'hb' && <HbCatalogManager />}
      {tab === 'custom' && <MpCustomServices />}
      {tab === 'bookings' && <AdminMpBookings fixedModule="home" />}
      {tab === 'reviews' && <MpReviews module="home" />}
      {tab === 'earnings' && <PlatformWallet />}
      {tab === 'withdrawals' && <MpWithdrawals ownerType="partner" />}
      {tab === 'refunds' && <AdminRefunds />}
      {tab === 'support' && <AdminSupport userType="partner" />}
      {tab === 'updates' && <MpUpdates module="service" />}
      {tab === 'settings' && <MpSettings module="service" />}
    </div>
  );
};

export default AdminPartnerHub;

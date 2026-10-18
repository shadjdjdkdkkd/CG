import React, { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { BadgeCheck, Video, ArrowRight, Zap, Crown, MapPinOff } from 'lucide-react';
import LocationGate, { useSharedLocation } from '../../components/mp/LocationGate';
import { PriceTag, DiscountBadge } from '../../components/mp/PriceTag';
import { SpecialtyBadges, fmtEta } from '../../components/mp/SpecialtyBadges';
import { mp } from '../../utils/mpApi';
import InstantConsultModal from '../../components/mp/InstantConsultModal';
import SEOHead from '../../components/SEOHead';

export const CircleCategories = ({ module, active, onSelect }) => {
  const [cats, setCats] = useState([]);
  useEffect(() => {
    mp.get('/categories', { params: { module } }).then((r) => setCats(r.data)).catch(() => {});
  }, [module]);
  if (!cats.length) return null;
  return (
    <div className="grid grid-cols-4 gap-2 sm:gap-4 max-w-3xl mx-auto" data-testid={`circle-cats-${module}`}>
      {cats.slice(0, 8).map((c) => {
        const isAll = ['View All', 'View All Services', 'All Dermatologists'].includes(c.title);
        const isActive = isAll ? !active : active === c.title;
        return (
          <button key={c.cat_id} data-testid={`cat-${c.cat_id}`}
            onClick={() => onSelect(isAll ? '' : c.title)}
            className={`group relative aspect-square rounded-2xl overflow-hidden border-2 transition-all ${isActive ? 'border-emerald-600 ring-4 ring-emerald-100' : 'border-transparent hover:border-emerald-300'}`}>
            {c.image
              ? <img src={c.image} alt={c.title} className="absolute inset-0 w-full h-full object-cover transition-transform duration-500 group-hover:scale-105" />
              : <span className="absolute inset-0 bg-emerald-50 flex items-center justify-center text-emerald-700 font-extrabold text-2xl">{c.title[0]}</span>}
            <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-emerald-950/80 via-emerald-950/25 to-transparent px-1.5 pb-1.5 pt-5">
              <span className="block text-white text-[9px] sm:text-[11px] font-bold leading-tight text-center drop-shadow">{c.title}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
};

export const GoldBar = ({ onlineCount, onClick, testid = 'consult-now-btn' }) => (
  <button onClick={onClick} disabled={onlineCount === 0} data-testid={testid}
    className="group relative w-full max-w-xl mx-auto flex items-center gap-3 overflow-hidden rounded-2xl px-4 py-3.5 text-left bg-gradient-to-r from-amber-300 via-yellow-400 to-amber-500 shadow-lg shadow-amber-500/25 ring-1 ring-amber-200 disabled:opacity-60 transition-transform active:scale-[.98]">
    <span className="absolute inset-y-0 -left-1/3 w-1/3 bg-white/40 skew-x-[-20deg] group-hover:left-[110%] transition-[left] duration-700" />
    <span className="w-10 h-10 rounded-xl bg-stone-900 text-amber-300 flex items-center justify-center shrink-0"><Zap size={18} /></span>
    <span className="flex-1 min-w-0">
      <span className="flex items-center gap-1.5 text-[10px] font-black tracking-[0.2em] uppercase text-stone-800"><Crown size={11} /> Online consult · Skin health</span>
      <span className="block text-sm sm:text-base font-extrabold text-stone-900 leading-tight">{onlineCount > 0 ? `${onlineCount} dermatologist${onlineCount > 1 ? 's' : ''} live now — talk in minutes` : 'Doctors go live soon — book a slot below'}</span>
    </span>
    <ArrowRight size={18} className="text-stone-900 shrink-0 group-hover:translate-x-1 transition-transform" />
  </button>
);

export const DoctorCard = ({ d }) => (
  <Link to={`/doctors/${d.doctor_id}`} data-testid={`doctor-card-${d.doctor_id}`}
    className="group bg-white rounded-2xl sm:rounded-3xl border border-stone-200 p-1.5 sm:p-4 hover:border-emerald-400 hover:shadow-xl transition-[box-shadow,border-color] flex flex-col min-w-0">
    <div className="relative rounded-xl sm:rounded-2xl overflow-hidden bg-stone-50 aspect-[3/4]">
      {d.photo
        ? <img src={d.photo} alt={d.name} className="w-full h-full object-cover object-top transition-transform duration-500 group-hover:scale-105" />
        : <div className="w-full h-full flex items-center justify-center text-emerald-700 text-3xl font-extrabold">{(d.name || 'D')[0]}</div>}
      {d.online && (
        <span className="absolute top-1.5 left-1.5 inline-flex items-center gap-1 text-[8px] sm:text-[9px] font-extrabold text-white bg-emerald-600 rounded-full px-1.5 sm:px-2 py-0.5" data-testid={`online-${d.doctor_id}`}>
          <span className="h-1.5 w-1.5 rounded-full bg-white animate-pulse" /> LIVE
        </span>
      )}
      <DiscountBadge pct={d.discount_pct} className="absolute top-1.5 right-1.5" />
      {d.distance_km != null && <span className="absolute bottom-1.5 right-1.5 text-[8px] sm:text-[9px] font-bold text-stone-700 bg-white/90 rounded-full px-1.5 py-0.5" data-testid={`dist-${d.doctor_id}`}>{d.distance_km} km{d.eta_minutes != null ? ` • ${fmtEta(d.eta_minutes).replace(' away', '')}` : ''}</span>}
    </div>
    <div className="mt-2 px-1 flex-1 min-w-0">
      <p className="font-extrabold text-stone-900 text-[11px] sm:text-base flex items-center gap-1 truncate">
        <span className="truncate">Dr. {d.name}</span> <BadgeCheck size={13} className="text-emerald-600 shrink-0" data-testid="verified-badge" />
      </p>
      <p className="text-[9px] sm:text-[11px] text-emerald-800 font-bold truncate">{(d.qualification || '').split(',')[0]}{d.experience_years ? ` · ${d.experience_years}+ yrs` : ''}</p>
      <div className="mt-1"><SpecialtyBadges items={d.specialties} max={2} testid={`card-specialties-${d.doctor_id}`} /></div>
      <p className="hidden sm:flex text-[11px] text-stone-400 items-center gap-1 mt-0.5"><Video size={11} /> Video consult</p>
    </div>
    <div className="px-1 pb-1 mt-1.5 flex items-center justify-between gap-1">
      <PriceTag price={d.fee} mrp={d.mrp} size="sm" />
      <span className="hidden sm:inline-flex items-center gap-1 bg-emerald-700 text-white text-xs font-bold rounded-full px-3 py-1.5 group-hover:bg-emerald-800">Book <ArrowRight size={12} /></span>
    </div>
  </Link>
);

const DoctorsPage = () => {
  const [searchParams] = useSearchParams();
  const [doctors, setDoctors] = useState([]);
  const [cat, setCat] = useState(searchParams.get('cat') || '');
  const [enabled, setEnabled] = useState(true);
  const [loading, setLoading] = useState(false);
  const [onlineCount, setOnlineCount] = useState(0);
  const [showInstant, setShowInstant] = useState(false);
  const loc = useSharedLocation();

  useEffect(() => {
    mp.get('/config').then((r) => { setEnabled(r.data.dermatologist_enabled); setOnlineCount(r.data.online_doctors || 0); }).catch(() => {});
  }, []);

  useEffect(() => {
    if (!loc) return;
    setLoading(true);
    mp.get('/doctors', { params: { ...(cat ? { category: cat } : {}), lat: loc.lat, lng: loc.lng, city: loc.city || '' } })
      .then((r) => setDoctors(r.data)).catch(() => setDoctors([])).finally(() => setLoading(false));
  }, [cat, loc?.lat, loc?.lng]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!enabled) return (
    <div className="max-w-xl mx-auto px-6 py-24 text-center" data-testid="doctors-disabled">
      <h1 className="text-2xl font-extrabold text-stone-900">Consultations are taking a short break</h1>
      <p className="text-stone-500 mt-2">Back very soon.</p>
    </div>
  );

  return (
    <div className="bg-white min-h-screen" data-testid="doctors-page">
      <SEOHead title="Consult a Dermatologist Online" canonicalPath="/doctors"
        description="Book verified dermatologists near you for secure video consultations with digital prescriptions — instant and scheduled appointments on Celesta Glow." />
      <div className="max-w-6xl mx-auto px-3 sm:px-6 py-8 sm:py-12">
        <div className="text-center mb-7">
          <p className="text-xs font-bold tracking-[0.2em] text-emerald-700 uppercase">What is your skin trying to tell you?</p>
          <h1 className="text-3xl sm:text-5xl font-extrabold text-stone-900 mt-2">Ask a Dermatologist</h1>
        </div>
        <div className="mb-7" data-testid="goldbar-under-heading"><GoldBar onlineCount={onlineCount} onClick={() => setShowInstant(true)} /></div>
        {showInstant && <InstantConsultModal onClose={() => setShowInstant(false)} />}

        {!loc ? (
          <LocationGate title="Find dermatologists around you" subtitle="See who is live near you right now." />
        ) : (
          <>
            <CircleCategories module="doctor" active={cat} onSelect={setCat} />

            <div className="mt-8 grid grid-cols-3 gap-2 sm:gap-5" data-testid="doctor-list">
              {loading && <p className="col-span-full text-center text-stone-400 py-16">Finding dermatologists near you…</p>}
              {!loading && doctors.length === 0 && (
                <div className="col-span-full flex justify-center py-10" data-testid="no-doctors-nearby">
                  <div className="max-w-md w-full text-center bg-gradient-to-br from-emerald-50 via-white to-teal-50 border border-emerald-100 rounded-3xl p-8 sm:p-10 shadow-sm">
                    <div className="mx-auto w-16 h-16 rounded-2xl bg-white shadow-sm ring-1 ring-emerald-100 flex items-center justify-center text-emerald-600 mb-4"><MapPinOff size={30} strokeWidth={1.6} /></div>
                    <h3 className="text-xl font-extrabold text-stone-900">We're not available at your location yet</h3>
                    <p className="text-sm text-stone-500 mt-2 leading-relaxed">No dermatologists near you right now. We're expanding fast — switch your area from the top bar to explore nearby, or check back soon.</p>
                    <Link to="/pro" className="inline-flex items-center gap-1.5 mt-5 text-emerald-700 font-bold text-sm hover:underline">Are you a dermatologist? Join us <ArrowRight size={14} /></Link>
                  </div>
                </div>
              )}
              {doctors.map((d) => <DoctorCard key={d.doctor_id} d={d} />)}
            </div>

            <div className="mt-12 max-w-2xl mx-auto bg-gradient-to-br from-emerald-700 to-teal-800 rounded-3xl p-6 sm:p-8 text-white text-center" data-testid="doctor-join-section">
              <h2 className="text-xl font-extrabold">Dermatologist? Grow your practice.</h2>
              <p className="text-sm text-emerald-100 mt-1">Your fees. Your hours. Patients near you.</p>
              <Link to="/pro" data-testid="apply-as-doctor-link" className="inline-block mt-4 bg-white text-emerald-900 font-extrabold rounded-full px-6 py-3 text-sm">Join Celesta Glow</Link>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

export default DoctorsPage;

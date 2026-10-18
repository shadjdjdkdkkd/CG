import React, { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { X, Zap, Loader2, CheckCircle2, CreditCard, BadgeCheck, Stethoscope, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';
import { mp } from '../../utils/mpApi';
import { openRazorpayCheckout } from '../../utils/razorpay';

const input = 'w-full rounded-xl border border-stone-200 px-4 py-3 text-sm';

// Instant consult: show ONLINE doctors + their rate first, let the patient pick, then pay & ring.
const InstantConsultModal = ({ doctorId, onClose }) => {
  const [form, setForm] = useState({ name: '', email: '', phone: '' });
  const [stage, setStage] = useState(doctorId ? 'form' : 'select'); // select | form | paying | waiting | ready | failed
  const [docs, setDocs] = useState(null);
  const [picked, setPicked] = useState(doctorId || null);
  const [booking, setBooking] = useState(null);
  const [msg, setMsg] = useState('');
  const timer = useRef(null);
  const navigate = useNavigate();

  useEffect(() => () => clearInterval(timer.current), []);
  useEffect(() => {
    if (stage !== 'select') return;
    mp.get('/consultations/online-doctors').then((r) => setDocs(r.data.doctors)).catch(() => setDocs([]));
  }, [stage]);

  const poll = (bid, email) => {
    let tries = 0;
    timer.current = setInterval(async () => {
      tries += 1;
      try {
        const r = await mp.get(`/consultations/${bid}/room`, { params: { email } });
        if (['confirmed', 'in_progress'].includes(r.data.status)) { clearInterval(timer.current); setStage('ready'); }
      } catch { /* still ringing */ }
      if (tries >= 36) {
        clearInterval(timer.current);
        setStage('failed');
        setMsg('No doctor picked up in time. Get an instant refund to your wallet, or keep waiting.');
      }
    }, 5000);
  };

  const requestRefund = async () => {
    try {
      const r = await mp.post(`/consultations/${booking.booking_id}/cancel-refund`, { email: form.email.toLowerCase() });
      toast.success(r.data.refunded ? `₹${r.data.refunded} added to your wallet` : 'Cancelled');
      onClose();
    } catch (e) { toast.error(e.response?.data?.detail || 'Could not refund — contact support'); }
  };

  const submit = async (e) => {
    e.preventDefault();
    try {
      const r = await mp.post('/consultations/instant', { ...form, doctor_id: picked || null });
      const bk = r.data.booking; setBooking(bk);
      if (r.data.payments_configured && bk.razorpay_order_id) {
        setStage('paying');
        openRazorpayCheckout({
          orderId: bk.razorpay_order_id, amount: bk.fee, name: form.name, email: form.email, phone: form.phone,
          description: 'Instant dermatologist consultation',
          onSuccess: async (resp) => {
            try {
              await mp.post('/consultations/verify-payment', {
                booking_id: bk.booking_id, razorpay_order_id: resp.razorpay_order_id,
                razorpay_payment_id: resp.razorpay_payment_id, razorpay_signature: resp.razorpay_signature });
              setStage('waiting'); poll(bk.booking_id, form.email.toLowerCase());
            } catch { toast.error('Payment verification failed — contact support'); setStage('failed'); }
          },
          onFailure: (m) => { toast.error(m); setStage('form'); },
        });
      } else { setStage('waiting'); poll(bk.booking_id, form.email.toLowerCase()); }
    } catch (err) { toast.error(err.response?.data?.detail || 'Instant consult unavailable'); }
  };

  const pickedDoc = (docs || []).find((d) => d.doctor_id === picked);

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center px-4" data-testid="instant-modal">
      <div className="bg-white rounded-3xl w-full max-w-md p-6 relative max-h-[90vh] overflow-y-auto">
        <button onClick={onClose} className="absolute top-4 right-4 text-stone-400" data-testid="instant-close"><X size={20} /></button>
        <p className="text-xs font-bold tracking-widest text-emerald-700 uppercase flex items-center gap-1.5"><Zap size={13} /> Instant consultation</p>

        {stage === 'select' && (
          <div className="mt-3" data-testid="instant-select">
            <h2 className="text-xl font-extrabold text-stone-900">Doctors online now</h2>
            <p className="text-xs text-stone-500 mb-4">Pick a dermatologist, then pay and we ring them for you.</p>
            {docs === null && <div className="py-10 text-center"><Loader2 className="animate-spin mx-auto text-emerald-600" /></div>}
            {docs && docs.length === 0 && (
              <div className="py-8 text-center text-sm text-stone-500" data-testid="instant-none-online">
                No dermatologists are online right now. Please book a slot instead.
              </div>
            )}
            <div className="space-y-2.5">
              {(docs || []).map((d) => (
                <button key={d.doctor_id} onClick={() => { setPicked(d.doctor_id); setStage('form'); }} data-testid={`instant-doc-${d.doctor_id}`}
                  className="w-full flex items-center gap-3 border border-stone-200 hover:border-emerald-500 rounded-2xl p-3 text-left transition-colors">
                  <div className="w-14 h-14 rounded-xl overflow-hidden bg-stone-50 shrink-0">
                    {d.photo ? <img src={d.photo} alt="" className="w-full h-full object-cover object-top" /> : <span className="w-full h-full flex items-center justify-center text-emerald-700"><Stethoscope size={22} /></span>}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-bold text-stone-900 text-sm flex items-center gap-1">Dr. {d.name} <BadgeCheck size={14} className="text-emerald-600" /></p>
                    <p className="text-xs text-stone-500 truncate">{d.specialisation}{d.experience_years ? ` • ${d.experience_years} yrs` : ''}</p>
                    <span className="inline-flex items-center gap-1.5 mt-0.5"><span className="text-emerald-700 font-extrabold text-sm">₹{d.fee}</span>{d.mrp > d.fee && <span className="text-[11px] text-stone-400 line-through">₹{d.mrp}</span>}<span className="w-1.5 h-1.5 rounded-full bg-emerald-500" /><span className="text-[10px] text-emerald-600 font-bold">Online</span></span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

        {stage === 'form' && (
          <form onSubmit={submit} className="mt-3 space-y-3" data-testid="instant-form">
            <h2 className="text-xl font-extrabold text-stone-900">{pickedDoc ? `Connect with Dr. ${pickedDoc.name}` : 'Connect with a dermatologist now'}</h2>
            <p className="text-xs text-stone-500">Pay securely, then we ring {pickedDoc ? 'this doctor' : 'every doctor online'} — they join you on video.{pickedDoc ? ` Fee ₹${pickedDoc.fee}.` : ''}</p>
            <input required placeholder="Full name" data-testid="instant-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={input} />
            <input required type="email" placeholder="Email" data-testid="instant-email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className={input} />
            <input required placeholder="Mobile" data-testid="instant-phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} className={input} />
            <button data-testid="instant-submit" className="w-full bg-emerald-700 hover:bg-emerald-800 text-white font-extrabold rounded-full py-3.5 text-sm inline-flex items-center justify-center gap-2">
              <CreditCard size={15} /> Pay & connect
            </button>
            {!doctorId && <button type="button" onClick={() => setStage('select')} className="w-full text-xs text-stone-500 underline">← Pick another doctor</button>}
          </form>
        )}

        {stage === 'paying' && (
          <div className="mt-4 text-center py-8" data-testid="instant-paying">
            <Loader2 size={36} className="mx-auto text-emerald-600 animate-spin" />
            <h2 className="text-lg font-extrabold text-stone-900 mt-3">Complete payment…</h2>
            <p className="text-xs text-stone-500 mt-1">Finish the secure Razorpay checkout to ring the doctor.</p>
          </div>
        )}

        {stage === 'waiting' && (
          <div className="mt-4 text-center py-6" data-testid="instant-waiting">
            <div className="relative w-16 h-16 mx-auto">
              <span className="animate-ping absolute inset-0 rounded-full bg-emerald-200" />
              <span className="relative w-16 h-16 rounded-full bg-emerald-700 text-white flex items-center justify-center"><Zap size={24} /></span>
            </div>
            <h2 className="text-lg font-extrabold text-stone-900 mt-3">Ringing {pickedDoc ? `Dr. ${pickedDoc.name}` : 'online doctors'}…</h2>
            <p className="text-xs text-stone-500 mt-1">{msg || 'Payment done. The doctor connects on video as soon as they accept.'}</p>
            <p className="text-[11px] text-stone-400 mt-3">Booking {booking?.booking_id}</p>
          </div>
        )}

        {stage === 'ready' && (
          <div className="mt-4 text-center py-6" data-testid="instant-ready">
            <CheckCircle2 size={40} className="mx-auto text-emerald-600" />
            <h2 className="text-lg font-extrabold text-stone-900 mt-3">Doctor accepted!</h2>
            <button onClick={() => navigate(`/consult-room/${booking.booking_id}`)} data-testid="instant-join"
              className="mt-4 bg-emerald-700 text-white font-extrabold rounded-full px-8 py-3.5 text-sm">Join video room</button>
          </div>
        )}

        {stage === 'failed' && (
          <div className="mt-4 text-center py-6" data-testid="instant-failed">
            <h2 className="text-lg font-extrabold text-stone-900">No doctor connected</h2>
            <p className="text-xs text-stone-500 mt-2">{msg}</p>
            <div className="flex flex-col gap-2 mt-4">
              <button onClick={requestRefund} data-testid="instant-refund" className="bg-emerald-700 text-white font-extrabold rounded-full px-6 py-3 text-sm inline-flex items-center justify-center gap-1.5"><RotateCcw size={14} /> Refund to my wallet</button>
              <button onClick={() => { setStage('waiting'); poll(booking.booking_id, form.email.toLowerCase()); }} data-testid="instant-keep-waiting" className="border border-stone-300 text-stone-700 font-bold rounded-full px-6 py-3 text-sm">Keep waiting</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default InstantConsultModal;

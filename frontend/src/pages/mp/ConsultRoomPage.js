import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { Video, VideoOff, LifeBuoy, PhoneOff, Phone, FileText } from 'lucide-react';
import { toast } from 'sonner';
import { mp, customerHdr, doctorHdr } from '../../utils/mpApi';
import AgoraCall from '../../components/mp/AgoraCall';

const ConsultRoomPage = () => {
  const { bookingId } = useParams();
  const [room, setRoom] = useState(null);
  const [err, setErr] = useState('');
  const [joined, setJoined] = useState(false);
  const [ended, setEnded] = useState(false);
  const [otp, setOtp] = useState('');
  const [busy, setBusy] = useState(false);
  const [callRoom, setCallRoom] = useState(null);

  const hdr = localStorage.getItem('mp_doctor_token') ? doctorHdr() : customerHdr();
  const load = () => mp.get(`/consultations/${bookingId}/room`, hdr)
    .then((r) => setRoom(r.data)).catch((e) => setErr(e.response?.data?.detail || 'Cannot open this room'));
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [bookingId]);

  if (err) return (
    <div className="min-h-screen bg-stone-50 flex items-center justify-center px-6" data-testid="room-error">
      <div className="text-center">
        <VideoOff size={40} className="mx-auto text-stone-300" />
        <p className="mt-3 text-stone-600 font-semibold">{err}</p>
        <Link to="/my/bookings" className="text-emerald-700 underline text-sm">My bookings</Link>
      </div>
    </div>
  );
  if (!room) return <div className="py-24 text-center text-stone-400">Preparing room…</div>;

  const requestCompletion = async () => {
    setBusy(true);
    try { await mp.post(`/doctor/bookings/${bookingId}/request-completion`, {}, doctorHdr()); toast.success('Completion code emailed to the customer'); load(); }
    catch (e) { toast.error(e.response?.data?.detail || 'Failed'); } finally { setBusy(false); }
  };
  const verify = async () => {
    setBusy(true);
    try { await mp.post(`/doctor/bookings/${bookingId}/verify`, { otp }, doctorHdr()); toast.success('Consultation verified & completed'); load(); }
    catch (e) { toast.error(e.response?.data?.detail || 'Verification failed'); } finally { setBusy(false); }
  };
  const uploadRx = async (file) => {
    if (!file) return;
    const fd = new FormData(); fd.append('file', file);
    setBusy(true);
    try { await mp.post(`/doctor/bookings/${bookingId}/prescription/image`, fd, doctorHdr()); toast.success('Prescription image uploaded & sent to patient'); }
    catch (e) { toast.error(e.response?.data?.detail || 'Upload failed'); } finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen bg-stone-900 text-white" data-testid="consult-room">
      <div className="max-w-5xl mx-auto px-4 py-6 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs text-stone-400">{room.booking_id} • {room.date} • {room.slot}</p>
            <h1 className="text-lg font-extrabold">Consultation with Dr. {room.doctor_name}</h1>
          </div>
          <span className="text-[11px] font-bold bg-emerald-500/20 text-emerald-300 rounded-full px-3 py-1.5">{room.status.replace(/_/g, ' ')}</span>
        </div>
        {ended ? (
          <div className="bg-stone-800 rounded-3xl p-10 text-center" data-testid="call-ended">
            <PhoneOff size={40} className="mx-auto text-rose-400" />
            <h2 className="text-xl font-extrabold mt-4">Call ended</h2>
            <p className="text-sm text-stone-400 mt-2">Dr. {room.doctor_name} • {room.date} {room.slot}</p>
            {room.role === 'customer' && (
              <Link to="/my/bookings" data-testid="view-rx-link" className="mt-5 inline-flex items-center gap-1.5 bg-emerald-600 text-white font-bold rounded-full px-6 py-3 text-sm">
                <FileText size={15} /> Prescription & summary
              </Link>
            )}
            <button onClick={() => { setEnded(false); setCallRoom(room); setJoined(true); }} data-testid="rejoin-call" className="mt-3 block mx-auto text-xs text-stone-400 underline">Rejoin call</button>
          </div>
        ) : !joined ? (
          <div className="bg-stone-800 rounded-3xl p-10 text-center" data-testid="waiting-room">
            <Video size={44} className="mx-auto text-emerald-400" />
            <h2 className="text-xl font-extrabold mt-4">{room.role === 'doctor' ? 'Your patient is ready' : `Dr. ${room.doctor_name} will see you now`}</h2>
            <p className="text-sm text-stone-400 mt-2">Private, paid & secure. Allow camera and mic when asked.</p>
            {room.provider === 'zoom' ? (
              <div className="flex flex-wrap gap-3 justify-center mt-6">
                <a href={room.web_url} target="_blank" rel="noreferrer" onClick={() => setJoined(true)} data-testid="join-call"
                  className="inline-flex items-center gap-2 bg-emerald-600 hover:bg-emerald-500 text-white font-extrabold rounded-full px-8 py-3.5"><Phone size={16} /> {room.role === 'doctor' ? 'Start Zoom call' : 'Call doctor'}</a>
                <a href={room.join_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-2 border border-stone-600 text-stone-200 font-bold rounded-full px-6 py-3.5 text-sm">Open in Zoom app</a>
              </div>
            ) : (
              <button onClick={() => { setCallRoom(room); setJoined(true); }} data-testid="join-call"
                className="mt-6 inline-flex items-center gap-2 bg-emerald-600 hover:bg-emerald-500 text-white font-extrabold rounded-full px-8 py-3.5"><Phone size={16} /> {room.role === 'doctor' ? 'Start call' : 'Call doctor'}</button>
            )}
          </div>
        ) : (
          <div className="space-y-3">
            {room.provider === 'agora' && callRoom ? (
              <AgoraCall room={callRoom} onEnd={() => { setJoined(false); setEnded(true); setCallRoom(null); load(); }} />
            ) : room.provider === 'zoom' ? (
              <div className="bg-stone-800 rounded-3xl p-8 text-center" data-testid="zoom-active">
                <p className="text-sm text-stone-300">Your Zoom call is open in a new tab.</p>
              </div>
            ) : (
              <div className="rounded-3xl overflow-hidden border border-stone-700" data-testid="jitsi-frame">
                <iframe title="Video consultation" width="100%" height="560" allow="camera; microphone; fullscreen; display-capture; autoplay"
                  src={`https://${room.domain}/${room.room}#config.prejoinPageEnabled=false&config.disableDeepLinking=true&config.startWithAudioMuted=false`} />
              </div>
            )}
            {room.provider !== 'agora' && <div className="flex justify-center">
              <button onClick={() => { setJoined(false); setEnded(true); load(); }} data-testid="end-call"
                className="inline-flex items-center gap-2 bg-rose-600 hover:bg-rose-500 text-white font-extrabold rounded-full px-8 py-3.5 shadow-lg shadow-rose-900/40">
                <PhoneOff size={18} /> End call
              </button>
            </div>}
          </div>
        )}
        {room.role === 'doctor' && (
          <div className="bg-stone-800 rounded-2xl p-5" data-testid="doctor-completion-panel">
            <p className="font-bold text-sm">Complete the consultation</p>
            <p className="text-xs text-stone-400 mt-1">Send the code, enter it to close the consult — earnings release instantly. Write the prescription from your dashboard.</p>
            <div className="flex flex-wrap gap-2 mt-3">
              <button onClick={requestCompletion} disabled={busy} data-testid="doctor-request-otp"
                className="bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-bold rounded-full px-4 py-2.5">Email completion code to customer</button>
              <input value={otp} onChange={(e) => setOtp(e.target.value)} placeholder="Enter code" data-testid="doctor-otp-input"
                className="bg-stone-900 border border-stone-600 rounded-full px-4 py-2 text-sm w-36 text-center tracking-widest" />
              <button onClick={verify} disabled={busy || !otp} data-testid="doctor-verify-otp"
                className="bg-white text-stone-900 text-xs font-extrabold rounded-full px-4 py-2.5">Verify & complete</button>
            </div>
            <label className="mt-3 inline-flex items-center gap-1.5 border border-stone-600 text-stone-200 text-xs font-bold rounded-full px-4 py-2.5 cursor-pointer" data-testid="doctor-rx-image">
              <FileText size={13} /> Upload prescription image
              <input type="file" accept="image/*" className="hidden" onChange={(e) => uploadRx(e.target.files[0])} />
            </label>
          </div>
        )}
        {room.role === 'customer' && room.status === 'completion_pending' && (
          <p className="text-center text-sm text-violet-300" data-testid="customer-otp-hint">Your doctor has requested completion — the verification code was sent to your email.</p>
        )}
        <div className="flex justify-center">
          <Link to="/support" className="inline-flex items-center gap-1.5 text-xs text-stone-400 hover:text-white"><LifeBuoy size={13} /> Report a problem</Link>
        </div>
      </div>
    </div>
  );
};

export default ConsultRoomPage;

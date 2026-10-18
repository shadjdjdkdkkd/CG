import React, { useEffect, useRef, useState } from 'react';
import AgoraRTC from 'agora-rtc-sdk-ng';
import { Mic, MicOff, Video, VideoOff, PhoneOff, Loader2 } from 'lucide-react';
import { toast } from 'sonner';

// 1:1 Agora RTC call; `room` comes from GET /consultations/{id}/room (provider=agora).
export default function AgoraCall({ room, onEnd }) {
  const client = useRef(null);
  const tracks = useRef({});
  const localRef = useRef(null);
  const remoteRef = useRef(null);
  const [state, setState] = useState('connecting');
  const [remoteIn, setRemoteIn] = useState(false);
  const [mic, setMic] = useState(true);
  const [cam, setCam] = useState(true);

  useEffect(() => {
    const c = AgoraRTC.createClient({ mode: 'rtc', codec: 'vp8' });
    client.current = c;
    let alive = true;
    c.on('user-published', async (user, type) => {
      await c.subscribe(user, type);
      if (type === 'video' && remoteRef.current) { user.videoTrack.play(remoteRef.current); setRemoteIn(true); }
      if (type === 'audio') user.audioTrack.play();
    });
    c.on('user-left', () => setRemoteIn(false));
    (async () => {
      try {
        await c.join(room.app_id, room.channel, room.token, room.uid);
        const [a, v] = await AgoraRTC.createMicrophoneAndCameraTracks();
        if (!alive) { a.close(); v.close(); return; }
        tracks.current = { a, v };
        if (localRef.current) v.play(localRef.current);
        await c.publish([a, v]);
        setState('live');
      } catch (e) {
        setState('error');
        // Surface the precise Agora failure so the real root cause is visible in logs.
        console.error('[AgoraCall] join/publish failed', { code: e?.code, name: e?.name, message: e?.message, e });
        const code = e?.code || '';
        let msg = 'Could not connect the video call';
        if (e?.message?.includes('Permission') || e?.name === 'NotAllowedError') msg = 'Allow camera & microphone to join';
        else if (code === 'CAN_NOT_GET_GATEWAY_SERVER' || /token|dynamic key|invalid vendor/i.test(e?.message || '')) msg = 'Video service rejected the token — please tell support (code: ' + (code || 'token') + ')';
        toast.error(msg);
      }
    })();
    return () => {
      alive = false;
      tracks.current.a?.close(); tracks.current.v?.close();
      c.removeAllListeners(); c.leave().catch(() => {});
    };
  }, [room.app_id, room.channel, room.token, room.uid]);

  const toggleMic = async () => { await tracks.current.a?.setEnabled(!mic); setMic(!mic); };
  const toggleCam = async () => { await tracks.current.v?.setEnabled(!cam); setCam(!cam); };
  const other = room.role === 'doctor' ? (room.customer_name || 'Patient') : `Dr. ${room.doctor_name}`;
  const btn = 'w-12 h-12 rounded-full flex items-center justify-center transition-colors';

  return (
    <div className="space-y-3" data-testid="agora-call">
      <div className="relative rounded-3xl overflow-hidden bg-black aspect-video border border-stone-700">
        <div ref={remoteRef} className="absolute inset-0" data-testid="agora-remote" />
        {!remoteIn && (
          <div className="absolute inset-0 flex flex-col items-center justify-center text-stone-400 text-sm gap-2">
            {state === 'connecting' ? <Loader2 className="animate-spin" /> : null}
            {state === 'error' ? 'Connection failed — tap End and rejoin' : `Waiting for ${other} to join…`}
          </div>
        )}
        <div ref={localRef} className="absolute bottom-3 right-3 w-28 sm:w-44 aspect-video rounded-xl overflow-hidden bg-stone-800 border border-stone-600" data-testid="agora-local" />
        <span className="absolute top-3 left-3 text-[10px] font-bold bg-black/50 rounded-full px-2.5 py-1">{state === 'live' ? '● LIVE' : state}</span>
      </div>
      <div className="flex justify-center gap-3">
        <button onClick={toggleMic} data-testid="agora-mic" className={`${btn} ${mic ? 'bg-stone-700' : 'bg-rose-600'}`}>{mic ? <Mic size={18} /> : <MicOff size={18} />}</button>
        <button onClick={toggleCam} data-testid="agora-cam" className={`${btn} ${cam ? 'bg-stone-700' : 'bg-rose-600'}`}>{cam ? <Video size={18} /> : <VideoOff size={18} />}</button>
        <button onClick={onEnd} data-testid="end-call" className={`${btn} bg-rose-600 hover:bg-rose-500 w-auto px-6 gap-2 font-extrabold text-sm`}><PhoneOff size={18} /> End call</button>
      </div>
    </div>
  );
}

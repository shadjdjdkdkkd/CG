import { useState } from "react";
import { toast } from "sonner";
import { Mail, KeyRound, Loader2 } from "lucide-react";
import { api, errMsg } from "@/af/lib/api";

const inputCls = "w-full bg-[#0B1120] border border-[#1F2937] rounded-md px-3 py-2.5 text-sm focus:outline-none focus:border-emerald-500 transition-colors";

export default function OtpReset({ onDone }) {
  const [sentTo, setSentTo] = useState("");
  const [otp, setOtp] = useState("");
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);

  const send = async () => {
    setBusy(true);
    try { const { data } = await api.post("/auth/request-otp"); setSentTo(data.sent_to); toast.success(`Code sent to ${data.sent_to}`); }
    catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };
  const reset = async (e) => {
    e.preventDefault();
    setBusy(true);
    try { await api.post("/auth/reset-password", { otp, new_password: pw }); toast.success("Password changed"); setOtp(""); setPw(""); setSentTo(""); onDone?.(); }
    catch (err) { toast.error(errMsg(err)); } finally { setBusy(false); }
  };

  return (
    <div className="space-y-4" data-testid="otp-reset">
      <button type="button" data-testid="send-otp-button" onClick={send} disabled={busy} className="w-full py-2.5 rounded-md border border-[#374151] text-sm flex items-center justify-center gap-2 hover:bg-white/5 disabled:opacity-50 transition-colors">
        {busy && !sentTo ? <Loader2 className="w-4 h-4 animate-spin" /> : <Mail className="w-4 h-4" />}{sentTo ? "Resend code" : "Email me a code"}
      </button>
      {sentTo && (
        <form onSubmit={reset} className="space-y-3">
          <p className="text-xs text-slate-400">Code sent to <span className="font-mono">{sentTo}</span> (valid 10 min)</p>
          <input data-testid="otp-input" className={inputCls + " font-mono tracking-[0.4em]"} maxLength={6} value={otp} onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))} placeholder="6-digit code" />
          <input data-testid="new-password-input" type="password" className={inputCls} value={pw} onChange={(e) => setPw(e.target.value)} placeholder="New password (min 8 characters)" />
          <button data-testid="reset-password-submit" disabled={busy || otp.length !== 6 || pw.length < 8} className="w-full py-2.5 rounded-full bg-emerald-500 text-[#04140D] font-semibold flex items-center justify-center gap-2 hover:bg-emerald-400 disabled:opacity-50 transition-colors"><KeyRound className="w-4 h-4" />Change password</button>
        </form>
      )}
    </div>
  );
}

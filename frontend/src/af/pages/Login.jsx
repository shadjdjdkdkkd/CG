import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Zap, Loader2 } from "lucide-react";
import { api, errMsg, TOKEN_KEY } from "@/af/lib/api";
import OtpReset from "@/af/components/OtpReset";

const inputCls = "w-full bg-[#0B1120] border border-[#1F2937] rounded-md px-3 py-3 text-sm focus:outline-none focus:border-emerald-500 transition-colors";

export default function Login() {
  const nav = useNavigate();
  const [u, setU] = useState("");
  const [p, setP] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [forgot, setForgot] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr("");
    try {
      const { data } = await api.post("/auth/login", { username: u, password: p });
      localStorage.setItem(TOKEN_KEY, data.token);
      nav("/");
    } catch (e2) { setErr(errMsg(e2)); } finally { setBusy(false); }
  };

  return (
    <div className="min-h-screen grid place-items-center bg-[#090D16] grid-bg p-6">
      <div className="w-full max-w-sm fade-up">
        <div className="flex items-center gap-2 mb-10">
          <div className="w-9 h-9 rounded-md bg-emerald-500 grid place-items-center"><Zap className="w-4 h-4 text-[#04140D]" /></div>
          <span className="font-display text-xl font-bold tracking-tight">AutoFill<span className="text-emerald-400">AI</span></span>
        </div>
        <h1 className="font-display text-4xl font-bold tracking-tight mb-2">{forgot ? "Change password" : "Sign in"}</h1>
        <p className="text-sm text-slate-400 mb-8">{forgot ? "We email a one-time code to the owner inbox." : "Celesta Glow listing autopilot"}</p>
        {forgot ? <OtpReset onDone={() => setForgot(false)} /> : (
          <form onSubmit={submit} className="space-y-4" data-testid="login-form">
            <input data-testid="login-username-input" className={inputCls} placeholder="Username" value={u} onChange={(e) => setU(e.target.value)} autoComplete="username" />
            <input data-testid="login-password-input" type="password" className={inputCls} placeholder="Password" value={p} onChange={(e) => setP(e.target.value)} autoComplete="current-password" />
            {err && <p data-testid="login-error" className="text-sm text-red-400">{err}</p>}
            <button data-testid="login-submit-button" disabled={busy} className="w-full py-3 rounded-full bg-emerald-500 text-[#04140D] font-semibold flex items-center justify-center gap-2 hover:bg-emerald-400 disabled:opacity-50 transition-colors">{busy && <Loader2 className="w-4 h-4 animate-spin" />}Sign in</button>
          </form>
        )}
        <button data-testid="toggle-forgot-button" onClick={() => setForgot(!forgot)} className="mt-6 text-sm text-emerald-400 hover:underline">{forgot ? "Back to sign in" : "Forgot / change password (OTP)"}</button>
      </div>
    </div>
  );
}

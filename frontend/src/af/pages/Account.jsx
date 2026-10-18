import { PageHeader } from "@/af/components/Layout";
import OtpReset from "@/af/components/OtpReset";

export default function Account() {
  return (
    <div>
      <PageHeader kicker="Signed in as cg" title="Account" />
      <div className="max-w-md p-6 rounded-xl bg-[#111827] border border-[#1F2937]">
        <h2 className="font-display text-xl font-semibold mb-1">Change password</h2>
        <p className="text-sm text-slate-400 mb-6">A one-time code is emailed to the owner inbox. Enter it with your new password.</p>
        <OtpReset />
      </div>
    </div>
  );
}

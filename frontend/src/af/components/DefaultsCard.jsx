import { useState } from "react";
import { toast } from "sonner";
import { api, errMsg } from "@/af/lib/api";

const inputCls = "w-full bg-[#0B1120] border border-[#1F2937] rounded-md px-3 py-2 text-sm focus:outline-none focus:border-amber-500 transition-colors";

export default function DefaultsCard({ settings, onSaved }) {
  const [f, setF] = useState(settings);
  const save = async () => {
    try {
      const body = { ...f, mrp_markup_percent: Number(f.mrp_markup_percent || 0), shelf_life_months: f.shelf_life_months === "" ? 24 : Number(f.shelf_life_months), sizes: [...(f.sizes || []), f.default_size], brands: [...(f.brands || []), f.default_brand] };
      const r = await api.put("/settings", body);
      onSaved(r.data); setF(r.data);
      toast.success("Defaults saved");
    } catch (e) { toast.error(errMsg(e)); }
  };
  const fields = [
    ["default_brand", "Default brand", "defaults-brand-input"], ["default_size", "Default bottle size", "defaults-size-input"],
    ["default_category", "Default category", "defaults-category-input"], ["default_manufacturer", "Default manufacturer", "defaults-manufacturer-input"],
    ["mrp_markup_percent", "MRP = price + %", "defaults-markup-input"], ["handling_fee", "Handling fee to customer (₹)", "defaults-handling-fee-input"],
    ["default_quantity", "Stock quantity", "defaults-quantity-input"], ["handling_time_days", "Handling time (days)", "defaults-handling-time-input"],
    ["country_of_origin", "Country of origin", "defaults-country-input"], ["amazon_shipping", "Amazon shipping", "defaults-amazon-shipping-input"],
    ["flipkart_shipping", "Flipkart shipping provider", "defaults-flipkart-shipping-input"], ["shelf_life_months", "Shelf life (months)", "defaults-shelf-life-input"],
    ["manufacturer_address", "Manufacturer address", "defaults-manufacturer-address-input"], ["manufacturer_contact", "Manufacturer contact (phone / email)", "defaults-manufacturer-contact-input"],
    ["packer_details", "Packer details", "defaults-packer-input"], ["importer_details", "Importer details", "defaults-importer-input"],
  ];
  return (
    <div className="mb-8 p-6 rounded-xl border border-amber-500/20 bg-amber-500/[0.03]" data-testid="defaults-card">
      <p className="text-[10px] font-semibold uppercase tracking-widest text-amber-400 mb-1">Defaults &amp; listing rules</p>
      <p className="text-xs text-slate-400 mb-4">You only give the selling price — offer price = selling price, MRP is raised by the % below. AI always uses these values.</p>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 items-end">
        {fields.map(([k, label, id]) => (
          <div key={k}>
            <label className="block text-xs text-slate-400 mb-1.5">{label}</label>
            <input data-testid={id} className={inputCls} value={f[k] ?? ""} onChange={(e) => setF({ ...f, [k]: e.target.value })} />
          </div>
        ))}
        <div className="md:col-span-3">
          <label className="block text-xs text-slate-400 mb-1.5">Extra rules for AI (optional)</label>
          <input data-testid="defaults-extra-rules-input" className={inputCls} value={f.extra_rules || ""} onChange={(e) => setF({ ...f, extra_rules: e.target.value })} placeholder="e.g. Always say 'Made in India'. Expiry: 24 months from manufacture." />
        </div>
        <div className="md:col-span-4">
          <label className="block text-xs text-slate-400 mb-1.5">Photo limit per platform (used when the upload page does not show its own limit)</label>
          <div className="flex flex-wrap gap-3">
            {["flipkart", "amazon", "meesho", "myntra", "nykaa", "instamart", "jiomart", "ajio", "blinkit", "zepto", "tata1mg", "other"].map((p) => (
              <label key={p} className="flex items-center gap-2 text-xs text-slate-300 capitalize">
                {p}
                <input type="number" min="1" max="30" data-testid={`defaults-image-limit-${p}`} className={inputCls + " w-16 py-1"} value={f.image_limits?.[p] ?? f.image_limits?.other ?? 10} onChange={(e) => setF({ ...f, image_limits: { ...(f.image_limits || {}), [p]: Number(e.target.value) || 1 } })} />
              </label>
            ))}
          </div>
        </div>
        <button data-testid="defaults-save-button" onClick={save} className="py-2 rounded-md bg-amber-500 text-black font-semibold text-sm hover:bg-amber-400 transition-colors">Save defaults</button>
      </div>
      {(settings.sizes?.length > 0) && (
        <div className="mt-4 flex flex-wrap gap-2 items-center">
          <span className="text-xs text-slate-500">Saved sizes:</span>
          {settings.sizes.map((s) => <button key={s} data-testid={`size-chip-${s}`} onClick={() => setF({ ...f, default_size: s })} className={`font-mono text-xs px-2 py-1 rounded border transition-colors ${f.default_size === s ? "border-amber-500 text-amber-300" : "border-[#1F2937] text-slate-400 hover:border-slate-500"}`}>{s}</button>)}
        </div>
      )}
    </div>
  );
}

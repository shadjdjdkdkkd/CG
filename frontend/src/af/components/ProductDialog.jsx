import { useState } from "react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/af/components/ui/dialog";
import { api, errMsg } from "@/af/lib/api";

const inputCls = "w-full bg-[#0B1120] border border-[#1F2937] rounded-md px-3 py-2.5 text-sm focus:outline-none focus:border-emerald-500 transition-colors";
const Lbl = ({ children }) => <label className="block text-[10px] font-semibold uppercase tracking-widest text-slate-400 mb-1.5">{children}</label>;

export default function ProductDialog({ product, settings, onClose, onSaved, onSettings }) {
  const isNew = !product.id;
  const [f, setF] = useState({
    name: product.name || "", brand: product.brand ?? (isNew ? settings?.default_brand || "" : ""),
    ingredients: product.ingredients || "", size: product.size ?? (isNew ? settings?.default_size || "" : ""),
    price: product.price || "", external_id: product.external_id || "", category: product.category ?? (isNew ? settings?.default_category || "" : ""), notes: product.notes || "",
    hsn_code: product.hsn_code || "", gst_rate: product.gst_rate || "",
  });
  const [hsnBusy, setHsnBusy] = useState(false);
  const findHsn = async () => {
    setHsnBusy(true);
    try {
      const r = await api.post(`/products/${product.id}/hsn`);
      setF((x) => ({ ...x, ...r.data }));
      toast.success(`HSN ${r.data.hsn_code} · GST ${r.data.gst_rate}% saved`);
    } catch (err) { toast.error(errMsg(err)); } finally { setHsnBusy(false); }
  };
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });

  const saveDefault = async (field, list, value) => {
    if (!value) return toast.error("Enter a value first");
    const s = { ...settings, [field]: value, [list]: [...(settings[list] || []), value] };
    const r = await api.put("/settings", s);
    onSettings(r.data);
    toast.success(`"${value}" saved as default`);
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!f.name.trim()) return toast.error("Product name is required");
    setBusy(true);
    try {
      isNew ? await api.post("/products", f) : await api.put(`/products/${product.id}`, f);
      toast.success("Product saved");
      onSaved();
    } catch (err) { toast.error(errMsg(err)); } finally { setBusy(false); }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="bg-[#111827] border-[#1F2937] max-w-lg" data-testid="product-dialog">
        <DialogHeader><DialogTitle className="font-display text-2xl">{isNew ? "New product" : "Edit product"}</DialogTitle></DialogHeader>
        <form onSubmit={submit} className="space-y-4">
          <div><Lbl>Product name</Lbl><input data-testid="product-name-input" className={inputCls} value={f.name} onChange={set("name")} placeholder="Onion Hair Oil" /></div>
          <div>
            <Lbl>Brand name</Lbl>
            <div className="flex gap-2">
              <input data-testid="product-brand-input" list="brand-list" className={inputCls} value={f.brand} onChange={set("brand")} placeholder="Your brand" />
              <button type="button" data-testid="save-default-brand-button" onClick={() => saveDefault("default_brand", "brands", f.brand)} className="shrink-0 px-3 text-xs rounded-md border border-amber-500/30 text-amber-300 hover:bg-amber-500/10 transition-colors">Save as default</button>
            </div>
            <datalist id="brand-list">{(settings?.brands || []).map((b) => <option key={b} value={b} />)}</datalist>
          </div>
          <div><Lbl>Ingredients</Lbl><textarea data-testid="product-ingredients-input" rows={3} className={inputCls} value={f.ingredients} onChange={set("ingredients")} placeholder="Red onion extract, coconut oil, bhringraj…" /></div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <Lbl>Bottle size</Lbl>
              <input data-testid="product-size-input" list="size-list" className={inputCls} value={f.size} onChange={set("size")} placeholder="200 ml" />
              <datalist id="size-list">{(settings?.sizes || []).map((s) => <option key={s} value={s} />)}</datalist>
              <button type="button" data-testid="save-default-size-button" onClick={() => saveDefault("default_size", "sizes", f.size)} className="mt-2 w-full py-1.5 text-xs rounded-md border border-amber-500/30 text-amber-300 hover:bg-amber-500/10 transition-colors">Save size as default</button>
            </div>
            <div><Lbl>Selling price (₹)</Lbl><input data-testid="product-price-input" className={inputCls} value={f.price} onChange={set("price")} placeholder="349" /></div>
          </div>
          <div><Lbl>External product ID / EAN (auto-generated if empty)</Lbl><input data-testid="product-ean-input" className={inputCls + " font-mono"} value={f.external_id} onChange={set("external_id")} placeholder="Leave empty to auto-generate" /></div>
          <div className="grid grid-cols-[1fr_90px_auto] gap-2 items-end">
            <div><Lbl>HSN code (AI finds it if empty)</Lbl><input data-testid="product-hsn-input" className={inputCls + " font-mono"} value={f.hsn_code} onChange={set("hsn_code")} placeholder="33049990" /></div>
            <div><Lbl>GST %</Lbl><input data-testid="product-gst-input" className={inputCls + " font-mono"} value={f.gst_rate} onChange={set("gst_rate")} placeholder="18" /></div>
            {!isNew && <button type="button" data-testid="product-find-hsn-button" disabled={hsnBusy} onClick={findHsn} className="h-[42px] px-3 text-xs rounded-md border border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/10 disabled:opacity-50 transition-colors">{hsnBusy ? "Finding…" : "Find with AI"}</button>}
          </div>
          <div><Lbl>Category (optional)</Lbl><input data-testid="product-category-input" className={inputCls} value={f.category} onChange={set("category")} placeholder="Hair Oil" /></div>
          <div><Lbl>Extra notes for AI (optional)</Lbl><input data-testid="product-notes-input" className={inputCls} value={f.notes} onChange={set("notes")} placeholder="Ayurvedic, paraben-free, for hair fall" /></div>
          <button data-testid="save-product-submit" disabled={busy} className="w-full py-3 rounded-full bg-emerald-500 text-[#04140D] font-semibold hover:bg-emerald-400 disabled:opacity-50 transition-colors">{busy ? "Saving…" : "Save product"}</button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

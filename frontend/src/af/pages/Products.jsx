import { useEffect, useState } from "react";
import { Plus, Pencil, Trash2, Star, FileSpreadsheet, RefreshCw } from "lucide-react";
import { toast } from "sonner";
import { api, errMsg } from "@/af/lib/api";
import { PageHeader } from "@/af/components/Layout";
import ProductDialog from "@/af/components/ProductDialog";
import DefaultsCard from "@/af/components/DefaultsCard";
import ImportDialog from "@/af/components/ImportDialog";

export default function Products() {
  const [items, setItems] = useState([]);
  const [settings, setSettings] = useState(null);
  const [editing, setEditing] = useState(null);
  const [importing, setImporting] = useState(false);
  const load = () => Promise.all([api.get("/products"), api.get("/settings")]).then(([p, s]) => { setItems(p.data); setSettings(s.data); });
  useEffect(() => { load(); }, []);

  const regen = async (p) => {
    try { await api.post(`/products/${p.id}/external-id`); toast.success("New external ID pinned"); load(); } catch (e) { toast.error(errMsg(e)); }
  };
  const del = async (p) => {
    try { await api.delete(`/products/${p.id}`); toast.success("Deleted"); load(); } catch (e) { toast.error(errMsg(e)); }
  };

  return (
    <div>
      <PageHeader kicker="Product vault" title="Products">
        <button data-testid="import-products-button" onClick={() => setImporting(true)} className="inline-flex items-center gap-2 px-5 py-3 rounded-full border border-slate-700 hover:border-slate-500 transition-colors"><FileSpreadsheet className="w-4 h-4" />Import spreadsheet</button>
        <button data-testid="create-product-button" onClick={() => setEditing({})} className="inline-flex items-center gap-2 px-5 py-3 rounded-full bg-emerald-500 text-[#04140D] font-semibold hover:bg-emerald-400 transition-colors"><Plus className="w-4 h-4" />New product</button>
      </PageHeader>
      {settings && <DefaultsCard key={JSON.stringify(settings)} settings={settings} onSaved={setSettings} />}
      <div className="rounded-xl border border-[#1F2937] bg-[#111827] overflow-hidden" data-testid="product-list">
        {items.length === 0 && <div className="p-12 text-center text-slate-400" data-testid="product-empty">No products yet. Add your first product to start auto-filling.</div>}
        {items.map((p) => (
          <div key={p.id} data-testid={`product-row-${p.id}`} className="grid grid-cols-12 gap-4 items-center px-6 py-5 border-b border-[#1F2937] last:border-0 hover:bg-white/[0.02] transition-colors">
            <div className="col-span-12 md:col-span-4">
              <div className="font-medium">{p.name}</div>
              <div className="text-xs text-slate-400 mt-1 flex items-center gap-1">{p.brand}{p.brand && p.brand === settings?.default_brand && <Star className="w-3 h-3 text-amber-400" />}</div>
              <div className="text-[11px] text-slate-500 mt-1 flex items-center gap-2 font-mono" data-testid={`product-ean-${p.id}`}>EAN {p.external_id || "—"}
                <button data-testid={`product-regen-ean-${p.id}`} title="Generate a new external product ID" onClick={() => regen(p)} className="text-slate-500 hover:text-emerald-400 transition-colors"><RefreshCw className="w-3 h-3" /></button></div>
            </div>
            <div className="col-span-6 md:col-span-4 text-xs text-slate-400 line-clamp-2">{p.ingredients || "—"}</div>
            <div className="col-span-3 md:col-span-1 font-mono text-xs">{p.size}</div>
            <div className="col-span-3 md:col-span-1 font-mono text-sm text-emerald-300">₹{p.price}</div>
            <div className="col-span-12 md:col-span-2 flex justify-end gap-1">
              <button data-testid={`product-edit-${p.id}`} onClick={() => setEditing(p)} className="p-2 rounded-md hover:bg-white/5 text-slate-400 hover:text-white transition-colors"><Pencil className="w-4 h-4" /></button>
              <button data-testid={`product-delete-${p.id}`} onClick={() => del(p)} className="p-2 rounded-md hover:bg-red-500/10 text-slate-400 hover:text-red-400 transition-colors"><Trash2 className="w-4 h-4" /></button>
            </div>
          </div>
        ))}
      </div>
      {importing && <ImportDialog onClose={() => setImporting(false)} onDone={load} />}
      {editing && <ProductDialog product={editing} settings={settings} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} onSettings={setSettings} />}
    </div>
  );
}

import { useRef, useState } from "react";
import { Upload, FileSpreadsheet, Download, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/af/components/ui/dialog";
import { api, errMsg, BACKEND_URL } from "@/af/lib/api";

export default function ImportDialog({ onClose, onDone }) {
  const [file, setFile] = useState(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const ref = useRef();

  const upload = async () => {
    if (!file) return toast.error("Choose a CSV or Excel file");
    setBusy(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const { data } = await api.post("/products/import", fd);
      setResult(data);
      toast.success(`Imported ${data.imported} products`);
      onDone();
    } catch (e) { toast.error(errMsg(e)); } finally { setBusy(false); }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="bg-[#111827] border-[#1F2937] max-w-lg" data-testid="import-dialog">
        <DialogHeader><DialogTitle className="font-display text-2xl">Bulk import products</DialogTitle></DialogHeader>
        <p className="text-sm text-slate-400">Upload a <b>.csv</b> or <b>.xlsx</b> with columns: Product Name, Brand, Ingredients, Bottle Size, Price (Category, Notes optional). Empty brand/size use your defaults.</p>
        <a href={`${BACKEND_URL}/api/products/import-template`} data-testid="import-template-download" className="inline-flex items-center gap-2 text-sm text-emerald-400 hover:underline"><Download className="w-4 h-4" />Download sample template</a>
        <button type="button" data-testid="import-file-dropzone" onClick={() => ref.current.click()} className="w-full p-8 rounded-lg border-2 border-dashed border-[#374151] hover:border-emerald-500/60 transition-colors flex flex-col items-center gap-2 text-sm text-slate-300">
          <FileSpreadsheet className="w-8 h-8 text-slate-500" />{file ? file.name : "Click to choose spreadsheet"}
        </button>
        <input ref={ref} type="file" accept=".csv,.xlsx,.xlsm" className="hidden" data-testid="import-file-input" onChange={(e) => { setFile(e.target.files[0]); setResult(null); }} />
        {result && <div data-testid="import-result" className="text-sm p-3 rounded-md bg-emerald-500/10 text-emerald-300">Imported {result.imported} · skipped {result.skipped} · matched columns: {result.columns.join(", ")}</div>}
        <button data-testid="import-submit-button" onClick={upload} disabled={busy} className="w-full py-3 rounded-full bg-emerald-500 text-[#04140D] font-semibold flex items-center justify-center gap-2 hover:bg-emerald-400 disabled:opacity-50 transition-colors">
          {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}Import
        </button>
      </DialogContent>
    </Dialog>
  );
}

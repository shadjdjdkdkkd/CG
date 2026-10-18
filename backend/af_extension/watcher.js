// Injected into every frame: detects new form steps + records clicks for autopilot.
(() => {
  if (window.__afWatcher) return;
  window.__afWatcher = true;
  const FILLABLE = 'input:not([type=hidden]):not([type=submit]):not([type=button]):not([type=file]):not([type=checkbox]):not([type=radio]):not([type=password]):not([type=search]), textarea, select, [contenteditable="true"], kat-input, kat-textarea, kat-dropdown';
  const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const send = (msg) => { try { chrome.runtime.sendMessage(msg); } catch (e) { /* panel closed */ } };
  let timer = null;
  let lastHref = location.href;

  const check = () => {
    if (document.documentElement.hasAttribute("data-af-probing")) return;
    const fresh = afAll(document, FILLABLE + ", " + AF_COMBO).filter((el) => !el.hasAttribute("data-af-id") && !el.disabled && visible(el) && !el.closest("[role=listbox], [role=option], [role=menu]"));
    const hrefChanged = location.href !== lastHref;
    lastHref = location.href;
    if (fresh.length || hrefChanged) send({ type: "af-new-fields", count: fresh.length, href: location.href });
  };
  new MutationObserver(() => { clearTimeout(timer); timer = setTimeout(check, 1200); })
    .observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ["style", "class", "hidden"] });

  const cssPath = (el) => {
    const parts = [];
    while (el && el.nodeType === 1 && parts.length < 6) {
      if (el.id && !/\d{3,}/.test(el.id)) { parts.unshift(`#${CSS.escape(el.id)}`); break; }
      let sel = el.tagName.toLowerCase();
      const sib = el.parentElement ? Array.from(el.parentElement.children).filter((c) => c.tagName === el.tagName) : [];
      if (sib.length > 1) sel += `:nth-of-type(${sib.indexOf(el) + 1})`;
      parts.unshift(sel);
      el = el.parentElement;
    }
    return parts.join(" > ");
  };

  const fieldLabel = (el) => {
    const h = el.getRootNode().host || el;
    const sc = el.getRootNode();
    const l = el.id && sc.querySelector ? sc.querySelector(`label[for="${CSS.escape(el.id)}"]`) : null;
    return (h.getAttribute("label") || el.getAttribute("aria-label") || (l && l.textContent) || el.getAttribute("placeholder") || el.getAttribute("name") || "").replace(/\s+/g, " ").trim().slice(0, 80);
  };
  const fieldOf = (e) => e.composedPath().find((n) => n.nodeType === 1 && n.matches && n.matches("input, textarea, select, [contenteditable=true]"));
  document.addEventListener("change", (e) => {
    if (!e.isTrusted) return;
    const el = fieldOf(e);
    if (!el) return;
    if (el.type === "file") {
      send({ type: "af-step", step: { type: "upload", text: `${el.files ? el.files.length : 0} file(s)`, label: fieldLabel(el), ident: afIdent(el) }, href: location.href });
      return;
    }
    if (["password", "hidden"].includes(el.type)) return;
    const val = el.tagName === "SELECT" ? (el.options[el.selectedIndex] || {}).text : el.type === "checkbox" || el.type === "radio" ? String(el.checked) : el.value || el.textContent;
    send({ type: "af-step", step: { type: el.tagName === "SELECT" ? "select" : "input", text: "", label: fieldLabel(el), ident: afIdent(el), value: String(val || "").slice(0, 60) }, href: location.href });
  }, true);
  document.addEventListener("keydown", (e) => {
    if (!e.isTrusted || e.key !== "Enter") return;
    const el = fieldOf(e);
    if (!el || el.tagName === "TEXTAREA" || el.type === "password") return;
    send({ type: "af-step", step: { type: "enter", text: "Enter", label: fieldLabel(el), ident: afIdent(el), value: String(el.value || "").slice(0, 60) }, href: location.href });
  }, true);
  document.addEventListener("drop", (e) => {
    if (!e.isTrusted || !e.dataTransfer || !e.dataTransfer.files.length) return;
    send({ type: "af-step", step: { type: "upload", text: `${e.dataTransfer.files.length} file(s) dropped` }, href: location.href });
  }, true);

  // ---- Upload button → photos from the product link (no file picker) ----
  const syncImgFlag = () => chrome.storage.local.get(["imgButton", "token", "productId"]).then((st) => {
    document.documentElement.setAttribute("data-af-img", st.imgButton !== false && st.token && st.productId ? "1" : "0");
  }).catch(() => {});
  syncImgFlag();
  chrome.storage.onChanged.addListener(syncImgFlag);
  let upBusy = false;
  const emptyInputs = () => afAll(document, "input[type=file]").filter((f) => !f.disabled && !(f.files && f.files.length) && (!f.accept || /image|jpe?g|png|webp|\*/i.test(f.accept)));
  const putFiles = (inp, files) => {
    const dt = new DataTransfer();
    files.forEach((f) => {
      const bin = atob(f.data.split(",")[1]);
      const arr = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
      dt.items.add(new File([arr], f.name, { type: "image/jpeg" }));
    });
    inp.files = dt.files;
    ["input", "change"].forEach((n) => inp.dispatchEvent(new Event(n, { bubbles: true, composed: true })));
    if (inp.hasAttribute("data-af-detached")) setTimeout(() => inp.remove(), 3000);
  };
  const fillInput = async (inp, pid, fresh) => {
    if (afLimitError()) return { n: 0, left: 0 };
    const r = await chrome.runtime.sendMessage({ type: "af-images", multiple: !!inp.multiple, pid, fresh, limit: afPageImageLimit() }).catch(() => null);
    if (!r || !r.files || !r.files.length) return { n: 0, left: 0 };
    putFiles(inp, r.files);
    return { n: r.files.length, left: r.left };
  };
  // fills every photo: all at once for multi-file inputs, one per slot for single-file inputs
  window.__afUploadAll = async (pid, fresh = true) => {
    if (upBusy) return 0;
    upBusy = true;
    let total = 0;
    try {
      let first = fresh, idle = 0;
      for (let round = 0; round < 20 && idle < 2; round++) {
        const ins = emptyInputs();
        if (!ins.length) {
          if (round === 0 || idle === 0) {
            const opened = afOpenUploader();
            if (!opened && round === 0) return 0;
          }
          idle++;
          await afSleep(1500);
          continue;
        }
        const r = await fillInput(ins[0], pid, first);
        first = false;
        if (!r.n) break;
        total += r.n;
        idle = 0;
        if (!r.left) break;
        await afSleep(1500);
        if (afLimitError()) break;
      }
    } finally { upBusy = false; }
    return total;
  };
  document.addEventListener("af-want-images", (e) => {
    const inp = e.composedPath()[0];
    if (!inp || upBusy) return;
    upBusy = true;
    (async () => {
      try {
        let r = await fillInput(inp, null, false);
        while (r.n && r.left && !inp.multiple) {
          await afSleep(1500);
          if (afLimitError()) break;
          const next = emptyInputs()[0];
          if (!next) break;
          r = await fillInput(next, null, false);
        }
      } finally { upBusy = false; }
    })();
  }, true);
  document.addEventListener("click", (e) => {
    const inp = e.composedPath()[0];
    if (inp && inp.tagName === "INPUT" && inp.type === "file" && document.documentElement.getAttribute("data-af-img") === "1") {
      e.preventDefault();
      inp.dispatchEvent(new CustomEvent("af-want-images", { bubbles: true, composed: true }));
    }
  }, true);

  document.addEventListener("click", (e) => {
    if (!e.isTrusted || document.documentElement.hasAttribute("data-af-probing")) return;
    const path = e.composedPath().filter((n) => n.nodeType === 1);
    const target = path[0];
    if (!target || target.matches("input:not([type=submit]):not([type=button]):not([type=radio]):not([type=checkbox]), textarea, select, [contenteditable=true], kat-input, kat-textarea")) return;
    const CLICKABLE = "button, a, kat-button, kat-link, kat-tab, kat-radiobutton, kat-checkbox, kat-option, [role=button], [role=tab], [role=menuitem], [role=option], input[type=submit], input[type=button], input[type=radio], input[type=checkbox], li";
    const FIELDY = "kat-date-picker, kat-dropdown, kat-predictive-input, kat-combobox, kat-radiobutton, kat-checkbox, kat-toggle, s-dropdown, [role=combobox], [role=listbox], [role=option], [aria-haspopup], [role=radio], [role=checkbox], [role=switch], [data-af-group], [data-af-id], [data-testid*=select i], input[type=radio], input[type=checkbox], label, [data-yesno]";
    const opt = path.find((n) => n.matches && n.matches("[role=option], kat-option, [role=listbox] li"));
    if (opt) {
      const box = opt.closest("[role=listbox]") || opt.parentElement;
      const owner = box && box.id ? afAll(document, `[aria-controls="${CSS.escape(box.id)}"], [aria-owns="${CSS.escape(box.id)}"]`)[0] : null;
      send({ type: "af-step", step: { type: "select", text: (opt.getAttribute("label") || opt.textContent || "").replace(/\s+/g, " ").trim().slice(0, 80), label: owner ? fieldLabel(owner) : "", ident: owner ? afIdent(owner) : "" }, href: location.href });
      return;
    }
    if (path.some((n) => n.matches && n.matches(FIELDY))) return;
    let el = path.find((n) => n.matches && n.matches(CLICKABLE));
    if (!el) return;
    const host = el.getRootNode().host;
    if (host && host.tagName.toLowerCase().startsWith("kat-")) el = host;
    const text = (el.getAttribute("label") || el.innerText || el.textContent || el.value || "").replace(/\s+/g, " ").trim().slice(0, 80);
    send({
      type: "af-click",
      step: { type: "click", text, tag: el.tagName.toLowerCase(), aria: el.getAttribute("aria-label") || "", elem_id: el.id || "", path: cssPath(el) },
      href: location.href,
    });
  }, true);
})();

function afClickStep(step) {
  const norm = (t) => (t || "").replace(/\s+/g, " ").trim().toLowerCase();
  const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  let el = null;
  const shown = (e) => visible(e) || (e.shadowRoot && afAll(e.shadowRoot, "button, a").some(visible));
  if (step.elem_id && !/\d{3,}/.test(step.elem_id) && !/^katal-id/.test(step.elem_id)) el = afAll(document, `[id="${CSS.escape(step.elem_id)}"]`).find(shown) || null;
  if (!el && (step.text || step.aria)) {
    const cands = afAll(document, step.tag || "*").filter(shown);
    el = cands.find((c) => step.aria && c.getAttribute("aria-label") === step.aria)
      || cands.find((c) => step.text && norm(c.getAttribute("label") || c.innerText || c.textContent || c.value) === norm(step.text));
  }
  if (!el && step.path) { try { el = document.querySelector(step.path); } catch (e) { el = null; } }
  if (!el || !shown(el)) return false;
  el.scrollIntoView({ block: "center" });
  const inner = el.tagName.toLowerCase().startsWith("kat-") && el.shadowRoot ? afAll(el.shadowRoot, "button, a").find(visible) : null;
  (inner || el).click();
  return true;
}

function afBanner(msg) {
  document.getElementById("af-done-banner")?.remove();
  const d = document.createElement("div");
  d.id = "af-done-banner";
  d.textContent = msg;
  d.style.cssText = "position:fixed;top:16px;left:50%;transform:translateX(-50%);z-index:2147483647;background:#10B981;color:#04140D;font:600 15px system-ui;padding:14px 22px;border-radius:10px;box-shadow:0 10px 30px rgba(0,0,0,.3);cursor:pointer";
  d.onclick = () => d.remove();
  document.body.appendChild(d);
  setTimeout(() => d.remove(), 15000);
}

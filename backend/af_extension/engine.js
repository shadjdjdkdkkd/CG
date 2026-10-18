// Injected into pages via chrome.scripting.executeScript — must stay self-contained.
function afAll(root, selector) {
  const out = [];
  const walk = (node) => {
    node.querySelectorAll(selector).forEach((e) => out.push(e));
    node.querySelectorAll("*").forEach((e) => { if (e.shadowRoot) walk(e.shadowRoot); });
  };
  walk(root);
  return out;
}

var AF_CUSTOM = "kat-input, kat-textarea, kat-dropdown, kat-combobox, kat-predictive-input, kat-date-picker";
var AF_COMBO = '[role=combobox]:not(input), [aria-haspopup=listbox]:not(input), button[aria-haspopup], [class*="select__control" i], .MuiSelect-select, s-dropdown > div > button, [data-testid*="single-select" i], [data-testid*="multi-select" i]';
var AF_AUTOCOMPLETE = "input[role=combobox], input[aria-autocomplete=list], input[aria-autocomplete=both]";
var AF_EMPTY = /^(|select|select\.\.\.|choose|choose\.\.\.|-+ ?select ?-+|-select-|please select|none)$/i;
var AF_DATE_HINT = /(dd|mm|yyyy|yy)[\/.\- ]|date|expir|best before|manufactur(ed|ing) (on|date)|mfg|launch|valid (till|until)/i;
var AF_NATIVE = 'input, textarea, select, [contenteditable="true"], [contenteditable=""], [role="textbox"]';

function afPick(opts, value) {
  const n = (t) => String(t || "").toLowerCase().replace(/[^a-z0-9%.]+/g, " ").trim();
  const v = n(value);
  if (!v) return null;
  const valid = opts.filter((o) => n(o.name) && !/^(select|select one|choose|--|-select-|please select)$/.test(n(o.name)));
  let m = valid.find((o) => n(o.name) === v || n(o.value) === v) || valid.find((o) => n(o.name).startsWith(v) || v.startsWith(n(o.name)));
  if (m) return m;
  const inc = valid.filter((o) => n(o.name).includes(v) || v.includes(n(o.name)));
  if (inc.length === 1) return inc[0];
  const tv = new Set(v.split(" "));
  let best = null, score = 0;
  valid.forEach((o) => {
    const to = n(o.name).split(" ");
    const hit = to.filter((w) => tv.has(w)).length;
    const sc = hit / Math.max(tv.size, to.length);
    if (sc > score) { score = sc; best = o; }
  });
  return score >= 0.5 ? best : null;
}

function afIdent(el) {
  const h = afHostOf(el) || el;
  const g = (a) => el.getAttribute(a) || h.getAttribute(a) || "";
  return (g("name") || g("data-testid") || (el.id && !/\d{3,}|^katal-id/.test(el.id) ? el.id : "") || g("aria-label") || g("label") || g("placeholder") || "").trim().slice(0, 80);
}
function afPressEnter(el) {
  ["keydown", "keypress", "keyup"].forEach((t) => el.dispatchEvent(new KeyboardEvent(t, { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, composed: true, cancelable: true })));
}
var AF_CHIPS = '[class*="chip" i], [class*="tag-input" i], [class*="tags-input" i], [class*="multi-value" i], [class*="tokenfield" i]';

function afHostOf(el) {
  const root = el.getRootNode && el.getRootNode();
  return root && root.host ? root.host : null;
}

function afKatOptions(el) {
  let opts = el.options;
  if (!Array.isArray(opts)) { try { opts = JSON.parse(el.getAttribute("options") || "[]"); } catch (e) { opts = []; } }
  if (!opts.length) opts = Array.from(el.querySelectorAll("kat-option, option")).map((o) => ({ name: o.textContent.trim(), value: o.getAttribute("value") || o.textContent.trim() }));
  return opts.map((o) => (typeof o === "string" ? { name: o, value: o } : { name: String(o.name ?? o.label ?? o.value ?? ""), value: String(o.value ?? o.name ?? "") })).filter((o) => o.name);
}

function afScan(rootSelector) {
  const root = rootSelector ? document.querySelector(rootSelector) : document;
  if (!root) return [];
  const skip = ["hidden", "submit", "button", "file", "image", "reset", "password", "checkbox", "radio", "search", "color", "range"];
  const clean = (t) => (t || "").replace(/\s+/g, " ").replace(/[*:]+\s*$/, "").trim().slice(0, 120);
  const slug = (t) => (t || "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 40);
  const visible = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length) && getComputedStyle(el).visibility !== "hidden";
  const STRIP = "input,textarea,select,option,script,style,svg,kat-option,[role=listbox],[role=menu],[role=option],ul,[data-af-self]";
  const shortText = (node) => {
    const clone = node.cloneNode(true);
    clone.querySelectorAll(STRIP).forEach((n) => n.remove());
    clone.querySelectorAll("*").forEach((n) => n.append(" "));
    return clean(clone.textContent);
  };
  const textAround = (start) => {
    start.setAttribute("data-af-self", "1");
    try {
      let node = start;
      for (let i = 0; i < 5; i++) {
        let sib = node.previousElementSibling;
        for (let k = 0; sib && k < 3; k++, sib = sib.previousElementSibling) {
          if (sib.matches && sib.matches(STRIP)) continue;
          const t = shortText(sib);
          if (t && t.length < 100) return t;
        }
        node = node.parentElement || (node.getRootNode && node.getRootNode().host);
        if (!node) break;
        const t = shortText(node);
        if (t && t.length < 100) return t;
      }
      return "";
    } finally { start.removeAttribute("data-af-self"); }
  };
  const labelFor = (el) => {
    const host = afHostOf(el);
    const attrs = [el, host].filter(Boolean);
    for (const a of attrs) {
      for (const k of ["label", "aria-label", "data-label", "title"]) if (a.getAttribute && a.getAttribute(k)) return a.getAttribute(k);
    }
    const scope = el.getRootNode ? el.getRootNode() : document;
    const lb = el.getAttribute("aria-labelledby");
    if (lb) {
      const t = lb.split(" ").map((id) => (scope.getElementById ? scope.getElementById(id) : document.getElementById(id))?.textContent || "").join(" ");
      if (t.trim()) return t;
    }
    if (el.id && scope.querySelector) {
      const l = scope.querySelector(`label[for="${CSS.escape(el.id)}"]`);
      if (l && l.textContent.trim()) return l.textContent;
    }
    const wrap = el.closest("label");
    if (wrap && wrap.textContent.trim()) return wrap.textContent;
    return textAround(host || el);
  };

  const custom = afAll(root, AF_CUSTOM).filter((el) => {
    const h = afHostOf(el);
    const n = (el.getAttribute("name") || el.id || "").toLowerCase();
    return !(h && h.tagName.toLowerCase().startsWith("kat-")) && !/^(attributefilter|lp-profile-selector)/.test(n);
  });
  const natives = afAll(root, AF_NATIVE).filter((el) => {
    const h = afHostOf(el);
    return !(h && h.tagName.toLowerCase().startsWith("kat-")) && !el.closest(AF_CUSTOM) && !el.closest("[role=listbox], [role=menu], [data-af-ui]") && !(el.getAttribute("type") === "search" || /^search/i.test(el.getAttribute("placeholder") || ""));
  });
  const combos = afAll(root, AF_COMBO).filter((el) => !el.closest(AF_CUSTOM) && !el.closest("header, nav, [role=banner], [role=navigation]") && !/^(help|settings|menu|profile|account|notifications?)$/i.test((el.getAttribute("aria-label") || el.textContent || "").trim()) && !el.closest("[role=listbox], [data-af-ui]") && !natives.includes(el) && !afAll(el, "input:not([type=hidden]), select, textarea").some((i) => natives.includes(i) && !i.matches(AF_AUTOCOMPLETE)));
  const used = {};
  const fields = [];
  const comboInputs = new Set(combos.flatMap((c) => afAll(c, AF_AUTOCOMPLETE)));
  [...custom, ...combos, ...natives.filter((n) => !comboInputs.has(n))].forEach((el, i) => {
    const tag = el.tagName.toLowerCase();
    const isKat = tag.startsWith("kat-");
    const isCombo = combos.includes(el);
    const isAuto = !isCombo && el.matches(AF_AUTOCOMPLETE);
    const isRich = !isKat && !isCombo && !["input", "textarea", "select"].includes(tag);
    let type = (el.getAttribute("type") || (tag === "input" ? "text" : tag)).toLowerCase();
    if (tag === "input" && skip.includes(type)) return;
    if (isKat && type === "file") return;
    const dateHintText = `${el.getAttribute("placeholder") || ""} ${el.getAttribute("aria-label") || ""} ${el.getAttribute("name") || ""} ${el.getAttribute("label") || ""}`;
    const isDate = ["date", "month", "datetime-local", "week"].includes(type) || tag === "kat-date-picker" || (tag === "input" && type === "text" && AF_DATE_HINT.test(dateHintText));
    if (el.disabled || el.hasAttribute("disabled") || el.getAttribute("aria-disabled") === "true" || (!isKat && !isAuto && !isCombo && !isDate && el.readOnly) || !visible(el)) return;
    if (isDate) {
      const ph = (el.getAttribute("placeholder") || "").toUpperCase();
      const fmt = ["date", "month", "datetime-local", "week"].includes(type) ? type : (ph.match(/(DD|MM|YYYY|YY)([\/.\- ])(DD|MM)\2(DD|MM|YYYY|YY)/) || [])[0] || (tag === "kat-date-picker" ? "MM/DD/YYYY" : "DD/MM/YYYY");
      el.setAttribute("data-af-datefmt", fmt);
    }
    const label = clean(labelFor(el));
    const placeholder = clean(el.getAttribute("placeholder") || el.getAttribute("data-placeholder") || el.getAttribute("aria-placeholder"));
    let base = el.getAttribute("name") || el.getAttribute("data-testid") || el.id || slug(label) || slug(placeholder) || "field";
    base = base.slice(0, 60);
    used[base] = (used[base] || 0) + 1;
    const key = used[base] > 1 ? `${base}_${used[base]}` : base;
    const afId = el.getAttribute("data-af-id") || `af-${i}-${Math.random().toString(36).slice(2, 7)}`;
    el.setAttribute("data-af-id", afId);
    let options = [];
    if (tag === "select") options = Array.from(el.options).map((o) => o.text.trim()).filter(Boolean).slice(0, 400);
    else if (tag === "kat-dropdown" || tag === "kat-combobox") { options = afKatOptions(el).map((o) => o.name); type = "select"; }
    else if (isCombo || isAuto) type = "select";
    if (isDate) type = "date";
    const kind = isCombo ? "combo" : isAuto ? "autocomplete" : (tag === "kat-predictive-input" || tag === "kat-combobox") ? "katpredict" : isKat ? "kat" : isRich ? "rich" : "native";
    const comboText = isCombo ? clean(el.textContent) : "";
    const ml = parseInt(el.getAttribute("maxlength"), 10);
    fields.push({
      af_id: afId, key, label: isCombo && label === comboText ? "" : label, placeholder: placeholder || (isCombo ? comboText : ""), tag, kind, options: options.slice(0, 400), ident: afIdent(el),
      type: isRich ? "richtext" : type,
      maxlength: ml > 0 ? ml : null,
      current_value: isCombo ? (AF_EMPTY.test(comboText) ? "" : comboText) : String((isRich ? el.textContent : el.value) || "").slice(0, 500),
    });
  });
  [...afRadioGroups(root), ...afChoiceButtons(root)].forEach((g) => {
    used[g.key] = (used[g.key] || 0) + 1;
    fields.push({ ...g, key: used[g.key] > 1 ? `${g.key}_${used[g.key]}` : g.key });
  });
  return fields;
}

function afRadioGroups(root) {
  const clean = (t) => (t || "").replace(/\s+/g, " ").replace(/[*:]+\s*$/, "").trim().slice(0, 120);
  const textOf = (r) => {
    if (r.getAttribute("label")) return r.getAttribute("label");
    if (r.getAttribute("aria-label")) return r.getAttribute("aria-label");
    const sc = r.getRootNode();
    if (r.id && sc.querySelector) { const l = sc.querySelector(`label[for="${CSS.escape(r.id)}"]`); if (l) return l.textContent; }
    const wrap = r.closest("label");
    if (wrap) return wrap.textContent;
    return r.textContent || (r.nextSibling && r.nextSibling.textContent) || r.value || "";
  };
  const groups = new Map();
  afAll(root, "kat-radiobutton").forEach((r) => {
    const nm = r.getAttribute("name") || (r.parentElement && r.parentElement.getAttribute("name")) || "";
    const k = `kat:${nm || (r.parentElement ? Array.from(r.parentElement.parentElement?.children || []).indexOf(r.parentElement) : 0)}`;
    if (!groups.has(k)) groups.set(k, { container: r.closest("kat-radiobutton-group, fieldset, [role=radiogroup]") || r.parentElement, items: [] });
    groups.get(k).items.push(r);
  });
  afAll(root, "input[type=radio]").forEach((r) => {
    const h = afHostOf(r);
    if (h && h.tagName.toLowerCase() === "kat-radiobutton") return;
    const k = r.name ? `name:${r.name}` : null;
    if (!k) return;
    if (!groups.has(k)) groups.set(k, { container: r.closest("fieldset, [role=radiogroup]") || null, items: [] });
    groups.get(k).items.push(r);
  });
  afAll(root, "[role=radiogroup], kat-radiobutton-group").forEach((g, i) => {
    if (afAll(g, "input[type=radio]").length) return;
    const items = afAll(g, "[role=radio], kat-radiobutton");
    if (items.length) groups.set(`group:${i}`, { container: g, items });
  });
  const out = [];
  let n = 0;
  groups.forEach((g, k) => {
    const items = g.items.filter((r) => afVisible(r) || afVisible(r.closest("label") || r.parentElement || r));
    if (items.length < 2) return;
    const gid = `afg-${n++}-${Math.random().toString(36).slice(2, 6)}`;
    items.forEach((r) => r.setAttribute("data-af-group", gid));
    let label = "";
    const c = g.container;
    if (c) label = c.getAttribute("label") || c.getAttribute("aria-label") || (c.querySelector("legend") || {}).textContent || "";
    if (!label) {
      let node = (c || items[0]).parentElement;
      for (let i = 0; i < 4 && node && !label; i++, node = node.parentElement) {
        const clone = node.cloneNode(true);
        clone.querySelectorAll("input, label, [role=radio], kat-radiobutton").forEach((x) => x.remove());
        const t = clean(clone.textContent);
        if (t && t.length < 140) label = t;
      }
    }
    const options = items.map((r) => clean(textOf(r))).filter(Boolean);
    const checked = items.find((r) => r.checked === true || r.getAttribute("aria-checked") === "true" || (r.tagName !== "INPUT" && r.hasAttribute("checked")));
    out.push({
      af_id: gid, key: (k.startsWith("name:") ? k.slice(5) : k.startsWith("kat:") && !/^kat:\d+$/.test(k) ? k.slice(4) : clean(label).toLowerCase().replace(/[^a-z0-9]+/g, "_").slice(0, 40)) || "choice",
      label: clean(label), placeholder: "", tag: "radio", kind: "radio", type: "select", options, maxlength: null,
      current_value: checked ? clean(textOf(checked)) : "",
    });
  });
  return out;
}

var AF_NAV_WORDS = /^(next|back|previous|save|submit|cancel|continue|close|done|add|delete|remove|edit|upload|browse|search|apply|ok|sign in|log ?in|menu|more|help|publish)\b/i;
function afChoiceButtons(root) {
  const clean = (t) => (t || "").replace(/\s+/g, " ").replace(/[*:]+\s*$/, "").trim().slice(0, 140);
  const btnText = (b) => clean(b.getAttribute("label") || b.getAttribute("aria-label") || b.textContent || b.value);
  const out = [];
  let n = 0;
  const labelAround = (start, strip) => {
    let node = start.parentElement || (start.getRootNode().host);
    for (let i = 0; i < 4 && node; i++, node = node.parentElement) {
      const clone = node.cloneNode(true);
      clone.querySelectorAll(strip).forEach((x) => x.remove());
      const t = clean(clone.textContent);
      if (t && t.length < 160) return t;
    }
    return "";
  };
  // groups of 2-5 sibling choice buttons (Yes / No, Applicable / Not applicable …)
  const BTN = "button, [role=button], kat-button, [aria-pressed], kat-segmented-control-item, [role=tab][aria-selected]";
  const parents = new Set();
  afAll(root, BTN).forEach((b) => { if (b.parentElement && afVisible(b)) parents.add(b.parentElement); });
  parents.forEach((p) => {
    if (p.closest("[data-af-ui], nav, header, [role=tablist], [role=menu], [role=listbox]")) return;
    const items = Array.from(p.children).filter((c) => c.matches(BTN) && afVisible(c));
    if (items.length < 2 || items.length > 5) return;
    const texts = items.map(btnText);
    if (texts.some((t) => !t || t.length > 30 || AF_NAV_WORDS.test(t))) return;
    const choicey = texts.some((t) => /^(yes|no|true|false|applicable|not applicable|n\/a|none|male|female|unisex)$/i.test(t)) || items.some((c) => c.hasAttribute("aria-pressed"));
    if (!choicey) return;
    const gid = `afb-${n++}-${Math.random().toString(36).slice(2, 6)}`;
    items.forEach((c) => c.setAttribute("data-af-group", gid));
    const sel = items.find((c) => c.getAttribute("aria-pressed") === "true" || c.getAttribute("aria-selected") === "true" || c.getAttribute("aria-checked") === "true" || /\b(active|selected|checked)\b/i.test(c.className || ""));
    const label = labelAround(p, BTN);
    out.push({ af_id: gid, key: label.toLowerCase().replace(/[^a-z0-9]+/g, "_").slice(0, 40) || "choice", label, placeholder: "", tag: "buttons", kind: "radio", type: "select", options: texts, maxlength: null, current_value: sel ? btnText(sel) : "" });
  });
  // single switches / checkboxes → Yes / No
  afAll(root, "[role=switch], [role=checkbox], kat-toggle, kat-checkbox, input[type=checkbox]").forEach((c) => {
    if (c.closest("[data-af-ui], [role=listbox], [role=menu], table") || c.hasAttribute("data-af-group")) return;
    const vis = afVisible(c) || (c.closest("label") && afVisible(c.closest("label")));
    if (!vis || c.disabled) return;
    const sc = c.getRootNode();
    const l = c.id && sc.querySelector ? sc.querySelector(`label[for="${CSS.escape(c.id)}"]`) : null;
    const label = clean(c.getAttribute("label") || c.getAttribute("aria-label") || (l && l.textContent) || (c.closest("label") || {}).textContent || labelAround(c, "input"));
    if (!label || /select all|remember me/i.test(label)) return;
    const gid = `aft-${n++}-${Math.random().toString(36).slice(2, 6)}`;
    c.setAttribute("data-af-group", gid);
    const on = c.checked || c.getAttribute("aria-checked") === "true" || c.hasAttribute("checked");
    out.push({ af_id: gid, key: label.toLowerCase().replace(/[^a-z0-9]+/g, "_").slice(0, 40), label, placeholder: "", tag: "toggle", kind: "toggle", type: "select", options: ["Yes", "No"], maxlength: null, current_value: on ? "Yes" : "" });
  });
  return out;
}

function afSetToggle(gid, value) {
  const c = afAll(document, `[data-af-group="${gid}"]`)[0];
  if (!c) return false;
  const want = /^(yes|true|on|1|checked|applicable)$/i.test(String(value).trim());
  const isOn = () => c.checked || c.getAttribute("aria-checked") === "true" || c.hasAttribute("checked");
  if (want === isOn()) return true;
  const target = c.tagName === "INPUT" && !afVisible(c) ? (c.closest("label") || c.parentElement) : c;
  afMouse(target);
  if (c.tagName === "INPUT" && c.checked !== want) { c.checked = want; c.dispatchEvent(new Event("change", { bubbles: true, composed: true })); }
  return true;
}

var AF_NEXT = /^(continue to\b.*|continue|next|next step|save and continue|save & continue|save and next|proceed|go to next.*)$/i;
function afBtnText(b) { return (b.getAttribute("label") || b.getAttribute("aria-label") || b.innerText || b.textContent || b.value || "").replace(/\s+/g, " ").trim(); }
function afClickEl(el) {
  el.scrollIntoView({ block: "center" });
  const inner = el.tagName.toLowerCase().startsWith("kat-") && el.shadowRoot ? afAll(el.shadowRoot, "button, a").find(afVisible) : null;
  (inner || el).click();
}
function afFindNext(doClick) {
  const c = afAll(document, "kat-button, button, a, [role=button], input[type=submit]").filter((b) => {
    const h = afHostOf(b);
    if (h && h.tagName.toLowerCase() === "kat-button") return false;
    const shown = afVisible(b) || (b.shadowRoot && afAll(b.shadowRoot, "button").some(afVisible));
    return shown && !b.disabled && !b.hasAttribute("disabled") && b.getAttribute("aria-disabled") !== "true" && AF_NEXT.test(afBtnText(b));
  });
  const pick = c.find((b) => /^continue to/i.test(afBtnText(b))) || c.find((b) => /continue|next/i.test(afBtnText(b))) || c[0];
  if (!pick) return "";
  if (doClick) afClickEl(pick);
  return afBtnText(pick);
}
var AF_UPLOAD = /^\+?\s*(upload|add)\s+(product\s+|more\s+)?(images?|photos?|pictures?)\b|^upload$|^browse( files?)?$|^select (images?|photos?|files?)|^choose (images?|photos?|files?)/i;
function afOpenUploader() {
  const b = afAll(document, "kat-button, button, a, [role=button], label").filter((x) => afVisible(x) || (x.shadowRoot && afAll(x.shadowRoot, "button").some(afVisible)))
    .find((x) => AF_UPLOAD.test(afBtnText(x)));
  if (!b) return false;
  afClickEl(b);
  return true;
}
function afTopTitles() {
  const t = new Set();
  const add = (s) => { s = (s || "").replace(/\s+/g, " ").trim(); if (s.length > 15 && s.length < 260) t.add(s); };
  document.querySelectorAll('[data-component-type="s-search-result"] h2').forEach((e) => add(e.getAttribute("aria-label") || e.textContent));
  document.querySelectorAll('a[href*="/p/"][title], a[href*="/p/"] img[alt]').forEach((e) => add(e.getAttribute("title") || e.getAttribute("alt")));
  document.querySelectorAll(".product-base").forEach((e) => add([e.querySelector(".product-brand")?.textContent, e.querySelector(".product-product")?.textContent].join(" ")));
  document.querySelectorAll('[class*="ProductTitle" i], [class*="product-title" i]').forEach((e) => add(e.textContent));
  if (t.size < 3) document.querySelectorAll("h2, h3, h4").forEach((e) => add(e.textContent));
  return [...t].slice(0, 15);
}

function afFileInputs() {
  const ins = [];
  afAll(document, "input[type=file]").forEach((f) => ins.push(f));
  afAll(document, "kat-file-upload").forEach((k) => { if (!(k.shadowRoot && afAll(k.shadowRoot, "input[type=file]").length)) ins.push(k); });
  return ins.filter((f) => !f.disabled && !(f.files && f.files.length)).map((f, i) => {
    const id = f.getAttribute("data-af-file") || `aff-${i}-${Math.random().toString(36).slice(2, 6)}`;
    f.setAttribute("data-af-file", id);
    return { id, multiple: !!f.multiple, accept: f.getAttribute("accept") || "" };
  });
}

function afSetFiles(id, files) {
  const input = afAll(document, `[data-af-file="${id}"]`)[0];
  if (!input) return 0;
  const dt = new DataTransfer();
  files.forEach((f) => {
    const bin = atob(f.data.split(",")[1]);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    dt.items.add(new File([arr], f.name, { type: "image/jpeg" }));
  });
  if (input.tagName === "INPUT") {
    input.files = dt.files;
    ["input", "change"].forEach((n) => input.dispatchEvent(new Event(n, { bubbles: true, composed: true })));
  }
  const zone = input.tagName !== "INPUT" ? input : null;
  if (zone) ["dragenter", "dragover", "drop"].forEach((n) => zone.dispatchEvent(new DragEvent(n, { bubbles: true, composed: true, cancelable: true, dataTransfer: dt })));
  return files.length;
}

function afSelectRadio(gid, value, onlyEmpty) {
  const items = afAll(document, `[data-af-group="${gid}"]`);
  if (!items.length || !value) return false;
  if (onlyEmpty && items.some((r) => r.checked === true || r.getAttribute("aria-checked") === "true")) return false;
  const v = String(value).toLowerCase().trim();
  const txt = (r) => {
    const sc = r.getRootNode();
    const l = r.id && sc.querySelector ? sc.querySelector(`label[for="${CSS.escape(r.id)}"]`) : null;
    return (r.getAttribute("label") || r.getAttribute("aria-label") || (l && l.textContent) || (r.closest("label") || {}).textContent || r.textContent || r.value || "").replace(/\s+/g, " ").trim().toLowerCase();
  };
  const pr = afPick(items.map((r) => ({ name: txt(r), value: (r.getAttribute("value") || "").toLowerCase(), el: r })), v);
  const m = pr ? pr.el : null;
  if (!m) return { ok: false, options: items.map(txt).filter(Boolean) };
  const target = m.tagName === "INPUT" && !afVisible(m) ? (m.closest("label") || m.parentElement) : m;
  afMouse(target);
  if (m.tagName === "INPUT" && !m.checked) { m.checked = true; m.dispatchEvent(new Event("change", { bubbles: true, composed: true })); }
  if (m.tagName.toLowerCase() === "kat-radiobutton") {
    const inner = m.shadowRoot ? afAll(m.shadowRoot, "input")[0] : null;
    if (inner && !inner.checked) inner.click();
    m.checked = true;
    m.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
  }
  return true;
}

function afIsRed(el) {
  const m = (getComputedStyle(el).color || "").match(/(\d+),\s*(\d+),\s*(\d+)/);
  return !!m && +m[1] > 170 && +m[2] < 110 && +m[3] < 110;
}
function afRedText(scope) {
  const clean = (t) => (t || "").replace(/\s+/g, " ").trim();
  return afAll(scope, "span, div, p, small, label, li, em").filter((e) => {
    const t = clean(e.textContent);
    return t.length > 3 && t.length < 200 && !/^\*+$/.test(t) && !e.querySelector("input, select, textarea, button") && afVisible(e) && afIsRed(e) && !Array.from(e.children).some((c) => clean(c.textContent) === t);
  }).map((e) => clean(e.textContent).replace(/^\*\s*/, ""));
}
function afBorderRed(el) {
  const m = (getComputedStyle(el).borderBottomColor || "").match(/(\d+),\s*(\d+),\s*(\d+)/);
  return !!m && +m[1] > 180 && +m[2] < 100 && +m[3] < 100;
}
function afErrors() {
  const clean = (t) => (t || "").replace(/\s+/g, " ").trim();
  const sel = '[role=alert], [aria-live=assertive], kat-alert, .a-alert-content, [class*="error" i]:not(input):not(textarea):not(select):not(body):not(html), [class*="invalid-feedback" i], [class*="helper-text" i][class*="error" i]';
  const messages = [...new Set([...afAll(document, sel).filter(afVisible).map((e) => clean(e.getAttribute("description") || e.textContent)), ...afRedText(document)].filter((t) => t && t.length > 2 && t.length < 300))].slice(0, 20);
  const fieldErrors = {};
  afAll(document, "[data-af-id], [data-af-group]").forEach((el) => {
    const id = el.getAttribute("data-af-id") || el.getAttribute("data-af-group");
    const invalid = el.getAttribute("aria-invalid") === "true" || el.hasAttribute("error") || el.getAttribute("state") === "error" || (el.matches && el.matches(":invalid") && el.value);
    let msg = el.getAttribute("error") || el.getAttribute("constraint-message") || "";
    const ids = (el.getAttribute("aria-errormessage") || el.getAttribute("aria-describedby") || "").split(" ").filter(Boolean);
    ids.forEach((i) => { const d = document.getElementById(i); if (d && afVisible(d)) msg = msg || clean(d.textContent); });
    if (!msg) {
      let node = el.parentElement;
      for (let i = 0; i < 3 && node && !msg; i++, node = node.parentElement) {
        const e = Array.from(node.querySelectorAll('[class*="error" i], [role=alert]')).find((x) => afVisible(x) && clean(x.textContent));
        if (e) msg = clean(e.textContent);
        else if (i < 2) { const r = afRedText(node).find((t) => t.length > 3); if (r) msg = r; }
      }
    }
    if (!msg && !invalid && el.tagName && afVisible(el) && afBorderRed(el)) msg = "Field marked red — value rejected";
    if (invalid || msg) fieldErrors[id] = (msg || el.validationMessage || "Invalid value").slice(0, 200);
  });
  return { messages, fieldErrors };
}

function afFormatDate(value, fmt) {
  const v = String(value).trim();
  let y, m, d, t = "00:00";
  let r = v.match(/(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ](\d{2}:\d{2}))?/);
  if (r) { [y, m, d] = [r[1], r[2], r[3]]; if (r[4]) t = r[4]; }
  else if ((r = v.match(/(\d{1,2})[\/.\- ](\d{1,2})[\/.\- ](\d{4})/))) { [d, m, y] = [r[1], r[2], r[3]]; }
  else { const dt = new Date(v); if (isNaN(dt)) return v; [y, m, d] = [dt.getFullYear(), dt.getMonth() + 1, dt.getDate()]; }
  const p = (n) => String(n).padStart(2, "0");
  if (fmt === "date") return `${y}-${p(m)}-${p(d)}`;
  if (fmt === "month") return `${y}-${p(m)}`;
  if (fmt === "datetime-local") return `${y}-${p(m)}-${p(d)}T${t}`;
  if (fmt === "week") return v;
  return fmt.replace("YYYY", y).replace("YY", String(y).slice(2)).replace("MM", p(m)).replace("DD", p(d));
}

function afFill(map, onlyEmpty, enterIdents) {
  const enters = new Set(enterIdents || []);
  let filled = 0;
  const ev = (el, name) => el.dispatchEvent(new Event(name, { bubbles: true, composed: true }));
  const setNative = (el, val) => {
    const proto = el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : el.tagName === "SELECT" ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
    setter ? setter.call(el, val) : (el.value = val);
  };
  const pick = afPick;
  const misses = [];
  const all = {};
  afAll(document, "[data-af-id]").forEach((e) => (all[e.getAttribute("data-af-id")] = e));
  Object.entries(map).forEach(([afId, value]) => {
    if (value === undefined || value === null || value === "") return;
    const el = all[afId];
    if (!el || el.matches(AF_COMBO) || el.matches(AF_AUTOCOMPLETE) || /^kat-(predictive-input|combobox)$/i.test(el.tagName)) return;
    const v = el.hasAttribute("data-af-datefmt") ? afFormatDate(value, el.getAttribute("data-af-datefmt")) : String(value);
    const tag = el.tagName.toLowerCase();
    const isKat = tag.startsWith("kat-");
    const isRich = !isKat && !["input", "textarea", "select"].includes(tag);
    const cur = isRich ? el.textContent.trim() : el.value;
    if (onlyEmpty && (cur || el.hasAttribute("data-af-chipped"))) return;
    if (tag === "select") {
      const all_ = Array.from(el.options).map((o) => ({ name: o.text.trim(), value: o.value }));
      const opt = pick(all_, v);
      if (!opt) { misses.push({ af_id: afId, wanted: v, options: all_.map((o) => o.name).filter(Boolean).slice(0, 400) }); return; }
      setNative(el, opt.value);
    } else if (tag === "kat-dropdown" || tag === "kat-combobox") {
      const all_ = afKatOptions(el);
      const opt = pick(all_, v);
      if (!opt) { misses.push({ af_id: afId, wanted: v, options: all_.map((o) => o.name).slice(0, 400) }); return; }
      el.value = opt.value;
    } else if (isKat) {
      const ml = parseInt(el.getAttribute("maxlength"), 10);
      const val = ml > 0 ? v.slice(0, ml) : v;
      el.value = val;
      const inner = el.shadowRoot ? afAll(el.shadowRoot, "input, textarea")[0] : null;
      if (inner) { setNative(inner, val); ev(inner, "input"); ev(inner, "change"); }
      if (enters.has(afIdent(el))) afPressEnter(inner || el);
    } else if (isRich) {
      el.focus();
      el.textContent = v;
    } else {
      el.focus();
      const ml = parseInt(el.getAttribute("maxlength"), 10);
      const chips = tag === "input" && el.closest(AF_CHIPS);
      if (chips || (tag === "input" && enters.has(afIdent(el)))) {
        if (el.getAttribute("data-af-chipped") === v) return;
        const parts = chips ? v.split(/[,;|\n]+/).map((x) => x.trim()).filter(Boolean).slice(0, 10) : [v];
        parts.forEach((part) => { setNative(el, ml > 0 ? part.slice(0, ml) : part); ev(el, "input"); afPressEnter(el); });
        el.setAttribute("data-af-chipped", v);
      } else setNative(el, ml > 0 ? v.slice(0, ml) : v);
    }
    ["input", "change", "blur"].forEach((n) => ev(el, n));
    el.style.transition = "box-shadow .3s";
    el.style.boxShadow = "0 0 0 2px #10B981";
    setTimeout(() => (el.style.boxShadow = ""), 2500);
    filled++;
  });
  return { filled, misses };
}

var afSleep = (ms) => new Promise((r) => setTimeout(r, ms));
function afMouse(el) {
  el.scrollIntoView({ block: "center" });
  ["pointerdown", "mousedown", "pointerup", "mouseup", "click"].forEach((t) => el.dispatchEvent(new MouseEvent(t, { bubbles: true, composed: true, cancelable: true, view: window })));
}
function afVisible(el) { return !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length); }
function afOptionsFor(el, before) {
  const ids = [el.getAttribute("aria-controls"), el.getAttribute("aria-owns"), ...afAll(el, "[aria-controls]").map((c) => c.getAttribute("aria-controls"))].filter(Boolean);
  let list = [];
  for (const id of ids) {
    const box = document.getElementById(id);
    if (box) list = afAll(box, "[role=option], li").filter(afVisible);
    if (list.length) break;
  }
  if (!list.length) list = afAll(document, "[role=option]").filter(afVisible);
  if (!list.length && before) list = afAll(document, "li").filter((li) => !before.has(li) && afVisible(li));
  if (!list.length && window.__afVisBefore) {
    const prev = window.__afVisBefore;
    const fresh = afAll(document, "div, span, li, button, a, p, label, kat-option").filter((e) => !prev.has(e) && afVisible(e) && !e.contains(el) && !el.contains(e) && !e.querySelector("input"));
    const cand = fresh.filter((e) => { const t = (e.textContent || "").trim(); return t && t.length < 80 && !Array.from(e.children).some((c) => (c.textContent || "").trim() === t); });
    list = cand.filter((e) => !cand.some((o) => o !== e && e.contains(o)));
  }
  return list.map((o) => ({ el: o, text: (o.getAttribute("label") || o.textContent || "").replace(/\s+/g, " ").trim() })).filter((o) => o.text && o.text.length < 120);
}
function afClose(el) {
  ["keydown", "keyup"].forEach((t) => (document.activeElement || el).dispatchEvent(new KeyboardEvent(t, { key: "Escape", code: "Escape", keyCode: 27, bubbles: true, composed: true })));
  if (el.getAttribute("aria-expanded") === "true") afMouse(el);
}
function afScrollHost(list) {
  for (const o of list.slice(0, 5)) {
    let n = o.el.parentElement;
    for (let i = 0; i < 6 && n && n !== document.body; i++, n = n.parentElement) {
      if (n.scrollHeight > n.clientHeight + 8 && /(auto|scroll)/.test(getComputedStyle(n).overflowY)) return n;
    }
  }
  return null;
}
async function afScrollStep(box, frac) {
  const last = box.scrollTop;
  box.scrollTop += Math.max(40, box.clientHeight * frac);
  box.dispatchEvent(new Event("scroll", { bubbles: true }));
  await afSleep(140);
  return box.scrollTop !== last;
}
async function afAllOptions(el, before) {
  const list = afOptionsFor(el, before);
  const seen = new Map(list.map((o) => [o.text, o]));
  const box = afScrollHost(list);
  if (box) {
    for (let i = 0; i < 120 && (await afScrollStep(box, 0.8)); i++) afOptionsFor(el, before).forEach((o) => { if (!seen.has(o.text)) seen.set(o.text, o); });
    afOptionsFor(el, before).forEach((o) => { if (!seen.has(o.text)) seen.set(o.text, o); });
  }
  return { opts: [...seen.values()], box };
}
async function afClickOptionText(el, before, text, box) {
  const find = () => afOptionsFor(el, before).find((o) => o.text === text && o.el.isConnected);
  let hit = find();
  if (!hit && box) {
    box.scrollTop = 0;
    await afSleep(140);
    hit = find();
    for (let i = 0; i < 120 && !hit && (await afScrollStep(box, 0.6)); i++) hit = find();
  }
  if (!hit) return false;
  afMouse(hit.el);
  return true;
}
async function afProbe(ids) {
  document.documentElement.setAttribute("data-af-probing", "1");
  const out = {};
  try {
    for (const id of ids) {
      const el = afAll(document, `[data-af-id="${id}"]`)[0];
      if (!el) continue;
      const before = new Set(afAll(document, "li"));
      window.__afVisBefore = new Set(afAll(document, "div, span, li, button, a, p, label, kat-option").filter(afVisible));
      afMouse(el);
      await afSleep(500);
      out[id] = [...new Set((await afAllOptions(el, before)).opts.map((o) => o.text))].filter((t) => !/^(search|select( one)?|check)$/i.test(t)).slice(0, 400);
      window.__afVisBefore = null;
      afClose(el);
      await afSleep(200);
    }
  } finally { document.documentElement.removeAttribute("data-af-probing"); }
  return out;
}
async function afSelectCustom(id, value, kind, onlyEmpty) {
  const el = afAll(document, `[data-af-id="${id}"]`)[0];
  if (!el || !value) return false;
  const v = String(value).toLowerCase().trim();
  if (onlyEmpty) {
    const cur = kind === "combo" ? el.textContent.replace(/\s+/g, " ").trim() : el.value;
    if (cur && !AF_EMPTY.test(cur)) return false;
  }
  document.documentElement.setAttribute("data-af-probing", "1");
  try {
    const before = new Set(afAll(document, "li"));
    window.__afVisBefore = new Set(afAll(document, "div, span, li, button, a, p, label, kat-option").filter(afVisible));
    if (kind === "katpredict") {
      const inner = el.shadowRoot ? afAll(el.shadowRoot, "input")[0] : null;
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      if (inner) { inner.focus(); setter.call(inner, String(value)); ["input", "keyup"].forEach((n) => inner.dispatchEvent(new Event(n, { bubbles: true, composed: true }))); }
      try { el.value = String(value); } catch (e) { /* read-only */ }
      await afSleep(900);
      const opts = afAll(el.shadowRoot || el, "[role=option], kat-option, li").filter(afVisible).map((o) => ({ el: o, text: (o.getAttribute("label") || o.textContent || "").replace(/\s+/g, " ").trim() })).filter((o) => o.text);
      const hit = afPick(opts.map((o) => ({ name: o.text, value: o.text, el: o.el })), value);
      if (hit) afMouse(hit.el);
      el.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
      el.style.boxShadow = "0 0 0 2px #10B981";
      setTimeout(() => (el.style.boxShadow = ""), 2500);
      return true;
    }
    if (kind === "autocomplete") {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
      el.focus();
      setter.call(el, String(value));
      el.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
    } else afMouse(el);
    let opts = [];
    let box = null;
    for (let i = 0; i < 8 && !opts.length; i++) { await afSleep(250); opts = afOptionsFor(el, before); }
    if (opts.length) ({ opts, box } = await afAllOptions(el, before));
    if (kind === "autocomplete" && !opts.length) { afPressEnter(el); await afSleep(300); return true; }
    const pk = afPick(opts.map((o) => ({ name: o.text, value: o.text, el: o.el })), value);
    const match = pk ? { el: pk.el, text: pk.name } : null;
    if (!match) {
      const prevVis = window.__afVisBefore || new Set();
      const search = afAll(document, "[role=listbox] input, [role=dialog] input[type=search], [class*=menu] input, input[placeholder*=search i], input[type=search]").find((i) => afVisible(i) && !prevVis.has(i) && i !== el);
      if (search && kind !== "autocomplete") {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set.call(search, String(value));
        search.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
        await afSleep(700);
        const againOpts = afOptionsFor(el, before);
        const again = afPick(againOpts.map((o) => ({ name: o.text, value: o.text, el: o.el })), value);
        if (again) { afMouse(again.el); return true; }
        if (!againOpts.length) { afPressEnter(search); await afSleep(300); }
      }
      const seenOpts = [...new Set(opts.map((o) => o.text))].filter((t) => !/^(search|select( one)?|check)$/i.test(t)).slice(0, 400);
      afClose(el);
      return { ok: false, options: seenOpts };
    }
    if (!(await afClickOptionText(el, before, match.text, box))) afMouse(match.el);
    await afSleep(250);
    el.style.boxShadow = "0 0 0 2px #10B981";
    setTimeout(() => (el.style.boxShadow = ""), 2500);
    return true;
  } finally { document.documentElement.removeAttribute("data-af-probing"); window.__afVisBefore = null; }
}

function afDiagnose() {
  const tags = {};
  let shadowHosts = 0;
  const walk = (node) => node.querySelectorAll("*").forEach((e) => {
    const t = e.tagName.toLowerCase();
    if (t.includes("-")) tags[t] = (tags[t] || 0) + 1;
    if (e.shadowRoot) { shadowHosts++; walk(e.shadowRoot); }
  });
  walk(document);
  const samples = afAll(document, `${AF_CUSTOM}, ${AF_NATIVE}`).slice(0, 25).map((e) => e.outerHTML.slice(0, 300));
  return {
    url: location.href,
    title: document.title,
    is_top: window.top === window,
    iframes: Array.from(document.querySelectorAll("iframe")).map((f) => f.src || "(inline)").slice(0, 15),
    light_inputs: document.querySelectorAll("input, textarea, select").length,
    deep_inputs: afAll(document, "input, textarea, select").length,
    contenteditable: afAll(document, "[contenteditable]").length,
    role_textbox: afAll(document, "[role=textbox], [role=combobox]").length,
    custom_dropdowns: afAll(document, AF_COMBO).length,
    dropdown_samples: afAll(document, AF_COMBO).slice(0, 10).map((e) => e.outerHTML.slice(0, 300)),
    shadow_hosts: shadowHosts,
    custom_tags: Object.entries(tags).sort((a, b) => b[1] - a[1]).slice(0, 30),
    detected_fields: afScan().length,
    samples,
  };
}

var AF_PLATFORMS = [["amazon", ["amazon"]], ["flipkart", ["flipkart"]], ["myntra", ["myntra"]], ["meesho", ["meesho"]], ["nykaa", ["nykaa"]], ["instamart", ["instamart", "swiggy"]], ["jiomart", ["jiomart"]], ["ajio", ["ajio"]], ["blinkit", ["blinkit", "grofers"]], ["zepto", ["zepto", "zeptonow"]], ["tata1mg", ["1mg"]]];
var AF_LIMIT_RE = [/(?:up ?to|upto|maximum(?: of)?|max\.?|at most|not more than)\s*(\d{1,2})\s*(?:product\s+)?(?:images?|photos?|pictures?|files?)/i, /(\d{1,2})\s*(?:images?|photos?|pictures?)\s*(?:max(?:imum)?|allowed|can be uploaded)/i];
var AF_LIMIT_ERR = /(limit|maximum|max).{0,30}(images?|photos?|files?).{0,20}(reached|exceed|allowed)|cannot (upload|add) more|too many (images?|photos?|files?)|exceed(s|ed)? the (maximum|limit)/i;
function afPageImageLimit() {
  const txt = (document.body ? document.body.innerText : "").slice(0, 60000);
  for (const re of AF_LIMIT_RE) { const m = txt.match(re); if (m && +m[1] > 0 && +m[1] <= 30) return +m[1]; }
  return 0;
}
function afLimitError() {
  return [...afRedText(document), ...afAll(document, "[role=alert], [aria-live]").filter(afVisible).map((e) => e.textContent || "")].some((t) => AF_LIMIT_ERR.test(t));
}

function afPageInfo(url) {
  const u = new URL(url);
  const host = u.hostname;
  const where = (host + u.pathname).toLowerCase();
  const platform = (AF_PLATFORMS.find(([, words]) => words.some((w) => where.includes(w))) || ["other"])[0];
  const hash = (u.hash || "").split("?")[0].replace(/^#!?/, "");
  const path = (u.pathname + (hash.startsWith("/") ? "#" + hash : "")).replace(/\d{3,}/g, "*").replace(/\/[A-Z0-9]{10}(?=\/|$)/g, "/*");
  return { platform, page_key: `${platform}:${host}${path}`, host };
}

if (typeof window !== "undefined") {
  window.afEngine = { afScan, afFill, afPageInfo };
}

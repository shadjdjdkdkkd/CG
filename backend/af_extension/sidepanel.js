const $ = (id) => document.getElementById(id);
let API = AF_DEFAULT_API;
let products = [];
let recording = null;
let piloting = false;
let stopFlag = false;
let recordings = [];
let lastScan = { tabId: null, fields: [], values: {} };

const setStatus = (msg, cls = "") => {
  const el = $("main").classList.contains("hidden") ? $("loginMsg") : $("status");
  el.textContent = msg; el.className = "status " + cls;
};

let TOKEN = "";
async function call(path, opts = {}) {
  if (!API || API.includes("__API_URL__")) throw new Error("Set the dashboard URL in Settings");
  const res = await fetch(`${API}/api${path}`, { headers: { "Content-Type": "application/json", ...(TOKEN ? { Authorization: `Bearer ${TOKEN}` } : {}) }, ...opts, body: opts.body ? JSON.stringify(opts.body) : undefined });
  if (res.status === 401 && !path.startsWith("/auth/")) { showLogin(true); throw new Error("Please sign in"); }
  if (!res.ok) { const d = (await res.json().catch(() => ({}))).detail; throw new Error(typeof d === "string" ? d : res.statusText); }
  return res.json();
}

function showLogin(on) {
  $("loginCard").classList.toggle("hidden", !on);
  $("main").classList.toggle("hidden", on);
}
$("loginBtn").onclick = () => withBusy($("loginBtn"), async () => {
  const r = await call("/auth/login", { method: "POST", body: { username: $("loginUser").value, password: $("loginPass").value } });
  TOKEN = r.token;
  await chrome.storage.local.set({ token: TOKEN });
  $("loginPass").value = "";
  showLogin(false);
  await loadProducts(); loadRecordings(); loadLearning(); refreshPage();
});
$("logoutBtn").onclick = async () => { TOKEN = ""; await chrome.storage.local.remove("token"); showLogin(true); };
$("otpSend").onclick = () => withBusy($("otpSend"), async () => {
  const r = await call("/auth/request-otp", { method: "POST" });
  $("otpBox").classList.remove("hidden");
  $("loginMsg").textContent = `Code sent to ${r.sent_to}`;
});
$("otpReset").onclick = () => withBusy($("otpReset"), async () => {
  await call("/auth/reset-password", { method: "POST", body: { otp: $("otpCode").value, new_password: $("otpNew").value } });
  $("otpBox").classList.add("hidden");
  $("loginMsg").textContent = "Password changed — sign in with the new password";
});

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true, windowType: "normal" });
  if (tab) return tab;
  const all = await chrome.tabs.query({ active: true, windowType: "normal" });
  return all[0];
}

async function loadProducts() {
  try {
    products = await call("/products");
    const settings = await call("/settings");
    $("apiDot").className = "dot ok";
    const saved = (await chrome.storage.local.get("productId")).productId;
    $("productSelect").innerHTML = products.length
      ? products.map((p) => `<option value="${p.id}">${p.name} · ${p.size || ""}</option>`).join("")
      : `<option value="">No products yet — add one</option>`;
    if (saved && products.find((p) => p.id === saved)) $("productSelect").value = saved;
    if (!$("pBrand").value) $("pBrand").value = settings.default_brand || "";
    if (!$("pSize").value) $("pSize").value = settings.default_size || "";
  } catch (e) {
    $("apiDot").className = "dot bad";
    if (e.message === "Please sign in") return;
    const ok = await fetch(`${API}/api/`).then((r) => r.ok).catch(() => false);
    setStatus(ok ? `Dashboard error: ${e.message}` : `Cannot reach dashboard at ${API} — the server may be asleep or the URL in Settings is wrong. Open the dashboard once, then reopen this panel.`, "err");
  }
}

async function scanTab(tabId) {
  await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, files: ["engine.js"], world: "MAIN" });
  const results = await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, func: () => afScan(), world: "MAIN" });
  const fields = [];
  const seen = {};
  results.forEach((r) => (r.result || []).forEach((f) => {
    let key = f.key;
    seen[key] = (seen[key] || 0) + 1;
    if (seen[key] > 1) key = `${key}_f${r.frameId}`;
    fields.push({ ...f, key, frameId: r.frameId });
  }));
  return fields;
}

async function fillTab(tabId, fields, values, onlyEmpty = false) {
  const byFrame = {};
  fields.forEach((f) => { (byFrame[f.frameId] = byFrame[f.frameId] || {})[f.af_id] = values[f.key]; });
  let total = 0;
  for (const [frameId, map] of Object.entries(byFrame)) {
    const [r] = await chrome.scripting.executeScript({ target: { tabId, frameIds: [Number(frameId)] }, func: (m, o, e) => afFill(m, o, e), args: [map, onlyEmpty, enterIdents()], world: "MAIN" });
    total += r?.result?.filled || 0;
    for (const miss of r?.result?.misses || []) {
      const f = fields.find((x) => x.af_id === miss.af_id);
      const opt = await aiMatch(f, miss.wanted, miss.options);
      if (!opt) continue;
      const [r2] = await chrome.scripting.executeScript({ target: { tabId, frameIds: [Number(frameId)] }, func: (m, e) => afFill(m, false, e), args: [{ [miss.af_id]: opt }, enterIdents()], world: "MAIN" }).catch(() => [{}]);
      total += r2?.result?.filled || 0;
    }
  }
  for (const f of fields.filter((x) => x.kind === "toggle")) {
    if (!values[f.key] || (onlyEmpty && f.current_value)) continue;
    const [r] = await chrome.scripting.executeScript({ target: { tabId, frameIds: [f.frameId] }, func: (id, v) => afSetToggle(id, v), args: [f.af_id, values[f.key]], world: "MAIN" }).catch(() => [{}]);
    if (r?.result) total++;
  }
  for (const f of fields.filter((x) => x.kind === "radio")) {
    if (!values[f.key]) continue;
    const [r] = await chrome.scripting.executeScript({ target: { tabId, frameIds: [f.frameId] }, func: (id, v, o) => afSelectRadio(id, v, o), args: [f.af_id, values[f.key], onlyEmpty], world: "MAIN" }).catch(() => [{}]);
    if (r?.result === true) total++;
    else if (r?.result?.options?.length) {
      const opt = await aiMatch(f, values[f.key], r.result.options);
      if (opt) { const [r2] = await chrome.scripting.executeScript({ target: { tabId, frameIds: [f.frameId] }, func: (id, v) => afSelectRadio(id, v, false), args: [f.af_id, opt], world: "MAIN" }).catch(() => [{}]); if (r2?.result === true) total++; }
    }
  }
  for (const f of fields.filter((x) => x.kind === "combo" || x.kind === "autocomplete" || x.kind === "katpredict")) {
    if (!values[f.key]) continue;
    const [r] = await chrome.scripting.executeScript({ target: { tabId, frameIds: [f.frameId] }, func: (id, v, k, o) => afSelectCustom(id, v, k, o), args: [f.af_id, values[f.key], f.kind, onlyEmpty], world: "MAIN" }).catch(() => [{}]);
    if (r?.result === true) total++;
    else if (r?.result?.options?.length) {
      const opt = await aiMatch(f, values[f.key], r.result.options);
      if (opt) { const [r2] = await chrome.scripting.executeScript({ target: { tabId, frameIds: [f.frameId] }, func: (id, v, k) => afSelectCustom(id, v, k, false), args: [f.af_id, opt, f.kind], world: "MAIN" }).catch(() => [{}]); if (r2?.result === true) total++; }
    }
  }
  return total;
}

async function aiMatch(field, wanted, options) {
  if (!options?.length) return "";
  const r = await call("/match-option", { method: "POST", body: { label: field?.label || field?.placeholder || field?.key || "", wanted: String(wanted), options, product_id: $("productSelect").value || null } }).catch(() => ({}));
  return r.option || "";
}

async function addDropdownOptions(tabId, fields, pageKey) {
  const combos = fields.filter((f) => f.kind === "combo" && !f.options.length);
  if (!combos.length) return;
  const { template } = await call(`/templates/lookup?page_key=${encodeURIComponent(pageKey)}`).catch(() => ({}));
  const known = Object.fromEntries((template?.fields || []).map((f) => [f.key, f.options || []]));
  const byFrame = {};
  combos.forEach((f) => {
    if (known[f.key]?.length) f.options = known[f.key];
    else (byFrame[f.frameId] = byFrame[f.frameId] || []).push(f.af_id);
  });
  for (const [frameId, ids] of Object.entries(byFrame)) {
    const [r] = await chrome.scripting.executeScript({ target: { tabId, frameIds: [Number(frameId)] }, func: (i) => afProbe(i), args: [ids], world: "MAIN" }).catch(() => [{}]);
    const got = r?.result || {};
    combos.forEach((f) => { if (got[f.af_id]) f.options = got[f.af_id]; });
  }
}

const toFieldInfo = (f) => ({ key: f.key, kind: f.kind, section: f.section || "", label: f.label, placeholder: f.placeholder, type: f.type, tag: f.tag, options: (f.options || []).slice(0, 150), maxlength: f.maxlength });

async function pageErrors(tabId) {
  const res = await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, func: () => afErrors(), world: "MAIN" }).catch(() => []);
  const out = { messages: [], fieldErrors: {} };
  res.forEach((r) => { if (r.result) { out.messages.push(...r.result.messages); Object.assign(out.fieldErrors, r.result.fieldErrors); } });
  return out;
}

async function fixErrors(tab, productId = $("productSelect").value) {
  const errs = await pageErrors(tab.id);
  const fields = await scanTab(tab.id);
  const errByKey = {};
  fields.forEach((f) => { if (errs.fieldErrors[f.af_id]) errByKey[f.key] = errs.fieldErrors[f.af_id]; });
  if (!Object.keys(errByKey).length && !errs.messages.length) return { fixed: 0, errors: errs };
  await addDropdownOptions(tab.id, fields, afPageInfo(tab.url).page_key);
  const info = afPageInfo(tab.url);
  const { values } = await call("/generate", {
    method: "POST",
    body: { product_id: productId, platform: info.platform, page_key: info.page_key, page_title: tab.title, url: tab.url, fields: fields.map(toFieldInfo), use_cache: true, errors: errByKey, page_errors: errs.messages },
  });
  const target = Object.keys(errByKey).length ? fields.filter((f) => errByKey[f.key] || !f.current_value) : fields.filter((f) => !f.current_value);
  const fixed = await fillTab(tab.id, target, values, false);
  return { fixed, errors: errs, keys: Object.keys(errByKey) };
}

// keeps reading red errors and fixing until none are left (stops only when an error refuses to change)
async function fixUntilClean(tabId, productId, label = "") {
  let lastSig = "", same = 0;
  for (let round = 0; round < 10; round++) {
    if (stopFlag) return false;
    await sleep(1000);
    const errs = await pageErrors(tabId);
    const msgs = Object.values(errs.fieldErrors);
    if (!msgs.length) return true;
    const sig = JSON.stringify(errs.fieldErrors);
    same = sig === lastSig ? same + 1 : 0;
    lastSig = sig;
    if (same >= 3) return false;
    setStatus(`${label}Red errors (${msgs.length}): ${msgs.slice(0, 3).join(" · ").slice(0, 160)} — reading and fixing (round ${round + 1})…`);
    await fixErrors(await chrome.tabs.get(tabId), productId).catch((e) => console.warn("fix", e));
  }
  return !Object.keys((await pageErrors(tabId)).fieldErrors).length;
}

async function processTab(tab, { regen = false, onlyEmpty = false, productId = $("productSelect").value } = {}) {
  if (!productId) throw new Error("Add / select a product first");
  const info = afPageInfo(tab.url);
  const fields = await scanTab(tab.id);
  if (!fields.length) {
    const up = $("autoImages").checked ? await uploadImages(tab.id, productId).catch((e) => { console.warn("images", e); return 0; }) : 0;
    if (up) return { fields: [], values: {}, filled: 0, cached: false, uploaded: up, hasFiles: false };
    throw new Error("No fillable fields found on this page — click 'Diagnose page' so we can see how this site builds its form");
  }
  await addDropdownOptions(tab.id, fields, info.page_key);
  const { values, cached, corrections = [] } = await call("/generate", {
    method: "POST",
    body: { product_id: productId, platform: info.platform, page_key: info.page_key, page_title: tab.title, url: tab.url, fields: fields.map(toFieldInfo), use_cache: !regen },
  });
  if (corrections.length) console.info("value checks", corrections);
  const filled = await fillTab(tab.id, fields, values, onlyEmpty);
  await fixUntilClean(tab.id, productId);
  setStatus(`Filled ${filled}/${fields.length} fields — checking for photo upload…`);
  const uploaded = $("autoImages").checked ? await uploadImages(tab.id, productId).catch((e) => { console.warn("images", e); return 0; }) : 0;
  await call("/templates", { method: "POST", body: { platform: info.platform, page_key: info.page_key, url: tab.url, name: tab.title?.slice(0, 80) || "", fields: fields.map(toFieldInfo), reference_values: {} } });
  const [fileCheck] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: () => afAll(document, "input[type=file], kat-file-upload").length > 0, world: "MAIN" }).catch(() => [{}]);
  return { fields, values, filled, cached, uploaded, corrections, hasFiles: !!fileCheck?.result && !uploaded };
}

function renderFields(fields, values = {}) {
  $("fieldCount").textContent = `(${fields.length})`;
  $("fieldList").innerHTML = "";
  fields.forEach((f) => {
    const d = document.createElement("div");
    d.className = "field";
    d.innerHTML = `<div class="lbl"></div><textarea rows="1"></textarea>`;
    d.querySelector(".lbl").textContent = `${f.label || f.placeholder || f.key}${f.placeholder && f.label ? " · " + f.placeholder : ""}`;
    const ta = d.querySelector("textarea");
    ta.value = values[f.key] ?? f.current_value ?? "";
    ta.oninput = () => (lastScan.values[f.key] = ta.value);
    $("fieldList").appendChild(d);
  });
}

async function refreshPage() {
  const tab = await activeTab();
  if (tab?.id) ensureWatcher(tab.id);
  if (!tab?.url || !/^https?:/.test(tab.url)) {
    $("platformBadge").textContent = "—"; $("formatStatus").textContent = "Open a seller page"; $("pageUrl").textContent = "";
    return;
  }
  const info = afPageInfo(tab.url);
  curPlatform = info.platform;
  renderLearning();
  $("platformBadge").textContent = info.platform;
  $("platformBadge").className = "badge " + info.platform;
  $("pageUrl").textContent = tab.url;
  try {
    const { template } = await call(`/templates/lookup?page_key=${encodeURIComponent(info.page_key)}`);
    $("formatStatus").textContent = template ? `Saved format · ${template.fields.length} fields` : "New page — first fill saves format";
    return template;
  } catch { $("formatStatus").textContent = "Offline"; }
}

async function withBusy(btn, fn) {
  btn.disabled = true;
  try { await fn(); } catch (e) { setStatus(e.message, "err"); } finally { btn.disabled = false; }
}

$("fillBtn").onclick = () => withBusy($("fillBtn"), async () => {
  const tab = await activeTab();
  setStatus("Reading page & generating with AI…");
  const r = await processTab(tab, { regen: $("regen").checked });
  lastScan = { tabId: tab.id, fields: r.fields, values: { ...r.values } };
  renderFields(r.fields, r.values);
  setStatus(`Filled ${r.filled}/${r.fields.length} fields${r.cached ? " (saved answers)" : ""}.${r.uploaded ? ` Uploaded ${r.uploaded} photo(s) from the product link.` : ""}${r.corrections?.length ? ` Value check fixed ${r.corrections.length} field(s): ${r.corrections.map((c) => c.field).join(", ").slice(0, 120)}.` : ""} Format saved.${r.hasFiles ? " Now upload images." : ""}`, "ok");
  refreshPage();
});

$("scanBtn").onclick = () => withBusy($("scanBtn"), async () => {
  const tab = await activeTab();
  const fields = await scanTab(tab.id);
  lastScan = { tabId: tab.id, fields, values: {} };
  renderFields(fields);
  setStatus(`Found ${fields.length} fields`, "ok");
});

$("refillBtn").onclick = () => withBusy($("refillBtn"), async () => {
  if (!lastScan.fields.length) throw new Error("Run AI Generate & Fill first");
  const n = await fillTab(lastScan.tabId, lastScan.fields, lastScan.values);
  setStatus(`Re-filled ${n} fields`, "ok");
});

$("learnBtn").onclick = () => withBusy($("learnBtn"), async () => {
  const tab = await activeTab();
  const info = afPageInfo(tab.url);
  const fields = await scanTab(tab.id);
  const ref = {};
  fields.forEach((f) => { if (f.current_value) ref[f.label || f.key] = f.current_value; });
  await call("/templates", { method: "POST", body: { platform: info.platform, page_key: info.page_key, url: tab.url, name: tab.title?.slice(0, 80) || "", fields: fields.map(toFieldInfo), reference_values: ref } });
  setStatus(`Learned ${Object.keys(ref).length} values as style reference`, "ok");
  refreshPage();
});

$("loadTabs").onclick = loadTabs;
async function loadTabs() {
  const tabs = await chrome.tabs.query({ windowType: "normal" });
  const list = tabs.filter((t) => /^https?:/.test(t.url || ""));
  $("tabList").innerHTML = "";
  list.forEach((t) => {
    const info = afPageInfo(t.url);
    const row = document.createElement("label");
    row.className = "tab check";
    row.innerHTML = `<input type="checkbox" value="${t.id}" ${info.platform !== "other" ? "checked" : ""}/> <span class="badge ${info.platform}">${info.platform}</span> <span class="ellipsis"></span>`;
    row.querySelector(".ellipsis").textContent = t.title || t.url;
    $("tabList").appendChild(row);
  });
}

$("batchBtn").onclick = () => withBusy($("batchBtn"), async () => {
  const ids = Array.from($("tabList").querySelectorAll("input:checked")).map((i) => Number(i.value));
  if (!ids.length) throw new Error("Select at least one page");
  let done = 0;
  for (const id of ids) {
    const tab = await chrome.tabs.get(id);
    setStatus(`Filling ${done + 1}/${ids.length}: ${tab.title}`);
    try { await processTab(tab, { regen: $("regen").checked }); done++; } catch (e) { console.warn(e); }
  }
  setStatus(`Filled ${done}/${ids.length} pages`, done ? "ok" : "err");
});

$("toggleSettings").onclick = () => $("settings").classList.toggle("hidden");
$("toggleNew").onclick = () => $("newProduct").classList.toggle("hidden");
$("saveApi").onclick = async () => { API = $("apiUrl").value.replace(/\/$/, ""); await chrome.storage.local.set({ api: API }); loadProducts(); };
$("productSelect").onchange = () => chrome.storage.local.set({ productId: $("productSelect").value });
$("autoMode").onchange = () => chrome.storage.local.set({ autoMode: $("autoMode").checked });
$("autoStep").onchange = () => chrome.storage.local.set({ autoStep: $("autoStep").checked });
$("autoSubmit").onchange = () => chrome.storage.local.set({ autoSubmit: $("autoSubmit").checked });
$("autoImages").onchange = () => chrome.storage.local.set({ autoImages: $("autoImages").checked });
$("imgButton").onchange = () => chrome.storage.local.set({ imgButton: $("imgButton").checked });

async function saveDefault(field, value) {
  const s = await call("/settings");
  s[field] = value;
  if (field === "default_size") s.sizes = [...(s.sizes || []), value];
  if (field === "default_brand") s.brands = [...(s.brands || []), value];
  await call("/settings", { method: "PUT", body: s });
  setStatus(`Saved "${value}" as default`, "ok");
}
$("defBrand").onclick = () => $("pBrand").value && saveDefault("default_brand", $("pBrand").value);
$("defSize").onclick = () => $("pSize").value && saveDefault("default_size", $("pSize").value);

$("saveProduct").onclick = () => withBusy($("saveProduct"), async () => {
  if (!$("pName").value.trim()) throw new Error("Product name is required");
  const p = await call("/products", { method: "POST", body: { name: $("pName").value, brand: $("pBrand").value, ingredients: $("pIngredients").value, size: $("pSize").value, price: $("pPrice").value } });
  await chrome.storage.local.set({ productId: p.id });
  $("pName").value = $("pIngredients").value = $("pPrice").value = "";
  $("newProduct").classList.add("hidden");
  await loadProducts();
  setStatus(`Saved ${p.name}`, "ok");
});

let autoRunning = false;
async function maybeAutoFill() {
  if (!autoOn() || autoRunning || piloting) return;
  const template = await refreshPage();
  if (!template) return;
  autoRunning = true;
  try {
    const tab = await activeTab();
    setStatus("Saved format found — auto-filling…");
    const r = await processTab(tab);
    lastScan = { tabId: tab.id, fields: r.fields, values: { ...r.values } };
    renderFields(r.fields, r.values);
    setStatus(`Auto-filled ${r.filled}/${r.fields.length} fields`, "ok");
  } catch (e) { setStatus(e.message, "err"); } finally { autoRunning = false; }
}

chrome.tabs.onActivated.addListener(() => { refreshPage(); maybeAutoFill(); });
chrome.tabs.onUpdated.addListener((id, change, tab) => {
  if (change.status === "complete") {
    ensureWatcher(id);
    if (tab.active) setTimeout(maybeAutoFill, 1500);
  } else if (tab.active) refreshPage();
});

(async () => {
  const st = await chrome.storage.local.get(["api", "autoMode", "autoStep", "autoSubmit", "autoImages", "token", "autoLearn", "imgButton"]);
  $("imgButton").checked = st.imgButton !== false;
  TOKEN = st.token || "";
  $("autoLearn").checked = st.autoLearn !== false;
  await chrome.storage.local.set({ piloting: false });
  if (!TOKEN) showLogin(true);
  $("autoSubmit").checked = !!st.autoSubmit;
  $("autoImages").checked = st.autoImages !== false;
  $("autoStep").checked = !!st.autoStep;
  API = st.api || AF_DEFAULT_API;
  $("apiUrl").value = API;
  $("autoMode").checked = !!st.autoMode;
  await loadProducts();
  await loadLearning();
  refreshPage();
  loadTabs();
  loadRecordings();
  const t = await activeTab();
  if (t) ensureWatcher(t.id);
})();

// ---------- Learning progress ----------
let learning = {};
let curPlatform = "";
const MILESTONE_TXT = { start: "Seller panel opened", add_page: "Add-product page reached", images: "Photo upload seen", fields: "Fields filled by you", save: "Saved / submitted" };
const enterIdents = () => learning[curPlatform]?.enter_fields || [];
const autoOn = () => $("autoMode").checked || !!learning[curPlatform]?.autofill_enabled;
async function loadLearning() {
  const list = await call("/learning").catch(() => null);
  if (!list) return;
  learning = Object.fromEntries(list.map((l) => [l.platform, l]));
  renderLearning();
}
function renderLearning() {
  const show = curPlatform && curPlatform !== "other";
  $("learnBox").classList.toggle("hidden", !show);
  if (!show) return;
  const L = learning[curPlatform] || { milestones: {}, progress: 0 };
  $("learnPct").textContent = `${L.progress || 0}%`;
  $("learnBar").style.width = `${L.progress || 0}%`;
  $("learnLabel").textContent = L.autofill_enabled ? `Auto-fill ON for ${curPlatform}` : L.complete ? `Learning complete · ${curPlatform}` : `Learning ${curPlatform} — keep listing manually`;
  $("learnSteps").innerHTML = "";
  Object.entries(MILESTONE_TXT).forEach(([k, t]) => {
    const d = document.createElement("span");
    d.className = "chip" + (L.milestones?.[k] ? " on" : "");
    d.dataset.testid = `learn-milestone-${k}`;
    d.textContent = (L.milestones?.[k] ? "✓ " : "") + t;
    $("learnSteps").appendChild(d);
  });
  $("learnSummary").textContent = L.journey_summary || "";
  $("learnPlat").textContent = curPlatform;
  $("learnAsk").classList.toggle("hidden", !(L.complete && !L.asked));
  $("learnOff").classList.toggle("hidden", !L.autofill_enabled);
}
const setAutofill = (on) => withBusy(on ? $("learnYes") : $("learnNo"), async () => {
  const r = await call(`/learning/${curPlatform}/autofill`, { method: "POST", body: { enabled: on } });
  learning[curPlatform] = r;
  renderLearning();
  setStatus(on ? `Full auto-fill is ON for ${curPlatform}. Pages you open will be filled automatically.` : "Auto-fill stays off — learning continues in the background.", "ok");
  if (on) maybeAutoFill();
});
$("learnYes").onclick = () => setAutofill(true);
$("learnNo").onclick = () => setAutofill(false);
$("learnOff").onclick = () => setAutofill(false);

// ---------- Step auto-detect ----------
async function ensureWatcher(tabId) {
  try {
    await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, files: ["pagehook.js"], world: "MAIN" });
    await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, files: ["engine.js", "watcher.js"] });
    if (recording && tabId === recording.tabId) await setRecFlag(tabId, true);
  } catch (e) { /* restricted page */ }
}

let stepBusy = false;
$("autoLearn").onchange = () => chrome.storage.local.set({ autoLearn: $("autoLearn").checked });
chrome.runtime.onMessage.addListener(async (msg, sender) => {
  if (msg.type === "af-progress") { loadLearning(); return; }
  if (msg.type === "af-learned") { await loadRecordings(); await loadLearning(); setStatus(`Learned your ${msg.platform} flow automatically (${msg.steps} actions recorded). AI is now writing why each step happens and optimising the path.`, "ok"); return; }
  const tab = sender.tab;
  if (!tab) return;
  if (msg.type === "af-click" && recording && tab.id === recording.tabId) {
    if (!msg.step.text && !msg.step.aria && !msg.step.elem_id) return;
    recording.steps.push({ ...msg.step, page_key: afPageInfo(msg.href).page_key });
    if (!recording.start_url) recording.start_url = msg.href;
    renderRecSteps();
    scheduleLearn(tab);
    return;
  }
  if (msg.type === "af-new-fields" && recording && tab.id === recording.tabId) {
    scheduleLearn(tab);
    return;
  }
  if (msg.type === "af-new-fields" && ($("autoStep").checked || autoOn()) && tab.active && !piloting && !stepBusy && !recording) {
    stepBusy = true;
    try {
      setStatus("New step detected — filling new fields…");
      const r = await processTab(tab, { onlyEmpty: true });
      lastScan = { tabId: tab.id, fields: r.fields, values: { ...r.values } };
      renderFields(r.fields, r.values);
      setStatus(`New step filled · ${r.fields.length} fields on page`, "ok");
    } catch (e) { setStatus(e.message, "err"); } finally { setTimeout(() => (stepBusy = false), 2500); }
  }
});

// ---------- Learn mode ----------
let learnTimer = null;
let learnBusy = false;
function scheduleLearn(tab) {
  clearTimeout(learnTimer);
  learnTimer = setTimeout(() => learnSnapshot(tab.id), 1500);
}

async function learnSnapshot(tabId) {
  if (!recording || learnBusy) return;
  learnBusy = true;
  try {
    const tab = await chrome.tabs.get(tabId);
    const info = afPageInfo(tab.url);
    const fields = await scanTab(tabId);
    if (!fields.length) return;
    const last = recording.steps[recording.steps.length - 1];
    const section = last ? (last.text || last.aria || "Section").slice(0, 40) : "Start";
    fields.forEach((f) => (f.section = section));
    await addDropdownOptions(tabId, fields, info.page_key);
    await call("/templates", { method: "POST", body: { platform: info.platform, page_key: info.page_key, url: tab.url, name: tab.title?.slice(0, 80) || "", fields: fields.map(toFieldInfo), reference_values: {} } });
    const L = recording.learned;
    L.sections.add(`${info.page_key}#${section}`);
    fields.forEach((f) => { L.fields.add(`${info.page_key}#${f.key}`); if (f.kind === "combo" || f.tag === "select" || f.tag === "kat-dropdown") L.dropdowns.add(`${info.page_key}#${f.key}`); });
    setStatus(`Learning… ${L.sections.size} section(s) · ${L.fields.size} fields · ${L.dropdowns.size} dropdowns learned`, "ok");
  } catch (e) { console.warn("learn", e); } finally { learnBusy = false; }
}

// ---------- Autopilot record / replay ----------
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function setRecFlag(tabId, on) {
  await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, func: (v) => { window.__afRecording = v; }, args: [on] }).catch(() => {});
}

function renderRecSteps() {
  const steps = recording ? recording.steps : [];
  $("recSteps").innerHTML = "";
  steps.forEach((s, i) => {
    const d = document.createElement("div");
    d.textContent = `${i + 1}. click "${s.text || s.aria || s.elem_id}"`;
    $("recSteps").appendChild(d);
  });
  $("recSave").disabled = !recording;
}

async function loadRecordings() {
  try {
    recordings = await call("/recordings");
    $("recSelect").innerHTML = recordings.length
      ? recordings.map((r) => `<option value="${r.id}">[${r.platform}] ${r.name}</option>`).join("")
      : `<option value="">No autopilot recorded yet</option>`;
    const tab = await activeTab();
    const plat = tab?.url && /^https?:/.test(tab.url) ? afPageInfo(tab.url).platform : null;
    const host = tab?.url && /^https?:/.test(tab.url) ? new URL(tab.url).host : "";
    const match = recordings.find((r) => r.platform === plat && r.start_url.includes(host)) || recordings.find((r) => r.platform === plat);
    if (match) $("recSelect").value = match.id;
  } catch (e) { /* offline */ }
}

$("recBtn").onclick = async () => {
  const tab = await activeTab();
  if (!recording) {
    await ensureWatcher(tab.id);
    recording = { tabId: tab.id, platform: afPageInfo(tab.url).platform, start_url: tab.url, steps: [], learned: { sections: new Set(), fields: new Set(), dropdowns: new Set() } };
    await setRecFlag(tab.id, true);
    $("recBtn").textContent = "Stop learning";
    $("recBadge").classList.remove("hidden");
    setStatus("Learning — move through every section / page yourself. Fields & dropdowns are captured automatically.");
    learnSnapshot(tab.id);
  } else {
    await setRecFlag(recording.tabId, false);
    clearTimeout(learnTimer);
    await learnSnapshot(recording.tabId);
    $("recBtn").textContent = "Start learning";
    $("recBadge").classList.add("hidden");
    const L = recording.learned;
    setStatus(`Learned ${L.sections.size} section(s), ${L.fields.size} fields, ${L.dropdowns.size} dropdowns, ${recording.steps.length} clicks — press Save`, "ok");
  }
  renderRecSteps();
};

$("recSave").onclick = () => withBusy($("recSave"), async () => {
  if (!recording) throw new Error("Start learning first");
  if ($("recBtn").textContent.startsWith("Stop")) await $("recBtn").onclick();
  if (!recording.steps.length) {
    const n = recording.learned.fields.size;
    recording = null; renderRecSteps();
    if (!n) throw new Error("Nothing learned yet");
    setStatus(`Single-page format saved (${n} fields). Use AI Generate & Fill.`, "ok");
    return;
  }
  const FINAL = /^(save|save draft|submit|publish|send (for|to) qc|list now|save & submit|save and submit)$/i;
  const finalSteps = [];
  while (recording.steps.length && FINAL.test(recording.steps[recording.steps.length - 1].text)) finalSteps.unshift(recording.steps.pop());
  if (!recording.steps.length) throw new Error("Only Save/Submit clicks recorded — record the steps before them");
  const r = await call("/recordings", { method: "POST", body: { platform: recording.platform, start_url: recording.start_url, steps: recording.steps, final_steps: finalSteps, name: "" } });
  recording = null;
  renderRecSteps();
  await loadRecordings();
  $("recSelect").value = r.id;
  setStatus(`Autopilot saved: ${r.name}`, "ok");
});

$("recDel").onclick = async () => {
  if (!$("recSelect").value) return;
  await call(`/recordings/${$("recSelect").value}`, { method: "DELETE" });
  loadRecordings();
};

async function waitTab(tabId) {
  for (let i = 0; i < 30; i++) {
    const t = await chrome.tabs.get(tabId);
    if (t.status === "complete") break;
    await sleep(500);
  }
  await sleep(1200);
  await ensureWatcher(tabId);
  return chrome.tabs.get(tabId);
}

async function fillQuiet(tabId, productId) {
  const tab = await waitTab(tabId);
  try { await processTab(tab, { onlyEmpty: true, productId }); } catch (e) {
    if (!/No fillable/.test(e.message)) throw e;
  }
}

const isClick = (s) => (s.type || "click") === "click";
const isUploadStep = (s) => s.type === "upload" || (isClick(s) && AF_UPLOAD.test((s.text || s.aria || "").trim()));
const SKIP_STEP = (s) => !isClick(s) || /^kat-(date-picker|dropdown|predictive-input|radiobutton|checkbox|toggle)$/.test(s.tag || "") || /s-dropdown/.test(s.path || "") || (!s.text && !s.aria && !s.elem_id);

async function clickStep(tabId, step, tries = 20) {
  for (let i = 0; i < tries; i++) {
    if (stopFlag) throw new Error("Stopped");
    const res = await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, func: (s) => (typeof afClickStep === "function" ? afClickStep(s) : false), args: [step] }).catch(() => []);
    if (res.some((r) => r.result)) return;
    await sleep(500);
  }
  throw new Error(`Could not find button "${step.text || step.aria}"`);
}

async function runAutoNext(tabId, productId, label) {
  const seen = [];
  for (let page = 0; page < 15; page++) {
    if (stopFlag) throw new Error("Stopped");
    setStatus(`${label} · page ${page + 1}: reading & filling…`);
    await fillQuiet(tabId, productId);
    const [peek] = await chrome.scripting.executeScript({ target: { tabId }, func: () => afFindNext(false), world: "MAIN" }).catch(() => [{}]);
    const nextText = peek?.result;
    if (!nextText) return;
    const tabNow = await chrome.tabs.get(tabId);
    const sig = `${afPageInfo(tabNow.url).page_key}|${nextText}`;
    if (seen.filter((x) => x === sig).length >= 2) throw new Error(`Stuck on "${nextText}" — the page did not move forward. Check the highlighted fields.`);
    seen.push(sig);
    setStatus(`${label} · clicking "${nextText}"`);
    const before = (await pageErrors(tabId)).messages.length;
    await chrome.scripting.executeScript({ target: { tabId }, func: () => afFindNext(true), world: "MAIN" });
    await sleep(2000);
    const errs = await pageErrors(tabId);
    if (Object.keys(errs.fieldErrors).length || errs.messages.length > before) {
      await fixUntilClean(tabId, productId, `${label} · `);
      await chrome.scripting.executeScript({ target: { tabId }, func: () => afFindNext(true), world: "MAIN" }).catch(() => {});
    }
  }
}

let skipped = [];
async function runPilot(rec, tabId, productId, label) {
  for (let i = 0; i < rec.steps.length; i++) {
    if (stopFlag) throw new Error("Stopped");
    setStatus(`${label} · step ${i + 1}/${rec.steps.length}: ${rec.steps[i].type && rec.steps[i].type !== "click" ? rec.steps[i].type : `fill + click "${rec.steps[i].text || rec.steps[i].aria}"`}${rec.steps[i].reason ? ` — ${rec.steps[i].reason}` : ""}`);
    await fillQuiet(tabId, productId);
    if (isUploadStep(rec.steps[i])) {
      if ($("autoImages").checked) {
        setStatus(`${label} · step ${i + 1}: uploading photos from the product link (no file picker)`);
        await uploadImages(tabId, productId).catch((e) => console.warn("images", e));
      }
      continue;
    }
    if (SKIP_STEP(rec.steps[i])) continue;
    const before = (await pageErrors(tabId)).messages.length;
    try { await clickStep(tabId, rec.steps[i], 12); } catch (e) {
      if (/Stopped/.test(e.message)) throw e;
      skipped.push(rec.steps[i].text || rec.steps[i].aria);
      continue;
    }
    await sleep(1500);
    const errs = await pageErrors(tabId);
    if (Object.keys(errs.fieldErrors).length || errs.messages.length > before) {
      await fixUntilClean(tabId, productId, `${label} · `);
      await clickStep(tabId, rec.steps[i]).catch(() => {});
    }
    await sleep(800);
    const left = await pageErrors(tabId);
    if (Object.keys(left.fieldErrors).length) throw new Error(`Stopped — page still shows errors: ${Object.values(left.fieldErrors).slice(0, 3).join(" · ")}. Fix them and press Fill everything again.`);
  }
  await fillQuiet(tabId, productId);
}

$("stopBtn").onclick = () => { stopFlag = true; };

$("runBtn").onclick = () => withBusy($("runBtn"), runSelected);
async function runSelected() {
  const tabA = await activeTab();
  const hostA = new URL(tabA.url).host;
  const rec = recordings.find((r) => r.id === $("recSelect").value && r.start_url.includes(hostA)) || recordings.find((r) => r.start_url.includes(hostA) && r.platform === afPageInfo(tabA.url).platform) || null;
  const tab = await activeTab();
  piloting = true; stopFlag = false; skipped = [];
  await chrome.storage.local.set({ piloting: true });
  try {
    const list = $("allProducts").checked ? products : products.filter((p) => p.id === $("productSelect").value);
    if (!list.length) throw new Error("Select a product");
    for (let i = 0; i < list.length; i++) {
      const label = `${list[i].name} (${i + 1}/${list.length})`;
      if (rec) {
        if ($("allProducts").checked || i > 0) { await chrome.tabs.update(tab.id, { url: rec.start_url }); await sleep(800); }
        await runPilot(rec, tab.id, list[i].id, label);
        await runAutoNext(tab.id, list[i].id, label);
      } else {
        if (i > 0) { await chrome.tabs.update(tab.id, { url: tabA.url }); await sleep(800); }
        await runAutoNext(tab.id, list[i].id, label);
      }
    }
    const clean = await fixUntilClean(tab.id, list[list.length - 1].id, "Final check · ");
    if (!clean) {
      const left = await pageErrors(tab.id);
      throw new Error(`Stopped — these errors could not be fixed automatically: ${Object.values(left.fieldErrors).slice(0, 4).join(" · ")}`);
    }
    let submitted = false;
    const finals = rec?.final_steps?.length ? rec.final_steps : [{ text: "Submit", tag: "kat-button" }, { text: "Submit", tag: "button" }, { text: "Save and finish", tag: "button" }];
    if ($("autoSubmit").checked) {
      for (const st of finals) {
        if (!rec?.final_steps?.length) { const ok = await clickStep(tab.id, st, 3).then(() => true).catch(() => false); if (ok) break; continue; }
        setStatus(`Auto-submitting: clicking "${st.text}"`);
        await clickStep(tab.id, st);
        await sleep(2000);
        const errs = await pageErrors(tab.id);
        if (Object.keys(errs.fieldErrors).length) {
          await fixUntilClean(tab.id, list[list.length - 1].id, "Submit · ");
          await clickStep(tab.id, st).catch(() => {});
          await sleep(1500);
        }
      }
      submitted = true;
    }
    if (rec) await call(`/recordings/${rec.id}/ran`, { method: "POST" });
    const imgCount = list.reduce((a, p) => a + (p.images?.length || 0), 0);
    const DONE = submitted ? "Every filling has been completed, images uploaded and listing submitted." : imgCount && $("autoImages").checked ? "Every filling has been completed and images uploaded. Review, then press Save / Submit." : "Every filling has been completed. Now upload images.";
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: (m) => afBanner(m), args: [DONE] }).catch(() => {});
    const skipNote = skipped.length ? ` (Skipped optional steps not shown this time: ${[...new Set(skipped)].join(", ")})` : "";
    setStatus((list.length > 1 ? `${DONE} (${list.length} products processed)` : DONE) + skipNote, "ok");
  } finally { piloting = false; chrome.storage.local.set({ piloting: false }); }
}

// ---------- Images from product link (downloaded by the dashboard server, no file picker) ----------

async function uploadImages(tabId, productId) {
  const product = products.find((p) => p.id === productId);
  if (!product?.images?.length) return 0;
  const res = await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, func: (pid) => (window.__afUploadAll ? window.__afUploadAll(pid, true) : 0), args: [productId] }).catch(() => []);
  return res.reduce((a, r) => a + (r.result || 0), 0);
}

$("linkBtn").onclick = () => withBusy($("linkBtn"), async () => {
  const url = $("linkInput").value.trim();
  if (!/^https?:\/\//.test(url)) throw new Error("Paste the full product link (https://…)");
  setStatus("Reading product page (details, ingredients, images, certificates)…");
  const p = await call("/products/from-url", { method: "POST", body: { url } });
  await chrome.storage.local.set({ productId: p.id });
  await loadProducts();
  $("productSelect").value = p.id;
  setStatus(`Imported "${p.name}" with ${p.images.length} images. Filling…`, "ok");
  const tab = await activeTab();
  const plat = afPageInfo(tab.url).platform;
  const host = new URL(tab.url).host;
  const sameHost = recordings.filter((r) => r.platform === plat && r.start_url.includes(host));
  const rec = sameHost.find((r) => r.id === $("recSelect").value) || sameHost[0];
  if (rec) $("recSelect").value = rec.id;
  $("allProducts").checked = false;
  if (plat !== "other") await researchStyle(plat, p.id).catch((e) => console.warn("style", e));
  await runSelected();
});

// ---------- Top-seller style research (runs in your own browser) ----------
const SEARCH_URL = {
  amazon: (q) => `https://www.amazon.in/s?k=${encodeURIComponent(q)}`,
  flipkart: (q) => `https://www.flipkart.com/search?q=${encodeURIComponent(q)}`,
  myntra: (q) => `https://www.myntra.com/${encodeURIComponent(q.toLowerCase().replace(/\s+/g, "-"))}`,
  meesho: (q) => `https://www.meesho.com/search?q=${encodeURIComponent(q)}`,
  nykaa: (q) => `https://www.nykaa.com/search/result/?q=${encodeURIComponent(q)}`,
  jiomart: (q) => `https://www.jiomart.com/search/${encodeURIComponent(q)}`,
  ajio: (q) => `https://www.ajio.com/search/?text=${encodeURIComponent(q)}`,
  tata1mg: (q) => `https://www.1mg.com/search/all?name=${encodeURIComponent(q)}`,
};
async function researchStyle(platform, productId) {
  if (!SEARCH_URL[platform]) return;
  setStatus(`Studying top-ranked ${platform} listings for naming style…`);
  const { query } = await call("/style/query", { method: "POST", body: { product_id: productId, platform } });
  const t = await chrome.tabs.create({ url: SEARCH_URL[platform](query), active: false });
  let titles = [];
  try {
    await waitTab(t.id);
    await sleep(2500);
    const [r] = await chrome.scripting.executeScript({ target: { tabId: t.id }, func: () => afTopTitles() });
    titles = r?.result || [];
  } finally { chrome.tabs.remove(t.id).catch(() => {}); }
  if (titles.length < 3) { setStatus(`Could not read ${platform} search results — using default style`, "err"); return; }
  const g = await call("/style/research", { method: "POST", body: { product_id: productId, platform, query, titles } });
  setStatus(`Learned ${platform} top-seller style from ${titles.length} listings: ${g.title_pattern || ""}`.slice(0, 220), "ok");
}
$("styleBtn").onclick = () => withBusy($("styleBtn"), async () => {
  const tab = await activeTab();
  const plat = afPageInfo(tab.url).platform;
  if (plat === "other") throw new Error("Open a marketplace seller page first (Amazon, Flipkart, Myntra, Meesho, Nykaa, Instamart, JioMart, Ajio, Blinkit, Zepto, Tata 1mg)");
  if (!SEARCH_URL[plat]) throw new Error(`${plat} search needs a delivery location — style research is not available there`);
  await researchStyle(plat, $("productSelect").value);
});

// ---------- Diagnose ----------
$("diagBtn").onclick = () => withBusy($("diagBtn"), async () => {
  const tab = await activeTab();
  await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, files: ["engine.js"], world: "MAIN" });
  const res = await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, func: () => afDiagnose(), world: "MAIN" });
  const frames = res.map((r) => ({ frameId: r.frameId, ...(r.result || { error: "no access" }) }));
  const info = afPageInfo(tab.url);
  const report = { platform: info.platform, page_key: info.page_key, url: tab.url, frames };
  await call("/diagnostics", { method: "POST", body: report });
  try { await navigator.clipboard.writeText(JSON.stringify(report, null, 2)); } catch (e) { /* clipboard blocked */ }
  const total = frames.reduce((a, f) => a + (f.detected_fields || 0), 0);
  const deep = frames.reduce((a, f) => a + (f.deep_inputs || 0), 0);
  const shadow = frames.reduce((a, f) => a + (f.shadow_hosts || 0), 0);
  setStatus(`Report sent to dashboard · ${frames.length} frame(s), ${deep} inputs, ${shadow} shadow parts, ${total} fillable fields`, "ok");
});

$("fixBtn").onclick = () => withBusy($("fixBtn"), async () => {
  const tab = await activeTab();
  setStatus("Reading error messages on page…");
  const r = await fixErrors(tab);
  if (!r.fixed && !r.errors.messages.length && !Object.keys(r.errors.fieldErrors).length) return setStatus("No errors found on this page", "ok");
  setStatus(`Fixed ${r.fixed} field(s)${r.keys?.length ? ": " + r.keys.join(", ") : ""}. Errors seen: ${r.errors.messages.slice(0, 3).join(" · ").slice(0, 160)}`, "ok");
});

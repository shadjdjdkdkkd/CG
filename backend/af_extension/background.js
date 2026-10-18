importScripts("config.js", "engine.js");

if (chrome.sidePanel) {
  chrome.runtime.onInstalled.addListener(() => chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }));
  chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
} else {
  chrome.action.onClicked.addListener(() => chrome.windows.create({ url: "sidepanel.html", type: "popup", width: 420, height: 820 }));
}

// ---------- Background auto-learning: records your whole manual listing journey ----------
const FINAL = /^(save|save draft|submit|publish|send (for|to) qc|list now|save & submit|save and submit|submit for qc|save and finish|save & go back|save and go back)$/i;
const UPLOADISH = /\b(upload|add)\s+(product\s+)?(images?|photos?|pictures?)\b/i;
const IDLE_MS = 15 * 60 * 1000;
const ADD_PAGE_MIN_FIELDS = 4;
const snapTimers = {};
const chains = {};
const serial = (tabId, fn) => (chains[tabId] = (chains[tabId] || Promise.resolve()).then(fn).catch((e) => console.warn("learn", e)));

async function cfg() {
  const st = await chrome.storage.local.get(["api", "token", "autoLearn", "piloting"]);
  return { api: st.api || AF_DEFAULT_API, token: st.token, on: st.autoLearn !== false && !st.piloting && !!st.token };
}
async function post(c, path, body) {
  const r = await fetch(`${c.api}/api${path}`, { method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${c.token}` }, body: JSON.stringify(body) });
  return r.ok ? r.json() : null;
}
const getS = async (id) => (await chrome.storage.session.get(`s${id}`))[`s${id}`];
const setS = (id, v) => chrome.storage.session.set({ [`s${id}`]: v });

async function session(tabId, info, href) {
  const now = Date.now();
  let s = await getS(tabId);
  if (!s || now - s.last > IDLE_MS || s.platform !== info.platform) s = { platform: info.platform, start_url: href, steps: [], last: now, m: {}, inputs: 0, enters: [] };
  s.m = s.m || {};
  s.enters = s.enters || [];
  s.last = now;
  return s;
}

async function progress(c, s, patch, extra = {}) {
  const fresh = Object.entries(patch).filter(([k, v]) => v && !s.m[k]).map(([k]) => k);
  fresh.forEach((k) => (s.m[k] = true));
  if (!fresh.length && !extra.enter_fields?.length) return;
  await post(c, "/learning/progress", { platform: s.platform, milestones: s.m, ...extra });
  chrome.runtime.sendMessage({ type: "af-progress", platform: s.platform, milestones: s.m }).catch(() => {});
}

async function snapshot(tabId) {
  const c = await cfg();
  if (!c.on) return;
  try {
    const tab = await chrome.tabs.get(tabId);
    const info = afPageInfo(tab.url);
    if (info.platform === "other") return;
    await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, files: ["engine.js"], world: "MAIN" });
    const res = await chrome.scripting.executeScript({ target: { tabId, allFrames: true }, func: () => afScan(), world: "MAIN" });
    const s = await session(tabId, info, tab.url);
    const lastClick = [...s.steps].reverse().find((x) => (x.type || "click") === "click");
    const section = lastClick ? (lastClick.text || lastClick.aria || "Section").slice(0, 40) : "Start";
    const fields = res.flatMap((r) => r.result || []).map((f) => ({ key: f.key, kind: f.kind, section, label: f.label, placeholder: f.placeholder, type: f.type, tag: f.tag, options: f.options, maxlength: f.maxlength }));
    if (fields.length) await post(c, "/templates", { platform: info.platform, page_key: info.page_key, url: tab.url, name: (tab.title || "").slice(0, 80), fields, reference_values: {} });
    await progress(c, s, { start: true, add_page: fields.length >= ADD_PAGE_MIN_FIELDS }, fields.length >= ADD_PAGE_MIN_FIELDS ? { pages: [info.page_key] } : {});
    await setS(tabId, s);
  } catch (e) { /* tab closed / restricted */ }
}
function scheduleSnap(tabId) {
  clearTimeout(snapTimers[tabId]);
  snapTimers[tabId] = setTimeout(() => serial(tabId, () => snapshot(tabId)), 1800);
}

async function finalize(tabId, s, c) {
  const steps = [...s.steps];
  const finalSteps = [];
  while (steps.length && (steps[steps.length - 1].type || "click") === "click" && FINAL.test(steps[steps.length - 1].text)) finalSteps.unshift(steps.pop());
  if (steps.some((x) => (x.type || "click") === "click")) await post(c, "/recordings", { platform: s.platform, start_url: s.start_url, steps, final_steps: finalSteps, auto: true, name: "" });
  await chrome.storage.session.remove(`s${tabId}`);
  chrome.runtime.sendMessage({ type: "af-learned", platform: s.platform, steps: steps.length }).catch(() => {});
}

async function record(tabId, href, step) {
  const c = await cfg();
  if (!c.on) return;
  const info = afPageInfo(href);
  if (info.platform === "other") return;
  const s = await session(tabId, info, href);
  const prev = s.steps[s.steps.length - 1];
  const t = step.type || "click";
  if (t === "navigate" && prev?.type === "navigate" && prev.page_key === info.page_key) return;
  if (t === "input" && prev?.type === "input" && prev.ident === step.ident && prev.page_key === info.page_key) s.steps.pop();
  s.steps.push({ ...step, type: t, page_key: info.page_key, url: href.slice(0, 300) });
  if (s.steps.length > 400) s.steps.splice(0, s.steps.length - 400);
  const patch = { start: true };
  const extra = {};
  if (t === "input" || t === "select") { s.inputs = (s.inputs || 0) + 1; patch.fields = s.inputs >= 3; }
  if (t === "upload" || (t === "click" && UPLOADISH.test(step.text || ""))) patch.images = true;
  if (t === "enter" && step.ident && !s.enters.includes(step.ident)) { s.enters.push(step.ident); extra.enter_fields = [step.ident]; }
  await progress(c, s, patch, extra);
  await setS(tabId, s);
  if (t !== "input") scheduleSnap(tabId);
  if (t === "click" && FINAL.test(step.text || "")) await finalize(tabId, s, c);
}

chrome.runtime.onMessage.addListener((msg, sender) => {
  const tab = sender.tab;
  if (!tab || !["af-click", "af-step", "af-new-fields"].includes(msg.type)) return;
  if (msg.type === "af-new-fields") {
    cfg().then((c) => { if (c.on && afPageInfo(msg.href || tab.url).platform !== "other") scheduleSnap(tab.id); });
    return;
  }
  if (msg.type === "af-click" && !msg.step.text && !msg.step.aria && !msg.step.elem_id) return;
  serial(tab.id, () => record(tab.id, msg.href || tab.url, msg.step));
});

// ---------- Photos from the product link for upload buttons ----------
const imgCur = {};
chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg.type !== "af-images" || !sender.tab) return;
  (async () => {
    const st = await chrome.storage.local.get(["api", "token", "productId"]);
    const pid = msg.pid || st.productId;
    if (!pid || !st.token) return reply({ files: [], left: 0 });
    const key = `${sender.tab.id}:${pid}`;
    const now = Date.now();
    let cur = imgCur[key];
    if (msg.fresh || !cur || now - cur.t > 5 * 60 * 1000 || (cur.total && cur.pos >= cur.total)) cur = { pos: 0, total: 0 };
    const count = msg.multiple ? 15 : 1;
    const platform = afPageInfo(sender.tab.url).platform;
    const r = await fetch(`${st.api || AF_DEFAULT_API}/api/products/${pid}/image-files?start=${cur.pos}&count=${count}&platform=${platform}&limit=${msg.limit || 0}`, { headers: { Authorization: `Bearer ${st.token}` } });
    const d = r.ok ? await r.json() : { files: [], total: 0 };
    cur.total = d.total;
    cur.pos = Math.min(d.total, cur.pos + count);
    cur.t = now;
    imgCur[key] = cur;
    reply({ files: d.files, left: Math.max(0, d.total - cur.pos) });
  })().catch(() => reply({ files: [], left: 0 }));
  return true;
});

chrome.tabs.onUpdated.addListener((tabId, change, tab) => {
  if (!change.url || !/^https?:/.test(change.url)) return;
  serial(tabId, () => record(tabId, change.url, { type: "navigate", text: (tab.title || "").slice(0, 80) }));
});

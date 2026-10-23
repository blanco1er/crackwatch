// CrackWatch. No framework, no third-party request. Server data is always inserted as text (textContent).
// Data lives on this device (localStorage + IndexedDB, no account). Photos sent for measurement go to a private S3 bucket
// through a presigned POST and are deleted after 24 h.
import { toast, openSheet, closeSheet, setTheme } from '/ds/motion.js';
import { T } from '/i18n.js';

// ------------------------------------------------------------------ tiny helpers
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
function h(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') e.className = v;
    else if (k === 'text') e.textContent = v;
    else if (k.startsWith('on')) e.addEventListener(k.slice(2), v);
    else if (k === 'style') e.style.cssText = v;
    else e.setAttribute(k, v === true ? '' : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k.nodeType ? k : document.createTextNode(String(k)));
  return e;
}
const svgNS = 'http://www.w3.org/2000/svg';
const s = (tag, attrs = {}) => { const e = document.createElementNS(svgNS, tag); for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v); return e; };
const icon = (id, cls = 'ui-icon') => { const e = s('svg', { class: cls, 'aria-hidden': 'true' }); e.append(s('use', { href: `#i-${id}` })); return e; };
const store = {
  get(k) { try { return localStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, v); return true; } catch { return false; } },
  del(k) { try { localStorage.removeItem(k); } catch { /* private mode */ } },
};
const reduceMotion = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const uid = () => Math.random().toString(36).slice(2, 10);
const DAY = 86400000;

// ------------------------------------------------------------------ language
let lang = store.get('cw-lang') || 'en';
if (!T[lang]) lang = 'en';
const LOCALE = () => (lang === 'fr' ? 'fr-FR' : 'en-GB');
function t(key, vars) {
  let v = T[lang][key] ?? T.en[key] ?? key;
  if (typeof v === 'function') return v(vars || {});
  if (vars) v = v.replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? ''));
  return v;
}
// "**bold** rest" -> nodes (translated strings only; values are inserted as text)
function rich(str) {
  const out = [];
  String(str).split(/(\*\*[^*]+\*\*|`[^`]+`)/).forEach((p) => { if (!p) return; out.push(p.startsWith('**') ? h('strong', null, p.slice(2, -2)) : p.startsWith('`') ? h('code', null, p.slice(1, -1)) : document.createTextNode(p)); });
  return out;
}
const num = (v, d = 2) => (v == null || Number.isNaN(+v) ? '—' : Number(v).toLocaleString(LOCALE(), { minimumFractionDigits: d, maximumFractionDigits: d }));

// ------------------------------------------------------------------ settings
const DEFAULTS = { units: 'mm', widthAlert: 1.0, wideningAlert: 0.2, theme: 'system' };
const settings = Object.assign({}, DEFAULTS, safeJSON(store.get('cw-settings')) || {});
function saveSettings() { store.set('cw-settings', JSON.stringify(settings)); }
function safeJSON(s) { try { return s ? JSON.parse(s) : null; } catch { return null; } }
// width formatting in the chosen unit: returns [number, unit]
function W(mm, { d, sign } = {}) {
  if (mm == null || Number.isNaN(+mm)) return ['—', ''];
  const inch = settings.units === 'in';
  const v = inch ? mm / 25.4 : mm;
  const dd = d ?? (inch ? 3 : 2);
  const n = num(Math.abs(v) < 1e-9 ? 0 : v, dd);
  return [sign && v > 0 ? `+${n}` : n, inch ? 'in' : 'mm'];
}
const Wt = (mm, o) => W(mm, o).join(' ');
const L = (mm) => (settings.units === 'in' ? `${num(mm / 25.4, 1)} in` : `${num(mm, 0)} mm`);
const fmtDate = (ms, opt = { day: 'numeric', month: 'short', year: 'numeric' }) => new Date(ms).toLocaleDateString(LOCALE(), opt);
const fmtShort = (ms) => new Date(ms).toLocaleDateString(LOCALE(), { day: 'numeric', month: 'short' });

// ------------------------------------------------------------------ images (IndexedDB, memory fallback)
const mem = new Map();
const idb = (() => {
  let p = null;
  const open = () => p || (p = new Promise((ok) => {
    try {
      const r = indexedDB.open('crackwatch', 1);
      r.onupgradeneeded = () => r.result.createObjectStore('img');
      r.onsuccess = () => ok(r.result); r.onerror = () => ok(null);
    } catch { ok(null); }
  }));
  const tx = async (mode, fn) => {
    const db = await open(); if (!db) return null;
    return new Promise((ok) => { try { const q = fn(db.transaction('img', mode).objectStore('img')); q.onsuccess = () => ok(q.result ?? null); q.onerror = () => ok(null); } catch { ok(null); } });
  };
  return {
    async put(k, v) { mem.set(k, v); await tx('readwrite', (st) => st.put(v, k)); },
    async get(k) { if (!k) return null; if (mem.has(k)) return mem.get(k); const v = await tx('readonly', (st) => st.get(k)); if (v) mem.set(k, v); return v; },
    async del(k) { mem.delete(k); await tx('readwrite', (st) => st.delete(k)); },
    async clear() { mem.clear(); await tx('readwrite', (st) => st.clear()); },
  };
})();
async function setImg(img, key) { const v = await idb.get(key); if (v) img.src = v; else img.removeAttribute('src'); return !!v; }

// ------------------------------------------------------------------ data model (this device only)
// crack = { id, name, place, demo, createdAt, nextVisitAt, visits: [{ id, at, shots: [shot] }] }
// shot  = { id, at, source, key, status, decision, trace, quality, cracks, comparison, ticket, timings, llm, img, ba, truth }
const DATA_KEY = 'cw-simple-v1';
const data = safeJSON(store.get(DATA_KEY)) || { cracks: [] };
function save() {
  if (!store.set(DATA_KEY, JSON.stringify(data))) toast({ title: t('saveFailed'), detail: t('saveFailedDetail'), tone: 'critical' });
  refreshChrome();
}
const crackById = (id) => data.cracks.find((c) => c.id === id);
const allShots = (c) => c.visits.flatMap((v) => v.shots.map((sh) => ({ ...sh, visitAt: v.at, visitId: v.id })));
const lastShot = (c) => { const v = c.visits[c.visits.length - 1]; return v && v.shots[v.shots.length - 1]; };
const isMeasured = (sh) => sh && sh.status === 'ok' && sh.cracks && sh.cracks[0] && !['request_retake', 'request_closer_photo'].includes(sh.decision?.name);
// one point per visit: the last measured photo of that visit
function series(c) {
  return c.visits.map((v) => { const m = [...v.shots].reverse().find(isMeasured); return m && { at: v.at, max: m.cracks[0].width_mm.max, med: m.cracks[0].width_mm.median, unc: m.cracks[0].uncertainty_mm, len: m.cracks[0].length_mm, shot: m }; }).filter(Boolean);
}
function crackDelta(c) {
  const ser = series(c); if (ser.length < 2) return null;
  const ls = lastShot(c); const cmp = ls && ls.comparison && ls.comparison.status === 'ok' ? ls.comparison.width_delta_mm.median : null;
  return cmp ?? ser[ser.length - 1].max - ser[0].max;
}
function crackStatus(c) {
  const ls = lastShot(c);
  if (!ls) return 'new';
  if (['request_retake', 'request_closer_photo'].includes(ls.decision?.name) || ls.status !== 'ok') return 'needs_photo';
  const ser = series(c);
  const delta = ser.length > 1 ? ser[ser.length - 1].max - ser[0].max : 0;
  const cmp = ls.comparison && ls.comparison.status === 'ok' ? ls.comparison.width_delta_mm.median : null;
  if ((cmp != null && cmp >= settings.wideningAlert) || delta >= settings.wideningAlert) return 'widening';
  if (ser.length && ser[ser.length - 1].max >= settings.widthAlert) return 'above';
  return 'stable';
}
const STATUS_TONE = { new: 'info', needs_photo: 'warn', widening: 'critical', above: 'warn', stable: 'ok' };
const statusEl = (st, cls = '') => h('span', { class: `ui-status ui-status--${STATUS_TONE[st]} ${cls}` }, t(`st_${st}`));
const pendingTickets = () => data.cracks.flatMap((c) => allShots(c).filter((sh) => sh.ticket && sh.ticket.status === 'pending_human_approval').map((sh) => ({ crack: c, shot: sh })));
const allTickets = () => data.cracks.flatMap((c) => allShots(c).filter((sh) => sh.ticket).map((sh) => ({ crack: c, shot: sh }))).sort((a, b) => b.shot.at - a.shot.at);
function findShot(c, shotId) { for (const v of c.visits) { const sh = v.shots.find((x) => x.id === shotId); if (sh) return sh; } return null; }

// ------------------------------------------------------------------ server
let health = null;
let warm = false;
async function api(path, body) {
  const r = await fetch(path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  let d = null;
  try { d = await r.json(); } catch { /* not json */ }
  if (!r.ok) { const e = new Error((d && d.detail) || (d && d.error) || `HTTP ${r.status}`); e.code = (d && d.error) || `http_${r.status}`; e.status = r.status; throw e; }
  return d;
}
const screenClass = () => (innerWidth < 700 ? 'compact' : innerWidth < 1000 ? 'regular' : 'large');
function visit(type, extra = {}) {
  try { fetch('/api/visit', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ type, lang, screen: screenClass(), ...extra }), keepalive: type === 'card' }).then((r) => r.text()).catch(() => {}); } catch { /* ignore */ }
}


// ------------------------------------------------------------------ plain-language reading of a measurement
const MONTH = 30 * DAY;
function nextCheckText(days) {
  if (!days) return '';
  if (days >= 28) { const m = Math.round(days / 30); return t('checkMonths', { n: m }); }
  return t('checkDays', { n: days });
}
// width categories: BRE Digest 251 (crack width only); growth beats width
function verdict(sh, c) {
  if (!sh) return null;
  const a = sh.decision || {}; const cr = sh.cracks && sh.cracks[0]; const q = sh.quality || {};
  if (sh.error) return { tone: 'watch', title: t('vErrorTitle'), text: sh.error, kind: 'error' };
  if (a.name === 'request_retake' || a.name === 'request_closer_photo' || (!cr && sh.status !== 'ok')) {
    const r = a.name === 'request_closer_photo' ? 'closer' : (a.args?.reason || (sh.status === 'no_card' ? 'card_not_found' : 'blur'));
    return { tone: 'watch', kind: 'retake', title: t(`r_${r}`, { blur: num(q.blur_sigma_px, 1) }), text: t(`f_${r}`, { z: num(a.args?.zoom_factor || 1.5, 1) }) };
  }
  if (!cr) return { tone: 'ok', kind: 'none', title: t('vNoneTitle'), text: t('vNoneText') };
  const cmp = sh.comparison && sh.comparison.status === 'ok' ? sh.comparison : null;
  const grew = cmp && (cmp.significant_widening || cmp.width_delta_mm.median >= settings.wideningAlert);
  if (grew || (sh.ticket && cmp)) {
    const since = c && c.visits[0] ? fmtDate(c.visits[0].at, { day: 'numeric', month: 'short' }) : '';
    return { tone: 'act', kind: 'growing', title: t('vGrowing', { d: Wt(cmp.width_delta_mm.median, { sign: true }), since }), text: t('vGrowingText') };
  }
  const w = cr.width_mm.max;
  const days = a.name === 'schedule_next_visit' ? a.args?.days : null;
  const cat = w < 0.1 ? ['ok', 'vHairline'] : w < 1 ? ['ok', 'vFine'] : w < 5 ? ['watch', 'vMedium'] : w < 15 ? ['act', 'vWide'] : ['act', 'vVeryWide'];
  const next = nextCheckText(days);
  return { tone: cat[0], kind: 'width', title: t(cat[1]), text: [t(`${cat[1]}Text`), next].filter(Boolean).join(' ') };
}
// used by the PDF report
function decisionTitle(sh) { const v = verdict(sh); return v ? v.title : ''; }
function decisionWhy(sh) { const v = verdict(sh); return v ? v.text : ''; }
function plannerLabel(p) { if (!p) return ''; if (p.includes('nova')) return 'Amazon Nova 2 Lite'; return t('byRules'); }
function decidedBy(sh) { const ps = [...new Set((sh.trace || []).map((x) => x.action.planner))]; const llm = ps.find((p) => p.includes('nova')); return llm ? t('byModel') : t('byRules'); }
const TONE_CLASS = { ok: 'is-ok', watch: 'is-watch', act: 'is-act' };
function trendOf(c) {
  const ser = series(c); const d = crackDelta(c); const ls = lastShot(c);
  if (!ls) return { tone: 'muted', text: t('trNoPhoto') };
  if (ser.length < 2) { const v = verdict(ls, c); return v && v.kind === 'retake' ? { tone: 'watch', text: t('trRetake') } : { tone: 'muted', text: t('trFirst', { d: fmtDate(ser[0]?.at || ls.at, { day: 'numeric', month: 'short' }) }) }; }
  const since = fmtDate(ser[0].at, { day: 'numeric', month: 'short' });
  if (d != null && Math.abs(d) >= settings.wideningAlert) return { tone: d > 0 ? 'act' : 'ok', text: t('trSince', { d: Wt(d, { sign: true }), since }) };
  return { tone: 'ok', text: t('trStable') };
}
const chip = (tr) => h('span', { class: `chip chip--${tr.tone}` }, h('i', { 'aria-hidden': 'true' }), tr.text);
function hero(mm, { unc, cls = '' } = {}) {
  const [n, unit] = W(mm);
  return h('div', { class: `hero ${cls}` }, h('span', { class: 'hero__num' }, n), h('span', { class: 'hero__unit' }, unit), unc != null ? h('span', { class: 'hero__unc' }, `± ${Wt(unc)}`) : null);
}

// ------------------------------------------------------------------ example: one crack followed over three months (4 photos)
const EX_ID = 'example';
const STEPS = [
  { id: 'blurry', visit: 0, retakes: 0 },
  { id: 'far', visit: 0, retakes: 1 },
  { id: 'close', visit: 0, retakes: 2 },
  { id: 'visit2', visit: 1, retakes: 0, previous: 'close' },
];
let truth = null;
function newExample() {
  const now = Date.now(); const d1 = now - 91 * DAY;
  const c = { id: EX_ID, demo: true, example: true, tracked: true, name: t('exName'), place: t('exPlace'), createdAt: d1, nextVisitAt: null,
    visits: [{ id: 'v1', at: d1, shots: [] }, { id: 'v2', at: now, shots: [] }] };
  data.cracks = data.cracks.filter((x) => x.id !== EX_ID); data.cracks.unshift(c); save();
  return c;
}
async function dropImages(c) { for (const sh of allShots(c)) { for (const k of [sh.img, sh.cu, sh.ba]) if (k) await idb.del(k); } }
let inflight = false;
async function startExample() {
  if (inflight) return;
  const old = crackById(EX_ID); if (old) await dropImages(old);
  newExample();
  S.run = { mode: 'example', crackId: EX_ID, step: 0, phase: 'idle' };
  go('analyze');
  runExampleStep(0);
}
async function runExampleStep(i) {
  if (inflight) return;
  inflight = true;
  const st = STEPS[i]; const c = crackById(EX_ID) || newExample();
  S.run = { mode: 'example', crackId: c.id, step: i, phase: 'measuring', photo: `/samples/${st.id}.jpg` };
  renderAnalyze();
  visit('sample', { sample: st.id });
  try {
    const d = await api('/api/inspect', { image: { sample: st.id }, previous: st.previous ? { sample: st.previous } : null, retakes: st.retakes });
    warm = true;
    const at = st.visit === 0 ? c.visits[0].at + i * 3 * 60000 : c.visits[1].at;
    const sh = await recordShot(c, d, { source: `sample:${st.id}`, at, visitIndex: st.visit, truth: truth?.samples?.[st.id] || null });
    S.run = { ...S.run, phase: 'done', result: d, shot: sh };
  } catch (e) { S.run = { ...S.run, phase: 'error', error: e }; }
  inflight = false;
  if (S.view === 'analyze') renderAnalyze();
}
async function recordShot(c, d, { source, key = null, at = Date.now(), visitIndex = null, truth: gt = null }) {
  const id = uid();
  const imgKey = `ov-${id}`;
  await idb.put(imgKey, `data:image/jpeg;base64,${d.overlay_jpeg_b64}`);
  let cuKey = null;
  if (d.closeup && d.closeup.jpeg_b64) { cuKey = `cu-${id}`; await idb.put(cuKey, `data:image/jpeg;base64,${d.closeup.jpeg_b64}`); }
  let baKey = null;
  if (d.before_after) { baKey = `ba-${id}`; await idb.put(baKey, JSON.stringify({ before: `data:image/jpeg;base64,${d.before_after.before_jpeg_b64}`, after: `data:image/jpeg;base64,${d.before_after.after_jpeg_b64}` })); }
  const last = d.trace[d.trace.length - 1].action;
  const sh = { id, at, source, key, status: d.measurement.status, decision: { name: last.name, args: last.args, planner: last.planner, reason: last.reason },
    trace: d.trace, quality: d.measurement.quality, card: d.measurement.card, cracks: d.measurement.cracks, comparison: d.comparison,
    ticket: d.ticket ? { id: d.ticket.id, severity: d.ticket.severity, evidence: d.ticket.evidence, status: 'pending_human_approval' } : null,
    timings: d.timings_ms, llm: d.llm, img: imgKey, cu: cuKey, ba: baKey, truth: gt, inspectionId: d.inspection_id };
  let v;
  if (visitIndex != null) {
    v = c.visits[visitIndex];
    const same = v.shots.findIndex((x) => x.source === source);
    if (same >= 0) { const o = v.shots[same]; if (o.img) idb.del(o.img); if (o.cu) idb.del(o.cu); if (o.ba) idb.del(o.ba); v.shots.splice(same, 1); }
  } else {
    const lv = c.visits[c.visits.length - 1]; const ls = lv && lv.shots[lv.shots.length - 1];
    const sameVisit = ls && ['request_retake', 'request_closer_photo'].includes(ls.decision?.name) && at - ls.at < 12 * 3600000;
    v = sameVisit ? lv : { id: uid(), at, shots: [] };
    if (!sameVisit) c.visits.push(v);
  }
  v.shots.push(sh); v.shots.sort((a, b) => a.at - b.at);
  if (last.name === 'schedule_next_visit') c.nextVisitAt = (visitIndex != null ? c.visits[visitIndex].at : at) + (last.args?.days || 90) * DAY;
  if (last.name === 'propose_ticket') c.nextVisitAt = null;
  save();
  return sh;
}

// ------------------------------------------------------------------ own photo
function pickFile(crackId = null) { S.pending = crackId; const f = $('#fileInput'); f.value = ''; f.click(); }
async function measureOwn(file) {
  if (inflight) return;
  if (file.size > 15 * 1024 * 1024) { toast({ title: t('tooBig'), tone: 'critical' }); return; }
  inflight = true;
  let c = S.pending && crackById(S.pending);
  if (!c) { c = { id: uid(), tracked: false, name: '', place: '', createdAt: Date.now(), nextVisitAt: null, visits: [] }; data.cracks.push(c); save(); }
  S.run = { mode: 'own', crackId: c.id, phase: 'measuring', uploading: true, photo: URL.createObjectURL(file), file };
  go('analyze');
  try {
    const up = await api('/api/upload-url', {});
    const form = new FormData(); Object.entries(up.fields).forEach(([k, v]) => form.append(k, v)); form.append('file', file);
    const r = await fetch(up.url, { method: 'POST', body: form });
    if (!r.ok) throw Object.assign(new Error('upload_failed'), { code: 'upload_failed' });
    visit('upload');
    S.run.uploading = false; if (S.view === 'analyze') renderAnalyze();
    const lv = c.visits[c.visits.length - 1]; const ls = lastShot(c);
    const sameVisit = !!(ls && ['request_retake', 'request_closer_photo'].includes(ls.decision?.name) && Date.now() - ls.at < 12 * 3600000);
    const prevShot = [...allShots(c)].reverse().find((x) => isMeasured(x) && x.key && Date.now() - x.at < 23 * 3600000 && !(sameVisit && x.visitId === lv.id));
    const retakes = sameVisit ? lv.shots.filter((x) => ['request_retake', 'request_closer_photo'].includes(x.decision?.name)).length : 0;
    const d = await api('/api/inspect', { image: { key: up.key }, previous: prevShot ? { key: prevShot.key } : null, retakes });
    warm = true;
    const sh = await recordShot(c, d, { source: 'upload', key: up.key });
    S.run = { ...S.run, phase: 'done', result: d, shot: sh };
  } catch (e) { S.run = { ...S.run, phase: 'error', error: e, uploading: false }; }
  inflight = false;
  if (S.view === 'analyze') renderAnalyze();
}

// ------------------------------------------------------------------ routing
const S = { view: 'measure', run: null, crackId: null, shotId: null, shared: null, pending: null };
const tracked = () => data.cracks.filter((c) => c.tracked);
function route() {
  const hsh = location.hash.replace(/^#/, '');
  if (hsh.startsWith('s=')) { S.shared = decodeShare(hsh.slice(2)); return show('shared'); }
  const [v, a, b] = hsh.split('/');
  if (v === 'crack' && crackById(a)) { S.crackId = a; return show('crack'); }
  if (v === 'result' && crackById(a)) { S.crackId = a; S.shotId = b; return show('result'); }
  if (v === 'analyze' && S.run) return show('analyze');
  if (v === 'cracks' || v === 'measure') return show(v);
  return show(tracked().length ? 'cracks' : 'measure');
}
function go(hash) { if (location.hash === `#${hash}`) route(); else location.hash = hash; }
function show(view) {
  S.view = view;
  $$('.view').forEach((x) => { x.hidden = x.dataset.view !== view; });
  document.body.dataset.view = view;
  const tab = { crack: 'cracks', result: 'measure', analyze: 'measure', shared: 'cracks' }[view] || view;
  $$('[data-nav]').forEach((a) => { if (a.dataset.nav === tab) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  $('#backBtn').hidden = !['crack', 'result', 'analyze', 'shared'].includes(view);
  $('#brandBtn').hidden = !$('#backBtn').hidden;
  render();
  scrollTo(0, 0);
}
function render() {
  ({ measure: renderMeasure, analyze: renderAnalyze, result: renderResult, cracks: renderCracks, crack: renderCrack, shared: renderShared })[S.view]?.();
}
function refreshChrome() {
  const n = tracked().filter((c) => !c.example).length;
  const b = $('[data-count="cracks"]'); if (b) { b.textContent = n || ''; b.hidden = !n; }
}
function back() {
  if (S.view === 'result' || S.view === 'shared') return go(S.view === 'result' && crackById(S.crackId)?.tracked ? `crack/${S.crackId}` : 'cracks');
  if (S.view === 'analyze') return go(S.run?.mode === 'own' && !crackById(S.run.crackId)?.tracked ? 'measure' : S.run?.mode === 'example' ? 'measure' : 'cracks');
  return go('cracks');
}

// ------------------------------------------------------------------ 1 · MEASURE (first screen)
function stepArt(kind) {
  // simple line drawings, one per step (stroke icons in the app's own style)
  const svg = s('svg', { viewBox: '0 0 120 80', class: 'art', 'aria-hidden': 'true' });
  const add = (tag, attrs) => svg.append(s(tag, attrs));
  if (kind === 'print') {
    add('rect', { x: 30, y: 26, width: 60, height: 34, rx: 6, class: 'art__line' });
    add('path', { d: 'M42 26V10h36v16M42 52h36v20H42z', class: 'art__line' });
    for (let i = 0; i < 3; i++) for (let j = 0; j < 2; j++) if ((i + j) % 2 === 0) add('rect', { x: 50 + i * 7, y: 56 + j * 7, width: 7, height: 7, class: 'art__fill' });
    add('circle', { cx: 80, cy: 36, r: 2.5, class: 'art__accent' });
  } else if (kind === 'place') {
    add('path', { d: 'M10 10h100v60H10z', class: 'art__line art__wall' });
    add('path', { d: 'M74 10l-6 14 7 9-8 14 5 9-4 14', class: 'art__crack' });
    add('rect', { x: 32, y: 26, width: 24, height: 32, rx: 2, class: 'art__line art__card' });
    for (let i = 0; i < 3; i++) for (let j = 0; j < 4; j++) if ((i + j) % 2 === 0) add('rect', { x: 36 + i * 6, y: 30 + j * 6, width: 6, height: 6, class: 'art__fill' });
  } else {
    add('rect', { x: 40, y: 4, width: 40, height: 72, rx: 9, class: 'art__line' });
    add('path', { d: 'M74 14l-4 10 5 7-5 9 3 7-3 10', class: 'art__crack' });
    add('rect', { x: 47, y: 30, width: 14, height: 19, rx: 1.5, class: 'art__line art__card' });
    add('circle', { cx: 60, cy: 68, r: 3.5, class: 'art__line' });
  }
  return svg;
}
function renderMeasure() {
  const root = $('#view-measure'); root.textContent = '';
  root.append(h('h1', { class: 'display' }, t('valueLine')),
    h('p', { class: 'lede' }, t('valueSub')),
    h('div', { class: 'cta' },
      h('button', { class: 'btn btn--primary', type: 'button', onclick: () => pickFile() }, icon('camera'), h('span', null, t('measureCta'))),
      h('button', { class: 'btn btn--soft', type: 'button', onclick: () => startExample() }, h('span', null, t('exampleCta')))),
    h('p', { class: 'fine center' }, t('noAccount')));
  const steps = [['print', 'st1t', 'st1d', h('a', { class: 'link-btn', href: '/card.pdf', target: '_blank', rel: 'noopener', 'data-visit': 'card' }, icon('doc'), h('span', null, t('st1cta')))],
    ['place', 'st2t', 'st2d'], ['shoot', 'st3t', 'st3d']];
  root.append(h('section', { class: 'how', 'aria-labelledby': 'howTitle' }, h('h2', { class: 'section-title', id: 'howTitle' }, t('howTitle')),
    h('ol', { class: 'how__list' }, ...steps.map(([k, tt, dd, extra]) => h('li', { class: 'tile how__item' }, stepArt(k), h('div', null, h('h3', null, t(tt)), h('p', null, t(dd)), extra || null))))));
  root.append(h('p', { class: 'fine' }, t('privacy')));
}

// ------------------------------------------------------------------ 2 · ANALYSIS (pipeline in plain words, live)
function pipeline(d) {
  const m = d.measurement; const q = m.quality || {}; const cr = (m.cracks || [])[0];
  const sharp = (q.blur_sigma_px ?? 0) <= 2.2 && (q.saturated_frac || 0) <= 0.03 && (q.tilt_deg_est ?? 0) <= 55;
  const v = d.trace[d.trace.length - 1].action;
  const steps = [
    { ok: !!m.card, label: m.card ? t('pCard') : t('pNoCard'), detail: m.card ? t('pCardD', { n: m.card.corners }) : '' },
    { ok: !!m.card, skip: !m.card, label: t('pStraight'), detail: m.card ? t('pStraightD', { ppm: num(q.card_px_per_mm, 1) }) : '' },
    { ok: sharp, skip: !m.card, label: sharp ? t('pSharp') : t('pBlurry'), detail: m.card ? t('pSharpD', { b: num(q.blur_sigma_px, 1) }) : '' },
    { ok: !!cr, skip: !m.card || !sharp, label: cr || !m.card || !sharp ? t('pTraced') : t('pNoCrack'), detail: '' },
    { ok: !!cr, skip: !cr, label: t('pWidth'), detail: cr ? t('pWidthD', { v: Wt(cr.width_mm.max) }) : '' },
  ];
  if (d.comparison) steps.push({ ok: d.comparison.status === 'ok', label: t('pCompared'), detail: d.comparison.status === 'ok' ? Wt(d.comparison.width_delta_mm.median, { sign: true }) : '' });
  steps.push({ ok: true, agent: true, label: t('pDecision'), detail: v.planner && v.planner.includes('nova') ? 'Amazon Nova 2 Lite' : t('byRules') });
  return steps;
}
function renderAnalyze() {
  const root = $('#view-analyze'); const R = S.run;
  if (!R) return go('measure');
  root.textContent = '';
  const c = crackById(R.crackId); const ex = R.mode === 'example';
  const vNow = R.phase === 'done' ? verdict(R.shot, c) : null;
  const head = h('div', { class: 'an-head' }, h('h1', { class: 'title' }, R.phase === 'measuring' ? t('aMeasuring') : R.phase === 'error' ? t('aStopped') : vNow && vNow.kind === 'retake' ? t('aRetake') : t('aDone')));
  if (ex) head.append(h('span', { class: 'badge-example' }, t('exampleBadge')));
  root.append(head);
  if (ex) {
    const strip = h('ol', { class: 'ex-strip', 'aria-label': t('exStripAria') });
    STEPS.forEach((st, i) => strip.append(h('li', { class: i < R.step || (i === R.step && R.phase === 'done') ? 'is-done' : i === R.step ? 'is-now' : '' },
      h('span', { class: 'ex-strip__n' }, String(i + 1)), h('span', null, t(`ex${i + 1}`)))));
    root.append(strip);
  }
  const frame = h('div', { class: `photo ${R.phase === 'measuring' ? 'is-scanning' : ''}` });
  const img = h('img', { alt: R.phase === 'done' ? t('overlayAlt') : t('photoAlt') });
  if (R.phase === 'done' && R.result) img.src = `data:image/jpeg;base64,${R.result.overlay_jpeg_b64}`; else if (R.photo) img.src = R.photo;
  frame.append(img, h('span', { class: 'scan', 'aria-hidden': 'true' }));
  if (ex) frame.append(h('span', { class: 'photo__badge' }, t('exampleBadge')));
  root.append(frame);
  const list = h('ul', { class: 'ticks', 'aria-live': 'polite' });
  if (R.phase === 'measuring') {
    [t('pCard'), t('pStraight'), t('pSharp'), t('pTraced'), t('pWidth')].concat(ex && STEPS[R.step].previous ? [t('pCompared')] : []).forEach((l, i) =>
      list.append(h('li', { class: 'is-wait', style: `--i:${i}` }, h('span', { class: 'tick' }), h('span', null, l))));
    root.append(h('p', { class: 'muted center' }, R.uploading ? t('uploading') : warm ? t('aWait') : t('aWaitCold')));
  } else if (R.phase === 'done') {
    pipeline(R.result).forEach((x, i) => list.append(h('li', { class: x.skip ? 'is-skip' : x.ok ? 'is-ok' : 'is-bad', style: `--i:${i}` },
      h('span', { class: 'tick' }, icon(x.skip ? 'minus' : x.ok ? 'check' : 'x')), h('span', null, x.label), x.detail ? h('span', { class: 'ticks__d' }, x.detail) : null)));
  }
  root.append(list);
  const acts = h('div', { class: 'cta' });
  if (R.phase === 'error') {
    const e = R.error;
    const msg = e.code === 'daily_limit' || e.code === 'visitor_limit' ? e.message : e.code === 'image_unavailable' ? t('errExpired') : e.code === 'image_too_small' ? t('errSmall') : e.code === 'not_an_image' ? t('errNotImage') : t('errGeneric');
    root.append(h('div', { class: 'note note--watch', role: 'alert' }, h('strong', null, t('errTitle')), h('p', null, msg)));
    acts.append(h('button', { class: 'btn btn--primary', type: 'button', onclick: () => (ex ? runExampleStep(R.step) : R.file ? measureOwn(R.file) : pickFile(R.crackId)) }, icon('retry'), h('span', null, t('tryAgain'))));
  }
  if (R.phase === 'done') {
    const v = verdict(R.shot, c);
    if (v.kind === 'retake') {
      root.append(h('div', { class: 'note note--watch' }, h('strong', null, t('retakeAsk')), h('p', null, h('b', null, v.title), ' ', v.text)));
      if (ex) acts.append(h('button', { class: 'btn btn--primary', type: 'button', onclick: () => runExampleStep(R.step + 1) }, icon('camera'), h('span', null, t('exRetaken'))));
      else acts.append(h('button', { class: 'btn btn--primary', type: 'button', onclick: () => pickFile(c.id) }, icon('camera'), h('span', null, t('takeAnother'))));
    } else if (ex && R.step === 2) {
      root.append(h('div', { class: 'note' }, h('strong', null, t('ex3Note')), h('p', null, t('ex3NoteText', { v: Wt(R.shot.cracks[0].width_mm.max) }))));
      acts.append(h('button', { class: 'btn btn--primary', type: 'button', onclick: () => runExampleStep(3) }, h('span', null, t('exLater')), icon('chev-r')));
    } else {
      acts.append(h('button', { class: 'btn btn--primary', type: 'button', onclick: () => go(`result/${c.id}/${R.shot.id}`) }, h('span', null, t('seeResult')), icon('chev-r')));
    }
  }
  root.append(acts);
}

// ------------------------------------------------------------------ 3 · RESULT
function renderResult() {
  const root = $('#view-result'); root.textContent = '';
  const c = crackById(S.crackId); const sh = c && (findShot(c, S.shotId) || lastShot(c));
  if (!sh) return go('measure');
  const v = verdict(sh, c); const cr = sh.cracks && sh.cracks[0];
  if (c.example) root.append(h('span', { class: 'badge-example' }, t('exampleBadge')));
  const frame = h('div', { class: `photo ${sh.cu ? 'photo--wide' : ''}` });
  const im = h('img', { alt: t('overlayAlt'), class: sh.cu ? 'is-cover' : '' }); setImg(im, sh.cu || sh.img); frame.append(im);
  root.append(frame, h('p', { class: 'legend' }, h('span', { class: 'legend__ramp', 'aria-hidden': 'true' }), t('legend')));
  if (cr) {
    root.append(h('p', { class: 'kicker' }, t('maxWidth')), hero(cr.width_mm.max, { unc: 2 * cr.uncertainty_mm }));
  }
  root.append(h('div', { class: `verdict ${TONE_CLASS[v.tone]}` }, h('span', { class: 'verdict__dot', 'aria-hidden': 'true' }), h('div', null, h('h2', null, v.title), h('p', null, v.text))));
  if (cr) {
    const cmp = sh.comparison && sh.comparison.status === 'ok' ? sh.comparison : null;
    root.append(h('div', { class: 'facts' },
      h('div', { class: 'tile fact' }, h('span', null, t('typical')), h('strong', null, Wt(cr.width_mm.median))),
      cmp ? h('div', { class: 'tile fact' }, h('span', null, t('sinceLast')), h('strong', { class: cmp.width_delta_mm.median >= settings.wideningAlert ? 'is-act' : '' }, Wt(cmp.width_delta_mm.median, { sign: true })))
        : h('div', { class: 'tile fact' }, h('span', null, t('measuredIn')), h('strong', null, `${num((sh.timings?.total_ms || 0) / 1000, 1)} s`))));
    if (sh.truth) root.append(h('p', { class: 'fine' }, t('truthLine', { v: Wt(sh.truth.true_width_mm.max) })));
  }
  const acts = h('div', { class: 'cta' });
  if (v.kind === 'retake') acts.append(h('button', { class: 'btn btn--primary', type: 'button', onclick: () => (c.example ? startExample() : pickFile(c.id)) }, icon('camera'), h('span', null, t('takeAnother'))));
  else if (!c.tracked) {
    acts.append(h('button', { class: 'btn btn--primary', type: 'button', onclick: () => openTrack(c) }, icon('plus'), h('span', null, t('trackCta'))));
    acts.append(h('button', { class: 'btn btn--soft', type: 'button', disabled: !tracked().some((x) => !x.example), onclick: () => openCompare(c) }, h('span', null, t('compareCta'))));
    if (!tracked().some((x) => !x.example)) acts.append(h('p', { class: 'fine center' }, t('compareHint')));
  } else {
    if (sh.ticket && sh.ticket.status === 'pending_human_approval') acts.append(h('button', { class: 'btn btn--primary', type: 'button', onclick: () => openAlert(c, sh) }, icon('bell'), h('span', null, t('alertCta'))));
    acts.append(h('button', { class: `btn ${sh.ticket && sh.ticket.status === 'pending_human_approval' ? 'btn--soft' : 'btn--primary'}`, type: 'button', onclick: () => go(`crack/${c.id}`) }, h('span', null, c.example ? t('openExample') : t('openCrack')), icon('chev-r')));
  }
  root.append(acts);
  root.append(howMeasured(sh));
}
function howMeasured(sh) {
  const d = h('details', { class: 'tile more' }, h('summary', null, h('span', null, t('howMeasured')), icon('chev-d')));
  const ul = h('ul', { class: 'more__list' });
  (sh.trace || []).forEach((x) => ul.append(h('li', null, h('code', null, x.action.name), h('span', null, ` · ${x.action.planner && x.action.planner.includes('nova') ? 'Amazon Nova 2 Lite' : t('byRules')} · ${num(x.latency_ms || 0, 0)} ms`))));
  const q = sh.quality || {};
  d.append(h('p', null, t('howMeasuredText')), ul,
    h('p', { class: 'fine' }, t('techLine', { b: num(q.blur_sigma_px, 2), ppm: num(q.card_px_per_mm, 1), ms: sh.timings?.total_ms ?? '—', cost: num(sh.llm?.cost_usd || 0, 4) })),
    h('p', { class: 'fine' }, t('scaleNote')));
  return d;
}

// ------------------------------------------------------------------ 4 · MY CRACKS + crack detail
function thumb(c) {
  const img = h('img', { alt: '', class: 'thumb' });
  const sh = [...allShots(c)].reverse(); const cu = sh.find((x) => x.cu); const ba = sh.find((x) => x.ba); const ov = sh.find((x) => x.img);
  if (cu) setImg(img, cu.cu); else if (ba) idb.get(ba.ba).then((v) => { if (v) img.src = JSON.parse(v).after; }); else if (ov) setImg(img, ov.img);
  return img;
}
function renderCracks() {
  const root = $('#view-cracks'); root.textContent = '';
  const list = tracked();
  root.append(h('h1', { class: 'title-xl' }, t('myCracks')));
  if (!list.length) {
    root.append(h('div', { class: 'empty' }, stepArt('place'), h('h2', null, t('emptyTitle')), h('p', null, t('emptyText')),
      h('div', { class: 'cta' }, h('button', { class: 'btn btn--primary', type: 'button', onclick: () => pickFile() }, icon('camera'), h('span', null, t('measureCta'))),
        h('button', { class: 'btn btn--soft', type: 'button', onclick: () => startExample() }, t('exampleCta')))));
    return;
  }
  const ul = h('ul', { class: 'cards' });
  list.forEach((c) => {
    const ser = series(c); const last = ser[ser.length - 1];
    ul.append(h('li', null, h('a', { class: 'tile crack-card', href: `#crack/${c.id}` },
      h('div', { class: 'crack-card__top' }, thumb(c), h('div', { class: 'crack-card__id' }, h('strong', null, c.name), h('span', null, c.place || fmtDate(c.createdAt))), c.example ? h('span', { class: 'badge-example' }, t('exampleBadge')) : null),
      h('div', { class: 'crack-card__bottom' }, last ? hero(last.max, { cls: 'hero--md' }) : h('span', { class: 'muted' }, t('trNoPhoto')), chip(trendOf(c))))));
  });
  root.append(ul, h('div', { class: 'cta' }, h('button', { class: 'btn btn--soft', type: 'button', onclick: () => pickFile() }, icon('plus'), h('span', null, t('addCrack')))));
}
function miniChart(ser) {
  const W0 = 340; const H0 = 120; const pad = 12;
  const svg = s('svg', { viewBox: `0 0 ${W0} ${H0 + 22}`, class: 'mini', role: 'img', 'aria-label': t('chartAria', { n: ser.length }) });
  if (ser.length < 2) { const tx = s('text', { x: W0 / 2, y: H0 / 2, 'text-anchor': 'middle', class: 'mini__empty' }); tx.textContent = t('chartOne'); svg.append(tx); return svg; }
  const hi = Math.max(...ser.map((p) => p.max)) * 1.15; const lo = Math.min(...ser.map((p) => p.max)) * 0.7;
  const t0 = ser[0].at; const t1 = ser[ser.length - 1].at;
  const X = (ms) => pad + ((ms - t0) / (t1 - t0 || 1)) * (W0 - 2 * pad); const Y = (v) => H0 - pad - ((v - lo) / (hi - lo || 1)) * (H0 - 2 * pad);
  const d = ser.map((p, i) => `${i ? 'L' : 'M'}${X(p.at).toFixed(1)},${Y(p.max).toFixed(1)}`).join(' ');
  const id = uid();
  const grad = s('linearGradient', { id: `g${id}`, x1: 0, y1: 0, x2: 0, y2: 1 }); grad.append(s('stop', { offset: '0', class: 'mini__g0' }), s('stop', { offset: '1', class: 'mini__g1' }));
  const defs = s('defs'); defs.append(grad); svg.append(defs);
  svg.append(s('path', { d: `${d} L${X(t1)},${H0} L${X(t0)},${H0} Z`, fill: `url(#g${id})` }), s('path', { d, class: 'mini__line' }));
  ser.forEach((p, i) => { svg.append(s('circle', { cx: X(p.at), cy: Y(p.max), r: i === ser.length - 1 ? 6 : 4, class: i === ser.length - 1 ? 'mini__last' : 'mini__dot' }));
    const tx = s('text', { x: X(p.at), y: H0 + 18, 'text-anchor': i === 0 ? 'start' : i === ser.length - 1 ? 'end' : 'middle', class: 'mini__label' }); tx.textContent = fmtDate(p.at, { day: 'numeric', month: 'short' }); svg.append(tx); });
  return svg;
}
function beforeAfter(before, after, l1, l2) {
  const box = h('div', { class: 'ba', style: '--pos: 50%' });
  const range = h('input', { type: 'range', min: 0, max: 100, value: 50, class: 'ba__range', 'aria-label': t('baSlider') });
  range.addEventListener('input', () => box.style.setProperty('--pos', `${range.value}%`));
  box.append(h('img', { src: before, alt: t('beforeAlt', { d: l1 }) }), h('img', { src: after, alt: t('afterAlt', { d: l2 }), class: 'ba__after' }),
    h('span', { class: 'ba__line', 'aria-hidden': 'true' }, h('span', { class: 'ba__knob' }, icon('compare'))), h('span', { class: 'ba__tag ba__tag--l' }, l1), h('span', { class: 'ba__tag ba__tag--r' }, l2), range);
  return box;
}
function renderCrack() {
  const root = $('#view-crack'); root.textContent = '';
  const c = crackById(S.crackId); if (!c) return go('cracks');
  const ser = series(c); const last = ser[ser.length - 1]; const ls = lastShot(c);
  root.append(h('div', { class: 'crack-head' }, h('div', null, h('h1', { class: 'title' }, c.name), h('p', { class: 'muted' }, c.place || '')), c.example ? h('span', { class: 'badge-example' }, t('exampleBadge')) : null));
  if (last) root.append(hero(last.max, { unc: 2 * last.unc }), h('div', { class: 'chips' }, chip(trendOf(c))));
  const v = ls && verdict(ls, c);
  if (v) root.append(h('div', { class: `verdict ${TONE_CLASS[v.tone]}` }, h('span', { class: 'verdict__dot', 'aria-hidden': 'true' }), h('div', null, h('h2', null, v.title), h('p', null, v.text))));
  const baShot = [...allShots(c)].reverse().find((x) => x.ba);
  if (baShot) {
    const box = h('section', { class: 'block' }, h('h2', { class: 'section-title' }, t('beforeAfter')), h('div', { class: 'photo photo--wide' }));
    idb.get(baShot.ba).then((val) => { if (!val) return; const p = JSON.parse(val); $('.photo', box).append(beforeAfter(p.before, p.after, fmtDate(c.visits[0].at, { day: 'numeric', month: 'short' }), fmtDate(baShot.visitAt, { day: 'numeric', month: 'short' }))); });
    box.append(h('p', { class: 'fine' }, t('baNote')));
    root.append(box);
  } else if (ls && ls.img) {
    const f = h('div', { class: 'photo' }); const im = h('img', { alt: t('overlayAlt') }); setImg(im, ls.img); f.append(im); root.append(h('section', { class: 'block' }, f));
  }
  root.append(h('section', { class: 'block tile chart-tile' }, h('div', { class: 'chart-tile__head' }, h('h2', { class: 'section-title' }, t('overTime')), h('span', { class: 'muted' }, t('nMeasures', { n: ser.length }))), miniChart(ser)));
  const visits = h('ul', { class: 'visits tile' });
  [...c.visits].reverse().forEach((vv) => { if (!vv.shots.length) return; const m = [...vv.shots].reverse().find(isMeasured); const vs = verdict(vv.shots[vv.shots.length - 1], c);
    visits.append(h('li', null, h('span', null, fmtDate(vv.at)), h('strong', null, m ? Wt(m.cracks[0].width_mm.max) : '—'), h('span', { class: `dot ${TONE_CLASS[vs.tone]}`, title: vs.title }))); });
  root.append(h('section', { class: 'block' }, h('h2', { class: 'section-title' }, t('visits')), visits));
  const pend = allShots(c).find((x) => x.ticket && x.ticket.status === 'pending_human_approval');
  root.append(h('div', { class: 'cta' },
    h('button', { class: 'btn btn--primary', type: 'button', onclick: () => (c.example ? startExample() : pickFile(c.id)) }, icon('camera'), h('span', null, c.example ? t('replayExample') : t('measureAgain'))),
    h('button', { class: 'btn btn--soft', type: 'button', onclick: () => savePdf(c) }, icon('doc'), h('span', null, t('reportCta'))),
    h('button', { class: `btn btn--soft ${pend ? 'is-act' : ''}`, type: 'button', onclick: () => openAlert(c, pend || ls) }, icon('bell'), h('span', null, t('alertCta')))));
  root.append(h('div', { class: 'row-actions' },
    h('button', { class: 'link-btn', type: 'button', onclick: () => downloadIcs(c) }, icon('cal'), h('span', null, t('reminderCta'))),
    h('button', { class: 'link-btn', type: 'button', onclick: () => shareLink(c) }, icon('link'), h('span', null, t('shareCta'))),
    h('button', { class: 'link-btn', type: 'button', onclick: () => openTrack(c) }, icon('pencil'), h('span', null, t('renameCta'))),
    h('button', { class: 'link-btn is-danger', type: 'button', onclick: () => confirmDelete(c) }, icon('trash'), h('span', null, t('deleteCta')))));
}

// ------------------------------------------------------------------ sheets: track, compare, alert a professional, settings
function openTrack(c) {
  const b = $('#sheetBody'); b.textContent = ''; $('#sheetTitle').textContent = c.tracked ? t('renameCta') : t('trackCta');
  const name = h('input', { class: 'field', id: 'fName', maxlength: 60, value: c.name || '', placeholder: t('namePh'), autocapitalize: 'sentences', enterkeyhint: 'next' });
  const place = h('input', { class: 'field', id: 'fPlace', maxlength: 80, value: c.place || '', placeholder: t('placePh'), autocapitalize: 'sentences', enterkeyhint: 'done' });
  const err = h('p', { class: 'field-err', hidden: true }, t('nameErr'));
  b.append(h('label', { class: 'label', for: 'fName' }, t('nameLabel')), name, err, h('label', { class: 'label', for: 'fPlace' }, t('placeLabel')), place, h('p', { class: 'fine' }, t('onDevice')),
    h('div', { class: 'cta' }, h('button', { class: 'btn btn--primary', type: 'button', onclick: () => {
      const n = name.value.trim(); if (!n) { err.hidden = false; name.setAttribute('aria-invalid', 'true'); name.focus(); return; }
      c.name = n.slice(0, 60); c.place = place.value.trim().slice(0, 80); c.tracked = true; save(); closeSheet('sheet'); go(`crack/${c.id}`);
    } }, t('save'))));
  openSheet('sheet');
}
function openCompare(c) {
  const b = $('#sheetBody'); b.textContent = ''; $('#sheetTitle').textContent = t('compareCta');
  const own = tracked().filter((x) => !x.example);
  b.append(h('p', null, t('compareText')));
  const ul = h('ul', { class: 'pick' });
  own.forEach((x) => ul.append(h('li', null, h('button', { class: 'tile pick__row', type: 'button', onclick: async () => {
    // this photo becomes the newest visit of the chosen crack
    const sh = lastShot(c); if (!sh) return;
    x.visits.push({ id: uid(), at: sh.at, shots: [sh] }); data.cracks = data.cracks.filter((y) => y.id !== c.id); save(); closeSheet('sheet');
    go(`crack/${x.id}`); toast({ title: t('compared'), tone: 'ok' });
  } }, thumb(x), h('span', null, h('strong', null, x.name), h('small', null, x.place || '')), icon('chev-r')))));
  b.append(ul);
  openSheet('sheet');
}
function openAlert(c, sh) {
  const b = $('#sheetBody'); b.textContent = ''; $('#sheetTitle').textContent = t('alertCta');
  const v = sh && verdict(sh, c); const cr = sh && sh.cracks && sh.cracks[0];
  b.append(h('p', { class: 'lede-sm' }, t('alertText')));
  if (cr) b.append(h('div', { class: 'tile summary' }, h('strong', null, c.name), h('span', null, `${t('maxWidth')} ${Wt(cr.width_mm.max)} ± ${Wt(2 * cr.uncertainty_mm)}`), v ? h('span', null, v.title) : null));
  const note = h('textarea', { class: 'field', id: 'aNote', rows: 3, maxlength: 200, placeholder: t('notePh') });
  b.append(h('label', { class: 'label', for: 'aNote' }, t('noteLabel')), note);
  const go1 = h('button', { class: 'btn btn--primary', type: 'button' }, icon('doc'), h('span', null, t('alertSend')));
  go1.addEventListener('click', async () => {
    go1.disabled = true;
    if (sh && sh.ticket && sh.ticket.status === 'pending_human_approval') {
      try { await api(`/api/tickets/${sh.ticket.id}/decision`, { decision: 'approve', note: note.value.slice(0, 200) }); } catch { /* recorded on this device below */ }
      const real = findShot(c, sh.id); if (real) Object.assign(real.ticket, { status: 'approved', decidedAt: Date.now(), note: note.value.slice(0, 200) }); save();
    }
    closeSheet('sheet'); await savePdf(c); render();
  });
  b.append(h('div', { class: 'cta' }, go1, h('button', { class: 'btn btn--soft', type: 'button', onclick: () => closeSheet('sheet') }, t('notNow'))), h('p', { class: 'fine' }, t('alertFoot')));
  openSheet('sheet');
}
function seg(name, options, value, onChange) {
  const f = h('div', { class: 'seg', role: 'radiogroup' });
  options.forEach(([val, label]) => { const btn = h('button', { type: 'button', role: 'radio', 'aria-checked': String(String(val) === String(value)) }, label);
    btn.addEventListener('click', () => { $$('button', f).forEach((x) => x.setAttribute('aria-checked', String(x === btn))); onChange(val); }); f.append(btn); });
  return f;
}
function openSettings() {
  const b = $('#sheetBody'); b.textContent = ''; $('#sheetTitle').textContent = t('settings');
  const row = (label, ctrl) => h('div', { class: 'set-row' }, h('span', null, label), ctrl);
  b.append(row(t('setLang'), seg('lang', [['en', 'English'], ['fr', 'Français']], lang, (v) => setLang(v))),
    row(t('setTheme'), seg('theme', [['system', t('themeSystem')], ['light', t('themeLight')], ['dark', t('themeDark')]], settings.theme, (v) => { settings.theme = v; saveSettings(); setTheme(v); })),
    row(t('setUnits'), seg('units', [['mm', 'mm'], ['in', 'in']], settings.units, (v) => { settings.units = v; saveSettings(); render(); })),
    h('a', { class: 'link-btn', href: '/card.pdf', target: '_blank', rel: 'noopener', 'data-visit': 'card' }, icon('doc'), h('span', null, t('st1cta'))),
    h('button', { class: 'link-btn is-danger', type: 'button', onclick: () => { closeSheet('sheet'); setTimeout(confirmErase, 250); } }, icon('trash'), h('span', null, t('eraseAll'))),
    h('p', { class: 'fine' }, t('privacy')), h('p', { class: 'fine' }, t('credits')), h('p', { class: 'fine' }, t('disclaimer')));
  openSheet('sheet');
}
function setLang(v) {
  lang = T[v] ? v : 'en'; store.set('cw-lang', lang);
  const ex = crackById(EX_ID); if (ex) { ex.name = t('exName'); ex.place = t('exPlace'); save(); }
  applyLang(); visit('lang');
}
function applyLang() {
  document.documentElement.lang = lang;
  $$('[data-i18n]').forEach((n) => { n.textContent = t(n.dataset.i18n); });
  $$('[data-i18n-aria]').forEach((n) => { n.setAttribute('aria-label', t(n.dataset.i18nAria)); });
  $$('.lang [data-lang]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.lang === lang)));
  refreshChrome(); render();
}
function ask(title, text, okLabel, fn) {
  $('#alertTitle').textContent = title; $('#alertText').textContent = text; $('#alertOk').textContent = okLabel;
  $('#alertOk').onclick = () => { closeSheet('alert'); fn(); };
  $('#alertCancel').onclick = () => closeSheet('alert');
  openSheet('alert');
}
function confirmDelete(c) { ask(t('delTitle', { name: c.name }), t('delText'), t('deleteCta'), async () => { await dropImages(c); data.cracks = data.cracks.filter((x) => x.id !== c.id); save(); go('cracks'); }); }
function confirmErase() { ask(t('eraseTitle'), t('eraseText'), t('erase'), async () => { data.cracks = []; await idb.clear(); save(); toast({ title: t('erased'), tone: 'ok' }); go('measure'); }); }
function renderShared() {
  const root = $('#view-shared'); root.textContent = '';
  const p = S.shared;
  if (!p) { root.append(h('div', { class: 'empty' }, h('h2', null, t('sharedBad')), h('p', null, t('sharedBadText')))); return; }
  const last = p.ser[p.ser.length - 1];
  root.append(h('p', { class: 'muted' }, t('sharedBanner')), h('h1', { class: 'title' }, p.name), h('p', { class: 'muted' }, p.place || ''));
  if (last) root.append(hero(last.max, { unc: 2 * last.unc }));
  root.append(h('section', { class: 'block tile chart-tile' }, h('h2', { class: 'section-title' }, t('overTime')), miniChart(p.ser)),
    h('div', { class: 'cta' }, h('button', { class: 'btn btn--primary', type: 'button', onclick: () => { history.replaceState(null, '', '/'); go('measure'); } }, t('openApp'))));
}

// ------------------------------------------------------------------ calendar, share link, PDF report
// ------------------------------------------------------------------ calendar reminder (.ics)
function downloadIcs(c) {
  const st = crackStatus(c);
  const when = c.nextVisitAt || Date.now() + (st === 'needs_photo' ? 1 : 30) * DAY;
  const d = new Date(when); const pad = (n) => String(n).padStart(2, '0');
  const ymd = (x) => `${x.getFullYear()}${pad(x.getMonth() + 1)}${pad(x.getDate())}`;
  const d2 = new Date(when + DAY);
  const stamp = new Date().toISOString().replace(/[-:]/g, '').replace(/\.\d+Z$/, 'Z');
  const esc = (x) => String(x).replace(/[\\;,]/g, (m) => `\\${m}`).replace(/\n/g, '\\n');
  const ser = series(c); const last = ser[ser.length - 1];
  const desc = [t('icsDesc', { name: c.name }), last ? t('icsLast', { v: Wt(last.max), d: fmtDate(last.at) }) : '', `${location.origin}/`].filter(Boolean).join('\n');
  const ics = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//CrackWatch//EN', 'CALSCALE:GREGORIAN', 'BEGIN:VEVENT', `UID:${c.id}-${ymd(d)}@crackwatch`, `DTSTAMP:${stamp}`,
    `DTSTART;VALUE=DATE:${ymd(d)}`, `DTEND;VALUE=DATE:${ymd(d2)}`, `SUMMARY:${esc(t('icsTitle', { name: c.name }))}`, `DESCRIPTION:${esc(desc)}`,
    'BEGIN:VALARM', 'TRIGGER:-PT15H', 'ACTION:DISPLAY', `DESCRIPTION:${esc(t('icsTitle', { name: c.name }))}`, 'END:VALARM', 'END:VEVENT', 'END:VCALENDAR'].join('\r\n');
  if (!c.nextVisitAt) { c.nextVisitAt = when; save(); }
  const file = new File([ics], `CrackWatch - ${c.name}.ics`.replace(/[\\/:*?"<>|]/g, ''), { type: 'text/calendar' });
  saveFile(file, false);
  toast({ title: t('icsDone', { d: fmtDate(when) }), detail: t('icsDetail'), tone: 'ok' });
  if (S.view === 'crack') renderCrack();
}
async function saveFile(file, share = true) {
  if (share && matchMedia('(pointer: coarse)').matches && navigator.canShare?.({ files: [file] })) {
    try { await navigator.share({ files: [file], title: file.name }); return; } catch (e) { if (e?.name === 'AbortError') return; }
  }
  const a = h('a', { href: URL.createObjectURL(file), download: file.name }); document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

// ------------------------------------------------------------------ share link (summary in the URL fragment: never sent to the server)
const b64u = { enc: (s) => btoa(unescape(encodeURIComponent(s))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''), dec: (s) => decodeURIComponent(escape(atob(s.replace(/-/g, '+').replace(/_/g, '/')))) };
function shareLink(c) {
  const ser = series(c);
  const p = { v: 1, n: c.name, p: c.place || '', d: c.demo ? 1 : 0, s: crackStatus(c), nv: c.nextVisitAt || 0,
    pts: ser.map((x) => [Math.round(x.at / 60000), +x.max.toFixed(3), +x.med.toFixed(3), +(x.unc || 0).toFixed(3), +(x.len || 0).toFixed(0)]) };
  const url = `${location.origin}/#s=${b64u.enc(JSON.stringify(p))}`;
  const done = () => toast({ title: t('linkCopied'), detail: t('linkDetail'), tone: 'ok' });
  if (matchMedia('(pointer: coarse)').matches && navigator.share) navigator.share({ title: `CrackWatch · ${c.name}`, url }).catch(() => {});
  else if (navigator.clipboard) navigator.clipboard.writeText(url).then(done, () => prompt(t('copyThis'), url));
  else prompt(t('copyThis'), url);
}
function decodeShare(str) {
  try { const p = JSON.parse(b64u.dec(str)); if (p.v !== 1 || !Array.isArray(p.pts)) return null;
    return { name: String(p.n || '').slice(0, 60), place: String(p.p || '').slice(0, 80), demo: !!p.d, status: STATUS_TONE[p.s] ? p.s : 'stable', next: +p.nv || 0,
      ser: p.pts.slice(0, 50).map((x) => ({ at: x[0] * 60000, max: +x[1], med: +x[2], unc: +x[3], len: +x[4] })) };
  } catch { return null; }
}
// ------------------------------------------------------------------ PDF report (jsPDF served locally, loaded on demand)
function loadScript(src) { return new Promise((ok, ko) => { const x = document.createElement('script'); x.src = src; x.onload = ok; x.onerror = () => ko(new Error('script')); document.head.append(x); }); }
async function savePdf(c) {
  const btn = $('#pdfBtn') || document.createElement('i'); btn.setAttribute('aria-busy', 'true');
  try {
    if (!window.jspdf) await loadScript('/vendor/jspdf.umd.min.js');
    const doc = new window.jspdf.jsPDF({ unit: 'pt', format: 'a4' });
    const PW = doc.internal.pageSize.getWidth(); const PH = doc.internal.pageSize.getHeight(); const M = 48; const CW = PW - 2 * M;
    let y = M;
    const clean = (x) => String(x ?? '').replace(/ /g, ' ').replace(/σ/g, 's').replace(/[“”]/g, '"').replace(/[^\u0000-ɏ‘-„–—…·±]/g, '');
    const need = (hgt) => { if (y + hgt > PH - M) { doc.addPage(); y = M; } };
    const text = (str, { size = 10.5, bold = false, color = [28, 28, 30], gap = 4, x = M, w = CW } = {}) => {
      doc.setFont('helvetica', bold ? 'bold' : 'normal'); doc.setFontSize(size); doc.setTextColor(...color);
      for (const l of doc.splitTextToSize(clean(str), w)) { need(size * 1.4); doc.text(l, x, y + size); y += size * 1.38; }
      y += gap;
    };
    const ser = series(c); const last = ser[ser.length - 1]; const first = ser[0]; const ls = lastShot(c); const st = crackStatus(c);
    const grey = [110, 110, 118];
    text('CrackWatch', { size: 10, bold: true, color: grey, gap: 2 });
    text(t('pdfTitle', { name: c.name }), { size: 22, bold: true, gap: 2 });
    text([c.place, c.demo ? t('demoTag') : null, t('pdfGenerated', { d: fmtDate(Date.now(), { day: 'numeric', month: 'long', year: 'numeric' }) })].filter(Boolean).join(' · '), { size: 10, color: grey, gap: 14 });
    text(`${t('pdfStatus')}: ${t(`st_${st}`)}`, { size: 12, bold: true, gap: 4 });
    if (last) {
      const delta = crackDelta(c);
      const lines = [[t('sMax'), `${Wt(last.max)} ± ${Wt(2 * last.unc)} (2 sigma)`], [t('sMedShort'), Wt(last.med)], [t('sLen'), L(last.len)],
        [t('sChange'), delta != null ? `${Wt(delta, { sign: true })} ${t('sChangeDays', { days: Math.round((last.at - first.at) / DAY) })}` : t('sChangeFirst')],
        [t('sNext'), c.nextVisitAt ? fmtDate(c.nextVisitAt) : '—']];
      lines.forEach(([k, v]) => { need(16); doc.setFont('helvetica', 'normal'); doc.setFontSize(10.5); doc.setTextColor(...grey); doc.text(clean(k), M, y + 10.5); doc.setTextColor(28, 28, 30); doc.text(clean(v), M + 150, y + 10.5); y += 16; });
      y += 10;
      // chart
      if (ser.length) {
        need(150); const cx = M, cy = y, cw = CW, chh = 130;
        const vmax = Math.max(settings.widthAlert * 1.1, ...ser.map((p) => p.max + 2 * p.unc)) * 1.1;
        const t0 = ser[0].at, t1 = ser.length > 1 ? ser[ser.length - 1].at : t0 + 30 * DAY;
        const X = (ms) => cx + 40 + ((ms - t0) / (t1 - t0 || 1)) * (cw - 90); const Y = (mm) => cy + chh - (mm / vmax) * chh;
        doc.setDrawColor(220, 220, 225); doc.setLineWidth(0.5);
        for (let v = 0; v <= vmax; v += vmax > 1.6 ? 0.5 : 0.25) { doc.line(cx + 40, Y(v), cx + cw - 50, Y(v)); doc.setFontSize(8); doc.setTextColor(...grey); doc.text(clean(W(v)[0]), cx + 34, Y(v) + 3, { align: 'right' }); }
        doc.setDrawColor(255, 56, 60); doc.setLineDashPattern([3, 3], 0); doc.line(cx + 40, Y(settings.widthAlert), cx + cw - 50, Y(settings.widthAlert)); doc.setLineDashPattern([], 0);
        doc.setFontSize(8); doc.setTextColor(200, 40, 45); doc.text(clean(t('chartAlert', { v: Wt(settings.widthAlert) })), cx + 44, Y(settings.widthAlert) - 4);
        doc.setDrawColor(226, 86, 31); doc.setLineWidth(2);
        for (let i = 1; i < ser.length; i++) doc.line(X(ser[i - 1].at), Y(ser[i - 1].max), X(ser[i].at), Y(ser[i].max));
        ser.forEach((p) => { doc.setFillColor(226, 86, 31); doc.circle(X(p.at), Y(p.max), 3.5, 'F'); doc.setDrawColor(226, 86, 31); doc.setLineWidth(1); doc.line(X(p.at), Y(p.max + 2 * p.unc), X(p.at), Y(Math.max(0, p.max - 2 * p.unc)));
          doc.setFontSize(8); doc.setTextColor(...grey); doc.text(clean(fmtShort(p.at)), X(p.at), cy + chh + 12, { align: 'center' }); });
        y = cy + chh + 26;
        text(t('pdfChartNote'), { size: 8.5, color: grey, gap: 10 });
      }
    }
    // photos
    const imgShot = [...allShots(c)].reverse().find((x) => x.img); const baShot = [...allShots(c)].reverse().find((x) => x.ba);
    const addImg = async (src, w, x = M) => { const im = new Image(); im.src = src; await im.decode().catch(() => {}); const hh = w * (im.naturalHeight / (im.naturalWidth || 1)); need(hh + 4); doc.addImage(src, 'JPEG', x, y, w, hh); return hh; };
    if (baShot) {
      const p = JSON.parse(await idb.get(baShot.ba) || 'null');
      if (p) { const w = (CW - 12) / 2; need(w / 1.5 + 50); text(t('beforeAfter'), { size: 12, bold: true, gap: 4 }); const y0 = y; await addImg(p.before, w, M); y = y0; const hh = await addImg(p.after, w, M + w + 12); y = y0 + hh + 4;
        text(`${fmtDate(c.visits[0].at)}  ·  ${fmtDate(baShot.visitAt)}  —  ${t('baCaptionShort')}`, { size: 8.5, color: grey, gap: 12 }); }
    }
    if (imgShot) { const src = await idb.get(imgShot.img); if (src) { need(CW * 0.8 * 0.75 + 30); text(t('latestPhoto'), { size: 12, bold: true, gap: 4 }); const hh = await addImg(src, CW * 0.8); y += hh + 4; text(t('caption'), { size: 8.5, color: grey, gap: 12 }); } }
    // inspector + ticket
    if (ls) {
      text(t('pdfInspector'), { size: 12, bold: true, gap: 4 });
      text(`${decisionTitle(ls)} — ${decidedBy(ls)}`, { size: 10.5, bold: true, gap: 2 });
      text(decisionWhy(ls), { size: 10.5, gap: 10 });
      if (ls.ticket) text(`${t('pdfTicket')}: ${ls.ticket.status === 'pending_human_approval' ? t('tk_pending') : t(`tk_${ls.ticket.status}`)}${ls.ticket.note ? ` — ${ls.ticket.note}` : ''}`, { size: 10.5, gap: 10 });
    }
    // visits
    text(t('timeline'), { size: 12, bold: true, gap: 4 });
    c.visits.forEach((v, i) => { if (!v.shots.length) return; text(`${t('visitN', { n: i + 1 })} · ${fmtDate(v.at)}`, { size: 10.5, bold: true, gap: 1 });
      v.shots.forEach((sh) => { const cr = sh.cracks && sh.cracks[0]; text(`– ${decisionTitle(sh)}${cr ? ` · ${t('shotMeasured', { max: Wt(cr.width_mm.max), u: Wt(2 * cr.uncertainty_mm), len: L(cr.length_mm) })}` : ''}${sh.truth ? ` · ${t('truthShort', { max: Wt(sh.truth.true_width_mm.max), med: Wt(sh.truth.true_width_mm.median) })}` : ''}`, { size: 9.5, gap: 1, x: M + 10, w: CW - 10 }); });
      y += 6; });
    y += 6;
    text(t('pdfMethod'), { size: 8.5, color: grey, gap: 4 });
    if (c.demo) text(t('pdfDemo'), { size: 8.5, color: grey, gap: 4 });
    text(t('disclaimer'), { size: 8.5, color: grey });
    const file = new File([doc.output('blob')], `CrackWatch - ${clean(c.name)}.pdf`.replace(/[\\/:*?"<>|]/g, ''), { type: 'application/pdf' });
    await saveFile(file, true);
  } catch (e) {
    toast({ title: t('pdfFailed'), detail: t('pdfFailedDetail'), tone: 'critical' });
  } finally { btn.removeAttribute('aria-busy'); }
}


// ------------------------------------------------------------------ service status + wiring
function wire() {
  addEventListener('hashchange', route);
  $('#backBtn').addEventListener('click', back);
  $('#brandBtn').addEventListener('click', () => go(tracked().length ? 'cracks' : 'measure'));
  $('#settingsBtn').addEventListener('click', openSettings);
  $$('.lang [data-lang]').forEach((b) => b.addEventListener('click', () => setLang(b.dataset.lang)));
  $('#fileInput').addEventListener('change', (e) => { const f = e.target.files && e.target.files[0]; if (f) measureOwn(f); });
  document.addEventListener('click', (e) => { const v = e.target.closest('[data-visit]'); if (v) visit(v.dataset.visit); });
  document.addEventListener('gesturestart', (e) => e.preventDefault());
}
function boot() {
  if (settings.theme !== 'system') setTheme(settings.theme);
  wire();
  applyLang();
  route();
  fetch('/samples/samples.json').then((r) => r.json()).then((j) => { truth = j; }).catch(() => {});
  fetch('/api/health').then((r) => (r.ok ? r.json() : false)).then((j) => { health = j; }).catch(() => { health = false; });
  let ref = '';
  try { const hn = document.referrer ? new URL(document.referrer).hostname.replace(/^www\./, '') : ''; ref = hn && hn !== location.hostname ? hn : ''; } catch { /* ignore */ }
  visit('view', { ref, utm: new URLSearchParams(location.search).get('utm_source') || '' });
}
boot();

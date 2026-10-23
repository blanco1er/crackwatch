// CrackWatch app. No framework, no third-party request. Server data is always inserted as text (textContent).
// Data lives on this device: crack list in localStorage, images in IndexedDB. Photos sent for measurement go to a
// private S3 bucket through a presigned POST and are deleted after 24 h.
import { UI, toast, openSheet, closeSheet, setTheme } from '/ds/motion.js';
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
let lang = store.get('cw-lang') || ((navigator.language || '').startsWith('fr') ? 'fr' : 'en');
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
const DATA_KEY = 'cw-data-v2';
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

// ------------------------------------------------------------------ demo story (4 synthetic photos of one wall)
const DEMO_ID = 'demo';
const STEPS = [
  { id: 'blurry', visit: 0, retakes: 0, title: 's1t', sub: 's1d' },
  { id: 'far', visit: 0, retakes: 1, title: 's2t', sub: 's2d' },
  { id: 'close', visit: 0, retakes: 2, title: 's3t', sub: 's3d' },
  { id: 'visit2', visit: 1, retakes: 0, title: 's4t', sub: 's4d', previous: 'close' },
];
let truth = null;
function demoDates() { const now = Date.now(); return [now - 91 * DAY, now]; }
function ensureDemo() {
  let c = crackById(DEMO_ID);
  if (!c) {
    const [d1, d2] = demoDates();
    c = { id: DEMO_ID, demo: true, name: t('demoName'), place: t('demoPlace'), createdAt: d1, nextVisitAt: null,
      visits: [{ id: 'v1', at: d1, shots: [] }, { id: 'v2', at: d2, shots: [] }] };
    data.cracks.unshift(c);
    save();
  }
  return c;
}
async function resetDemo() {
  const c = crackById(DEMO_ID);
  if (c) for (const sh of allShots(c)) { if (sh.img) await idb.del(sh.img); if (sh.ba) await idb.del(sh.ba); }
  data.cracks = data.cracks.filter((x) => x.id !== DEMO_ID);
  save();
}

// ------------------------------------------------------------------ routing
const S = { view: 'walls', crackId: null, run: null, mediaMode: 'compare', shared: null };
function route() {
  const hsh = location.hash.replace(/^#/, '');
  if (hsh.startsWith('s=')) { S.shared = decodeShare(hsh.slice(2)); return show('shared'); }
  const [v, id] = hsh.split('/');
  if (v === 'crack' && id && crackById(id)) { S.crackId = id; return show('crack'); }
  if (v === 'inspect' && S.run) return show('inspect');
  if (['walls', 'tickets', 'settings'].includes(v)) return show(v);
  return show('walls');
}
function go(hash) { if (location.hash === `#${hash}`) route(); else location.hash = hash; }
function show(view) {
  S.view = view;
  $$('.view').forEach((x) => { x.hidden = x.dataset.view !== view; });
  const tab = { crack: 'walls', inspect: 'walls', shared: 'walls' }[view] || view;
  $$('[data-nav]').forEach((a) => { if (a.dataset.nav === tab && view !== 'crack' && view !== 'shared') a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  const tb = $('.ui-tabbar'); const item = $(`.ui-tabbar__item[data-nav="${tab}"]`);
  if (tb && item) tb.dispatchEvent(new CustomEvent('ui:select', { detail: item }));
  $('#backBtn').hidden = !['crack', 'inspect', 'shared'].includes(view);
  $('#crackTools').hidden = view !== 'crack';
  $$('.ui-nav-item[data-crack]').forEach((a) => { if (view === 'crack' && a.dataset.crack === S.crackId) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  closeSidebar();
  render();
  if (!reduceMotion()) scrollTo({ top: 0 }); else scrollTo(0, 0);
}
function render() {
  ({ walls: renderWalls, crack: renderCrack, inspect: renderInspect, tickets: renderTickets, settings: renderSettings, shared: renderShared })[S.view]?.();
  document.title = S.view === 'walls' ? 'CrackWatch' : `${$('#tbTitle').textContent} · CrackWatch`;
}
function setTitle(title, sub = '') { $('#tbTitle').textContent = title; $('#tbSub').textContent = sub; }

// ------------------------------------------------------------------ chrome (sidebar list, counts, badges)
function refreshChrome() {
  const side = $('#sideCracks');
  side.textContent = '';
  if (!data.cracks.length) side.append(h('p', { class: 'side-empty ui-footnote ui-secondary' }, t('sideEmpty')));
  data.cracks.forEach((c) => {
    const ser = series(c); const last = ser[ser.length - 1]; const st = crackStatus(c);
    side.append(h('a', { class: 'ui-nav-item side-crack', href: `#crack/${c.id}`, 'data-crack': c.id, 'aria-current': S.view === 'crack' && S.crackId === c.id ? 'page' : null },
      h('span', { class: `dot dot--${STATUS_TONE[st]}`, 'aria-hidden': 'true' }),
      h('span', { class: 'side-crack__text' }, h('span', { class: 'side-crack__name' }, c.name), h('small', null, `${t(`st_${st}`)}${last ? ` · ${Wt(last.max)}` : ''}`))));
  });
  $('[data-count="cracks"]').textContent = data.cracks.length || '';
  const pend = pendingTickets().length;
  $('[data-count="tickets"]').textContent = pend || '';
  const b = $('[data-badge="tickets"]'); b.hidden = !pend; b.textContent = pend;
}
function closeSidebar() { $('#app').classList.remove('is-sidebar-open'); $('.sidebar-scrim').hidden = true; }

// ------------------------------------------------------------------ shared UI pieces
function stat(label, value, unit, delta, cls) {
  return h('div', { class: `ui-stat ${cls || ''}`, role: 'listitem' }, h('p', { class: 'ui-stat__label' }, label),
    h('p', { class: 'ui-stat__value' }, value, unit ? h('small', null, unit) : null), delta ? h('p', { class: 'ui-stat__delta' }, delta) : null);
}
function sectionHead(title, aside) { return h('div', { class: 'ui-list__header' }, h('strong', null, title), aside ? (aside.nodeType ? aside : h('span', null, aside)) : null); }
function banner(tone, title, text, action) {
  return h('div', { class: `ui-banner ui-banner--${tone}`, role: tone === 'critical' ? 'alert' : 'status' }, icon(tone === 'info' ? 'info' : 'alert'),
    h('div', { style: 'flex:1;min-width:0' }, h('strong', null, title), text ? h('p', null, text) : null), action || null);
}
function sparkline(ser) {
  const svg = s('svg', { viewBox: '0 0 64 24', class: 'spark', 'aria-hidden': 'true' });
  if (ser.length < 2) { if (ser.length === 1) svg.append(s('circle', { cx: 32, cy: 12, r: 2.5, class: 'spark__dot' })); return svg; }
  const ys = ser.map((p) => p.max); const lo = Math.min(...ys) * 0.9; const hi = Math.max(...ys) * 1.05 || 1;
  const pts = ser.map((p, i) => [2 + (i * 60) / (ser.length - 1), 21 - ((p.max - lo) / (hi - lo || 1)) * 18]);
  svg.append(s('polyline', { points: pts.map((p) => p.join(',')).join(' '), class: 'spark__line' }));
  const [x, y] = pts[pts.length - 1]; svg.append(s('circle', { cx: x, cy: y, r: 2.5, class: 'spark__dot' }));
  return svg;
}
// width over time: max (with ±2σ bars) and median, alert threshold dashed
function widthChart(ser, { compact = false } = {}) {
  const wrap = h('figure', { class: 'ui-chart width-chart' });
  const narrow = innerWidth < 700; const Wd = narrow ? 350 : 640; const Hd = narrow ? 210 : (compact ? 180 : 240); const pad = { l: 40, r: narrow ? 18 : 40, t: 22, b: 28 };
  const svg = s('svg', { viewBox: `0 0 ${Wd} ${Hd}`, role: 'img', 'aria-label': t('chartAria', { n: ser.length }) });
  const inch = settings.units === 'in'; const k = inch ? 1 / 25.4 : 1;
  const vmax = Math.max(settings.widthAlert * 1.1, ...ser.map((p) => p.max + 2 * (p.unc || 0))) * 1.08;
  const t0 = ser.length ? ser[0].at : Date.now(); const t1 = ser.length > 1 ? ser[ser.length - 1].at : t0 + 30 * DAY;
  const X = (ms) => pad.l + ((ms - t0) / (t1 - t0 || 1)) * (Wd - pad.l - pad.r);
  const Y = (mm) => Hd - pad.b - (mm / vmax) * (Hd - pad.t - pad.b);
  const step = vmax > 1.6 ? 0.5 : vmax > 0.8 ? 0.25 : 0.1;
  for (let v = 0; v <= vmax + 1e-9; v += step) {
    svg.append(s('line', { x1: pad.l, x2: Wd - pad.r, y1: Y(v), y2: Y(v), class: 'ui-chart__grid' }));
    const lab = s('text', { x: pad.l - 8, y: Y(v) + 4, 'text-anchor': 'end', class: 'ui-chart__label' }); lab.textContent = num(v * k, inch ? 2 : (step < 0.25 ? 1 : 2)); svg.append(lab);
  }
  // alert threshold
  const yt = Y(settings.widthAlert);
  svg.append(s('line', { x1: pad.l, x2: Wd - pad.r, y1: yt, y2: yt, class: 'ui-chart__threshold' }));
  const tl = s('text', { x: pad.l + 4, y: yt - 6, class: 'ui-chart__label chart-th' }); tl.textContent = t('chartAlert', { v: Wt(settings.widthAlert) }); svg.append(tl);
  if (ser.length) {
    const path = (key) => ser.map((p, i) => `${i ? 'L' : 'M'}${X(p.at).toFixed(1)},${Y(p[key]).toFixed(1)}`).join(' ');
    if (ser.length > 1) {
      svg.append(s('path', { d: `${path('max')} L${X(ser[ser.length - 1].at)},${Y(0)} L${X(ser[0].at)},${Y(0)} Z`, class: 'ui-chart__area', style: '--_c: var(--width-color)' }));
      svg.append(s('path', { d: path('med'), class: 'ui-chart__line chart-med' }));
      svg.append(s('path', { d: path('max'), class: 'ui-chart__line', style: '--_c: var(--width-color)' }));
    }
    ser.forEach((p, i) => {
      const x = X(p.at);
      if (p.unc) svg.append(s('line', { x1: x, x2: x, y1: Y(p.max + 2 * p.unc), y2: Y(Math.max(0, p.max - 2 * p.unc)), class: 'chart-err' }));
      svg.append(s('circle', { cx: x, cy: Y(p.med), r: 3.5, class: 'ui-chart__dot chart-med-dot' }));
      svg.append(s('circle', { cx: x, cy: Y(p.max), r: 5, class: 'ui-chart__dot', style: '--_c: var(--width-color)' }));
      const dl = s('text', { x, y: Hd - 8, 'text-anchor': i === 0 ? 'start' : i === ser.length - 1 && ser.length > 1 ? 'end' : 'middle', class: 'ui-chart__label' }); dl.textContent = fmtShort(p.at); svg.append(dl);
      if (i === ser.length - 1) {
        const v1 = s('text', { x: X(p.at) - (ser.length > 1 ? 8 : -10), y: Y(p.max) - 12, 'text-anchor': ser.length > 1 ? 'end' : 'start', class: 'chart-end' }); v1.textContent = Wt(p.max); svg.append(v1);
      }
    });
  }
  wrap.append(svg);
  wrap.append(h('ul', { class: 'ui-chart__legend' }, h('li', { style: '--_c: var(--width-color)' }, t('legendMax')), h('li', { style: '--_c: var(--label-secondary)' }, t('legendMed')), h('li', { class: 'is-dashed', style: '--_c: var(--chart-threshold)' }, t('legendAlert'))));
  return wrap;
}
function plannerLabel(p) {
  if (!p) return '';
  if (p.includes('nova')) return 'Amazon Nova 2 Lite';
  if (p.toLowerCase().includes('claude')) return 'Claude on Amazon Bedrock';
  const m = p.match(/^rules(?: \((.*)\))?/);
  return m ? `${t('planRules')}${m[1] ? ` (${m[1]})` : ''}` : p;
}

// ------------------------------------------------------------------ WALLS (home)
function renderWalls() {
  const root = $('#view-walls');
  root.textContent = '';
  const n = data.cracks.length;
  setTitle(t('navWalls'), n ? t('wallsSub', { n }) : t('wallsSubEmpty'));
  const demo = crackById(DEMO_ID);
  const own = data.cracks.filter((c) => !c.demo);

  // lead: the result in one sentence, then the two entry points
  const lead = h('div', { class: 'lead' });
  const st = data.cracks.map(crackStatus);
  const widening = data.cracks.filter((c, i) => st[i] === 'widening');
  const needs = data.cracks.filter((c, i) => st[i] === 'needs_photo');
  const pend = pendingTickets();
  let sentence;
  if (!n) sentence = t('leadEmpty');
  else if (widening.length) { const c = widening[0]; const ser = series(c); const d = crackDelta(c); sentence = t('leadWidening', { n: widening.length, name: c.name, d: d != null ? Wt(d, { sign: true }) : '', tk: pend.length }); }
  else if (needs.length) sentence = t('leadNeeds', { n: needs.length, name: needs[0].name });
  else sentence = t('leadStable', { n });
  lead.append(h('p', { class: 'summary' }, rich(sentence)));
  const acts = h('div', { class: 'lead-actions' },
    h('button', { class: 'ui-button ui-button--prominent ui-button--lg', type: 'button', onclick: () => startDemo() }, icon('play', 'ui-icon is-filled'), h('span', null, demo ? t('replayDemo') : t('runDemo'))),
    h('button', { class: 'ui-button ui-button--lg', type: 'button', onclick: () => openNewPhoto() }, icon('camera'), h('span', null, t('trackOwn'))),
    h('p', { class: 'ui-footnote ui-secondary lead-note' }, t('demoNote')));
  lead.append(acts);
  if (pend.length) {
    const p = pend[0];
    lead.append(banner('critical', t('ticketWaiting', { n: pend.length }), t('ticketWaitingText', { name: p.crack.name }),
      h('button', { class: 'ui-button ui-button--sm', type: 'button', onclick: () => openTicket(p.crack.id, p.shot.id) }, t('review'))));
  }
  if (n) {
    const next = data.cracks.map((c) => c.nextVisitAt).filter(Boolean).sort()[0];
    const stats = h('div', { class: 'ui-stats home-stats', role: 'list' },
      stat(t('statTracked'), String(n), null, own.length ? t('statOwn', { n: own.length }) : t('statDemoOnly')),
      stat(t('statWidening'), String(widening.length), null, widening.length ? widening[0].name : t('statNone'), widening.length ? 'is-critical' : ''),
      stat(t('statNeeds'), String(needs.length), null, needs.length ? needs[0].name : t('statNone')),
      stat(t('statNext'), next ? fmtShort(next) : '—', null, next ? t('inDays', { n: Math.max(0, Math.round((next - Date.now()) / DAY)) }) : t('statNoReminder')));
    lead.append(stats);
  }
  root.append(lead);

  // crack list
  const grid = h('div', { class: 'grid-main block' });
  const listSec = h('div', { class: 'ui-list-section' });
  listSec.append(sectionHead(t('yourCracks'), n ? t('tapToOpen') : null));
  if (n) {
    const ul = h('ul', { class: 'ui-list crack-list' });
    data.cracks.forEach((c, i) => ul.append(h('li', null, crackRow(c, st[i]))));
    listSec.append(ul);
    listSec.append(h('p', { class: 'ui-list__footer' }, t('listFoot')));
  } else {
    listSec.append(h('div', { class: 'ui-surface empty-card' }, h('div', { class: 'ui-empty' },
      h('span', { class: 'ui-empty__icon' }, icon('crack')), h('h3', null, t('emptyTitle')), h('p', null, t('emptyBody')),
      )));
  }
  grid.append(listSec);

  // onboarding: three steps to track a real crack
  const ob = h('div', { class: 'ui-list-section' });
  ob.append(sectionHead(t('obTitle'), own.length ? null : t('obAside')));
  const steps = h('ul', { class: 'ui-list how' });
  [['card', 'ob1t', 'ob1d', h('a', { class: 'ui-button ui-button--sm ui-button--tinted', href: '/card.pdf', target: '_blank', rel: 'noopener', 'data-visit': 'card' }, t('printCard'))],
    ['crack', 'ob2t', 'ob2d'], ['camera', 'ob3t', 'ob3d', h('button', { class: 'ui-button ui-button--sm ui-button--tinted', type: 'button', onclick: () => openNewPhoto() }, t('takePhoto'))]]
    .forEach(([ic, tt, dd, btn], i) => steps.append(h('li', null, h('div', { class: 'ui-row' }, h('span', { class: 'how-n' }, String(i + 1)),
      h('div', { class: 'ui-row__body' }, h('span', { class: 'ui-row__title' }, t(tt)), h('span', { class: 'ui-row__subtitle' }, t(dd))), btn || null))));
  ob.append(steps);
  ob.append(h('p', { class: 'ui-list__footer' }, t('privacyShort'), ' ', h('button', { class: 'linkish', type: 'button', 'data-help': '' }, t('howItWorks'))));
  grid.append(ob);
  root.append(grid);
  root.append(h('p', { class: 'fine' }, t('proof')));
}
function crackRow(c, st) {
  const ser = series(c); const last = ser[ser.length - 1]; const ls = lastShot(c);
  const thumb = h('img', { class: 'crack-thumb', alt: '', loading: 'lazy' });
  const src = [...allShots(c)].reverse().find((x) => x.ba)?.ba; const ov = [...allShots(c)].reverse().find((x) => x.img)?.img;
  if (src) idb.get(src).then((v) => { if (v) thumb.src = JSON.parse(v).after; else if (ov) setImg(thumb, ov); });
  else if (ov) setImg(thumb, ov);
  const when = ls ? t('lastPhoto', { d: fmtDate(ls.at) }) : t('noPhotoYet');
  return h('a', { class: 'ui-row crack-row', href: `#crack/${c.id}` },
    h('span', { class: 'thumb-wrap' }, thumb, icon('crack', 'ui-icon thumb-fallback')),
    h('div', { class: 'ui-row__body' },
      h('span', { class: 'ui-row__title' }, c.name, c.demo ? h('span', { class: 'tag' }, t('demoTag')) : null),
      h('span', { class: 'ui-row__subtitle' }, [c.place, when].filter(Boolean).join(' · ')),
      h('span', { class: 'row-status' }, statusEl(st))),
    h('div', { class: 'row-end' }, h('span', { class: 'row-value' }, last ? W(last.max)[0] : '—', last ? h('small', null, ` ${W(last.max)[1]}`) : null), sparkline(ser)),
    icon('chev-r', 'ui-icon ui-row__chevron'));
}

// ------------------------------------------------------------------ CRACK detail
function renderCrack() {
  const c = crackById(S.crackId);
  const root = $('#view-crack');
  root.textContent = '';
  if (!c) return go('walls');
  setTitle(c.name, [c.place, c.demo ? t('demoTag') : null].filter(Boolean).join(' · '));
  const ser = series(c); const last = ser[ser.length - 1]; const first = ser[0]; const ls = lastShot(c); const st = crackStatus(c);
  const shots = allShots(c);
  const lead = h('div', { class: 'lead' });
  // sentence
  let sentence;
  const cmpOk = ls && ls.comparison && ls.comparison.status === 'ok' ? ls.comparison : null;
  const delta = ser.length > 1 ? (cmpOk ? cmpOk.width_delta_mm.median : last.max - first.max) : null;
  const days = ser.length > 1 ? Math.round((last.at - first.at) / DAY) : 0;
  if (!ls) sentence = t('cNone');
  else if (st === 'needs_photo') sentence = t('cNeeds', { why: decisionTitle(ls) });
  else if (st === 'widening') sentence = t('cWidening', { a: Wt(first.max), b: Wt(last.max), d: Wt(delta, { sign: true }), days, u: Wt(2 * (last.unc || 0)) });
  else if (st === 'above') sentence = t('cAbove', { v: Wt(last.max), th: Wt(settings.widthAlert) });
  else sentence = t('cStable', { v: Wt(last.max), u: Wt(2 * (last.unc || 0)), n: ser.length });
  lead.append(h('p', { class: 'summary' }, rich(sentence)));
  const pend = shots.filter((x) => x.ticket && x.ticket.status === 'pending_human_approval');
  if (pend.length) lead.append(banner('critical', t('ticketPending'), t('ticketPendingText'), h('button', { class: 'ui-button ui-button--sm', type: 'button', onclick: () => openTicket(c.id, pend[0].id) }, t('review'))));
  // hero numbers
  if (last) {
    const ds = cmpOk;
    lead.append(h('div', { class: 'ui-stats crack-stats', role: 'list' },
      stat(t('sMax'), W(last.max)[0], W(last.max)[1], `± ${Wt(2 * last.unc)} (2σ)`, 'is-width'),
      stat(t('sChange'), delta != null ? W(delta, { sign: true })[0] : '—', delta != null ? W(delta)[1] : null,
        delta != null ? (ds ? t('sChangeReg', { u: Wt(2 * ds.delta_uncertainty_mm), days }) : t('sChangeDays', { days })) : t('sChangeFirst'), st === 'widening' ? 'is-critical' : ''),
      stat(t('sLen'), settings.units === 'in' ? num(last.len / 25.4, 1) : num(last.len, 0), settings.units === 'in' ? 'in' : 'mm', t('sMed', { v: Wt(last.med) })),
      stat(t('sNext'), c.nextVisitAt ? fmtShort(c.nextVisitAt) : '—', null, c.nextVisitAt ? t('inDays', { n: Math.max(0, Math.round((c.nextVisitAt - Date.now()) / DAY)) }) : t('statNoReminder'))));
  }
  const primary = h('div', { class: 'lead-actions' },
    h('button', { class: 'ui-button ui-button--prominent', type: 'button', onclick: () => (c.demo ? startDemo(nextDemoStep(c)) : openNewPhoto(c.id)) }, icon('camera'), h('span', null, c.demo ? (nextDemoStep(c) != null ? t('continueDemo') : t('replayDemo')) : t('newPhotoOf'))),
    h('button', { class: 'ui-button', type: 'button', onclick: () => downloadIcs(c) }, icon('cal'), h('span', null, t('addReminder'))),
    h('button', { class: 'ui-button', type: 'button', onclick: () => savePdf(c) }, icon('doc'), h('span', null, t('pdfReport'))));
  lead.append(primary);
  root.append(lead);
  if (!ls) {
    root.append(h('div', { class: 'ui-surface empty-card block' }, h('div', { class: 'ui-empty' }, h('span', { class: 'ui-empty__icon' }, icon('camera')), h('h3', null, t('cEmptyTitle')), h('p', null, t('cEmptyBody')),
      h('button', { class: 'ui-button ui-button--prominent', type: 'button', onclick: () => openNewPhoto(c.id) }, t('takePhoto')))));
    root.append(crackManage(c));
    return;
  }

  // media: annotated photo / aligned before-after
  const media = h('section', { class: 'block media-block', 'aria-label': t('photoTitle') });
  const baShot = [...shots].reverse().find((x) => x.ba);
  const imgShot = [...shots].reverse().find((x) => x.img);
  const frame = h('div', { class: 'photo-frame' });
  const mode = baShot ? S.mediaMode : 'measured';
  const head = h('div', { class: 'media-head' }, h('h2', { class: 'ui-title3' }, mode === 'compare' ? t('beforeAfter') : t('latestPhoto')));
  if (baShot) {
    const seg = h('fieldset', { class: 'ui-segmented media-seg', 'aria-label': t('photoTitle') },
      h('label', null, h('input', { type: 'radio', name: 'media', value: 'measured', checked: mode === 'measured' }), t('measured')),
      h('label', null, h('input', { type: 'radio', name: 'media', value: 'compare', checked: mode === 'compare' }), t('beforeAfter')));
    seg.addEventListener('change', (e) => { S.mediaMode = e.target.value; renderCrack(); });
    head.append(seg);
  }
  media.append(head, frame);
  if (mode === 'compare') {
    idb.get(baShot.ba).then((v) => { if (!v) return; const p = JSON.parse(v); frame.append(beforeAfter(p.before, p.after, fmtDate(c.visits[0].at), fmtDate(baShot.visitAt))); });
    media.append(h('p', { class: 'ui-footnote ui-secondary caption' }, t('baCaption', { reg: baShot.comparison?.registration?.mode === 'texture_homography' ? t('regTex') : t('regCard') })));
  } else if (imgShot) {
    const im = h('img', { alt: t('overlayAlt'), class: 'photo' }); setImg(im, imgShot.img); frame.append(im);
    if (c.demo) frame.append(h('span', { class: 'photo-chip ui-glass-clear is-dimmed' }, t('syntheticPhoto')));
    media.append(h('p', { class: 'ui-footnote ui-secondary caption' }, t('caption')));
  }
  root.append(media);

  // chart + inspector side by side on wide screens
  const grid = h('div', { class: 'grid-main block' });
  const chartSec = h('section', { class: 'panel' }, h('div', { class: 'panel-head' }, h('h2', { class: 'ui-title3' }, t('chartTitle')), h('p', { class: 'ui-footnote ui-secondary' }, ser.length > 1 ? t('chartSub', { n: ser.length }) : t('chartSubOne'))));
  chartSec.append(widthChart(ser));
  grid.append(chartSec);
  const insp = h('section', { class: 'inspector-col' }, inspectorCard(c, ls, { inCrack: true }));
  grid.append(insp);
  root.append(grid);

  // timeline
  const tl = h('section', { class: 'block' }, h('div', { class: 'ui-list-section' }, sectionHead(t('timeline'), t('timelineAside', { n: shots.length }))));
  const ul = h('ul', { class: 'ui-list timeline' });
  [...c.visits].reverse().forEach((v, vi) => {
    if (!v.shots.length) return;
    ul.append(h('li', { class: 'tl-visit' }, h('div', { class: 'tl-visit__head' }, h('strong', null, t('visitN', { n: c.visits.length - vi })), h('span', null, fmtDate(v.at, { weekday: 'short', day: 'numeric', month: 'long', year: 'numeric' })))));
    [...v.shots].reverse().forEach((sh) => ul.append(h('li', null, shotRow(c, sh))));
  });
  tl.firstChild.append(ul);
  if (c.demo) tl.firstChild.append(h('p', { class: 'ui-list__footer' }, t('demoTimelineFoot')));
  root.append(tl);
  root.append(crackManage(c));
}
function shotRow(c, sh) {
  const cr = sh.cracks && sh.cracks[0];
  const tone = { request_retake: 'warn', request_closer_photo: 'warn', propose_ticket: 'critical', schedule_next_visit: 'ok' }[sh.decision?.name] || 'info';
  const gt = sh.truth;
  return h('div', { class: 'ui-row shot-row' },
    h('span', { class: `shot-ic shot-ic--${tone}` }, icon({ request_retake: 'retry', request_closer_photo: 'zoom', propose_ticket: 'ticket', schedule_next_visit: 'check' }[sh.decision?.name] || 'photo')),
    h('div', { class: 'ui-row__body' },
      h('span', { class: 'ui-row__title' }, decisionTitle(sh)),
      h('span', { class: 'ui-row__subtitle' }, cr ? t('shotMeasured', { max: Wt(cr.width_mm.max), u: Wt(2 * cr.uncertainty_mm), len: L(cr.length_mm) }) : sh.status === 'no_card' ? t('why_card_not_found') : t('shotNoMeasure', { blur: num(sh.quality?.blur_sigma_px, 1) })),
      gt ? h('span', { class: 'ui-row__subtitle truth' }, t('truthShort', { max: Wt(gt.true_width_mm.max), med: Wt(gt.true_width_mm.median) })) : null),
    h('span', { class: 'ui-row__detail' }, new Date(sh.at).toLocaleTimeString(LOCALE(), { hour: '2-digit', minute: '2-digit' })),
    sh.ticket ? h('button', { class: 'ui-button ui-button--sm', type: 'button', onclick: () => openTicket(c.id, sh.id) }, sh.ticket.status === 'pending_human_approval' ? t('review') : t(`tk_${sh.ticket.status}`)) : null);
}
function crackManage(c) {
  const sec = h('section', { class: 'block ui-list-section manage' }, sectionHead(t('manage')));
  const ul = h('ul', { class: 'ui-list' });
  const row = (ic, label, fn, cls = '') => h('li', null, h('button', { class: `ui-row ${cls}`, type: 'button', onclick: fn }, h('span', { class: 'ui-row__icon' }, icon(ic)), h('div', { class: 'ui-row__body' }, h('span', { class: 'ui-row__title' }, label)), icon('chev-r', 'ui-icon ui-row__chevron')));
  ul.append(row('pencil', t('editCrack'), () => openEdit(c)), row('link', t('shareLink'), () => shareLink(c)), row('cal', t('addReminder'), () => downloadIcs(c)),
    row('doc', t('pdfReport'), () => savePdf(c)), row('trash', t('deleteCrack'), () => confirmDelete(c), 'is-destructive'));
  sec.append(ul);
  return sec;
}
function beforeAfter(before, after, l1, l2) {
  const box = h('div', { class: 'ba', style: '--pos: 50%' });
  const i1 = h('img', { src: before, alt: t('beforeAlt', { d: l1 }), class: 'ba__img' });
  const i2 = h('img', { src: after, alt: t('afterAlt', { d: l2 }), class: 'ba__img ba__after' });
  const range = h('input', { type: 'range', min: 0, max: 100, value: 50, class: 'ba__range', 'aria-label': t('baSlider') });
  range.addEventListener('input', () => box.style.setProperty('--pos', `${range.value}%`));
  box.append(i1, i2, h('span', { class: 'ba__line', 'aria-hidden': 'true' }, h('span', { class: 'ba__knob' }, icon('compare'))),
    h('span', { class: 'ba__tag ba__tag--l ui-glass-clear is-dimmed' }, l1), h('span', { class: 'ba__tag ba__tag--r ui-glass-clear is-dimmed' }, l2), range);
  return box;
}

// ------------------------------------------------------------------ inspector decision card (+ trace)
function decisionTitle(sh) {
  if (!sh) return '';
  if (sh.error) return t('dError');
  if (sh.ticket && sh.ticket.status !== 'pending_human_approval') return t(sh.ticket.status === 'approved' ? 'dTicketApproved' : 'dTicketRejected');
  return t({ request_retake: 'dRetake', request_closer_photo: 'dCloser', propose_ticket: 'dTicket', schedule_next_visit: 'dFine', stop: 'dStop', compare_with_previous: 'dCompare' }[sh.decision?.name] || 'dFine');
}
function decisionWhy(sh) {
  const a = sh.decision || {}; const q = sh.quality || {}; const cr = sh.cracks && sh.cracks[0];
  if (a.name === 'request_retake') return t(`why_${a.args?.reason || 'blur'}`, { blur: num(q.blur_sigma_px, 1), sat: num(100 * (q.saturated_frac || 0), 1), tilt: num(q.tilt_deg_est, 0) });
  if (a.name === 'request_closer_photo') return cr ? t('why_closer', { px: num(cr.width_mm.median * cr.native_px_per_mm, 1) }) : t('why_closer_none');
  if (a.name === 'schedule_next_visit') {
    if (!cr) return t('why_fine_none', { days: a.args?.days ?? 90 });
    const low = cr.width_mm.max - 2 * cr.uncertainty_mm;
    if (cr.width_mm.max >= 1.0) return t('why_fine_near', { v: Wt(cr.width_mm.max), low: Wt(low), th: Wt(1.0), days: a.args?.days ?? 30 });
    return t('why_fine', { v: Wt(cr.width_mm.max), th: Wt(1.0), days: a.args?.days ?? 90 });
  }
  if (a.name === 'propose_ticket') {
    const c = sh.comparison; const parts = [];
    if (c && c.status === 'ok') parts.push(t('why_ticket_widen', { d: Wt(c.width_delta_mm.median, { sign: true }), u: Wt(2 * c.delta_uncertainty_mm) }));
    if (cr) parts.push(t('why_ticket_max', { v: Wt(cr.width_mm.max) }));
    if (!sh.ticket || sh.ticket.status === 'pending_human_approval') parts.push(t('why_ticket_human'));
    return parts.join(' ');
  }
  return a.reason || '';
}
function inspectorCard(c, sh, { inCrack = false, onNext } = {}) {
  const card = h('section', { class: 'inspector', 'aria-live': 'polite' });
  if (!sh) return card;
  const name = sh.decision?.name;
  const tone = sh.error ? 'warn' : sh.ticket && sh.ticket.status === 'approved' ? 'ok' : sh.ticket && sh.ticket.status === 'rejected' ? 'info' : { request_retake: 'warn', request_closer_photo: 'warn', propose_ticket: 'critical', schedule_next_visit: 'ok' }[name] || 'info';
  card.dataset.tone = tone;
  card.append(h('div', { class: 'inspector__who' }, h('span', { class: 'inspector__avatar', 'aria-hidden': 'true' }, icon('agent')), h('span', null, t('inspector')),
    h('span', { class: 'inspector__planner' }, sh.error ? '' : decidedBy(sh))));
  card.append(h('h3', { class: 'inspector__title' }, decisionTitle(sh)));
  if (sh.error) { card.append(h('p', { class: 'inspector__why' }, sh.error.message)); return card; }
  card.append(h('p', { class: 'inspector__why' }, decisionWhy(sh)));
  const instr = localInstruction(sh.decision?.args?.instruction);
  if (instr) card.append(h('p', { class: 'inspector__instr' }, icon('info'), h('span', null, `“${instr}”`)));
  const acts = h('div', { class: 'inspector__actions' });
  if (sh.ticket) acts.append(h('button', { class: `ui-button ${sh.ticket.status === 'pending_human_approval' ? 'ui-button--prominent' : 'ui-button--tinted'}`, type: 'button', onclick: () => openTicket(c.id, sh.id) }, icon('ticket'), h('span', null, sh.ticket.status === 'pending_human_approval' ? t('reviewTicket') : t('viewTicket'))));
  if (onNext) onNext(acts, sh);
  else if (inCrack && !c.demo) {
    if (['request_retake', 'request_closer_photo'].includes(name)) acts.append(h('button', { class: 'ui-button ui-button--prominent', type: 'button', onclick: () => openNewPhoto(c.id) }, icon('camera'), h('span', null, t('takePhoto'))));
    if (name === 'schedule_next_visit') acts.append(h('button', { class: 'ui-button ui-button--tinted', type: 'button', onclick: () => downloadIcs(c) }, icon('cal'), h('span', null, t('addReminder'))));
  }
  if (acts.childNodes.length) card.append(acts);
  card.append(traceBlock(sh));
  return card;
}
// the rule policy's instructions are fixed English sentences: show them in the interface language
const RULE_INSTR = { 'Hold still, tap to focus on the crack, use more light.': 'instr_blur', 'Turn off the flash or step sideways to remove the glare.': 'instr_glare',
  'Face the wall more directly.': 'instr_oblique', 'Frame the whole ChArUco card and the crack; avoid reflections on the card.': 'instr_card' };
function localInstruction(s) {
  if (!s) return s;
  if (RULE_INSTR[s]) return t(RULE_INSTR[s]);
  const m = s.match(/^Move about ([\d.]+)x closer to the highlighted part of the crack, card still visible\.$/);
  return m ? t('instr_closer', { z: num(+m[1], 1) }) : s;
}
function decidedBy(sh) {
  const ps = [...new Set((sh.trace || []).map((x) => x.action.planner))];
  const llm = ps.find((p) => p.includes('nova') || p.toLowerCase().includes('claude'));
  return llm ? t('byModel', { m: plannerLabel(llm) }) : t('byRules');
}
function traceBlock(sh) {
  const tr = sh.trace || [];
  const ms = Math.round((sh.timings?.agent_ms ?? tr.reduce((a, x) => a + (x.latency_ms || 0), 0)));
  const cost = sh.llm?.cost_usd || 0;
  const d = h('details', { class: 'trace' }, h('summary', null, h('span', null, t('traceSum', { n: tr.length, ms, cost: `$${num(cost, 4)}` })), icon('chev-d', 'ui-icon trace__chev')));
  const ol = h('ol', { class: 'trace__list' });
  tr.forEach((x, i) => {
    const a = x.action; const m = a.meta || {};
    const bits = [plannerLabel(a.planner)];
    if (m.latency_ms != null) bits.push(`${m.latency_ms} ms`); else if (x.latency_ms != null) bits.push(`${num(x.latency_ms, 1)} ms`);
    if (m.input_tokens != null) bits.push(`${m.input_tokens} + ${m.output_tokens} tokens`, `$${num(m.cost_usd, 4)}`);
    if (m.agrees_with_rules != null) bits.push(m.agrees_with_rules ? t('agrees') : t('differs'));
    ol.append(h('li', null, h('span', { class: 'trace__n' }, String(i + 1)), h('div', null, h('code', { class: 'trace__tool' }, a.name),
      h('p', { class: 'trace__why' }, m.rationale || a.reason || ''), h('p', { class: 'trace__meta' }, bits.join(' · ')))));
  });
  d.append(ol);
  const tm = sh.timings || {};
  d.append(h('p', { class: 'trace__foot' }, t('timings', { m: tm.measure_ms ?? '—', c: tm.compare_ms != null ? ` · ${t('compareMs', { v: tm.compare_ms })}` : '', tot: tm.total_ms ?? '—' })));
  return d;
}

// ------------------------------------------------------------------ INSPECT (live analysis, demo story or own photo)
function nextDemoStep(c) {
  const ids = allShots(c).map((x) => x.source.replace('sample:', ''));
  const i = STEPS.findIndex((st) => !ids.includes(st.id));
  return i < 0 ? null : i;
}
let inflight = false;   // one inspection at a time (double tap, double click)
const isBusy = () => inflight;
async function startDemo(step = 0) {
  if (inflight) return;
  inflight = true;
  if (step == null) step = 0;
  if (step === 0) await resetDemo();
  ensureDemo();
  S.run = { mode: 'demo', crackId: DEMO_ID, step, phase: 'idle' };
  go('inspect');
  inflight = false;
  runStep(step);
}
async function runStep(i) {
  if (inflight) return;
  inflight = true;
  const st = STEPS[i]; const c = ensureDemo();
  S.run = { mode: 'demo', crackId: c.id, step: i, phase: 'measuring', photo: `/samples/${st.id}.jpg`, t0: Date.now() };
  renderInspect();
  visit('sample', { sample: st.id });
  try {
    const d = await api('/api/inspect', { image: { sample: st.id }, previous: st.previous ? { sample: st.previous } : null, retakes: st.retakes });
    warm = true;
    const [d1, d2] = [c.visits[0].at, c.visits[1].at];
    const at = st.visit === 0 ? d1 + (9 * 60 + 40 + 3 * i) * 60000 - (d1 % DAY) + 0 : d2;
    const sh = await recordShot(c, d, { source: `sample:${st.id}`, at, visitIndex: st.visit, truth: truth?.samples?.[st.id] || null });
    S.run = { ...S.run, phase: 'done', result: d, shot: sh };
  } catch (e) {
    S.run = { ...S.run, phase: 'error', error: e };
  }
  inflight = false;
  renderInspect();
}
async function recordShot(c, d, { source, key = null, at = Date.now(), visitIndex = null, truth: gt = null }) {
  const id = uid();
  const imgKey = `ov-${id}`;
  await idb.put(imgKey, `data:image/jpeg;base64,${d.overlay_jpeg_b64}`);
  let baKey = null;
  if (d.before_after) { baKey = `ba-${id}`; await idb.put(baKey, JSON.stringify({ before: `data:image/jpeg;base64,${d.before_after.before_jpeg_b64}`, after: `data:image/jpeg;base64,${d.before_after.after_jpeg_b64}` })); }
  const last = d.trace[d.trace.length - 1].action;
  const sh = { id, at, source, key, status: d.measurement.status, decision: { name: last.name, args: last.args, planner: last.planner, reason: last.reason },
    trace: d.trace, quality: d.measurement.quality, card: d.measurement.card, cracks: d.measurement.cracks, comparison: d.comparison,
    ticket: d.ticket ? { id: d.ticket.id, severity: d.ticket.severity, evidence: d.ticket.evidence, status: 'pending_human_approval' } : null,
    timings: d.timings_ms, llm: d.llm, img: imgKey, ba: baKey, truth: gt, inspectionId: d.inspection_id };
  let v;
  if (visitIndex != null) {
    v = c.visits[visitIndex];
    const same = v.shots.findIndex((x) => x.source === source);   // replaying a demo step replaces it
    if (same >= 0) { const old = v.shots[same]; if (old.img) idb.del(old.img); if (old.ba) idb.del(old.ba); v.shots.splice(same, 1); }
    if (source === 'sample:close') c.visits[1].shots.splice(0).forEach((x) => { idb.del(x.img); if (x.ba) idb.del(x.ba); }); // a new closer photo invalidates visit 2
  } else {
    const lv = c.visits[c.visits.length - 1]; const ls = lv && lv.shots[lv.shots.length - 1];
    const sameVisit = ls && ['request_retake', 'request_closer_photo'].includes(ls.decision?.name) && at - ls.at < 12 * 3600000;
    v = sameVisit ? lv : { id: uid(), at, shots: [] };
    if (!sameVisit) c.visits.push(v);
  }
  v.shots.push(sh);
  v.shots.sort((a, b) => a.at - b.at);
  if (last.name === 'schedule_next_visit') c.nextVisitAt = (visitIndex != null ? c.visits[visitIndex].at : at) + (last.args?.days || 90) * DAY;
  if (last.name === 'propose_ticket') c.nextVisitAt = null;
  save();
  return sh;
}
function analysisSteps(d) {
  const m = d.measurement; const q = m.quality || {}; const cr = (m.cracks || [])[0];
  const blurOk = (q.blur_sigma_px ?? 0) <= 2.2; const satOk = (q.saturated_frac || 0) <= 0.03; const tiltOk = (q.tilt_deg_est ?? 0) <= 55;
  const out = [
    { k: 'card', fn: 'aruco.CharucoDetector', ok: !!m.card, text: m.card ? t('aCard', { n: m.card.corners, rms: num(m.card.reproj_rms_px, 2) }) : t('aNoCard') },
    { k: 'scale', fn: 'findHomography · MAGSAC', ok: !!m.card, skip: !m.card, text: m.card ? t('aScale', { ppm: num(q.card_px_per_mm, 1) }) : t('aSkipped') },
    { k: 'quality', fn: t('aQualityFn'), ok: blurOk && satOk && tiltOk, skip: !m.card, text: m.card ? t('aQuality', { blur: num(q.blur_sigma_px, 1), tilt: num(q.tilt_deg_est, 0), sat: num(100 * (q.saturated_frac || 0), 1) }) : t('aSkipped') },
    { k: 'crack', fn: t('aCrackFn'), ok: !!cr, skip: !m.card || !blurOk, text: cr ? t('aCrack', { len: L(cr.length_mm), n: m.n_cracks }) : (!m.card || !blurOk ? t('aSkipped') : t('aNoCrack')) },
    { k: 'width', fn: t('aWidthFn'), ok: !!cr, skip: !cr, text: cr ? t('aWidth', { max: Wt(cr.width_mm.max), u: Wt(2 * cr.uncertainty_mm), px: num(cr.width_mm.median * cr.native_px_per_mm, 1) }) : t('aSkipped') },
  ];
  if (d.comparison) out.push({ k: 'compare', fn: 'ORB · MAGSAC · ECC', ok: d.comparison.status === 'ok', text: d.comparison.status === 'ok' ? t('aCompare', { d: Wt(d.comparison.width_delta_mm.median, { sign: true }), u: Wt(2 * d.comparison.delta_uncertainty_mm), reg: d.comparison.registration?.mode === 'texture_homography' ? t('regTex') : t('regCard') }) : t('aNoCompare') });
  const last = d.trace[d.trace.length - 1].action;
  out.push({ k: 'agent', fn: d.trace.map((x) => x.action.name).join(' → '), ok: true, agent: true, text: t('aAgent', { by: plannerLabel(last.planner), ms: d.timings_ms?.agent_ms ?? 0 }) });
  return out;
}
const STEP_TITLES = { card: 'aT_card', scale: 'aT_scale', quality: 'aT_quality', crack: 'aT_crack', width: 'aT_width', compare: 'aT_compare', agent: 'aT_agent' };
function renderInspect() {
  const root = $('#view-inspect');
  const R = S.run;
  if (!R) return go('walls');
  const c = crackById(R.crackId);
  root.textContent = '';
  const demo = R.mode === 'demo';
  const st = demo ? STEPS[R.step] : null;
  setTitle(demo ? t('demoTitle') : t('newPhoto'), demo ? t('demoSub', { n: R.step + 1 }) : c ? c.name : '');

  if (demo) {
    const [d1, d2] = [c.visits[0].at, c.visits[1].at];
    const done = new Set(allShots(c).map((x) => x.source.replace('sample:', '')));
    const ol = h('ol', { class: 'story', 'aria-label': t('storyAria') });
    STEPS.forEach((x, i) => {
      const state = i === R.step ? 'current' : done.has(x.id) ? 'done' : 'todo';
      const can = R.phase !== 'measuring' && (done.has(x.id) || i === (nextDemoStep(c) ?? 4) || i === R.step);
      ol.append(h('li', { class: `story__step is-${state}` }, h('button', { type: 'button', disabled: !can, 'aria-current': state === 'current' ? 'step' : null, onclick: () => runStep(i) },
        h('span', { class: 'story__bar', 'aria-hidden': 'true' }), h('span', { class: 'story__when' }, `${t(x.visit ? 'visit2' : 'visit1')} · ${fmtShort(x.visit ? d2 : d1)}`),
        h('span', { class: 'story__title' }, t(x.title)), h('span', { class: 'story__sub' }, t(x.sub)))));
    });
    root.append(ol);
  }

  const grid = h('div', { class: 'inspect-grid' });
  // photo column
  const col1 = h('div', { class: 'inspect-photo' });
  const frame = h('div', { class: `photo-frame ${R.phase === 'measuring' ? 'is-scanning' : ''}` });
  const img = h('img', { class: 'photo', alt: R.phase === 'done' ? t('overlayAlt') : t('photoAlt') });
  if (R.phase === 'done' && R.result) img.src = `data:image/jpeg;base64,${R.result.overlay_jpeg_b64}`; else if (R.photo) img.src = R.photo;
  frame.append(img, h('span', { class: 'scan', 'aria-hidden': 'true' }));
  if (demo) frame.append(h('span', { class: 'photo-chip ui-glass-clear is-dimmed' }, t('syntheticPhoto')));
  if (R.phase === 'measuring') frame.append(h('span', { class: 'busy-pill ui-glass-clear is-dimmed', role: 'status' }, h('span', { class: 'ui-spinner', 'aria-hidden': 'true' }, ...Array.from({ length: 8 }, () => h('i'))), h('span', null, R.uploading ? t('uploading') : warm ? t('busy') : t('busyCold'))));
  col1.append(frame);
  if (R.phase === 'done') col1.append(h('p', { class: 'ui-footnote ui-secondary caption' }, t('caption')));
  if (demo && truth?.samples?.[st.id]) {
    const gt = truth.samples[st.id]; const cr = R.result?.measurement?.cracks?.[0];
    col1.append(h('p', { class: 'truth-line' }, icon('info'), h('span', null, t('truthLine', { max: Wt(gt.true_width_mm.max), med: Wt(gt.true_width_mm.median), len: L(gt.true_length_mm) }),
      cr ? ` ${t('truthMeasured', { max: Wt(cr.width_mm.max), med: Wt(cr.width_mm.median), len: L(cr.length_mm) })}` : '')));
  }
  grid.append(col1);

  // analysis + inspector column
  const col2 = h('div', { class: 'inspect-side' });
  const head = h('div', { class: 'panel-head' }, h('h2', { class: 'ui-title3' }, t('analysis')),
    h('p', { class: 'ui-footnote ui-secondary' }, R.phase === 'done' ? t('analysisDone', { s: num((R.result.timings_ms?.total_ms || 0) / 1000, 1), where: health ? health.runtime : 'AWS Lambda' }) : R.phase === 'measuring' ? t('analysisWait') : ''));
  col2.append(head);
  const list = h('ol', { class: 'analysis' });
  if (R.phase === 'done') {
    analysisSteps(R.result).forEach((x, i) => list.append(h('li', { class: `analysis__step ${x.skip ? 'is-skip' : x.ok ? 'is-ok' : 'is-warn'} ${x.agent ? 'is-agent' : ''}`, style: `--i:${i}` },
      h('span', { class: 'analysis__ic' }, icon(x.skip ? 'chev-r' : x.ok ? 'check' : 'alert')),
      h('div', null, h('span', { class: 'analysis__title' }, t(STEP_TITLES[x.k])), h('code', { class: 'analysis__fn' }, x.fn), h('span', { class: 'analysis__text' }, x.text)))));
  } else if (R.phase === 'measuring') {
    ['card', 'scale', 'quality', 'crack', 'width'].concat(st?.previous ? ['compare'] : [], ['agent']).forEach((k) => list.append(h('li', { class: 'analysis__step is-pending' },
      h('span', { class: 'analysis__ic' }, h('span', { class: 'pending-dot' })), h('div', null, h('span', { class: 'analysis__title' }, t(STEP_TITLES[k])), h('span', { class: 'ui-skeleton sk-line' })))));
  }
  col2.append(list);
  if (R.phase === 'error') {
    const e = R.error;
    const msg = e.code === 'daily_limit' || e.code === 'visitor_limit' ? e.message : e.code === 'image_unavailable' ? t('errExpired') : e.code === 'image_too_small' ? t('errSmall') : e.code === 'not_an_image' ? t('errNotImage') : t('errGeneric');
    col2.append(banner('critical', t('errTitle'), msg, h('button', { class: 'ui-button ui-button--sm', type: 'button', onclick: () => (demo ? runStep(R.step) : R.file ? measureOwn(R.crackId, R.file) : openNewPhoto(R.crackId)) }, icon('retry'), h('span', null, t('tryAgain')))));
    col2.append(h('p', { class: 'ui-footnote ui-secondary err-code' }, e.code || ''));
  }
  if (R.phase === 'done' && R.shot) {
    col2.append(inspectorCard(c, R.shot, { onNext: (acts, sh) => nextActions(acts, sh, R) }));
  }
  grid.append(col2);
  root.append(grid);
  if (R.phase === 'done' && innerWidth < 1000 && !R.revealed) {
    R.revealed = true;
    requestAnimationFrame(() => $('.inspector', root)?.scrollIntoView({ behavior: reduceMotion() ? 'auto' : 'smooth', block: 'start' }));
  }
}
function nextActions(acts, sh, R) {
  const name = sh.decision.name;
  const c = crackById(R.crackId);
  const btn = (label, ic, fn, cls = 'ui-button--prominent') => acts.append(h('button', { class: `ui-button ${cls}`, type: 'button', onclick: fn }, ic ? icon(ic) : null, h('span', null, label)));
  if (R.mode === 'demo') {
    if (name === 'request_retake') btn(t('doFar'), 'retry', () => runStep(1));
    else if (name === 'request_closer_photo') btn(t('doClose'), 'zoom', () => runStep(2));
    else if (name === 'schedule_next_visit' && R.step === 2) btn(t('doVisit2'), 'chev-r', () => runStep(3));
    else if (R.step < 3 && !sh.ticket) btn(t('nextStep'), 'chev-r', () => runStep(R.step + 1), 'ui-button--tinted');
    if (R.step === 3 || sh.ticket) btn(t('openCrack'), null, () => go(`crack/${c.id}`), sh.ticket ? 'ui-button--tinted' : 'ui-button--prominent');
  } else {
    if (['request_retake', 'request_closer_photo'].includes(name)) btn(t('takePhoto'), 'camera', () => pickFile(c.id));
    btn(t('openCrack'), null, () => go(`crack/${c.id}`), ['request_retake', 'request_closer_photo'].includes(name) || sh.ticket ? 'ui-button--tinted' : 'ui-button--prominent');
  }
}

// ------------------------------------------------------------------ own photo
let pendingCrack = null;
function openNewPhoto(crackId = null) {
  const own = data.cracks.filter((c) => !c.demo);
  const body = $('#photoBody');
  body.textContent = '';
  let target = crackId && crackById(crackId) && !crackById(crackId).demo ? crackId : own[0]?.id || 'new';
  body.append(h('p', { class: 'sheet-lede' }, rich(t('photoLede'))));
  const how = h('ol', { class: 'howto' },
    h('li', null, h('span', { class: 'how-n' }, '1'), h('div', null, h('strong', null, t('ob1t')), h('p', null, t('ob1d')), h('a', { href: '/card.pdf', target: '_blank', rel: 'noopener', 'data-visit': 'card', class: 'ui-button ui-button--sm ui-button--tinted' }, icon('card'), h('span', null, t('printCard'))))),
    h('li', null, h('span', { class: 'how-n' }, '2'), h('div', null, h('strong', null, t('ob2t')), h('p', null, t('ob2d')))),
    h('li', null, h('span', { class: 'how-n' }, '3'), h('div', null, h('strong', null, t('ob3t')), h('p', null, t('ob3d')))));
  body.append(how);
  const field = h('div', { class: 'ui-field' }, h('label', { class: 'ui-field__label', for: 'fCrack' }, t('whichCrack')));
  const sel = h('select', { class: 'ui-select', id: 'fCrack' });
  own.forEach((c) => sel.append(h('option', { value: c.id, selected: c.id === target }, `${c.name}${c.place ? ` · ${c.place}` : ''}`)));
  sel.append(h('option', { value: 'new', selected: target === 'new' }, t('newCrack')));
  field.append(sel);
  body.append(field);
  body.append(h('div', { class: 'sheet-actions' },
    h('button', { class: 'ui-button ui-button--prominent ui-button--lg', type: 'button', onclick: () => { closeSheet('sheet-photo'); pickFile(sel.value); } }, icon('camera'), h('span', null, t('chooseOrTake'))),
    h('button', { class: 'ui-button ui-button--lg', type: 'button', onclick: () => { closeSheet('sheet-photo'); startDemo(); } }, t('orDemo'))));
  body.append(h('p', { class: 'ui-footnote ui-secondary' }, t('privacy')));
  openSheet('sheet-photo');
}
function pickFile(crackId) { pendingCrack = crackId; const f = $('#fileInput'); f.value = ''; f.click(); }
function newOwnCrack() {
  const n = data.cracks.filter((c) => !c.demo).length + 1;
  const c = { id: uid(), demo: false, name: t('crackN', { n }), place: '', createdAt: Date.now(), nextVisitAt: null, visits: [] };
  data.cracks.push(c); save();
  return c;
}
async function measureOwn(crackId, file) {
  if (inflight) return;
  if (file.size > 15 * 1024 * 1024) { toast({ title: t('tooBig'), tone: 'critical' }); return; }
  inflight = true;
  const c = crackId && crackId !== 'new' ? crackById(crackId) : newOwnCrack();
  const photo = URL.createObjectURL(file);
  S.run = { mode: 'own', crackId: c.id, phase: 'measuring', uploading: true, photo, file };
  go('inspect');
  renderInspect();
  try {
    const up = await api('/api/upload-url', {});
    const form = new FormData();
    Object.entries(up.fields).forEach(([k, v]) => form.append(k, v));
    form.append('file', file);
    const r = await fetch(up.url, { method: 'POST', body: form });
    if (!r.ok) throw Object.assign(new Error('upload_failed'), { code: 'upload_failed' });
    visit('upload');
    S.run.uploading = false; renderInspect();
    // the server only keeps photos 24 h: compare on the server with the last measured photo if it is still there
    const lv = c.visits[c.visits.length - 1]; const ls = lastShot(c);
    const sameVisit = !!(ls && ['request_retake', 'request_closer_photo'].includes(ls.decision?.name) && Date.now() - ls.at < 12 * 3600000);
    const prevShot = [...allShots(c)].reverse().find((x) => isMeasured(x) && x.key && Date.now() - x.at < 23 * 3600000 && !(sameVisit && x.visitId === lv.id));
    const retakes = sameVisit ? lv.shots.filter((x) => ['request_retake', 'request_closer_photo'].includes(x.decision?.name)).length : 0;
    const d = await api('/api/inspect', { image: { key: up.key }, previous: prevShot ? { key: prevShot.key } : null, retakes });
    warm = true;
    const sh = await recordShot(c, d, { source: 'upload', key: up.key });
    S.run = { ...S.run, phase: 'done', result: d, shot: sh };
  } catch (e) {
    S.run = { ...S.run, phase: 'error', error: e, uploading: false };
  }
  inflight = false;
  if (S.view === 'inspect') renderInspect();
}

// ------------------------------------------------------------------ ticket (human decision)
function openTicket(crackId, shotId) {
  const c = crackById(crackId); const sh = c && findShot(c, shotId);
  if (!sh || !sh.ticket) return;
  const body = $('#ticketBody');
  body.textContent = '';
  const tk = sh.ticket; const ev = tk.evidence || {}; const cmp = sh.comparison;
  const sev = tk.severity || 'medium';
  body.append(h('div', { class: 'tk-head' }, h('span', { class: `tk-sev tk-sev--${sev}` }, t(`sev_${sev}`)),
    h('div', null, h('h3', { class: 'ui-title2' }, c.name), h('p', { class: 'ui-subhead ui-secondary' }, [c.place, fmtDate(sh.at)].filter(Boolean).join(' · ')))));
  body.append(h('p', { class: 'tk-why' }, decisionWhy(sh)));
  const facts = h('dl', { class: 'facts' });
  const fact = (k, v) => facts.append(h('div', null, h('dt', null, k), h('dd', null, v)));
  if (ev.max_width_mm != null) fact(t('sMax'), `${Wt(ev.max_width_mm)} ± ${Wt(2 * (ev.uncertainty_mm || 0))}`);
  if (ev.width_delta_median_mm != null) fact(t('sChange'), `${Wt(ev.width_delta_median_mm, { sign: true })}${cmp?.delta_uncertainty_mm ? ` ± ${Wt(2 * cmp.delta_uncertainty_mm)}` : ''}`);
  if (ev.new_length_mm != null) fact(t('newLength'), L(ev.new_length_mm));
  if (ev.location_board_mm) fact(t('where'), t('whereCard', { x: num(ev.location_board_mm[0], 0), y: num(ev.location_board_mm[1], 0) }));
  if (cmp?.registration) fact(t('registration'), cmp.registration.mode === 'texture_homography' ? t('regTex') : t('regCard'));
  fact(t('proposedBy'), decidedBy(sh));
  body.append(facts);
  if (tk.status !== 'pending_human_approval') {
    body.append(banner(tk.status === 'approved' ? 'info' : 'warn', t(`tk_${tk.status}`), t(tk.status === 'approved' ? 'approvedText' : 'rejectedText', { d: tk.decidedAt ? fmtDate(tk.decidedAt) : '' }) + (tk.localOnly ? ` ${t('localOnly')}` : '')));
    if (tk.note) body.append(h('p', { class: 'ui-footnote ui-secondary' }, `${t('note')}: ${tk.note}`));
  } else {
    const note = h('textarea', { class: 'ui-textarea', id: 'tkNote', maxlength: 200, rows: 2, placeholder: t('notePh') });
    body.append(h('div', { class: 'ui-field' }, h('label', { class: 'ui-field__label', for: 'tkNote' }, t('noteLabel')), note));
    const ok = h('button', { class: 'ui-button ui-button--prominent ui-button--lg', type: 'button' }, icon('check'), h('span', null, t('approve')));
    const no = h('button', { class: 'ui-button ui-button--lg', type: 'button' }, t('reject'));
    const decide = async (decision) => {
      ok.disabled = no.disabled = true;
      let localOnly = false;
      try { await api(`/api/tickets/${tk.id}/decision`, { decision, note: note.value.slice(0, 200) }); }
      catch (e) { if (e.status === 404) localOnly = true; else { ok.disabled = no.disabled = false; toast({ title: t('errTitle'), detail: t('errGeneric'), tone: 'critical' }); return; } }
      Object.assign(tk, { status: decision === 'approve' ? 'approved' : 'rejected', decidedAt: Date.now(), note: note.value.slice(0, 200), localOnly });
      if (decision === 'reject' && !c.nextVisitAt) c.nextVisitAt = Date.now() + 30 * DAY;
      save();
      closeSheet('sheet-ticket');
      toast({ title: t(decision === 'approve' ? 'toastApproved' : 'toastRejected'), detail: t('toastLogged'), tone: decision === 'approve' ? 'ok' : 'info' });
      render();
    };
    ok.addEventListener('click', () => decide('approve'));
    no.addEventListener('click', () => decide('reject'));
    body.append(h('div', { class: 'tk-actions' }, no, ok));
    body.append(h('p', { class: 'ui-footnote ui-secondary' }, t('tkFoot')));
  }
  if (sh.ba) { const box = h('div', { class: 'tk-ba' }, h('h4', { class: 'ui-headline' }, t('evidencePhotos'))); body.append(box); idb.get(sh.ba).then((v) => { if (v) { const p = JSON.parse(v); box.append(beforeAfter(p.before, p.after, fmtShort(c.visits[0].at), fmtShort(sh.at))); } }); }
  openSheet('sheet-ticket');
}

// ------------------------------------------------------------------ TICKETS view
function renderTickets() {
  const root = $('#view-tickets');
  root.textContent = '';
  const all = allTickets(); const pend = all.filter((x) => x.shot.ticket.status === 'pending_human_approval');
  setTitle(t('navTickets'), pend.length ? t('ticketsSub', { n: pend.length }) : t('ticketsSubNone'));
  root.append(h('div', { class: 'lead' }, h('p', { class: 'summary' }, rich(pend.length ? t('ticketsLead', { n: pend.length }) : all.length ? t('ticketsLeadDone') : t('ticketsLeadEmpty')))));
  if (!all.length) {
    root.append(h('div', { class: 'ui-surface empty-card' }, h('div', { class: 'ui-empty' }, h('span', { class: 'ui-empty__icon' }, icon('ticket')), h('h3', null, t('noTickets')), h('p', null, t('noTicketsBody')),
      h('button', { class: 'ui-button ui-button--prominent', type: 'button', onclick: () => startDemo() }, t('runDemo')))));
    return;
  }
  const sec = h('div', { class: 'ui-list-section' }, sectionHead(t('allTickets'), t('tapToReview')));
  const ul = h('ul', { class: 'ui-list' });
  all.forEach(({ crack: c, shot: sh }) => {
    const tk = sh.ticket; const ev = tk.evidence || {};
    const tone = tk.status === 'pending_human_approval' ? 'critical' : tk.status === 'approved' ? 'ok' : 'info';
    ul.append(h('li', null, h('button', { class: 'ui-row', type: 'button', onclick: () => openTicket(c.id, sh.id) },
      h('span', { class: 'ui-row__icon' }, icon('ticket')),
      h('div', { class: 'ui-row__body' }, h('span', { class: 'ui-row__title' }, c.name), h('span', { class: 'ui-row__subtitle' }, `${t(`sev_${tk.severity || 'medium'}`)} · ${ev.max_width_mm != null ? Wt(ev.max_width_mm) : ''}${ev.width_delta_median_mm != null ? ` · ${Wt(ev.width_delta_median_mm, { sign: true })}` : ''} · ${fmtDate(sh.at)}`)),
      h('span', { class: `ui-status ui-status--${tone}` }, tk.status === 'pending_human_approval' ? t('tk_pending') : t(`tk_${tk.status}`)), icon('chev-r', 'ui-icon ui-row__chevron'))));
  });
  sec.append(ul, h('p', { class: 'ui-list__footer' }, t('tkFoot')));
  root.append(sec);
}

// ------------------------------------------------------------------ SETTINGS
function seg(name, options, value, onChange, aria) {
  const f = h('fieldset', { class: 'ui-segmented', 'aria-label': aria });
  options.forEach(([v, label]) => f.append(h('label', null, h('input', { type: 'radio', name, value: v, checked: String(v) === String(value) }), label)));
  f.addEventListener('change', (e) => onChange(e.target.value));
  UI.enhanceSegmented?.(f);
  return f;
}
function renderSettings() {
  const root = $('#view-settings');
  root.textContent = '';
  setTitle(t('navSettings'), t('settingsSub'));
  const grid = h('div', { class: 'grid-2 settings' });
  const row = (title, sub, ctrl) => h('li', null, h('div', { class: 'ui-row set-row' }, h('div', { class: 'ui-row__body' }, h('span', { class: 'ui-row__title' }, title), sub ? h('span', { class: 'ui-row__subtitle' }, sub) : null), ctrl));
  const col1 = h('div');
  col1.append(h('div', { class: 'ui-list-section' }, sectionHead(t('setDisplay')), h('ul', { class: 'ui-list' },
    row(t('setUnits'), t('setUnitsSub'), seg('units', [['mm', 'mm'], ['in', 'in']], settings.units, (v) => { settings.units = v; saveSettings(); refreshChrome(); }, t('setUnits'))),
    row(t('setLang'), null, seg('lang', [['en', 'English'], ['fr', 'Français']], lang, (v) => setLang(v), t('setLang'))),
    row(t('setTheme'), null, seg('theme', [['system', t('themeSystem')], ['light', t('themeLight')], ['dark', t('themeDark')]], settings.theme, (v) => { settings.theme = v; saveSettings(); setTheme(v); }, t('setTheme'))))));
  col1.append(h('div', { class: 'ui-list-section' }, sectionHead(t('setAlerts')), h('ul', { class: 'ui-list' },
    row(t('setWidth'), t('setWidthSub'), seg('wa', [['0.5', '0.5'], ['1', '1.0'], ['2', '2.0']], String(settings.widthAlert), (v) => { settings.widthAlert = +v; saveSettings(); refreshChrome(); }, t('setWidth'))),
    row(t('setWiden'), t('setWidenSub'), seg('wd', [['0.1', '0.1'], ['0.2', '0.2'], ['0.3', '0.3']], String(settings.wideningAlert), (v) => { settings.wideningAlert = +v; saveSettings(); refreshChrome(); }, t('setWiden')))),
    h('p', { class: 'ui-list__footer' }, t('setAlertsFoot'))));
  const col2 = h('div');
  const act = (ic, label, fn, cls = '') => h('li', null, h('button', { class: `ui-row ${cls}`, type: 'button', onclick: fn }, h('span', { class: 'ui-row__icon' }, icon(ic)), h('div', { class: 'ui-row__body' }, h('span', { class: 'ui-row__title' }, label)), icon('chev-r', 'ui-icon ui-row__chevron')));
  col2.append(h('div', { class: 'ui-list-section' }, sectionHead(t('setData')), h('ul', { class: 'ui-list' },
    act('card', t('printCard'), () => { visit('card'); window.open('/card.pdf', '_blank', 'noopener'); }),
    act('help', t('navHelp'), () => openHelp()),
    act('retry', t('resetDemo'), async () => { await resetDemo(); toast({ title: t('demoReset'), tone: 'ok' }); render(); }),
    act('trash', t('eraseAll'), () => confirmErase(), 'is-destructive')),
  h('p', { class: 'ui-list__footer' }, t('privacy'))));
  const about = h('div', { class: 'ui-list-section' }, sectionHead(t('setAbout')));
  const ul = h('ul', { class: 'ui-list' });
  const info = (k, v) => ul.append(h('li', null, h('div', { class: 'ui-row' }, h('div', { class: 'ui-row__body' }, h('span', { class: 'ui-row__title' }, k)), h('span', { class: 'ui-row__detail' }, v))));
  info(t('aboutService'), health ? `OpenCV ${health.opencv} · ${health.runtime}` : t('svcUnknown'));
  info(t('aboutAgent'), t('aboutAgentVal'));
  info(t('aboutLimits'), health ? t('limitsVal', { n: health.limits.inspections_per_visitor_day }) : '—');
  about.append(ul, h('p', { class: 'ui-list__footer' }, t('credits')));
  col2.append(about);
  grid.append(col1, col2);
  root.append(grid);
  root.append(h('p', { class: 'fine' }, t('disclaimer')));
}
function setLang(v) {
  lang = T[v] ? v : 'en'; store.set('cw-lang', lang);
  const demo = crackById(DEMO_ID); if (demo) { demo.name = t('demoName'); demo.place = t('demoPlace'); }
  applyLang(); visit('lang');
}
function applyLang() {
  document.documentElement.lang = lang;
  $$('[data-i18n]').forEach((n) => { n.textContent = t(n.dataset.i18n); });
  $$('[data-i18n-aria]').forEach((n) => { n.setAttribute('aria-label', t(n.dataset.i18nAria)); n.title = t(n.dataset.i18nAria); });
  $$('.lang-switch [data-lang]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.lang === lang)));
  refreshChrome(); svc(); render();
}

// ------------------------------------------------------------------ help sheet ("How it works" lives here)
function openHelp() {
  const b = $('#helpBody');
  b.textContent = '';
  const sec = (title, ...kids) => h('section', { class: 'help-sec' }, h('h3', { class: 'ui-headline' }, title), ...kids);
  b.append(sec(t('hStart'), h('ol', { class: 'help-ol' }, h('li', null, rich(t('hStart1'))), h('li', null, rich(t('hStart2'))), h('li', null, rich(t('hStart3'))))));
  b.append(sec(t('hStatus'), h('ul', { class: 'help-ul' }, ...['stable', 'widening', 'above', 'needs_photo'].map((k) => h('li', null, statusEl(k), h('span', { class: 'ui-secondary' }, ` — ${t(`hSt_${k}`)}`))))));
  b.append(sec(t('hAgent'), h('p', null, t('hAgentP')), h('ul', { class: 'help-ul mono-list' }, ...['request_retake', 'request_closer_photo', 'compare_with_previous', 'propose_ticket', 'schedule_next_visit'].map((k) => h('li', null, h('code', null, k), ' ', t(`hTool_${k}`))))));
  b.append(sec(t('howTitle'), h('ol', { class: 'help-ol' }, ...['how1', 'how2', 'how3', 'how4', 'how5'].map((k) => h('li', null, rich(t(k)))))));
  b.append(sec(t('hAcc'), h('p', null, t('proof')), h('p', null, t('hAccDemo'))));
  b.append(sec(t('hPrivacy'), h('p', null, t('privacy'))));
  b.append(h('p', { class: 'fine' }, t('disclaimer')));
  openSheet('sheet-help');
}

// ------------------------------------------------------------------ edit / delete / erase
function openEdit(c) {
  $('#fName').value = c.name; $('#fPlace').value = c.place || '';
  $('#editForm').onsubmit = (e) => {
    e.preventDefault();
    const n = $('#fName').value.trim();
    if (!n) { $('#fName').setAttribute('aria-invalid', 'true'); $('#fName').focus(); return; }
    $('#fName').removeAttribute('aria-invalid');
    c.name = n.slice(0, 60); c.place = $('#fPlace').value.trim().slice(0, 80); save();
    closeSheet('sheet-edit'); render();
  };
  openSheet('sheet-edit');
}
function ask(title, text, okLabel, fn) {
  $('#alertTitle').textContent = title; $('#alertText').textContent = text; $('#alertOk').textContent = okLabel;
  $('#alertOk').onclick = () => { closeSheet('alert'); fn(); };
  $('#alertCancel').onclick = () => closeSheet('alert');
  openSheet('alert');
}
function confirmDelete(c) {
  ask(t('delTitle', { name: c.name }), t('delText'), t('delete'), async () => {
    for (const sh of allShots(c)) { if (sh.img) await idb.del(sh.img); if (sh.ba) await idb.del(sh.ba); }
    data.cracks = data.cracks.filter((x) => x.id !== c.id); save(); go('walls');
  });
}
function confirmErase() {
  ask(t('eraseTitle'), t('eraseText'), t('erase'), async () => { data.cracks = []; await idb.clear(); save(); toast({ title: t('erased'), tone: 'ok' }); render(); });
}

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
function renderShared() {
  const root = $('#view-shared');
  root.textContent = '';
  const p = S.shared;
  if (!p) { setTitle(t('sharedTitle')); root.append(banner('warn', t('sharedBad'), t('sharedBadText'))); return; }
  setTitle(p.name, [p.place, p.demo ? t('demoTag') : null].filter(Boolean).join(' · '));
  const last = p.ser[p.ser.length - 1]; const first = p.ser[0];
  root.append(h('div', { class: 'lead' }, banner('info', t('sharedBanner'), t('sharedBannerText')),
    h('p', { class: 'summary' }, statusEl(p.status), ' ', last ? rich(t('sharedSentence', { v: Wt(last.max), u: Wt(2 * last.unc), d: fmtDate(last.at), n: p.ser.length })) : ''),
    last ? h('div', { class: 'ui-stats crack-stats', role: 'list' }, stat(t('sMax'), W(last.max)[0], W(last.max)[1], `± ${Wt(2 * last.unc)} (2σ)`, 'is-width'),
      stat(t('sChange'), p.ser.length > 1 ? W(last.max - first.max, { sign: true })[0] : '—', p.ser.length > 1 ? W(1)[1] : null, p.ser.length > 1 ? t('sChangeDays', { days: Math.round((last.at - first.at) / DAY) }) : t('sChangeFirst')),
      stat(t('sLen'), num(last.len, 0), 'mm'), stat(t('sNext'), p.next ? fmtShort(p.next) : '—')) : null));
  root.append(h('section', { class: 'panel block' }, h('div', { class: 'panel-head' }, h('h2', { class: 'ui-title3' }, t('chartTitle'))), widthChart(p.ser)));
  root.append(h('div', { class: 'lead-actions block' }, h('button', { class: 'ui-button ui-button--prominent', type: 'button', onclick: () => { history.replaceState(null, '', '/'); go('walls'); } }, t('openApp'))));
}

// ------------------------------------------------------------------ PDF report (jsPDF served locally, loaded on demand)
function loadScript(src) { return new Promise((ok, ko) => { const x = document.createElement('script'); x.src = src; x.onload = ok; x.onerror = () => ko(new Error('script')); document.head.append(x); }); }
async function savePdf(c) {
  const btn = $('#pdfBtn'); btn.setAttribute('aria-busy', 'true');
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

// ------------------------------------------------------------------ service status (sidebar footer)
function svc() {
  const lab = $('#svcLabel'); const det = $('#svcDetail');
  if (health === null) { lab.className = 'ui-status ui-status--info ui-subhead'; lab.textContent = t('svcChecking'); det.textContent = ''; return; }
  if (health === false) { lab.className = 'ui-status ui-status--warn ui-subhead'; lab.textContent = t('svcDown'); det.textContent = t('svcDownText'); return; }
  lab.className = 'ui-status ui-status--ok ui-subhead'; lab.textContent = t('svcOk');
  det.textContent = `OpenCV ${health.opencv} · ${health.runtime}`;
}

// ------------------------------------------------------------------ wiring
function wire() {
  addEventListener('hashchange', route);
  $('#backBtn').addEventListener('click', () => { if (S.view === 'crack' || S.view === 'shared') go('walls'); else if (S.view === 'inspect' && S.run?.crackId && crackById(S.run.crackId)?.visits.some((v) => v.shots.length)) go(`crack/${S.run.crackId}`); else go('walls'); });
  document.addEventListener('click', (e) => {
    const np = e.target.closest('[data-new-photo]'); if (np) { const id = S.view === 'crack' ? S.crackId : null; return openNewPhoto(id && !crackById(id)?.demo ? id : null); }
    if (e.target.closest('[data-help]')) return openHelp();
    const v = e.target.closest('[data-visit]'); if (v) visit(v.dataset.visit);
    if (e.target.closest('[data-sidebar-toggle]')) {
      const app = $('#app');
      if (innerWidth >= 1000) app.classList.toggle('is-sidebar-collapsed');
      else { app.classList.toggle('is-sidebar-open'); $('.sidebar-scrim').hidden = !app.classList.contains('is-sidebar-open'); }
    }
    if (e.target.closest('[data-sidebar-close]')) closeSidebar();
  });
  $$('.lang-switch [data-lang]').forEach((b) => b.addEventListener('click', () => setLang(b.dataset.lang)));
  $('#shareBtn').addEventListener('click', () => { const c = crackById(S.crackId); if (c) shareLink(c); });
  $('#icsBtn').addEventListener('click', () => { const c = crackById(S.crackId); if (c) downloadIcs(c); });
  $('#pdfBtn').addEventListener('click', () => { const c = crackById(S.crackId); if (c) savePdf(c); });
  $('#fileInput').addEventListener('change', (e) => { const f = e.target.files && e.target.files[0]; if (f) measureOwn(pendingCrack, f); });
  // iOS: no long-press callout on app chrome, no pinch zoom
  document.addEventListener('gesturestart', (e) => e.preventDefault());
  matchMedia('(prefers-color-scheme: dark)').addEventListener?.('change', () => { if (S.view === 'crack') renderCrack(); });
}

function boot() {
  if (settings.theme !== 'system') setTheme(settings.theme);
  wire();
  applyLang();   // renders the current route too
  route();
  fetch('/samples/samples.json').then((r) => r.json()).then((j) => { truth = j; if (S.view === 'inspect') renderInspect(); }).catch(() => {});
  fetch('/api/health').then((r) => (r.ok ? r.json() : false)).then((j) => { health = j; svc(); if (S.view === 'settings') renderSettings(); }).catch(() => { health = false; svc(); });
  let ref = '';
  try { const hn = document.referrer ? new URL(document.referrer).hostname.replace(/^www\./, '') : ''; ref = hn && hn !== location.hostname ? hn : ''; } catch { /* ignore */ }
  visit('view', { ref, utm: new URLSearchParams(location.search).get('utm_source') || '' });
}
boot();

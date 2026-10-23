/* ==========================================================================
   Design system — motion.js  (module ES, vanilla, sans dépendance, sans réseau)

   HTML    : <script type="module" src="/design-system/motion.js"></script>
             → s'initialise seul (désactiver : <html data-ui-auto="off">).
   Next.js : import { init } from "@/design-system/motion.js";
             useEffect(() => init(), []);   // côté client uniquement
   Global  : window.UI (mêmes fonctions).

   Modèle de ressort Apple (WWDC23 « Animate with springs ») :
     duration = rythme perçu, bounce ∈ [0, 1)  →  ζ = 1 − bounce, ω₀ = 2π / duration
   ========================================================================== */

const hasDOM = typeof window !== "undefined" && typeof document !== "undefined";
const done = new WeakSet();

/* ---------- Préférences ---------------------------------------------- */
export const prefersReducedMotion = () =>
  hasDOM && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const supportsLinear = hasDOM && window.CSS && CSS.supports("animation-timing-function", "linear(0, 1)");

/* ---------- Ressorts : courbe analytique ----------------------------- */
function springValue(t, duration, bounce, v0 = 0) {
  // Position normalisée de 0 → 1 ; v0 = vitesse initiale (unités / s, normalisée)
  const w = (2 * Math.PI) / duration;
  const z = Math.min(Math.max(1 - bounce, 0.0001), 1);
  if (z >= 0.9999) {
    // critique : x(t) = 1 − (1 + (w − v0) t) e^(−wt)
    return 1 - (1 + (w - v0) * t) * Math.exp(-w * t);
  }
  const wd = w * Math.sqrt(1 - z * z);
  const A = 1, B = (z * w * A - v0) / wd;
  return 1 - Math.exp(-z * w * t) * (A * Math.cos(wd * t) + B * Math.sin(wd * t));
}

function settleTime(duration, bounce, v0 = 0, eps = 0.001) {
  let last = 0;
  for (let t = 0; t < duration * 6; t += 0.004) {
    if (Math.abs(1 - springValue(t, duration, bounce, v0)) > eps) last = t;
  }
  return Math.max(last, 0.08);
}

function simplify(points, eps) {
  if (points.length < 3) return points;
  const a = points[0], b = points[points.length - 1];
  let idx = 0, max = 0;
  for (let i = 1; i < points.length - 1; i++) {
    const y = a[1] + ((b[1] - a[1]) * (points[i][0] - a[0])) / (b[0] - a[0]);
    const d = Math.abs(points[i][1] - y);
    if (d > max) { max = d; idx = i; }
  }
  if (max <= eps) return [a, b];
  return simplify(points.slice(0, idx + 1), eps).slice(0, -1).concat(simplify(points.slice(idx), eps));
}

const cache = new Map();
/** Renvoie { easing: "linear(...)", duration: ms } pour un ressort Apple. */
export function springEasing(duration = 0.5, bounce = 0, velocity = 0) {
  const key = `${duration}|${bounce}|${velocity.toFixed(2)}`;
  if (cache.has(key)) return cache.get(key);
  const T = settleTime(duration, bounce, velocity);
  const N = 240, pts = [];
  for (let i = 0; i <= N; i++) pts.push([i / N, i === N ? 1 : springValue((T * i) / N, duration, bounce, velocity)]);
  const s = simplify(pts, 0.002);
  const easing = supportsLinear
    ? `linear(${s.map(([x, y], i) => (i === 0 ? "0" : i === s.length - 1 ? "1" : `${+y.toFixed(4)} ${+(x * 100).toFixed(2)}%`)).join(", ")})`
    : bounce > 0.1 ? "cubic-bezier(0.34, 1.4, 0.64, 1)" : "cubic-bezier(0.22, 1, 0.36, 1)";
  const out = { easing, duration: Math.round(T * 1000) };
  cache.set(key, out);
  return out;
}

/** Échantillonne la courbe (pour tracer / documenter). Renvoie [[t (s), x], …]. */
export function springCurve(duration = 0.5, bounce = 0, samples = 120) {
  const T = settleTime(duration, bounce);
  return Array.from({ length: samples + 1 }, (_, i) => [(T * i) / samples, springValue((T * i) / samples, duration, bounce)]);
}

/** Presets alignés sur SwiftUI (.smooth / .snappy / .bouncy, durée 0,5 s par défaut). */
export const springs = {
  smooth: { duration: 0.5, bounce: 0 },
  snappy: { duration: 0.4, bounce: 0.15 },
  bouncy: { duration: 0.5, bounce: 0.3 },
  quick: { duration: 0.25, bounce: 0 },
};

/** Anime avec WAAPI + ressort. Respecte « Réduire les animations » (fondu court). */
export function spring(el, keyframes, opts = {}) {
  if (!el || !el.animate) return null;
  const p = typeof opts === "string" ? springs[opts] : { ...springs.smooth, ...(springs[opts.preset] || {}), ...opts };
  if (prefersReducedMotion()) {
    const last = Array.isArray(keyframes) ? keyframes[keyframes.length - 1] : keyframes;
    return el.animate(last.opacity !== undefined ? [{ opacity: 0 }, last] : [last, last], { duration: 120, fill: opts.fill || "both", easing: "ease-out" });
  }
  const { easing, duration } = springEasing(p.duration, p.bounce, p.velocity || 0);
  return el.animate(keyframes, { duration, easing, fill: opts.fill || "both", delay: opts.delay || 0, composite: opts.composite });
}

/* ---------- Ressort physique interruptible (gestes) ------------------ */
/** Anime une valeur numérique avec conservation de la vitesse (glisser-relâcher). */
export function springValueTo({ from, to, velocity = 0, duration = 0.5, bounce = 0, onUpdate, onDone }) {
  const k = Math.pow((2 * Math.PI) / duration, 2);
  const c = (4 * Math.PI * (1 - bounce)) / duration;
  let x = from, v = velocity, last = performance.now(), raf = 0, stopped = false;
  if (prefersReducedMotion()) { onUpdate?.(to); onDone?.(); return { stop() {} }; }
  const step = (now) => {
    if (stopped) return;
    let dt = Math.min((now - last) / 1000, 1 / 30); last = now;
    const sub = 4; dt /= sub;
    for (let i = 0; i < sub; i++) { const a = -k * (x - to) - c * v; v += a * dt; x += v * dt; }
    onUpdate?.(x);
    if (Math.abs(x - to) < 0.05 && Math.abs(v) < 0.5) { onUpdate?.(to); onDone?.(); return; }
    raf = requestAnimationFrame(step);
  };
  raf = requestAnimationFrame(step);
  return { stop() { stopped = true; cancelAnimationFrame(raf); }, get value() { return x; }, get velocity() { return v; } };
}

/* ---------- Indicateur glissant (segmenté, onglets) ------------------ */
function moveIndicator(indicator, target, container, animate = true) {
  if (!indicator || !target) return;
  const c = container.getBoundingClientRect(), r = target.getBoundingClientRect();
  const x = r.left - c.left, w = r.width;
  const prev = indicator._pos;
  indicator.style.width = `${w}px`;
  indicator.style.transform = `translateX(${x}px)`;
  indicator._pos = { x, w };
  if (animate && prev && (prev.x !== x || prev.w !== w)) {
    // L'indicateur « s'étire » comme une goutte puis se pose (Liquid Glass)
    spring(indicator, [
      { transform: `translateX(${prev.x}px) scaleX(1)`, width: `${prev.w}px` },
      { transform: `translateX(${x}px) scaleX(1)`, width: `${w}px` },
    ], { preset: "snappy", fill: "none" });
    indicator.animate([{ scale: "1 1" }, { scale: "1.06 0.92" }, { scale: "1 1" }],
      { duration: prefersReducedMotion() ? 1 : 320, easing: "ease-out" });
  }
}

export function enhanceSegmented(root) {
  if (done.has(root)) return; done.add(root);
  root.classList.add("is-enhanced");
  let ind = root.querySelector(".ui-segmented__indicator");
  if (!ind) { ind = document.createElement("span"); ind.className = "ui-segmented__indicator"; ind.setAttribute("aria-hidden", "true"); root.prepend(ind); }
  const current = () => root.querySelector("input:checked")?.closest("label");
  const sync = (anim) => moveIndicator(ind, current(), root, anim);
  root.addEventListener("change", () => sync(true));
  new ResizeObserver(() => sync(false)).observe(root);
  sync(false);
}

export function enhanceTabbar(root) {
  if (done.has(root)) return; done.add(root);
  const tabs = root.querySelector(".ui-tabbar__tabs") || root;
  let ind = tabs.querySelector(".ui-tabbar__indicator");
  if (!ind) { ind = document.createElement("span"); ind.className = "ui-tabbar__indicator"; tabs.prepend(ind); }
  const sync = (anim) => moveIndicator(ind, tabs.querySelector('[aria-current="page"]'), tabs, anim);
  const select = (item, bounce) => {
    if (!item || item.getAttribute("aria-current") === "page") return;
    tabs.querySelectorAll(".ui-tabbar__item").forEach((t) => t.removeAttribute("aria-current"));
    item.setAttribute("aria-current", "page"); sync(true);
    if (bounce) spring(item.querySelector("svg"), [{ transform: "scale(0.82)" }, { transform: "scale(1)" }], { preset: "bouncy", fill: "none" });
  };
  tabs.addEventListener("click", (e) => select(e.target.closest(".ui-tabbar__item"), true));
  // Sélection programmatique (ex. suivi du défilement) : root.dispatchEvent(new CustomEvent("ui:select", { detail: index | element }))
  root.addEventListener("ui:select", (e) => {
    const items = [...tabs.querySelectorAll(".ui-tabbar__item")];
    select(typeof e.detail === "number" ? items[e.detail] : e.detail, false);
  });
  new ResizeObserver(() => sync(false)).observe(tabs);
  sync(false);
  // Minimisation au défilement vers le bas (HIG Tab bars, iOS)
  if (root.hasAttribute("data-minimize")) {
    let lastY = scrollY;
    addEventListener("scroll", () => {
      const y = scrollY; root.classList.toggle("is-minimized", y > lastY && y > 120); lastY = y;
    }, { passive: true });
  }
}

/* ---------- Toolbar : effet de bord de défilement -------------------- */
export function enhanceToolbar(bar) {
  if (done.has(bar)) return; done.add(bar);
  const sentinel = document.createElement("div");
  sentinel.style.cssText = "position:absolute;top:0;height:1px;width:1px;pointer-events:none";
  bar.parentElement.insertBefore(sentinel, bar);
  new IntersectionObserver(([e]) => bar.classList.toggle("is-scrolled", !e.isIntersecting)).observe(sentinel);
}

/* ---------- Halo spéculaire sur le verre ----------------------------- */
function trackPointer(e) {
  const el = e.target.closest?.(".ui-button--glass, .ui-glass.ui-icon-button, .ui-glass.ui-button");
  if (!el) return;
  const r = el.getBoundingClientRect();
  el.style.setProperty("--px", `${e.clientX - r.left}px`);
  el.style.setProperty("--py", `${e.clientY - r.top}px`);
}

/* ---------- Sheets ------------------------------------------------- */
export function openSheet(dialog) {
  if (typeof dialog === "string") dialog = document.getElementById(dialog);
  if (!dialog || dialog.open) return;
  dialog.classList.remove("is-closing");
  dialog.showModal();
  dialog.style.transform = "";
  // Focus sur la boîte elle-même (annoncée via aria-labelledby), sauf [autofocus] explicite
  if (!dialog.querySelector("[autofocus]")) { dialog.tabIndex = -1; dialog.focus(); }
}

export function closeSheet(dialog, returnValue) {
  if (typeof dialog === "string") dialog = document.getElementById(dialog);
  if (!dialog || !dialog.open || dialog.classList.contains("is-closing")) return;
  if (prefersReducedMotion()) { dialog.close(returnValue); return; }
  dialog.classList.add("is-closing");
  const end = () => { dialog.classList.remove("is-closing"); dialog.style.transform = ""; dialog.close(returnValue); };
  dialog.addEventListener("animationend", end, { once: true });
  setTimeout(() => dialog.open && end(), 400);
}

function enhanceSheet(dialog) {
  if (done.has(dialog)) return; done.add(dialog);
  // Clic sur le voile = Annuler (pas pour les alertes)
  dialog.addEventListener("click", (e) => {
    if (e.target === dialog && !dialog.classList.contains("ui-alert")) closeSheet(dialog, "cancel");
  });
  dialog.addEventListener("cancel", (e) => { e.preventDefault(); closeSheet(dialog, "cancel"); });
  // Glisser pour fermer (iPhone) : suit le doigt, relâche avec la vitesse du geste
  const handle = dialog.querySelector(".ui-sheet__grabber, .ui-sheet__bar");
  if (!handle) return;
  let startY = 0, y = 0, lastT = 0, lastY = 0, vel = 0, dragging = false;
  handle.addEventListener("pointerdown", (e) => {
    if (innerWidth >= 700 || e.target.closest("button, a, input")) return;
    dragging = true; startY = e.clientY; lastY = e.clientY; lastT = performance.now(); handle.setPointerCapture(e.pointerId);
    dialog.style.animation = "none";
  });
  handle.addEventListener("pointermove", (e) => {
    if (!dragging) return;
    const now = performance.now();
    y = Math.max(0, e.clientY - startY);
    const raw = e.clientY - startY; if (raw < 0) y = -Math.sqrt(-raw) * 2; // résistance vers le haut
    vel = ((e.clientY - lastY) / Math.max(now - lastT, 1)) * 1000; lastY = e.clientY; lastT = now;
    dialog.style.transform = `translateY(${y}px)`;
  });
  const release = () => {
    if (!dragging) return; dragging = false;
    const h = dialog.getBoundingClientRect().height;
    if (y > h * 0.3 || vel > 900) {
      springValueTo({ from: y, to: h + 40, velocity: vel, duration: 0.35, onUpdate: (v) => (dialog.style.transform = `translateY(${v}px)`),
        onDone: () => { dialog.close("cancel"); dialog.style.transform = ""; dialog.style.animation = ""; } });
    } else {
      springValueTo({ from: y, to: 0, velocity: vel, duration: 0.45, bounce: 0.2, onUpdate: (v) => (dialog.style.transform = `translateY(${v}px)`),
        onDone: () => { dialog.style.transform = ""; dialog.style.animation = ""; } });
    }
  };
  handle.addEventListener("pointerup", release);
  handle.addEventListener("pointercancel", release);
}

/* ---------- Toasts ------------------------------------------------- */
const ICONS = {
  ok: '<svg class="ui-icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="m8 12.4 2.7 2.6L16.2 9"/></svg>',
  critical: '<svg class="ui-icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7.5v5.2"/><path d="M12 16.2v.3"/></svg>',
  info: '<svg class="ui-icon" viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 7.8v.3"/></svg>',
};
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }

/** toast({ title, detail, tone: "ok"|"critical"|"info", action: { label, onClick }, duration }) */
export function toast({ title, detail = "", tone = "info", action, duration = 4200 } = {}) {
  let region = document.querySelector(".ui-toast-region");
  if (!region) { region = document.createElement("div"); region.className = "ui-toast-region"; region.setAttribute("aria-live", "polite"); document.body.append(region); }
  const el = document.createElement("div");
  el.className = `ui-toast ui-glass ui-toast--${tone}`;
  el.setAttribute("role", tone === "critical" ? "alert" : "status");
  el.innerHTML = `<span class="ui-toast__icon">${ICONS[tone] || ICONS.info}</span>
    <span class="ui-toast__text"><strong>${esc(title)}</strong>${detail ? `<span>${esc(detail)}</span>` : ""}</span>`;
  if (action) {
    const b = document.createElement("button");
    b.className = "ui-button ui-button--sm ui-button--tinted"; b.textContent = action.label;
    b.addEventListener("click", () => { action.onClick?.(); dismiss(); });
    el.append(b);
  }
  region.append(el);
  const fromY = innerWidth < 700 ? -24 : 24;
  spring(el, [{ opacity: 0, transform: `translateY(${fromY}px) scale(0.94)` }, { opacity: 1, transform: "none" }], { preset: "bouncy", fill: "none" });
  let timer = setTimeout(dismiss, duration);
  // Hover pauses the timer for a mouse only: on iPhone a touch fires pointerenter without a matching
  // pointerleave, which left the toast on screen for good. A tap dismisses it.
  el.addEventListener("pointerenter", (e) => { if (e.pointerType === "mouse") clearTimeout(timer); });
  el.addEventListener("pointerleave", (e) => { if (e.pointerType === "mouse") timer = setTimeout(dismiss, 1800); });
  el.addEventListener("click", (e) => { if (!e.target.closest("button")) dismiss(); });
  let gone = false;
  function dismiss() {
    if (gone) return; gone = true;
    clearTimeout(timer);
    const remove = () => el.remove();
    const a = spring(el, [{ opacity: 1, transform: "none" }, { opacity: 0, transform: `translateY(${fromY / 2}px) scale(0.96)` }], { preset: "quick", fill: "forwards" });
    (a ? a.finished : Promise.resolve()).then(remove, remove);
    setTimeout(remove, 700); // never rely on the animation alone to remove it
  }
  return { dismiss };
}

/* ---------- Thème et verre ----------------------------------------- */
export function setTheme(mode /* "light" | "dark" | "system" */) {
  const r = document.documentElement;
  if (mode === "system") r.removeAttribute("data-theme"); else r.setAttribute("data-theme", mode);
  try { localStorage.setItem("ui-theme", mode); } catch {}
}
/** 0 = ultra-clair … 1 = teinté (comme le réglage Liquid Glass d'iOS 27). */
export function setGlassTint(v) {
  document.documentElement.style.setProperty("--glass-tint", String(Math.min(1, Math.max(0, v))));
  try { localStorage.setItem("ui-glass", String(v)); } catch {}
}

/* ---------- Curseurs : remplissage de piste ------------------------ */
function syncSlider(input) {
  const min = +input.min || 0, max = +input.max || 100;
  input.style.setProperty("--_v", `${((input.value - min) / (max - min)) * 100}%`);
}

/* ---------- Initialisation ----------------------------------------- */
export function init(scope = hasDOM ? document : null) {
  if (!scope) return;
  try {
    const t = localStorage.getItem("ui-theme"); if (t && t !== "system") document.documentElement.setAttribute("data-theme", t);
    const g = localStorage.getItem("ui-glass"); if (g !== null) document.documentElement.style.setProperty("--glass-tint", g);
  } catch {}
  scope.querySelectorAll(".ui-segmented").forEach(enhanceSegmented);
  scope.querySelectorAll(".ui-tabbar").forEach(enhanceTabbar);
  scope.querySelectorAll(".ui-toolbar").forEach(enhanceToolbar);
  scope.querySelectorAll("dialog.ui-sheet").forEach(enhanceSheet);
  scope.querySelectorAll(".ui-slider").forEach((s) => { syncSlider(s); if (!done.has(s)) { done.add(s); s.addEventListener("input", () => syncSlider(s)); } });
  if (!done.has(document)) {
    done.add(document);
    document.addEventListener("pointermove", trackPointer, { passive: true });
    document.addEventListener("click", (e) => {
      const o = e.target.closest("[data-sheet-open]"); if (o) { openSheet(o.getAttribute("data-sheet-open")); return; }
      const c = e.target.closest("[data-sheet-close]");
      if (c) closeSheet(c.closest("dialog"), c.getAttribute("data-sheet-close") || "cancel");
    });
  }
}

export const UI = { init, spring, springs, springEasing, springCurve, springValueTo, toast, openSheet, closeSheet, setTheme, setGlassTint,
  enhanceSegmented, enhanceTabbar, enhanceToolbar, prefersReducedMotion };

if (hasDOM) {
  window.UI = UI;
  if (document.documentElement.dataset.uiAuto !== "off") {
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => init());
    else init();
  }
}
export default UI;

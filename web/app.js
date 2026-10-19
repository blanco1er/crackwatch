// CrackWatch demo page. No framework, no third-party request. Server data is always inserted as text.
const $ = (s) => document.querySelector(s);
const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
const store = { get(k) { try { return localStorage.getItem(k); } catch { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } } };

const T = {
  en: {
    printCard: 'Print the card', headline: 'A printed card turns a phone photo into a crack gauge.',
    lede: 'OpenCV 5 reads the card to get millimetres, measures the crack width with its uncertainty, and compares it with the last visit. An agent on Amazon Bedrock decides what happens next: a retake, a closer photo of one spot, or a ticket that only a human can approve.',
    proof: 'Measured so far on 300 held-out synthetic photos: median-width error 0.17 mm, card found in 99.7 %. Real-photo validation is in progress and will be published here.',
    guided: 'Guided inspection of a synthetic wall', s1t: 'First photo', s1d: 'Taken in a hurry', s2t: 'Retake', s2d: 'Sharp, but from far away',
    s3t: 'Closer photo', s3d: 'Where the agent asked', s4t: 'Three months later', s4d: 'Second visit, same card',
    emptyTitle: 'Start with step 1, or measure your own photo.', emptyBody: "Each step sends a photo to the measuring service on AWS Lambda (arm64). The agent's answer decides the next step.",
    busy: 'Measuring with OpenCV 5…', busyCold: 'Starting the measuring service (first call can take ~10 s)…', uploading: 'Uploading the photo…',
    ownTitle: 'Measure your own crack',
    own1: '<a href="/card.pdf" target="_blank" rel="noopener" data-visit="card">Print the A6 card</a> at 100&nbsp;% (actual size). Its 50&nbsp;mm ruler must measure 50&nbsp;mm.',
    own2: 'Tape it flat on the wall, 2 to 10 cm from the crack.', own3: 'Photograph card and crack together, facing the wall, without flash.',
    choose: 'Choose or take a photo', usePrev: 'Compare with my previous photo',
    privacy: 'Your photo goes to a private storage bucket and is deleted automatically after 24 hours. Decoding drops EXIF and GPS data. Please do not photograph people.',
    resultEmpty: "The measurement, the agent's decision and every step of its reasoning will appear here.",
    changeTitle: 'Change since the previous visit', traceTitle: 'What the agent did', qualityTitle: 'Photo quality and timings',
    howTitle: 'How it works',
    how1: '<b>Scale.</b> <code>cv2.aruco.CharucoDetector</code> finds the card; <code>findHomography</code> (MAGSAC) maps the photo to the wall plane in millimetres.',
    how2: "<b>Quality.</b> Blur is measured in pixels on the card's black-and-white edges; glare and tilt are checked before anything is measured.",
    how3: '<b>Width.</b> A multi-scale Hessian ridge filter finds the crack; each cross-section is deconvolved with the blur measured on the card, giving sub-pixel widths and an uncertainty.',
    how4: "<b>Change.</b> Both visits share the card's frame; if the card was re-glued, ORB + MAGSAC + ECC register the wall texture.",
    how5: '<b>Decision.</b> Amazon Nova 2 Lite on Bedrock chooses one tool (retake, closer photo, compare, ticket, next visit). A deterministic policy validates every choice and takes over if the model fails or the daily budget is used.',
    disclaimer: 'CrackWatch is a monitoring and triage aid, not a structural diagnosis. Thresholds are configurable defaults, not engineering norms. Tickets are never sent without a human decision.',
    // dynamic
    retake: 'Retake needed', closer: 'Closer photo needed', fine: 'No action needed now', ticket: 'Ticket proposed, waiting for your decision', stop: 'Handed over to a human',
    nextVisit: (d) => `Next visit suggested in ${d} days.`,
    why_blur: (q) => `The photo is blurred: ${fmt(q.blur_sigma_px, 1)} px of edge blur on the card (limit 2.2 px).`,
    why_card_not_found: () => 'The scale card is not visible, so nothing can be measured in millimetres.',
    why_glare: (q) => `Glare: ${fmt(100 * (q.saturated_frac || 0), 1)} % of the wall is over-exposed.`,
    why_oblique: (q) => `The photo is too oblique (${fmt(q.tilt_deg_est, 0)}°).`,
    why_closer: (c) => c ? `The crack is about ${fmt(c.width_mm.median * c.native_px_per_mm, 1)} px wide in this photo; at least 3 px are needed for a reliable width.` : 'No crack was found at this distance; fine cracks may be invisible.',
    doFar: 'Retake, as asked', doClose: 'Take the closer photo', doVisit2: 'Go three months later', approve: 'Approve ticket', reject: 'Reject',
    approved: 'Ticket approved by you. In a real deployment it would now go to the maintenance team.', rejected: 'Ticket rejected by you. The decision is logged with the trace.',
    sMax: 'Max width', sMed: 'Median width', sLen: 'Length', sRes: 'Resolution', sConf: 'Confidence',
    sDelta: 'Widening (median)', sNew: 'New length', sReg: 'Registration',
    truth: (t) => `Synthetic ground truth for this photo: median ${t.median} mm, max ${t.max} mm, length ${t.len} mm.`,
    regCard: 'card frame', regTex: 'wall texture (card moved)',
    planRules: 'Rule policy', agrees: 'same as the rule policy', differs: 'differs from the rule policy, validated',
    caption: 'Blue: card corners. Crack coloured from yellow (thin) to red (wide). White circle: widest sustained point. Dashed box: where the agent wants a closer photo.',
    noCrack: 'No crack found in this photo.', tooBig: 'This photo is larger than 15 MB. Please use a smaller one.',
    errGeneric: 'The measurement failed. Nothing was stored. Please try again.', tryAgain: 'Try again',
    q: { blur: 'Edge blur', sat: 'Over-exposed wall', tilt: 'Tilt (estimated)', ppm: 'Card resolution', corners: 'Card corners found', rms: 'Card fit error', measure: 'Measure', compare: 'Compare', agent: 'Agent', total: 'Total' },
  },
  fr: {
    printCard: 'Imprimer la carte', headline: 'Une carte imprimée transforme une photo de téléphone en jauge de fissure.',
    lede: "OpenCV 5 lit la carte pour obtenir des millimètres, mesure la largeur de la fissure avec son incertitude et la compare à la visite précédente. Un agent sur Amazon Bedrock décide de la suite : reprendre la photo, photographier un endroit de plus près, ou proposer un ticket que seul un humain peut valider.",
    proof: "Mesuré à ce jour sur 300 photos synthétiques indépendantes : erreur de 0,17 mm sur la largeur médiane, carte trouvée dans 99,7 % des cas. La validation sur vraies photos est en cours et sera publiée ici.",
    guided: "Inspection guidée d'un mur synthétique", s1t: 'Première photo', s1d: 'Prise à la hâte', s2t: 'Reprise', s2d: 'Nette, mais de loin',
    s3t: 'Photo rapprochée', s3d: "Là où l'agent l'a demandé", s4t: 'Trois mois plus tard', s4d: 'Deuxième visite, même carte',
    emptyTitle: "Commencez par l'étape 1, ou mesurez votre propre photo.", emptyBody: "Chaque étape envoie une photo au service de mesure sur AWS Lambda (arm64). La réponse de l'agent décide de l'étape suivante.",
    busy: 'Mesure avec OpenCV 5…', busyCold: 'Démarrage du service de mesure (le premier appel peut prendre ~10 s)…', uploading: 'Envoi de la photo…',
    ownTitle: 'Mesurer votre propre fissure',
    own1: '<a href="/card.pdf" target="_blank" rel="noopener" data-visit="card">Imprimez la carte A6</a> à 100&nbsp;% (taille réelle). Sa règle de 50&nbsp;mm doit mesurer 50&nbsp;mm.',
    own2: 'Collez-la à plat sur le mur, à 2 à 10 cm de la fissure.', own3: 'Photographiez la carte et la fissure ensemble, face au mur, sans flash.',
    choose: 'Choisir ou prendre une photo', usePrev: 'Comparer avec ma photo précédente',
    privacy: "Votre photo va dans un espace de stockage privé et s'efface automatiquement au bout de 24 heures. Le décodage supprime les données EXIF et GPS. Merci de ne pas photographier de personnes.",
    resultEmpty: "La mesure, la décision de l'agent et chaque étape de son raisonnement s'afficheront ici.",
    changeTitle: 'Évolution depuis la visite précédente', traceTitle: "Ce qu'a fait l'agent", qualityTitle: 'Qualité de la photo et temps de calcul',
    howTitle: 'Comment ça marche',
    how1: "<b>Échelle.</b> <code>cv2.aruco.CharucoDetector</code> trouve la carte ; <code>findHomography</code> (MAGSAC) projette la photo sur le plan du mur, en millimètres.",
    how2: "<b>Qualité.</b> Le flou est mesuré en pixels sur les bords noir et blanc de la carte ; le reflet et l'inclinaison sont contrôlés avant toute mesure.",
    how3: "<b>Largeur.</b> Un filtre de crête hessien multi-échelle trouve la fissure ; chaque coupe est déconvoluée avec le flou mesuré sur la carte, d'où une largeur sous-pixel et une incertitude.",
    how4: "<b>Évolution.</b> Les deux visites partagent le repère de la carte ; si la carte a été recollée, ORB + MAGSAC + ECC recalent la texture du mur.",
    how5: "<b>Décision.</b> Amazon Nova 2 Lite sur Bedrock choisit un outil (reprise, photo rapprochée, comparaison, ticket, prochaine visite). Une politique déterministe valide chaque choix et prend le relais si le modèle échoue ou si le budget du jour est épuisé.",
    disclaimer: "CrackWatch est un outil de suivi et de tri, pas un diagnostic structurel. Les seuils sont des valeurs par défaut réglables, pas des normes d'ingénierie. Aucun ticket ne part sans décision humaine.",
    retake: 'Photo à reprendre', closer: 'Photo plus proche demandée', fine: 'Rien à faire pour le moment', ticket: 'Ticket proposé, en attente de votre décision', stop: 'Confié à un humain',
    nextVisit: (d) => `Prochaine visite conseillée dans ${d} jours.`,
    why_blur: (q) => `La photo est floue : ${fmt(q.blur_sigma_px, 1)} px de flou sur les bords de la carte (limite 2,2 px).`,
    why_card_not_found: () => "La carte d'échelle n'est pas visible : rien ne peut être mesuré en millimètres.",
    why_glare: (q) => `Reflet : ${fmt(100 * (q.saturated_frac || 0), 1)} % du mur est surexposé.`,
    why_oblique: (q) => `La photo est trop de biais (${fmt(q.tilt_deg_est, 0)}°).`,
    why_closer: (c) => c ? `La fissure fait environ ${fmt(c.width_mm.median * c.native_px_per_mm, 1)} px de large sur cette photo ; il en faut au moins 3 pour une largeur fiable.` : "Aucune fissure trouvée à cette distance ; une fissure fine peut être invisible.",
    doFar: 'Reprendre, comme demandé', doClose: 'Prendre la photo rapprochée', doVisit2: 'Revenir trois mois plus tard', approve: 'Valider le ticket', reject: 'Refuser',
    approved: "Ticket validé par vous. En situation réelle, il partirait maintenant vers l'équipe de maintenance.", rejected: 'Ticket refusé par vous. La décision est enregistrée avec la trace.',
    sMax: 'Largeur max', sMed: 'Largeur médiane', sLen: 'Longueur', sRes: 'Résolution', sConf: 'Confiance',
    sDelta: 'Élargissement (médian)', sNew: 'Nouvelle longueur', sReg: 'Recalage',
    truth: (t) => `Vérité terrain synthétique de cette photo : médiane ${t.median} mm, max ${t.max} mm, longueur ${t.len} mm.`,
    regCard: 'repère de la carte', regTex: 'texture du mur (carte déplacée)',
    planRules: 'Politique à règles', agrees: 'identique à la politique à règles', differs: 'différent de la politique à règles, validé',
    caption: "Bleu : coins de la carte. Fissure colorée du jaune (fine) au rouge (large). Cercle blanc : point le plus large sur 6 mm. Cadre pointillé : zone que l'agent veut voir de plus près.",
    noCrack: 'Aucune fissure trouvée sur cette photo.', tooBig: 'Cette photo dépasse 15 Mo. Choisissez-en une plus légère.',
    errGeneric: "La mesure a échoué. Rien n'a été enregistré. Réessayez.", tryAgain: 'Réessayer',
    q: { blur: 'Flou des bords', sat: 'Mur surexposé', tilt: 'Inclinaison (estimée)', ppm: 'Résolution de la carte', corners: 'Coins de carte trouvés', rms: "Erreur d'ajustement", measure: 'Mesure', compare: 'Comparaison', agent: 'Agent', total: 'Total' },
  },
};
let lang = store.get('cw-lang') === 'fr' ? 'fr' : 'en';
const t = (k) => T[lang][k] ?? T.en[k];
function fmt(v, d = 2) { if (v == null || Number.isNaN(v)) return '—'; return Number(v).toLocaleString(lang === 'fr' ? 'fr-FR' : 'en-US', { minimumFractionDigits: d, maximumFractionDigits: d }); }

function applyLang() {
  document.documentElement.lang = lang;
  document.querySelectorAll('[data-i18n]').forEach((n) => { const v = t(n.dataset.i18n); if (typeof v === 'string') n.textContent = v; });
  document.querySelectorAll('[data-i18n-html]').forEach((n) => { n.innerHTML = t(n.dataset.i18nHtml); }); // static, trusted strings only
  document.querySelectorAll('.cw-lang input').forEach((i) => { i.checked = i.value === lang; });
  if (last) render(last.data, last.ctx);
}

// ------------------------------------------------------------------ anonymous visit events
const screenClass = () => (innerWidth < 700 ? 'compact' : innerWidth < 1000 ? 'regular' : 'large');
function visit(type, extra = {}) {
  const body = JSON.stringify({ type, lang, screen: screenClass(), ...extra });
  try { fetch('/api/visit', { method: 'POST', headers: { 'content-type': 'application/json' }, body, keepalive: true }).catch(() => {}); } catch { /* ignore */ }
}

// ------------------------------------------------------------------ state
const STEPS = ['blurry', 'far', 'close', 'visit2'];
const STEP_REQ = { blurry: { image: { sample: 'blurry' }, retakes: 0 }, far: { image: { sample: 'far' }, retakes: 1 },
  close: { image: { sample: 'close' }, retakes: 2 }, visit2: { image: { sample: 'visit2' }, previous: { sample: 'close' }, retakes: 0 } };
let truth = null;
let last = null;
let busy = false;
let own = { retakes: 0, lastKey: null };
let warm = false;

async function api(path, body) {
  const r = await fetch(path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });
  let data = null;
  try { data = await r.json(); } catch { /* not json */ }
  if (!r.ok) { const e = new Error((data && data.detail) || (data && data.error) || `HTTP ${r.status}`); e.code = data && data.error; throw e; }
  return data;
}

function setBusy(on, textKey = 'busy') {
  busy = on;
  $('#busy').hidden = !on;
  $('#busy-text').textContent = t(textKey);
  document.querySelectorAll('.cw-step, #file').forEach((b) => { b.disabled = on; });
}

async function runStep(step) {
  if (busy) return;
  document.querySelectorAll('.cw-step').forEach((b) => { b.removeAttribute('aria-current'); b.classList.remove('is-suggested'); });
  const btn = document.querySelector(`.cw-step[data-step="${step}"]`);
  btn?.setAttribute('aria-current', 'step');
  visit('sample', { sample: step });
  await inspect(STEP_REQ[step], { step });
  btn?.classList.add('is-done');
}

async function inspect(req, ctx) {
  setBusy(true, warm ? 'busy' : 'busyCold');
  if (ctx.step) showPhoto(`/samples/${ctx.step}.jpg`);
  try {
    const data = await api('/api/inspect', req);
    warm = true;
    last = { data, ctx };
    render(data, ctx);
  } catch (e) {
    renderError(e, () => inspect(req, ctx));
  } finally { setBusy(false); }
}

function showPhoto(src) {
  const img = $('#photo');
  img.src = src;
  img.alt = '';
  img.hidden = false;
  $('#viewer-empty').hidden = true;
}

// ------------------------------------------------------------------ rendering
function plannerLabel(p) {
  if (!p) return '';
  if (p.includes('nova')) return 'Amazon Nova 2 Lite';
  const m = p.match(/^rules(?: \((.*)\))?/);
  return m ? `${t('planRules')}${m[1] ? ` (${m[1]})` : ''}` : p;
}

function stat(label, value, unit, delta) {
  const s = el('div', 'ui-stat');
  s.append(el('p', 'ui-stat__label', label));
  const v = el('p', 'ui-stat__value', value);
  if (unit) v.append(el('small', null, unit));
  s.append(v);
  if (delta) s.append(el('p', 'ui-stat__delta', delta));
  return s;
}

function render(d, ctx) {
  $('#result-empty').hidden = true;
  $('#result').hidden = false;
  $('#photo').src = `data:image/jpeg;base64,${d.overlay_jpeg_b64}`;
  $('#photo').alt = 'Photo with the measured crack overlaid';
  $('#photo').hidden = false;
  $('#viewer-empty').hidden = true;
  $('#caption').textContent = t('caption');
  const m = d.measurement;
  const q = m.quality || {};
  const crack = (m.cracks || [])[0];
  const lastAct = d.trace[d.trace.length - 1].action;

  // decision
  const dec = $('#decision');
  dec.textContent = '';
  const tone = { request_retake: 'warn', request_closer_photo: 'info', propose_ticket: 'critical', schedule_next_visit: 'ok', stop: 'warn' }[lastAct.name] || 'info';
  const key = { request_retake: 'retake', request_closer_photo: 'closer', propose_ticket: 'ticket', schedule_next_visit: 'fine', stop: 'stop' }[lastAct.name];
  dec.append(el('span', `ui-status ui-status--${tone}`, plannerLabel(lastAct.planner)));
  dec.append(document.createTextNode(t(key)));
  document.querySelectorAll('.cw-instruction').forEach((n) => n.remove());
  const instr = el('p', 'cw-instruction');
  let why = '';
  if (lastAct.name === 'request_retake') why = (T[lang][`why_${lastAct.args.reason}`] || T.en.why_blur)(q);
  if (lastAct.name === 'request_closer_photo') why = t('why_closer')(crack);
  if (lastAct.name === 'schedule_next_visit') why = t('nextVisit')(lastAct.args.days);
  instr.textContent = [why, lastAct.args.instruction].filter(Boolean).join(' ');
  dec.after(instr);

  // next actions (the agent's request decides the suggested next step)
  const acts = $('#actions');
  acts.textContent = '';
  const suggest = (step, label) => {
    const b = el('button', 'ui-button ui-button--prominent', label);
    b.addEventListener('click', () => runStep(step));
    acts.append(b);
    document.querySelector(`.cw-step[data-step="${step}"]`)?.classList.add('is-suggested');
  };
  if (ctx.step) {
    if (lastAct.name === 'request_retake') suggest('far', t('doFar'));
    if (lastAct.name === 'request_closer_photo') suggest('close', t('doClose'));
    if (lastAct.name === 'schedule_next_visit' && ctx.step === 'close') suggest('visit2', t('doVisit2'));
  }
  if (d.ticket) {
    const ok = el('button', 'ui-button ui-button--prominent', t('approve'));
    const no = el('button', 'ui-button ui-button--plain', t('reject'));
    const decide = async (decision) => {
      ok.disabled = no.disabled = true;
      try {
        const r = await api(`/api/tickets/${d.ticket.id}/decision`, { decision });
        acts.textContent = '';
        acts.append(el('p', 'ui-subhead', r.status === 'approved' ? t('approved') : t('rejected')));
      } catch (e) { ok.disabled = no.disabled = false; renderError(e); }
    };
    ok.addEventListener('click', () => decide('approve'));
    no.addEventListener('click', () => decide('reject'));
    acts.append(ok, no);
  }

  // stats
  const st = $('#stats');
  st.textContent = '';
  if (crack) {
    st.append(stat(t('sMax'), fmt(crack.width_mm.max), ' mm', `± ${fmt(2 * crack.uncertainty_mm)} mm (2σ)`));
    st.append(stat(t('sMed'), fmt(crack.width_mm.median), ' mm'));
    st.append(stat(t('sLen'), fmt(crack.length_mm, 0), ' mm'));
    st.append(stat(t('sRes'), fmt(crack.native_px_per_mm, 1), ' px/mm'));
    st.append(stat(t('sConf'), fmt(100 * crack.confidence, 0), ' %'));
  } else {
    st.append(el('p', 'ui-subhead ui-secondary', m.status === 'no_card' ? t('why_card_not_found')() : t('noCrack')));
  }
  const tr = $('#truth');
  const gt = ctx.step && truth && truth.samples[ctx.step];
  tr.hidden = !gt;
  if (gt) tr.textContent = t('truth')({ median: fmt(gt.true_width_mm.median), max: fmt(gt.true_width_mm.max), len: fmt(gt.true_length_mm, 0) });

  // comparison
  const cb = $('#compare-box');
  cb.hidden = !(d.comparison && d.comparison.status === 'ok');
  if (!cb.hidden) {
    const c = d.comparison;
    const cs = $('#compare-stats');
    cs.textContent = '';
    cs.append(stat(t('sDelta'), `${c.width_delta_mm.median >= 0 ? '+' : ''}${fmt(c.width_delta_mm.median)}`, ' mm', `± ${fmt(2 * c.delta_uncertainty_mm)} mm (2σ)`));
    cs.append(stat(t('sNew'), fmt(c.new_length_mm, 0), ' mm'));
    cs.append(stat(t('sReg'), c.registration?.mode === 'texture_homography' ? t('regTex') : t('regCard')));
  }

  // trace
  const list = $('#trace');
  list.textContent = '';
  d.trace.forEach((s, i) => {
    const a = s.action;
    const meta = a.meta || {};
    const li = el('li');
    li.append(el('span', 'cw-trace__n', String(i + 1)));
    const head = el('div');
    head.append(el('span', 'cw-trace__tool', a.name));
    li.append(head);
    li.append(el('div', 'cw-trace__why', meta.rationale || a.reason || ''));
    const bits = [plannerLabel(a.planner)];
    if (meta.latency_ms != null) bits.push(`${meta.latency_ms} ms`);
    if (meta.input_tokens != null) bits.push(`${meta.input_tokens} + ${meta.output_tokens} tokens`, `$${fmt(meta.cost_usd, 4)}`);
    if (meta.agrees_with_rules != null) bits.push(meta.agrees_with_rules ? t('agrees') : t('differs'));
    if (s.cv && s.cv.max_width_mm != null) bits.push(`CV: max ${fmt(s.cv.max_width_mm)} mm, conf. ${fmt(s.cv.confidence)}`);
    li.append(el('div', 'cw-trace__meta', bits.join(' · ')));
    list.append(li);
  });

  // quality
  const dl = $('#quality');
  dl.textContent = '';
  const row = (k, v) => { dl.append(el('dt', null, k), el('dd', null, v)); };
  const Q = t('q');
  row(Q.blur, `${fmt(q.blur_sigma_px, 2)} px`);
  row(Q.sat, `${fmt(100 * (q.saturated_frac || 0), 1)} %`);
  row(Q.tilt, `${fmt(q.tilt_deg_est, 0)}°`);
  row(Q.ppm, `${fmt(q.card_px_per_mm, 1)} px/mm`);
  row(Q.corners, `${q.card_corners ?? '—'}`);
  row(Q.rms, `${fmt(q.card_reproj_rms_px, 2)} px`);
  const tm = d.timings_ms || {};
  row(Q.measure, `${tm.measure_ms ?? '—'} ms`);
  if (tm.compare_ms != null) row(Q.compare, `${tm.compare_ms} ms`);
  row(Q.agent, `${tm.agent_ms ?? '—'} ms`);
  row(Q.total, `${tm.total_ms ?? '—'} ms`);
}

function renderError(e, retry) {
  $('#result-empty').hidden = true;
  $('#result').hidden = false;
  const dec = $('#decision');
  dec.textContent = '';
  const msg = e.code === 'daily_limit' || e.code === 'visitor_limit' ? e.message : t('errGeneric');
  const b = el('div', 'ui-banner ui-banner--warn');
  const txt = el('div');
  txt.append(el('strong', null, msg));
  if (e.code) txt.append(el('p', null, e.code));
  b.append(txt);
  dec.append(b);
  document.querySelectorAll('.cw-instruction').forEach((n) => n.remove());
  const acts = $('#actions');
  acts.textContent = '';
  if (retry) { const r = el('button', 'ui-button ui-button--tinted', t('tryAgain')); r.addEventListener('click', retry); acts.append(r); }
  ['#stats', '#trace', '#quality'].forEach((s) => { $(s).textContent = ''; });
  $('#compare-box').hidden = true;
  $('#truth').hidden = true;
}

// ------------------------------------------------------------------ own photo
async function uploadOwn(file) {
  if (file.size > 15 * 1024 * 1024) { renderError({ code: 'image_too_large', message: t('tooBig') }); return; }
  setBusy(true, 'uploading');
  showPhoto(URL.createObjectURL(file));
  document.querySelectorAll('.cw-step').forEach((b) => b.classList.remove('is-suggested', 'is-done'));
  try {
    const up = await api('/api/upload-url', {});
    const form = new FormData();
    Object.entries(up.fields).forEach(([k, v]) => form.append(k, v));
    form.append('file', file);
    const r = await fetch(up.url, { method: 'POST', body: form });
    if (!r.ok) throw Object.assign(new Error('upload_failed'), { code: 'upload_failed' });
    visit('upload');
    const usePrev = $('#use-prev').checked && own.lastKey;
    setBusy(true, warm ? 'busy' : 'busyCold');
    const data = await api('/api/inspect', { image: { key: up.key }, previous: usePrev ? { key: own.lastKey } : null, retakes: own.retakes });
    warm = true;
    last = { data, ctx: {} };
    render(data, {});
    const a = data.trace[data.trace.length - 1].action.name;
    if (a === 'request_retake' || a === 'request_closer_photo') own.retakes += 1;
    else { own.retakes = 0; if (data.measurement.status === 'ok') { own.lastKey = up.key; $('#prev-wrap').hidden = false; } }
  } catch (e) {
    renderError(e);
  } finally { setBusy(false); $('#file').value = ''; }
}

// ------------------------------------------------------------------ wiring
document.querySelectorAll('.cw-step').forEach((b) => b.addEventListener('click', () => runStep(b.dataset.step)));
$('#file').addEventListener('change', (e) => { const f = e.target.files && e.target.files[0]; if (f) uploadOwn(f); });
document.querySelectorAll('.cw-lang input').forEach((i) => i.addEventListener('change', () => { lang = i.value; store.set('cw-lang', lang); applyLang(); visit('lang'); }));
document.addEventListener('click', (e) => { const a = e.target.closest('[data-visit]'); if (a) visit(a.dataset.visit); });
document.querySelector('.cw-bar') && addEventListener('scroll', () => document.querySelector('.cw-bar').classList.toggle('is-scrolled', scrollY > 4), { passive: true });

applyLang();
fetch('/samples/samples.json').then((r) => r.json()).then((j) => { truth = j; }).catch(() => {});
fetch('/api/health').then((r) => r.json()).then((h) => { $('#health').textContent = `OpenCV ${h.opencv} · ${h.runtime}`; }).catch(() => {});
let ref = '';
try { const h = document.referrer ? new URL(document.referrer).hostname.replace(/^www\./, '') : ''; ref = h && h !== location.hostname ? h : ''; } catch { /* ignore */ }
const utm = new URLSearchParams(location.search).get('utm_source') || '';
visit('view', { ref, utm });

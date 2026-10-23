/* CrackWatch guided camera.
   openGuidedCamera({ onPhoto(file), onCancel(), lang: 'en' | 'fr' }) -> { close() }

   Full-screen rear camera with live framing hints. OpenCV.js runs in a Web Worker on ~640 px frames a few times a
   second and finds either the printed ChArUco card or a wallet-size card; when the card is big enough, the phone
   faces the wall and nothing moves, a short ring fills and the photo is taken automatically (manual shutter and
   "choose from library" are always available). The live overlay only GUIDES: the measurement is done on the server,
   on the captured full-resolution photo. Everything degrades to a plain camera, then to the photo library. */

const STR = {
  en: {
    dialog: 'Camera', close: 'Close', torchOn: 'Turn on the light', torchOff: 'Turn off the light',
    shutter: 'Take the photo', library: 'Library', libraryLong: 'Choose from library',
    preparing: 'Preparing the live guide…', guideOff: 'Live guide unavailable. Take the photo with the button.',
    place: 'Place a card next to the crack', closer: 'Come closer', back: 'Move back a little',
    straight: 'Hold the phone straight', straightSub: 'Face the wall until the level turns green', still: 'Hold still',
    aim: 'Aim the centre at the crack', level: 'Level', levelEst: 'estimated from the phone', dark: 'Too dark — turn on the light',
    darkNoTorch: 'Too dark — find more light', great: 'Great — hold still…',
    seenCharuco: 'CrackWatch card found', seenWallet: 'Bank-card-size card found',
    placeSub: 'The CrackWatch card, or any bank-card-size card',
    reviewTitle: 'Check the photo', use: 'Use this photo', retake: 'Retake',
    honest: 'The frame on screen only helps you aim. The width is measured on our server, from this photo.',
    errTitle: 'Camera unavailable', errInsecure: 'The camera needs a secure (https) connection. You can still choose a photo.',
    errDenied: 'Camera access is turned off. Allow it in your browser settings, or choose a photo.',
    errNoCam: 'No camera was found on this device. You can choose a photo instead.',
    errBusy: 'Another app is using the camera. Close it and try again, or choose a photo.',
    errOther: 'The camera could not start. Try again, or choose a photo.', retry: 'Try again', taken: 'Photo taken',
  },
  fr: {
    dialog: 'Appareil photo', close: 'Fermer', torchOn: 'Allumer la lampe', torchOff: 'Éteindre la lampe',
    shutter: 'Prendre la photo', library: 'Photos', libraryLong: 'Choisir dans mes photos',
    preparing: 'Préparation du guide…', guideOff: 'Guide indisponible. Prenez la photo avec le bouton.',
    place: 'Placez une carte à côté de la fissure', closer: 'Rapprochez-vous', back: 'Reculez un peu',
    straight: 'Tenez le téléphone bien en face', straightSub: 'Face au mur, jusqu’à ce que le niveau passe au vert', still: 'Ne bougez plus',
    aim: 'Visez la fissure avec le centre', level: 'Niveau', levelEst: 'estimé par le téléphone', dark: 'Trop sombre — allumez la lampe',
    darkNoTorch: 'Trop sombre — cherchez plus de lumière', great: 'Parfait — ne bougez plus…',
    seenCharuco: 'Carte CrackWatch repérée', seenWallet: 'Carte format bancaire repérée',
    placeSub: 'La carte CrackWatch, ou toute carte au format carte bancaire',
    reviewTitle: 'Vérifiez la photo', use: 'Utiliser cette photo', retake: 'Reprendre',
    honest: 'Le cadre à l’écran sert seulement à viser. La largeur est mesurée sur notre serveur, à partir de cette photo.',
    errTitle: 'Appareil photo indisponible', errInsecure: 'L’appareil photo demande une connexion sécurisée (https). Vous pouvez quand même choisir une photo.',
    errDenied: 'L’accès à l’appareil photo est désactivé. Autorisez-le dans les réglages du navigateur, ou choisissez une photo.',
    errNoCam: 'Aucun appareil photo sur cet appareil. Vous pouvez choisir une photo.',
    errBusy: 'Une autre app utilise l’appareil photo. Fermez-la et réessayez, ou choisissez une photo.',
    errOther: 'L’appareil photo n’a pas pu démarrer. Réessayez, ou choisissez une photo.', retry: 'Réessayer', taken: 'Photo prise',
  },
};

// Thresholds. px/mm are in the CAPTURED photo (the server's agent asks for a closer photo below 5 px/mm).
const CFG = {
  analyseLong: 960,        // long side of analysed frames (960: live tilt within ~2 deg of the server's on real photos)
  frameGapMs: 140,         // pause between analysed frames (one frame in flight at a time)
  minPxPerMm: 5.0, closerExit: 4.5, targetPxPerMm: 6.5, maxPxPerMm: 45,
  // degrees between the camera axis and the wall normal. Deep cracks read narrower when seen at an angle (near lip
  // hides the gap), so the photo is only taken within 10 deg; enter at 8 to absorb the live estimate's error.
  maxTilt: 8, tiltExit: 10, levelOk: 10,
  maxMotion: 3.2,          // mean |frame difference| (0-255) on a 1/4 thumbnail
  maxCornerShift: 0.025,   // card corner jump between analysed frames, fraction of the card size
  darkLuma: 42, darkExit: 50,
  holdMs: 1000,            // ring duration before the automatic photo
  retakeCooldownMs: 2200, workerTimeoutMs: 35000, jpegQuality: 0.92,
};
const A6_BOARD = { w: 79, h: 109 }, ID1 = { w: 85.6, h: 53.98 };   // checkerboard + 2 mm, wallet card

const ICON = {
  x: '<path d="M6.5 6.5l11 11M17.5 6.5l-11 11"/>',
  bolt: '<path d="M13 3 5.5 13.5H12L11 21l7.5-10.5H12z"/>',
  photo: '<rect x="3.5" y="5" width="17" height="14" rx="2.5"/><circle cx="9" cy="10" r="1.6"/><path d="m4 17 5-4.5 3.5 3 3-2.5 4.5 4"/>',
  camoff: '<path d="M4 8.5A1.5 1.5 0 0 1 5.5 7h2l1.4-2h6.2l1.4 2h2A1.5 1.5 0 0 1 20 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 17.5z"/><path d="M4 4l16 16"/>',
};
const svg = (name, cls = 'gc-icon') => `<svg class="${cls}" viewBox="0 0 24 24" aria-hidden="true">${ICON[name]}</svg>`;

let worker = null, workerState = 'idle', workerReadyAt = 0, workerLoadMs = null;
const workerWaiters = [];
function getWorker() {
  if (worker) return worker;
  workerState = 'loading';
  try { worker = new Worker('/camera-worker.js'); } catch (e) { workerState = 'failed'; return null; }
  const timer = setTimeout(() => { if (workerState === 'loading') { workerState = 'failed'; flushWaiters(); } }, CFG.workerTimeoutMs);
  worker.addEventListener('message', (ev) => {
    const m = ev.data;
    if (m.type === 'ready') { workerState = 'ready'; workerLoadMs = m.loadMs; workerReadyAt = performance.now(); clearTimeout(timer); flushWaiters(); }
    if (m.type === 'fail') { workerState = 'failed'; clearTimeout(timer); flushWaiters(); }
  });
  worker.addEventListener('error', () => { workerState = 'failed'; clearTimeout(timer); flushWaiters(); });
  return worker;
}
function flushWaiters() { while (workerWaiters.length) workerWaiters.shift()(workerState); }
const whenWorker = () => new Promise((res) => (workerState === 'ready' || workerState === 'failed' ? res(workerState) : workerWaiters.push(res)));

function ensureCss() {
  if (document.querySelector('link[data-gc-css]')) return;
  const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = '/camera.css'; l.dataset.gcCss = '';
  document.head.append(l);
}

export function openGuidedCamera({ onPhoto = () => {}, onCancel = () => {}, lang = 'en' } = {}) {
  ensureCss();
  const L = STR[lang] || STR.en;
  const root = document.createElement('div');
  root.className = 'gc'; root.setAttribute('role', 'dialog'); root.setAttribute('aria-modal', 'true'); root.setAttribute('aria-label', L.dialog);
  root.lang = lang;
  root.innerHTML = `
    <video class="gc__video" playsinline webkit-playsinline muted autoplay disablepictureinpicture></video>
    <svg class="gc__overlay" aria-hidden="true"><rect class="gc__ghost" rx="10"/><polygon class="gc__quad"/>
      <g class="gc__reticle"><circle r="15"/><path d="M-27 0h-8M27 0h8M0 -27v-8M0 27v8"/><circle class="gc__reticle-dot" r="2"/></g></svg>
    <div class="gc__top">
      <button class="gc-round" type="button" data-act="close" aria-label="${L.close}">${svg('x')}</button>
      <div class="gc-level" role="img" hidden>
        <svg viewBox="0 0 40 40" aria-hidden="true"><circle class="gc-level__ring" cx="20" cy="20" r="18"/><circle class="gc-level__zone" cx="20" cy="20" r="6.5"/><circle class="gc-level__dot" cx="20" cy="20" r="4.5"/></svg>
        <span class="gc-level__deg"></span>
      </div>
      <button class="gc-round" type="button" data-act="torch" aria-label="${L.torchOn}" aria-pressed="false" hidden>${svg('bolt')}</button>
    </div>
    <div class="gc__status" role="status" hidden><span class="gc-spin" aria-hidden="true"></span><span class="gc__status-text"></span></div>
    <div class="gc__hint" aria-live="polite"><p class="gc__hint-main"></p><p class="gc__hint-sub"></p></div>
    <div class="gc__bottom">
      <button class="gc-side" type="button" data-act="library" aria-label="${L.libraryLong}">${svg('photo')}<span>${L.library}</span></button>
      <button class="gc-shutter" type="button" data-act="shutter" aria-label="${L.shutter}" disabled>
        <svg class="gc-ring" viewBox="0 0 84 84" aria-hidden="true"><circle class="gc-ring__track" cx="42" cy="42" r="39"/><circle class="gc-ring__fill" cx="42" cy="42" r="39"/></svg>
        <span class="gc-shutter__dot"></span>
      </button>
      <span class="gc-side gc-side--spacer" aria-hidden="true"></span>
    </div>
    <div class="gc__flash" aria-hidden="true"></div>
    <section class="gc__review" hidden aria-labelledby="gcReviewTitle">
      <h2 class="gc__review-title" id="gcReviewTitle">${L.reviewTitle}</h2>
      <div class="gc__review-media"><img alt=""></div>
      <p class="gc__review-note">${L.honest}</p>
      <div class="gc__review-actions">
        <button class="gc-btn gc-btn--soft" type="button" data-act="retake">${L.retake}</button>
        <button class="gc-btn gc-btn--primary" type="button" data-act="use">${L.use}</button>
      </div>
    </section>
    <section class="gc__error" hidden aria-labelledby="gcErrTitle">
      <div class="gc__error-icon">${svg('camoff')}</div>
      <h2 id="gcErrTitle">${L.errTitle}</h2>
      <p class="gc__error-text"></p>
      <div class="gc__error-actions">
        <button class="gc-btn gc-btn--primary" type="button" data-act="library">${svg('photo')}<span>${L.libraryLong}</span></button>
        <button class="gc-btn gc-btn--soft" type="button" data-act="retry">${L.retry}</button>
      </div>
    </section>
    <input type="file" accept="image/jpeg,image/png,image/*" hidden>`;
  const $ = (s) => root.querySelector(s);
  const video = $('.gc__video'), overlay = $('.gc__overlay'), ghost = $('.gc__ghost'), quadEl = $('.gc__quad');
  const hintMain = $('.gc__hint-main'), hintSub = $('.gc__hint-sub'), hintBox = $('.gc__hint');
  const statusEl = $('.gc__status'), statusText = $('.gc__status-text');
  const levelEl = $('.gc-level'), levelDot = $('.gc-level__dot'), levelDeg = $('.gc-level__deg'), reticle = $('.gc__reticle');
  const shutter = $('.gc-shutter'), ringFill = $('.gc-ring__fill'), torchBtn = $('[data-act="torch"]');
  const review = $('.gc__review'), reviewImg = $('.gc__review img'), errBox = $('.gc__error'), fileIn = $('input[type=file]');
  const RING = 2 * Math.PI * 39;
  ringFill.style.strokeDasharray = `${RING}`; ringFill.style.strokeDashoffset = `${RING}`;

  // ---------------------------------------------------------------- state
  let stream = null, track = null, closed = false, torchOn = false;
  let analysing = false, inFlight = false, frameId = 0, pumpTimer = 0, raf = 0;
  let small = null, sctx = null;
  let lastCard = null, lastResultAt = 0, lostCount = 0, candidate = null, candidateN = 0, shownKey = '';
  let closeEnough = false, straightOk = false, darkNow = false, holdStart = 0, cooldownUntil = 0;
  let shownQuad = null, targetQuad = null, quadGood = false, kindSeen = null;
  let capturing = false, reviewBlob = null, reviewUrl = null, motionRate = 0;
  let tiltHist = [], devTilt = null;
  const stats = { log: [], streamAt: 0, frames: 0, detected: 0, ms: [], rtt: [], hints: [], firstReadyAt: 0, autoCaptures: 0, captureSource: null };
  root.__gcStats = stats; // read by the automated tests

  const prevOverflow = document.documentElement.style.overflow;
  document.documentElement.style.overflow = 'hidden';
  document.body.append(root);
  requestAnimationFrame(() => root.classList.add('is-open'));

  // ---------------------------------------------------------------- layout
  // object-fit: contain, so the screen shows exactly what the photo will contain (cover would hide its sides)
  function cover() {
    const cw = root.clientWidth, ch = root.clientHeight, vw = video.videoWidth || cw, vh = video.videoHeight || ch;
    const s = Math.min(cw / vw, ch / vh);
    return { s, dx: (cw - vw * s) / 2, dy: (ch - vh * s) / 2, cw, ch, vw, vh };
  }
  function layoutGhost() {
    const c = cover();
    overlay.setAttribute('viewBox', `0 0 ${c.cw} ${c.ch}`);
    const sheet = kindSeen === 'wallet' ? ID1 : A6_BOARD;
    // size the ghost at the target scale for THIS camera's resolution, clamped to stay readable
    let gw = sheet.w * CFG.targetPxPerMm * c.s, gh = sheet.h * CFG.targetPxPerMm * c.s;
    const top = $('.gc__top').getBoundingClientRect().bottom, bottom = $('.gc__hint').getBoundingClientRect().top;
    const avail = Math.max(120, bottom - top - 24);
    const gap = Math.max(28, c.cw * 0.06), room = c.cw / 2 - gap - 16;   // right half, clear of the centre reticle
    let k = gw < room * 0.7 ? (room * 0.7) / gw : 1;                    // a 4K camera would give a tiny ghost
    k = Math.min(k, room / gw, avail / gh);
    gw *= k; gh *= k;
    ghost.setAttribute('x', c.cw / 2 + gap); ghost.setAttribute('y', c.ch / 2 - gh / 2);
    reticle.setAttribute('transform', `translate(${c.cw / 2} ${c.ch / 2})`);
    ghost.setAttribute('width', gw); ghost.setAttribute('height', gh);
  }
  const ro = new ResizeObserver(() => requestAnimationFrame(layoutGhost));
  ro.observe(root);

  // ---------------------------------------------------------------- hints
  function setHint(key, sub = '') {
    if (key === shownKey && hintSub.textContent === sub) return;
    shownKey = key;
    hintMain.textContent = key ? L[key] : '';
    hintSub.textContent = sub; hintSub.hidden = !sub;
    hintBox.dataset.tone = key === 'great' ? 'good' : key === 'dark' || key === 'darkNoTorch' ? 'warn' : '';
    hintBox.hidden = !key; root.dataset.hint = key;
    stats.hints.push({ t: Math.round(performance.now()), key });
    layoutGhost();
  }
  function setStatus(text) { statusEl.hidden = !text; statusText.textContent = text || ''; }

  function evaluate(r) {
    const c = cover();
    const k = c.vw / r.w;                                // analysed px -> photo px
    if (darkNow ? r.luma < CFG.darkExit : r.luma < CFG.darkLuma) { darkNow = true; return track && hasTorch() && !torchOn ? 'dark' : 'darkNoTorch'; }
    darkNow = false;
    const card = r.card;
    if (!card) { tiltHist = []; return 'place'; }
    const ppm = card.pxPerMm * k;
    let xs = card.quad.map((p) => p[0]), ys = card.quad.map((p) => p[1]);
    const bw = (Math.max(...xs) - Math.min(...xs)) / r.w, bh = (Math.max(...ys) - Math.min(...ys)) / r.h;
    if (ppm > CFG.maxPxPerMm || (card.kind === 'wallet' && (bw > 0.9 || bh > 0.9))) return 'back';
    closeEnough = ppm >= (closeEnough ? CFG.closerExit : CFG.minPxPerMm);
    if (!closeEnough) return 'closer';
    tiltHist.push(card.tiltDeg); if (tiltHist.length > 3) tiltHist.shift();
    const tilt = tiltHist.slice().sort((a, b) => a - b)[tiltHist.length >> 1];   // median of the last 3 frames
    straightOk = tilt <= (straightOk ? CFG.tiltExit : CFG.maxTilt) && card.tiltDeg <= CFG.levelOk;
    if (!straightOk) return 'straight';
    let shift = 0;
    if (lastCard && lastCard.kind === card.kind) {
      const size = Math.hypot(bw * r.w, bh * r.h);
      shift = Math.max(...card.quad.map((p, i) => Math.hypot(p[0] - lastCard.quad[i][0], p[1] - lastCard.quad[i][1]))) / size;
    }
    if ((r.motion != null && r.motion > CFG.maxMotion) || shift > CFG.maxCornerShift || motionRate > 30) return 'still';
    return 'great';
  }

  function onResult(r) {
    inFlight = false;
    if (closed || !analysing) return;
    stats.frames++; if (r.ms != null) stats.ms.push(r.ms); if (r.sentAt) stats.rtt.push(performance.now() - r.sentAt);
    if (r.card) stats.detected++;
    if (stats.log.length < 3000) stats.log.push({ t: Math.round(performance.now() - stats.streamAt), ms: r.ms && Math.round(r.ms),
      kind: r.card && r.card.kind, m: r.card && r.card.markers, tilt: r.card && +r.card.tiltDeg.toFixed(1),
      ppm: r.card && +(r.card.pxPerMm * (video.videoWidth / r.w)).toFixed(2), luma: Math.round(r.luma), motion: r.motion && +r.motion.toFixed(2) });
    const c = cover();
    let key = evaluate(r);
    if (stats.log.length) stats.log[stats.log.length - 1].key = key;
    showLevel(r.card ? { deg: r.card.tiltDeg, x: r.card.tiltX, y: r.card.tiltY, src: 'card' } : devTilt);
    if (r.card) {
      root.dataset.kind = r.card.kind;
      lostCount = 0; kindSeen = r.card.kind;
      const sx = c.vw / r.w;
      targetQuad = r.card.quad.map((p) => [p[0] * sx * c.s + c.dx, p[1] * sx * c.s + c.dy]);
      if (!shownQuad) shownQuad = targetQuad.map((p) => p.slice());
      lastCard = r.card;
    } else if (++lostCount >= 3) { targetQuad = null; lastCard = null; }
    if (!r.card && lostCount < 3 && shownKey && shownKey !== 'great') key = shownKey; // brief dropouts don't flicker
    quadGood = key === 'great';
    // one hint at a time; a new hint must hold for 2 analysed frames (except "great", shown at once)
    if (key === candidate) candidateN++; else { candidate = key; candidateN = 1; }
    if (key === 'great' || candidateN >= 2 || !shownKey) {
      const sub = key === 'place' ? L.placeSub : key === 'straight' ? L.straightSub : key.startsWith('dark') ? '' : r.card ? L.aim : '';
      setHint(key, sub);
    }
    if (key === 'great' && performance.now() >= cooldownUntil) { if (!holdStart) holdStart = performance.now(); }
    else holdStart = 0;
    root.dataset.state = key;
    schedule();
  }

  // live level: green within 10 deg. From the card's homography; before a card is seen, from the phone's sensors
  // (angle to the nearest vertical or horizontal plane, so it suits walls and floors alike).
  function showLevel(t) {
    if (!t || !analysing) { levelEl.hidden = true; return; }
    const ok = t.deg <= CFG.levelOk, R = 13.5, k = 6.5 / CFG.levelOk;
    let dx = (t.x || 0) * k, dy = (t.y || 0) * k; const m = Math.hypot(dx, dy);
    if (m > R) { dx *= R / m; dy *= R / m; }
    levelDot.setAttribute('cx', (20 + dx).toFixed(1)); levelDot.setAttribute('cy', (20 + dy).toFixed(1));
    levelEl.hidden = false; levelEl.classList.toggle('is-ok', ok); levelEl.dataset.src = t.src;
    levelDeg.textContent = `${t.src === 'device' ? '≈ ' : ''}${Math.round(t.deg)}°`;
    levelEl.setAttribute('aria-label', `${L.level} ${Math.round(t.deg)}°${t.src === 'device' ? ' (' + L.levelEst + ')' : ''}`);
    root.dataset.tilt = t.deg.toFixed(1);
  }
  function onOrient(e) {
    if (e.beta == null || e.gamma == null) return;
    const b = e.beta * Math.PI / 180, g = e.gamma * Math.PI / 180;
    const elev = Math.asin(Math.max(-1, Math.min(1, Math.cos(b) * Math.cos(g)))) * 180 / Math.PI; // camera axis vs horizon
    const toWall = Math.abs(elev), toFloor = 90 - Math.abs(elev);
    devTilt = toWall <= toFloor ? { deg: toWall, x: 0, y: -elev, src: 'device' }
                                : { deg: toFloor, x: e.gamma > 0 ? toFloor : -toFloor, y: 0, src: 'device' };
    if (!lastCard && analysing) showLevel(devTilt);
  }

  function schedule() {
    clearTimeout(pumpTimer);
    if (!closed && analysing) pumpTimer = setTimeout(pump, CFG.frameGapMs);
  }
  function pump() {
    if (closed || !analysing || inFlight || !worker || workerState !== 'ready') return;
    if (video.readyState < 2 || !video.videoWidth) { schedule(); return; }
    const vw = video.videoWidth, vh = video.videoHeight, s = CFG.analyseLong / Math.max(vw, vh);
    const w = Math.round(vw * Math.min(1, s)), h = Math.round(vh * Math.min(1, s));
    if (!small) { small = document.createElement('canvas'); sctx = small.getContext('2d', { willReadFrequently: true }); }
    if (small.width !== w || small.height !== h) { small.width = w; small.height = h; }
    sctx.drawImage(video, 0, 0, w, h);
    const img = sctx.getImageData(0, 0, w, h);
    inFlight = true;
    const id = ++frameId, sentAt = performance.now();
    pending.set(id, sentAt);
    worker.postMessage({ type: 'frame', id, w, h, buf: img.data.buffer }, [img.data.buffer]);
  }
  const pending = new Map();
  function onWorkerMessage(ev) {
    const m = ev.data;
    if (m.type !== 'result') return;
    const sentAt = pending.get(m.id); pending.delete(m.id);
    if (m.skipped) { inFlight = false; schedule(); return; }
    onResult({ ...m, sentAt });
  }

  // ---------------------------------------------------------------- animation loop (quad snap + ring)
  function tick() {
    raf = requestAnimationFrame(tick);
    if (targetQuad) {
      if (!shownQuad) shownQuad = targetQuad.map((p) => p.slice());
      for (let i = 0; i < 4; i++) for (let j = 0; j < 2; j++) shownQuad[i][j] += (targetQuad[i][j] - shownQuad[i][j]) * 0.45;
      quadEl.setAttribute('points', shownQuad.map((p) => p.map((v) => v.toFixed(1)).join(',')).join(' '));
      quadEl.classList.add('is-on'); quadEl.classList.toggle('is-good', quadGood);
      ghost.classList.add('is-matched');
    } else {
      quadEl.classList.remove('is-on', 'is-good'); shownQuad = null; ghost.classList.remove('is-matched');
    }
    let p = 0;
    if (holdStart && analysing && !capturing) {
      p = Math.min(1, (performance.now() - holdStart) / CFG.holdMs);
      if (p >= 1) { stats.autoCaptures++; capture(true); }
    }
    ringFill.style.strokeDashoffset = `${RING * (1 - p)}`;
    shutter.classList.toggle('is-armed', p > 0);
  }

  // ---------------------------------------------------------------- camera
  const hasTorch = () => { try { return !!(track && track.getCapabilities && track.getCapabilities().torch); } catch { return false; } };
  async function startCamera() {
    errBox.hidden = true;
    if (!window.isSecureContext) return showError('errInsecure');
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return showError('errOther');
    const tries = [
      { facingMode: { ideal: 'environment' }, width: { ideal: 3840 }, height: { ideal: 2160 } },
      { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } },
      { facingMode: { ideal: 'environment' } },
    ];
    let lastErr = null;
    for (const v of tries) {
      try { stream = await navigator.mediaDevices.getUserMedia({ video: v, audio: false }); break; } catch (e) {
        lastErr = e;
        if (e && (e.name === 'NotAllowedError' || e.name === 'SecurityError' || e.name === 'NotFoundError')) break;
      }
    }
    if (closed) { stopStream(); return; }
    if (!stream) {
      const n = lastErr && lastErr.name;
      return showError(n === 'NotAllowedError' || n === 'SecurityError' ? 'errDenied' : n === 'NotFoundError' || n === 'OverconstrainedError' ? 'errNoCam' : n === 'NotReadableError' ? 'errBusy' : 'errOther');
    }
    track = stream.getVideoTracks()[0]; stats.streamAt = performance.now();
    try { // continuous autofocus where the browser exposes it (Chrome Android)
      const caps = track.getCapabilities ? track.getCapabilities() : {};
      if (caps.focusMode && caps.focusMode.includes('continuous')) await track.applyConstraints({ advanced: [{ focusMode: 'continuous' }] });
    } catch { /* optional */ }
    torchBtn.hidden = !hasTorch();
    track.addEventListener('ended', () => { if (!closed && !document.hidden) restart(); });
    video.srcObject = stream;
    try { await video.play(); } catch { /* autoplay with muted+playsinline normally succeeds */ }
    await new Promise((res) => (video.videoWidth ? res() : video.addEventListener('loadedmetadata', res, { once: true })));
    const st = track.getSettings ? track.getSettings() : {};
    root.dataset.res = `${video.videoWidth}x${video.videoHeight}`;
    stats.settings = { width: st.width, height: st.height, frameRate: st.frameRate, facingMode: st.facingMode, video: root.dataset.res };
    shutter.disabled = false;
    layoutGhost();
    startGuide();
  }
  function stopStream() { if (stream) stream.getTracks().forEach((t) => t.stop()); stream = null; track = null; }
  async function restart() { analysing = false; stopStream(); await startCamera(); }

  async function startGuide() {
    if (workerState !== 'ready') { setStatus(workerState === 'failed' ? '' : L.preparing); setHint('place', L.placeSub); }
    const w = getWorker();
    const st = await whenWorker();
    if (closed) return;
    if (st !== 'ready' || !w) { setStatus(''); setHint('guideOff'); root.dataset.guide = 'off'; levelEl.hidden = true; return; }
    setStatus(''); root.dataset.guide = 'on'; stats.firstReadyAt = Math.round(performance.now()); stats.workerLoadMs = workerLoadMs;
    w.removeEventListener('message', onWorkerMessage); w.addEventListener('message', onWorkerMessage);
    analysing = true; inFlight = false; schedule();
  }

  function showError(key) {
    analysing = false; stopStream();
    $('.gc__error-text').textContent = L[key];
    errBox.hidden = false; root.classList.add('is-error');
    $('[data-act="retry"]').hidden = key === 'errInsecure' || key === 'errNoCam';
    setHint(''); setStatus(''); root.dataset.state = 'error'; root.dataset.error = key;
  }

  // ---------------------------------------------------------------- capture
  async function grab() {
    // The video frame of the good moment is kept first (native video resolution). Where the browser can take a real
    // still (ImageCapture.takePhoto, Chrome on Android: full sensor size, often 3-4x the pixels), that photo wins.
    const vw = video.videoWidth, vh = video.videoHeight;
    const c = document.createElement('canvas'); c.width = vw; c.height = vh;
    c.getContext('2d').drawImage(video, 0, 0, vw, vh);
    stats.captureSource = `video ${vw}x${vh}`; stats.label = track && track.label;
    if (typeof window.ImageCapture === 'function' && track && !/fake|virtual|obs/i.test(track.label || '')) {
      try {
        const ic = new window.ImageCapture(track);
        const caps = await Promise.race([ic.getPhotoCapabilities(), new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), 600))]);
        const w = caps && caps.imageWidth && caps.imageWidth.max;
        if (w && w > Math.max(vw, vh) * 1.2) {
          const b = await Promise.race([ic.takePhoto(), new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), 2500))]);
          if (b && b.size > 50000 && /jpeg/.test(b.type)) { stats.captureSource = `takePhoto ${w}`; return b; }
        }
      } catch { /* keep the video frame */ }
    }
    return new Promise((res) => c.toBlob(res, 'image/jpeg', CFG.jpegQuality));
  }
  async function capture(auto) {
    if (capturing || closed || !stream) return;
    capturing = true; holdStart = 0;
    const flash = $('.gc__flash'); flash.classList.remove('is-on'); void flash.offsetWidth; flash.classList.add('is-on');
    try { if (navigator.vibrate) navigator.vibrate(15); } catch { /* ignore */ }
    let blob = null;
    try { blob = await grab(); } catch { blob = null; }
    capturing = false;
    if (!blob || closed) return;
    analysing = false; clearTimeout(pumpTimer);
    reviewBlob = blob; if (reviewUrl) URL.revokeObjectURL(reviewUrl);
    reviewUrl = URL.createObjectURL(blob); reviewImg.src = reviewUrl;
    review.hidden = false; root.classList.add('is-review'); root.dataset.state = 'review'; root.dataset.auto = auto ? '1' : '0';
    stats.capturedAt = Math.round(performance.now()); stats.capturedBytes = blob.size; stats.auto = !!auto;
    setHint('');
    hintBox.setAttribute('aria-label', L.taken);
    setTimeout(() => $('[data-act="use"]').focus({ preventScroll: true }), 50);
  }
  function retake() {
    review.hidden = true; root.classList.remove('is-review'); reviewImg.removeAttribute('src');
    if (reviewUrl) URL.revokeObjectURL(reviewUrl); reviewUrl = null; reviewBlob = null;
    cooldownUntil = performance.now() + CFG.retakeCooldownMs; holdStart = 0; candidate = null; shownKey = '';
    if (workerState === 'ready' && stream) { analysing = true; schedule(); } else setHint(workerState === 'failed' ? 'guideOff' : 'place');
  }
  function use() {
    if (!reviewBlob) return;
    const d = new Date(), p = (n) => String(n).padStart(2, '0');
    const name = `crackwatch-${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}.jpg`;
    const file = new File([reviewBlob], name, { type: 'image/jpeg' });
    close(false); onPhoto(file);
  }

  // ---------------------------------------------------------------- events
  root.addEventListener('click', async (e) => {
    const b = e.target.closest('[data-act]'); if (!b) return;
    const a = b.dataset.act;
    if (a === 'close') close(true);
    else if (a === 'shutter') capture(false);
    else if (a === 'library') { fileIn.value = ''; fileIn.click(); }
    else if (a === 'retake') retake();
    else if (a === 'use') use();
    else if (a === 'retry') { root.classList.remove('is-error'); await startCamera(); }
    else if (a === 'torch' && track) {
      try { await track.applyConstraints({ advanced: [{ torch: !torchOn }] }); torchOn = !torchOn; } catch { /* unsupported */ }
      torchBtn.setAttribute('aria-pressed', String(torchOn)); torchBtn.setAttribute('aria-label', torchOn ? L.torchOff : L.torchOn);
    }
  });
  fileIn.addEventListener('change', () => { const f = fileIn.files && fileIn.files[0]; if (f) { close(false); onPhoto(f); } });
  const onKey = (e) => { if (e.key === 'Escape') { e.preventDefault(); if (!review.hidden) retake(); else close(true); } };
  document.addEventListener('keydown', onKey);
  const onVis = () => {
    if (closed) return;
    if (document.hidden) { analysing = false; clearTimeout(pumpTimer); holdStart = 0; }
    else if (!track || track.readyState === 'ended') restart();
    else if (review.hidden && workerState === 'ready') { analysing = true; schedule(); }
  };
  document.addEventListener('visibilitychange', onVis);
  const onPageHide = () => close(true);
  window.addEventListener('pagehide', onPageHide);
  // rotation rate helps "Hold still" where it needs no permission prompt (Android); iOS would ask, so it is skipped
  const onMotion = (e) => { const r = e.rotationRate; if (r) motionRate = Math.max(Math.abs(r.alpha || 0), Math.abs(r.beta || 0), Math.abs(r.gamma || 0)); };
  const useMotion = typeof DeviceMotionEvent !== 'undefined' && typeof DeviceMotionEvent.requestPermission !== 'function';
  if (useMotion) window.addEventListener('devicemotion', onMotion);
  // orientation (level before a card is seen): free on Android; on iOS it needs a permission that can only be asked
  // from a tap, so it is requested right away (we are still inside the tap that opened the camera) and skipped if refused
  let orientOn = false;
  const DOE = typeof DeviceOrientationEvent !== 'undefined' ? DeviceOrientationEvent : null;
  if (DOE && typeof DOE.requestPermission === 'function') {
    try { DOE.requestPermission().then((r) => { if (r === 'granted' && !closed) { window.addEventListener('deviceorientation', onOrient); orientOn = true; } }).catch(() => {}); } catch { /* no gesture */ }
  } else if (DOE) { window.addEventListener('deviceorientation', onOrient); orientOn = true; }

  function close(cancelled) {
    if (closed) return;
    closed = true; analysing = false; clearTimeout(pumpTimer); cancelAnimationFrame(raf);
    stopStream(); video.srcObject = null;
    if (worker) worker.removeEventListener('message', onWorkerMessage);
    ro.disconnect();
    document.removeEventListener('keydown', onKey); document.removeEventListener('visibilitychange', onVis);
    window.removeEventListener('pagehide', onPageHide); if (useMotion) window.removeEventListener('devicemotion', onMotion);
    if (orientOn) window.removeEventListener('deviceorientation', onOrient);
    if (reviewUrl) URL.revokeObjectURL(reviewUrl);
    document.documentElement.style.overflow = prevOverflow;
    root.classList.remove('is-open'); root.classList.add('is-closing');
    setTimeout(() => root.remove(), 220);
    if (cancelled) onCancel();
  }

  getWorker();   // start loading OpenCV.js now, in parallel with the camera permission prompt
  raf = requestAnimationFrame(tick);
  setTimeout(() => $('[data-act="close"]').focus({ preventScroll: true }), 30);
  startCamera();
  return { close: () => close(true) };
}

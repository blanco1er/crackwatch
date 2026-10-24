/* CrackWatch guided camera worker: loads OpenCV.js (pinned 4.12.0, checksum-verified) off the main thread and analyses
   small RGBA frames. Messages in:  {type:'frame', id, w, h, buf (transferred ArrayBuffer)}
                       out: {type:'progress', pct} | {type:'ready', loadMs} | {type:'fail', error} | {type:'result', id, ...detect(), buf} */
'use strict';
const t0 = performance.now();
let detector = null;

function fail(e) { self.postMessage({ type: 'fail', error: String((e && e.message) || e) }); }

// OpenCV.js 4.12.0 (@techstark/opencv-js 4.12.0-release.1, dist/opencv.js, 10 872 779 bytes): from jsDelivr's CDN
// first (fast everywhere), then our own copy. Whatever the source, the bytes must match this SHA-256 before they run
// (importScripts has no integrity check, so the file is fetched, hashed, then run from a Blob URL).
const CV_SHA256 = 'bd0c3e6448043de04f6a64a12cb7b759f78c3ab8f7c35c9f2e0f71c88bb17103';
const CV_SIZE = 10872779;
const CV_SOURCES = ['https://cdn.jsdelivr.net/npm/@techstark/opencv-js@4.12.0-release.1/dist/opencv.js', '/vendor/opencv-4.12.0.js'];
let lastPct = -1;
function progress(done) {
  const pct = Math.min(99, Math.floor((100 * done) / CV_SIZE));
  if (pct >= lastPct + 5) { lastPct = pct; self.postMessage({ type: 'progress', pct }); }
}
async function fetchVerified(url) {
  const r = await fetch(url, { mode: 'cors', credentials: 'omit' });
  if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`);
  const reader = r.body.getReader(); const parts = []; let n = 0;
  for (;;) { const { done, value } = await reader.read(); if (done) break; parts.push(value); n += value.length; progress(n); }
  const buf = new Uint8Array(n); let o = 0; for (const p of parts) { buf.set(p, o); o += p.length; }
  const h = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', buf)), (b) => b.toString(16).padStart(2, '0')).join('');
  if (h !== CV_SHA256) throw new Error('OpenCV.js checksum mismatch');
  return buf;
}
async function loadOpenCv() {
  let lastErr = null;
  for (const url of CV_SOURCES) {
    try {
      const buf = await fetchVerified(url);
      const blobUrl = URL.createObjectURL(new Blob([buf], { type: 'text/javascript' }));
      importScripts(blobUrl, '/camera-detect.js');
      URL.revokeObjectURL(blobUrl);
      self.postMessage({ type: 'progress', pct: 100, source: url.startsWith('https:') ? 'cdn' : 'self' });
      return true;
    } catch (e) { lastErr = e; lastPct = -1; }
  }
  fail(lastErr || 'OpenCV.js unavailable');
  return false;
}

function boot(cv) {
  try {
    detector = self.CWDetect.create(cv);
    self.postMessage({ type: 'ready', loadMs: Math.round(performance.now() - t0) });
  } catch (e) { fail(e); }
}

loadOpenCv().then((ok) => {
  if (!ok || !self.cv) return ok && fail('OpenCV.js did not define cv');
  const cv = self.cv;
  if (typeof cv.then === 'function' && !cv.Mat) cv.then((m) => boot(m), fail);
  else if (cv.Mat) boot(cv);
  else cv.onRuntimeInitialized = () => boot(cv);
});

self.onmessage = (ev) => {
  const m = ev.data;
  if (m.type !== 'frame') return;
  if (!detector) { self.postMessage({ type: 'result', id: m.id, card: null, skipped: true, buf: m.buf }, [m.buf]); return; }
  let r;
  try { r = detector.detect(new Uint8Array(m.buf), m.w, m.h); } catch (e) { r = { card: null, error: String(e && e.message || e) }; }
  self.postMessage({ type: 'result', id: m.id, ...r, buf: m.buf }, [m.buf]);
};

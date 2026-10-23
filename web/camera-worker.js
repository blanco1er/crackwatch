/* CrackWatch guided camera worker: loads OpenCV.js (pinned 4.12.0, served gzip) off the main thread and analyses
   small RGBA frames. Messages in:  {type:'frame', id, w, h, buf (transferred ArrayBuffer)}
                       out: {type:'ready', loadMs} | {type:'fail', error} | {type:'result', id, ...detect(), buf} */
'use strict';
const t0 = performance.now();
let detector = null;

function fail(e) { self.postMessage({ type: 'fail', error: String((e && e.message) || e) }); }

try {
  importScripts('/vendor/opencv-4.12.0.js', '/camera-detect.js');
} catch (e) { fail(e); }

function boot(cv) {
  try {
    detector = self.CWDetect.create(cv);
    self.postMessage({ type: 'ready', loadMs: Math.round(performance.now() - t0) });
  } catch (e) { fail(e); }
}

if (self.cv) {
  const cv = self.cv;
  if (typeof cv.then === 'function' && !cv.Mat) cv.then((m) => boot(m), fail);
  else if (cv.Mat) boot(cv);
  else cv.onRuntimeInitialized = () => boot(cv);
}

self.onmessage = (ev) => {
  const m = ev.data;
  if (m.type !== 'frame') return;
  if (!detector) { self.postMessage({ type: 'result', id: m.id, card: null, skipped: true, buf: m.buf }, [m.buf]); return; }
  let r;
  try { r = detector.detect(new Uint8Array(m.buf), m.w, m.h); } catch (e) { r = { card: null, error: String(e && e.message || e) }; }
  self.postMessage({ type: 'result', id: m.id, ...r, buf: m.buf }, [m.buf]);
};

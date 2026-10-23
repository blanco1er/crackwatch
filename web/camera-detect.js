/* CrackWatch guided camera: live card detection on small frames (runs in camera-worker.js, also loadable in Node
   for tests). It only GUIDES framing; the measurement itself is done on the server on the full-resolution photo.

   Two references are recognised:
   - the printed ChArUco card (A6 5x7 15 mm, ids 0-16; A5 7x10 17 mm, ids 20-54; DICT_5X5_100, same layout as
     crackwatch/card.py) -> ArUco markers -> homography board(mm) -> image;
   - a wallet card (ISO/IEC 7810 ID-1, 85.60 x 53.98 mm) -> plain contour / convex-quad search, rectified aspect ~1.586.

   detect(rgba, w, h) returns { card: null | {kind, spec, quad, H, tiltDeg, tiltX, tiltY, pxPerMm, markers}, luma, motion, ms }.
   quad = 4 image points (frame px, clockwise from top-left) of the outline to draw: the checkerboard (+2 mm) for the
   ChArUco card, the card itself for a wallet card. pxPerMm is in FRAME pixels (caller rescales to the photo). */
(function (root) {
  'use strict';

  const CARDS = [
    { name: 'A6', sx: 5, sy: 7, sq: 15.0, mk: 11.0, first: 0, paper: [-15.0, -15.0, 90.0, 133.0] },
    { name: 'A5', sx: 7, sy: 10, sq: 17.0, mk: 12.5, first: 20, paper: [-14.5, -14.0, 133.5, 196.0] },
  ];
  // marker id -> 4 corners in board mm (TL, TR, BR, BL), markers sit in squares where (row + col) is odd
  for (const c of CARDS) {
    c.obj = new Map(); let id = c.first;
    for (let r = 0; r < c.sy; r++) for (let q = 0; q < c.sx; q++) {
      if ((r + q) % 2 !== 1) continue;
      const cx = (q + 0.5) * c.sq, cy = (r + 0.5) * c.sq, m = c.mk / 2;
      c.obj.set(id++, [[cx - m, cy - m], [cx + m, cy - m], [cx + m, cy + m], [cx - m, cy + m]]);
    }
    c.centre = [c.sx * c.sq / 2, c.sy * c.sq / 2];
  }
  const ID1 = { w: 85.60, h: 53.98 };
  const ID1_ASPECT = ID1.w / ID1.h; // 1.586

  function applyH(H, x, y) {
    const d = H[6] * x + H[7] * y + H[8];
    return [(H[0] * x + H[1] * y + H[2]) / d, (H[3] * x + H[4] * y + H[5]) / d];
  }
  // sqrt|det J| of the homography at a board point: image px per mm there
  function localScale(H, x, y) {
    const e = 0.5, p0 = applyH(H, x, y), px = applyH(H, x + e, y), py = applyH(H, x, y + e);
    const a = (px[0] - p0[0]) / e, b = (py[0] - p0[0]) / e, c = (px[1] - p0[1]) / e, d = (py[1] - p0[1]) / e;
    return Math.sqrt(Math.abs(a * d - b * c));
  }
  // same model as crackwatch/measure.py tilt_from_homography: f = 0.85 * max(w, h), centred principal point
  function tiltDeg(H, w, h) {
    const f = 0.85 * Math.max(w, h), cx = w / 2 - 0.5, cy = h / 2 - 0.5;
    const col = (j) => { const X = H[j], Y = H[3 + j], Z = H[6 + j]; return [(X - cx * Z) / f, (Y - cy * Z) / f, Z]; };
    const norm = (v) => { const n = Math.hypot(v[0], v[1], v[2]); return [v[0] / n, v[1] / n, v[2] / n]; };
    const r1 = norm(col(0)), r2 = norm(col(1));
    const n = [r1[1] * r2[2] - r1[2] * r2[1], r1[2] * r2[0] - r1[0] * r2[2], r1[0] * r2[1] - r1[1] * r2[0]];
    const sg = n[2] < 0 ? -1 : 1, N = Math.hypot(n[0], n[1], n[2]);
    const c = Math.min(1, Math.abs(n[2]) / N);
    // components: wall normal leaning left/right (x) and up/down (y) in the camera frame, for the live level
    return { deg: Math.acos(c) * 180 / Math.PI,
             x: Math.atan2(sg * n[0], Math.abs(n[2])) * 180 / Math.PI, y: Math.atan2(sg * n[1], Math.abs(n[2])) * 180 / Math.PI };
  }
  function tiltOf(H, w, h) { const t = tiltDeg(H, w, h); return { tiltDeg: t.deg, tiltX: t.x, tiltY: t.y }; }
  function orderQuad(pts) {   // clockwise from the top-left (smallest x + y), image coords (y down)
    const c = pts.reduce((a, p) => [a[0] + p[0] / pts.length, a[1] + p[1] / pts.length], [0, 0]);
    const s = pts.slice().sort((p, q) => Math.atan2(p[1] - c[1], p[0] - c[0]) - Math.atan2(q[1] - c[1], q[0] - c[0]));
    let k = 0; s.forEach((p, i) => { if (p[0] + p[1] < s[k][0] + s[k][1]) k = i; });
    return s.slice(k).concat(s.slice(0, k));
  }
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);

  function create(cv) {
    const dict = cv.getPredefinedDictionary(cv.DICT_5X5_100);
    const REFINE = root.CW_REFINE != null ? root.CW_REFINE : 1; // 1 = CORNER_REFINE_SUBPIX
    const mkDetector = (win) => {
      const p = new cv.aruco_DetectorParameters();
      p.adaptiveThreshWinSizeMin = win; p.adaptiveThreshWinSizeMax = win; p.adaptiveThreshWinSizeStep = 10;
      p.minMarkerPerimeterRate = 0.02;  // markers are small in a 640 px frame
      p.cornerRefinementMethod = REFINE; p.cornerRefinementWinSize = 3; // sub-pixel corners: steadier tilt
      return new cv.aruco_ArucoDetector(dict, p, new cv.aruco_RefineParameters(10, 3, true));
    };
    // one threshold window per frame (fast, ~30 ms at 360x640 on a laptop); alternate when the card is lost
    const detectors = [mkDetector(7), mkDetector(15)];
    let turn = 0;
    let rgba = null, gray = null, small = null, prevSmall = null, diff = null;
    const blur = new cv.Mat(), edges = new cv.Mat(), kernel = cv.Mat.ones(3, 3, cv.CV_8U);

    function ensure(w, h) {
      if (rgba && rgba.cols === w && rgba.rows === h) return;
      [rgba, gray, small, prevSmall, diff].forEach((m) => m && m.delete());
      rgba = new cv.Mat(h, w, cv.CV_8UC4); gray = new cv.Mat(); small = new cv.Mat(); prevSmall = null; diff = new cv.Mat();
    }

    function charuco(w, h) {
      const det = detectors[turn];
      const corners = new cv.MatVector(), ids = new cv.Mat(), rej = new cv.MatVector();
      let out = null;
      try {
        det.detectMarkers(gray, corners, ids, rej);
        const n = ids.rows;
        if (!n) { turn = (turn + 1) % detectors.length; return null; }
        const idv = ids.data32S;
        // pick the card family with the most markers
        let best = null;
        for (const c of CARDS) {
          const k = Array.from(idv).filter((i) => c.obj.has(i)).length;
          if (k && (!best || k > best.k)) best = { c, k };
        }
        if (!best || best.k < 3) return null;
        const obj = [], img = [];
        for (let i = 0; i < n; i++) {
          const o = best.c.obj.get(idv[i]); if (!o) continue;
          const p = corners.get(i).data32F;
          for (let j = 0; j < 4; j++) { obj.push(o[j][0], o[j][1]); img.push(p[2 * j], p[2 * j + 1]); }
        }
        const om = cv.matFromArray(obj.length / 2, 1, cv.CV_32FC2, obj), im = cv.matFromArray(img.length / 2, 1, cv.CV_32FC2, img);
        const Hm = cv.findHomography(om, im, cv.RANSAC, 3);
        om.delete(); im.delete();
        if (Hm.rows === 3) {
          const H = Array.from(Hm.data64F); const s = H[8]; for (let i = 0; i < 9; i++) H[i] /= s;
          // outline = the printed checkerboard + 2 mm (exact on every print; the paper's cut edge is not)
          const [x0, y0, x1, y1] = [-2, -2, best.c.sx * best.c.sq + 2, best.c.sy * best.c.sq + 2];
          const quad = [applyH(H, x0, y0), applyH(H, x1, y0), applyH(H, x1, y1), applyH(H, x0, y1)];
          out = { kind: 'charuco', spec: best.c.name, markers: best.k, quad, H,
                  pxPerMm: localScale(H, best.c.centre[0], best.c.centre[1]), ...tiltOf(H, w, h) };
        }
        Hm.delete();
      } finally { corners.delete(); ids.delete(); rej.delete(); }
      return out;
    }

    function wallet(w, h) {
      // edges of the blurred frame, closed so that a card on a busy wall still gives one outer contour
      cv.GaussianBlur(gray, blur, new cv.Size(5, 5), 0);
      cv.Canny(blur, edges, 40, 110);
      cv.dilate(edges, edges, kernel);
      const contours = new cv.MatVector(), hier = new cv.Mat();
      cv.findContours(edges, contours, hier, cv.RETR_LIST, cv.CHAIN_APPROX_SIMPLE);
      const area = w * h; let best = null;
      for (let i = 0; i < contours.size(); i++) {
        const c = contours.get(i);
        const a = Math.abs(cv.contourArea(c));
        if (a < 0.015 * area || a > 0.8 * area) { c.delete(); continue; }
        const approx = new cv.Mat();
        cv.approxPolyDP(c, approx, 0.03 * cv.arcLength(c, true), true);
        if (approx.rows === 4 && cv.isContourConvex(approx)) {
          const d = approx.data32S;
          const q = orderQuad([[d[0], d[1]], [d[2], d[3]], [d[4], d[5]], [d[6], d[7]]]);
          const top = dist(q[0], q[1]), right = dist(q[1], q[2]), bottom = dist(q[2], q[3]), left = dist(q[3], q[0]);
          const hz = (top + bottom) / 2, vt = (left + right) / 2;
          const aspect = Math.max(hz, vt) / Math.min(hz, vt);
          // not touching the frame border (a cut-off card is not a card)
          const inside = q.every((p) => p[0] > 3 && p[1] > 3 && p[0] < w - 4 && p[1] < h - 4);
          // opposite sides roughly parallel-ish: rejects kites and trapezoids from wall texture
          const par = Math.min(top, bottom) / Math.max(top, bottom) > 0.7 && Math.min(left, right) / Math.max(left, right) > 0.7;
          if (inside && par && Math.abs(aspect - ID1_ASPECT) / ID1_ASPECT < 0.12) {
            const score = a * (1 - Math.abs(aspect - ID1_ASPECT));
            if (!best || score > best.score) best = { q, score, landscape: hz >= vt };
          }
        }
        approx.delete(); c.delete();
      }
      contours.delete(); hier.delete();
      if (!best) return null;
      // homography card(mm) -> image, long side along the longer image side
      const q = best.q, W = ID1.w, Hh = ID1.h;
      const cw = best.landscape ? W : Hh, ch = best.landscape ? Hh : W;   // card upright or on its side
      const src = cv.matFromArray(4, 1, cv.CV_32FC2, [0, 0, cw, 0, cw, ch, 0, ch]);
      const img = cv.matFromArray(4, 1, cv.CV_32FC2, [q[0][0], q[0][1], q[1][0], q[1][1], q[2][0], q[2][1], q[3][0], q[3][1]]);
      const Hm = cv.getPerspectiveTransform(src, img);
      const H = Array.from(Hm.data64F); const s = H[8]; for (let i = 0; i < 9; i++) H[i] /= s;
      src.delete(); img.delete(); Hm.delete();
      return { kind: 'wallet', spec: 'ID-1', markers: 0, quad: q, H,
               pxPerMm: localScale(H, cw / 2, ch / 2), ...tiltOf(H, w, h) };
    }

    function detect(buf, w, h) {
      const t0 = (root.performance || Date).now();
      ensure(w, h);
      rgba.data.set(buf instanceof Uint8ClampedArray || buf instanceof Uint8Array ? buf : new Uint8Array(buf));
      cv.cvtColor(rgba, gray, cv.COLOR_RGBA2GRAY);
      // luminance + motion on a 1/4 thumbnail
      cv.resize(gray, small, new cv.Size(Math.max(1, w >> 2), Math.max(1, h >> 2)), 0, 0, cv.INTER_AREA);
      const luma = cv.mean(small)[0];
      let motion = null;
      if (prevSmall) { cv.absdiff(small, prevSmall, diff); motion = cv.mean(diff)[0]; } else prevSmall = new cv.Mat();
      small.copyTo(prevSmall);   // deep copy (Mat.clone() shares the buffer in this opencv.js build)
      let card = charuco(w, h);
      if (!card) card = wallet(w, h);
      return { card, luma, motion, w, h, ms: (root.performance || Date).now() - t0 };
    }
    return { detect };
  }

  root.CWDetect = { create, CARDS, ID1 };
})(typeof self !== 'undefined' ? self : globalThis);

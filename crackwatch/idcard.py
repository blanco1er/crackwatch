"""Wallet-card scale reference: any ISO/IEC 7810 ID-1 card (bank, transport, loyalty, gift card).

Nothing to print: the card's outline is a known 85.60 x 53.98 mm rectangle (corner radius 3.18 mm,
thickness 0.76 mm). The printed ChArUco card stays the "precision mode"; this module gives the same kind
of result (`H_img_from_board`: homography from a metric plane in mm to the image) so the rest of the
pipeline (rectification, segmentation, widths) runs unchanged.

Method
1. Candidates (downscaled copy): LSD line segments on the L, a and b channels (a card may differ from
   the wall in colour only), merged into lines; quadrilaterals = two pairs of roughly opposite lines whose
   segments cover the central part of each side and stop near the corners (a wall joint does not stop),
   with a rectified aspect ratio close to 85.60 / 53.98 for some plausible phone focal length.
2. Refinement (full resolution): along each side, excluding 3.18 mm rounded corners + margin, the colour
   gradient profile across the edge gives one sub-pixel edge point every 0.5 mm; a robust (RANSAC + total
   least squares) line is fitted per side; the corners are the intersections of adjacent lines (virtual
   sharp corners of the rounded rectangle) -> exact 4-point homography to the 85.60 x 53.98 mm rectangle.
3. Uncertainty: the line-fit residuals give each line's offset/angle covariance; a Monte Carlo over the
   four lines gives the relative scale uncertainty at any point of the plane (it grows away from the card).
   Added in quadrature: ISO size tolerance and the card thickness (the outline is 0-0.76 mm in front of the
   wall). The thickness is corrected to first order: the wall plane is the card plane scaled about the
   camera's foot point by D / (D + 0.76 mm) (D = camera-card distance from the homography); the residual
   (which face edge the outline follows, seen obliquely) is budgeted.
4. Retake reasons when the card cannot give a trustworthy scale: card_not_found, card_cut_by_frame,
   card_too_small, card_too_oblique, card_occluded, card_not_flat, card_wrong_size.
5. Privacy: `redact()` pixelates + blurs the card area (card numbers) in any image returned or stored.

Board frame convention (as card.py): origin at a virtual sharp corner, x along the long side, y along the
short side, millimetres, right-handed with the image (x right / y down when facing the card).
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field, replace

import cv2
import numpy as np

ID1_W_MM, ID1_H_MM = 85.60, 53.98
ID1_CORNER_R_MM = 3.18
ID1_THICK_MM = 0.76
ID1_ASPECT = ID1_W_MM / ID1_H_MM
# ISO/IEC 7810 ID-1 tolerances: width 85.47-85.72 mm, height 53.92-54.03 mm (about +-0.15 % / +-0.10 %);
# treated as uniform -> 1 sigma ~ 0.08 % on the scale.
ISO_SIZE_REL_SIGMA = 0.0008


@dataclass(frozen=True)
class IdCardSpec:
    name: str = "ID-1"
    width_mm: float = ID1_W_MM
    height_mm: float = ID1_H_MM

    @property
    def board_mm(self):
        return (self.width_mm, self.height_mm)

    def paper_rect_in_board_frame(self):
        """The card itself (hidden from the crack search, like the ChArUco paper)."""
        return (0.0, 0.0, self.width_mm, self.height_mm)

    def to_json(self):
        return {"name": self.name, "board_mm": self.board_mm, "corner_radius_mm": ID1_CORNER_R_MM,
                "thickness_mm": ID1_THICK_MM}


ID1 = IdCardSpec()


@dataclass
class IdCardParams:
    coarse_max_side: int = 1100        # candidate search on a downscaled copy
    min_px_per_mm: float = 3.0         # card long side >= ~257 px
    max_tilt_deg: float = 40.0
    min_side_coverage: float = 0.6     # fraction of a side's central part with an inlier edge point
    max_gap_frac: float = 0.4          # longest run without edge points / side length
    max_sagitta_mm: float = 0.5        # bow of one side (bent card)
    max_edge_sigma_px: float = 3.0     # robust spread of edge points around their line (gross failures only)
    aspect_tol: float = 0.035          # |aspect / 1.586 - 1| with the best plausible focal
    corner_excl_mm: float = ID1_CORNER_R_MM + 1.7
    step_mm: float = 0.5
    max_samples_per_side: int = 180
    n_mc: int = 200
    max_scale_rel_unc: float = 0.03    # reject (retake) above 3 % (1 sigma) at the card centre
    max_corner_rms_mm: float = 0.6     # corners vs the best flat ID-1 rectangle (PnP), RMS
    # hand-held card vs wall plane (a priori, NOT fitted on photos): a card pressed by a fingertip on a rough wall
    # stands off by ~1-2 mm and tilts by ~1-2 deg (2 mm over 85 mm = 1.3 deg); the wall itself is not perfectly
    # flat between the card and the crack. Their effect on the scale grows with the distance to the card.
    standoff_mm: float = 1.5
    plane_tilt_deg: float = 1.5
    edge_sys_mm: float = 0.15          # per-edge systematic offset (shadow, worn edge, side-wall colour), 1 sigma;
                                       # calibrated on seeds 60000-60149 (scripts/calib_idcard.py), not the eval seeds
    # Focal lengths in 35 mm-equivalent mm, i.e. relative to the image DIAGONAL (43.27 mm), which stays right for
    # 4:3, 16:9 or 9:16 crops of the sensor (a "x long side" rule does not: 24 mm is 0.69 x the long side in 4:3
    # but 0.64 x in 16:9). Phone main cameras are 23-28 mm; the real photos' EXIF says 24 mm (iPhone 17 Pro Max).
    focal_35mm: float = 25.0           # prior when EXIF is missing and the card's perspective cannot tell
    focal_35mm_range: tuple = (20.0, 36.0)   # plausible (no zoom): bounds the focal estimated from the rectangle
    focal_35mm_mc: tuple = (22.0, 34.0)      # unknown focal: Monte Carlo range


RETAKE = {
    "card_not_found": "Put a bank, transport or loyalty card flat on the wall next to the crack, with the whole card "
                      "in the photo and no reflection on it (or use the printed CrackWatch card).",
    "card_cut_by_frame": "Keep the whole card inside the photo, with a small margin around it.",
    "card_too_small": "Move closer: the card should fill at least about a fifth of the photo's width.",
    "card_too_oblique": "Hold the phone parallel to the wall, facing the card.",
    "card_occluded": "Too much of the card's outline is hidden: press the centre of the card with one fingertip, so "
                     "its edges stay visible.",
    "card_not_flat": "Press the card flat against the wall with one fingertip at its centre: it must not bend or "
                     "stand off the wall.",
    "card_wrong_size": "The outline does not have bank-card proportions (85.6 x 54 mm): use a bank, transport or "
                       "loyalty card, held by one fingertip at its centre.",
}


# ------------------------------------------------------------------------------------------------ geometry
def _apply_h(H, pts):
    p = np.asarray(pts, np.float64).reshape(-1, 2)
    q = np.hstack([p, np.ones((len(p), 1))]) @ np.asarray(H, np.float64).T
    return q[:, :2] / q[:, 2:3]


def homography_4pt(src, dst):
    """Exact float64 homography mapping 4 src points to 4 dst points (DLT, h33 = 1)."""
    A, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    h = np.linalg.solve(np.array(A, np.float64), np.array(b, np.float64))
    return np.append(h, 1.0).reshape(3, 3)


def _intersect(l1, l2):
    """Lines as (n, c) with n . x = c."""
    A = np.array([l1[0], l2[0]], np.float64)
    if abs(np.linalg.det(A)) < 1e-9:
        return None
    return np.linalg.solve(A, np.array([l1[1], l2[1]], np.float64))


def _jac(H, pt):
    x, y = pt
    e = 0.05
    p = _apply_h(H, [(x, y), (x + e, y), (x, y + e)])
    return np.column_stack([(p[1] - p[0]) / e, (p[2] - p[0]) / e])


def _jac_batch(Hs, pt):
    """Jacobians d img / d mm at `pt` for a stack of homographies (n, 3, 3) -> (n, 2, 2)."""
    x, y = pt
    e = 0.05
    P = np.array([[x, y, 1.0], [x + e, y, 1.0], [x, y + e, 1.0]])
    q = np.einsum("nij,kj->nki", Hs, P)
    q = q[:, :, :2] / q[:, :, 2:3]
    return np.stack([(q[:, 1] - q[:, 0]) / e, (q[:, 2] - q[:, 0]) / e], axis=2)


def _fu(shape):
    """Pixels per mm of 35 mm-equivalent focal length for this image (diagonal / 43.27 mm)."""
    return math.hypot(shape[0], shape[1]) / 43.27


def _K(f, shape):
    h, w = shape[:2]
    return np.array([[f, 0, w / 2 - 0.5], [0, f, h / 2 - 0.5], [0, 0, 1.0]])


def focal_from_rectangle(H, shape):
    """Focal length (px) that makes the two board axes orthogonal in 3-D (Zhang & He 2007, whiteboard
    scanning), principal point at the image centre. None when the view is too frontal to tell."""
    h, w = shape[:2]
    T = np.array([[1, 0, -(w / 2 - 0.5)], [0, 1, -(h / 2 - 0.5)], [0, 0, 1.0]])
    Hc = T @ H
    h1, h2 = Hc[:, 0], Hc[:, 1]
    den = h1[2] * h2[2]
    if abs(den) < 1e-12:
        return None
    f2 = -(h1[0] * h2[0] + h1[1] * h2[1]) / den
    return math.sqrt(f2) if f2 > 0 else None


def aspect_with_focal(H_unit, f, shape):
    """Width/height ratio of the plane rectangle whose unit-square homography is H_unit, for focal f."""
    h, w = shape[:2]
    cx, cy = w / 2 - 0.5, h / 2 - 0.5
    a0, a1, a2 = H_unit[0, 0], H_unit[1, 0], H_unit[2, 0]
    b0, b1, b2 = H_unit[0, 1], H_unit[1, 1], H_unit[2, 1]
    na = ((a0 - cx * a2) / f) ** 2 + ((a1 - cy * a2) / f) ** 2 + a2 * a2
    nb = ((b0 - cx * b2) / f) ** 2 + ((b1 - cy * b2) / f) ** 2 + b2 * b2
    return float(math.sqrt(na / nb))


def pose_from_homography(H, f, shape):
    """(R, t, camera centre in board frame) for a plane homography and focal f."""
    M = np.linalg.inv(_K(f, shape)) @ H
    k = 2.0 / (np.linalg.norm(M[:, 0]) + np.linalg.norm(M[:, 1]))
    if M[2, 2] * k < 0:           # board in front of the camera
        k = -k
    r1, r2, t = M[:, 0] * k, M[:, 1] * k, M[:, 2] * k
    r3 = np.cross(r1, r2)
    U, _, Vt = np.linalg.svd(np.column_stack([r1, r2, r3]))
    R = U @ Vt
    return R, t, -R.T @ t


# ------------------------------------------------------------------------------------------------ candidates
def _segments(small_bgr):
    lab = cv2.cvtColor(small_bgr, cv2.COLOR_BGR2Lab)
    chans = [lab[:, :, 0]]
    for c in (lab[:, :, 1], lab[:, :, 2]):
        d = c.astype(np.float32) - 128.0
        k = 110.0 / max(float(np.percentile(np.abs(d), 99.5)), 6.0)
        chans.append(np.clip(128 + d * k, 0, 255).astype(np.uint8))
    lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
    segs = []
    for c in chans:
        out = lsd.detect(cv2.GaussianBlur(c, (0, 0), 0.8))[0]
        if out is not None:
            segs.append(out.reshape(-1, 4))
    return np.vstack(segs) if segs else np.zeros((0, 4), np.float32)


class _Line:
    __slots__ = ("pts", "w", "n", "c", "d", "m", "length", "intervals")

    def __init__(self, p, q):
        self.pts = [p, q, (p + q) / 2]
        L = float(np.linalg.norm(q - p))
        self.w = [L, L, 2 * L]
        self.length = L
        self._fit()
        self.intervals = []

    def _fit(self):
        P = np.array(self.pts)
        W = np.array(self.w)
        m = (P * W[:, None]).sum(0) / W.sum()
        C = ((P - m).T * W) @ (P - m)
        ev, evec = np.linalg.eigh(C)
        self.n = evec[:, 0]
        self.d = evec[:, 1]
        self.m = m
        self.c = float(self.n @ m)

    def add(self, p, q):
        L = float(np.linalg.norm(q - p))
        self.pts += [p, q, (p + q) / 2]
        self.w += [L, L, 2 * L]
        self.length += L
        self._fit()


def _merge_lines(segs, min_len, ang_tol_deg=2.5, dist_tol=1.6):
    L = np.hypot(segs[:, 2] - segs[:, 0], segs[:, 3] - segs[:, 1])
    order = np.argsort(-L)
    lines: list[_Line] = []
    ct = math.cos(math.radians(ang_tol_deg))
    nb = int(round(180.0 / ang_tol_deg))
    buckets: dict = {}                       # angle bin -> lines (only neighbouring bins are compared)

    def abin(d):
        return int(math.degrees(math.atan2(d[1], d[0])) % 180.0 / ang_tol_deg) % nb
    for i in order:
        if L[i] < min_len:
            break
        p, q = segs[i, :2].astype(np.float64), segs[i, 2:].astype(np.float64)
        d = (q - p) / L[i]
        b = abin(d)
        hit = None
        for bb in ((b - 1) % nb, b, (b + 1) % nb):
            for ln in buckets.get(bb, ()):
                if abs(float(d @ ln.d)) >= ct and abs(ln.n @ p - ln.c) < dist_tol and abs(ln.n @ q - ln.c) < dist_tol:
                    hit = ln
                    break
            if hit is not None:
                break
        if hit is not None:
            hit.add(p, q)
        else:
            ln = _Line(p, q)
            lines.append(ln)
            buckets.setdefault(b, []).append(ln)
    for ln in lines:            # covered intervals along the (final) line direction
        P = np.array(ln.pts).reshape(-1, 3, 2)[:, :2]
        iv = sorted(tuple(sorted((float(ln.d @ a), float(ln.d @ b)))) for a, b in P)
        merged = []
        for a, b in iv:
            if merged and a <= merged[-1][1] + 1.0:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        ln.intervals = [(float(a), float(b)) for a, b in merged]
    return lines


def _covered(intervals, a, b):
    """Length of [a, b] covered by the (disjoint) intervals."""
    if b <= a:
        return 0.0
    tot = 0.0
    for lo, hi in intervals:
        lo = a if lo < a else lo
        hi = b if hi > b else hi
        if hi > lo:
            tot += hi - lo
    return tot


def _convex_quad(Q):
    sgn = 0
    for s in range(4):
        (x0, y0), (x1, y1), (x2, y2) = Q[s], Q[(s + 1) % 4], Q[(s + 2) % 4]
        cr = (x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1)
        if abs(cr) < 1e-9:
            return False
        if sgn == 0:
            sgn = 1 if cr > 0 else -1
        elif (cr > 0) != (sgn > 0):
            return False
    return True


def _order_quad(Q):
    """Clockwise in image coordinates (y down), starting anywhere."""
    c = Q.mean(0)
    ang = np.arctan2(Q[:, 1] - c[1], Q[:, 0] - c[0])
    return Q[np.argsort(ang)]


def _unit_h(Q):
    return homography_4pt([(0, 0), (1, 0), (1, 1), (0, 1)], Q)


def _best_aspect(Q, shape, p: IdCardParams, strict=False):
    """Aspect (long / short side) error vs ID-1 -> (err, aspect, f). With `strict`, the focal is the one
    that makes the quad a 3-D rectangle (focal_from_rectangle) when it is plausible: then a quad with one
    wrong side cannot hide behind another focal. Otherwise (frontal view, where the aspect hardly depends
    on the focal) the error is minimised over plausible phone focals."""
    Hu = _unit_h(Q)
    S = _fu(shape)
    if strict:
        f_o = focal_from_rectangle(Hu, shape)
        if f_o is not None and p.focal_35mm_range[0] * S <= f_o <= p.focal_35mm_range[1] * S:
            a = aspect_with_focal(Hu, f_o, shape)
            a = a if a >= 1 else 1 / a
            return abs(a / ID1_ASPECT - 1), a, f_o
    best = (1e9, None, None)
    for ff in np.linspace(p.focal_35mm_range[0], p.focal_35mm_range[1], 18):
        a = aspect_with_focal(Hu, ff * S, shape)
        a = a if a >= 1 else 1 / a
        e = abs(a / ID1_ASPECT - 1)
        if e < best[0]:
            best = (e, a, ff * S)
    return best


def find_candidates(small_bgr, scale, p: IdCardParams, max_lines=64, keep=30):
    """Quadrilateral candidates (coarse image coordinates), best first: list of (score, quad, info)."""
    h, w = small_bgr.shape[:2]
    segs = _segments(small_bgr)
    if len(segs) == 0:
        return []
    short_min = ID1_H_MM * p.min_px_per_mm * scale * 0.7        # smallest acceptable short side (coarse px)
    lines = _merge_lines(segs, min_len=max(8.0, 0.25 * short_min))
    lines = [ln for ln in lines if ln.length >= 0.45 * short_min]
    lines.sort(key=lambda ln: -ln.length)
    # keep the longest lines, but at most 8 per cell of a 4 x 4 grid: a checkerboard or tiles elsewhere must not
    # use up the whole budget (the card's own sides are shorter than a printed sheet's)
    per_cell, kept = {}, []
    for ln in lines:
        cell = (min(3, int(4 * ln.m[0] / w)), min(3, int(4 * ln.m[1] / h)))
        if per_cell.get(cell, 0) >= 12:
            continue
        per_cell[cell] = per_cell.get(cell, 0) + 1
        kept.append(ln)
        if len(kept) >= max_lines:
            break
    lines = kept
    n = len(lines)
    # line-line intersections, closed form (Cramer), once
    X = [[None] * n for _ in range(n)]
    for i in range(n):
        a1, b1, c1 = float(lines[i].n[0]), float(lines[i].n[1]), lines[i].c
        for j in range(i + 1, n):
            a2, b2, c2 = float(lines[j].n[0]), float(lines[j].n[1]), lines[j].c
            det = a1 * b2 - a2 * b1
            if abs(det) > 1e-9:
                X[i][j] = X[j][i] = ((c1 * b2 - c2 * b1) / det, (a1 * c2 - a2 * c1) / det)
    D = [(float(ln.d[0]), float(ln.d[1])) for ln in lines]
    pairs = []
    for i in range(n):
        for j in range(i + 1, n):
            if abs(float(lines[i].d @ lines[j].d)) < math.cos(math.radians(30)):
                continue
            dist = abs(lines[j].n @ lines[i].m - lines[j].c)
            if dist < short_min * 0.95 or dist > 1.2 * max(h, w):
                continue
            pairs.append((i, j))
    cands = []
    for a in range(len(pairs)):
        i, j = pairs[a]
        di = lines[i].d
        for b in range(a + 1, len(pairs)):
            k, l = pairs[b]
            if len({i, j, k, l}) < 4 or abs(float(di @ lines[k].d)) > math.cos(math.radians(45)):
                continue
            idx = (i, k, j, l)
            corners = [X[idx[s]][idx[(s + 1) % 4]] for s in range(4)]
            if any(c is None for c in corners):
                continue
            lim = 0.02 * max(h, w)
            if any(x < -lim or y < -lim or x > w + lim or y > h + lim for x, y in corners):
                continue
            if not _convex_quad(corners):
                continue
            # quad side s runs from corner s to corner s+1 and lies on line idx[(s + 1) % 4]
            cov, over = [], []
            ok = True
            for s in range(4):
                li = idx[(s + 1) % 4]
                dx, dy = D[li]
                pa, pb = corners[s], corners[(s + 1) % 4]
                ta, tb = dx * pa[0] + dy * pa[1], dx * pb[0] + dy * pb[1]
                if ta > tb:
                    ta, tb = tb, ta
                Ls = tb - ta
                if Ls < short_min:
                    ok = False
                    break
                m = 0.1 * Ls
                cv_ = _covered(lines[li].intervals, ta + m, tb - m) / (Ls - 2 * m)
                if cv_ < 0.3:
                    ok = False
                    break
                cov.append(cv_)
                over.append((_covered(lines[li].intervals, ta - 0.35 * Ls, ta - 0.06 * Ls)
                             + _covered(lines[li].intervals, tb + 0.06 * Ls, tb + 0.35 * Ls)) / (0.58 * Ls))
            if not ok:
                continue
            Q = np.array(corners)
            e, asp, f = _best_aspect(Q, small_bgr.shape, p)
            if e > 0.12:
                continue
            score = float(np.mean(cov)) + 0.5 * min(cov) - 0.6 * float(np.mean(over)) - 2.0 * e
            cands.append((score, Q, {"coverage": cov, "overshoot": over, "aspect_err": e}))
    # always: one side of the card may be invisible at this scale (low-contrast edge, hand over it) while other
    # card-shaped rectangles elsewhere (a printed sheet, tiles) are complete
    cands += _three_sided_candidates(lines, pairs, small_bgr.shape, short_min, p)
    cands = [(sc, _order_quad(Q), info) for sc, Q, info in cands]
    cands.sort(key=lambda c: -c[0])
    out = []
    for sc, Q, info in cands:     # non-maximum suppression on corner positions
        if any(np.max(np.linalg.norm(_match_quad(Q, q2) - q2, axis=1)) < 0.08 * np.ptp(q2[:, 0]) for _, q2, _ in out):
            continue
        # spatial diversity: a checkerboard, tiles or a printed chart offer dozens of nested card-like rectangles;
        # at most 3 candidates per place, so the real card elsewhere in the photo is still examined
        c = Q.mean(0)
        if sum(cv2.pointPolygonTest(q2.astype(np.float32).reshape(-1, 1, 2), (float(c[0]), float(c[1])), False) >= 0
               for _, q2, _ in out) >= 3:
            continue
        out.append((sc, Q, info))
        if len(out) >= keep:
            break
    return out


def _three_sided_candidates(lines, pairs, shape, short_min, p: IdCardParams):
    """Card with one side hidden (finger over a whole short side, glare...): two opposite lines + one
    crossing line; the fourth side is rebuilt with the ID-1 rectangle constraint (recover_side)."""
    h, w = shape[:2]
    f_def = p.focal_35mm * _fu(shape)
    c45 = math.cos(math.radians(45))
    out = []
    trip = []
    for i, j in pairs:
        for k in range(len(lines)):
            if k in (i, j) or abs(float(lines[i].d @ lines[k].d)) > c45:
                continue
            trip.append((lines[i].length + lines[j].length + lines[k].length, i, j, k))
    trip.sort(key=lambda t: -t[0])
    n_rec = 0
    for _, i, j, k in trip:
        if n_rec >= 120:
            break
        if True:
            li, lj, lk = lines[i], lines[j], lines[k]
            c1 = _intersect((li.n, li.c), (lk.n, lk.c))
            c2 = _intersect((lk.n, lk.c), (lj.n, lj.c))
            if c1 is None or c2 is None:
                continue
            ta, tb = sorted((float(lk.d @ c1), float(lk.d @ c2)))
            Ls = tb - ta
            if Ls < short_min or _covered(lk.intervals, ta + 0.1 * Ls, tb - 0.1 * Ls) / (0.8 * Ls) < 0.5:
                continue
            L = [(li.n, li.c), (lk.n, lk.c), (lj.n, lj.c), None]
            n_rec += 1
            for target in (ID1_ASPECT, 1 / ID1_ASPECT):
                lm = recover_side(L, 3, f_def, shape, toward=li.m, target=target)
                if lm is None:
                    continue
                Q = _corners_from_lines(L[:3] + [lm])
                if Q is None or np.any(Q < -0.02 * max(h, w)) or np.any(Q[:, 0] > 1.02 * w) or np.any(Q[:, 1] > 1.02 * h):
                    continue
                if len(cv2.convexHull(Q.astype(np.float32))) != 4:
                    continue
                cov, over = [], []
                for s, ln in ((0, li), (1, lk), (2, lj)):
                    pa, pb = Q[s], Q[(s + 1) % 4]
                    a_, b_ = sorted((float(ln.d @ pa), float(ln.d @ pb)))
                    Ls2 = b_ - a_
                    if Ls2 < 0.6 * short_min:
                        break
                    cov.append(_covered(ln.intervals, a_ + 0.1 * Ls2, b_ - 0.1 * Ls2) / (0.8 * Ls2))
                    over.append((_covered(ln.intervals, a_ - 0.35 * Ls2, a_ - 0.06 * Ls2)
                                 + _covered(ln.intervals, b_ + 0.06 * Ls2, b_ + 0.35 * Ls2)) / (0.58 * Ls2))
                if len(cov) < 3 or min(cov) < 0.5:
                    continue
                score = float(np.mean(cov)) + 0.5 * min(cov) - 0.6 * float(np.mean(over)) - 0.35
                out.append((score, Q, {"coverage": cov + [0.0], "overshoot": over, "aspect_err": 0.0, "three_sided": True}))
    return out


def _match_quad(Q, ref):
    """Cyclic shift of Q (same orientation) closest to ref."""
    best, bd = Q, 1e18
    for s in range(4):
        q = np.roll(Q, s, axis=0)
        d = float(np.sum((q - ref) ** 2))
        if d < bd:
            best, bd = q, d
    return best


# ------------------------------------------------------------------------------------------------ refinement
def _fit_line(P, tau0):
    """Robust line: RANSAC then iterated total least squares. -> (n, c, inlier mask) or None."""
    nP = len(P)
    if nP < 8:
        return None
    rng = np.random.default_rng(12345)
    best, best_cnt = None, -1
    span = np.ptp(P, axis=0).max()
    for _ in range(120):
        i, j = rng.choice(nP, 2, replace=False)
        d = P[j] - P[i]
        L = float(np.hypot(*d))
        if L < 0.25 * span:
            continue
        n = np.array([-d[1], d[0]]) / L
        r = np.abs(P @ n - n @ P[i])
        cnt = int((r < tau0).sum())
        if cnt > best_cnt:
            best, best_cnt = r < tau0, cnt
    if best is None or best_cnt < 6:
        return None
    inl = best
    for _ in range(4):
        m = P[inl].mean(0)
        ev, evec = np.linalg.eigh(np.cov((P[inl] - m).T))
        n = evec[:, 0]
        c = float(n @ m)
        r = P @ n - c
        s = 1.4826 * float(np.median(np.abs(r[inl]))) + 1e-6
        # a straight card edge does not scatter by more than ~2 px: wider points are a chip in the card, a
        # texture grain or a finger outline, not the edge (capping keeps them from bending the line)
        new = np.abs(r) <= max(0.6, min(3.0 * s, 2.0))
        if new.sum() < 6:
            break
        if np.array_equal(new, inl):
            break
        inl = new
    return n, c, inl


def _edge_points(img, offset, H, side, p: IdCardParams, half_win_px, ppm, skin=None):
    """Sub-pixel edge points along one side of the card (board mm -> image via H)."""
    W, Hh = ID1_W_MM, ID1_H_MM
    a, b = [((0, 0), (W, 0)), ((W, 0), (W, Hh)), ((W, Hh), (0, Hh)), ((0, Hh), (0, 0))][side]
    a, b = np.array(a, float), np.array(b, float)
    L = float(np.linalg.norm(b - a))
    e = p.corner_excl_mm
    n_s = int(min(p.max_samples_per_side, max(12, (L - 2 * e) / p.step_mm)))
    u = np.linspace(e, L - e, n_s)
    pts_mm = a + (b - a)[None, :] * (u / L)[:, None]
    pim = _apply_h(H, pts_mm)
    tan = _apply_h(H, pts_mm + (b - a) / L * 0.5) - pim
    tan /= np.linalg.norm(tan, axis=1, keepdims=True)
    nrm = np.column_stack([tan[:, 1], -tan[:, 0]])       # outward for a clockwise board (x right, y down)
    ctr = _apply_h(H, [(W / 2, Hh / 2)])[0]
    if np.mean(np.sum((pim - ctr) * nrm, axis=1)) < 0:
        nrm = -nrm
    step = 0.25
    t = np.arange(-half_win_px, half_win_px + 1e-9, step, dtype=np.float32)
    mx = (pim[:, 0:1] - offset[0] + nrm[:, 0:1] * t[None, :]).astype(np.float32)
    my = (pim[:, 1:2] - offset[1] + nrm[:, 1:2] * t[None, :]).astype(np.float32)
    prof = cv2.remap(img, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    if prof.ndim == 2:
        prof = prof[:, :, None]
    d = np.gradient(prof, step, axis=1)
    E = np.sqrt((d ** 2).sum(-1))
    k = np.argmax(E, axis=1)
    rows = np.arange(len(k))
    good = (k > 0) & (k < len(t) - 1)
    k1 = np.clip(k, 1, len(t) - 2)
    y0, y1, y2 = E[rows, k1 - 1], E[rows, k1], E[rows, k1 + 1]
    den = y0 - 2 * y1 + y2
    with np.errstate(divide="ignore", invalid="ignore"):
        frac = np.where(np.abs(den) > 1e-9, 0.5 * (y0 - y2) / den, 0.0)
    frac = np.clip(frac, -0.5, 0.5)
    tpk = t[k1] + frac * step
    peak = E[rows, k1]
    good &= (peak >= 1.5 * np.median(E, axis=1)) & (peak >= 2.0) & (peak >= 0.35 * np.median(peak))
    # clipping shifts the gradient peak only when the edge's mid-level itself is clipped (a saturated card face
    # next to a darker wall is fine): drop samples whose profile is near saturation AT the peak
    # Clipping: a blurred step keeps its steepest point (the edge) as long as its mid-level is below the clip
    # level, i.e. when the value at the gradient peak is clearly below saturation. When the bright plateau is
    # clipped AND the peak sits close to the clip (strong over-exposure), the observed edge is pulled to the
    # dark side: such channels do not count, and a sample whose gradient comes mostly from them is dropped.
    kk = np.arange(len(t))[None, :]
    near = (np.abs(kk - k1[:, None]) <= int(3.0 / step))[..., None]
    v_pk = prof[rows, k1]                                                       # (n, C)
    hi_clip = ((prof >= 250.0) & near).any(axis=1) & (v_pk > 235.0)
    lo_clip = ((prof <= 3.0) & near).any(axis=1) & (v_pk < 20.0)
    clipped = hi_clip | lo_clip
    d_pk = d[rows, k1] ** 2
    good &= (d_pk * ~clipped).sum(1) >= 0.5 * d_pk.sum(1)
    on_skin = np.zeros(len(k), bool)
    if skin is not None:
        # `skin` is the occluder mask (finger, hand: see occluder_mask): a sample whose profile touches it is not
        # the card's edge and is left out; the side is fitted on its visible parts only
        sk = cv2.remap(skin, mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        on_skin = sk.max(axis=1) > 0.5
        good &= ~on_skin
    P = pim + nrm * tpk[:, None]
    return {"P": P, "pim": pim, "good": good, "skin": on_skin, "u_mm": u, "L_mm": L, "n_img": nrm, "t": t, "prof": prof, "k": k1, "peak": peak}


def _blur_from_profiles(prof, t, k, good):
    """Edge blur sigma (px) from colour step profiles: sigma = contrast / (peak gradient * sqrt(2 pi))."""
    sig = []
    for i in np.nonzero(good)[0]:
        pr = prof[i]                                     # (T, C)
        n = len(t)
        c = k[i]
        lo = pr[max(0, c - int(4 / 0.25)):max(1, c - int(2.5 / 0.25))].mean(0) if c > 12 else pr[:4].mean(0)
        hi = pr[min(n - 1, c + int(2.5 / 0.25)):min(n, c + int(4 / 0.25))].mean(0) if c < n - 12 else pr[-4:].mean(0)
        dv = hi - lo
        C = float(np.linalg.norm(dv))
        if C < 8:
            continue
        s = pr @ (dv / C)
        G = float(np.max(np.gradient(s, 0.25)))
        if G > 0:
            sig.append(C / (G * math.sqrt(2 * math.pi)))
    return float(np.median(sig)) if len(sig) >= 10 else None


def _side_stats(ep, fit, ppm):
    n, c, inl = fit
    P = ep["P"][ep["good"]]
    u = ep["u_mm"][ep["good"]]
    r = P @ n - c
    ri, ui = r[inl], u[inl]
    nin = int(inl.sum())
    span = ep["L_mm"] - 2 * (ep["u_mm"][0])
    # coverage counts inliers whose edge is about as strong as the side's own edge: weak texture gradients that
    # happen to line up with a wrong (or partly missing) side must not count as support
    pk = ep["peak"][ep["good"]][inl]
    strong = pk >= 0.2 * float(np.percentile(pk, 90)) if nin else np.zeros(0, bool)
    cover = int(strong.sum()) / max(1, len(ep["u_mm"]))
    us = np.sort(np.concatenate([[ep["u_mm"][0]], ui[strong], [ep["u_mm"][-1]]]))
    gap = float(np.max(np.diff(us))) / max(span, 1e-6)
    rms = float(np.sqrt(np.mean(ri ** 2)))
    rob = 1.4826 * float(np.median(np.abs(ri)))
    inl_span = float(np.ptp(ui) / max(span, 1e-6)) if nin >= 2 else 0.0
    # bow: quadratic term of the residuals along the side
    sag, sag_sig = 0.0, 0.0
    if nin >= 12:
        x = (ui - ui.mean()) / max(np.ptp(ui) / 2, 1e-6)
        A = np.column_stack([np.ones_like(x), x, x * x - np.mean(x * x)])
        coef, *_ = np.linalg.lstsq(A, ri, rcond=None)
        res = ri - A @ coef
        s2 = float(res @ res) / max(1, nin - 3)
        cov = s2 * np.linalg.inv(A.T @ A)
        sag = float(abs(coef[2]) / ppm)            # mm, max deviation from the chord ~ |c2| * 1
        sag_sig = float(math.sqrt(cov[2, 2]) / ppm)
    return {"n_samples": int(len(ep["u_mm"])), "n_inliers": nin, "coverage": round(cover, 3), "max_gap_frac": round(gap, 3),
            "skin_frac": round(float(np.mean(ep["skin"])), 3), "occ_frac": round(float(np.mean(ep["skin"])), 3),
            "skin_inl": round(float(np.mean(ep["skin"][ep["good"]][inl])) if nin else 0.0, 3),
            "inl_span_frac": round(inl_span, 3),
            "rms_px": round(rms, 3), "robust_sigma_px": round(rob, 3), "sagitta_mm": round(sag, 3),
            "sagitta_sigma_mm": round(sag_sig, 3), "_inl_P": P[inl], "_inl_u": ui, "_res": ri}


def _canonical(Q, shape, p):
    """Order the 4 corners as board (0,0), (W,0), (W,H), (0,H): long side first, clockwise in the image
    (right-handed with y down), x axis pointing as much to the image right as possible."""
    Q = _order_quad(Q)
    e, asp, f = _best_aspect(Q, shape, p)
    Hu = _unit_h(Q)
    a = aspect_with_focal(Hu, f, shape)
    if a < 1:
        Q = np.roll(Q, -1, axis=0)
    d = Q[1] - Q[0]
    if d[0] < 0 or (abs(d[0]) < 1e-9 and d[1] < 0):
        Q = np.roll(Q, 2, axis=0)
    return Q


# ------------------------------------------------------------------------------------------------ result
@dataclass
class IdCardDetection:
    """Duck-types measure.CardDetection (spec, n_corners, H_img_from_board, reproj_rms_px, img_pts, obj_pts)."""
    spec: IdCardSpec
    H_img_from_board: np.ndarray          # wall plane (thickness-corrected), board mm -> image px
    H_img_from_card_face: np.ndarray      # card face plane, before the thickness correction
    img_pts: np.ndarray                   # the 4 virtual sharp corners (image px)
    obj_pts: np.ndarray                   # their board coordinates (mm)
    reproj_rms_px: float                  # RMS distance of the inlier edge points to their fitted lines
    px_per_mm: float
    tilt_deg: float
    focal_px: float
    focal_source: str
    camera_distance_mm: float
    thickness_scale: float                # wall = card face scaled by this about the camera foot point
    aspect_measured: float
    corner_cut_mm: float | None           # distance virtual corner -> outline along the bisector (rounded: ~1.32)
    blur_sigma_px: float | None
    edges: list
    unc_terms: dict
    scale_rel_unc: float                  # 1 sigma, at the card centre, all terms
    confidence: float
    H_samples: np.ndarray = field(repr=False, default=None)
    recovered_edge: int | None = None     # board side rebuilt from the other three (hidden by a finger...)
    corner_rms_px: float | None = None    # 4 line-intersection corners vs the PnP rectangle (shape consistency)
    corner_support: list = field(default_factory=list)   # rounded-corner evidence per board corner (0..1)
    occluded_edges: list = field(default_factory=list)
    n_corners: int = 4
    reference: str = "idcard"

    def scale_rel_unc_at(self, pt_mm) -> float:
        """1-sigma relative scale uncertainty at a board point (mm): Monte Carlo line-fit term evaluated at
        that point (it grows with the distance to the card) + ISO size + thickness terms."""
        fit = self._fit_term(pt_mm)
        return float(math.sqrt(fit ** 2 + self.unc_terms["iso"] ** 2 + self.unc_terms["thickness"] ** 2))

    def _fit_term(self, pt_mm):
        if self.H_samples is None or len(self.H_samples) < 10:
            return 0.0
        J0 = _jac(self.H_img_from_board, pt_mm)
        Js = _jac_batch(self.H_samples, pt_mm)
        M = np.linalg.solve(Js, np.broadcast_to(J0, Js.shape))        # nominal mm -> sample mm
        s = np.linalg.svd(M, compute_uv=False)
        dev = np.max(np.abs(s - 1.0), axis=1)
        return float(np.sqrt(np.mean(dev ** 2)))

    def outline_img(self, margin_mm=0.0, n_arc=6):
        """Rounded-rectangle outline of the card (image px), optionally grown by margin_mm."""
        r = ID1_CORNER_R_MM + margin_mm
        W, H = ID1_W_MM, ID1_H_MM
        pts = []
        for cx, cy, a0 in ((W - ID1_CORNER_R_MM, ID1_CORNER_R_MM, -90), (W - ID1_CORNER_R_MM, H - ID1_CORNER_R_MM, 0),
                           (ID1_CORNER_R_MM, H - ID1_CORNER_R_MM, 90), (ID1_CORNER_R_MM, ID1_CORNER_R_MM, 180)):
            for k in range(n_arc + 1):
                a = math.radians(a0 + 90 * k / n_arc)
                pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        return _apply_h(self.H_img_from_card_face, pts)

    def public_info(self) -> dict:
        return {"reference": "idcard", "scale_rel_unc": round(self.scale_rel_unc, 5),
                "scale_unc_terms": {k: round(v, 5) for k, v in self.unc_terms.items()},
                "edge_rms_px": round(self.reproj_rms_px, 3), "aspect_measured": round(self.aspect_measured, 4),
                "focal_px": round(self.focal_px, 1), "focal_source": self.focal_source,
                "camera_distance_mm": round(self.camera_distance_mm, 1),
                "corner_rms_px": None if self.corner_rms_px is None else round(self.corner_rms_px, 3), "thickness_scale": round(self.thickness_scale, 5),
                "corner_cut_mm": None if self.corner_cut_mm is None else round(self.corner_cut_mm, 2),
                "corner_support": self.corner_support,
                "edge_coverage": [e["coverage"] for e in self.edges], "confidence": round(self.confidence, 3),
                "rebuilt_edge": None if self.recovered_edge is None else self.edges[self.recovered_edge]["image_side"],
                "occluded_edges": self.occluded_edges,
                "corners_img_px": np.round(self.img_pts, 2).tolist()}


@dataclass
class IdCardReport:
    """What detect_idcard says besides the detection: status, retake reason, numbers for the quality dict,
    and the image polygons to redact (also when the card was found but rejected)."""
    status: str = "card_not_found"         # "ok" or one of RETAKE
    detail: str = ""
    quality: dict = field(default_factory=dict)
    redact_polys_img: list = field(default_factory=list)
    candidates: int = 0

    @property
    def rejected(self):
        return self.status not in ("ok", "card_not_found")

    def quality_fields(self) -> dict:
        q = {"reference": "idcard", "reference_status": self.status}
        if self.status != "ok":
            q.update({"retake_reason": self.status, "retake_instruction": RETAKE.get(self.status, ""),
                      "retake_detail": self.detail})
        q.update(self.quality)
        return q


# ------------------------------------------------------------------------------------------------ 4th side
def _hl(line):
    n, c = line
    return (float(n[0]), float(n[1]), -float(c))


def _cross(a, b):
    """3-vector cross product on plain tuples (np.cross is ~20x slower on single vectors)."""
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _corners_from_lines(L):
    """Board-order corners: corner s = side s-1 x side s."""
    out = []
    for s in range(4):
        q = _cross(_hl(L[(s - 1) % 4]), _hl(L[s]))
        if abs(q[2]) < 1e-12:
            return None
        out.append((q[0] / q[2], q[1] / q[2]))
    return np.array(out)


def recover_side(L, m, f, shape, toward, target=ID1_ASPECT, t_hint=None):
    """Line of side `m` (unknown: hidden by a finger, glare...) from the three others, assuming they bound a
    3-D rectangle with aspect side0/side1 = `target` seen by a camera of focal f (principal point at the
    image centre). The hidden side is parallel in 3-D to its opposite side o, so it passes through o's
    vanishing point, which is the point of line o orthogonal (w.r.t. the image of the absolute conic
    omega = K^-T K^-1) to the vanishing point of the two adjacent sides; its position along the adjacent
    side is then fixed by the aspect ratio (1-D root finding). `toward`: a point on the visible part of
    adjacent side (m+1) % 4, to know in which direction the card extends. -> (n, c) or None."""
    a, o = (m + 1) % 4, (m + 2) % 4
    b = (m + 3) % 4
    Ki = np.linalg.inv(_K(f, shape))
    omega = Ki.T @ Ki
    v_ab = _cross(_hl(L[a]), _hl(L[b]))
    v_o = _cross(_hl(L[o]), tuple(omega @ np.array(v_ab)))
    c_ao = _intersect(L[a], L[o])
    if c_ao is None:
        return None
    na = L[a][0]
    d_a = np.array([-na[1], na[0]])
    if d_a @ (np.asarray(toward) - c_ao) < 0:
        d_a = -d_a
    c_bo = _intersect(L[b], L[o])
    Lo = float(np.linalg.norm(c_bo - c_ao)) if c_bo is not None else 100.0
    unit = [(0, 0), (1, 0), (1, 1), (0, 1)]

    def line_at(t):
        p = c_ao + t * d_a
        lm = _cross(v_o, (p[0], p[1], 1.0))
        s = math.hypot(lm[0], lm[1])
        if s < 1e-12:
            return None
        return np.array([lm[0] / s, lm[1] / s]), -lm[2] / s

    def g(t):
        lm = line_at(t)
        if lm is None:
            return None
        LL = list(L)
        LL[m] = lm
        Q = _corners_from_lines(LL)
        if Q is None:
            return None
        try:
            asp = aspect_with_focal(homography_4pt(unit, Q), f, shape)
        except np.linalg.LinAlgError:
            return None
        return math.log(asp / target)

    ts = np.exp(np.linspace(math.log(0.25 * Lo), math.log(5.0 * Lo), 24))
    vals = [g(t) for t in ts]
    roots = []
    for i in range(len(ts) - 1):
        if vals[i] is None or vals[i + 1] is None or vals[i] * vals[i + 1] > 0:
            continue
        lo, hi, glo = ts[i], ts[i + 1], vals[i]
        for _ in range(22):
            mid = 0.5 * (lo + hi)
            gm = g(mid)
            if gm is None:
                break
            if gm * glo > 0:
                lo, glo = mid, gm
            else:
                hi = mid
        roots.append(0.5 * (lo + hi))
    if not roots:
        return None
    t = min(roots, key=lambda r: abs(r - t_hint)) if t_hint is not None else roots[0]
    return line_at(t)


def _image_corner(H, k):
    """Where board corner k is in the photo, seen from the card centre: top-left, bottom-right..."""
    c, q = _apply_h(H, [(ID1_W_MM / 2, ID1_H_MM / 2), _OBJ[k]])
    return ("top" if q[1] < c[1] else "bottom") + "-" + ("left" if q[0] < c[0] else "right")


def _image_side(H, s):
    """Where board side s is in the photo, seen from the card centre: left / right / top / bottom."""
    mids = [(ID1_W_MM / 2, 0), (ID1_W_MM, ID1_H_MM / 2), (ID1_W_MM / 2, ID1_H_MM), (0, ID1_H_MM / 2)]
    c, q = _apply_h(H, [(ID1_W_MM / 2, ID1_H_MM / 2), mids[s]])
    d = q - c
    return ("right" if d[0] > 0 else "left") if abs(d[0]) > abs(d[1]) else ("bottom" if d[1] > 0 else "top")


# ------------------------------------------------------------------------------------------------ fingers
def occluder_mask(bgr_roi, quad_roi):
    """Finger / hand over the card's edge, whatever the skin tone: pixels just outside the card (4-25 mm) clearly
    redder than the wall around it (robust Lab statistics of that ring), grouped in regions that touch
    the card, reach >= 6 mm away from it and are >= 6 mm thick (a finger is 12-20 mm; the card's shadow, a joint
    or a ledge line are thin). The region is then grown 4 mm so it also covers the finger where it lies over the
    edge itself. Float mask 0/1 in ROI pixels."""
    H0, W0 = bgr_roi.shape[:2]
    Q = np.asarray(quad_roi, np.float64)
    ppm0 = math.sqrt(max(cv2.contourArea(Q.astype(np.float32)), 1.0) / (ID1_W_MM * ID1_H_MM))
    fs = min(1.0, 3.0 / max(ppm0, 1e-6))          # work at ~3 px/mm: a finger is ~40 px wide, plenty
    if fs < 1.0:
        small = cv2.resize(bgr_roi, None, fx=fs, fy=fs, interpolation=cv2.INTER_AREA)
        m = occluder_mask(small, (Q + 0.5) * fs - 0.5)
        return cv2.resize(m, (W0, H0), interpolation=cv2.INTER_NEAREST)
    h, w = H0, W0
    ppm = ppm0
    card = np.zeros((h, w), np.uint8)
    cv2.fillConvexPoly(card, np.round(Q).astype(np.int32), 1)

    def grow(m, mm):                         # disc dilation by a distance transform (O(N), any radius)
        d = cv2.distanceTransform((m == 0).astype(np.uint8), cv2.DIST_L2, 3)
        return (d <= max(1.0, mm * ppm)).astype(np.uint8)
    near = grow(card, 4.0)
    ring = (grow(card, 25.0) > 0) & (near == 0)
    if ring.sum() < 50:
        return np.zeros((h, w), np.float32)
    lab = cv2.cvtColor(np.clip(bgr_roi, 0, 255).astype(np.uint8), cv2.COLOR_BGR2Lab).astype(np.float32)
    lab = cv2.GaussianBlur(lab, (0, 0), max(0.7, 0.5 * ppm))
    vals = lab[ring]
    med = np.median(vals, axis=0)
    mad = 1.4826 * np.median(np.abs(vals - med), axis=0)
    sig = np.maximum(mad, np.array([4.0, 1.5, 1.5]))
    # Skin of every tone is redder than plaster, paint or concrete (CIE a*: +8 to +14 on the owner's photos, dark
    # skin included), while what else differs from the wall next to a card -- its shadow, a joint, a ledge, a
    # crack, the card's own colour -- is a change of lightness or of yellow/blue, not of red. So the test is on a*.
    da = lab[..., 1] - med[1]
    foreign = ((da > max(5.0, 4.0 * sig[1])) & (grow(card, 25.0) > 0) & (card == 0)).astype(np.uint8)
    foreign = cv2.morphologyEx(foreign, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, lab_c = cv2.connectedComponents(foreign, connectivity=8)
    if n <= 1:
        return np.zeros((h, w), np.float32)
    dist_card = cv2.distanceTransform((1 - card).astype(np.uint8), cv2.DIST_L2, 5)
    thick = cv2.distanceTransform(foreign, cv2.DIST_L2, 5)
    out = np.zeros((h, w), np.uint8)
    touch = near > 0
    for c in range(1, n):
        m = lab_c == c
        if not (m & touch).any():
            continue
        if dist_card[m].max() < 6.0 * ppm or thick[m].max() < 3.0 * ppm:
            continue
        out[m] = 1
    if not out.any():
        return np.zeros((h, w), np.float32)
    return grow(out, 4.0).astype(np.float32)


def skin_mask(bgr_roi, quad_roi=None):
    """Float mask (0/1) of skin-coloured pixels (YCrCb box, Chai & Ngan 1999, slightly widened), used to drop
    edge samples where a finger crosses the card's edge. Disabled (all zeros) when the wall around the card is
    itself skin-coloured (brick, wood, terracotta), where it would not tell a finger from the wall."""
    ycc = cv2.cvtColor(np.clip(bgr_roi, 0, 255).astype(np.uint8), cv2.COLOR_BGR2YCrCb)
    m = ((ycc[:, :, 0] > 40) & (ycc[:, :, 1] >= 140) & (ycc[:, :, 1] <= 180) & (ycc[:, :, 2] >= 77) & (ycc[:, :, 2] <= 127))
    m = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    if quad_roi is not None:
        inner = np.zeros(m.shape, np.uint8)
        cv2.fillConvexPoly(inner, np.round(quad_roi).astype(np.int32), 1)
        ring = cv2.dilate(inner, np.ones((25, 25), np.uint8)) & (1 - inner)
        if ring.any() and m[ring > 0].mean() > 0.1:
            return np.zeros(m.shape, np.float32)
    return m.astype(np.float32)


# ------------------------------------------------------------------------------------------------ main entry
_OBJ = np.array([(0, 0), (ID1_W_MM, 0), (ID1_W_MM, ID1_H_MM), (0, ID1_H_MM)], np.float64)
_SIDE_MID = [np.array(v) for v in ((ID1_W_MM / 2, 0.0), (ID1_W_MM, ID1_H_MM / 2), (ID1_W_MM / 2, ID1_H_MM), (0.0, ID1_H_MM / 2))]
_SIDE_OUT = ((0, -1), (1, 0), (0, 1), (-1, 0))


def _low(st):
    """Too little edge found, even counting only the part of the side not hidden by a finger/hand."""
    return st["coverage"] < 0.45 and st["coverage"] < 0.6 * (1.0 - st.get("occ_frac", 0.0))


def _supported(st, p):
    """A side is usable when its edge is found along most of it, or -- when a finger/hand hides part of it -- along
    most of its VISIBLE part (>= 75 %), with at least 30 % of the side and points spread over >= 40 % of it."""
    if st is None or st.get("noisy", False):
        return False
    if st["coverage"] >= p.min_side_coverage and st["max_gap_frac"] <= p.max_gap_frac:
        return True
    vis = 1.0 - st.get("occ_frac", 0.0)
    if st.get("occ_frac", 0.0) <= 0.05 or st["n_inliers"] < 12:
        return False
    # the visible parts are well covered, and the points either spread over >= 40 % of the side, or come in
    # fragments on both sides of the hand (span >= 60 %): two fragments far apart fix the line well
    return st["coverage"] >= max(0.1, 0.6 * vis) and st.get("inl_span_frac", 0.0) >= (0.4 if st["coverage"] >= 0.3 else 0.6)


def _flag_noisy(stats):
    """A side whose edge points scatter much more than the other sides' is not the card's edge (texture line,
    printed line, finger outline): it is then treated as weakly supported."""
    sig = [st["robust_sigma_px"] if st is not None else None for st in stats]
    for s_, st in enumerate(stats):
        if st is None:
            continue
        others = [v for o, v in enumerate(sig) if o != s_ and v is not None]
        st["noisy"] = bool(others) and st["robust_sigma_px"] > max(1.5, 3.0 * float(np.median(others)))


def _refine_candidate(img, offset, Qfull, shape, p: IdCardParams, skin=None, focal_px=None):
    """Edge sampling + robust line fits from a full-resolution candidate quad (3 iterations). A side whose
    edge is mostly hidden is rebuilt from the three others (see recover_side). -> dict or None."""
    Q = _canonical(Qfull, shape, p)
    H = homography_4pt(_OBJ, Q)
    ppm = math.sqrt(abs(np.linalg.det(_jac(H, (ID1_W_MM / 2, ID1_H_MM / 2)))))
    half = max(6.0, 0.012 * max(shape[:2]))
    f_def = p.focal_35mm * _fu(shape)
    blur = None
    n_it, n_flip, it = 3, 0, -1
    while it < n_it - 1:
        it += 1
        flipped = False
        eps, fits, stats = [], [], []
        for s in range(4):
            ep = _edge_points(img, offset, H, s, p, half, ppm, skin)
            fit = _fit_line(ep["P"][ep["good"]], tau0=1.5 if it == 0 else 1.0)
            st = _side_stats(ep, fit, ppm) if fit is not None else None
            usable = st is not None and ((st["coverage"] >= 0.25 and np.ptp(st["_inl_u"]) >= 0.35 * (ep["L_mm"] - 2 * ep["u_mm"][0]))
                                         or _supported(st, p))
            eps.append(ep)
            fits.append(fit if usable else None)
            stats.append(st)
        _flag_noisy(stats)
        lines = [(f_[0], f_[1]) if f_ is not None else None for f_ in fits]
        missing = [s for s in range(4) if lines[s] is None]
        provisional = len(missing) > 1 and it < n_it - 1
        bad_shape = False
        if provisional:
            # first passes use a wide search window on a rough outline (a 4032 px photo: +-48 px), where the card's
            # print can out-vote a weak edge: keep the current outline's side and look again, narrower
            for s in missing:
                a_, b_ = Q[s], Q[(s + 1) % 4]
                d_ = (b_ - a_) / max(float(np.linalg.norm(b_ - a_)), 1e-9)
                n_ = np.array([-d_[1], d_[0]])
                lines[s] = (n_, float(n_ @ a_))
            missing = []
        recovered = None
        weak = sorted((s for s in range(4) if not _supported(stats[s], p)),
                      key=lambda s: 0.0 if stats[s] is None else stats[s]["coverage"])

        def fail(sides):
            return {"fail": "card_occluded", "H": H, "sides": [_image_side(H, s) for s in sides],
                    "coverage": [0.0 if stats[s] is None else stats[s]["coverage"] for s in sides],
                    "corners": [corner_support(img, offset, H, k, ppm, occ=skin) for k in range(4)]}
        last = it == n_it - 1               # early iterations run on a rough outline: judge only the last one
        if len(missing) > 1 or (len(weak) >= 3 and last):
            return fail(weak)
        if provisional:
            todo = []
        elif missing:
            # a side with no usable edge at all (hidden by a finger, glare): rebuilt from the other three,
            # nothing to check it against -> lower confidence, larger uncertainty (unknown focal)
            if len(weak) > 1 and any(stats[s] is not None and _low(stats[s]) for s in weak if s != missing[0]) and last:
                return fail(weak)
            # Synthetic evaluation: a side rebuilt with NO visible edge under it (finger laid along the edge) was
            # wrong by 7-12 % in 3 of 5 accepted cases, so some edge evidence along the rebuilt line is required;
            # otherwise the photo is refused naming the hidden edge.
            todo, need_support = missing, 0.2
        else:
            Qn = _corners_from_lines(lines)
            if Qn is None:
                return None
            e = _best_aspect(Qn, shape, p, strict=True)[0]
            # not a flat ID-1 rectangle: wrong proportions, or corners off the best rectangle for the focal in use
            cr_mm = pnp_homography(Qn, focal_px or f_def, shape)[1] / max(ppm, 1e-6)
            bad_shape = e > p.aspect_tol or cr_mm > p.max_corner_rms_mm
            finger_side = [s for s in range(4) if stats[s]["skin_inl"] >= 0.5
                           and sum(stats[o]["skin_inl"] < 0.1 for o in range(4) if o != s) >= 2
                           and _skin_deep_inside(skin, offset, H, s) < 0.3]
            # refuse only for lack of edge (a scattered but consistent edge is kept: its scatter enters the uncertainty;
            # a wrong line is caught by the ID-1 proportions and the rounded-corner checks)
            low = [s for s in weak if _low(stats[s])]
            noisy_or_low = [s for s in weak if stats[s].get("noisy") or _low(stats[s])]
            if len(low) >= 2 and last:
                return fail(weak)
            # Rebuild candidates: a side running along skin (finger outline), else -- when the quad is not an ID-1
            # rectangle or one side is unreliable -- the weak sides. A rebuilt side is kept only if a real edge
            # supports it (a finger laid along the edge hides the true edge: then nothing supports any rebuild and
            # the photo is refused rather than measured with a wrong side).
            # a measured side is kept as long as the outline is a flat ID-1 rectangle (its weaker support enters the
            # uncertainty); rebuilding it on a coverage threshold made the decision flip on JPEG noise
            todo = finger_side[:1] or (noisy_or_low if bad_shape else [])
            need_support = 0.35
            if bad_shape and not todo:
                if it == n_it - 1:
                    return {"fail": "card_inconsistent", "H": H, "sides": [], "coverage": [], "aspect_err": e,
                            "corners": [corner_support(img, offset, H, k, ppm, occ=skin) for k in range(4)]}
        if len(todo) > 2:
            todo = []                         # more than two doubtful sides: nothing reliable to rebuild from
        if todo:
            ref_peak = float(np.median(np.concatenate([eps[s]["peak"][eps[s]["good"]] for s in range(4) if s not in todo])))
            best_rec = None
            for m in todo:
                if sum(_supported(stats[s], p) or (stats[s] is not None and stats[s]["coverage"] >= 0.45)
                       for s in range(4) if s != m) < 3:
                    continue
                Lm = list(lines)
                Lm[m] = None
                toward = stats[(m + 1) % 4]["_inl_P"].mean(0)
                t_hint = float(np.linalg.norm(_apply_h(H, [_OBJ[(m + 1) % 4]])[0] - _apply_h(H, [_OBJ[(m + 2) % 4]])[0]))
                # which pair of sides is the long one is not certain when a side is wrong: try both proportions
                for target in (ID1_ASPECT, 1 / ID1_ASPECT):
                    rec = recover_side(Lm, m, f_def, shape, toward, target=target, t_hint=t_hint)
                    if rec is None:
                        continue
                    Qr = _corners_from_lines(Lm[:m] + [rec] + Lm[m + 1:])
                    if Qr is None or not _convex_quad([tuple(q) for q in Qr]):
                        continue
                    if not _rebuild_plausible(Qr, rec, m, stats, ppm):
                        continue
                    sup = _line_support(img, offset, Qr[m], Qr[(m + 1) % 4], ref_peak, occ=skin)
                    if best_rec is None or sup > best_rec[0]:
                        best_rec = (sup, rec, target, m)
            if best_rec is None or best_rec[0] < need_support:
                if missing and it < n_it - 1:
                    # early pass on a rough outline: keep its side and look again with a narrower window
                    for s in missing:
                        a_, b_ = Q[s], Q[(s + 1) % 4]
                        d_ = (b_ - a_) / max(float(np.linalg.norm(b_ - a_)), 1e-9)
                        n_ = np.array([-d_[1], d_[0]])
                        lines[s] = (n_, float(n_ @ a_))
                    missing = []
                elif missing:
                    return fail(missing)
                if bad_shape and it == n_it - 1:
                    return {"fail": "card_inconsistent", "H": H, "sides": [_image_side(H, s) for s in todo],
                            "coverage": [stats[s]["coverage"] for s in todo], "aspect_err": e,
                            "corners": [corner_support(img, offset, H, k, ppm, occ=skin) for k in range(4)]}
            else:
                m = best_rec[3]
                lines[m] = best_rec[1]
                fits[m] = None
                recovered = m
                flipped = best_rec[2] != ID1_ASPECT
        Qn = _corners_from_lines(lines)
        if Qn is None:
            return None
        Q = Qn
        if recovered is not None and flipped:
            Q = _canonical(Q, shape, p)          # long side first again; sides are re-sampled next iteration
            n_flip += 1
            if it == n_it - 1 and n_flip <= 2:
                n_it += 1
        H = homography_4pt(_OBJ, Q)
        ppm = math.sqrt(abs(np.linalg.det(_jac(H, (ID1_W_MM / 2, ID1_H_MM / 2)))))
        sel = [s for s in range(4) if fits[s] is not None]
        blur = _blur_from_profiles(np.concatenate([eps[s]["prof"] for s in sel]), eps[0]["t"],
                                   np.concatenate([eps[s]["k"] for s in sel]),
                                   np.concatenate([_inl_full(eps[s]["good"], fits[s][2]) for s in sel])) if sel else None
        half = max(2.5, 3.0 * (blur or 1.5) + 1.5) if not flipped else max(6.0, 0.012 * max(shape[:2]))
    pk_all = [eps[s]["peak"][eps[s]["good"]] for s in range(4) if fits[s] is not None]
    ref_pk = float(np.median(np.concatenate(pk_all))) if pk_all else None
    corners = [corner_support(img, offset, H, k, ppm, occ=skin, ref_peak=ref_pk) for k in range(4)]
    return {"Q": Q, "H": H, "ppm": ppm, "fits": fits, "lines": lines, "stats": stats, "eps": eps, "recovered": recovered,
            "corners": corners, "_occ": skin}


def _rebuild_plausible(Qr, rec, m, stats, ppm, max_hidden_mm=30.0):
    """A rebuilt side must leave the edge points of its two neighbours inside the card, and close the card
    within `max_hidden_mm` of the last visible point (a finger hides ~15-20 mm): this tells the right
    proportions (long vs short) apart when nothing is visible along the hidden side itself."""
    n, c = rec
    n = np.asarray(n, float)
    if float(n @ Qr.mean(0)) > c:          # orient: outward = n . x > c
        n, c = -n, -c
    for a in ((m + 1) % 4, (m + 3) % 4):
        st = stats[a]
        if st is None or not len(st["_inl_P"]):
            continue
        d = st["_inl_P"] @ n - c            # <= 0 inside
        if d.max() > 2.0 or -d.max() > max_hidden_mm * ppm:
            return False
    return True


def _skin_deep_inside(skin, offset, H, s, depths_mm=(22.0, 27.0, 32.0)):
    """Skin fraction 22-32 mm inside the card from side s: a finger is ~15-20 mm wide, so skin found that deep
    is the card's own (skin-coloured) face, not a finger lying along the edge."""
    if skin is None:
        return 1.0
    a, b = [((0, 0), (ID1_W_MM, 0)), ((ID1_W_MM, 0), (ID1_W_MM, ID1_H_MM)), ((ID1_W_MM, ID1_H_MM), (0, ID1_H_MM)),
            ((0, ID1_H_MM), (0, 0))][s]
    a, b = np.array(a, float), np.array(b, float)
    inward = -np.array(_SIDE_OUT[s], float)
    pts = [a + (b - a) * u + inward * d for u in np.linspace(0.2, 0.8, 12) for d in depths_mm]
    q = _apply_h(H, pts) - offset
    v = cv2.remap(skin, q[:, 0:1].astype(np.float32), q[:, 1:2].astype(np.float32), cv2.INTER_NEAREST,
                  borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    return float(np.mean(v > 0.5))


_CORNER_CENTRES = [(ID1_CORNER_R_MM, ID1_CORNER_R_MM, 180), (ID1_W_MM - ID1_CORNER_R_MM, ID1_CORNER_R_MM, 270),
                   (ID1_W_MM - ID1_CORNER_R_MM, ID1_H_MM - ID1_CORNER_R_MM, 0), (ID1_CORNER_R_MM, ID1_H_MM - ID1_CORNER_R_MM, 90)]


def corner_support(img, offset, H, k, ppm, n=11, occ=None, tol_mm=0.4, ref_peak=None):
    """Fraction of the rounded corner k (r = 3.18 mm arc between the two straight sides) where a colour edge is
    found on the arc (within max(0.6 mm, 2 px)). A real card corner is there; the 'corner' of a quad closed by
    a finger, a joint or a printed line is not. Corner k is board corner k (0 = (0,0), clockwise)."""
    cx, cy, a0 = _CORNER_CENTRES[k]
    # around the bisector only (30-60 deg): there a rounded corner and a sharp one differ by 0.5-1.3 mm, while
    # near the straight sides both look alike
    ang = np.radians(a0 + np.linspace(30, 60, n))
    tol = max(tol_mm, 1.5 / max(ppm, 1e-6))
    rr = ID1_CORNER_R_MM + np.linspace(-1.6, 1.6, 33)
    pts = np.array([(cx + r * math.cos(a), cy + r * math.sin(a)) for a in ang for r in rr])
    q = _apply_h(H, pts) - offset
    prof = cv2.remap(img, q[:, 0:1].astype(np.float32), q[:, 1:2].astype(np.float32), cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_REPLICATE)
    prof = prof.reshape(n, len(rr), -1)
    valid = None
    if occ is not None:
        oc = cv2.remap(occ, q[:, 0:1].astype(np.float32), q[:, 1:2].astype(np.float32), cv2.INTER_NEAREST,
                       borderMode=cv2.BORDER_CONSTANT, borderValue=0).reshape(n, len(rr))
        valid = oc.max(axis=1) < 0.5
    E = np.sqrt((np.gradient(prof, axis=1) ** 2).sum(-1))
    # a local gradient peak on the arc, even if a stronger edge lies nearby (the card's shadow on the wall, a ledge)
    win = np.abs(rr - ID1_CORNER_R_MM) <= tol
    Ew = np.where(win[None, :], E, -1.0)
    kpk = np.argmax(Ew, axis=1)
    pk = E[np.arange(n), kpk]
    left = E[np.arange(n), np.clip(kpk - 1, 0, len(rr) - 1)]
    right = E[np.arange(n), np.clip(kpk + 1, 0, len(rr) - 1)]
    ok = (pk >= left) & (pk >= right) & (pk >= 0.3 * E.max(axis=1)) & (pk >= 1.5 * np.median(E, axis=1)) & (pk >= 1.0)
    if ref_peak:                                   # as strong as the card's own edges, not a texture ripple
        ok &= pk >= 0.2 * ref_peak
    if valid is not None:
        ok = ok[valid]
        if len(ok) < 3:
            return float("nan")                    # corner hidden (occluder): no evidence either way
    return float(np.mean(ok))


def side_inside_check(img, offset, H, occ=None):
    """For each side: does the band just inside it (1.5-4 mm) look like the card or like the wall outside?
    A side that is not the card's boundary (a crack lip, a joint or a texture line a few mm beyond the card)
    has wall on both sides. Returns per side d(inside band, outside band) / d(wall, card) in Lab: ~1 for a true card
    side, ~0 for a side lying a few mm off the card on the wall."""
    lab = cv2.cvtColor(np.clip(img, 0, 255).astype(np.uint8), cv2.COLOR_BGR2Lab).astype(np.float32)
    g = np.mgrid[8:78:24j, 8:46:12j].reshape(2, -1).T              # card interior samples (mm)
    q = _apply_h(H, g) - offset
    inner = cv2.remap(lab, q[:, 0:1].astype(np.float32), q[:, 1:2].astype(np.float32), cv2.INTER_LINEAR,
                      borderMode=cv2.BORDER_REPLICATE).reshape(-1, 3)
    card_med = np.median(inner, axis=0)
    bands = []
    for s_ in range(4):
        a, b = [((0, 0), (ID1_W_MM, 0)), ((ID1_W_MM, 0), (ID1_W_MM, ID1_H_MM)), ((ID1_W_MM, ID1_H_MM), (0, ID1_H_MM)),
                ((0, ID1_H_MM), (0, 0))][s_]
        a, b = np.array(a, float), np.array(b, float)
        nb = np.array(_SIDE_OUT[s_], float)
        u = np.linspace(0.15, 0.85, 30)[:, None]
        P = a + (b - a) * u
        vals = {}
        for name, ds in (("in", (-0.8, -1.5, -2.5)), ("out", (1.5, 2.5, 4.0))):
            pts = np.vstack([P + nb * d for d in ds])
            qq = _apply_h(H, pts) - offset
            v = cv2.remap(lab, qq[:, 0:1].astype(np.float32), qq[:, 1:2].astype(np.float32), cv2.INTER_LINEAR,
                          borderMode=cv2.BORDER_REPLICATE).reshape(-1, 3)
            if occ is not None:
                o = cv2.remap(occ, qq[:, 0:1].astype(np.float32), qq[:, 1:2].astype(np.float32), cv2.INTER_NEAREST,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=0).ravel()
                v = v[o < 0.5] if (o < 0.5).sum() >= 10 else v
            vals[name] = np.median(v, axis=0)
        bands.append(vals)
    wall = np.median(np.array([v["out"] for v in bands]), axis=0)
    d_wc = max(float(np.linalg.norm(wall - card_med)), 4.0)
    # the band just inside should differ from the band just outside about as much as the card differs from the wall;
    # a side lying on the wall has the same thing on both sides (score ~0). Card designs vary, so the inside band
    # is not compared with the card's average colour.
    # either test: inside like the outside right there, or inside like the wall in general (a side drawn along a
    # crack lip has dark crack outside but plain wall inside)
    return [min(float(np.linalg.norm(v["in"] - v["out"])), float(np.linalg.norm(v["in"] - wall))) / d_wc for v in bands]


def _line_support(img, offset, pa, pb, ref_peak, n=60, occ=None):
    """Fraction of the VISIBLE points along the image segment pa-pb (not under the occluder mask `occ`) with a
    colour edge near the segment (within 4 px); 0 when fewer than 6 of the 40 points are visible."""
    pa, pb = np.asarray(pa, float), np.asarray(pb, float)
    L = float(np.linalg.norm(pb - pa))
    if L < 5:
        return 0.0
    d = (pb - pa) / L
    nrm = np.array([-d[1], d[0]])
    # from 3 % to 97 % of the side: when a hand covers most of it, the fragments left are near the corners
    u = np.linspace(0.03, 0.97, n)[:, None]
    P = pa + (pb - pa) * u
    t = np.arange(-7.0, 7.01, 0.25, dtype=np.float32)
    mx = (P[:, 0:1] - offset[0] + nrm[0] * t[None, :]).astype(np.float32)
    my = (P[:, 1:2] - offset[1] + nrm[1] * t[None, :]).astype(np.float32)
    prof = cv2.remap(img, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    if prof.ndim == 2:
        prof = prof[:, :, None]
    E = np.sqrt((np.gradient(prof, 0.25, axis=1) ** 2).sum(-1))
    k = np.argmax(E, axis=1)
    pk = E[np.arange(n), k]
    ok = (np.abs(t[k]) <= 4.0) & (pk >= max(8.0, 0.12 * ref_peak)) & (pk >= 2.5 * np.median(E, axis=1))
    if occ is not None:
        vis = cv2.remap(occ, mx, my, cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0).max(axis=1) < 0.5
        if vis.sum() < 4:
            return 0.0
        return float(np.mean(ok[vis]))
    return float(np.mean(ok))


def _inl_full(good, inl):
    out = np.zeros_like(good)
    out[np.nonzero(good)[0][inl]] = True
    return out


def _corner_cut(img, offset, H, ppm):
    """Median distance (mm) from the virtual sharp corners to the outline along the inward bisector.
    A rounded ID-1 corner (r = 3.18 mm) gives r (sqrt 2 - 1) = 1.32 mm; a sharp corner ~0. Informative only."""
    if ppm < 4:
        return None
    out = []
    for cx, cy, dx, dy in ((0, 0, 1, 1), (ID1_W_MM, 0, -1, 1), (ID1_W_MM, ID1_H_MM, -1, -1), (0, ID1_H_MM, 1, -1)):
        s = np.linspace(-2.0, 4.0, 121) / math.sqrt(2)
        pts_mm = np.column_stack([cx + dx * s, cy + dy * s])
        pim = _apply_h(H, pts_mm) - offset
        prof = cv2.remap(img, pim[:, 0:1].astype(np.float32), pim[:, 1:2].astype(np.float32), cv2.INTER_LINEAR,
                         borderMode=cv2.BORDER_REPLICATE).reshape(len(s), -1)
        E = np.sqrt((np.gradient(prof, axis=0) ** 2).sum(-1))
        out.append(float(s[int(np.argmax(E))] * math.sqrt(2)))
    return float(np.median(out))


def _reprofile(roi, offset, ep):
    """Same profile positions as `ep`, re-sampled on the unsmoothed ROI (for the blur estimate)."""
    t = ep["t"]
    mx = (ep["pim"][:, 0:1] - offset[0] + ep["n_img"][:, 0:1] * t[None, :]).astype(np.float32)
    my = (ep["pim"][:, 1:2] - offset[1] + ep["n_img"][:, 1:2] * t[None, :]).astype(np.float32)
    prof = cv2.remap(roi, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return prof if prof.ndim == 3 else prof[:, :, None]


def pnp_homography(Q, f, shape):
    """Plane homography from the 4 corners with a KNOWN focal: 6-DOF pose (IPPE, planar PnP) instead of the
    free 8-DOF homography. The rectangle shape (right angles, 85.60 x 53.98) is then imposed, which damps the
    false perspective an edge offset of a few tenths of a mm would otherwise create (and which grows when the
    scale is extrapolated to a crack 5-10 cm away). -> (H, corner reprojection RMS px)."""
    h, w = shape[:2]
    K = np.array([[f, 0, w / 2 - 0.5], [0, f, h / 2 - 0.5], [0, 0, 1.0]])
    obj = np.hstack([_OBJ, np.zeros((4, 1))])
    ok, rv, tv = cv2.solvePnP(obj, np.asarray(Q, np.float64).reshape(-1, 1, 2), K, None, flags=cv2.SOLVEPNP_IPPE)
    if not ok:
        return homography_4pt(_OBJ, Q), float("nan")
    Rm, _ = cv2.Rodrigues(rv)
    H = K @ np.column_stack([Rm[:, 0], Rm[:, 1], tv.ravel()])
    H /= H[2, 2]
    return H, float(np.sqrt(np.mean(np.sum((_apply_h(H, _OBJ) - Q) ** 2, axis=1))))


def _focal_sample(fmode, Q, shape, rng, p):
    S = _fu(shape)
    kind, f0 = fmode
    if kind == "exif":
        return f0 * (1 + rng.normal(0, 0.02))
    if kind == "rectangle":
        fo = focal_from_rectangle(_unit_h(Q), shape)
        if fo is not None and p.focal_35mm_range[0] * S <= fo <= p.focal_35mm_range[1] * S:
            return fo
    return rng.uniform(*p.focal_35mm_mc) * S


def _mc_homographies(lines, fits, stats, recovered, A, ppm, blur, shape, p, rng, side_sig_px=None, fmode=("default", None)):
    """Monte Carlo over the fitted lines (offset + angle covariance from the residuals, inflated for the
    correlation of neighbouring edge samples) and, for a rebuilt side, over the unknown focal length."""
    corr_px = max(2.0 * (blur or 1.0), 4.0)
    model = {}
    for s in range(4):
        if fits[s] is None:
            continue
        n = lines[s][0]
        st = stats[s]
        P = st["_inl_P"]
        m = P.mean(0)
        s_ = (P - m) @ np.array([-n[1], n[0]])
        nin = len(P)
        n_eff = max(3.0, nin * min(1.0, p.step_mm * ppm / corr_px))
        sig = math.sqrt(float(np.sum(st["_res"] ** 2)) / max(1, nin - 2))
        m = m - n * (float(n @ m) - lines[s][1])          # centroid moved onto the (possibly shifted) line
        sc_ = math.sqrt(sig ** 2 / n_eff + (side_sig_px or {}).get(s, 0.0) ** 2 + (p.edge_sys_mm * ppm) ** 2)
        model[s] = (n, m, sc_, sig / math.sqrt(max(float(np.sum(s_ ** 2)), 1e-9)) * math.sqrt(nin / n_eff))
    S = _fu(shape)
    Hs = []
    for _ in range(p.n_mc):
        L = [None] * 4
        for s, (n, m, sc_, sphi) in model.items():
            a = rng.normal(0, sphi)
            ca, sa = math.cos(a), math.sin(a)
            n2 = np.array([ca * n[0] - sa * n[1], sa * n[0] + ca * n[1]])
            L[s] = (n2, float(n2 @ (m + n * rng.normal(0, sc_))))
        f_k = None
        if recovered is not None:
            toward = stats[(recovered + 1) % 4]["_inl_P"].mean(0)
            f_k = fmode[1] * (1 + rng.normal(0, 0.02)) if fmode[0] == "exif" else rng.uniform(*p.focal_35mm_mc) * S
            L[recovered] = recover_side(L, recovered, f_k, shape, toward)
            if L[recovered] is None:
                continue
        Q = _corners_from_lines(L)
        if Q is None:
            continue
        f_k = f_k or _focal_sample(fmode, Q, shape, rng, p)
        Hk = pnp_homography(Q, f_k, shape)[0]
        if p.standoff_mm > 0 or p.plane_tilt_deg > 0:
            Hk = _perturb_plane(Hk, f_k, shape, rng.normal(0, p.standoff_mm),
                                rng.normal(0, math.radians(p.plane_tilt_deg)), rng.uniform(0, math.pi))
        Hk = Hk @ A
        Hs.append(Hk / Hk[2, 2])
    return np.array(Hs)


def _perturb_plane(H, f, shape, dz, ang, axis_dir):
    """Homography of a plane through the card centre offset by dz (mm, along the card normal) and rotated by
    `ang` about an in-plane axis of direction `axis_dir`: the wall is not exactly the card's plane (card held by
    a fingertip, rough render, wall not flat between the card and the crack)."""
    R, t, _ = pose_from_homography(H, f, shape)
    u = np.array([math.cos(axis_dir), math.sin(axis_dir), 0.0])
    Rd, _ = cv2.Rodrigues(u * ang)
    X0 = np.array([ID1_W_MM / 2, ID1_H_MM / 2, 0.0])
    t2 = R @ (X0 + np.array([0.0, 0.0, dz]) - Rd @ X0) + t
    K = _K(f, shape)
    H2 = K @ np.column_stack([R @ Rd[:, 0], R @ Rd[:, 1], t2])
    return H2 / H2[2, 2]


def detect_idcard(image: np.ndarray, p: IdCardParams = IdCardParams(), focal_px: float | None = None,
                  exclude_polys=None, expected_ppm: float | None = None):
    """-> (IdCardDetection | None, IdCardReport). `image` BGR (or gray). `focal_px`: the camera focal in
    pixels of this image if known (EXIF FocalLengthIn35mmFilm / 43.27 x image diagonal), else estimated.
    `exclude_polys`: image polygons hidden from the search (e.g. a printed ChArUco sheet in the same photo:
    its checkerboard offers dozens of card-shaped rectangles). `expected_ppm`: px/mm of the wall known from another
    reference (the printed card): a "card" whose own scale disagrees by more than x1.6 is not a card on that wall."""
    rep = IdCardReport()
    bgr = image if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if exclude_polys:
        bgr = _paint_out(bgr, exclude_polys)
    h, w = bgr.shape[:2]
    scale = min(1.0, p.coarse_max_side / max(h, w))
    small = cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else bgr
    cands = find_candidates(small, scale, p)
    rep.candidates = len(cands)
    if not cands:
        rep.detail = "no rectangle with bank-card proportions found"
        return None, rep
    refined = []
    occl = None
    n_refined = 0
    for sc, Qs, info in cands:
        if n_refined >= 8:
            break
        Q = Qs / scale + (0.5 / scale - 0.5)
        # cheap pre-screen at full resolution: rounded corners (loose tolerance, the outline is still rough) where a
        # card's corners would be. A printed checkerboard, tiles or a poster offer many card-shaped rectangles.
        Qc = _canonical(Q, bgr.shape, p)
        Hc = homography_4pt(_OBJ, Qc)
        ppm_c = math.sqrt(abs(np.linalg.det(_jac(Hc, (ID1_W_MM / 2, ID1_H_MM / 2)))))
        gimg = bgr.astype(np.float32) if bgr.shape[0] * bgr.shape[1] < 4e6 else None
        cs = [corner_support(gimg if gimg is not None else bgr, (0, 0), Hc, k, ppm_c, tol_mm=1.0) for k in range(4)]
        if sum(c >= 0.5 for c in cs) < 2:
            continue
        n_refined += 1
        mg = 40 + 0.7 * float(np.ptp(Q, axis=0).max())     # room for a rebuilt side beyond the candidate
        x0, y0 = np.floor(Q.min(0) - mg).astype(int)
        x1, y1 = np.ceil(Q.max(0) + mg).astype(int)
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
        if x1 - x0 < 20 or y1 - y0 < 20:
            continue
        roi = bgr[y0:y1, x0:x1].astype(np.float32)
        out = _refine_candidate(cv2.GaussianBlur(roi, (0, 0), 0.6), (x0, y0), Q, bgr.shape, p,
                                occluder_mask(bgr[y0:y1, x0:x1], Q - (x0, y0)), focal_px=focal_px)
        if out is None:
            continue
        if "fail" in out:
            # report "occluded"/"wrong size" only for something that looks like a card (>= 2 rounded corners);
            # rectangles of the wall, a printed chart or a ChArUco board stay "card not found"
            n_c = sum(c >= 0.5 for c in out.get("corners", []))
            if (n_c >= 2 or (n_c >= 1 and out["sides"])) and (
                    occl is None or (not occl["sides"] and out["sides"])):    # prefer a report naming the hidden edge
                occl = out
            continue
        e, asp, f = _best_aspect(out["Q"], bgr.shape, p, strict=True)
        covs = [st["coverage"] if st is not None else 0.0 for st in out["stats"]]
        res = np.concatenate([out["stats"][s]["_res"] for s in range(4) if out["fits"][s] is not None])
        rms = float(np.sqrt(np.mean(res ** 2)))
        score = float(np.mean(covs)) + 0.5 * min(covs) - 10.0 * e - 0.1 * rms   # ID-1 proportions are known to 0.15 %
        if out["recovered"] is None and e > p.aspect_tol:
            score -= 1.0                                   # not an ID-1 rectangle as it stands
        # rounded corners where the card's corners should be: all of them, except one under a finger, and the two
        # ends of a rebuilt side
        m_ = out["recovered"]
        exempt = {m_, (m_ + 1) % 4} if m_ is not None else set()
        bad = [k for k in range(4) if k not in exempt and out["corners"][k] < 0.5]
        # a corner hidden by the finger/hand mask has no value (nan) and is fine; a VISIBLE corner without a rounded
        # card corner is tolerated once and only if some arc evidence remains (>= 0.3): a quad closed by a finger
        # outline, a printed line or a joint has none
        # ... or when both its sides are well supported (a fingertip on the corner the hand mask missed)
        lone_ok = len(bad) == 1 and m_ is None and (out["corners"][bad[0]] >= 0.3 or all(
            _supported(out["stats"][s_], p) for s_ in ((bad[0] - 1) % 4, bad[0])))
        out["corner_fail"] = [] if (not bad or lone_ok) else bad
        cmean = float(np.nanmean(out["corners"])) if np.isfinite(out["corners"]).any() else 0.0
        score += 1.5 * cmean - (2.0 if out["corner_fail"] else 0.0)   # rounded corners: the best evidence of a card
        if m_ is not None:
            score -= 0.4                 # a rebuilt side rests on fewer measurements: prefer a complete outline
        # an outline that would be refused (cut by the frame, too oblique) is unlikely to be the card when another
        # one is not
        if np.any(out["Q"] < 3) or np.any(out["Q"][:, 0] > w - 4) or np.any(out["Q"][:, 1] > h - 4):
            score -= 1.5
        try:
            Rs, _, _ = pose_from_homography(out["H"], focal_px or p.focal_35mm * _fu(bgr.shape), bgr.shape)
            if math.degrees(math.acos(min(1.0, abs(Rs[2, 2])))) > p.max_tilt_deg:
                score -= 1.5
        except (np.linalg.LinAlgError, ValueError):
            pass
        # a side with wall on both sides is not the card's boundary (crack lip, joint, texture line beyond the card)
        ins = side_inside_check(roi, (x0, y0), out["H"], out.get("_occ"))
        out["inside"] = [round(v, 2) for v in ins]
        # suspect only with weak rounded-corner evidence at BOTH ends: a card whose colour near an edge resembles the
        # wall still shows its rounded corners
        cw = [c if c == c else 0.0 for c in out["corners"]]
        out["side_suspect"] = [s_ for s_ in range(4) if ins[s_] < 0.3 and cw[s_] < 0.75 and cw[(s_ + 1) % 4] < 0.75]
        score -= 1.0 * len(out["side_suspect"])
        if os.environ.get("CW_IDCARD_DEBUG"):
            print("refined", np.round(out["Q"]).astype(int).tolist(), "score", round(score, 3), "e", round(e, 4), "corners", out["corners"], "rec", out["recovered"], "fail", out["corner_fail"], "inside", out["inside"], "suspect", out["side_suspect"])
        refined.append((score, out, e, asp, roi, (x0, y0), rms))
    # a printed rectangle inside the card can also have ID-1 proportions: keep the outer one
    keep = []
    for i, ci in enumerate(refined):
        inside_other = False
        for j, cj in enumerate(refined):
            # ... unless the inner one has clearly more rounded-corner evidence: then the outer one is the card plus
            # a crack lip, a joint or a texture line, and the inner one is the card
            cs_i = np.nan_to_num(np.asarray(ci[1]["corners"], float), nan=0.5)
            cs_j = np.nan_to_num(np.asarray(cj[1]["corners"], float), nan=0.5)
            if cs_i.mean() > cs_j.mean() + 0.05:
                continue
            if i != j and cj[0] > -0.5 and cv2.contourArea(cj[1]["Q"].astype(np.float32)) > 1.15 * cv2.contourArea(ci[1]["Q"].astype(np.float32)):
                poly = cj[1]["Q"].astype(np.float32).reshape(-1, 1, 2)
                if all(cv2.pointPolygonTest(poly, (float(x), float(y)), True) > -3.0 for x, y in ci[1]["Q"]):
                    inside_other = True
        if not inside_other:
            keep.append(ci)
    best = max(keep, key=lambda c: c[0]) if keep else None
    if best is None:
        if occl is not None and occl["fail"] == "card_inconsistent" and not occl["sides"]:
            # two neighbouring corners without a rounded card corner: something straight (a finger) lies along
            # the side joining them, and its outline was taken for the card's edge
            weak_c = [k for k in range(4) if occl["corners"][k] < 0.5]
            if len(weak_c) == 2 and (weak_c[1] - weak_c[0]) in (1, 3):
                k0 = weak_c[0] if weak_c[1] - weak_c[0] == 1 else weak_c[1]
                occl = dict(occl, sides=[_image_side(occl["H"], k0)], coverage=[0.0])
        if occl is not None and occl["fail"] == "card_inconsistent" and not occl["sides"]:
            rep.status = "card_wrong_size"
            rep.detail = f"four straight edges found but not in ID-1 proportions (aspect error {100 * occl['aspect_err']:.1f} %)"
        elif occl is not None:
            rep.status = "card_occluded"
            if occl["fail"] == "card_inconsistent":
                rep.detail = ("the outline is not an ID-1 rectangle and no hidden edge could be rebuilt (something "
                              "straight, e.g. a finger along an edge, may hide it): " + ", ".join(occl["sides"]))
            else:
                rep.detail = "card edges hidden: " + ", ".join(f"{s} ({100 * c:.0f} % visible)" for s, c in zip(occl["sides"], occl["coverage"]))
            rep.quality = {"card_occluded_edges": occl["sides"]}
            if occl["sides"]:
                rep.quality["card_occluded_edge"] = occl["sides"][0]
            H = occl["H"]
            # a refused candidate is never blurred: a wrong "card" (fence, joint) blurred on the crack would corrupt
            # the stored photo used at the next visit
        else:
            rep.detail = "candidate rectangles had no measurable edges"
        return None, rep
    _, out, aspect_err, aspect, roi, off, rms = best
    Q, H_face, ppm, fits, lines, stats, eps, recovered = (out[k] for k in ("Q", "H", "ppm", "fits", "lines", "stats", "eps", "recovered"))
    sel = [s for s in range(4) if fits[s] is not None]
    blur = _blur_from_profiles(np.concatenate([_reprofile(roi, off, eps[s]) for s in sel]), eps[0]["t"],
                               np.concatenate([eps[s]["k"] for s in sel]),
                               np.concatenate([_inl_full(eps[s]["good"], fits[s][2]) for s in sel]))

    # camera: focal from the rectangle when the perspective is strong enough (and all 4 sides are measured)
    S = _fu(bgr.shape)
    f_orth = focal_from_rectangle(H_face, bgr.shape) if recovered is None else None
    if focal_px:
        f, fsrc = float(focal_px), "exif"
    elif f_orth is not None and p.focal_35mm_range[0] * S <= f_orth <= p.focal_35mm_range[1] * S:
        f, fsrc = f_orth, "rectangle"
    else:
        f, fsrc = p.focal_35mm * S, "default"
    R, t, C = pose_from_homography(H_face, f, bgr.shape)
    # Side walls: an edge whose 0.76 mm side wall faces the camera shows two outlines, the face edge and, up to
    # t * tan(view angle) further out, the wall-plane edge; which one the gradient picks depends on colours.
    # The line is moved half-way (centred estimate) and the other half becomes a uniform offset uncertainty.
    D0 = float(abs(C[2]))
    side_sig_px = {}
    lines = list(lines)
    for s_ in range(4):
        if fits[s_] is None:
            continue
        mid, nb = _SIDE_MID[s_], np.array(_SIDE_OUT[s_], float)
        v = float((C[:2] - mid) @ nb)
        delta = ID1_THICK_MM * max(v, 0.0) / (D0 + ID1_THICK_MM)       # mm, face plane
        if delta <= 0:
            continue
        d_img = _jac(H_face, mid) @ nb                                  # image px per mm outward
        n_l, c_l = lines[s_]
        sgn = 1.0 if float(n_l @ d_img) > 0 else -1.0                   # n_l . x grows outward when sgn > 0
        lines[s_] = (n_l, c_l - sgn * abs(float(n_l @ d_img)) * delta / 2)
        side_sig_px[s_] = abs(float(n_l @ d_img)) * delta / math.sqrt(12)
    if side_sig_px:
        if recovered is not None:
            toward = stats[(recovered + 1) % 4]["_inl_P"].mean(0)
            rec = recover_side([ln if i != recovered else None for i, ln in enumerate(lines)], recovered, f, bgr.shape, toward)
            if rec is not None:
                lines[recovered] = rec
        Qn = _corners_from_lines(lines)
        if Qn is not None:
            Q = Qn
    H_face, corner_rms = pnp_homography(Q, f, bgr.shape)
    # flatness / consistency test with the focal actually used: a quad that only fits a flat ID-1 rectangle with a
    # focal far from the one used would extrapolate the scale wrongly (synthetic gross errors of 8-16 % otherwise)
    flat_rms = corner_rms
    R, t, C = pose_from_homography(H_face, f, bgr.shape)
    ppm = math.sqrt(abs(np.linalg.det(_jac(H_face, (ID1_W_MM / 2, ID1_H_MM / 2)))))
    tilt = float(math.degrees(math.acos(min(1.0, abs(R[2, 2])))))
    D = float(abs(C[2]))
    k = D / (D + ID1_THICK_MM)
    F = C[:2]
    A = np.array([[k, 0, (1 - k) * F[0]], [0, k, (1 - k) * F[1]], [0, 0, 1.0]])
    H_wall = H_face @ A
    H_wall /= H_wall[2, 2]
    card_poly = [_apply_h(H_face, [(-3, -3), (ID1_W_MM + 3, -3), (ID1_W_MM + 3, ID1_H_MM + 3), (-3, ID1_H_MM + 3)]).tolist()]

    # The 4 lines should be the image of a flat 85.60 x 53.98 rectangle: their corners' misfit to the PnP rectangle
    # (bent card, shadow or side wall on one edge, lens distortion) is added to the per-edge systematic budget.
    corner_rms_mm = corner_rms / max(ppm, 1e-6)
    p_mc = replace(p, edge_sys_mm=math.sqrt(p.edge_sys_mm ** 2 + corner_rms_mm ** 2))
    Hs = _mc_homographies(lines, fits, stats, recovered, A, ppm, blur, bgr.shape, p_mc, np.random.default_rng(7), side_sig_px,
                          (fsrc, f))
    u_thick = 0.3 * ID1_THICK_MM / max(D, 1.0)          # face -> wall correction, with a +-30 % focal uncertainty
    edges = []
    for s in range(4):
        st = stats[s]
        e_ = {kk: v for kk, v in (st or {}).items() if not kk.startswith("_")}
        e_.update({"edge": s, "image_side": _image_side(H_face, s),
                   "status": "rebuilt" if s == recovered else ("ok" if _supported(st, p) else "partial")})
        if st is None:
            e_["coverage"] = 0.0
        edges.append(e_)
    occluded = [e_ for e_ in edges if e_["status"] != "ok"]
    det = IdCardDetection(
        spec=ID1, H_img_from_board=H_wall, H_img_from_card_face=H_face / H_face[2, 2], img_pts=Q, obj_pts=_OBJ.copy(),
        reproj_rms_px=rms, px_per_mm=ppm, tilt_deg=tilt, focal_px=f, focal_source=fsrc, camera_distance_mm=D,
        thickness_scale=k, aspect_measured=aspect,
        corner_cut_mm=_corner_cut(cv2.GaussianBlur(roi, (0, 0), 0.6), off, H_face, ppm),
        blur_sigma_px=blur, edges=edges, unc_terms={"iso": ISO_SIZE_REL_SIGMA, "thickness": u_thick, "fit": 0.0},
        scale_rel_unc=0.0, confidence=0.0, H_samples=Hs, recovered_edge=recovered, corner_rms_px=corner_rms,
        corner_support=[round(c, 2) for c in out["corners"]],
        occluded_edges=[{"edge": e_["edge"], "image_side": e_["image_side"], "status": e_["status"],
                         "coverage": e_["coverage"]} for e_ in occluded])
    det.unc_terms["fit"] = det._fit_term((ID1_W_MM / 2, ID1_H_MM / 2))
    det.scale_rel_unc = det.scale_rel_unc_at((ID1_W_MM / 2, ID1_H_MM / 2))
    min_cov = min(e_["coverage"] for e_ in edges if e_["status"] != "rebuilt")
    det.confidence = float(np.clip(min(1.0, min_cov / 0.85) * min(1.0, ppm / 4.0)
                                   * (1.0 if rms < 0.6 else max(0.3, 0.6 / rms))
                                   * (1.0 if recovered is None else 0.6)
                                   * max(0.3, 1.0 - aspect_err / (2 * p.aspect_tol)), 0, 1))
    rep.quality = {"card_px_per_mm": round(ppm, 3), "tilt_deg_est": round(tilt, 2), "card_corners": 4,
                   "card_reproj_rms_px": round(rms, 3), "scale_rel_unc": round(det.scale_rel_unc, 5),
                   "reference_confidence": round(det.confidence, 3),
                   "card_occluded_edges": [e_["image_side"] for e_ in occluded]}
    if blur is not None:
        rep.quality["blur_sigma_px"] = round(blur, 3)

    # ---- acceptance (first failing reason wins; order = what the user should fix first)
    margin = 3.0
    worst = min(occluded, key=lambda e_: e_["coverage"]) if occluded else None
    if sum(c >= 0.5 for c in out["corners"]) < 2:
        rep.status, rep.detail = "card_not_found", "a rectangle of card proportions without rounded card corners"
    elif np.any(Q[:, 0] < margin) or np.any(Q[:, 1] < margin) or np.any(Q[:, 0] > w - 1 - margin) or np.any(Q[:, 1] > h - 1 - margin):
        rep.status, rep.detail = "card_cut_by_frame", "a card corner is at or outside the photo border"
    elif ppm < p.min_px_per_mm:
        rep.status, rep.detail = "card_too_small", f"{ppm:.1f} px/mm < {p.min_px_per_mm} px/mm"
    elif tilt > p.max_tilt_deg:
        rep.status, rep.detail = "card_too_oblique", f"estimated tilt {tilt:.0f} deg > {p.max_tilt_deg:.0f}"
    elif flat_rms / max(ppm, 1e-6) > p.max_corner_rms_mm:
        rep.status = "card_not_flat"
        rep.detail = (f"the outline is not a flat ID-1 rectangle: corners {flat_rms / ppm:.2f} mm off "
                      f"(bent card, card lifted off the wall, or something straight along an edge)")
    elif (np.nanmean(np.asarray(out["corners"], float)) < 0.75 if np.isfinite(out["corners"]).any() else True) \
            and aspect_err > 0.01:
        # weak rounded-corner evidence AND proportions off by > 1 % (ID-1 is +-0.15 %): the outline is probably the
        # card plus something next to it (a crack lip, a joint); refusing is better than a scale off by several %
        rep.status = "card_occluded"
        rep.detail = (f"outline not reliably the card's (rounded corners weak, proportions off by {100 * aspect_err:.1f} %)")
    elif out.get("side_suspect"):
        s_ = out["side_suspect"][0]
        rep.status = "card_occluded"
        rep.detail = (f"the {_image_side(H_face, s_)} edge found is not the card's (wall on both sides of it): edge "
                      "hidden, damaged or too faint")
        rep.quality["card_occluded_edge"] = _image_side(H_face, s_)
    elif out["corner_fail"]:
        rep.status = "card_occluded"
        names = [_image_corner(H_face, k) for k in out["corner_fail"]]
        rep.detail = "no rounded card corner where expected (" + ", ".join(names) + "): hidden, or the outline is not the card's"
        rep.quality["card_occluded_corners"] = names
    elif det.scale_rel_unc > p.max_scale_rel_unc:
        rep.status = "card_occluded" if worst is not None else "card_not_flat"
        rep.detail = (f"scale uncertainty {100 * det.scale_rel_unc:.1f} % > {100 * p.max_scale_rel_unc:.1f} %"
                      + (f"; {worst['image_side']} edge visible on {100 * worst['coverage']:.0f} % of its length" if worst else ""))
    elif any(st is not None and fits[s] is not None and st["sagitta_mm"] > p.max_sagitta_mm and st["sagitta_mm"] > 4 * st["sagitta_sigma_mm"]
             for s, st in enumerate(stats)) or max(stats[s]["robust_sigma_px"] for s in sel) > max(p.max_edge_sigma_px, 0.5 * ppm):
        rep.status = "card_not_flat"
        rep.detail = (f"edge bow up to {max(stats[s]['sagitta_mm'] for s in sel):.2f} mm, edge scatter up to "
                      f"{max(stats[s]['robust_sigma_px'] for s in sel):.2f} px")
    elif recovered is None and aspect_err > p.aspect_tol:
        sk = [stats[s]["skin_frac"] if stats[s] is not None else 0.0 for s in range(4)]
        weak_c = [k for k in range(4) if out["corners"][k] < 0.5]
        if len(weak_c) == 2 and (weak_c[1] - weak_c[0]) in (1, 3):
            # two neighbouring corners without a rounded card corner: a finger (or anything straight) along the
            # side joining them was taken for the card's edge
            s_ = weak_c[0] if weak_c[1] - weak_c[0] == 1 else weak_c[1]
            rep.status = "card_occluded"
            rep.detail = f"something straight along the {edges[s_]['image_side']} edge hides it (card proportions do not match ID-1)"
            worst = edges[s_]
        elif max(sk) >= 0.25:                   # a finger along an edge: its outline was taken for the card's
            s_ = int(np.argmax(sk))
            rep.status = "card_occluded"
            rep.detail = f"a finger seems to cover the {edges[s_]['image_side']} edge (card proportions do not match ID-1)"
            worst = edges[s_]
        else:
            rep.status, rep.detail = "card_wrong_size", f"aspect {aspect:.3f} vs {ID1_ASPECT:.3f} (ID-1)"
    else:
        rep.status = "ok"
        if recovered is not None:
            rep.detail = f"{edges[recovered]['image_side']} edge hidden: rebuilt from the other three (lower confidence)"
    if worst is not None:
        rep.quality["card_occluded_edge"] = worst["image_side"]
    if expected_ppm and not _scale_plausible(H_face, expected_ppm):
        rep.status, rep.detail = "card_not_found", "card-shaped outline at a scale that does not match the wall's"
    # redaction only for an accepted card (all checks passed): never for a refused candidate, which may not be a card
    rep.redact_polys_img = card_poly if rep.status == "ok" else []
    if rep.status != "ok":
        return None, rep
    return det, rep


def _scale_plausible(H, expected_ppm, factor=1.6):
    if not expected_ppm:
        return True
    ppm = math.sqrt(abs(np.linalg.det(_jac(H, (ID1_W_MM / 2, ID1_H_MM / 2)))))
    return expected_ppm / factor <= ppm <= expected_ppm * factor


def _paint_out(img, polys):
    """Fill image polygons with the median colour of a ring around them (hide them from the card search)."""
    out = img.copy()
    for P in polys:
        m = np.zeros(img.shape[:2], np.uint8)
        cv2.fillPoly(m, [np.round(np.asarray(P)).astype(np.int32)], 255)
        m = cv2.dilate(m, np.ones((9, 9), np.uint8))
        ring = cv2.dilate(m, np.ones((31, 31), np.uint8)) & ~m
        col = np.median(img[ring > 0], axis=0) if (ring > 0).any() else np.array([128, 128, 128])
        out[m > 0] = col
    return out


# ------------------------------------------------------------------------------------------------ privacy
def redact_polys(bgr: np.ndarray, polys, block_px: int | None = None) -> np.ndarray:
    """Pixelate then blur each image polygon (card numbers, names). Returns a copy."""
    out = bgr.copy()
    h, w = out.shape[:2]
    for poly in polys:
        P = np.asarray(poly, np.float64).reshape(-1, 2)
        x0, y0 = np.maximum(np.floor(P.min(0)).astype(int) - 2, 0)
        x1, y1 = np.minimum(np.ceil(P.max(0)).astype(int) + 3, [w, h])
        if x1 <= x0 or y1 <= y0:
            continue
        sub = out[y0:y1, x0:x1]
        side = min(x1 - x0, y1 - y0)
        b = block_px or max(4, side // 8)
        small = cv2.resize(sub, (max(1, (x1 - x0) // b), max(1, (y1 - y0) // b)), interpolation=cv2.INTER_AREA)
        pix = cv2.resize(small, (x1 - x0, y1 - y0), interpolation=cv2.INTER_NEAREST)
        pix = cv2.GaussianBlur(pix, (0, 0), max(1.0, b / 2))
        m = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.fillPoly(m, [np.round(P - (x0, y0)).astype(np.int32)], 255, cv2.LINE_AA)
        a = (m.astype(np.float32) / 255.0)[..., None] if sub.ndim == 3 else m.astype(np.float32) / 255.0
        out[y0:y1, x0:x1] = np.clip(sub * (1 - a) + pix * a + 0.5, 0, 255).astype(out.dtype)
    return out


def redact(bgr: np.ndarray, det: IdCardDetection, margin_mm: float = 3.0) -> np.ndarray:
    return redact_polys(bgr, [det.outline_img(margin_mm)], block_px=max(4, int(round(6.0 * det.px_per_mm))))


def redact_reference(bgr: np.ndarray, res) -> np.ndarray:
    """Redact the wallet card of a MeasureResult (kept with keep_debug=True) in a photo before it is rendered,
    returned or stored. ChArUco results are returned unchanged (the printed card holds nothing private)."""
    dbg = getattr(res, "debug", None) or {}
    card = dbg.get("card")
    if isinstance(card, IdCardDetection):
        return redact(bgr, card)
    polys = dbg.get("redact_polys_img")
    return redact_polys(bgr, polys) if polys else bgr

"""CrackWatch measurement pipeline (classic OpenCV 5, no learned model).

detect card (ChArUco) -> homography image<->board (mm) -> quality checks ->
metric rectification -> crack segmentation (background closing + multi-scale Hessian
ridge + hysteresis + shape filters) -> skeleton -> per-point width (sub-pixel profile:
FWHM when resolved, darkness-integral when thinner than the blur) -> per-crack
aggregates + uncertainty + confidence.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from .card import KNOWN_CARDS, CardSpec, make_board

_DETECTORS: dict = {}


# ============================================================== card detection
@dataclass
class CardDetection:
    spec: CardSpec
    n_corners: int
    H_img_from_board: np.ndarray
    reproj_rms_px: float
    img_pts: np.ndarray
    obj_pts: np.ndarray


def _detector(spec):
    if spec.name not in _DETECTORS:
        board = make_board(spec)
        params = cv2.aruco.DetectorParameters()
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        _DETECTORS[spec.name] = (board, cv2.aruco.CharucoDetector(board, cv2.aruco.CharucoParameters(), params))
    return _DETECTORS[spec.name]


def detect_card(gray: np.ndarray, specs=KNOWN_CARDS, min_corners=6) -> CardDetection | None:
    best = None
    for spec in specs:
        board, det = _detector(spec)
        cc, ci, _, _ = det.detectBoard(gray)
        if cc is None or len(cc) < min_corners:
            continue
        obj, img = board.matchImagePoints(cc, ci)
        obj = obj.reshape(-1, 3)[:, :2].astype(np.float64)
        img = img.reshape(-1, 2).astype(np.float64)
        H, inl = cv2.findHomography(obj, img, cv2.USAC_MAGSAC, 1.5)
        if H is None:
            continue
        inl = inl.ravel().astype(bool)
        if inl.sum() >= 8:   # least-squares polish on inliers
            H, _ = cv2.findHomography(obj[inl], img[inl], 0)
        proj = cv2.perspectiveTransform(obj.reshape(-1, 1, 2), H).reshape(-1, 2)
        rms = float(np.sqrt(np.mean(np.sum((proj - img) ** 2, axis=1)[inl])))
        cand = CardDetection(spec, int(inl.sum()), H / H[2, 2], rms, img, obj)
        if best is None or cand.n_corners > best.n_corners:
            best = cand
    return best


def apply_h(H, pts):
    pts = np.asarray(pts, np.float64).reshape(-1, 1, 2)
    return cv2.perspectiveTransform(pts, H).reshape(-1, 2)


def jacobian(H, pt):
    x, y = pt
    e = 0.25
    p = apply_h(H, [(x, y), (x + e, y), (x, y + e)])
    return np.column_stack([(p[1] - p[0]) / e, (p[2] - p[0]) / e])


def local_scale(H, pt):
    return math.sqrt(abs(np.linalg.det(jacobian(H, pt))))


# ============================================================== quality
def estimate_quality(gray: np.ndarray, card: CardDetection | None) -> dict:
    g = gray.astype(np.float32)
    q = {"saturated_frac": float(np.mean(gray >= 250)),
         "dark_frac": float(np.mean(gray <= 8)),
         "laplacian_var": float(cv2.Laplacian(g, cv2.CV_32F).var())}
    if card is None:
        return q
    # Blur estimate from the card's step edges: for a Gaussian-blurred step of contrast C
    # the peak gradient is C / (sigma*sqrt(2*pi)).
    # saturation on the wall only (the white card paper may legitimately clip)
    x0, y0, x1, y1 = card.spec.paper_rect_in_board_frame()
    paper = apply_h(card.H_img_from_board, [(x0 - 3, y0 - 3), (x1 + 3, y0 - 3), (x1 + 3, y1 + 3), (x0 - 3, y1 + 3)])
    wall = np.ones(gray.shape, np.uint8)
    cv2.fillConvexPoly(wall, np.round(paper).astype(np.int32), 0)
    q["saturated_frac_card_incl"] = q["saturated_frac"]
    q["saturated_frac"] = float(np.mean(gray[wall > 0] >= 250)) if wall.any() else 0.0
    hull = cv2.convexHull(card.img_pts.astype(np.float32)).astype(np.int32)
    m = np.zeros(gray.shape, np.uint8)
    cv2.fillConvexPoly(m, hull, 1)
    vals = g[m > 0]
    C = float(np.percentile(vals, 95) - np.percentile(vals, 5))
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3) / 8.0
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3) / 8.0
    gm = np.sqrt(gx * gx + gy * gy)[m > 0]
    G = float(np.percentile(gm, 99.5))
    sigma = C / (G * math.sqrt(2 * math.pi)) if G > 0 else float("inf")
    c = card.obj_pts.mean(0)
    q.update({"card_contrast": C, "blur_sigma_px": float(sigma),
              "card_px_per_mm": float(local_scale(card.H_img_from_board, c)),
              "tilt_deg_est": tilt_from_homography(card.H_img_from_board, gray.shape),
              "card_corners": card.n_corners, "card_reproj_rms_px": card.reproj_rms_px})
    return q


def tilt_from_homography(H, shape, focal_factor=0.85):
    """Angle between the optical axis and the wall normal, assuming a phone-like focal
    length f = focal_factor * max(w, h) and a centred principal point (no EXIF yet)."""
    h, w = shape[:2]
    f = focal_factor * max(w, h)
    K = np.array([[f, 0, w / 2 - 0.5], [0, f, h / 2 - 0.5], [0, 0, 1]])
    M = np.linalg.inv(K) @ H
    r1 = M[:, 0] / np.linalg.norm(M[:, 0])
    r2 = M[:, 1] / np.linalg.norm(M[:, 1])
    nrm = np.cross(r1, r2)
    return float(math.degrees(math.acos(min(1.0, abs(nrm[2]) / np.linalg.norm(nrm)))))


# ============================================================== rectification
@dataclass
class Rectified:
    gray: np.ndarray            # float32 0..1, board-frame metric image
    valid: np.ndarray           # bool, inside the photo
    search: np.ndarray          # bool, where cracks are searched
    R: float                    # rectified px per mm
    origin: tuple               # board mm of pixel (0,0) centre minus 0.5/R
    native_ppm: np.ndarray      # photo px per mm, per rectified px
    H_img_from_rect: np.ndarray

    def px_to_mm(self, uv):
        uv = np.asarray(uv, np.float64)
        return np.column_stack([self.origin[0] + (uv[:, 0] + 0.5) / self.R, self.origin[1] + (uv[:, 1] + 0.5) / self.R])

    def mm_to_px(self, xy):
        xy = np.asarray(xy, np.float64).reshape(-1, 2)
        return np.column_stack([(xy[:, 0] - self.origin[0]) * self.R - 0.5, (xy[:, 1] - self.origin[1]) * self.R - 0.5])


def rectify(gray: np.ndarray, card: CardDetection, R: float | None = None, extent=None,
            exclude_rects_mm=(), max_pixels=9e6, card_margin_mm=4.0, paper_rect_mm=None) -> Rectified:
    h, w = gray.shape
    H = card.H_img_from_board
    Hinv = np.linalg.inv(H)
    gy, gx = np.mgrid[0:h:h / 12, 0:w:w / 16]
    grid_img = np.column_stack([gx.ravel(), gy.ravel()])
    grid_b = apply_h(Hinv, grid_img)
    scales = np.array([local_scale(H, p) for p in grid_b])
    if extent is None:
        corners_b = apply_h(Hinv, [(0, 0), (w, 0), (w, h), (0, h)])
        x0, y0 = np.maximum(corners_b.min(0), -350)
        x1, y1 = np.minimum(corners_b.max(0), 450)
        extent = (float(x0), float(y0), float(x1), float(y1))
    x0, y0, x1, y1 = extent
    if R is None:
        R = float(np.clip(1.25 * np.percentile(scales, 75), 2.0, 16.0))
    R = float(min(R, math.sqrt(max_pixels / max((x1 - x0) * (y1 - y0), 1.0))))
    W, Hh = int(math.ceil((x1 - x0) * R)), int(math.ceil((y1 - y0) * R))
    S = np.array([[1 / R, 0, x0 + 0.5 / R], [0, 1 / R, y0 + 0.5 / R], [0, 0, 1]])
    H_ir = H @ S
    g = gray.astype(np.float32) / 255.0
    rect = cv2.warpPerspective(g, H_ir, (W, Hh), flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP,
                               borderMode=cv2.BORDER_REPLICATE)
    valid = cv2.warpPerspective(np.ones((h, w), np.uint8), H_ir, (W, Hh),
                                flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP, borderValue=0) > 0
    # native resolution map (coarse, then resized)
    cy, cx = np.mgrid[0:Hh:max(1, Hh // 24), 0:W:max(1, W // 32)]
    pts_mm = np.column_stack([x0 + (cx.ravel() + 0.5) / R, y0 + (cy.ravel() + 0.5) / R])
    nat = np.array([local_scale(H, p) for p in pts_mm], np.float32).reshape(cx.shape)
    native = cv2.resize(nat, (W, Hh), interpolation=cv2.INTER_LINEAR)
    search = valid.copy()
    px0, py0, px1, py1 = paper_rect_mm or card.spec.paper_rect_in_board_frame()
    rects = [(px0 - card_margin_mm, py0 - card_margin_mm, px1 + card_margin_mm, py1 + card_margin_mm)]
    rects += [(a - 1, b - 1, c + 1, d + 1) for a, b, c, d in exclude_rects_mm]
    for a, b, c, d in rects:
        u0, v0 = int(max(0, (a - x0) * R)), int(max(0, (b - y0) * R))
        u1, v1 = int(min(W, (c - x0) * R + 1)), int(min(Hh, (d - y0) * R + 1))
        if u1 > u0 and v1 > v0:
            search[v0:v1, u0:u1] = False
    # far-away, heavily foreshortened parts are not measurable: require >= 1.5 px/mm
    search &= native >= 1.5
    return Rectified(rect, valid, search, R, (x0, y0), native, H_ir)


# ============================================================== segmentation
def _fill_masked(img, mask, sigma):
    m = mask.astype(np.float32)
    num = cv2.GaussianBlur(img * m, (0, 0), sigma)
    den = cv2.GaussianBlur(m, (0, 0), sigma)
    filled = num / np.maximum(den, 1e-4)
    out = img.copy()
    out[~mask] = filled[~mask]
    return out


def hessian_ridge(rel, R, sigmas_mm=(0.2, 0.4, 0.8, 1.4, 2.2)):
    """Multi-scale ridge strength for bright ridges in `rel` (= relative darkness).
    Returns strength, best sigma (px) and unit normal (nx, ny) of the ridge."""
    best = np.zeros_like(rel)
    best_s = np.zeros_like(rel)
    nx = np.zeros_like(rel)
    ny = np.zeros_like(rel)
    for s_mm in sigmas_mm:
        s = max(0.8, s_mm * R)
        g = cv2.GaussianBlur(rel, (0, 0), s)
        dxx = cv2.Sobel(g, cv2.CV_32F, 2, 0, ksize=3)
        dyy = cv2.Sobel(g, cv2.CV_32F, 0, 2, ksize=3)
        dxy = cv2.Sobel(g, cv2.CV_32F, 1, 1, ksize=3) / 4.0
        half_tr = (dxx + dyy) / 2
        disc = np.sqrt(((dxx - dyy) / 2) ** 2 + dxy ** 2)
        l1 = half_tr - disc                   # most negative eigenvalue
        l2 = half_tr + disc
        rb = np.abs(l2) / (np.abs(l1) + 1e-9)
        resp = (s * s) * np.maximum(0, -l1) * np.exp(-(rb ** 2) / (2 * 0.5 ** 2))
        upd = resp > best
        # eigenvector of l1: (dxy, l1 - dxx) or (l1 - dyy, dxy)
        ex = dxy
        ey = l1 - dxx
        alt = np.abs(ex) + np.abs(ey) < 1e-9
        ex = np.where(alt, l1 - dyy, ex)
        ey = np.where(alt, dxy, ey)
        nrm = np.sqrt(ex * ex + ey * ey) + 1e-12
        best = np.where(upd, resp, best)
        best_s = np.where(upd, s, best_s)
        nx = np.where(upd, ex / nrm, nx)
        ny = np.where(upd, ey / nrm, ny)
    return best, best_s, nx, ny


def thin(mask: np.ndarray) -> np.ndarray:
    """Zhang-Suen thinning (vectorised numpy). Uses cv2.ximgproc.thinning if present."""
    if hasattr(cv2, "ximgproc"):
        return cv2.ximgproc.thinning(mask.astype(np.uint8) * 255) > 0
    img = np.pad(mask.astype(np.uint8), 1)
    while True:
        changed = False
        for step in (0, 1):
            P = img
            p2, p3, p4 = P[:-2, 1:-1], P[:-2, 2:], P[1:-1, 2:]
            p5, p6, p7 = P[2:, 2:], P[2:, 1:-1], P[2:, :-2]
            p8, p9 = P[1:-1, :-2], P[:-2, :-2]
            nb = [p2, p3, p4, p5, p6, p7, p8, p9]
            B = sum(n.astype(np.int16) for n in nb)
            A = sum(((nb[i] == 0) & (nb[(i + 1) % 8] == 1)).astype(np.int16) for i in range(8))
            if step == 0:
                c = (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
            else:
                c = (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)
            rm = (P[1:-1, 1:-1] == 1) & (B >= 2) & (B <= 6) & (A == 1) & c
            if rm.any():
                img[1:-1, 1:-1][rm] = 0
                changed = True
        if not changed:
            break
    return img[1:-1, 1:-1] > 0


_N8 = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def _is_true_junction(sk, y, x, removed):
    """A pixel with >= 3 neighbours is a real junction only if, once the traced branch is removed,
    its remaining neighbours form >= 2 separate groups (a staircase corner of a thin line does not)."""
    h, w = sk.shape
    patch = np.zeros((3, 3), np.uint8)
    for dy, dx in _N8:
        yy, xx = y + dy, x + dx
        if 0 <= yy < h and 0 <= xx < w and sk[yy, xx] and (yy, xx) not in removed:
            patch[dy + 1, dx + 1] = 1
    n, _ = cv2.connectedComponents(patch, connectivity=8)
    return n - 1 >= 2


def prune_spurs(sk, resp, hi, R, short_mm=4.0, weak_mm=12.0, passes=8, scale=None, wide_ratio=2.0):
    """Remove side branches of a skeleton: terminal branches shorter than `short_mm`; terminal
    branches shorter than `weak_mm` whose median ridge response is below the strong threshold `hi`
    (texture glued to the crack by the hysteresis/closing); and terminal branches shorter than
    1.5 x `weak_mm` whose ridge scale is > `wide_ratio` x the trunk's (a side branch much wider
    than the trunk is a dark blob, not a crack branch). Lines without junctions are kept."""
    sk = sk.copy()
    h, w = sk.shape
    s_med = float(np.median(scale[sk])) if scale is not None and sk.any() else None
    max_trace = 1.5 * weak_mm
    for _ in range(passes):
        k = np.ones((3, 3), np.float32)
        k[1, 1] = 0
        nb = cv2.filter2D(sk.astype(np.float32), -1, k, borderType=cv2.BORDER_CONSTANT)
        ends = np.argwhere(sk & (nb == 1))
        changed = False
        for y0, x0 in ends:
            if not sk[y0, x0]:
                continue
            path, seen, cur = [(y0, x0)], {(y0, x0)}, (y0, x0)
            hit_junction = False
            while True:
                nxt = [(cur[0] + dy, cur[1] + dx) for dy, dx in _N8
                       if 0 <= cur[0] + dy < h and 0 <= cur[1] + dx < w and sk[cur[0] + dy, cur[1] + dx]
                       and (cur[0] + dy, cur[1] + dx) not in seen]
                if not nxt:
                    break
                if len(nxt) >= 2 or nb[nxt[0]] >= 3:
                    j = nxt[0] if len(nxt) == 1 else cur
                    if _is_true_junction(sk, j[0], j[1], seen if j != cur else set(path[:-1])):
                        hit_junction = True
                        if j == cur:
                            path.pop()
                        break
                cur = nxt[0]
                path.append(cur)
                seen.add(cur)
                if len(path) * 1.08 / R > max_trace:
                    break
            if not hit_junction or not path:
                continue
            L = len(path) * 1.08 / R
            ys, xs = zip(*path)
            wide = s_med is not None and float(np.median(scale[list(ys), list(xs)])) > wide_ratio * s_med
            if L < short_mm or (L < weak_mm and float(np.median(resp[list(ys), list(xs)])) < hi) or (L < max_trace and wide):
                sk[list(ys), list(xs)] = False
                changed = True
        if not changed:
            break
    # pruning can leave detached pieces of a removed branch: keep the main piece, and other pieces
    # only when they are long and strong on their own
    n, lab = cv2.connectedComponents(sk.astype(np.uint8), connectivity=8)
    if n > 2:
        sizes = np.bincount(lab.ravel())[1:]
        main = 1 + int(np.argmax(sizes))
        for L in range(1, n):
            if L == main:
                continue
            m = lab == L
            if sizes[L - 1] * 1.08 / R < weak_mm or float(np.median(resp[m])) < hi:
                sk[m] = False
    return sk


@dataclass
class SegParams:
    bg_mm: float = 12.0          # background window (must exceed the widest crack x 2)
    k_high: float = 7.0          # strong threshold = median + k * MAD of ridge response
    k_low: float = 3.5
    rel_min: float = 0.06        # strong seeds must be >= 6 % darker than their background
    min_contrast: float = 0.18   # median relative darkness along the skeleton
    min_resp_ratio: float = 1.0  # ridge response along the skeleton (percentile below) / strong threshold
    resp_percentile: float = 50.0  # 50 = median of the ridge response along the (pruned) skeleton
    prune_short_mm: float = 0.0     # spur pruning, OFF by default (tuning set: max-width MAE 0.266->0.251 but crack coverage 0.85->0.75); try 4.0
    prune_weak_mm: float = 12.0     # ... and weak side branches shorter than this
    gap_mm: float = 0.8          # bridge small gaps in the weak mask
    min_length_mm: float = 6.0
    min_elongation: float = 6.0  # length / ridge-scale width
    # thresholds above were tuned on synthetic seeds 1000-1169 (see TECH.md); the reported
    # accuracy comes from a held-out set generated with other seeds
    joint_straightness: float = 0.985
    joint_min_length_mm: float = 60.0


def background(G, R, bg_mm):
    """Local background by a large median (8-bit histogram median: O(1) per pixel)."""
    g8 = np.clip(G * 255 + 0.5, 0, 255).astype(np.uint8)
    k = int(bg_mm * R) | 1
    f = 1.0
    if k > 99:                       # keep the kernel small: median on a downscaled copy
        f = 99.0 / k
        small = cv2.resize(g8, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        bg = cv2.medianBlur(small, 99)
        bg = cv2.resize(bg, (G.shape[1], G.shape[0]), interpolation=cv2.INTER_LINEAR)
    else:
        bg = cv2.medianBlur(g8, max(3, k))
    return cv2.GaussianBlur(bg.astype(np.float32) / 255.0, (0, 0), max(1.0, 0.5 * R))


def segment(rect: Rectified, p: SegParams = SegParams()):
    R = rect.R
    G = _fill_masked(rect.gray, rect.valid, 3 * R)
    bg = background(G, R, p.bg_mm)
    rel_s = (bg - G) / np.maximum(bg, 1e-3)              # signed relative darkness
    rel = np.clip(rel_s, 0, 1)
    resp, best_s, nx, ny = hessian_ridge(rel_s, R)
    search = cv2.erode(rect.search.astype(np.uint8), np.ones((3, 3), np.uint8), iterations=max(1, int(1.5 * R))) > 0
    vals = resp[search]
    if vals.size == 0:
        return None
    med = float(np.median(vals))
    mad = float(np.median(np.abs(vals - med))) + 1e-9
    hi, lo = med + p.k_high * mad, med + p.k_low * mad
    weak = ((resp > lo) & search).astype(np.uint8)
    gk = max(3, int(p.gap_mm * R) | 1)
    weak = cv2.morphologyEx(weak, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (gk, gk))) & search
    strong = (resp > hi) & (rel > p.rel_min) & search
    n, lab, stats, _ = cv2.connectedComponentsWithStats(weak.astype(np.uint8), connectivity=8)
    keep_lab = np.unique(lab[strong])
    keep_lab = keep_lab[keep_lab > 0]
    comps = []
    skel_all = np.zeros(weak.shape, bool)
    rejected = []
    for L in keep_lab:
        x, y, w, h, area = stats[L]
        if max(w, h) < p.min_length_mm * R * 0.7:
            rejected.append({"label": int(L), "reject": "short", "length_mm": max(w, h) / R})
            continue
        sub = lab[y:y + h, x:x + w] == L
        sk = thin(sub)
        if p.prune_short_mm > 0:
            sk = prune_spurs(sk, resp[y:y + h, x:x + w], hi, R, p.prune_short_mm, p.prune_weak_mm,
                             scale=best_s[y:y + h, x:x + w])
        ys, xs = np.nonzero(sk)
        pts = np.column_stack([xs + x, ys + y]).astype(np.float64)
        length_mm = len(pts) * 1.08 / R
        width_mm = float(np.median(best_s[pts[:, 1].astype(int), pts[:, 0].astype(int)])) * 2.5 / R
        contrast = float(np.median(rel[pts[:, 1].astype(int), pts[:, 0].astype(int)]))
        resp_ratio = float(np.percentile(resp[pts[:, 1].astype(int), pts[:, 0].astype(int)], p.resp_percentile)) / hi
        elong = length_mm / max(width_mm, 0.1)
        info = {"label": int(L), "length_mm": length_mm, "width_est_mm": width_mm, "elongation": elong,
                "contrast": contrast, "resp_ratio": resp_ratio, "bbox_px": (int(x), int(y), int(w), int(h))}
        if length_mm < p.min_length_mm or elong < p.min_elongation:
            info["reject"] = "short_or_blob"
            rejected.append(info)
            continue
        if contrast < p.min_contrast or resp_ratio < p.min_resp_ratio:
            info["reject"] = "low_contrast"
            rejected.append(info)
            continue
        c = pts - pts.mean(0)
        ev, evec = np.linalg.eigh(c.T @ c / len(c))
        proj = c @ evec[:, 1]
        straight = (proj.max() - proj.min()) / R / max(length_mm, 1e-6)
        info["straightness"] = float(straight)
        if length_mm > p.joint_min_length_mm and straight > p.joint_straightness and math.sqrt(ev[0]) / R < 0.6:
            info["reject"] = "straight_joint_suspect"
            rejected.append(info)
            continue
        info["skeleton_px"] = pts
        comps.append(info)
        skel_all[y:y + h, x:x + w] |= sk
    return {"rel": rel, "bg": bg, "G": G, "resp": resp, "best_s": best_s, "nx": nx, "ny": ny,
            "components": comps, "rejected": rejected, "skeleton": skel_all, "thr": (lo, hi)}


# ============================================================== width
# ---- blur model: a crack cross-section is a box of width w and depth Dt, seen through a
# Gaussian PSF of std sigma (measured on the card). Tables are in units of sigma.
_TABLES = None
_AREA_K = 2.5   # area window half-width = FWHM/2 + _AREA_K * sigma (same rule as the tables)


def _erf_antideriv(u):
    return u * math.erf(u) + math.exp(-u * u) / math.sqrt(math.pi)


def blur_tables():
    global _TABLES
    if _TABLES is None:
        xs = np.concatenate([np.linspace(0.02, 6, 300), np.linspace(6.1, 80, 300)])
        r2 = math.sqrt(2)
        fw, pk, aw = [], [], []
        for x in xs:
            a = x / 2
            p = lambda t: 0.5 * (math.erf((t + a) / r2) - math.erf((t - a) / r2))
            peak = p(0.0)
            lo, hi = 0.0, a + 12
            for _ in range(60):
                mid = (lo + hi) / 2
                if p(mid) > peak / 2:
                    lo = mid
                else:
                    hi = mid
            fwhm = 2 * lo
            L = fwhm / 2 + _AREA_K
            area = 0.5 * r2 * (_erf_antideriv((L + a) / r2) - _erf_antideriv((-L + a) / r2)
                               - _erf_antideriv((L - a) / r2) + _erf_antideriv((-L - a) / r2))
            fw.append(fwhm)
            pk.append(peak)
            aw.append(area)
        _TABLES = (xs, np.array(fw), np.array(pk), np.array(aw))
    return _TABLES


def _junction_mask(skel):
    k = np.ones((3, 3), np.float32)
    k[1, 1] = 0
    nb = cv2.filter2D(skel.astype(np.float32), -1, k, borderType=cv2.BORDER_CONSTANT)
    return skel & (nb >= 3)


@dataclass
class WidthParams:
    step_px: float = 0.25
    smooth_px: float = 0.35        # profile smoothing (rect px), part of the model sigma
    interp_sigma_px: float = 0.30  # resampling blur (rectification + remap), rect px
    fwhm_resolved: float = 2.6     # FWHM/sigma above which the width is invertible
    depth_prior: float = 0.65      # true relative darkness assumed when nothing is resolved
    agree_rel: float = 0.35        # max relative disagreement FWHM vs area on resolved points
    outlier_factor: float = 2.0    # wide-and-shallow outliers (stains under a thin crack)
    outlier_depth: float = 0.7


def normal_sigma_mm(H_img_from_board, pts_mm, normals):
    """Blur std (mm per image px) along each board-frame normal: |J^-T n|."""
    e = 0.25
    p0 = apply_h(H_img_from_board, pts_mm)
    px = apply_h(H_img_from_board, pts_mm + [e, 0])
    py = apply_h(H_img_from_board, pts_mm + [0, e])
    J = np.stack([(px - p0) / e, (py - p0) / e], axis=2)          # (n, 2, 2) d img / d board
    Jinv = np.linalg.inv(J)
    v = np.einsum("nji,nj->ni", Jinv, normals)
    return np.linalg.norm(v, axis=1)


def measure_widths(rect: Rectified, seg: dict, sigma_img_px: float, H_img_from_board,
                   wp: WidthParams = WidthParams()):
    xs, fw_t, pk_t, aw_t = blur_tables()
    R = rect.R
    G = seg["G"]
    out = []
    junc = _junction_mask(seg["skeleton"])
    dt = _dt_baseline(seg, rect)
    for comp in seg["components"]:
        pts = comp["skeleton_px"]
        n = len(pts)
        xi, yi = pts[:, 0].astype(int), pts[:, 1].astype(int)
        nxv, nyv = seg["nx"][yi, xi], seg["ny"][yi, xi]
        pts_mm = rect.px_to_mm(pts)
        s_mm = normal_sigma_mm(H_img_from_board, pts_mm, np.column_stack([nxv, nyv]))
        sig = np.sqrt((sigma_img_px * s_mm * R) ** 2 + wp.smooth_px ** 2 + wp.interp_sigma_px ** 2)
        w_est_px = np.median(seg["best_s"][yi, xi]) * 2.5
        T = float(np.clip(2.5 * w_est_px + 1.5 * R + 4 * np.median(sig), 2.0 * R, 16.0 * R))
        t = np.arange(-T, T + 1e-9, wp.step_px, dtype=np.float32)
        mx = (pts[:, 0:1] + nxv[:, None] * t[None, :]).astype(np.float32)
        my = (pts[:, 1:2] + nyv[:, None] * t[None, :]).astype(np.float32)
        prof = cv2.remap(G, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        prof = cv2.GaussianBlur(prof, (0, 0), sigmaX=wp.smooth_px / wp.step_px, sigmaY=1e-3)
        n_s = len(t)
        tail = max(4, int(0.25 * n_s))
        bl = np.median(prof[:, :tail], axis=1)
        br = np.median(prof[:, -tail:], axis=1)
        frac = (t - t[0]) / (t[-1] - t[0])
        bgl = bl[:, None] * (1 - frac[None, :]) + br[:, None] * frac[None, :]
        drel = (bgl - prof) / np.maximum(bgl, 1e-3)
        c0 = n_s // 2
        win = max(2, int(max(1.5, 0.6 * w_est_px) / wp.step_px))
        imin = c0 - win + np.argmax(drel[:, c0 - win:c0 + win + 1], axis=1)
        D = drel[np.arange(n), imin]
        wf = np.full(n, np.nan)
        A = np.full(n, np.nan)
        ok = np.zeros(n, bool)
        for i in range(n):
            d = drel[i]
            m = imin[i]
            if D[i] <= 0.02:
                continue
            half = D[i] / 2
            l = m
            while l > 0 and d[l] > half:
                l -= 1
            r = m
            while r < n_s - 1 and d[r] > half:
                r += 1
            if l == 0 or r == n_s - 1:
                continue
            tl = t[l] + (half - d[l]) / (d[l + 1] - d[l] + 1e-12) * wp.step_px
            tr = t[r - 1] + (d[r - 1] - half) / (d[r - 1] - d[r] + 1e-12) * wp.step_px
            wf[i] = tr - tl
            c = 0.5 * (tl + tr)
            L = wf[i] / 2 + _AREA_K * sig[i]
            sel = np.abs(t - c) <= L
            A[i] = float(d[sel].sum() * wp.step_px)
            ok[i] = abs(c) <= max(1.0, 0.5 * wf[i])        # skeleton must sit on the dark core
        ok &= ~junc[yi, xi]
        if not ok.any():
            continue
        xf = wf / sig
        resolved = ok & (xf >= wp.fwhm_resolved)
        x_fw = np.interp(xf, fw_t, xs)                    # deconvolved width / sigma
        w_fw = x_fw * sig
        Dt = D / np.interp(x_fw, xs, pk_t)                # true (deblurred) relative depth
        def from_area(depth):
            return np.interp(A / (np.maximum(depth, 1e-3) * sig), aw_t, xs) * sig

        def depth_ref(sel):
            if sel.sum() >= max(5, 0.1 * ok.sum()):
                return float(np.clip(np.median(Dt[sel]), 0.05, 1.0)), "resolved"
            return float(min(1.0, max(np.percentile(D[ok], 90), wp.depth_prior))), "prior"

        # Two independent estimators must agree on resolved points: deconvolved FWHM
        # (shape) and darkness integral / depth (area). A profile that runs obliquely or
        # into a neighbouring dark blob inflates the FWHM but not the area -> dropped.
        D_ref, depth_source = depth_ref(resolved)
        w_area = from_area(D_ref)
        agree = np.abs(w_fw - w_area) <= wp.agree_rel * np.maximum(w_fw, w_area) + 0.5
        inconsistent = resolved & ~agree
        resolved &= agree
        ok &= ~inconsistent
        if ok.sum() < 5:
            continue
        D_ref, depth_source = depth_ref(resolved)
        w_area = from_area(D_ref)
        w_px = np.where(resolved, w_fw, w_area)
        # A thin crack crossing a dark stain/pore: much wider than the crack's typical
        # width while much shallower than the crack's own depth -> not crack, dropped.
        w_med = np.median(w_px[ok])
        stain = ok & (w_px > wp.outlier_factor * w_med) & (np.where(resolved, Dt, D) < wp.outlier_depth * D_ref)
        ok &= ~stain
        resolved &= ~stain
        if ok.sum() < 5:
            continue
        native = rect.native_ppm[yi, xi]
        out.append({
            "pts_px": pts[ok], "pts_mm": pts_mm[ok],
            "width_mm": (w_px / R)[ok],
            "width_fwhm_raw_mm": (wf / R)[ok],          # no blur correction (ablation)
            "width_fwhm_mm": (w_fw / R)[ok],            # deconvolved FWHM only
            "width_int_mm": (w_area / R)[ok],           # darkness integral only
            "width_dt_mm": ((2 * dt[yi, xi] - 1) / R)[ok] if dt is not None else None,
            "lower_bound_mm": (from_area(np.ones(n)) / R)[ok],   # if the crack were pitch black
            "resolved": resolved[ok], "native_ppm": native[ok], "sigma_mm": (sig / R)[ok],
            "depth_ref": D_ref, "depth_source": depth_source,
            "length_mm": comp["length_mm"], "n_points_total": int(n),
        })
    return out


def _dt_baseline(seg, rect):
    """Pixel-level baseline: local half-maximum binary mask + distance transform."""
    rel = seg["rel"]
    k = max(3, int(1.5 * rect.R) | 1)
    relmax = cv2.dilate(rel, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    near = cv2.dilate(seg["skeleton"].astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3 * k, 3 * k))) > 0
    mask = (rel > 0.5 * relmax) & (relmax > 0.03) & near
    return cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)


# ============================================================== aggregate
def _local_median(pts, vals, radius):
    """Median of `vals` over neighbours within `radius` (same units as pts)."""
    out = np.empty(len(vals))
    for s0 in range(0, len(pts), 1024):
        d2 = ((pts[s0:s0 + 1024, None, :] - pts[None, :, :]) ** 2).sum(-1)
        nb = d2 <= radius * radius
        v = np.where(nb, vals[None, :], np.nan)
        out[s0:s0 + 1024] = np.nanmedian(v, axis=1)
    return out


def summarize(rect: Rectified, comps, quality, card: CardDetection, smooth_mm=2.0, max_window_mm=6.0, max_percentile=95):
    cracks = []
    for i, c in enumerate(comps):
        w = c["width_mm"]
        if len(w) < 5:
            continue
        p = c["pts_mm"]
        ws = _local_median(p, w, smooth_mm)          # robust along-crack profile
        c["width_smooth_mm"] = ws
        wmax_prof = _local_median(p, w, max_window_mm / 2)   # width sustained over ~6 mm of crack
        c["width_maxprof_mm"] = wmax_prof
        wmax = float(np.percentile(wmax_prof, max_percentile))  # robust "max" (P95, see TECH.md)
        nat = float(np.median(c["native_ppm"]))
        sig_mm = float(np.median(c["sigma_mm"]))
        mad = float(np.median(np.abs(w - ws)))
        res_frac = float(np.mean(c["resolved"]))
        # 1-sigma uncertainty (mm): quantisation + local scatter + depth-model + scale terms
        u_quant = 0.25 / nat
        u_scatter = 1.4826 * mad / math.sqrt(max(1.0, smooth_mm * rect.R / 2))
        u_depth = 0.0 if c["depth_source"] == "resolved" else 0.35 * float(np.median(w))
        u_scale = (card.scale_rel_unc_at(p.mean(0)) if hasattr(card, "scale_rel_unc_at")     # wallet card (idcard.py)
                   else card.reproj_rms_px / max(quality.get("card_px_per_mm", nat) * 15.0, 1e-6)) * float(np.median(w))
        unc = math.sqrt(u_quant ** 2 + u_scatter ** 2 + u_depth ** 2 + u_scale ** 2)
        conf = 1.0
        conf *= min(1.0, nat / 4.0)                                # resolution
        conf *= 0.6 + 0.4 * res_frac                               # deblurred vs prior-based
        conf *= 1.0 if c["depth_source"] == "resolved" else 0.7
        conf *= max(0.2, 1.0 - quality.get("saturated_frac", 0) * 5)
        conf *= card.confidence if hasattr(card, "confidence") else min(1.0, quality.get("card_corners", 24) / 12.0)
        imax = int(np.argmin(np.abs(wmax_prof - wmax)))
        unres = ~c["resolved"]
        focus_pts = p[unres] if unres.sum() >= 5 else p
        fx0, fy0 = focus_pts.min(0)
        fx1, fy1 = focus_pts.max(0)
        cracks.append({
            "id": i, "length_mm": round(float(c["length_mm"]), 1),
            "width_mm": {"median": round(float(np.median(ws)), 3), "mean": round(float(np.mean(w)), 3),
                         "p90": round(float(np.percentile(ws, 90)), 3), "max": round(wmax, 3)},
            "max_location_board_mm": [round(float(v), 1) for v in p[imax]],
            "uncertainty_mm": round(unc, 3), "confidence": round(conf, 2),
            "resolved_fraction": round(res_frac, 2), "depth_source": c["depth_source"],
            "lower_bound_median_mm": round(float(np.median(c["lower_bound_mm"])), 3),
            "native_px_per_mm": round(nat, 2), "blur_sigma_mm": round(sig_mm, 3),
            "min_measurable_mm": round(max(1.5 / nat, 1.3 * sig_mm), 3),
            "bbox_board_mm": [round(float(v), 1) for v in (*p.min(0), *p.max(0))],
            "focus_region_board_mm": [round(float(v), 1) for v in (fx0, fy0, fx1, fy1)],
        })
    cracks.sort(key=lambda d: -d["length_mm"])
    return cracks


@dataclass
class MeasureResult:
    status: str
    quality: dict
    card: dict | None = None
    cracks: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    debug: dict = field(default_factory=dict)

    def to_json(self):
        return {"status": self.status, "quality": self.quality, "card": self.card,
                "cracks": self.cracks, "rejected": [{k: v for k, v in r.items() if k != "skeleton_px"} for r in self.rejected]}


def measure_image(bgr: np.ndarray, exclude_rects_mm=(), R=None, extent=None,
                  seg_params: SegParams = SegParams(), keep_debug=False, paper_rect_mm=None,
                  reference="charuco", focal_px=None) -> MeasureResult:
    """`paper_rect_mm`: board-frame rectangle hidden from the crack search instead of the card's own
    paper (used for the printed test chart, whose board sits on a larger sheet).
    `reference`: "charuco" (printed card), "idcard" (any bank/loyalty card, see idcard.py) or "auto"
    (ChArUco if found, else a wallet card). A wallet card found but unusable gives "reference_rejected"
    with quality["retake_reason"]. `focal_px`: camera focal in pixels of this image if known (EXIF), used by
    the wallet-card reference only."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr
    card = detect_card(gray) if reference != "idcard" else None
    ref = None
    if card is None and reference in ("idcard", "auto"):
        from .idcard import detect_idcard
        card, ref = detect_idcard(bgr, focal_px=focal_px)
    q = estimate_quality(gray, card)
    if ref is not None:
        q.update(ref.quality_fields())
    if card is None:
        res = MeasureResult("reference_rejected" if ref is not None and ref.rejected else "no_card", q)
        if keep_debug and ref is not None:
            res.debug = {"redact_polys_img": ref.redact_polys_img}
        return res
    rect = rectify(gray, card, R=R, extent=extent, exclude_rects_mm=exclude_rects_mm, paper_rect_mm=paper_rect_mm)
    seg = segment(rect, seg_params)
    card_info = {"spec": card.spec.name, "corners": card.n_corners, "reproj_rms_px": round(card.reproj_rms_px, 3),
                 "H_img_from_board": card.H_img_from_board.tolist(), "rectified_px_per_mm": rect.R,
                 "reference": getattr(card, "reference", "charuco")}
    if hasattr(card, "public_info"):
        card_info.update(card.public_info())
    if seg is None:
        return MeasureResult("no_search_area", q, card_info)
    comps = measure_widths(rect, seg, q.get("blur_sigma_px", 1.0), card.H_img_from_board)
    cracks = summarize(rect, comps, q, card)
    res = MeasureResult("ok" if cracks else "no_crack_found", q, card_info, cracks, seg["rejected"])
    if keep_debug:
        res.debug = {"rect": rect, "seg": seg, "comps": comps, "card": card}
    return res

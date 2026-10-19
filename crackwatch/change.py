"""Change detection between two inspections of the same crack.

1. Each photo is measured in its own card (board) frame -> metric, rectified.
2. Registration board(v2) -> board(v1):
   - if the card stayed glued, both frames already coincide (identity);
   - ORB features on the rectified wall texture (card masked out) + cv2.findHomography
     (USAC_MAGSAC) estimate the residual transform; if it is significant (card re-glued or
     replaced) it is used, optionally refined with cv2.findTransformECC.
3. v2 skeleton points are mapped into v1's frame and matched to v1's skeleton with
   cv2.distanceTransformWithLabels -> new crack length and point-wise width deltas.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from .measure import MeasureResult, measure_image, rectify, apply_h


def _rect_u8(rect):
    return np.clip(rect.gray * 255 + 0.5, 0, 255).astype(np.uint8)


def register_texture(rect1, rect2, n_features=6000, use_ecc=True):
    """Estimate T (3x3) mapping board2 mm -> board1 mm from wall texture only."""
    g1, g2 = _rect_u8(rect1), _rect_u8(rect2)
    clahe = cv2.createCLAHE(2.0, (8, 8))
    g1c, g2c = clahe.apply(g1), clahe.apply(g2)
    m1 = (rect1.search & rect1.valid).astype(np.uint8) * 255
    m2 = (rect2.search & rect2.valid).astype(np.uint8) * 255
    orb = cv2.ORB_create(nfeatures=n_features, scaleFactor=1.2, nlevels=8, fastThreshold=10)
    k1, d1 = orb.detectAndCompute(g1c, m1)
    k2, d2 = orb.detectAndCompute(g2c, m2)
    info = {"kp1": len(k1), "kp2": len(k2)}
    if d1 is None or d2 is None or len(k1) < 20 or len(k2) < 20:
        info["status"] = "too_few_features"
        return None, info
    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    knn = bf.knnMatch(d2, d1, k=2)
    good = [m for m, n in (p for p in knn if len(p) == 2) if m.distance < 0.8 * n.distance]
    info["matches"] = len(good)
    if len(good) < 15:
        info["status"] = "too_few_matches"
        return None, info
    p2 = rect2.px_to_mm(np.array([k2[m.queryIdx].pt for m in good]))
    p1 = rect1.px_to_mm(np.array([k1[m.trainIdx].pt for m in good]))
    T, inl = cv2.findHomography(p2, p1, cv2.USAC_MAGSAC, 0.6)
    if T is None:
        info["status"] = "homography_failed"
        return None, info
    info["inliers"] = int(inl.sum())
    info["status"] = "ok" if inl.sum() >= 12 else "weak"
    if use_ecc and info["status"] == "ok":
        T, ecc_info = _refine_ecc(rect1, rect2, T)
        info.update(ecc_info)
    return T, info


def _refine_ecc(rect1, rect2, T, scale_px_per_mm=3.0):
    """Refine T with ECC on a common low-resolution board-frame grid around the overlap."""
    x0 = max(rect1.origin[0], rect2.origin[0])
    y0 = max(rect1.origin[1], rect2.origin[1])
    x1 = min(rect1.origin[0] + rect1.gray.shape[1] / rect1.R, rect2.origin[0] + rect2.gray.shape[1] / rect2.R)
    y1 = min(rect1.origin[1] + rect1.gray.shape[0] / rect1.R, rect2.origin[1] + rect2.gray.shape[0] / rect2.R)
    if x1 - x0 < 30 or y1 - y0 < 30:
        return T, {"ecc": "no_overlap"}
    s = scale_px_per_mm
    W, H = int((x1 - x0) * s), int((y1 - y0) * s)
    S = np.array([[1 / s, 0, x0], [0, 1 / s, y0], [0, 0, 1]])           # grid px -> board1 mm

    def sample(rect, M_mm):  # M_mm: grid board-mm -> rect board-mm
        P = np.array([[rect.R, 0, -rect.origin[0] * rect.R - 0.5], [0, rect.R, -rect.origin[1] * rect.R - 0.5], [0, 0, 1]])
        M = P @ M_mm @ S
        img = cv2.warpPerspective(rect.gray, M, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP)
        msk = cv2.warpPerspective((rect.search & rect.valid).astype(np.uint8), M, (W, H), flags=cv2.INTER_NEAREST | cv2.WARP_INVERSE_MAP)
        # band-pass: ECC is only invariant to a global gain/bias, not to lighting gradients
        img = cv2.GaussianBlur(img, (0, 0), 1.0) - cv2.GaussianBlur(img, (0, 0), 8.0)
        return img, msk

    a, ma = sample(rect1, np.eye(3))
    b, mb = sample(rect2, np.linalg.inv(T))
    warp = np.eye(3, dtype=np.float32)
    try:
        # OpenCV 5: inputMask and gaussFiltSize are positional and mandatory
        cc, warp = cv2.findTransformECC(a, b, warp, cv2.MOTION_HOMOGRAPHY,
                                        (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-6), (ma & mb), 5)
    except cv2.error as e:
        return T, {"ecc": "failed: " + " ".join(str(e).split())[-160:]}
    # warp maps grid(a) coords -> grid(b) coords; b was sampled with inv(T)
    Wmm = S @ warp.astype(np.float64) @ np.linalg.inv(S)                # board1 mm -> (T^-1-warped) mm
    T_new = np.linalg.inv(np.linalg.inv(T) @ Wmm)
    return T_new / T_new[2, 2], {"ecc": "ok", "ecc_cc": float(cc)}


def _transform_size_mm(T, pts):
    return float(np.max(np.linalg.norm(apply_h(T, pts) - pts, axis=1)))


def compare(res1: MeasureResult, res2: MeasureResult, match_tol_mm=1.5, card_moved_tol_mm=0.4):
    """Compare two measured inspections (measure_image(..., keep_debug=True))."""
    if res1.status != "ok" or res2.status != "ok":
        return {"status": "cannot_compare", "reason": f"v1={res1.status}, v2={res2.status}"}
    r1, r2 = res1.debug["rect"], res2.debug["rect"]
    c1, c2 = res1.debug["comps"], res2.debug["comps"]
    pts1 = np.vstack([c["pts_mm"] for c in c1])
    w1 = np.concatenate([c["width_smooth_mm"] for c in c1])
    pts2 = np.vstack([c["pts_mm"] for c in c2])
    w2 = np.concatenate([c["width_smooth_mm"] for c in c2])
    T_tex, reg = register_texture(r1, r2)
    T = np.eye(3)
    reg["mode"] = "card_frame"
    if T_tex is not None and reg["status"] == "ok":
        motion = _transform_size_mm(T_tex, pts2)
        reg["texture_motion_mm"] = round(motion, 3)
        if motion > card_moved_tol_mm:
            T = T_tex
            reg["mode"] = "texture_homography"
    p2in1 = apply_h(T, pts2)
    # match v2 points to v1 skeleton with a labelled distance transform on a 0.1 mm grid
    s = 10.0
    allp = np.vstack([pts1, p2in1])
    o = allp.min(0) - 5
    size = (allp.max(0) + 5 - o) * s
    Wd, Hd = int(size[0]) + 1, int(size[1]) + 1
    canvas = np.ones((Hd, Wd), np.uint8)
    q1 = np.round((pts1 - o) * s).astype(int)
    canvas[q1[:, 1], q1[:, 0]] = 0
    dist, labels = cv2.distanceTransformWithLabels(canvas, cv2.DIST_L2, cv2.DIST_MASK_PRECISE, labelType=cv2.DIST_LABEL_PIXEL)
    # label -> v1 point index
    lab_of_pt = labels[q1[:, 1], q1[:, 0]]
    lut = np.full(labels.max() + 1, -1)
    lut[lab_of_pt] = np.arange(len(q1))
    q2 = np.clip(np.round((p2in1 - o) * s).astype(int), 0, [Wd - 1, Hd - 1])
    d2 = dist[q2[:, 1], q2[:, 0]] / s
    j = lut[labels[q2[:, 1], q2[:, 0]]]
    tol = np.maximum(match_tol_mm, 0.75 * w2)
    matched = (d2 <= tol) & (j >= 0)
    # "new" crack = v2 points far from v1's skeleton AND without ridge evidence in the v1
    # image at that place (v1 may simply have missed a faint segment).
    seg1 = res1.debug["seg"]
    uv = r1.mm_to_px(p2in1)
    h1, w1_ = seg1["resp"].shape
    inside = (uv[:, 0] >= 1) & (uv[:, 0] < w1_ - 1) & (uv[:, 1] >= 1) & (uv[:, 1] < h1 - 1)
    ev = np.zeros(len(uv), bool)
    if inside.any():
        k = max(3, int(1.0 * r1.R) | 1)
        resp_max = cv2.dilate(seg1["resp"], np.ones((k, k), np.uint8))
        ui, vi = uv[inside, 0].astype(int), uv[inside, 1].astype(int)
        ev[inside] = resp_max[vi, ui] > seg1["thr"][0]
    new = ~matched & inside & ~ev
    dw = w2[matched] - w1[j[matched]]
    new_len = float(new.sum()) * 1.08 / r2.R
    n_eff = max(1.0, matched.sum() / (2.0 * r2.R))           # ~1 independent sample per 2 mm
    mad = float(np.median(np.abs(dw - np.median(dw)))) if dw.size else 0.0
    u_delta = math.sqrt((1.4826 * mad / math.sqrt(n_eff)) ** 2 + 0.04 ** 2)
    max1 = max(c["width_mm"]["max"] for c in res1.cracks)
    max2 = max(c["width_mm"]["max"] for c in res2.cracks)
    out = {
        "status": "ok", "registration": reg,
        "T_board1_from_board2": T.tolist(),
        "matched_fraction_v2": round(float(matched.mean()), 3),
        "width_delta_mm": {"median": round(float(np.median(dw)), 3) if dw.size else None,
                           "p90": round(float(np.percentile(dw, 90)), 3) if dw.size else None,
                           "max_width_v1": max1, "max_width_v2": max2,
                           "max_delta": round(max2 - max1, 3)},
        "new_length_mm": round(new_len, 1),
        "delta_uncertainty_mm": round(u_delta, 3),
    }
    med = out["width_delta_mm"]["median"] or 0.0
    out["significant_widening"] = bool(med > max(0.1, 2 * u_delta))
    out["significant_growth"] = bool(new_len > 4.0)
    return out


def compare_images(bgr1, bgr2, **kw):
    r1 = measure_image(bgr1, keep_debug=True)
    r2 = measure_image(bgr2, keep_debug=True)
    return r1, r2, compare(r1, r2, **kw)

"""Scoring helpers: match measured skeleton points to the synthetic ground truth."""
from __future__ import annotations

import numpy as np


def nearest(a: np.ndarray, b: np.ndarray):
    """For each point of a (n,2), index and distance of the nearest point of b (m,2)."""
    if len(b) == 0 or len(a) == 0:
        return np.zeros(len(a), int), np.full(len(a), np.inf)
    idx = np.empty(len(a), int)
    dist = np.empty(len(a))
    for s in range(0, len(a), 2048):
        d2 = ((a[s:s + 2048, None, :] - b[None, :, :]) ** 2).sum(-1)
        j = d2.argmin(1)
        idx[s:s + 2048] = j
        dist[s:s + 2048] = np.sqrt(d2[np.arange(len(j)), j])
    return idx, dist


def gt_points(gt_cracks, search_ok=None):
    pts, w, br = [], [], []
    for c in gt_cracks:
        p = np.asarray(c["pts_board_mm"])
        v = np.asarray(c["visible"], bool)
        pts.append(p[v])
        w.append(np.asarray(c["width_mm"])[v])
        br.append(np.full(v.sum(), c["branch"]))
    pts = np.vstack(pts) if pts else np.zeros((0, 2))
    w = np.concatenate(w) if w else np.zeros(0)
    br = np.concatenate(br) if br else np.zeros(0, bool)
    if search_ok is not None and len(pts):
        keep = search_ok(pts)
        pts, w, br = pts[keep], w[keep], br[keep]
    return pts, w, br


def score(gt_cracks, comps, search_ok=None):
    """Point-wise and crack-level errors. `comps` = measure_widths() output."""
    gp, gw, _ = gt_points(gt_cracks, search_ok)
    if len(gp) == 0:
        return {"skipped": "no_visible_gt"}
    if not comps:
        return {"detected": False, "recall": 0.0, "gt_max": float(gw.max()), "gt_median": float(np.median(gw))}
    mp = np.vstack([c["pts_mm"] for c in comps])
    keys = ["width_mm", "width_smooth_mm", "width_maxprof_mm", "width_fwhm_raw_mm", "width_fwhm_mm", "width_int_mm", "width_dt_mm"]
    mw = {k: np.concatenate([c[k] if c.get(k) is not None else np.full(len(c["pts_mm"]), np.nan) for c in comps]) for k in keys}
    resolved = np.concatenate([c["resolved"] for c in comps])
    j, d = nearest(mp, gp)
    tol = np.maximum(1.0, 0.75 * gw[j])
    matched = d <= tol
    _, dg = nearest(gp, mp)
    recall = float(np.mean(dg <= np.maximum(1.0, 0.75 * gw)))
    precision = float(np.mean(matched))
    out = {"detected": bool(matched.sum() >= 10), "recall": recall, "precision": precision,
           "n_matched": int(matched.sum()), "gt_max": float(gw.max()), "gt_median": float(np.median(gw)),
           "resolved_frac": float(resolved[matched].mean()) if matched.any() else 0.0}
    if matched.sum() >= 10:
        for k in keys:
            e = mw[k][matched] - gw[j[matched]]
            e = e[np.isfinite(e)]
            if e.size:
                out[f"pt_mae_{k}"] = float(np.mean(np.abs(e)))
                out[f"pt_bias_{k}"] = float(np.mean(e))
        w = mw["width_smooth_mm"][matched]
        out["meas_max"] = float(np.percentile(mw["width_maxprof_mm"][matched], 95))
        out["meas_median"] = float(np.median(w))
        # compare max over the same (matched) GT points to avoid visibility mismatch
        gm = gw[j[matched]]
        out["gt_max_matched"] = float(gm.max())
        out["gt_median_matched"] = float(np.median(gm))
        out["err_max"] = out["meas_max"] - out["gt_max_matched"]
        out["err_median"] = out["meas_median"] - out["gt_median_matched"]
    return out

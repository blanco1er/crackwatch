"""Which of the measured ridges is THE crack the user is photographing.

A real wall shows several dark ridges: the crack, mortar joints, a wall edge, small stains. The user glues
or holds the card ON or next to the crack (protocol: 0 to 10 cm), and the card often covers part of it, so
the crack comes out in pieces on both sides of the card. Selection therefore works in the card frame:

1. Link fragments that continue each other across the card (the crack passes under it).
2. Score every candidate (fragment or linked group) by physical evidence:
   - proximity to the card sheet: weight 1 / (1 + (d / 100 mm)^2), i.e. half weight at the protocol's
     10 cm limit;
   - length inside the monitoring area (card sheet + 100 mm);
   - darkness of its own interior (deblurred relative depth, measure.measure_widths): an open crack is a
     cavity that light barely reaches, whereas joints, edges and stains are surface features of moderate
     darkness; the score uses depth^2;
   - man-made straightness: a ridge whose centreline stays within 1 mm (RMS) of a straight line over at
     least 50 mm is a joint, an edge or a pipe (cracks follow the aggregate and wander by more); its score
     is divided by 4. The 1 mm / 50 mm figures are the same order as measure.SegParams' straight-joint
     filter (lateral spread < 0.6 mm over > 60 mm), relaxed because a wide ridge's skeleton has spurs.
3. Order res.cracks by score; the first one is the main crack. The user can still pick another one.
"""
from __future__ import annotations

import math

import numpy as np


ZONE_MM = 100.0            # protocol: card at most 10 cm from the crack (= measure.ZONE_MARGIN_MM)
PROX_MM = 100.0
STRAIGHT_RMS_MM = 1.0
STRAIGHT_MIN_MM = 50.0
STRAIGHT_FACTOR = 0.25
LINK_MIN_CHORD_MM = 15.0
LINK_TOUCH_MM = 15.0       # a fragment "reaches the card" if it comes this close to the sheet (mask margin + erosion ~ 6 mm)


def _rect_dist(P, r):
    x0, y0, x1, y1 = r
    dx = np.maximum(0, np.maximum(x0 - P[:, 0], P[:, 0] - x1))
    dy = np.maximum(0, np.maximum(y0 - P[:, 1], P[:, 1] - y1))
    return np.hypot(dx, dy)


def _axis(P):
    c = P.mean(0)
    d = P - c
    ev, vec = np.linalg.eigh(d.T @ d / max(len(d), 1))
    return c, vec[:, 1], vec[:, 0]


def centreline_wander_mm(P, bin_mm=5.0):
    """RMS distance of the crack's centreline from its best straight line. The centreline is the median
    lateral offset in 5 mm bins along the principal axis (robust to skeleton spurs). Returns (rms, chord)."""
    c, u, n = _axis(P)
    s, t = (P - c) @ u, (P - c) @ n
    chord = float(s.max() - s.min())
    b = np.floor((s - s.min()) / bin_mm).astype(int)
    xs, ys = [], []
    for k in np.unique(b):
        m = b == k
        if m.sum() >= 3:
            xs.append(float(np.median(s[m])))
            ys.append(float(np.median(t[m])))
    if len(xs) < 3:
        return float("inf"), chord
    A = np.column_stack([xs, np.ones(len(xs))])
    coef, *_ = np.linalg.lstsq(A, np.array(ys), rcond=None)
    return float(np.sqrt(np.mean((np.array(ys) - A @ coef) ** 2))), chord


def _near_end(P, paper):
    """Point of the fragment closest to the card sheet and the fragment's direction near it (fitted on the
    part within 30 mm of that point)."""
    d = _rect_dist(P, paper)
    e = P[int(np.argmin(d))]
    near = P[np.linalg.norm(P - e, axis=1) <= 30.0]
    _, u, _ = _axis(near if len(near) >= 5 else P)
    return e, u, float(d.min())


def _side(p, paper):
    x0, y0, x1, y1 = paper
    ex = {"left": x0 - p[0], "right": p[0] - x1, "top": y0 - p[1], "bottom": p[1] - y1}
    return max(ex, key=ex.get)


def link_across_card(comps, paper):
    """Groups of comp indices that continue each other across the card sheet. Two fragments are linked when
    both reach the sheet at OPPOSITE edges (top/bottom or left/right: the crack runs under the card), and at least one
    of them, extended along its own direction across the gap, passes within 5 mm + 15 % of the gap of the
    other's near end. Each fragment must span >= 15 mm (shorter pieces have no defined direction). Only one side is required: a crack can bend where it leaves the card (on the owner's
    render crack the lower piece turns by ~45 degrees right at the card edge), and a wide crack's skeleton
    spurs blur the local direction."""
    n = len(comps)
    ends = [(_near_end(c["pts_mm"], paper) if len(c["pts_mm"]) >= 5 and centreline_wander_mm(c["pts_mm"])[1] >= LINK_MIN_CHORD_MM
             else None) for c in comps]
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    x0, y0, x1, y1 = paper
    for i in range(n):
        for j in range(i + 1, n):
            if ends[i] is None or ends[j] is None or ends[i][2] > LINK_TOUCH_MM or ends[j][2] > LINK_TOUCH_MM:
                continue
            (ei, ui, _), (ej, uj, _) = ends[i], ends[j]
            gap = ej - ei
            L = float(np.linalg.norm(gap))
            if L < 1e-6:
                continue
            if {_side(ei, paper), _side(ej, paper)} not in ({"left", "right"}, {"top", "bottom"}):
                continue                                   # not on opposite edges of the card
            tol = 5.0 + 0.15 * L
            off_i = abs(float(gap @ np.array([-ui[1], ui[0]])))   # lateral offset of j's end from i's line
            off_j = abs(float(gap @ np.array([-uj[1], uj[0]])))
            if off_i <= tol or off_j <= tol:
                parent[find(j)] = find(i)
    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def _merge(comps, idx):
    if len(idx) == 1:
        return comps[idx[0]]
    keys = ("pts_px", "pts_mm", "width_mm", "width_fwhm_raw_mm", "width_fwhm_mm", "width_int_mm", "lower_bound_mm",
            "resolved", "native_ppm", "sigma_mm")
    m = {k: np.concatenate([comps[i][k] for i in idx]) for k in keys if all(comps[i].get(k) is not None for i in idx)}
    srcs = [comps[i]["depth_source"] for i in idx]
    m.update({"length_mm": float(sum(comps[i]["length_mm"] for i in idx)),
              "depth_ref": float(np.average([comps[i]["depth_ref"] for i in idx], weights=[len(comps[i]["pts_mm"]) for i in idx])),
              "depth_source": "resolved" if all(s == "resolved" for s in srcs) else "prior",
              "n_points_total": int(sum(comps[i].get("n_points_total", 0) for i in idx)),
              "part_sizes": [len(comps[i]["pts_mm"]) for i in idx]})
    return m


def _clip_to_zone(c, paper):
    """Keep the points within ZONE_MM of the card sheet: that is the monitoring zone, and the only part of the
    wall where the card's plane (the homography) is known to hold. A ridge network that runs on for half a
    metre (joints, a pipe) does not then inflate the crack's statistics. Candidates entirely outside are kept
    whole (they score 0)."""
    P = c["pts_mm"]
    x0, y0, x1, y1 = paper
    m = (P[:, 0] > x0 - ZONE_MM) & (P[:, 0] < x1 + ZONE_MM) & (P[:, 1] > y0 - ZONE_MM) & (P[:, 1] < y1 + ZONE_MM)
    if m.all() or m.sum() < 5:
        return c
    n = len(P)
    out = {k: (v[m] if isinstance(v, np.ndarray) and len(v) == n else v) for k, v in c.items()}
    out["length_mm"] = c["length_mm"] * float(m.mean())
    if c.get("part_sizes"):
        o, sizes = 0, []
        for k in c["part_sizes"]:
            sizes.append(int(m[o:o + k].sum()))
            o += k
        out["part_sizes"] = [k for k in sizes if k > 0]
    out.pop("width_smooth_mm", None)
    out.pop("width_maxprof_mm", None)
    return out


def score_candidate(comp, paper):
    P = comp["pts_mm"]
    x0, y0, x1, y1 = paper
    d = float(_rect_dist(P, paper).min())
    inz = ((P[:, 0] > x0 - ZONE_MM) & (P[:, 0] < x1 + ZONE_MM) & (P[:, 1] > y0 - ZONE_MM) & (P[:, 1] < y1 + ZONE_MM))
    L_zone = comp["length_mm"] * float(inz.mean())
    depth = float(np.clip(comp.get("depth_ref", 0.5), 0.0, 1.0))
    wander, chord = centreline_wander_mm(P)
    straight = chord >= STRAIGHT_MIN_MM and wander < STRAIGHT_RMS_MM
    prox = 1.0 / (1.0 + (d / PROX_MM) ** 2)
    score = prox * L_zone * depth ** 2 * (STRAIGHT_FACTOR if straight else 1.0)
    return score, {"card_dist_mm": round(d, 1), "zone_length_mm": round(L_zone, 1), "depth": round(depth, 2),
                   "wander_mm": round(wander, 2) if math.isfinite(wander) else None, "chord_mm": round(chord, 1),
                   "straight": bool(straight)}


def select_cracks(comps, rect, quality, card, cam_c=None):
    """Link fragments across the card, summarise each candidate and order them by score (best first).
    Returns (candidate comps, crack dicts); crack["id"] indexes the returned comps. Each crack dict gets
    `score`, `selection` (the evidence) and `parts` (indices of the original fragments)."""
    comps = [c for c in comps if len(c["pts_mm"]) >= 5]
    if not comps:
        return comps, []
    paper = card.spec.paper_rect_in_board_frame()
    groups = link_across_card(comps, paper)
    merged = [_clip_to_zone(_merge(comps, g), paper) for g in groups]
    from .measure import summarize
    cracks = summarize(rect, merged, quality, card, cam_c=cam_c)
    for cr in cracks:
        k = cr["id"]
        sc, ev = score_candidate(merged[k], paper)
        cr.update({"score": round(sc, 2), "selection": ev, "parts": [int(i) for i in groups[k]]})
    cracks.sort(key=lambda c: -c["score"])
    return merged, cracks

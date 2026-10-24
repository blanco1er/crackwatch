"""Measurement stations: fixed, labelled points on the crack, re-measured at the same place at every visit
(like a surveyor's gauge points).

- `make_stations`: on one crack, STATION_COUNT points evenly spaced along its traced length (inside the
  monitoring zone, the crack's points are already limited to it), plus the point of maximum sustained width
  (it replaces the nearest station when closer than max(MERGE_MM, a third of the spacing), so pins never pile up). Positions are in board millimetres (card frame), the frame
  that stays attached to the wall when the printed card stays glued.
- `measure_at_stations`: a later photo is measured AT those board positions (mapped through the visit-to-
  visit alignment), never elsewhere. A station outside the new photo, or with no crack within reach, is
  reported `not_visible`: nothing is invented. Each change is tested like a crack stretch in change.py
  (same per-photo systematic error model, Bonferroni over the visible stations, >= 0.1 mm).
"""
from __future__ import annotations

import math
import string
from statistics import NormalDist

import numpy as np

from .change import ALPHA, MIN_CHANGE_MM, SYS_ABS_MM, _u_sys
from .measure import apply_h

STATION_COUNT = 5
LOCAL_MM = 2.0          # width at a station = median over +-2 mm of crack around it
MERGE_MM = 5.0
MAX_STATIONS = 12


def _centreline(comp, bin_mm=2.0):
    """Centreline of the crack in board mm: each fragment binned every 2 mm along its own principal axis
    (median point per bin, robust to the skeleton's side spurs), fragments in order along the whole crack.
    Returns (points (n,2), arc length (n,)); the jump between fragments (e.g. under the card) adds no length."""
    P = comp["pts_mm"]
    sizes = comp.get("part_sizes") or [len(P)]
    c0 = P.mean(0)
    _, v0 = np.linalg.eigh((P - c0).T @ (P - c0))
    u0 = v0[:, 1]
    parts, o = [], 0
    for n in sizes:
        q = P[o:o + n]
        o += n
        if n < 3:
            continue
        c = q.mean(0)
        _, v = np.linalg.eigh((q - c).T @ (q - c))
        u = v[:, 1] if v[:, 1] @ u0 >= 0 else -v[:, 1]
        t = (q - c) @ u
        b = np.floor((t - t.min()) / bin_mm).astype(int)
        line = np.array([np.median(q[b == k], axis=0) for k in np.unique(b)])
        parts.append((float((c - c0) @ u0), line))
    parts.sort(key=lambda x: x[0])
    pts, arc, s0 = [], [], 0.0
    for _, line in parts:
        seg = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(line, axis=0), axis=1))])
        pts.append(line)
        arc.append(s0 + seg)
        s0 += seg[-1]
    return np.vstack(pts), np.concatenate(arc)


def _local(P, W, p, radius=LOCAL_MM):
    d = np.linalg.norm(P - p, axis=1)
    m = d <= radius
    if m.sum() < 3:
        m = d <= 2 * radius
    w = W[m]
    med = float(np.median(w))
    mad = float(np.median(np.abs(w - med)))
    # A station is found again only to within about its own +-2 mm window (card or texture alignment, and the
    # point snapped to the skeleton), so its width is one draw from the widths of that window: the spread is
    # NOT divided by the number of points. Where the crack narrows or widens sharply, the station is uncertain.
    u_stat = 1.4826 * mad
    return med, u_stat, int(m.sum())


def make_stations(comp, crack, n=STATION_COUNT):
    """Stations on one crack (comp = its measure_widths/selection dict, crack = its summary dict)."""
    P, W = comp["pts_mm"], np.asarray(comp["width_mm"], float)
    if len(P) < 10:
        return []
    Q, s = _centreline(comp)
    total = float(s[-1]) if len(s) else 0.0
    if total < 1.0:
        return []
    picks = [int(np.argmin(np.abs(s - (k + 0.5) / n * total))) for k in range(n)]
    snap = lambda p: P[int(np.argmin(np.linalg.norm(P - p, axis=1)))]          # noqa: E731  (a real crack point)
    st = [{"arc": float(s[i]), "p": snap(Q[i]), "is_max": False} for i in sorted(set(picks))]
    mx = np.asarray(crack.get("max_location_board_mm") or [], float)
    if mx.size == 2:
        j = int(np.argmin(np.linalg.norm(Q - mx, axis=1)))
        d = [float(np.linalg.norm(x["p"] - Q[j])) for x in st]
        k = int(np.argmin(d))
        if d[k] < max(MERGE_MM, total / n / 3):      # closer than a third of the spacing: that station becomes the max
            st[k].update(p=snap(mx), arc=float(s[j]), is_max=True)
        else:
            st.append({"arc": float(s[j]), "p": snap(mx), "is_max": True})
    st.sort(key=lambda x: x["arc"])
    out = []
    prior = comp.get("depth_source") != "resolved"
    for i, x in enumerate(st[:MAX_STATIONS]):
        w, u_stat, npts = _local(P, W, x["p"])
        u = math.hypot(u_stat, _u_sys(w, prior, SYS_ABS_MM))
        out.append({"id": string.ascii_uppercase[i], "board_mm": [round(float(v), 2) for v in x["p"]],
                    "arc_mm": round(x["arc"], 1), "width_mm": round(w, 3), "u_mm": round(u, 3), "is_max": x["is_max"]})
    return out


def _valid_station(st):
    try:
        b = [float(v) for v in st["board_mm"]]
        w = float(st["width_mm"])
        u = float(st.get("u_mm", 0.1))
        sid = str(st["id"])[:2]
    except (KeyError, TypeError, ValueError, IndexError):
        return None
    if len(b) != 2 or not all(math.isfinite(v) and abs(v) < 2000 for v in b) or not (0 < w < 100) or not (0 <= u < 50):
        return None
    return {"id": sid, "board_mm": b, "width_mm": w, "u_mm": u, "is_max": bool(st.get("is_max"))}


def clean_stations(stations):
    """Validate stations sent back by the client (small, public data: positions in card mm and widths)."""
    if not isinstance(stations, list):
        return []
    out = [s for s in (_valid_station(x) for x in stations[:MAX_STATIONS] if isinstance(x, dict)) if s]
    return out


def measure_at_stations(res, prev_stations, T_board1_from_board2=None, registration="card_frame"):
    """Re-measure a new photo (res = measure_image(..., keep_debug=True)) at previous stations."""
    stations = clean_stations(prev_stations)
    if not stations:
        return {"status": "no_stations"}
    if res.status != "ok":
        return {"status": "cannot_compare", "reason": res.status}
    rect, comps = res.debug["rect"], res.debug.get("comps") or []
    if not comps:
        return {"status": "cannot_compare", "reason": "no_crack"}
    T = np.eye(3) if T_board1_from_board2 is None else np.asarray(T_board1_from_board2, float)
    Tinv = np.linalg.inv(T)
    # Measure on ONE crack of the new photo, the one that passes by the most stations (the tracked crack),
    # so that a station is never read on a neighbouring joint or side branch.
    P2 = [apply_h(Tinv, [st["board_mm"]])[0] for st in stations]
    def hits(c):
        return sum(float(np.min(np.linalg.norm(c["pts_mm"] - p, axis=1))) <= max(1.5, 0.75 * st["width_mm"])
                   for p, st in zip(P2, stations))
    best = max(comps, key=hits)
    P = best["pts_mm"]
    W = np.asarray(best["width_mm"], float)
    prior = np.full(len(P), best.get("depth_source") != "resolved")
    h, w_ = rect.valid.shape
    rows = []
    for st in stations:
        p2 = apply_h(Tinv, [st["board_mm"]])[0]
        uv = rect.mm_to_px([p2])[0]
        ui, vi = int(round(uv[0])), int(round(uv[1]))
        row = {"id": st["id"], "is_max": st["is_max"], "board_mm": [round(float(v), 2) for v in st["board_mm"]],
               "board_mm_now": [round(float(v), 2) for v in p2], "prev_width_mm": round(st["width_mm"], 3)}
        if not (0 <= ui < w_ and 0 <= vi < h) or not rect.valid[vi, ui]:
            rows.append(dict(row, status="not_visible", reason="outside_photo"))
            continue
        d = np.linalg.norm(P - p2, axis=1)
        j = int(np.argmin(d))
        if d[j] > max(1.5, 0.75 * st["width_mm"]):
            rows.append(dict(row, status="not_visible", reason="no_crack_here"))
            continue
        wn, u_stat, _ = _local(P, W, P[j])
        u_new = math.hypot(u_stat, _u_sys(wn, bool(prior[j]), SYS_ABS_MM))
        delta = wn - st["width_mm"]
        u = math.hypot(st["u_mm"], u_new)
        rows.append(dict(row, status="ok", width_mm=round(wn, 3), u_mm=round(u_new, 3), delta_mm=round(delta, 3),
                         u_delta_mm=round(u, 3), z=round(delta / max(u, 1e-9), 2)))
    ok = [r for r in rows if r["status"] == "ok"]
    # The model error above was calibrated on synthetic walls; on a real ragged crack two photos taken minutes
    # apart can differ by more at one point (viewing angle, a chipped lip). The stations of the pair measure it:
    # the robust spread of their changes around their median (an "empirical null": most points of a crack do
    # not change between two photos, and a uniform widening shifts all of them without spreading them) is added
    # to every station's uncertainty. Needs >= 3 visible stations.
    s_emp = 0.0
    if len(ok) >= 3:
        d = np.array([r["delta_mm"] for r in ok])
        s_emp = 1.4826 * float(np.median(np.abs(d - np.median(d))))
    for r in ok:
        r["u_delta_mm"] = round(math.hypot(r["u_delta_mm"], s_emp), 3)
        r["z"] = round(r["delta_mm"] / max(r["u_delta_mm"], 1e-9), 2)
    z_crit = NormalDist().inv_cdf(1 - ALPHA / max(1, len(ok)))      # one-sided, Bonferroni over visible stations
    for r in ok:
        r["significant"] = bool(r["z"] > z_crit and r["delta_mm"] >= MIN_CHANGE_MM)
    return {"status": "ok" if ok else "none_visible", "registration": registration, "z_critical": round(z_crit, 2),
            "pair_spread_mm": round(s_emp, 3),
            "stations": rows, "n_visible": len(ok), "n_significant": sum(r["significant"] for r in ok)}


def as_comparison(sc):
    """Station result in the shape the agent reads from change.compare (stations-only follow-up)."""
    ok = [r for r in sc.get("stations", []) if r["status"] == "ok"]
    if sc.get("status") != "ok" or not ok:
        return {"status": "cannot_compare", "reason": sc.get("reason") or sc.get("status")}
    sig = [r for r in ok if r["significant"]]
    best = max(sig, key=lambda r: r["delta_mm"]) if sig else None
    deltas = [r["delta_mm"] for r in ok]
    return {"status": "ok", "registration": {"mode": sc["registration"]}, "source": "stations",
            "width_delta_mm": {"median": round(float(np.median(deltas)), 3), "p90": round(float(np.percentile(deltas, 90)), 3)},
            "delta_uncertainty_mm": round(float(np.median([r["u_delta_mm"] for r in ok])), 3),
            "new_length_mm": 0.0, "significant_growth": False, "significant_widening": bool(sig),
            "widening_mm": best["delta_mm"] if best else None,
            "widening_location_board_mm": best["board_mm"] if best else None, "widening_scope": "station" if best else None}

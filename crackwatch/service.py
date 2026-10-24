"""One inspection = measure (OpenCV 5) -> agent loop (Nova 2 Lite on Bedrock, validated by the rules)
-> optional comparison with the previous visit -> ticket waiting for a human, or a request for a
better photo. Shared by the Lambda API (deploy/app.py) and the local server (scripts/serve_local.py)."""
from __future__ import annotations

import base64
import math
import time
import uuid

import cv2
import numpy as np

from .agent import AgentState, RulePlanner, run_agent
from .change import compare
from .card import KNOWN_CARDS
from .idcard import ID1, ID1_H_MM, ID1_W_MM, IdCardDetection, detect_idcard, redact_polys
from .measure import apply_h, measure_image
from .stations import as_comparison, clean_stations, measure_at_stations

MAX_SIDE = 4032          # longer photo side kept for measurement (12 MP phone photos pass unchanged)
OVERLAY_SIDE = 1400


def decode_image(data: bytes) -> np.ndarray:
    """JPEG/PNG bytes -> BGR. Decoding keeps pixels only: EXIF, GPS and maker notes are dropped."""
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("not_an_image")
    h, w = img.shape[:2]
    if min(h, w) < 480:
        raise ValueError("image_too_small")
    s = MAX_SIDE / max(h, w)
    if s < 1:
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    return img


# Width colour scale, ABSOLUTE so a colour means the same width on every photo (web/app.js widthColor mirrors it):
# log scale from 0.2 mm (warm yellow) to 5 mm and more (deep red), the "fine" and "wide" ends of the verdict scale.
W_COLOR_MIN_MM, W_COLOR_MAX_MM = 0.2, 5.0


def _width_t(w_mm: float) -> float:
    w = max(float(w_mm), 1e-6)
    return float(np.clip(math.log(w / W_COLOR_MIN_MM) / math.log(W_COLOR_MAX_MM / W_COLOR_MIN_MM), 0, 1))


def focal_px_from_35mm(focal_35mm, shape):
    """EXIF FocalLengthIn35mmFilm -> focal in pixels of this image (35 mm equivalence is on the diagonal,
    43.27 mm). The app reads it before upload, since decoding drops EXIF. None if absent or implausible."""
    try:
        f = float(focal_35mm)
    except (TypeError, ValueError):
        return None
    if not 10.0 <= f <= 200.0:
        return None
    h, w = shape[:2]
    return f / 43.27 * math.hypot(w, h)


def _width_color(t: float):
    # sequential: warm yellow (thin) -> deep red (wide), BGR
    a = np.array([60, 200, 255], np.float32)
    b = np.array([40, 30, 215], np.float32)
    c = a + (b - a) * float(np.clip(t, 0, 1))
    return tuple(int(v) for v in c)


def render_overlay(bgr: np.ndarray, res, focus_region_mm=None, marks=True) -> bytes:
    """Photo + what OpenCV found: card corners, crack skeleton coloured by width, the max location,
    and (active perception) the region the agent wants re-photographed. JPEG bytes.
    marks=False: the same photo (same size, same darkening, card outline only) for the app, which draws the
    candidates and the measurement stations itself as crisp vector graphics on top of it."""
    s = min(1.0, OVERLAY_SIDE / max(bgr.shape[:2]))
    out = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else bgr.copy()
    out = cv2.addWeighted(out, 0.82, np.full_like(out, 255), 0.0, -12)   # slightly darker to lift the marks
    dbg = getattr(res, "debug", {}) or {}
    card = dbg.get("card")
    lw = max(2, int(round(out.shape[1] / 600)))
    if card is not None:
        H = card.H_img_from_board
        x0, y0, x1, y1 = card.spec.paper_rect_in_board_frame()
        poly = apply_h(H, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]) * s
        cv2.polylines(out, [np.round(poly).astype(np.int32)], True, (255, 200, 120), lw, cv2.LINE_AA)
        if not marks:
            ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 82])
            return buf.tobytes()
        for p in card.img_pts * s:
            cv2.circle(out, (int(p[0]), int(p[1])), lw + 1, (255, 170, 60), -1, cv2.LINE_AA)
        comps = dbg.get("comps") or []
        for c in comps:
            pts = apply_h(H, c["pts_mm"]) * s
            w = c.get("width_smooth_mm", c["width_mm"])
            for (x, y), wi in zip(pts[::2], w[::2]):
                cv2.circle(out, (int(x), int(y)), lw, _width_color(_width_t(wi)), -1, cv2.LINE_AA)
        if res.cracks:
            cr = res.cracks[0]
            x, y = apply_h(H, [cr["max_location_board_mm"]])[0] * s
            cv2.circle(out, (int(x), int(y)), 6 * lw, (255, 255, 255), lw, cv2.LINE_AA)
        if focus_region_mm:
            fx0, fy0, fx1, fy1 = focus_region_mm
            m = 3.0
            q = apply_h(H, [(fx0 - m, fy0 - m), (fx1 + m, fy0 - m), (fx1 + m, fy1 + m), (fx0 - m, fy1 + m)]) * s
            q = np.round(q).astype(np.int32)
            for i in range(4):   # dashed outline
                p0, p1 = q[i].astype(float), q[(i + 1) % 4].astype(float)
                n = max(2, int(np.linalg.norm(p1 - p0) / (6 * lw)))
                for k in range(0, n, 2):
                    a, b = p0 + (p1 - p0) * k / n, p0 + (p1 - p0) * min(k + 1, n) / n
                    cv2.line(out, tuple(int(v) for v in a), tuple(int(v) for v in b), (255, 255, 255), lw + 1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return buf.tobytes()


def render_before_after(prev_bgr, prev_res, cur_bgr, cur_res, T_board1_from_board2, max_side=960) -> dict | None:
    """Both visits warped into the card frame of the first visit, over the same window around the crack:
    the two JPEGs are pixel-aligned, so the app can lay one over the other (slider).
    Card left in place -> identical frames; card re-glued -> the texture registration T is applied."""
    try:
        c1, c2 = prev_res.debug["card"], cur_res.debug["card"]
        T = np.asarray(T_board1_from_board2, np.float64)
        pts1 = np.vstack([c["pts_mm"] for c in prev_res.debug["comps"]])
        pts2 = apply_h(T, np.vstack([c["pts_mm"] for c in cur_res.debug["comps"]]))
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    allp = np.vstack([pts1, pts2])
    (x0, y0), (x1, y1) = allp.min(0) - 10.0, allp.max(0) + 10.0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2                    # 3:2 window, 45 to 150 mm wide
    wmm = float(min(max(x1 - x0, 1.5 * (y1 - y0), 45.0), 150.0))
    hmm = wmm / 1.5
    x0, y0 = cx - wmm / 2, cy - hmm / 2
    r = max_side / wmm
    W, H = int(round(wmm * r)), int(round(hmm * r))
    A = np.array([[1 / r, 0, x0], [0, 1 / r, y0], [0, 0, 1]], np.float64)     # output px -> board-1 mm
    out = {}
    for name, img, M in (("before", prev_bgr, c1.H_img_from_board @ A),
                         ("after", cur_bgr, c2.H_img_from_board @ np.linalg.inv(T) @ A)):
        warped = cv2.warpPerspective(img, M, (W, H), flags=cv2.INTER_AREA | cv2.WARP_INVERSE_MAP,
                                     borderMode=cv2.BORDER_CONSTANT, borderValue=(40, 40, 40))
        ok, buf = cv2.imencode(".jpg", warped, [cv2.IMWRITE_JPEG_QUALITY, 82])
        out[name + "_jpeg_b64"] = base64.b64encode(buf.tobytes()).decode()
    out.update({"window_board_mm": [round(float(v), 1) for v in (x0, y0, x0 + wmm, y0 + hmm)],
                "px_per_mm": round(float(r), 3), "size_px": [W, H]})
    return out


def render_closeup(bgr, res, max_side=960) -> dict | None:
    """The photo straightened in the card frame and cropped around the crack, with the traced crack coloured by
    width (yellow thin -> red wide) and the widest point ringed: what the app shows as the result photo."""
    try:
        card = res.debug["card"]
        comps = res.debug["comps"]
        pts = np.vstack([c["pts_mm"] for c in comps])
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
    if not len(pts) or not res.cracks:
        return None
    bx0, by0, bx1, by1 = res.cracks[0]["bbox_board_mm"]          # frame the main crack, not every ridge found
    (x0, y0), (x1, y1) = (bx0 - 10.0, by0 - 10.0), (bx1 + 10.0, by1 + 10.0)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    wmm = float(min(max(x1 - x0, 1.5 * (y1 - y0), 45.0), 150.0))
    hmm = wmm / 1.5
    x0, y0 = cx - wmm / 2, cy - hmm / 2
    r = max_side / wmm
    W, H = int(round(wmm * r)), int(round(hmm * r))
    A = np.array([[1 / r, 0, x0], [0, 1 / r, y0], [0, 0, 1]], np.float64)
    out = cv2.warpPerspective(bgr, card.H_img_from_board @ A, (W, H), flags=cv2.INTER_AREA | cv2.WARP_INVERSE_MAP,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=(40, 40, 40))
    lw = max(2, int(round(W / 320)))
    for c in comps:
        w = c.get("width_smooth_mm", c["width_mm"])
        for (px, py), wi in zip((np.asarray(c["pts_mm"]) - (x0, y0)) * r, w):
            cv2.circle(out, (int(px), int(py)), lw, _width_color(_width_t(wi)), -1, cv2.LINE_AA)
    mx, my = (np.asarray(res.cracks[0]["max_location_board_mm"]) - (x0, y0)) * r
    cv2.circle(out, (int(mx), int(my)), 7 * lw, (255, 255, 255), lw + 1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return {"jpeg_b64": base64.b64encode(buf.tobytes()).decode(), "window_board_mm": [round(float(v), 1) for v in (x0, y0, x0 + wmm, y0 + hmm)],
            "px_per_mm": round(float(r), 3), "size_px": [W, H]}


def add_outlines(res, shape) -> None:
    """The main crack is chosen in measure_image (crackwatch/selection.py: card proximity, cavity darkness,
    man-made straightness, fragments linked across the card). Here every candidate gets its outline in overlay
    pixels so the app can draw it and let the user tap another one. A candidate made of fragments on both
    sides of the card has `outline_breaks`: indices where a new fragment starts (no line drawn across the card)."""
    dbg = getattr(res, "debug", None) or {}
    card, comps = dbg.get("card"), dbg.get("comps") or []
    if card is None or not res.cracks:
        return
    h, w = shape[:2]
    centre, diag = np.array([w / 2.0, h / 2.0]), math.hypot(w, h)
    s = min(1.0, OVERLAY_SIDE / max(h, w))
    for cr in res.cracks:
        i = cr.get("id")
        if i is None or i >= len(comps):
            continue
        c = comps[i]
        pts = apply_h(card.H_img_from_board, c["pts_mm"])
        cr["center_dist"] = round(float(np.min(np.linalg.norm(pts - centre, axis=1)) / diag), 3)
        ww = np.asarray(c.get("width_smooth_mm", c["width_mm"]), float)
        sizes = c.get("part_sizes") or [len(pts)]
        line, wl, breaks, o = [], [], [], 0
        for n in sizes:
            seg = slice(o, o + n)
            order = _order_along(pts[seg])
            step = max(1, len(pts) // 80)
            if line:
                breaks.append(len(line))
            line += np.round(pts[seg][order][::step] * s).astype(int).tolist()
            wl += [round(float(v), 2) for v in ww[seg][order][::step]]
            o += n
        cr["outline_px"], cr["outline_w_mm"] = line, wl          # width at each outline point, for colouring
        for st in cr.get("stations") or []:
            st["overlay_px"] = [int(round(v)) for v in apply_h(card.H_img_from_board, [st["board_mm"]])[0] * s]
        if breaks:
            cr["outline_breaks"] = breaks


# ---------------------------------------------------------------- measure first, blur after
# What a later visit needs from this photo, captured BEFORE any redaction: the reference card's geometry and the
# quality measured on it. The comparison then measures the stored (possibly blurred) photo with this geometry and
# never looks for the card again.
_Q_KEEP = ("blur_sigma_px", "card_px_per_mm", "tilt_deg_est", "card_corners", "card_reproj_rms_px", "card_contrast",
           "reference", "reference_status", "scale_rel_unc")


def card_geometry(res, shape) -> dict | None:
    card = (getattr(res, "debug", None) or {}).get("card")
    if card is None:
        return None
    g = {"v": 1, "reference": getattr(card, "reference", "charuco"), "spec": card.spec.name, "shape": [int(shape[0]), int(shape[1])],
         "H_img_from_board": np.asarray(card.H_img_from_board, float).tolist(),
         "img_pts": np.asarray(card.img_pts, float).tolist(), "obj_pts": np.asarray(card.obj_pts, float).tolist(),
         "reproj_rms_px": float(card.reproj_rms_px), "n_corners": int(card.n_corners),
         "quality": {k: res.quality[k] for k in _Q_KEEP if k in res.quality and isinstance(res.quality[k], (int, float, str))}}
    if isinstance(card, IdCardDetection):
        g.update({"H_img_from_card_face": np.asarray(card.H_img_from_card_face, float).tolist(),
                  "px_per_mm": float(card.px_per_mm), "confidence": float(card.confidence)})
    return g


class StoredCard:
    """The reference card of an earlier photo, rebuilt from card_geometry() (duck-types measure.CardDetection)."""

    def __init__(self, g: dict, shape):
        specs = {c.name: c for c in KNOWN_CARDS}
        specs[ID1.name] = ID1
        if g.get("spec") not in specs:
            raise ValueError("unknown card")
        sy, sx = shape[0] / float(g["shape"][0]), shape[1] / float(g["shape"][1])
        if abs(sx - sy) > 0.01:
            raise ValueError("photo aspect changed")
        S = np.diag([sx, sy, 1.0])                         # the stored copy may have been resized
        self.spec = specs[g["spec"]]
        self.reference = g.get("reference", "charuco")
        self.H_img_from_board = S @ np.asarray(g["H_img_from_board"], float)
        self.img_pts = np.asarray(g["img_pts"], float) * [sx, sy]
        self.obj_pts = np.asarray(g["obj_pts"], float)
        self.reproj_rms_px = float(g.get("reproj_rms_px", 0.0)) * sx
        self.n_corners = int(g.get("n_corners", len(self.img_pts)))
        if "H_img_from_card_face" in g:
            self.H_img_from_card_face = S @ np.asarray(g["H_img_from_card_face"], float)
            self.px_per_mm = float(g.get("px_per_mm", 5.0)) * sx
        if "confidence" in g:
            self.confidence = float(g["confidence"])
        self.quality = dict(g.get("quality") or {})


def clean_geometry(g) -> dict | None:
    """A card geometry sent back by the app: shape-checked numbers only, else None."""
    try:
        if not isinstance(g, dict) or g.get("v") != 1:
            return None
        H = np.asarray(g["H_img_from_board"], float)
        P = np.asarray(g["img_pts"], float)
        O = np.asarray(g["obj_pts"], float)
        ok = H.shape == (3, 3) and P.ndim == 2 and P.shape[1] == 2 and O.shape == P.shape and 4 <= len(P) <= 200
        ok &= bool(np.all(np.isfinite(H))) and len(g["shape"]) == 2
        if "H_img_from_card_face" in g:
            ok &= np.asarray(g["H_img_from_card_face"], float).shape == (3, 3)
        q = {k: v for k, v in (g.get("quality") or {}).items() if k in _Q_KEEP and isinstance(v, (int, float, str))}
        return dict(g, quality=q) if ok else None
    except (KeyError, TypeError, ValueError):
        return None


CARD_EDGE_BAND_MM = 2.5     # outline band left sharp so a later visit can find the card again


def redact_card_interior(bgr: np.ndarray, det: IdCardDetection, band_mm: float = CARD_EDGE_BAND_MM) -> np.ndarray:
    """Pixelate + blur the card face INSIDE a 2.5 mm band along its edges (card frame, through the card-face
    homography). The band keeps the straight edges and the rounded corners the detector needs, so the stored copy
    of a visit can be measured again at the next one; on the owner's real photos (8 cards, 4.7-9.6 px/mm) nothing
    readable is left in it (numbers, name, chip and logos are further in)."""
    b = band_mm
    poly = apply_h(det.H_img_from_card_face, [(b, b), (ID1_W_MM - b, b), (ID1_W_MM - b, ID1_H_MM - b), (b, ID1_H_MM - b)])
    return redact_polys(bgr, [poly], block_px=max(4, int(round(6.0 * det.px_per_mm))))


def redact_cards(bgr: np.ndarray, res, focal_px=None) -> np.ndarray:
    """Every bank / ID-1 card in the photo is blurred before any image is returned or stored, WHATEVER reference
    measured the scale: when the printed ChArUco card is the reference, a wallet card lying next to it would
    otherwise stay readable. The ID-1 detector runs for redaction only (the printed sheet is hidden from it).
    A detected card is blurred inside its edge band (redact_card_interior); a card found but rejected (no
    trustworthy outline) is blurred entirely, margin included."""
    dbg = getattr(res, "debug", None) or {}
    card = dbg.get("card")
    if isinstance(card, IdCardDetection):
        return redact_card_interior(bgr, card)      # the wallet card itself was the reference
    if dbg.get("redact_polys_img"):
        return redact_polys(bgr, dbg["redact_polys_img"])
    excl = None
    if card is not None:
        x0, y0, x1, y1 = card.spec.paper_rect_in_board_frame()
        excl = [apply_h(card.H_img_from_board, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])]
    det, rep = detect_idcard(bgr, focal_px=focal_px, exclude_polys=excl)
    if det is not None:
        return redact_card_interior(bgr, det)
    if rep is not None and rep.redact_polys_img:
        return redact_polys(bgr, rep.redact_polys_img)
    return bgr


def card_outline_px(res, shape):
    """The reference card's sheet in overlay pixels (the app keeps station labels off it)."""
    card = (getattr(res, "debug", None) or {}).get("card")
    if card is None:
        return None
    s = min(1.0, OVERLAY_SIDE / max(shape[:2]))
    x0, y0, x1, y1 = card.spec.paper_rect_in_board_frame()
    return np.round(apply_h(card.H_img_from_board, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]) * s).astype(int).tolist()


def _order_along(p):
    """Order skeleton points along the fragment's principal axis (a polyline the app can draw)."""
    c = p.mean(0)
    d = p - c
    _, vec = np.linalg.eigh(d.T @ d)
    return np.argsort(d @ vec[:, 1])


def _round(o, nd=3):
    if isinstance(o, float):
        return round(o, nd) if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: _round(v, nd) for k, v in o.items()}
    if isinstance(o, list):
        return [_round(v, nd) for v in o]
    return o


def public_measurement(res) -> dict:
    j = res.to_json()
    card = j.get("card") or {}
    return _round({"status": j["status"], "quality": {k: j["quality"].get(k) for k in
                   ("blur_sigma_px", "saturated_frac", "tilt_deg_est", "card_px_per_mm", "card_corners", "card_reproj_rms_px",
                    "reference", "retake_reason", "card_occluded_edge", "card_occluded_corners", "scale_rel_unc")
                   if k in j["quality"]},
                   "card": {k: card.get(k) for k in ("spec", "corners", "reproj_rms_px", "rectified_px_per_mm", "reference",
                                                     "scale_rel_unc", "confidence", "rebuilt_edge") if k in card} if card else None,
                   "cracks": j["cracks"][:3], "n_cracks": len(j["cracks"])})


def overlay_size(shape):
    h, w = shape[:2]
    s = min(1.0, OVERLAY_SIDE / max(h, w))
    return [int(round(w * s)), int(round(h * s))]


def inspect(current: np.ndarray, previous: np.ndarray | None = None, *, retakes: int = 0, planner=None,
            inspection_id: str | None = None, log=lambda *_: None, reference: str = "auto",
            focal_35mm: float | None = None, previous_stations: list | None = None,
            previous_focal_35mm: float | None = None, previous_card: dict | None = None) -> dict:
    """Run one inspection. `retakes` = photos already re-requested in this visit (client-held).
    `previous_stations`: the tracked crack's stations from its last visit (kept by the client, since uploaded
    photos are deleted after a day); the new photo is measured at exactly those points.
    `reference`: "auto" (printed ChArUco card if present, else a wallet card), "charuco" or "idcard"."""
    inspection_id = inspection_id or uuid.uuid4().hex[:12]
    t0 = time.time()
    f_px = focal_px_from_35mm(focal_35mm, current.shape)
    res = measure_image(current, keep_debug=True, reference=reference, focal_px=f_px)
    add_outlines(res, current.shape)
    geometry = card_geometry(res, current.shape)     # measured on the original photo, before any blur
    raw = current
    current = redact_cards(current, res, f_px)     # wallet card numbers never leave in a returned image
    wallet_seen = current is not raw               # a wallet card was found (used or rejected): redacted copy differs
    timings = {"measure_ms": round(1000 * (time.time() - t0))}
    obs = res.to_json()
    state = AgentState(inspection_id, previous_inspection_id="previous-visit" if previous is not None else None,
                       retakes=int(retakes))
    out = {"inspection_id": inspection_id, "comparison": None, "request": None, "ticket": None, "next_visit_days": None}
    prev_st = clean_stations(previous_stations)
    H_ov = None
    if res.debug.get("card") is not None:
        s_ov = min(1.0, OVERLAY_SIDE / max(current.shape[:2]))
        H_ov = np.diag([s_ov, s_ov, 1.0]) @ res.debug["card"].H_img_from_board

    def stations_cmp(cmpd):
        if cmpd and cmpd.get("status") == "ok" and cmpd.get("T_board1_from_board2") is not None:
            T, mode = cmpd["T_board1_from_board2"], cmpd["registration"]["mode"]
        elif (res.card or {}).get("reference", "charuco") == "charuco":
            T, mode = None, "card_frame_assumed"          # printed card left glued on the wall (precision mode)
        else:
            return {"status": "cannot_register",
                    "reason": "a wallet card is not left on the wall and the previous photo is not available"}
        sc = measure_at_stations(res, prev_st, T, mode)
        for r in sc.get("stations", []):
            if H_ov is not None and r.get("status") == "ok":
                r["overlay_px"] = [int(round(v)) for v in apply_h(H_ov, [r["board_mm_now"]])[0]]
        return sc

    if prev_st and previous is None:
        # follow-up without the previous image: the stations alone carry the comparison
        out["stations_compare"] = _round(stations_cmp(None))
        state.comparison = as_comparison(out["stations_compare"])
        state.previous_inspection_id, state.compared = "previous-visit", True
        out["comparison"] = _round(state.comparison)

    def do_compare(args, st):
        t1 = time.time()
        f_prev = focal_px_from_35mm(previous_focal_35mm, previous.shape)
        stored = None
        if previous_card:
            try:
                stored = StoredCard(previous_card, previous.shape)
            except (ValueError, KeyError, TypeError):
                stored = None
        if stored is not None:   # measure first, blur after: the earlier photo is measured with ITS card, never re-detected
            prev = measure_image(previous, keep_debug=True, reference=reference, focal_px=f_prev, card=stored,
                                 known_quality=stored.quality)
        else:
            prev = measure_image(previous, keep_debug=True, reference=reference, focal_px=f_prev)
        st.comparison = compare(prev, res)
        timings["compare_ms"] = round(1000 * (time.time() - t1))
        out["comparison"] = _round({k: v for k, v in st.comparison.items() if k != "T_board1_from_board2"})
        out["previous_measurement"] = public_measurement(prev)
        if st.comparison.get("status") == "ok":
            # the stored earlier photo was redacted when it was taken; with its stored geometry nothing is detected again
            prev_img = previous if stored is not None else redact_cards(previous, prev, f_prev)
            out["before_after"] = render_before_after(prev_img, prev, current, res,
                                                      st.comparison["T_board1_from_board2"])
        return obs

    def wait_for_inspector(args, st):
        return None

    tools = {"compare_with_previous": do_compare, "request_retake": wait_for_inspector,
             "request_closer_photo": wait_for_inspector}
    t2 = time.time()
    trace = run_agent(obs, state, tools, planner or RulePlanner(), log=log)
    timings["agent_ms"] = round(1000 * (time.time() - t2)) - timings.get("compare_ms", 0)
    if prev_st and previous is not None:
        out["stations_compare"] = _round(stations_cmp(state.comparison))
    last = trace[-1]["action"]
    focus = None
    if last["name"] in ("request_retake", "request_closer_photo"):
        out["request"] = {"kind": last["name"], **last["args"]}
        focus = last["args"].get("region_board_mm") if last["name"] == "request_closer_photo" else None
    elif last["name"] == "propose_ticket":
        out["ticket"] = {"id": uuid.uuid4().hex[:10], "status": "pending_human_approval", **last["args"]}
    elif last["name"] == "schedule_next_visit":
        out["next_visit_days"] = last["args"].get("days")
    if wallet_seen:
        # the stored upload must not keep the card's numbers either: the API overwrites it with this copy
        ok, buf = cv2.imencode(".jpg", current, [cv2.IMWRITE_JPEG_QUALITY, 92])
        out["_redacted_jpeg"] = buf.tobytes() if ok else b""
    out["card_geometry"] = geometry
    out.update({"measurement": public_measurement(res), "trace": _round(trace),
                "overlay_jpeg_b64": base64.b64encode(render_overlay(current, res, focus)).decode(),
                "photo_jpeg_b64": base64.b64encode(render_overlay(current, res, marks=False)).decode() if res.cracks else None,
                "card_outline_px": card_outline_px(res, current.shape),
                "closeup": render_closeup(current, res) if last["name"] not in ("request_retake",) else None,
                "overlay_size": overlay_size(current.shape),
                "timings_ms": dict(timings, total_ms=round(1000 * (time.time() - t0))),
                "llm": {"calls": sum(1 for t in trace if t["action"].get("meta", {}).get("input_tokens")),
                        "cost_usd": round(sum(t["action"].get("meta", {}).get("cost_usd", 0) or 0 for t in trace), 6)}})
    return out

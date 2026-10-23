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
from .measure import apply_h, measure_image

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


def _width_color(t: float):
    # sequential: warm yellow (thin) -> deep red (wide), BGR
    a = np.array([60, 200, 255], np.float32)
    b = np.array([40, 30, 215], np.float32)
    c = a + (b - a) * float(np.clip(t, 0, 1))
    return tuple(int(v) for v in c)


def render_overlay(bgr: np.ndarray, res, focus_region_mm=None) -> bytes:
    """Photo + what OpenCV found: card corners, crack skeleton coloured by width, the max location,
    and (active perception) the region the agent wants re-photographed. JPEG bytes."""
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
        for p in card.img_pts * s:
            cv2.circle(out, (int(p[0]), int(p[1])), lw + 1, (255, 170, 60), -1, cv2.LINE_AA)
        comps = dbg.get("comps") or []
        wmax = max([float(np.percentile(c.get("width_smooth_mm", c["width_mm"]), 98)) for c in comps] or [1.0])
        for c in comps:
            pts = apply_h(H, c["pts_mm"]) * s
            w = c.get("width_smooth_mm", c["width_mm"])
            for (x, y), wi in zip(pts[::2], w[::2]):
                cv2.circle(out, (int(x), int(y)), lw, _width_color(wi / max(wmax, 1e-6)), -1, cv2.LINE_AA)
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
    wmax = max([float(np.percentile(c.get("width_smooth_mm", c["width_mm"]), 98)) for c in comps] or [1.0])
    for c in comps:
        w = c.get("width_smooth_mm", c["width_mm"])
        for (px, py), wi in zip((np.asarray(c["pts_mm"]) - (x0, y0)) * r, w):
            cv2.circle(out, (int(px), int(py)), lw, _width_color(wi / max(wmax, 1e-6)), -1, cv2.LINE_AA)
    mx, my = (np.asarray(res.cracks[0]["max_location_board_mm"]) - (x0, y0)) * r
    cv2.circle(out, (int(mx), int(my)), 7 * lw, (255, 255, 255), lw + 1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return {"jpeg_b64": base64.b64encode(buf.tobytes()).decode(), "window_board_mm": [round(float(v), 1) for v in (x0, y0, x0 + wmm, y0 + hmm)],
            "px_per_mm": round(float(r), 3), "size_px": [W, H]}


def order_by_centre(res, shape) -> None:
    """On a real wall several ridges can be measured (a mortar joint, a wall edge next to the crack). The user aims the
    centre of the photo at the crack, so the main crack is the one passing closest to the image centre, not the longest.
    Each candidate also gets its outline in overlay pixels, so the app can let the user tap another one."""
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
            cr["center_dist"] = 1.0
            continue
        pts = apply_h(card.H_img_from_board, comps[i]["pts_mm"])
        cr["center_dist"] = round(float(np.min(np.linalg.norm(pts - centre, axis=1)) / diag), 3)
        step = max(1, len(pts) // 80)
        cr["outline_px"] = np.round(pts[::step] * s).astype(int).tolist()
    res.cracks.sort(key=lambda c: c.get("center_dist", 1.0))


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
                   ("blur_sigma_px", "saturated_frac", "tilt_deg_est", "card_px_per_mm", "card_corners", "card_reproj_rms_px")
                   if k in j["quality"]},
                   "card": {k: card.get(k) for k in ("spec", "corners", "reproj_rms_px", "rectified_px_per_mm")} if card else None,
                   "cracks": j["cracks"][:3], "n_cracks": len(j["cracks"])})


def overlay_size(shape):
    h, w = shape[:2]
    s = min(1.0, OVERLAY_SIDE / max(h, w))
    return [int(round(w * s)), int(round(h * s))]


def inspect(current: np.ndarray, previous: np.ndarray | None = None, *, retakes: int = 0, planner=None,
            inspection_id: str | None = None, log=lambda *_: None) -> dict:
    """Run one inspection. `retakes` = photos already re-requested in this visit (client-held)."""
    inspection_id = inspection_id or uuid.uuid4().hex[:12]
    t0 = time.time()
    res = measure_image(current, keep_debug=True)
    order_by_centre(res, current.shape)
    timings = {"measure_ms": round(1000 * (time.time() - t0))}
    obs = res.to_json()
    state = AgentState(inspection_id, previous_inspection_id="previous-visit" if previous is not None else None,
                       retakes=int(retakes))
    out = {"inspection_id": inspection_id, "comparison": None, "request": None, "ticket": None, "next_visit_days": None}

    def do_compare(args, st):
        t1 = time.time()
        prev = measure_image(previous, keep_debug=True)
        st.comparison = compare(prev, res)
        timings["compare_ms"] = round(1000 * (time.time() - t1))
        out["comparison"] = _round({k: v for k, v in st.comparison.items() if k != "T_board1_from_board2"})
        out["previous_measurement"] = public_measurement(prev)
        if st.comparison.get("status") == "ok":
            out["before_after"] = render_before_after(previous, prev, current, res, st.comparison["T_board1_from_board2"])
        return obs

    def wait_for_inspector(args, st):
        return None

    tools = {"compare_with_previous": do_compare, "request_retake": wait_for_inspector,
             "request_closer_photo": wait_for_inspector}
    t2 = time.time()
    trace = run_agent(obs, state, tools, planner or RulePlanner(), log=log)
    timings["agent_ms"] = round(1000 * (time.time() - t2)) - timings.get("compare_ms", 0)
    last = trace[-1]["action"]
    focus = None
    if last["name"] in ("request_retake", "request_closer_photo"):
        out["request"] = {"kind": last["name"], **last["args"]}
        focus = last["args"].get("region_board_mm") if last["name"] == "request_closer_photo" else None
    elif last["name"] == "propose_ticket":
        out["ticket"] = {"id": uuid.uuid4().hex[:10], "status": "pending_human_approval", **last["args"]}
    elif last["name"] == "schedule_next_visit":
        out["next_visit_days"] = last["args"].get("days")
    out.update({"measurement": public_measurement(res), "trace": _round(trace),
                "overlay_jpeg_b64": base64.b64encode(render_overlay(current, res, focus)).decode(),
                "closeup": render_closeup(current, res) if last["name"] not in ("request_retake",) else None,
                "overlay_size": overlay_size(current.shape),
                "timings_ms": dict(timings, total_ms=round(1000 * (time.time() - t0))),
                "llm": {"calls": sum(1 for t in trace if t["action"].get("meta", {}).get("input_tokens")),
                        "cost_usd": round(sum(t["action"].get("meta", {}).get("cost_usd", 0) or 0 for t in trace), 6)}})
    return out

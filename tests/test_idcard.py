"""Wallet-card (ID-1) scale reference: detection, retake reasons, measure_image hook, agent, privacy.
Run: python tests/test_idcard.py   (or pytest)"""
import base64
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch.agent import AgentState, decide_next_action  # noqa: E402
from crackwatch.idcard import ID1_H_MM, ID1_W_MM, detect_idcard, recover_side, homography_4pt, _corners_from_lines  # noqa: E402
from crackwatch.measure import measure_image  # noqa: E402
from crackwatch.service import inspect, render_overlay  # noqa: E402
from crackwatch.synth import apply_h  # noqa: E402
from crackwatch.synth_idcard import make_scene, scale_errors  # noqa: E402

_CACHE = {}


def scene(seed=7, finger="none", max_tilt=20):
    key = (seed, finger, max_tilt)
    if key not in _CACHE:
        s = None
        while s is None:
            s = make_scene(seed, finger=finger, max_tilt=max_tilt)
            seed += 1000
        _CACHE[key] = s
    return _CACHE[key]


def card_center_err(det, sc):
    p_wall = apply_h(np.linalg.inv(sc["H_img_from_wall"]) @ sc["H_img_from_card_wall"], [(ID1_W_MM / 2, ID1_H_MM / 2)])[0]
    return max(abs(v) for v in scale_errors(det.H_img_from_board, sc["H_img_from_wall"], p_wall))


def _ok_scene():
    for seed in range(7, 60):
        sc = scene(seed)
        det, rep = detect_idcard(sc["img_idcard"])
        if det is not None:
            return sc, det, rep
    raise AssertionError("no clean synthetic scene detected")


def test_detect_clean_card():
    sc, det, rep = _ok_scene()
    assert rep.status == "ok"
    assert card_center_err(det, sc) < 0.01                     # < 1 % scale error at the card
    assert 0 < det.scale_rel_unc < 0.02
    assert det.H_img_from_board.shape == (3, 3) and det.n_corners == 4
    assert np.linalg.det(det.H_img_from_board[:2, :2]) != 0
    assert 0.98 < det.thickness_scale < 1.0                    # wall plane slightly behind the card face
    info = det.public_info()
    assert info["reference"] == "idcard" and len(info["corners_img_px"]) == 4


def test_known_focal():
    """EXIF focal (35 mm equivalent) path: same detection, focal fixed instead of estimated."""
    from crackwatch.service import focal_px_from_35mm
    sc, det, rep = _ok_scene()
    f_px = sc["camera"]["focal_px"]
    f35 = f_px / np.hypot(1600, 1200) * 43.27
    assert abs(focal_px_from_35mm(f35, (1200, 1600)) - f_px) < 1e-6 and focal_px_from_35mm(None, (1200, 1600)) is None
    d2, r2 = detect_idcard(sc["img_idcard"], focal_px=f_px)
    assert d2 is not None and d2.focal_source == "exif"
    assert card_center_err(d2, sc) < 0.01


def test_recover_side_exact():
    """Three lines of a known rectangle seen in perspective + the focal -> the fourth line is recovered."""
    K = np.array([[1400.0, 0, 799.5], [0, 1400.0, 599.5], [0, 0, 1]])
    a = np.radians(25)
    R = np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])
    t = np.array([-40.0, -20.0, 300.0])
    H = K @ np.column_stack([R[:, 0], R[:, 1], t])
    obj = [(0, 0), (ID1_W_MM, 0), (ID1_W_MM, ID1_H_MM), (0, ID1_H_MM)]
    Q = apply_h(H, obj)
    L = []
    for s in range(4):
        p, q = Q[s], Q[(s + 1) % 4]
        d = (q - p) / np.linalg.norm(q - p)
        n = np.array([-d[1], d[0]])
        L.append((n, float(n @ p)))
    for m in range(4):
        LL = list(L)
        LL[m] = None
        toward = Q[(m + 1) % 4] * 0.5 + Q[(m + 2) % 4] * 0.5
        rec = recover_side(LL, m, 1400.0, (1200, 1600), toward)
        LL[m] = rec
        Qr = _corners_from_lines(LL)
        assert np.max(np.linalg.norm(Qr - Q, axis=1)) < 0.05, (m, Qr, Q)


def test_retake_too_small():
    sc, det, rep = _ok_scene()
    small = cv2.resize(sc["img_idcard"], None, fx=0.45, fy=0.45, interpolation=cv2.INTER_AREA)
    d2, r2 = detect_idcard(small)
    assert d2 is None and r2.status in ("card_too_small", "card_not_found"), r2.status


def test_retake_cut_by_frame():
    sc, det, rep = _ok_scene()
    q = det.img_pts
    x_cut = int(round(q[:, 0].min() + 0.4 * np.ptp(q[:, 0])))
    img = sc["img_idcard"][:, x_cut:].copy()
    d2, r2 = detect_idcard(img)
    assert d2 is None and r2.status in ("card_cut_by_frame", "card_not_found", "card_occluded"), r2.status


def test_no_wallet_card():
    sc = scene(11)
    d, r = detect_idcard(sc["img_charuco"])                  # ChArUco A6 sheet only: aspect 1.41, not ID-1
    assert d is None and r.status == "card_not_found", r.status


def test_finger_over_short_edge():
    """A finger laid along a short edge: either the edge is rebuilt (accepted, lower confidence, edge named)
    or a retake naming the hidden edge -- never a silently wrong scale."""
    n_checked = 0
    for seed in range(300, 340):
        sc = make_scene(seed, finger="short_full", max_tilt=15)
        if sc is None:
            continue
        det, rep = detect_idcard(sc["img_idcard"])
        if det is not None:
            assert card_center_err(det, sc) < 0.02
            if det.recovered_edge is not None:
                assert det.confidence < 0.7 and rep.quality.get("card_occluded_edge") in ("left", "right", "top", "bottom")
        else:
            assert rep.status in ("card_occluded", "card_wrong_size", "card_not_found", "card_too_small", "card_not_flat"), rep.status
            if rep.status == "card_occluded":
                assert rep.quality.get("card_occluded_edge") in ("left", "right", "top", "bottom")
        n_checked += 1
        if n_checked >= 3:
            break
    assert n_checked >= 3


def test_measure_hook_and_agent():
    sc, det, rep = _ok_scene()
    res = measure_image(sc["img_idcard"], keep_debug=True, reference="idcard")
    assert res.status in ("ok", "no_crack_found"), res.status
    assert res.card["reference"] == "idcard" and res.quality["reference"] == "idcard"
    assert res.debug["card"].spec.paper_rect_in_board_frame() == (0.0, 0.0, ID1_W_MM, ID1_H_MM)
    for c in res.cracks:
        assert c["uncertainty_mm"] > 0
    # ChArUco path unchanged by default
    r2 = measure_image(sc["img_charuco"], reference="charuco")
    assert r2.card is not None and r2.card["reference"] == "charuco"
    # auto: ChArUco when present, wallet card otherwise
    assert measure_image(sc["img_charuco"], reference="auto").card["reference"] == "charuco"
    # agent: a rejected wallet card gives its own retake reason and the hidden edge
    obs = {"status": "reference_rejected", "cracks": [],
           "quality": {"retake_reason": "card_occluded", "retake_instruction": "x", "card_occluded_edge": "left"}}
    a = decide_next_action(obs, AgentState("t"))
    assert a.name == "request_retake" and a.args["reason"] == "card_occluded" and a.args["edge"] == "left"


def _hf_energy(img, poly):
    m = np.zeros(img.shape[:2], np.uint8)
    cv2.fillPoly(m, [np.round(poly).astype(np.int32)], 1)
    m = cv2.erode(m, np.ones((5, 5), np.uint8))
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)
    hp = g - cv2.GaussianBlur(g, (0, 0), 2.0)
    return float(np.mean(hp[m > 0] ** 2))


def test_returned_images_are_redacted():
    """The overlay returned by inspect() must not show the card face (numbers): its fine detail inside the
    card is gone, compared with the photo."""
    sc, det, rep = _ok_scene()
    img = sc["img_idcard"]
    out = inspect(img, reference="idcard")
    ov = cv2.imdecode(np.frombuffer(base64.b64decode(out["overlay_jpeg_b64"]), np.uint8), cv2.IMREAD_COLOR)
    s = ov.shape[1] / img.shape[1]
    face = apply_h(sc["H_img_from_card_face"], [(4, 4), (ID1_W_MM - 4, 4), (ID1_W_MM - 4, ID1_H_MM - 4), (4, ID1_H_MM - 4)])
    # unredacted overlay of the same photo, same rendering, for a fair comparison
    res = measure_image(img, keep_debug=True, reference="idcard")
    raw = cv2.imdecode(np.frombuffer(render_overlay(img, res), np.uint8), cv2.IMREAD_COLOR)
    e_raw, e_red = _hf_energy(raw, face * s), _hf_energy(ov, face * s)
    assert e_red < 0.1 * e_raw, (e_red, e_raw)
    # digits box specifically
    x0, y0, x1, y1 = sc["digits_box_card_mm"]
    box = apply_h(sc["H_img_from_card_face"], [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]) * s
    assert _hf_energy(ov, box) < 0.1 * _hf_energy(raw, box)


def test_bank_card_redacted_when_printed_card_is_the_reference():
    """A bank card next to a printed ChArUco card must be blurred too, although the ChArUco measured the scale."""
    from types import SimpleNamespace
    from crackwatch.card import CARD_A6
    from crackwatch.service import redact_cards
    sc, det, rep = _ok_scene()
    img = sc["img_idcard"]
    # stand-in for a ChArUco result: its sheet maps to a small patch in the image corner, away from the bank card
    H = np.array([[0.5, 0, 5], [0, 0.5, 5], [0, 0, 1]], float)
    res = SimpleNamespace(debug={"card": SimpleNamespace(spec=CARD_A6, H_img_from_board=H)})
    out = redact_cards(img, res)
    x0, y0, x1, y1 = sc["digits_box_card_mm"]
    box = apply_h(sc["H_img_from_card_face"], [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    assert _hf_energy(out, box) < 0.1 * _hf_energy(img, box)


class _MemBlobs:
    def __init__(self):
        self.d = {}

    def presign_post(self, key, max_bytes):
        return {"url": "https://example.invalid/", "fields": {"key": key}}

    def get(self, key):
        return self.d[key]

    def put(self, key, data):
        self.d[key] = data

    def delete(self, key):
        self.d.pop(key, None)


def test_stored_upload_is_redacted():
    """Wallet-card mode: after /api/inspect the stored upload is the redacted copy, never the raw card photo."""
    import json
    os.environ.setdefault("CW_VISIT_SECRET", "test-secret-for-unit-tests-only-0000")
    from crackwatch import api
    from crackwatch.store import MemStore
    sc, det, rep = _ok_scene()
    img = sc["img_idcard"]
    blobs = _MemBlobs()
    a = api.App(MemStore(), blobs, log=lambda *_: None)
    key = json.loads(a.handle("POST", "/api/upload-url", {}, b"{}", {}, "1").body)["key"]
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
    blobs.put(key, buf.tobytes())
    r = a.handle("POST", "/api/inspect", {}, json.dumps({"image": {"key": key}, "reference": "auto"}).encode(), {}, "1")
    out = json.loads(r.body)
    assert r.status == 200 and out.get("upload_redacted") is True and "_redacted_jpeg" not in out
    stored = cv2.imdecode(np.frombuffer(blobs.get(key), np.uint8), cv2.IMREAD_COLOR)
    x0, y0, x1, y1 = sc["digits_box_card_mm"]
    box = apply_h(sc["H_img_from_card_face"], [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    assert _hf_energy(stored, box) < 0.1 * _hf_energy(img, box)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
    print("all idcard tests passed")

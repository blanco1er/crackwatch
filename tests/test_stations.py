"""Measurement stations (crackwatch/stations.py): JSON shape, and re-measurement at the same stations on a
second visit (synthetic two-visit pairs with exact ground truth, card left in place).
Run: python tests/test_stations.py   (or pytest)"""
import json
import os
import sys
import tempfile

import cv2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch.service import inspect  # noqa: E402
from crackwatch.stations import clean_stations  # noqa: E402
from crackwatch.synth import generate_pair  # noqa: E402

_PAIRS = {}


def pair(widen, seed):
    if (widen, seed) not in _PAIRS:
        d = tempfile.mkdtemp(prefix="cw-st-")
        gt = generate_pair(seed, d, widen, 0.0, False)
        assert gt is not None
        _PAIRS[(widen, seed)] = [cv2.imread(os.path.join(d, v["image"])) for v in gt["visits"]]
    return _PAIRS[(widen, seed)]


def test_station_json():
    v1, _ = pair(0.0, 71001)
    out = inspect(v1)
    cr = out["measurement"]["cracks"][0]
    st = cr["stations"]
    assert 5 <= len(st) <= 6, st
    assert [s["id"] for s in st] == list("ABCDEF"[:len(st)])
    assert sum(s["is_max"] for s in st) == 1
    for s in st:
        assert len(s["board_mm"]) == 2 and len(s["overlay_px"]) == 2 and s["width_mm"] > 0 and s["u_mm"] > 0
    arcs = [s["arc_mm"] for s in st]
    assert arcs == sorted(arcs)
    json.dumps(out["measurement"])                      # serialisable as sent to the app
    assert clean_stations([{"id": "A", "board_mm": ["x", 1], "width_mm": 1}, "junk", {"id": "B", "board_mm": [1, 2], "width_mm": 0.5}]) \
        == [{"id": "B", "board_mm": [1.0, 2.0], "width_mm": 0.5, "u_mm": 0.1, "is_max": False}]


def _follow_up(widen, seed, with_image):
    v1, v2 = pair(widen, seed)
    st = inspect(v1)["measurement"]["cracks"][0]["stations"]
    out = inspect(v2, v1 if with_image else None, previous_stations=st)
    return out["stations_compare"], out


def test_unchanged_crack_not_significant():
    for with_image in (False, True):
        sc, _ = _follow_up(0.0, 71001, with_image)
        assert sc["status"] == "ok" and sc["n_visible"] >= 3, sc
        assert sc["n_significant"] == 0, sc
        assert all(abs(r["delta_mm"]) < 0.3 for r in sc["stations"] if r["status"] == "ok"), sc


def test_widened_crack_detected_at_stations():
    sc, out = _follow_up(0.5, 71001, with_image=False)
    ok = [r for r in sc["stations"] if r["status"] == "ok"]
    assert sum(r["significant"] for r in ok) >= len(ok) // 2, sc
    assert all(0.2 < r["delta_mm"] < 0.8 for r in ok), sc
    assert out["comparison"]["source"] == "stations" and out["comparison"]["significant_widening"]


def test_outside_station_is_not_invented():
    v1, v2 = pair(0.0, 71001)
    st = inspect(v1)["measurement"]["cracks"][0]["stations"]
    far = dict(st[0], id="Z", board_mm=[900.0, 900.0])
    sc = inspect(v2, previous_stations=st + [far])["stations_compare"]
    z = [r for r in sc["stations"] if r["id"] == "Z"][0]
    assert z["status"] == "not_visible" and "width_mm" not in z


if __name__ == "__main__":
    test_station_json()
    test_unchanged_crack_not_significant()
    test_widened_crack_detected_at_stations()
    test_outside_station_is_not_invented()
    print("station tests passed")

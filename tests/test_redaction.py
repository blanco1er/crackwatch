"""Bank-card redaction keeps the card measurable: the interior is blurred (numbers unreadable) but a 2.5 mm edge
band stays, so the stored copy of a visit can be measured again with the same card at the next visit.
Run: python tests/test_redaction.py   (or pytest)"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.dirname(__file__))
from test_idcard import _hf_energy, _ok_scene  # noqa: E402
from crackwatch.idcard import ID1_H_MM, ID1_W_MM  # noqa: E402
from crackwatch.measure import apply_h, local_scale, measure_image  # noqa: E402
from crackwatch.service import redact_cards  # noqa: E402


def test_interior_blurred_card_still_measurable():
    sc, det, rep = _ok_scene()
    img = sc["img_idcard"]
    res = measure_image(img, keep_debug=True, reference="idcard")
    assert res.status in ("ok", "no_crack_found"), res.status
    red = redact_cards(img, res)
    x0, y0, x1, y1 = sc["digits_box_card_mm"]
    box = apply_h(sc["H_img_from_card_face"], [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
    assert _hf_energy(red, box) < 0.1 * _hf_energy(img, box)          # the numbers are gone
    again = measure_image(red, keep_debug=True, reference="idcard")      # ... the card is still found
    assert again.status == res.status, again.quality
    c = (ID1_W_MM / 2, ID1_H_MM / 2)
    s0 = local_scale(res.debug["card"].H_img_from_board, c)
    s1 = local_scale(again.debug["card"].H_img_from_board, c)
    assert abs(s1 / s0 - 1) < 0.01, (s0, s1)                             # same scale within 1 %


def test_compare_reuses_stored_card_geometry():
    """Measure first, blur after: when the earlier visit's card geometry is known, the comparison measures the
    earlier photo with it and never runs a card detector on that photo."""
    import cv2
    from crackwatch import idcard, measure, service
    load = lambda k: service.decode_image(open(os.path.join(os.path.dirname(__file__), "..", "web", "samples", k + ".jpg"), "rb").read())  # noqa: E731
    prev, cur = load("close"), load("visit2")
    first = service.inspect(prev)
    geo = first["card_geometry"]
    assert geo and geo["reference"] == "charuco" and len(geo["H_img_from_board"]) == 3
    fp = lambda a: round(float(np.mean(a if a.ndim == 2 else cv2.cvtColor(a, cv2.COLOR_BGR2GRAY))), 3)  # noqa: E731
    prev_fp, calls = fp(prev), []
    orig = (measure.detect_card, idcard.detect_idcard, service.detect_idcard)

    def spy(fn):
        def f(img, *a, **k):
            calls.append(fp(img))
            return fn(img, *a, **k)
        return f
    measure.detect_card, idcard.detect_idcard, service.detect_idcard = (spy(f) for f in orig)
    try:
        out = service.inspect(cur, prev, previous_card=geo)
    finally:
        measure.detect_card, idcard.detect_idcard, service.detect_idcard = orig
    assert out["comparison"]["status"] == "ok", out["comparison"]
    assert prev_fp not in calls, calls                       # no detection on the earlier photo
    assert calls                                             # ... while the new photo was searched as usual
    base = service.inspect(cur, prev)                        # same comparison as when the card is re-detected
    assert abs(out["comparison"]["width_delta_mm"]["median"] - base["comparison"]["width_delta_mm"]["median"]) < 0.02


if __name__ == "__main__":
    test_interior_blurred_card_still_measurable()
    test_compare_reuses_stored_card_geometry()
    print("redaction tests passed")

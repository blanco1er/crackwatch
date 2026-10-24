"""The bank-card decision must not flip on JPEG re-compression noise (the web app re-encodes photos to 4032 px
JPEG q0.92). Every real bank-card photo is re-encoded at quality 80-100: same accept / refuse decision, and the
scale (px/mm at the card centre) within 0.5 %. Uses the owner's photos when present (skipped otherwise).
Run: python tests/test_idcard_jpeg_stability.py   (or pytest)"""
import glob
import os
import subprocess
import sys
import tempfile

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch.exif import focal_35mm  # noqa: E402
from crackwatch.idcard import detect_idcard  # noqa: E402
from crackwatch.service import decode_image, focal_px_from_35mm  # noqa: E402

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "photos-reelles", "v2-carte-a-cote"))
PHOTOS = ["beton-deux-cartes/IMG_164[1-6]", "beton-carte-seule/IMG_165[3-6]", "fine-carte-seule/IMG_1652", "fine-carte-seule/IMG_166[12]",
          "fine-carte-seule/IMG_1660", "enduit-carte-seule/IMG_165[78]"]
QUALITIES = (80, 88, 92, 95, 100)


def _photos():
    out = []
    for pat in PHOTOS:
        out += sorted(glob.glob(os.path.join(ROOT, pat + ".heic")))
    return out


def _decide(img, f_px):
    det, rep = detect_idcard(img, focal_px=f_px)
    return rep.status, (det.px_per_mm if det is not None else None)


def check_photo(path, tmp):
    jpg = os.path.join(tmp, os.path.basename(path) + ".jpg")
    subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "100", path, "--out", jpg], check=True,
                   capture_output=True)
    data = open(jpg, "rb").read()
    f_px = None
    base = decode_image(data)                       # 4032 px, as the service
    f_px = focal_px_from_35mm(focal_35mm(data), base.shape)
    res = []
    for q in QUALITIES:
        ok, buf = cv2.imencode(".jpg", base, [cv2.IMWRITE_JPEG_QUALITY, q])
        res.append((q, *_decide(cv2.imdecode(buf, cv2.IMREAD_COLOR), f_px)))
    return res


def test_jpeg_stability():
    photos = _photos()
    if not photos or sys.platform != "darwin":
        print("skipped: real photos / sips not available")
        return
    bad = []
    with tempfile.TemporaryDirectory() as tmp:
        for p in photos:
            res = check_photo(p, tmp)
            status = {r[1] for r in res}
            ppm = [r[2] for r in res if r[2]]
            spread = (max(ppm) / min(ppm) - 1) if len(ppm) > 1 else 0.0
            line = f"{os.path.basename(p)}: " + ", ".join(f"q{q} {s}{'' if v is None else f' {v:.3f}'}" for q, s, v in res)
            print(line)
            if len(status) > 1 or spread > 0.005:
                bad.append(line)
    assert not bad, "decision or scale changes with JPEG quality:\n" + "\n".join(bad)


PRINTED_ONLY = ["enduit-imprimee/IMG_162[7-9]", "enduit-imprimee/IMG_1630", "beton-imprimee/IMG_16[34][90]"]


def test_no_redaction_without_bank_card():
    """Photos with the printed card only: nothing may be blurred (a wrong "card" blurred on the crack would corrupt
    the stored copy used at the next visit), at any JPEG quality."""
    from crackwatch.measure import measure_image
    from crackwatch.service import redact_cards
    photos = []
    for pat in PRINTED_ONLY:
        photos += sorted(glob.glob(os.path.join(ROOT, pat + ".heic")))
    if not photos or sys.platform != "darwin":
        print("skipped: real photos / sips not available")
        return
    bad = []
    with tempfile.TemporaryDirectory() as tmp:
        for p in photos:
            jpg = os.path.join(tmp, os.path.basename(p) + ".jpg")
            subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "100", p, "--out", jpg], check=True,
                           capture_output=True)
            data = open(jpg, "rb").read()
            base = decode_image(data)
            f_px = focal_px_from_35mm(focal_35mm(data), base.shape)
            for q in QUALITIES:
                ok, buf = cv2.imencode(".jpg", base, [cv2.IMWRITE_JPEG_QUALITY, q])
                img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                res = measure_image(img, keep_debug=True, reference="charuco")
                out = redact_cards(img, res, focal_px=f_px)
                changed = int(np.count_nonzero(np.any(out != img, axis=-1)))
                print(f"{os.path.basename(p)} q{q}: {res.status}, pixels changed {changed}")
                if changed:
                    bad.append(f"{os.path.basename(p)} q{q}: {changed} px blurred")
    assert not bad, "printed-card-only photos were redacted:\n" + "\n".join(bad)


if __name__ == "__main__":
    test_jpeg_stability()
    test_no_redaction_without_bank_card()
    print("jpeg stability and redaction tests passed")

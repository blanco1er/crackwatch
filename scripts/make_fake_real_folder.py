"""Test helper: builds a folder with the exact layout expected by scripts/process_real.py, using SIMULATED
photos (the printable chart warped in perspective, blurred, noisy, JPEG; synthetic cracks for E3).
It only checks that the real-photo chain runs end to end. Its numbers are NOT real-photo results.

  python scripts/make_fake_real_folder.py --out /tmp/fake-photos && python scripts/process_real.py --dir /tmp/fake-photos --out /tmp/fake-eval
"""
import argparse
import glob
import math
import os
import shutil
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch.card import PRINT_PX_PER_MM, mire_layout, render_mire_page  # noqa: E402

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def photo_of_page(page, rng, ppm, tilt_deg, size=(3024, 4032)):
    h, w = size
    ph, pw = page.shape
    sx, sy = pw / PRINT_PX_PER_MM, ph / PRINT_PX_PER_MM          # page size in mm
    src = np.float32([[0, 0], [pw, 0], [pw, ph], [0, ph]])
    cx, cy = w / 2 + rng.uniform(-150, 150), h / 2 + rng.uniform(-150, 150)
    hw, hh = sx * ppm / 2, sy * ppm / 2
    t = math.tan(math.radians(tilt_deg)) * 0.25
    dst = np.float32([[cx - hw * (1 - t), cy - hh], [cx + hw * (1 + t), cy - hh * (1 + t)],
                      [cx + hw * (1 + t), cy + hh * (1 + t)], [cx - hw * (1 - t), cy + hh]])
    rot = cv2.getRotationMatrix2D((cx, cy), rng.uniform(-8, 8), 1.0)
    dst = cv2.transform(dst[None], rot)[0].astype(np.float32)
    H = cv2.getPerspectiveTransform(src, dst)
    wall = (rng.normal(0.62, 0.03, (h // 8, w // 8)).astype(np.float32))
    wall = cv2.resize(cv2.GaussianBlur(wall, (0, 0), 2), (w, h))
    paper = cv2.warpPerspective(page.astype(np.float32) / 255 * 0.92, H, (w, h), flags=cv2.INTER_AREA, borderValue=-1)
    img = np.where(paper >= 0, paper, wall)
    img = cv2.GaussianBlur(img, (0, 0), rng.uniform(0.8, 1.6))
    img = img * rng.uniform(0.8, 1.1) + rng.normal(0, 0.01, img.shape).astype(np.float32)
    bgr = cv2.cvtColor(np.clip(img * 255, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    return bgr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    rng = np.random.default_rng(7)
    for v in (1, 2):
        d = os.path.join(a.out, f"mire-v{v}")
        os.makedirs(d, exist_ok=True)
        page = render_mire_page(mire_layout(v))
        for i, (ppm, tilt) in enumerate([(14, 0), (10, 15), (8, 25), (12, 5), (9, 30), (15, 10)]):
            cv2.imwrite(os.path.join(d, f"IMG_{v}{i:02d}.jpg"), photo_of_page(page, rng, ppm, tilt), [cv2.IMWRITE_JPEG_QUALITY, 90])
    d = os.path.join(a.out, "fissure-A")
    os.makedirs(d, exist_ok=True)
    for p in sorted(glob.glob(os.path.join(ROOT, "web", "samples", "*.jpg"))):
        shutil.copy(p, os.path.join(d, os.path.basename(p)))
    with open(os.path.join(a.out, "regle.txt"), "w") as f:
        f.write("50.0\n")
    print(a.out)


if __name__ == "__main__":
    main()

"""Calibrate the per-visit systematic width error used by change.py: u_sys = sqrt(a^2 + (r w)^2).

r (SYS_REL = 3 %) is an ASSUMPTION, not fitted: the card homography cannot see a wall that is not flat
or residual lens distortion (3 % ~ 7 mm of relief at 25 cm), and the synthetic walls are perfectly
flat, so no synthetic data can calibrate it. a (SYS_ABS_MM) is fitted here on synthetic two-visit
pairs generated with seeds that are NOT the reported test set (make_synth.py --seed0 1000 -> pairs
51000+; the reported E4 uses data/synth_test, pairs 70000+): for each ~10 mm stretch,
z = (measured change - true widening) / sqrt(u_stat^2 + 2 u_sys^2), and a is the smallest value
(0.005 mm steps) for which the robust spread (1.4826 MAD) of z on stretches narrower than 1.5 mm is
<= 1. (Narrow cracks carry the absolute term: the blur model dominates there.)

usage: python scripts/make_synth.py --out /tmp/calib --n 0 --pairs 60 --seed0 1000
       python scripts/calib_sys.py --data /tmp/calib/e4
"""
import argparse
import glob
import json
import math
import os
import sys
from multiprocessing import Pool

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch import change  # noqa: E402
from crackwatch.measure import measure_image  # noqa: E402


def one(path):
    gt = json.load(open(path))
    d = os.path.dirname(path)
    v1, v2 = gt["visits"]
    r1 = measure_image(cv2.imread(os.path.join(d, v1["image"])), keep_debug=True)
    r2 = measure_image(cv2.imread(os.path.join(d, v2["image"])), keep_debug=True)
    c = change.compare(r1, r2)
    if c.get("status") != "ok":
        return []
    return [(gt["widen_mm"], w["delta_mm"], w["w1_mm"], w["u_stat_mm"], 0.0) for w in c["windows"]] + \
        [(gt["widen_mm"], c["whole"]["delta_mm"], c["whole"]["w1_mm"], c["whole"]["u_stat_mm"], 1.0)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/synth/e4")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(a.data, "e4_*.json")))
    with Pool(a.workers) as pool:
        rows = [r for rr in pool.map(one, files) for r in rr]
    R = np.array(rows, float)
    Rw, R = R[R[:, 4] > 0], R[R[:, 4] == 0]
    e = R[:, 1] - R[:, 0]
    w = R[:, 2]
    us = R[:, 3]
    r = change.SYS_REL
    print(f"{len(R)} stretches from {len(files)} pairs; error median {np.median(e):+.3f} mm, "
          f"robust sd {1.4826 * np.median(np.abs(e - np.median(e))):.3f} mm")
    rsd = lambda z: 1.4826 * float(np.median(np.abs(z - np.median(z))))  # noqa: E731
    thin = w < 1.5
    for a_ in np.arange(0.0, 0.2001, 0.005):
        z = e / np.sqrt(us ** 2 + 2 * (a_ ** 2 + (r * w) ** 2))
        if rsd(z[thin]) <= 1.0:
            print(f"SYS_REL = {r} (assumed) -> SYS_ABS_MM = {a_:.3f}; robust sd of z: thin {rsd(z[thin]):.2f}, "
                  f"wide {rsd(z[~thin]):.2f}, all {rsd(z):.2f}; P(z > 2.5) = {np.mean(z > 2.5):.3f}")
            break
    # whole-crack test: same procedure on the per-pair whole-crack change
    e, w, us = Rw[:, 1] - Rw[:, 0], Rw[:, 2], Rw[:, 3]
    for a_ in np.arange(0.0, 0.2001, 0.005):
        z = e / np.sqrt(us ** 2 + 2 * (a_ ** 2 + (r * w) ** 2))
        if rsd(z) <= 1.0:
            print(f"whole crack ({len(Rw)} pairs): SYS_ABS_WHOLE_MM = {a_:.3f}; robust sd of z {rsd(z):.2f}; "
                  f"P(z > 2.5) = {np.mean(z > 2.5):.3f}")
            break


if __name__ == "__main__":
    main()

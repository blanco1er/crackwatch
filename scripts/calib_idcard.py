"""Calibrate the per-edge systematic offset budget of the wallet-card reference (IdCardParams.edge_sys_mm) on a
CALIBRATION seed range (default 60000-60149), disjoint from the evaluation seeds of eval_idcard.py (50000+).

  python scripts/calib_idcard.py
Prints, for each candidate value, the share of accepted scenes whose scale error at the crack is within
1, 2 and 3 announced sigmas (target for a Gaussian: 68 / 95 / 99.7 %).
"""
import os
import sys
from dataclasses import replace
from multiprocessing import Pool

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch.idcard import IdCardParams, detect_idcard  # noqa: E402
from crackwatch.synth import apply_h  # noqa: E402
from crackwatch.synth_idcard import make_scene, scale_errors  # noqa: E402

VALUES = (0.0, 0.05, 0.1, 0.15, 0.2)


def one(seed):
    sc = make_scene(seed)
    if sc is None:
        return None
    out = []
    for v in VALUES:
        det, rep = detect_idcard(sc["img_idcard"], replace(IdCardParams(), edge_sys_mm=v))
        if det is None:
            out.append(None)
            continue
        cc = sc["crack_center_wall"]
        e = scale_errors(det.H_img_from_board, sc["H_img_from_wall"], cc)
        x = apply_h(sc["H_img_from_wall"], [cc])[0]
        pe = apply_h(np.linalg.inv(det.H_img_from_board), [x])[0]
        out.append((max(abs(e[0]), abs(e[1])), det.scale_rel_unc_at(pe)))
    return out


if __name__ == "__main__":
    a = int(sys.argv[1]) if len(sys.argv) > 1 else 60000
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 150
    with Pool(max(1, (os.cpu_count() or 2) - 1)) as pool:
        R = [r for r in pool.map(one, range(a, a + n)) if r]
    for i, v in enumerate(VALUES):
        z = np.array([r[i][0] / r[i][1] for r in R if r[i] is not None])
        u = np.array([r[i][1] for r in R if r[i] is not None])
        print(f"edge_sys_mm={v:.2f}: accepted {len(z)}/{len(R)}, median sigma {100 * np.median(u):.2f} %, "
              f"|err|<=1s {100 * np.mean(z <= 1):.0f} %, <=2s {100 * np.mean(z <= 2):.0f} %, <=3s {100 * np.mean(z <= 3):.0f} %")

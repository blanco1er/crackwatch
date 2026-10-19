"""E4: change detection between two visits (synthetic pairs with known widening/extension)."""
import glob
import json
import os
import sys
import time
from multiprocessing import Pool

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch.change import compare  # noqa: E402
from crackwatch.measure import measure_image  # noqa: E402


def eval_pair(path):
    gt = json.load(open(path))
    d = os.path.dirname(path)
    v1, v2 = gt["visits"]
    t0 = time.time()
    r1 = measure_image(cv2.imread(os.path.join(d, v1["image"])), keep_debug=True)
    r2 = measure_image(cv2.imread(os.path.join(d, v2["image"])), keep_debug=True)
    cmp = compare(r1, r2)
    rec = {"id": gt["id"], "widen": gt["widen_mm"], "extend": gt["extend_mm"], "card_moved": gt["card_moved"],
           "time_s": time.time() - t0, "cmp": {k: v for k, v in cmp.items() if k != "T_board1_from_board2"}}
    if cmp["status"] == "ok":
        # registration error: map v2 GT crack points with the estimated vs true transform
        T_true = np.array(gt["T_board1_from_board2"])
        T_est = np.array(cmp["T_board1_from_board2"])
        p = np.array(v2["cracks"][0]["pts_board_mm"])
        ph = np.hstack([p, np.ones((len(p), 1))])
        a = ph @ T_true.T
        b = ph @ T_est.T
        err = np.linalg.norm(a[:, :2] / a[:, 2:] - b[:, :2] / b[:, 2:], axis=1)
        rec["reg_err_mm"] = float(np.median(err))
    return rec


def run_e4(data_dir, out_dir, workers):
    files = sorted(glob.glob(os.path.join(data_dir, "e4_*.json")))
    with Pool(workers) as pool:
        recs = pool.map(eval_pair, files)
    json.dump(recs, open(os.path.join(out_dir, "e4_results.json"), "w"), indent=1)
    ok = [r for r in recs if r["cmp"]["status"] == "ok"]
    lines = [f"- Paires: {len(recs)}; comparables (fissure mesurée aux deux visites): {len(ok)}"]
    if not ok:
        return lines
    moved = [r for r in ok if r["card_moved"]]
    fixed = [r for r in ok if not r["card_moved"]]
    for name, grp in (("carte restée en place", fixed), ("carte recollée (déplacée)", moved)):
        if grp:
            e = [r["reg_err_mm"] for r in grp]
            modes = {}
            for r in grp:
                modes[r["cmp"]["registration"]["mode"]] = modes.get(r["cmp"]["registration"]["mode"], 0) + 1
            lines.append(f"- Recalage, {name}: {len(grp)} paires, erreur médiane {np.median(e):.2f} mm, P90 {np.percentile(e, 90):.2f} mm, modes {modes}")
    dw = np.array([r["cmp"]["width_delta_mm"]["median"] for r in ok])
    tw = np.array([r["widen"] for r in ok])
    lines.append(f"- Élargissement (médiane des écarts point à point): MAE **{np.mean(np.abs(dw - tw)):.3f} mm**, biais {np.mean(dw - tw):+.3f} mm")
    tbl = ["", "| élargissement vrai (mm) | paires | écart mesuré médian (mm) | MAE (mm) | détecté significatif |", "|---|---|---|---|---|"]
    for w in sorted(set(tw)):
        s = tw == w
        sig = np.mean([r["cmp"]["significant_widening"] for r, k in zip(ok, s) if k])
        tbl.append(f"| {w:.1f} | {s.sum()} | {np.median(dw[s]):+.3f} | {np.mean(np.abs(dw[s] - w)):.3f} | {100 * sig:.0f} % |")
    # growth detection
    ext = np.array([r["extend"] > 0 for r in ok])
    det = np.array([r["cmp"]["significant_growth"] for r in ok])
    wid = tw > 0
    sigw = np.array([r["cmp"]["significant_widening"] for r in ok])
    alarm = det | sigw
    change = ext | wid
    tp = (alarm & change).sum()
    fp = (alarm & ~change).sum()
    fn = (~alarm & change).sum()
    lines.append(f"- Alerte « évolution » (élargissement ou allongement significatif): précision {tp / max(1, tp + fp):.2f}, rappel {tp / max(1, tp + fn):.2f}, "
                 f"fausses alertes sur paires sans changement {fp}/{(~change).sum()}")
    nl = np.array([r["cmp"]["new_length_mm"] for r in ok])
    te = np.array([r["extend"] for r in ok])
    lines.append(f"- Allongement: MAE longueur nouvelle {np.mean(np.abs(nl - te)):.1f} mm (vrai 0/8/15 mm)")
    return lines + tbl

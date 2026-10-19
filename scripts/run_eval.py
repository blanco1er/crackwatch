"""Run the measurement pipeline over the synthetic set and report accuracy + failures.

usage: python scripts/run_eval.py --data data/synth --out eval
Writes eval/e1_results.json, eval/e4_results.json and eval/RESULTS.md
"""
import argparse
import glob
import json
import os
import sys
import time
from multiprocessing import Pool

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch.evaluate import score  # noqa: E402
from crackwatch.measure import measure_image  # noqa: E402


def _search_ok(rect):
    def f(p):
        uv = rect.mm_to_px(p)
        u = np.clip(uv[:, 0].astype(int), 0, rect.search.shape[1] - 1)
        v = np.clip(uv[:, 1].astype(int), 0, rect.search.shape[0] - 1)
        inside = (uv[:, 0] >= 0) & (uv[:, 0] < rect.search.shape[1]) & (uv[:, 1] >= 0) & (uv[:, 1] < rect.search.shape[0])
        return inside & rect.search[v, u]
    return f


def eval_e1(json_path):
    gt = json.load(open(json_path))
    img = cv2.imread(os.path.join(os.path.dirname(json_path), gt["image"]))
    t0 = time.time()
    res = measure_image(img, keep_debug=True)
    dt = time.time() - t0
    rec = {"id": gt["id"], "status": res.status, "time_s": dt, "quality": res.quality,
           "gt": {"w_base": gt["w_base_mm"], "max": gt["max_width_mm"], "median": gt["median_width_mm"],
                  "ppm": gt["cracks"][0]["img_ppm_median"], "tilt": gt["camera"]["tilt_deg"],
                  "blur": gt["degradations"]["blur_sigma_px"], "glare": gt["degradations"]["glare"],
                  "motion": gt["degradations"]["motion_px"], "jpeg": gt["degradations"]["jpeg_quality"],
                  "distractors": gt["distractors"]}}
    if res.status in ("ok", "no_crack_found"):
        rect = res.debug["rect"]
        sc = score(gt["cracks"], res.debug["comps"], _search_ok(rect))
        rec["score"] = sc
        rec["n_cracks"] = len(res.cracks)
        rec["n_rejected"] = len(res.rejected)
        rec["rejected_reasons"] = [r.get("reject") for r in res.rejected]
        if res.cracks:
            main = max(res.cracks, key=lambda c: c["length_mm"])
            rec["pred"] = {"max": main["width_mm"]["max"], "median": main["width_mm"]["median"],
                           "unc": main["uncertainty_mm"], "conf": main["confidence"],
                           "depth_source": main["depth_source"], "min_measurable": main["min_measurable_mm"]}
        # point-level errors for binning
        if sc.get("detected"):
            from crackwatch.evaluate import gt_points, nearest
            gp, gw, _ = gt_points(gt["cracks"], _search_ok(rect))
            mp = np.vstack([c["pts_mm"] for c in res.debug["comps"]])
            mw = np.concatenate([c["width_mm"] for c in res.debug["comps"]])
            md = np.concatenate([c["width_dt_mm"] for c in res.debug["comps"]])
            nat = np.concatenate([c["native_ppm"] for c in res.debug["comps"]])
            j, d = nearest(mp, gp)
            m = d <= np.maximum(1.0, 0.75 * gw[j])
            rec["pts"] = {"gt": gw[j[m]].round(4).tolist(), "meas": mw[m].round(4).tolist(),
                          "dt": md[m].round(4).tolist(), "ppm": nat[m].round(3).tolist()}
    return rec


def summarize_e1(recs):
    n = len(recs)
    card_ok = [r for r in recs if r["status"] != "no_card"]
    det = [r for r in card_ok if r.get("score", {}).get("detected")]
    lines = []
    lines.append(f"- Images: {n}; carte détectée: {len(card_ok)} ({100 * len(card_ok) / n:.1f} %); "
                 f"fissure détectée (>=10 points appariés): {len(det)} ({100 * len(det) / n:.1f} %)")
    G = np.concatenate([r["pts"]["gt"] for r in det if "pts" in r])
    M = np.concatenate([r["pts"]["meas"] for r in det if "pts" in r])
    DT = np.concatenate([r["pts"]["dt"] for r in det if "pts" in r])
    P = np.concatenate([r["pts"]["ppm"] for r in det if "pts" in r])
    e = M - G
    lines.append(f"- Points appariés: {len(G)}; MAE point par point: **{np.mean(np.abs(e)):.3f} mm** "
                 f"(biais {np.mean(e):+.3f}, médiane |e| {np.median(np.abs(e)):.3f}, P90 |e| {np.percentile(np.abs(e), 90):.3f}); "
                 f"ligne de base transformée de distance (pixel entier): MAE {np.nanmean(np.abs(DT - G)):.3f} mm")
    rel = np.abs(e) / G
    lines.append(f"- Erreur relative point par point: médiane {100 * np.median(rel):.1f} %, P90 {100 * np.percentile(rel, 90):.1f} %")
    em = np.array([r["score"]["err_max"] for r in det])
    ed = np.array([r["score"]["err_median"] for r in det])
    lines.append(f"- Par image (fissure principale + branches): MAE largeur max **{np.mean(np.abs(em)):.3f} mm** (biais {np.mean(em):+.3f}), "
                 f"MAE largeur médiane **{np.mean(np.abs(ed)):.3f} mm** (biais {np.mean(ed):+.3f})")
    rec_ = np.array([r["score"]["recall"] for r in det])
    pre = np.array([r["score"]["precision"] for r in det])
    lines.append(f"- Couverture de la fissure (rappel) moyenne {rec_.mean():.2f}; précision des points {pre.mean():.2f}")
    tbl = ["", "| Largeur vraie (mm) | points | MAE (mm) | biais (mm) | MAE relative médiane | MAE base DT (mm) |", "|---|---|---|---|---|---|"]
    for lo, hi in ((0.1, 0.3), (0.3, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, 3.0), (3.0, 6.0)):
        s = (G >= lo) & (G < hi)
        if s.sum():
            tbl.append(f"| {lo}–{hi} | {s.sum()} | {np.mean(np.abs(e[s])):.3f} | {np.mean(e[s]):+.3f} | {100 * np.median(rel[s]):.1f} % | {np.nanmean(np.abs(DT[s] - G[s])):.3f} |")
    tbl += ["", "| Largeur vraie en pixels photo | points | MAE (mm) | MAE relative médiane |", "|---|---|---|---|"]
    W = G * P
    for lo, hi in ((0, 1), (1, 2), (2, 4), (4, 8), (8, 100)):
        s = (W >= lo) & (W < hi)
        if s.sum():
            tbl.append(f"| {lo}–{hi} px | {s.sum()} | {np.mean(np.abs(e[s])):.3f} | {100 * np.median(rel[s]):.1f} % |")
    # image-level by tilt
    tbl += ["", "| Inclinaison | images détectées | MAE largeur max (mm) | MAE largeur médiane (mm) |", "|---|---|---|---|"]
    for lo, hi in ((0, 15), (15, 30), (30, 46)):
        s = [r for r in det if lo <= r["gt"]["tilt"] < hi]
        if s:
            tbl.append(f"| {lo}–{hi}° | {len(s)} | {np.mean([abs(r['score']['err_max']) for r in s]):.3f} | {np.mean([abs(r['score']['err_median']) for r in s]):.3f} |")
    # uncertainty coverage on the median width
    cov = [abs(r["score"]["err_median"]) <= 2 * r["pred"]["unc"] for r in det if "pred" in r]
    lines.append(f"- Couverture de l'incertitude annoncée (|erreur médiane| <= 2 sigma): {100 * np.mean(cov):.0f} % des images")
    # failures
    fails = []
    for r in recs:
        why = None
        if r["status"] == "no_card":
            why = "carte non détectée"
        elif not r.get("score", {}).get("detected"):
            why = "fissure non détectée"
        elif abs(r["score"]["err_max"]) > max(0.3, 0.3 * r["score"]["gt_max_matched"]):
            why = "erreur largeur max > max(0,3 mm, 30 %)"
        if why:
            g = r["gt"]
            fails.append(f"| {r['id']} | {why} | {g['w_base']:.2f} | {g['ppm']:.1f} | {g['tilt']:.0f} | {g['blur']:.2f} | "
                         f"{'oui' if g['glare'] else ''} | {g['motion'] or ''} | {'joint' if g['distractors']['joint'] else ''}{' tache' if g['distractors']['stain'] else ''} | "
                         f"{r.get('score', {}).get('err_max', float('nan')):+.2f} |")
    fl = ["", f"Cas d'échec ({len(fails)} / {n}) :", "",
          "| image | raison | largeur base (mm) | px/mm photo | incl. (°) | flou (px) | reflet | bougé (px) | distracteurs | err. max (mm) |",
          "|---|---|---|---|---|---|---|---|---|---|"] + fails
    return lines, tbl, fl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/synth")
    ap.add_argument("--out", default="eval")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--skip-e4", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    files = sorted(glob.glob(os.path.join(a.data, "e1", "*.json")))
    if a.limit:
        files = files[:a.limit]
    t0 = time.time()
    with Pool(a.workers) as pool:
        recs = pool.map(eval_e1, files)
    json.dump(recs, open(os.path.join(a.out, "e1_results.json"), "w"))
    lines, tbl, fl = summarize_e1(recs)
    times = np.array([r["time_s"] for r in recs])
    lines.append(f"- Temps de calcul par image (Mac M2, 1 cœur par image): médiane {np.median(times):.2f} s, P95 {np.percentile(times, 95):.2f} s")
    md = ["# Résultats d'évaluation (synthétique)", "", f"Généré par `scripts/run_eval.py` le {time.strftime('%Y-%m-%d %H:%M')}, OpenCV {cv2.__version__}.", "",
          "## E1 — largeur de fissure (images synthétiques)", ""] + lines + tbl + fl
    if not a.skip_e4 and glob.glob(os.path.join(a.data, "e4", "*.json")):
        from eval_e4 import run_e4
        md += ["", "## E4 — évolution entre deux visites (paires synthétiques)", ""] + run_e4(os.path.join(a.data, "e4"), a.out, a.workers)
    open(os.path.join(a.out, "RESULTS.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))
    print(f"\n[{time.time() - t0:.0f} s]")


if __name__ == "__main__":
    main()

"""Synthetic evaluation of the wallet-card (ID-1) reference against the printed ChArUco card, scene by scene.

  python scripts/eval_idcard.py --n 300 --out eval_idcard                 # scale only (fast)
  python scripts/eval_idcard.py --n 120 --widths --out eval_idcard        # + crack widths with both references

Each scene (crackwatch/synth_idcard.py) is rendered twice with the same wall, crack, camera and noise: once
with the ChArUco card, once with an ID-1 card (thickness, side wall, contact shadow, gloss, optional finger).
Scale error = singular values of J_est^-1 J_true at the crack centre (worst direction), in %.
Writes <out>/idcard_results.json and <out>/RESULTS-carte.md (French, like the other RESULTS files).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from multiprocessing import Pool

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch.evaluate import score  # noqa: E402
from crackwatch.idcard import detect_idcard  # noqa: E402
from crackwatch.measure import detect_card, measure_image  # noqa: E402
from crackwatch.synth import apply_h  # noqa: E402
from crackwatch.synth_idcard import make_scene, scale_errors  # noqa: E402


def _wall_comps(comps, H_est, H_img_from_wall):
    """Measured skeleton points moved from the estimated metric frame to the true wall frame (widths kept:
    their scale error is what we evaluate)."""
    T = np.linalg.inv(H_img_from_wall) @ H_est
    out = []
    for c in comps:
        d = dict(c)
        d["pts_mm"] = apply_h(T, c["pts_mm"])
        out.append(d)
    return out


def _widths(img, reference, sc):
    res = measure_image(img, keep_debug=True, reference=reference)
    rec = {"status": res.status}
    if res.status not in ("ok", "no_crack_found"):
        return rec
    card = res.debug["card"]
    rect = res.debug["rect"]
    Hw = sc["H_img_from_wall"]
    T_wall_to_est = np.linalg.inv(card.H_img_from_board) @ Hw

    def search_ok(p):
        uv = rect.mm_to_px(apply_h(T_wall_to_est, p))
        u = np.clip(uv[:, 0].astype(int), 0, rect.search.shape[1] - 1)
        v = np.clip(uv[:, 1].astype(int), 0, rect.search.shape[0] - 1)
        inside = (uv[:, 0] >= 0) & (uv[:, 0] < rect.search.shape[1]) & (uv[:, 1] >= 0) & (uv[:, 1] < rect.search.shape[0])
        return inside & rect.search[v, u]
    sc_ = score(sc["cracks"], _wall_comps(res.debug["comps"], card.H_img_from_board, Hw), search_ok)
    rec["score"] = {k: v for k, v in sc_.items() if isinstance(v, (int, float, bool))}
    if res.cracks:
        main = max(res.cracks, key=lambda c: c["length_mm"])
        rec["pred"] = {"max": main["width_mm"]["max"], "median": main["width_mm"]["median"], "unc": main["uncertainty_mm"],
                       "conf": main["confidence"]}
    return rec


def run_one(args):
    seed, widths, exif = args
    sc = make_scene(seed)
    if sc is None:
        return None
    cam = sc["camera"]
    cc = sc["crack_center_wall"]
    r = {"seed": seed, "finger": sc["finger"], "face_style": sc["face_style"], "shadow": sc["shadow"],
         "tilt": cam["tilt_deg"], "ppm_look": cam["ppm"], "focal_px": cam["focal_px"], "blur": sc["degradations"]["blur_sigma_px"],
         "glare": sc["degradations"]["glare"], "motion": sc["degradations"]["motion_px"], "w_base": sc["w_base_mm"]}
    Hc = sc["H_img_from_card_face"]
    r["card_ppm_true"] = float(np.sqrt(abs(np.linalg.det(
        np.column_stack([(apply_h(Hc, [(42.8 + 0.05, 27)])[0] - apply_h(Hc, [(42.8, 27)])[0]) / 0.05,
                         (apply_h(Hc, [(42.8, 27 + 0.05)])[0] - apply_h(Hc, [(42.8, 27)])[0]) / 0.05])))))
    t0 = time.time()
    det, rep = detect_idcard(sc["img_idcard"], focal_px=cam["focal_px"] if exif else None)
    r["t_detect"] = time.time() - t0
    r["status"] = rep.status
    r["detail"] = rep.detail
    r["occluded_edge"] = rep.quality.get("card_occluded_edge")
    if det is not None:
        x = apply_h(sc["H_img_from_wall"], [cc])[0]
        p_est = apply_h(np.linalg.inv(det.H_img_from_board), [x])[0]
        r.update({"err": scale_errors(det.H_img_from_board, sc["H_img_from_wall"], cc),
                  "err_face": scale_errors(det.H_img_from_card_face, sc["H_img_from_wall"], cc),
                  "err_card": scale_errors(det.H_img_from_board, sc["H_img_from_wall"],
                                           apply_h(np.linalg.inv(sc["H_img_from_wall"]) @ sc["H_img_from_card_wall"], [(42.8, 27.0)])[0]),
                  "unc_crack": det.scale_rel_unc_at(p_est), "unc_card": det.scale_rel_unc, "unc_terms": det.unc_terms,
                  "tilt_est": det.tilt_deg, "focal_est": det.focal_px, "focal_src": det.focal_source, "ppm": det.px_per_mm,
                  "recovered": det.recovered_edge, "blur_est": det.blur_sigma_px, "rms": det.reproj_rms_px,
                  "aspect": det.aspect_measured, "corner_cut": det.corner_cut_mm, "confidence": det.confidence,
                  "dist_crack_mm": float(np.linalg.norm(p_est - (42.8, 27.0))), "corner_support": det.corner_support,
                  "corner_rms": det.corner_rms_px})
    ch = detect_card(cv2.cvtColor(sc["img_charuco"], cv2.COLOR_BGR2GRAY))
    if ch is not None:
        r["err_charuco"] = scale_errors(ch.H_img_from_board, sc["H_img_from_wall"], cc)
    if widths:
        r["w_charuco"] = _widths(sc["img_charuco"], "charuco", sc)
        r["w_idcard"] = _widths(sc["img_idcard"], "idcard", sc)
    return r


def pct(v):
    return f"{100 * v:.2f} %"


def summarize(R, widths):
    R = [r for r in R if r]
    n = len(R)
    ok = [r for r in R if r["status"] == "ok"]
    md = []
    st = {}
    for r in R:
        st[r["status"]] = st.get(r["status"], 0) + 1
    md.append(f"- Scènes : {n} ; carte acceptée : {len(ok)} ({100 * len(ok) / n:.0f} %) ; statuts : "
              + ", ".join(f"{k} {v}" for k, v in sorted(st.items(), key=lambda kv: -kv[1])))
    within = [r for r in R if r["tilt"] <= 40 and r["card_ppm_true"] >= 3.2]
    okw = [r for r in within if r["status"] == "ok"]
    md.append(f"- Dans le domaine annoncé (inclinaison ≤ 40°, carte ≥ 3,2 px/mm) : {len(okw)}/{len(within)} acceptées "
              f"({100 * len(okw) / max(1, len(within)):.0f} %)")

    def errstats(rows, key):
        e = np.array([max(abs(r[key][0]), abs(r[key][1])) for r in rows if r.get(key)])
        if not len(e):
            return "—"
        return f"médiane {pct(np.median(e))}, P90 {pct(np.percentile(e, 90))}, P95 {pct(np.percentile(e, 95))}, max {pct(e.max())} (n={len(e)})"
    md += ["", "Erreur d'échelle relative au centre de la fissure (pire direction) :", "",
           f"- Carte bancaire (ID-1, épaisseur corrigée) : {errstats(ok, 'err')}",
           f"- même chose sans correction d'épaisseur : {errstats(ok, 'err_face')}",
           f"- Carte ChArUco imprimée, mêmes scènes : {errstats([r for r in ok if r.get('err_charuco')], 'err_charuco')}",
           f"- Carte bancaire, au centre de la carte : {errstats(ok, 'err_card')}"]
    signed = np.array([np.mean(r["err"]) for r in ok])
    if len(signed):
        md.append(f"- Biais moyen (moyenne des deux valeurs singulières − 1) : {pct(np.mean(signed))} ± {pct(np.std(signed))}")
    z = np.array([max(abs(r["err"][0]), abs(r["err"][1])) / max(r["unc_crack"], 1e-9) for r in ok])
    if len(z):
        md.append(f"- Incertitude annoncée (1 σ) : médiane {pct(np.median([r['unc_crack'] for r in ok]))} ; "
                  f"erreur ≤ 2 σ dans {100 * np.mean(z <= 2):.0f} % des cas, ≤ 3 σ dans {100 * np.mean(z <= 3):.0f} %")
    md += ["", "| Doigt | scènes | acceptées | erreur médiane | P90 | bord reconstruit | refus « card_occluded » |", "|---|---|---|---|---|---|---|"]
    for f in ("none", "short_mid", "long_mid", "corner", "short_full"):
        rows = [r for r in R if r["finger"] == f]
        if not rows:
            continue
        o = [r for r in rows if r["status"] == "ok"]
        e = np.array([max(abs(r["err"][0]), abs(r["err"][1])) for r in o])
        md.append(f"| {f} | {len(rows)} | {len(o)} | {pct(np.median(e)) if len(e) else '—'} | {pct(np.percentile(e, 90)) if len(e) else '—'} | "
                  f"{sum(r.get('recovered') is not None for r in o)} | {sum(r['status'] == 'card_occluded' for r in rows)} |")
    md += ["", "| Inclinaison | acceptées | erreur médiane carte | P90 | erreur médiane ChArUco |", "|---|---|---|---|---|"]
    for lo, hi in ((0, 15), (15, 30), (30, 41), (41, 60)):
        o = [r for r in ok if lo <= r["tilt"] < hi]
        e = np.array([max(abs(r["err"][0]), abs(r["err"][1])) for r in o])
        ec = np.array([max(abs(r["err_charuco"][0]), abs(r["err_charuco"][1])) for r in o if r.get("err_charuco")])
        md.append(f"| {lo}–{hi}° | {len(o)} | {pct(np.median(e)) if len(e) else '—'} | {pct(np.percentile(e, 90)) if len(e) else '—'} | "
                  f"{pct(np.median(ec)) if len(ec) else '—'} |")
    be = [(r["blur_est"], r["blur"]) for r in ok if r.get("blur_est")]
    if be:
        b = np.array(be)
        md.append("")
        md.append(f"- Flou estimé sur les bords de la carte vs vrai : erreur médiane {np.median(b[:, 0] - b[:, 1]):+.2f} px, "
                  f"MAE {np.mean(np.abs(b[:, 0] - b[:, 1])):.2f} px")
    md.append(f"- Temps de détection : médiane {np.median([r['t_detect'] for r in R]):.2f} s, P95 {np.percentile([r['t_detect'] for r in R], 95):.2f} s")
    if widths:
        md += ["", "Largeur de fissure, mêmes scènes, les deux références (fissure détectée par les deux) :", ""]
        both = [r for r in R if r["w_charuco"].get("score", {}).get("detected") and r["w_idcard"].get("score", {}).get("detected")]
        for key, name in (("err_max", "largeur max"), ("err_median", "largeur médiane")):
            a = np.array([r["w_charuco"]["score"][key] for r in both])
            b = np.array([r["w_idcard"]["score"][key] for r in both])
            if len(a):
                md.append(f"- {name} : MAE ChArUco **{np.mean(np.abs(a)):.3f} mm** (biais {np.mean(a):+.3f}) ; "
                          f"MAE carte bancaire **{np.mean(np.abs(b)):.3f} mm** (biais {np.mean(b):+.3f}) ; "
                          f"écart médian entre les deux |b − a| {np.median(np.abs(b - a)):.3f} mm (n={len(a)})")
        rel = np.array([r["w_idcard"]["score"]["meas_median"] / r["w_charuco"]["score"]["meas_median"] - 1 for r in both
                        if r["w_charuco"]["score"].get("meas_median")])
        if len(rel):
            md.append(f"- Rapport des largeurs médianes carte/ChArUco − 1 : médiane {pct(np.median(rel))}, P90 |.| {pct(np.percentile(np.abs(rel), 90))}")
        md.append(f"- Fissure détectée : ChArUco {sum(bool(r['w_charuco'].get('score', {}).get('detected')) for r in R)}/{n}, "
                  f"carte bancaire {sum(bool(r['w_idcard'].get('score', {}).get('detected')) for r in R)}/{n}")
    return md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed0", type=int, default=50000)
    ap.add_argument("--widths", action="store_true")
    ap.add_argument("--exif", action="store_true", help="give the true focal to the card detector (EXIF case)")
    ap.add_argument("--out", default="eval_idcard")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    with Pool(a.workers) as pool:
        R = pool.map(run_one, [(s, a.widths, a.exif) for s in range(a.seed0, a.seed0 + a.n)], chunksize=1)
    R = [r for r in R if r]
    json.dump(R, open(os.path.join(a.out, "idcard_results%s.json" % ("_widths" if a.widths else ("_exif" if a.exif else ""))), "w"),
              default=float)
    md = ["# Carte bancaire comme référence d'échelle — évaluation synthétique", "",
          f"Généré par `scripts/eval_idcard.py` le {time.strftime('%Y-%m-%d %H:%M')}, OpenCV {cv2.__version__}, graines {a.seed0}–{a.seed0 + a.n - 1}.", ""]
    md += summarize(R, a.widths)
    name = "RESULTS-carte-largeurs.md" if a.widths else ("RESULTS-carte-exif.md" if a.exif else "RESULTS-carte.md")
    if a.exif:
        md.insert(3, "Mode EXIF : la vraie focale est donnée au détecteur (comme si l'app envoyait FocalLengthIn35mmFilm).")
    open(os.path.join(a.out, name), "w").write("\n".join(md) + "\n")
    print("\n".join(md))
    print(f"[{time.time() - t0:.0f} s]")


if __name__ == "__main__":
    main()

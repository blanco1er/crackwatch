"""Real photos with a wallet card (ID-1) as the scale reference, checked against the printed ChArUco card.

Folder layout (any subset; .jpg .jpeg .png .heic):
  <dir>/mire/        the wallet card held flat next to the printed test chart v1 (print/mire_v1.pdf):
                     ground truth = the chart's ChArUco board (scale) and its 8 bars of known width
  <dir>/fissure-*/   a real crack with BOTH the stuck printed card and the wallet card in the photo:
                     same photo measured twice, once per reference
  <dir>/seule/       wallet card only (the real use case): status, retake reasons, repeatability
  <dir>/../regle.txt optional: what the printed card's 50 mm ruler measured (printer scale), as process_real.py

  python scripts/eval_idcard_real.py --dir ../photos-reelles/carte-portefeuille --out eval_real_carte
Writes <out>/RESULTS-carte-reelle.md (French), <out>/carte_real.json and redacted overlays (card numbers blurred).
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import sys
import tempfile
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch.idcard import detect_idcard, redact_reference  # noqa: E402
from crackwatch.measure import apply_h, detect_card, measure_image  # noqa: E402
from crackwatch.service import render_overlay  # noqa: E402
from scripts.process_real import MIRE_BOARD_RECT, ROOT, list_photos, load  # noqa: E402


def jac(H, p):
    e = 0.05
    q = apply_h(H, [p, (p[0] + e, p[1]), (p[0], p[1] + e)])
    return np.column_stack([(q[1] - q[0]) / e, (q[2] - q[0]) / e])


def scale_vs(H_ref, H_test, pt_ref, ref_fix=1.0):
    """Relative scale of H_test vs H_ref (true mm = ref mm x ref_fix) at a point of the ref frame, worst
    direction: singular values of J_test^-1 J_ref / ref_fix - 1."""
    x = apply_h(H_ref, [pt_ref])[0]
    pt_t = apply_h(np.linalg.inv(H_test), [x])[0]
    M = np.linalg.solve(jac(H_test, pt_t), jac(H_ref, pt_ref)) / ref_fix
    s = np.linalg.svd(M, compute_uv=False)
    return float(s.min() - 1), float(s.max() - 1)


def paint_out(img, polys):
    """Hide image polygons (the other reference, chart labels) from the crack search: local median fill."""
    out = img.copy()
    for P in polys:
        P = np.round(np.asarray(P)).astype(np.int32)
        m = np.zeros(img.shape[:2], np.uint8)
        cv2.fillPoly(m, [P], 255)
        m = cv2.dilate(m, np.ones((9, 9), np.uint8))
        ring = cv2.dilate(m, np.ones((31, 31), np.uint8)) & ~m
        col = np.median(img[ring > 0], axis=0) if (ring > 0).any() else np.array([128, 128, 128])
        out[m > 0] = col
    return out


def board_poly(card, rect):
    x0, y0, x1, y1 = rect
    return apply_h(card.H_img_from_board, [(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def bars(res_debug, T_mire_from_meas, mire, fix, tol_mm=1.6):
    comps = (res_debug or {}).get("comps") or []
    if not comps:
        return {}
    pts = apply_h(T_mire_from_meas, np.vstack([c["pts_mm"] for c in comps]))
    w = np.concatenate([c["width_mm"] for c in comps])
    out = {}
    for ln in mire["lines"]:
        on = (np.abs(pts[:, 0] - ln["x_mm"]) < tol_mm + ln["width_mm"] / 2) & (pts[:, 1] > ln["y0_mm"] + 2) & (pts[:, 1] < ln["y1_mm"] - 2)
        if on.sum() >= 10:
            out[ln["label"]] = {"nominal_mm": round(ln["width_mm"] * fix, 3), "measured_mm": round(float(np.median(w[on])), 3)}
    return out


def overlay(path, img, res):
    with open(path, "wb") as fh:
        fh.write(render_overlay(redact_reference(img, res), res))


def do_mire(folder, tmp, odir, fix):
    mire = json.load(open(os.path.join(ROOT, "print", "mire_v1.json")))
    rows = []
    bar_c = (float(np.mean([ln["x_mm"] for ln in mire["lines"]])), float(np.mean([(ln["y0_mm"] + ln["y1_mm"]) / 2 for ln in mire["lines"]])))
    for i, p in enumerate(list_photos(folder)):
        img = load(p, tmp)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        ch = detect_card(gray)
        # the chart's own squares and bars form rectangles too: hide them before looking for the wallet card
        pexcl = [board_poly(ch, MIRE_BOARD_RECT)] + [board_poly(ch, rr) for rr in mire["exclude_rects_mm"]] if ch is not None else []
        img_id = paint_out(img, pexcl)
        det, rep = detect_idcard(img_id)
        r = {"photo": os.path.basename(p), "charuco": ch is not None, "idcard": rep.status, "detail": rep.detail}
        if det is not None:
            r.update({"ppm": round(det.px_per_mm, 2), "tilt": round(det.tilt_deg, 1), "unc_card_pct": round(100 * det.scale_rel_unc, 2),
                      "rebuilt_edge": det.edges[det.recovered_edge]["image_side"] if det.recovered_edge is not None else None})
        if ch is not None and det is not None:
            # scale agreement at the bars and at the card
            r["scale_err_bars_pct"] = [round(100 * v, 2) for v in scale_vs(ch.H_img_from_board, det.H_img_from_board, bar_c, fix)]
            card_c = apply_h(np.linalg.inv(ch.H_img_from_board) @ det.H_img_from_board, [(42.8, 27.0)])[0]
            r["scale_err_card_pct"] = [round(100 * v, 2) for v in scale_vs(ch.H_img_from_board, det.H_img_from_board, card_c, fix)]
            r["dist_card_bars_mm"] = round(float(np.linalg.norm(np.array(card_c) - bar_c)), 1)
            res_id = measure_image(img_id, keep_debug=True, reference="idcard")
            res_ch = measure_image(img, exclude_rects_mm=[tuple(x) for x in mire["exclude_rects_mm"]], keep_debug=True,
                                   paper_rect_mm=MIRE_BOARD_RECT, reference="charuco")
            if res_id.status == "ok":
                T = np.linalg.inv(ch.H_img_from_board) @ res_id.debug["card"].H_img_from_board
                r["bars_idcard"] = bars(res_id.debug, T, mire, fix)
                if i < 3:
                    overlay(os.path.join(odir, f"mire_carte_{i + 1}.jpg"), img, res_id)
            if res_ch.status == "ok":
                r["bars_charuco"] = bars(res_ch.debug, np.eye(3), mire, fix)
        rows.append(r)
    return rows


def do_fissure(folder, tmp, odir):
    rows = []
    for i, p in enumerate(list_photos(folder)):
        img = load(p, tmp)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        ch = detect_card(gray)
        img_id = paint_out(img, [board_poly(ch, ch.spec.paper_rect_in_board_frame())]) if ch is not None else img
        det, rep = detect_idcard(img_id)
        r = {"photo": os.path.basename(p), "charuco": ch is not None, "idcard": rep.status, "detail": rep.detail}
        res_ch = res_id = None
        if ch is not None:
            hide = rep.redact_polys_img if rep.redact_polys_img else []
            res_ch = measure_image(paint_out(img, hide), keep_debug=True, reference="charuco")
        if det is not None:
            res_id = measure_image(img_id, keep_debug=True, reference="idcard")
            r.update({"ppm": round(det.px_per_mm, 2), "tilt": round(det.tilt_deg, 1), "unc_card_pct": round(100 * det.scale_rel_unc, 2)})
        for name, res in (("charuco", res_ch), ("idcard", res_id)):
            if res is not None and res.cracks:
                c = res.cracks[0]
                r[name + "_crack"] = {"median_mm": c["width_mm"]["median"], "max_mm": c["width_mm"]["max"],
                                      "length_mm": c["length_mm"], "unc_mm": c["uncertainty_mm"]}
        if ch is not None and det is not None and res_ch is not None and res_ch.cracks:
            bx = res_ch.cracks[0]["bbox_board_mm"]
            r["scale_err_crack_pct"] = [round(100 * v, 2) for v in scale_vs(ch.H_img_from_board, det.H_img_from_board,
                                                                             ((bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2))]
        if res_id is not None and res_id.status == "ok" and i < 3:
            overlay(os.path.join(odir, f"{os.path.basename(folder)}_carte_{i + 1}.jpg"), img, res_id)
        rows.append(r)
    return rows


def do_seule(folder, tmp, odir):
    rows = []
    for i, p in enumerate(list_photos(folder)):
        img = load(p, tmp)
        res = measure_image(img, keep_debug=True, reference="idcard")
        q = res.quality
        r = {"photo": os.path.basename(p), "status": res.status, "retake_reason": q.get("retake_reason"),
             "occluded_edge": q.get("card_occluded_edge"), "ppm": q.get("card_px_per_mm"), "scale_unc_pct": None}
        if res.card:
            r["scale_unc_pct"] = round(100 * res.card.get("scale_rel_unc", float("nan")), 2)
        if res.cracks:
            c = res.cracks[0]
            r.update({"median_mm": c["width_mm"]["median"], "max_mm": c["width_mm"]["max"], "unc_mm": c["uncertainty_mm"]})
        if i < 3:
            overlay(os.path.join(odir, f"seule_{i + 1}.jpg"), img, res)
        rows.append(r)
    return rows


def f2(v):
    return "—" if v is None else (f"{v[0]:+.2f} / {v[1]:+.2f}" if isinstance(v, list) else str(v))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", default="eval_real_carte")
    a = ap.parse_args()
    odir = os.path.join(a.out, "overlays")
    os.makedirs(odir, exist_ok=True)
    fix = 1.0
    for rf in (os.path.join(a.dir, "regle.txt"), os.path.join(a.dir, "..", "regle.txt")):
        if os.path.exists(rf):
            try:
                fix = float(open(rf).read().strip().replace(",", ".")) / 50.0
                break
            except ValueError:
                pass
    md = ["# Carte bancaire comme référence — vraies photos", "",
          f"Généré par `scripts/eval_idcard_real.py` le {time.strftime('%Y-%m-%d %H:%M')}, OpenCV {cv2.__version__}. "
          f"Facteur d'échelle de l'impression (règle 50 mm) : {fix:.4f}.", ""]
    results = {"print_scale_fix": fix}
    with tempfile.TemporaryDirectory() as tmp:
        folder = os.path.join(a.dir, "mire")
        if list_photos(folder):
            rows = do_mire(folder, tmp, odir, fix)
            results["mire"] = rows
            e = [max(abs(v) for v in r["scale_err_bars_pct"]) for r in rows if "scale_err_bars_pct" in r]
            md += ["## Mire v1 + carte bancaire (vérité : damier ChArUco de la mire et largeurs des traits)", "",
                   f"- Photos : {len(rows)} ; carte acceptée : {sum(r['idcard'] == 'ok' for r in rows)} ; ChArUco trouvé : {sum(r['charuco'] for r in rows)}",
                   f"- Écart d'échelle carte vs ChArUco au centre des traits (pire direction) : "
                   + (f"médiane {np.median(e):.2f} %, max {np.max(e):.2f} %" if e else "—"), "",
                   "| Photo | carte | px/mm | incl. (°) | ± annoncé (%) | écart échelle traits (%) | écart au centre carte (%) |", "|---|---|---|---|---|---|---|"]
            for r in rows:
                md.append(f"| {r['photo']} | {r['idcard']} | {r.get('ppm', '—')} | {r.get('tilt', '—')} | {r.get('unc_card_pct', '—')} | "
                          f"{f2(r.get('scale_err_bars_pct'))} | {f2(r.get('scale_err_card_pct'))} |")
            labels = [ln for ln in ("L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8")]
            md += ["", "Largeur des traits (médiane des photos), mm :", "", "| Trait | nominal | ChArUco | carte bancaire |", "|---|---|---|---|"]
            for L in labels:
                nom = [r["bars_charuco"][L]["nominal_mm"] for r in rows if L in r.get("bars_charuco", {})] or \
                      [r["bars_idcard"][L]["nominal_mm"] for r in rows if L in r.get("bars_idcard", {})]
                mc = [r["bars_charuco"][L]["measured_mm"] for r in rows if L in r.get("bars_charuco", {})]
                mi = [r["bars_idcard"][L]["measured_mm"] for r in rows if L in r.get("bars_idcard", {})]
                if nom:
                    md.append(f"| {L} | {nom[0]:.2f} | {np.median(mc):.3f} ({len(mc)}) | " if mc else f"| {L} | {nom[0]:.2f} | — | ")
                    md[-1] += f"{np.median(mi):.3f} ({len(mi)}) |" if mi else "— |"
            md.append("")
        for folder in sorted(glob.glob(os.path.join(a.dir, "fissure-*"))):
            if not list_photos(folder):
                continue
            rows = do_fissure(folder, tmp, odir)
            name = os.path.basename(folder)
            results[name] = rows
            both = [r for r in rows if "charuco_crack" in r and "idcard_crack" in r]
            rel = [r["idcard_crack"]["median_mm"] / r["charuco_crack"]["median_mm"] - 1 for r in both if r["charuco_crack"]["median_mm"]]
            md += [f"## {name} — même photo, deux références", "",
                   f"- Photos : {len(rows)} ; mesurées par les deux : {len(both)} ; "
                   f"rapport des largeurs médianes carte/ChArUco − 1 : " + (f"médiane {100 * np.median(rel):+.1f} %, max |.| {100 * np.max(np.abs(rel)):.1f} %" if rel else "—"), "",
                   "| Photo | carte | ChArUco médiane / max (mm) | carte médiane / max (mm) | écart échelle à la fissure (%) |", "|---|---|---|---|---|"]
            for r in rows:
                c, d = r.get("charuco_crack"), r.get("idcard_crack")
                md.append(f"| {r['photo']} | {r['idcard']} | {f'{c['median_mm']:.3f} / {c['max_mm']:.3f}' if c else '—'} | "
                          f"{f'{d['median_mm']:.3f} / {d['max_mm']:.3f}' if d else '—'} | {f2(r.get('scale_err_crack_pct'))} |")
            md.append("")
        folder = os.path.join(a.dir, "seule")
        if list_photos(folder):
            rows = do_seule(folder, tmp, odir)
            results["seule"] = rows
            med = [r["median_mm"] for r in rows if r.get("median_mm")]
            cv = float(np.std(med, ddof=1) / np.mean(med)) if len(med) >= 3 else None
            md += ["## Carte bancaire seule (usage réel)", "",
                   f"- Photos : {len(rows)} ; statuts : " + ", ".join(f"{s} {sum(r['status'] == s for r in rows)}" for s in sorted({r['status'] for r in rows})),
                   f"- Répétabilité de la largeur médiane : " + (f"CV {100 * cv:.1f} %" if cv is not None else "—"), "",
                   "| Photo | statut | reprise | bord masqué | ± échelle (%) | médiane (mm) | max (mm) |", "|---|---|---|---|---|---|---|"]
            for r in rows:
                md.append(f"| {r['photo']} | {r['status']} | {r['retake_reason'] or ''} | {r['occluded_edge'] or ''} | {r['scale_unc_pct']} | "
                          f"{r.get('median_mm', '—')} | {r.get('max_mm', '—')} |")
    if len(md) < 6:
        md.append("Aucune photo trouvée (dossiers attendus : mire/, fissure-*/, seule/).")
    open(os.path.join(a.out, "RESULTS-carte-reelle.md"), "w").write("\n".join(md) + "\n")
    json.dump(results, open(os.path.join(a.out, "carte_real.json"), "w"), indent=1,
              default=lambda o: None if isinstance(o, float) and math.isnan(o) else str(o))
    print("\n".join(md))


if __name__ == "__main__":
    main()

"""Real-photo evaluation (E2 printed chart, E4 real two-visit chart, E3 real cracks) in one command.

Folder layout (names are fixed; any subset may be present; .jpg .jpeg .png .heic accepted):
  <dir>/mire-v1/        photos of the printed test chart v1 (8 bars of known width)
  <dir>/mire-v2/        photos of chart v2 (bars 3, 5, 7 wider; bars 2, 6 longer) = simulated second visit
  <dir>/fissure-A/      ~10 photos of one real crack with the A6 card taped next to it (repeatability)
  <dir>/fissure-B/      same for a second crack (any folder whose name starts with "fissure-")
  <dir>/regle.txt       optional: what the 50 mm ruler of the printed card measured, e.g. "49.6"

  python scripts/process_real.py --dir ../photos-reelles --out eval_real
Writes <out>/RESULTS.md (French, for the owner and the report), <out>/real_results.json and a few overlays.
No AWS call: the decisions use the deterministic rule policy (the same one that validates the LLM).
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import subprocess
import sys
import tempfile
import time

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch.agent import AgentState, decide_next_action  # noqa: E402
from crackwatch.change import compare  # noqa: E402
from crackwatch.measure import measure_image  # noqa: E402
from crackwatch.service import render_overlay  # noqa: E402

ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
EXTS = (".jpg", ".jpeg", ".png", ".heic", ".heif")
MIRE_BOARD_RECT = (-3.0, -3.0, 75.0, 108.0)    # the chart board (75 x 105 mm), hidden from the crack search; rectify() adds 4 mm, so bar L1 at x = 82 mm stays searchable


def f(v, spec=".3f", suffix=""):
    return "—" if v is None else f"{v:{spec}}{suffix}"


def list_photos(folder):
    return sorted(p for p in glob.glob(os.path.join(folder, "*")) if p.lower().endswith(EXTS))


def load(path, tmp):
    if path.lower().endswith((".heic", ".heif")):        # iPhone default format: convert with macOS sips
        out = os.path.join(tmp, os.path.basename(path) + ".jpg")
        subprocess.run(["sips", "-s", "format", "jpeg", path, "--out", out], check=True, capture_output=True)
        path = out
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"cannot read {path}")
    s = 4032 / max(img.shape[:2])
    return cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA) if s < 1 else img


def bar_widths(res, mire, tol_mm=1.6):
    """Per bar: median of the measured width at skeleton points lying on that bar."""
    comps = (res.debug or {}).get("comps") or []
    if not comps:
        return {}
    pts = np.vstack([c["pts_mm"] for c in comps])
    w = np.concatenate([c["width_mm"] for c in comps])
    out = {}
    for ln in mire["lines"]:
        on = (np.abs(pts[:, 0] - ln["x_mm"]) < tol_mm + ln["width_mm"] / 2) & (pts[:, 1] > ln["y0_mm"] + 2) & (pts[:, 1] < ln["y1_mm"] - 2)
        L = ln["y1_mm"] - ln["y0_mm"] - 4
        cover = float(on.sum()) / max(1.0, L * res.debug["rect"].R) if on.any() else 0.0
        if on.sum() >= 10:
            out[ln["label"]] = {"nominal_mm": ln["width_mm"], "measured_mm": round(float(np.median(w[on])), 3),
                                "coverage": round(min(1.0, cover), 2)}
    return out


def e2(folder, version, tmp, overlays):
    mire = json.load(open(os.path.join(ROOT, "print", f"mire_v{version}.json")))
    rows = []
    for i, p in enumerate(list_photos(folder)):
        t0 = time.time()
        img = load(p, tmp)
        res = measure_image(img, exclude_rects_mm=[tuple(r) for r in mire["exclude_rects_mm"]], keep_debug=True,
                            paper_rect_mm=MIRE_BOARD_RECT)
        q = res.quality
        rows.append({"photo": os.path.basename(p), "status": res.status, "bars": bar_widths(res, mire) if res.status == "ok" else {},
                     "blur_px": round(q.get("blur_sigma_px", float("nan")), 2), "card_px_per_mm": round(q.get("card_px_per_mm", float("nan")), 2),
                     "tilt_deg": round(q.get("tilt_deg_est", float("nan")), 1), "time_s": round(time.time() - t0, 1), "_res": res})
        if i < 3 and res.status == "ok":
            with open(os.path.join(overlays, f"mire_v{version}_{i + 1}.jpg"), "wb") as fh:
                fh.write(render_overlay(img, res))
    return mire, rows


def summarize_e2(mire, rows):
    lines = []
    ok = [r for r in rows if r["status"] == "ok"]
    lines.append(f"- Photos : {len(rows)} ; carte détectée et mesure faite : {len(ok)}")
    lines.append("")
    lines.append("| Trait | Largeur nominale (mm) | Détecté (photos) | Médiane mesurée (mm) | Erreur absolue moyenne (mm) | Biais (mm) |")
    lines.append("|---|---|---|---|---|---|")
    stats = {}
    for ln in mire["lines"]:
        m = [r["bars"][ln["label"]]["measured_mm"] for r in ok if ln["label"] in r["bars"]]
        e = np.array(m) - ln["width_mm"] if m else np.array([])
        stats[ln["label"]] = {"nominal": ln["width_mm"], "n": len(m), "of": len(ok),
                              "median": float(np.median(m)) if m else None,
                              "mae": float(np.mean(np.abs(e))) if m else None, "bias": float(np.mean(e)) if m else None}
        s = stats[ln["label"]]
        lines.append(f"| {ln['label']} | {ln['width_mm']:.2f} | {s['n']}/{s['of']} | {f(s['median'])} | {f(s['mae'])} | {f(s['bias'], '+.3f')} |")
    det = [s["nominal"] for s in stats.values() if s["of"] and s["n"] / s["of"] >= 0.8]
    allerr = [abs(r["bars"][k]["measured_mm"] - r["bars"][k]["nominal_mm"]) for r in ok for k in r["bars"]]
    lines.append("")
    if allerr:
        lines.append(f"- Erreur absolue moyenne, tous traits et toutes photos : **{np.mean(allerr):.3f} mm** (médiane {np.median(allerr):.3f} mm, {len(allerr)} mesures)")
    lines.append(f"- Plus petite largeur détectée sur au moins 80 % des photos : **{min(det):.2f} mm**" if det else "- Aucun trait détecté sur 80 % des photos.")
    lines.append("- Limite : la largeur imprimée réelle des traits n'a pas été contrôlée au scanner ; l'étalement de l'encre peut l'élargir de quelques centièmes de mm.")
    return lines, stats


def e4_real(rows1, rows2, mire1, mire2):
    """Bars measured on v1 photos vs v2 photos (different sheets, same layout = same board frame)."""
    lines = ["| Trait | v1 nominal | v2 nominal | Écart vrai (mm) | Écart mesuré, médiane (mm) | Rallongé de |", "|---|---|---|---|---|---|"]
    ok1 = [r for r in rows1 if r["status"] == "ok"]
    ok2 = [r for r in rows2 if r["status"] == "ok"]
    errs = []
    for l1, l2 in zip(mire1["lines"], mire2["lines"]):
        m1 = [r["bars"][l1["label"]]["measured_mm"] for r in ok1 if l1["label"] in r["bars"]]
        m2 = [r["bars"][l2["label"]]["measured_mm"] for r in ok2 if l2["label"] in r["bars"]]
        true = l2["width_mm"] - l1["width_mm"]
        meas = (np.median(m2) - np.median(m1)) if m1 and m2 else None
        if meas is not None:
            errs.append(abs(meas - true))
        ext = l2["y1_mm"] - l1["y1_mm"]
        lines.append(f"| {l1['label']} | {l1['width_mm']:.2f} | {l2['width_mm']:.2f} | {true:+.2f} | {f(meas, '+.3f')} | {ext:.0f} mm |")
    pair = []
    per_bar = {l1["label"]: {"true": l2["width_mm"] - l1["width_mm"], "tested": 0, "flagged": 0, "deltas": []}
               for l1, l2 in zip(mire1["lines"], mire2["lines"])}
    for a, b in zip(ok1, ok2):
        c = compare(a["_res"], b["_res"])
        if c.get("status") == "ok":
            pair.append({"v1": a["photo"], "v2": b["photo"], "mode": c["registration"]["mode"], "new_length_mm": c["new_length_mm"],
                         "widening_median_mm": c["width_delta_mm"]["median"], "significant_widening": c["significant_widening"],
                         "widening_mm": c.get("widening_mm"), "widening_location_board_mm": c.get("widening_location_board_mm"),
                         "significant_growth": c["significant_growth"], "windows": c.get("windows", [])})
            # which bar each ~10 mm stretch lies on; a bar counts as flagged if any of its stretches is
            for l1 in mire1["lines"]:
                ws = [w for w in c.get("windows", []) if abs(w["center_board_mm"][0] - l1["x_mm"]) < 3.25
                      and l1["y0_mm"] - 2 < w["center_board_mm"][1] < l1["y1_mm"] + 2]
                if ws:
                    pb = per_bar[l1["label"]]
                    pb["tested"] += 1
                    pb["flagged"] += any(w["significant"] for w in ws)
                    pb["deltas"].append(float(np.median([w["delta_mm"] for w in ws])))
    out = lines + [""]
    if errs:
        out.append(f"- Erreur absolue moyenne sur l'écart de largeur (par trait, médianes des photos) : **{np.mean(errs):.3f} mm**")
    if pair:
        out.append(f"- Comparaisons photo à photo v1→v2 : {len(pair)} ; élargissement significatif détecté : "
                   f"{sum(p['significant_widening'] for p in pair)}/{len(pair)} ; rallongement détecté (> 4 mm) : {sum(p['significant_growth'] for p in pair)}/{len(pair)}")
        out += ["", "Test par tronçon de ~10 mm (`change.py` : fissure entière + chaque tronçon, seuil de Bonferroni à 5 % "
                "par paire, changement >= 0,1 mm). Un trait compte comme « signalé » si l'un de ses tronçons l'est.", "",
                "| Trait | Écart vrai (mm) | Paires où le trait est comparé | Signalé élargi | Écart médian par paire (mm) |", "|---|---|---|---|---|"]
        for lab, pb in per_bar.items():
            dl = ", ".join(f"{d:+.2f}" for d in pb["deltas"]) or "—"
            out.append(f"| {lab} | {pb['true']:+.2f} | {pb['tested']} | {pb['flagged']} | {dl} |")
        ch = [pb for pb in per_bar.values() if pb["true"] > 0]
        un = [pb for pb in per_bar.values() if pb["true"] == 0]
        out += ["", f"- Traits élargis (vrai > 0) : signalés {sum(p['flagged'] for p in ch)}/{sum(p['tested'] for p in ch)} comparaisons ; "
                f"traits inchangés : signalés à tort {sum(p['flagged'] for p in un)}/{sum(p['tested'] for p in un)}"]
    return out, pair, errs


def _cv(v):
    v = [x for x in v if x is not None]
    return float(np.std(v, ddof=1) / np.mean(v)) if len(v) >= 3 and np.mean(v) > 0 else None


def e3(folder, tmp, overlays, scale_fix, cell_mm=10.0):
    """Repeatability on one real crack. Three per-photo widths, all defined identically for every photo:
    - `median_mm`: the longest detected crack (what the app reports first; framing-dependent);
    - `zone_median_mm`: all crack points in the monitoring zone (card sheet + 40 mm, card frame);
    - location-matched: the zone cut into 10 mm cells (card frame); per photo, the median over the cells
      that every measured photo sees, so each photo is scored on the same stretches of crack."""
    rows, cells = [], []
    for i, p in enumerate(list_photos(folder)):
        img = load(p, tmp)
        res = measure_image(img, keep_debug=True)
        act = decide_next_action(res.to_json(), AgentState("real"))
        c = res.cracks[0] if res.cracks else None
        z = res.zone or {}
        zw = z.get("width_mm") or {}
        rows.append({"photo": os.path.basename(p), "status": res.status, "decision": act.name, "reason": act.reason,
                     "median_mm": c and round(c["width_mm"]["median"] * scale_fix, 3), "max_mm": c and round(c["width_mm"]["max"] * scale_fix, 3),
                     "length_mm": c and round(c["length_mm"] * scale_fix, 1), "uncertainty_mm": c and c["uncertainty_mm"],
                     "px_per_mm": c and c["native_px_per_mm"], "blur_px": round(res.quality.get("blur_sigma_px", float("nan")), 2),
                     "zone_median_mm": zw.get("median") and round(zw["median"] * scale_fix, 3),
                     "zone_max_mm": zw.get("max") and round(zw["max"] * scale_fix, 3),
                     "zone_length_mm": z.get("length_mm"), "zone_searchable": z.get("searchable_fraction"),
                     "view_angle_across_deg": z.get("view_angle_across_deg")})
        pc = {}
        if res.status == "ok" and z.get("n_points"):
            Z = z["rect_board_mm"]
            for comp in res.debug["comps"]:
                P, W = comp["pts_mm"], comp["width_mm"]
                m = (P[:, 0] > Z[0]) & (P[:, 0] < Z[2]) & (P[:, 1] > Z[1]) & (P[:, 1] < Z[3])
                for key, w in zip(map(tuple, np.floor(P[m] / cell_mm).astype(int)), W[m]):
                    pc.setdefault(key, []).append(w)
        cells.append({k: float(np.median(v)) * scale_fix for k, v in pc.items() if len(v) * 1.08 / res.debug["rect"].R >= 3.0} if pc else {})
        if i < 2 and res.status == "ok":
            with open(os.path.join(overlays, f"{os.path.basename(folder)}_{i + 1}.jpg"), "wb") as fh:
                fh.write(render_overlay(img, res))
    ok = [r for r in rows if r["median_mm"] is not None and r["decision"] not in ("request_retake",)]
    oki = [i for i, r in enumerate(rows) if r in ok]
    common = set.intersection(*[set(cells[i]) for i in oki]) if oki else set()
    for i, r in enumerate(rows):
        r["matched_median_mm"] = round(float(np.median([cells[i][k] for k in common])), 3) if i in oki and common else None
    frontal = [r for r in ok if r["view_angle_across_deg"] is not None and r["view_angle_across_deg"] <= 10.0]
    summ = {"n": len(rows), "measured": len(ok),
            "median_mm": float(np.median([r["median_mm"] for r in ok])) if ok else None,
            "cv_median": _cv([r["median_mm"] for r in ok]), "cv_max": _cv([r["max_mm"] for r in ok]),
            "cv_zone_median": _cv([r["zone_median_mm"] for r in ok]), "cv_zone_max": _cv([r["zone_max_mm"] for r in ok]),
            "n_common_cells": len(common), "cv_matched": _cv([r["matched_median_mm"] for r in ok]),
            "n_frontal": len(frontal), "cv_zone_median_frontal": _cv([r["zone_median_mm"] for r in frontal]),
            "cv_matched_frontal": _cv([r["matched_median_mm"] for r in frontal]),
            "decisions": {d: sum(r["decision"] == d for r in rows) for d in sorted({r["decision"] for r in rows})}}
    return rows, summ


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", default="eval_real")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    overlays = os.path.join(a.out, "overlays")
    os.makedirs(overlays, exist_ok=True)
    scale_fix, ruler = 1.0, None
    rf = os.path.join(a.dir, "regle.txt")
    if os.path.exists(rf):
        try:
            ruler = float(open(rf).read().strip().replace(",", "."))
            scale_fix = ruler / 50.0          # printed card scaled by the printer: real mm = card mm x factor
        except ValueError:
            pass
    md = [f"# Résultats sur vraies photos", "", f"Généré par `scripts/process_real.py` le {time.strftime('%Y-%m-%d %H:%M')}, OpenCV {cv2.__version__}.", ""]
    if ruler:
        md.append(f"Règle de 50 mm de la carte imprimée mesurée à {ruler:.1f} mm : facteur d'échelle {scale_fix:.4f} appliqué aux vraies fissures (E3). "
                  "Les traits de la mire (E2/E4) n'en dépendent pas : carte et traits sont imprimés ensemble.")
    else:
        md.append("Pas de `regle.txt` : l'échelle d'impression n'est pas corrigée (à mesurer avec une vraie règle).")
    md.append("")
    results = {"ruler_mm": ruler, "scale_fix": scale_fix}
    with tempfile.TemporaryDirectory() as tmp:
        m1 = m2 = r1 = r2 = None
        for v in (1, 2):
            folder = os.path.join(a.dir, f"mire-v{v}")
            if list_photos(folder):
                mire, rows = e2(folder, v, tmp, overlays)
                lines, stats = summarize_e2(mire, rows)
                md += [f"## E2 — mire imprimée v{v}", ""] + lines + [""]
                results[f"e2_v{v}"] = {"stats": stats, "photos": [{k: x for k, x in r.items() if k != "_res"} for r in rows]}
                if v == 1:
                    m1, r1 = mire, rows
                else:
                    m2, r2 = mire, rows
        if r1 and r2:
            lines, pairs, errs = e4_real(r1, r2, m1, m2)
            md += ["## E4 réel — deux « visites » de la mire (v1 puis v2)", ""] + lines + [""]
            results["e4_real"] = {"pairs": pairs, "abs_errors_mm": errs}
        for folder in sorted(glob.glob(os.path.join(a.dir, "fissure-*"))):
            if not list_photos(folder):
                continue
            rows, summ = e3(folder, tmp, overlays, scale_fix)
            name = os.path.basename(folder)
            pct = lambda v: f(None if v is None else 100 * v, ".1f", " %")  # noqa: E731
            md += [f"## E3 — {name} (répétabilité, pas de vérité terrain)", "",
                   f"- Photos : {summ['n']} ; mesurées sans demande de reprise : {summ['measured']}",
                   f"- Largeur médiane (médiane des photos, fissure la plus longue) : {f(summ['median_mm'], '.3f', ' mm')}",
                   f"- Coefficient de variation entre photos :",
                   f"  - fissure la plus longue de chaque photo (ancien indicateur) : médiane {pct(summ['cv_median'])}, max {pct(summ['cv_max'])}",
                   f"  - zone de suivi (feuille de la carte + 40 mm, repère carte, même zone pour toutes les photos) : médiane {pct(summ['cv_zone_median'])}, max {pct(summ['cv_zone_max'])}",
                   f"  - mêmes tronçons (cases de 10 mm de la zone vues par toutes les photos : {summ['n_common_cells']}) : médiane {pct(summ['cv_matched'])}",
                   f"  - analyse, pas une règle de l'app : photos vues à <= 10° en travers de la fissure ({summ['n_frontal']}) : zone {pct(summ['cv_zone_median_frontal'])}, mêmes tronçons {pct(summ['cv_matched_frontal'])}",
                   f"- Décisions de l'agent (règles) : {', '.join(f'{k} {n}' for k, n in summ['decisions'].items())}", "",
                   "| Photo | Décision | Plus longue : médiane (mm) | Zone : médiane (mm) | Zone : max (mm) | Mêmes tronçons (mm) | Angle en travers (°) | Zone cherchable | px/mm | ± (mm) |",
                   "|---|---|---|---|---|---|---|---|---|---|"]
            for r in rows:
                md.append(f"| {r['photo']} | {r['decision']} | {r['median_mm']} | {r['zone_median_mm']} | {r['zone_max_mm']} | {r['matched_median_mm']} | "
                          f"{r['view_angle_across_deg']} | {r['zone_searchable']} | {r['px_per_mm']} | {r['uncertainty_mm']} |")
            md.append("")
            results[name] = {"summary": summ, "photos": rows}
    if len(md) < 12:
        md.append("Aucune photo trouvée. Voir `PHOTOS-PROPRIETAIRE.md` pour les noms de dossiers.")
    with open(os.path.join(a.out, "RESULTS.md"), "w") as fh:
        fh.write("\n".join(md) + "\n")
    with open(os.path.join(a.out, "real_results.json"), "w") as fh:
        json.dump(results, fh, indent=1, default=lambda o: None if isinstance(o, float) and math.isnan(o) else str(o))
    print("\n".join(md))


if __name__ == "__main__":
    main()

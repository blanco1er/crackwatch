"""Real photos with BOTH references (printed ChArUco card and a bank card) next to the same crack: the same photo
is measured twice, exactly as the service does it (decode_image -> 4032 px, EXIF focal read from the file).

  python scripts/eval_idcard_twocards.py --dir ../photos-reelles/v2-carte-a-cote --out eval_real_carte
Folders whose name contains "deux" are used (any .heic/.jpg). Writes <out>/RESULTS-deux-cartes.md (French) and
<out>/deux_cartes.json, plus overlays of the fitted card outline (card area blurred).
ChArUco is the reference: it was checked against the printed test chart and a ruler.
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
from crackwatch.exif import focal_35mm  # noqa: E402
from crackwatch.idcard import _paint_out, pose_from_homography, redact  # noqa: E402
from crackwatch.measure import apply_h, local_scale, measure_image  # noqa: E402
from crackwatch.service import decode_image, focal_px_from_35mm  # noqa: E402


def load_bytes(path, tmp):
    if path.lower().endswith((".heic", ".heif")):
        out = os.path.join(tmp, os.path.basename(path) + ".jpg")
        subprocess.run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "95", path, "--out", out], check=True,
                       capture_output=True)
        path = out
    return open(path, "rb").read()


def jac(H, p):
    e = 0.05
    q = apply_h(H, [p, (p[0] + e, p[1]), (p[0], p[1] + e)])
    return np.column_stack([(q[1] - q[0]) / e, (q[2] - q[0]) / e])


def one(path, tmp, odir):
    data = load_bytes(path, tmp)
    f35 = focal_35mm(data)
    img = decode_image(data)
    f_px = focal_px_from_35mm(f35, img.shape)
    r = {"photo": os.path.basename(path), "focal_35mm": f35}
    # each run hides the OTHER reference (its paper or the bank card + fingers) so that neither the checkerboard nor
    # the card's print is taken for cracks: the two runs then see the same wall
    ri = measure_image(img, keep_debug=True, reference="idcard", focal_px=f_px)
    rc0 = measure_image(img, keep_debug=True, reference="charuco")
    img_c = img
    if ri.card is not None:
        cd = ri.debug["card"]
        img_c = _paint_out(img, [cd.outline_img(6.0)])
    rc = measure_image(img_c, keep_debug=True, reference="charuco") if ri.card is not None else rc0
    if rc0.card is not None and ri.card is not None:
        ch0 = rc0.debug["card"]
        x0, y0, x1, y1 = ch0.spec.paper_rect_in_board_frame()
        img_i = _paint_out(img, [apply_h(ch0.H_img_from_board, [(x0 - 3, y0 - 3), (x1 + 3, y0 - 3), (x1 + 3, y1 + 3), (x0 - 3, y1 + 3)])])
        ri = measure_image(img_i, keep_debug=True, reference="idcard", focal_px=f_px)
    for name, res in (("charuco", rc), ("idcard", ri)):
        c = res.cracks[0] if res.cracks else None
        r[name] = {"status": res.status, "why": res.quality.get("retake_reason"), "detail": res.quality.get("retake_detail"),
                   "median": c and c["width_mm"]["median"], "max": c and c["width_mm"]["max"], "unc": c and c["uncertainty_mm"]}
    if rc.status == "ok" and ri.card is not None:
        ch, cd = rc.debug["card"], ri.debug["card"]
        # scale of the bank card vs ChArUco at the centre of the main crack (ChArUco board frame)
        bx = rc.cracks[0]["bbox_board_mm"]
        pc = ((bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2)
        x = apply_h(ch.H_img_from_board, [pc])[0]
        pi = apply_h(np.linalg.inv(cd.H_img_from_board), [x])[0]
        sv = np.linalg.svd(np.linalg.solve(jac(cd.H_img_from_board, pi), jac(ch.H_img_from_board, pc)), compute_uv=False)
        r["scale_err_crack_pct"] = [round(100 * float(sv.min() - 1), 2), round(100 * float(sv.max() - 1), 2)]
        r["scale_unc_crack_pct"] = round(100 * cd.scale_rel_unc_at(pi), 2)
        r["dist_card_crack_mm"] = round(float(np.linalg.norm(pi - (42.8, 27.0))), 1)
        # where the card is relative to the ChArUco plane (same camera model, EXIF focal)
        f = f_px or cd.focal_px
        Rc, tc, _ = pose_from_homography(ch.H_img_from_board, f, img.shape)
        Rd, td, _ = pose_from_homography(cd.H_img_from_card_face, f, img.shape)
        Xd = Rd @ np.array([42.8, 27.0, 0.0]) + td
        r["card_vs_charuco_plane_mm"] = round(float(Rc[:, 2] @ (Xd - tc)), 1)
        r["plane_angle_deg"] = round(math.degrees(math.acos(min(1.0, abs(float(Rc[:, 2] @ Rd[:, 2]))))), 1)
        xc = apply_h(cd.H_img_from_board, [(42.8, 27.0)])[0]
        pcc = apply_h(np.linalg.inv(ch.H_img_from_board), [xc])[0]
        r["ppm_at_card_pct"] = round(100 * (local_scale(cd.H_img_from_board, (42.8, 27.0)) / local_scale(ch.H_img_from_board, pcc) - 1), 2)
        v = redact(img, cd)
        cv2.polylines(v, [np.round(cd.outline_img()).astype(np.int32)], True, (0, 255, 0), 2)
        cv2.polylines(v, [np.round(apply_h(ch.H_img_from_board, [(0, 0), (75, 0), (75, 105), (0, 105)])).astype(np.int32)], True, (255, 0, 0), 2)
        s = 1000 / max(v.shape[:2])
        cv2.imwrite(os.path.join(odir, r["photo"].rsplit(".", 1)[0] + "_cartes.jpg"), cv2.resize(v, None, fx=s, fy=s))
    if rc.status == "ok" and ri.status == "ok":
        # widths at the SAME crack points: the two references rectify different windows of the photo (each around
        # its own card), so their "main crack" statistics cover different stretches; matched points do not
        T = np.linalg.inv(rc.debug["card"].H_img_from_board) @ ri.debug["card"].H_img_from_board
        P1 = np.vstack([c["pts_mm"] for c in rc.debug["comps"]])[::3]
        W1 = np.concatenate([c["width_mm"] for c in rc.debug["comps"]])[::3]
        P2 = apply_h(T, np.vstack([c["pts_mm"] for c in ri.debug["comps"]]))
        W2 = np.concatenate([c["width_mm"] for c in ri.debug["comps"]])
        j, dist = np.zeros(len(P2), int), np.full(len(P2), np.inf)
        for s0 in range(0, len(P2), 2048):
            d2 = ((P2[s0:s0 + 2048, None, :] - P1[None, :, :]) ** 2).sum(-1)
            j[s0:s0 + 2048] = d2.argmin(1)
            dist[s0:s0 + 2048] = np.sqrt(d2.min(1))
        m = dist < 1.0
        if m.sum() >= 20:
            rr = W2[m] / W1[j[m]]
            r["matched_points"] = int(m.sum())
            r["matched_ratio_pct"] = round(100 * (float(np.median(rr)) - 1), 2)
            u = r.get("scale_unc_crack_pct")
            if u:
                r["matched_within_2u"] = bool(abs(r["matched_ratio_pct"]) <= 2 * u)
    a, b = r["charuco"], r["idcard"]
    if a["median"] and b["median"]:
        d = b["median"] - a["median"]
        u = math.hypot(a["unc"] or 0, b["unc"] or 0)
        r["median_diff_mm"] = round(d, 3)
        r["median_ratio_pct"] = round(100 * (b["median"] / a["median"] - 1), 1)
        r["within_2u"] = bool(abs(d) <= 2 * u)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--out", default="eval_real_carte")
    a = ap.parse_args()
    odir = os.path.join(a.out, "overlays")
    os.makedirs(odir, exist_ok=True)
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        for d in sorted(glob.glob(os.path.join(a.dir, "*deux*"))):
            for p in sorted(glob.glob(os.path.join(d, "*"))):
                if p.lower().endswith((".heic", ".heif", ".jpg", ".jpeg")):
                    r = one(p, tmp, odir)
                    r["folder"] = os.path.basename(d)
                    rows.append(r)
                    print(json.dumps(r), flush=True)
    json.dump(rows, open(os.path.join(a.out, "deux_cartes.json"), "w"), indent=1)
    acc = [r for r in rows if r["idcard"]["status"] == "ok"]
    both = [r for r in rows if "median_ratio_pct" in r]
    md = ["# Carte bancaire et carte imprimée sur la même photo (vraies photos)", "",
          f"Généré par `scripts/eval_idcard_twocards.py` le {time.strftime('%Y-%m-%d %H:%M')} ; photos réduites à 4032 px "
          "comme le service ; focale lue dans l'EXIF. La carte imprimée (ChArUco) sert de référence.", "",
          f"- Photos : {len(rows)} ; carte bancaire acceptée : {len(acc)} ; fissure mesurée par les deux : {len(both)}",
          (f"- **Largeur aux mêmes points de la fissure**, carte / ChArUco : médiane "
           f"{np.median([r['matched_ratio_pct'] for r in rows if 'matched_ratio_pct' in r]):+.1f} %, de "
           f"{min(r['matched_ratio_pct'] for r in rows if 'matched_ratio_pct' in r):+.1f} à "
           f"{max(r['matched_ratio_pct'] for r in rows if 'matched_ratio_pct' in r):+.1f} % ; dans ±2 σ d'échelle annoncés : "
           f"{sum(bool(r.get('matched_within_2u')) for r in rows)}/{sum('matched_ratio_pct' in r for r in rows)}")
          if any("matched_ratio_pct" in r for r in rows) else "- —",
          "- La « fissure principale » de chaque mesure couvre une portion différente de la photo (fenêtre redressée autour "
          "de chaque carte) : sa médiane n'est pas comparable d'une référence à l'autre ; la ligne ci-dessus l'est.",
          (f"- Écart de largeur médiane carte / ChArUco : médiane {np.median([r['median_ratio_pct'] for r in both]):+.1f} % ; "
           f"dans ±2 incertitudes annoncées : {sum(r['within_2u'] for r in both)}/{len(both)}") if both else "- —", "",
          "| Dossier | Photo | ChArUco méd. / max (± mm) | Carte méd. / max (± mm) | écart méd. | mêmes points (%) | échelle à la fissure (%) | ± échelle annoncé (%) | carte devant le plan ChArUco (mm) | angle des plans (°) | statut carte |",
          "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        c, b = r["charuco"], r["idcard"]
        fmt = lambda x: f"{x['median']:.2f} / {x['max']:.2f} (± {x['unc']:.2f})" if x["median"] else x["status"]  # noqa: E731
        md.append(f"| {r['folder']} | {r['photo']} | {fmt(c)} | {fmt(b)} | {r.get('median_ratio_pct', '—')} % | {r.get('matched_ratio_pct', '—')} | "
                  f"{r.get('scale_err_crack_pct', '—')} | {r.get('scale_unc_crack_pct', '—')} | {r.get('card_vs_charuco_plane_mm', '—')} | "
                  f"{r.get('plane_angle_deg', '—')} | {b['status']}{' (' + b['why'] + ')' if b['why'] else ''} |")
    open(os.path.join(a.out, "RESULTS-deux-cartes.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()

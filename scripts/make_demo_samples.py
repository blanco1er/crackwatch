"""Synthetic sample photos for the hosted demo (one wall, one crack, four photos).

The hosted demo must be testable by judges who have no printed card and no cracked wall, so it
ships four *synthetic* photos of the same wall (ground truth known exactly):

  blurry   visit 1, first attempt: camera shake -> the agent must ask for a retake
  far      visit 1, second attempt: sharp but far away -> the crack is < 3 px wide -> closer photo
  close    visit 1, closer photo of the same crack -> measured
  visit2   three months later: the crack widened by 0.45 mm and grew by 12 mm -> compare -> ticket

The published samples (web/samples) put the synthetic crack on a real CC0 wall photo from Poly Haven
("Plastered Wall" by Amal Kumar, see crackwatch/assets/textures/ATTRIBUTION.md):

  python scripts/make_demo_samples.py --out web/samples --texture crackwatch/assets/textures/plastered_wall_diff_crop.jpg

Only the look changes with --texture (colour wall, soft light fall-off, vignette, shaded crack); the
crack polylines, the card pose, the four camera poses (seed 424246) and therefore the ground truth are
the same as without it, computed by the same synth._gt_cracks. The texture's fine pores are toned
down (--texture-detail) because isolated dark dots are not what the detector was tuned on; the
measurement thresholds are never touched. Output is deterministic (fixed seeds, OpenCV only).
Without --texture the original procedural grey concrete is rendered (crackwatch.synth, unchanged).

They are clearly labelled "synthetic" in the interface, with the true widths next to the measured ones.
"""
import argparse
import json
import math
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch import synth  # noqa: E402

SEED = 424246   # chosen among 424242-424247 as an illustrative case (see README: demo photos are a selected example)
W_BASE = 0.42


def crack_like(rng, start, theta, length_mm, w_base, step=0.25):
    """A crack-looking polyline: straight-ish overall path, jagged 2-6 mm facets, width varying along it."""
    pts, ang = [np.asarray(start, float)], theta
    seg_left, facet = 0.0, 0.0
    n = int(length_mm / step)
    for _ in range(n - 1):
        if seg_left <= 0:
            seg_left = rng.uniform(2.0, 6.0)
            facet = rng.uniform(-0.45, 0.45)
            ang = 0.85 * ang + 0.15 * theta + rng.normal(0, 0.05)
        d = ang + facet
        pts.append(pts[-1] + step * np.array([math.cos(d), math.sin(d)]))
        seg_left -= step
    pts = np.array(pts)
    s = np.arange(n) * step
    prof = 1.0 + 0.35 * synth.smooth_noise(rng, n, 12 / step)
    taper = np.minimum(1.0, 0.35 + 0.65 * np.minimum(s, s[-1] - s) / (0.2 * s[-1]))
    return pts, w_base * prof * taper


def make_cracks(start, theta, length, w_base, widen_mm=0.0, extend_mm=0.0):
    rng = np.random.default_rng(SEED + 77)
    p, w = crack_like(rng, start, theta, length, w_base)
    if widen_mm or extend_mm:
        w = w + widen_mm * np.clip(np.minimum(np.arange(len(w)), len(w) - 1 - np.arange(len(w))) / 40.0, 0.3, 1.0)
        if extend_mm:
            t = p[-1] - p[-12]
            ep, _ = crack_like(np.random.default_rng(SEED + 99), p[-1], math.atan2(t[1], t[0]), extend_mm + 0.25, 1.0)
            p = np.vstack([p, ep[1:]])
            w = np.concatenate([w, w[-1] * np.linspace(1.0, 0.4, len(ep))[1:]])
    return [{"pts_wall": p, "widths": w, "branch": False}]


def inside_wall(Hw, margin=15.0):
    c = synth.apply_h(np.linalg.inv(Hw), [(0, 0), (synth.IMG_W, 0), (synth.IMG_W, synth.IMG_H), (0, synth.IMG_H)])
    x0, y0, x1, y1 = synth.WALL_REGION
    return bool((c[:, 0] > x0 + margin).all() and (c[:, 0] < x1 - margin).all()
                and (c[:, 1] > y0 + margin).all() and (c[:, 1] < y1 - margin).all())


def pick_camera(rng, sp, cracks, ppm, tilt_range=(5, 25)):
    cpts = np.vstack([c["pts_wall"] for c in cracks])
    card_c = synth.apply_h(synth.board_to_wall(sp.card_pose), [(37.5, 52.5)])[0]
    best = None
    for _ in range(400):
        a = rng.uniform(0.45, 0.7)
        look = tuple(card_c * (1 - a) + cpts.mean(0) * a + rng.normal(0, 5, 2))
        cam = dict(ppm=ppm, tilt_deg=float(rng.uniform(*tilt_range)), azimuth_deg=float(rng.uniform(0, 360)),
                   roll_deg=float(rng.uniform(-8, 8)), look_at=look)
        Hw, _ = synth.camera_homography(look, ppm, cam["tilt_deg"], cam["azimuth_deg"], cam["roll_deg"])
        ip = synth.apply_h(Hw, cpts)
        vis = ((ip[:, 0] > 40) & (ip[:, 0] < synth.IMG_W - 40) & (ip[:, 1] > 40) & (ip[:, 1] < synth.IMG_H - 40)).mean()
        nc = synth.card_visibility(Hw, sp.card_pose)
        if not inside_wall(Hw):
            continue
        score = vis + nc / 24.0
        if vis > 0.9 and nc >= 14 and (best is None or score > best[0]):
            best = (score, cam)
    return best[1] if best else None


def render(sp, wall, cracks, cam, seed, extra_blur=0.0, motion_px=0):
    rng = np.random.default_rng(seed)
    lin, Hw = synth.render_view(wall, sp, cracks, sp.card_pose, cam, rng)
    if extra_blur:
        lin = cv2.GaussianBlur(lin, (0, 0), extra_blur)
    if motion_px:
        k = np.zeros((motion_px, motion_px), np.float32)
        k[motion_px // 2, :] = 1.0 / motion_px
        lin = cv2.filter2D(lin, -1, k)
    # mild, fixed degradations (the random ones of synth.degrade are for the benchmark)
    img = cv2.GaussianBlur(lin, (0, 0), 0.7)
    img = img + rng.normal(0, 0.008, img.shape).astype(np.float32)
    img = np.clip(img, 0, 1) ** (1 / 1.1)
    bgr = np.clip(img[..., None] * np.array([0.97, 1.0, 1.02], np.float32) * 255 + 0.5, 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 88])
    gt = synth._gt_cracks(cracks, sp.card_pose, Hw)
    return buf, gt


# ------------------------------------------------------------------ photographic wall (--texture)
# Same scene, same cameras, same crack polygons as above; only the look changes: the procedural
# grey concrete is replaced by a real CC0 wall photo (colour), the crack is a dark gap with a soft
# shadowed rim, the light falls off across the wall and the lens vignettes. Ground truth is computed
# by the same synth._gt_cracks from the same polylines and homographies, so it stays exact.
# Intensities stay in the same near-linear domain as render() (output gamma 1.1, crack depth
# sp.crack_depth): the measurement's blur/width model sees the crack exactly as on the grey wall.
LAMP_MM = (-320.0, -300.0)      # broad soft light up-left of the card (wall mm)
LAMP_SIGMA_MM = 520.0
CRACK_CORE_TINT = np.array([0.88, 0.96, 1.0], np.float32)   # BGR: shadow inside the gap reads slightly warm
CRACK_RIM = 0.06                # extra darkening of the rim (dust, chipped paint edge)
CRACK_RIM_MM = 0.15             # rim softness (Gaussian sigma)


def load_texture(path, px_per_mm, smooth_mm=1.5, contrast=3.0, detail=0.5, tint=(1.0, 1.08, 1.15), mid=None, broad_mm=8.0):
    """CC0 wall photo (JPEG) -> float32 BGR 0..1 ready to render.

    Works on luminance so the paint colour is kept, in three bands: the broad relief (coarser than
    `broad_mm`, which the detector's 12 mm background median absorbs) is scaled by `contrast`, the
    mid relief (`smooth_mm`..`broad_mm`) by `mid`, the fine grain (pores, specks) by `detail`. Real paint pores are isolated dark
    dots that the ridge detector's relative thresholds (median + k MAD) were not tuned on, so they are
    toned down rather than the thresholds touched. Hue variation is kept, softened."""
    bgr = cv2.imread(path, cv2.IMREAD_COLOR)
    if bgr is None:
        raise SystemExit(f"cannot read texture {path}")
    lin = bgr.astype(np.float32) / 255.0
    L = lin.mean(2)
    s = max(0.5, smooth_mm * px_per_mm)
    low = cv2.GaussianBlur(L, (0, 0), s)
    Lm = float(L.mean())
    broad = cv2.GaussianBlur(L, (0, 0), broad_mm * px_per_mm)
    mid = contrast if mid is None else mid
    Lnew = Lm + contrast * (broad - Lm) + mid * (low - broad) + detail * (L - low)
    chroma = cv2.GaussianBlur(lin / np.maximum(L, 1e-3)[..., None], (0, 0), s)
    cm = chroma.reshape(-1, 3).mean(0)
    chroma = cm + 0.5 * (chroma - cm)
    return np.clip(Lnew[..., None] * chroma * np.asarray(tint, np.float32), 0, 1)


def texture_meta(path):
    """Provenance sidecar <texture>.json (id, name, authors, url, license, sha256 ...)."""
    side = os.path.splitext(path)[0] + ".json"
    if not os.path.exists(side):
        raise SystemExit(f"missing provenance file {side}")
    with open(side) as f:
        return json.load(f)


def render_textured(sp, tex, tex_frame, cracks, cam, seed, extra_blur=0.0, motion_px=0, exposure=1.0, noise=0.008,
                    spec=synth.CARD_A6):
    """Photographic version of render(): colour wall texture, shaded crack, lit card, vignette."""
    rng = np.random.default_rng(seed)
    H_wall, _ = synth.camera_homography(cam["look_at"], cam["ppm"], cam["tilt_deg"], cam["azimuth_deg"], cam["roll_deg"])
    Hinv = np.linalg.inv(H_wall)
    # raster exactly as synth.render_view (same bounds, same P)
    corners = synth.apply_h(Hinv, [(0, 0), (synth.IMG_W, 0), (synth.IMG_W, synth.IMG_H), (0, synth.IMG_H)])
    x0, y0 = corners.min(0) - 5
    x1, y1 = corners.max(0) + 5
    x0, y0 = max(x0, synth.WALL_REGION[0]), max(y0, synth.WALL_REGION[1])
    x1, y1 = min(x1, synth.WALL_REGION[2]), min(y1, synth.WALL_REGION[3])
    ppm_max = max(synth.local_ppm(H_wall, c) for c in synth.apply_h(Hinv, [(0, 0), (synth.IMG_W, 0), (synth.IMG_W, synth.IMG_H),
                                                                            (0, synth.IMG_H), (synth.IMG_W / 2, synth.IMG_H / 2)]))
    P = float(np.clip(round(2.0 * ppm_max), 6, 22))
    h, w = int((y1 - y0) * P) + 1, int((x1 - x0) * P) + 1
    # wall: texture pixel (i, j) centre is at wall mm (tx0 + (i + 0.5) / tp, ty0 + (j + 0.5) / tp)
    tx0, ty0, tp = tex_frame
    A = np.array([[tp / P, 0, (x0 - tx0) * tp + 0.5 * tp / P - 0.5],
                  [0, tp / P, (y0 - ty0) * tp + 0.5 * tp / P - 0.5]], np.float64)
    img = cv2.warpAffine(tex, A, (w, h), flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REFLECT)
    img = np.clip(img, 0, 1)
    # crack: exact coverage of the same polygons (synth.render_cracks with depth 0 -> 1 - coverage)
    keep = np.ones((h, w), np.float32)
    synth.render_cracks(keep, cracks, (x0, y0), P, 0.0)
    cov = 1.0 - keep
    rim = cv2.GaussianBlur(cov, (0, 0), CRACK_RIM_MM * P)
    rim = np.clip(rim * 2.0, 0, 1) * keep
    img *= (1.0 - CRACK_RIM * rim)[..., None]
    core = 1.0 - cov[..., None] * (1.0 - sp.crack_depth * CRACK_CORE_TINT)
    img *= core
    # card: same warp as synth.paste_card, recovered as (page * mask, mask), then a faint contact shadow
    a = np.zeros((h, w), np.float32)
    synth.paste_card(a, spec, sp.card_pose, (x0, y0), P)          # a = page * mask
    b = np.ones((h, w), np.float32)
    synth.paste_card(b, spec, sp.card_pose, (x0, y0), P)          # b = 1 - mask + page * mask
    mask = np.clip(1.0 - b + a, 0, 1)
    page = np.where(mask > 1e-3, a / np.maximum(mask, 1e-3), 0)
    sh = cv2.GaussianBlur(np.roll(mask, (int(round(0.8 * P)), int(round(0.5 * P))), (0, 1)), (0, 0), 0.9 * P)
    img *= (1.0 - 0.18 * sh * (1.0 - mask))[..., None]
    paper = np.clip(page, 0, 1)[..., None] * np.array([0.96, 0.99, 1.0], np.float32)
    img = img * (1.0 - mask[..., None]) + paper * mask[..., None]
    # light falls off across the wall (fixed in wall space: same lamp for every photo)
    xs = x0 + (np.arange(w, dtype=np.float32) + 0.5) / P
    ys = y0 + (np.arange(h, dtype=np.float32) + 0.5) / P
    d2 = (xs[None, :] - LAMP_MM[0]) ** 2 + (ys[:, None] - LAMP_MM[1]) ** 2
    img *= (0.62 + 0.55 * np.exp(-d2 / (2 * LAMP_SIGMA_MM ** 2)))[..., None]
    # camera
    img = cv2.GaussianBlur(img, (0, 0), 0.35 * P / cam["ppm"])
    S = np.array([[1 / P, 0, x0 + 0.5 / P], [0, 1 / P, y0 + 0.5 / P], [0, 0, 1]])
    lin = cv2.warpPerspective(img, H_wall @ S, (synth.IMG_W, synth.IMG_H), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REFLECT)
    yy, xx = np.mgrid[0:synth.IMG_H, 0:synth.IMG_W].astype(np.float32)
    r2 = ((xx - synth.IMG_W / 2) / synth.IMG_W) ** 2 + ((yy - synth.IMG_H / 2) / synth.IMG_W) ** 2
    lin *= (exposure * (1.0 - 0.55 * r2))[..., None]
    if extra_blur:
        lin = cv2.GaussianBlur(lin, (0, 0), extra_blur)
    if motion_px:
        k = np.zeros((motion_px, motion_px), np.float32)
        k[motion_px // 2, :] = 1.0 / motion_px
        lin = cv2.filter2D(lin, -1, k)
    img = cv2.GaussianBlur(lin, (0, 0), 0.7)
    img = np.clip(img, 0, 1) ** (1 / 1.1)
    img = img + rng.normal(0, noise, img.shape[:2]).astype(np.float32)[..., None] \
              + rng.normal(0, noise / 2, img.shape).astype(np.float32)      # luma + a little chroma noise
    bgr = np.clip(img * 255 + 0.5, 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 86])
    gt = synth._gt_cracks(cracks, sp.card_pose, H_wall)
    return buf, gt


def seed_all(seed):
    global SEED
    SEED = seed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="web/samples")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--texture", help="CC0 wall photo (with a provenance sidecar <texture>.json); default: procedural concrete")
    ap.add_argument("--texture-ppm", type=float, default=6.0, help="texture pixels per wall mm")
    ap.add_argument("--texture-smooth-mm", type=float, default=1.5, help="scale separating broad relief from fine grain")
    ap.add_argument("--texture-contrast", type=float, default=2.5, help="gain on the broad relief (luminance)")
    ap.add_argument("--texture-detail", type=float, default=0.35, help="gain on the fine grain (luminance)")
    ap.add_argument("--tint", type=float, nargs=3, default=(1.0, 1.08, 1.15), metavar=("B", "G", "R"),
                    help="paint colour gain (default: warm cream)")
    ap.add_argument("--exposure", type=float, default=1.0)
    a = ap.parse_args()
    seed_all(a.seed)
    os.makedirs(a.out, exist_ok=True)
    rng = np.random.default_rng(SEED)
    sp = synth.sample_scene(rng, SEED, W_BASE)
    sp.branch = False
    sp.length_mm = 70.0
    sp.crack_theta = math.radians(-12)
    sp.card_pose = (0.0, 0.0, math.radians(2))
    wall = synth.make_wall(rng, SEED, distractors=False)
    start, theta = (102.0, 70.0), math.radians(-18)
    v1 = make_cracks(start, theta, 70.0, W_BASE)
    v2 = make_cracks(start, theta, 70.0, W_BASE, widen_mm=0.45, extend_mm=12.0)
    crng = np.random.default_rng(SEED + 1)
    shots = {
        "blurry": (v1, pick_camera(crng, sp, v1, 6.5), dict(extra_blur=3.2, motion_px=7)),
        "far": (v1, pick_camera(crng, sp, v1, 3.8), {}),
        "close": (v1, pick_camera(crng, sp, v1, 9.0), {}),
        "visit2": (v2, pick_camera(crng, sp, v2, 9.0), {}),
    }
    meta = {"generator": "crackwatch.synth (procedural concrete, exact ground truth)", "seed": SEED, "samples": {}}
    tex = None
    if a.texture:
        tex = load_texture(a.texture, a.texture_ppm, a.texture_smooth_mm, a.texture_contrast, a.texture_detail, a.tint)
        th, tw = tex.shape[:2]
        cx, cy = 111.0, 84.0     # centre of the four camera footprints on the wall (mm)
        tex_frame = (cx - tw / (2 * a.texture_ppm), cy - th / (2 * a.texture_ppm), a.texture_ppm)
        tm = texture_meta(a.texture)
        meta["generator"] = "crackwatch synthetic crack on a CC0 Poly Haven wall texture, exact ground truth"
        meta["texture"] = {k: tm[k] for k in ("id", "name", "authors", "url", "license")}
        meta["render"] = {"texture_file": os.path.basename(a.texture), "texture_px_per_mm": a.texture_ppm,
                          "texture_smooth_mm": a.texture_smooth_mm,
                          "texture_contrast": a.texture_contrast, "texture_detail": a.texture_detail,
                          "tint_bgr": list(a.tint), "exposure": a.exposure}
    for i, (name, (cracks, cam, kw)) in enumerate(shots.items()):
        assert cam is not None, name
        if tex is None:
            buf, gt = render(sp, wall, cracks, cam, SEED + 10 + i, **kw)
        else:
            buf, gt = render_textured(sp, tex, tex_frame, cracks, cam, SEED + 10 + i, exposure=a.exposure, **kw)
        with open(os.path.join(a.out, name + ".jpg"), "wb") as f:
            f.write(buf.tobytes())
        w = np.concatenate([np.array(c["width_mm"])[np.array(c["visible"], bool)] for c in gt])
        meta["samples"][name] = {"image": name + ".jpg", "camera_px_per_mm": round(cam["ppm"], 2),
                                 "tilt_deg": round(cam["tilt_deg"], 1),
                                 "true_width_mm": {"median": round(float(np.median(w)), 3), "max": round(float(w.max()), 3)},
                                 "true_length_mm": round(float(sum(np.linalg.norm(np.diff(np.array(c["pts_board_mm"]), axis=0), axis=1).sum() for c in gt)), 1)}
        print(name, meta["samples"][name])
    prev = os.path.join(a.out, "samples.json")
    if os.path.exists(prev):          # keep the hand-prepared real photo entry (real.jpg is not generated here)
        with open(prev) as f:
            old = json.load(f).get("samples", {})
        if "real" in old:
            meta["samples"]["real"] = old["real"]
    with open(os.path.join(a.out, "samples.json"), "w") as f:
        json.dump(meta, f, indent=1)


if __name__ == "__main__":
    main()

"""Synthetic sample photos for the hosted demo (one wall, one crack, four photos).

The hosted demo must be testable by judges who have no printed card and no cracked wall, so it
ships four *synthetic* photos of the same procedural wall (ground truth known exactly):

  blurry   visit 1, first attempt: camera shake -> the agent must ask for a retake
  far      visit 1, second attempt: sharp but far away -> the crack is < 3 px wide -> closer photo
  close    visit 1, closer photo of the same crack -> measured
  visit2   three months later: the crack widened by 0.45 mm and grew by 12 mm -> compare -> ticket

usage: python scripts/make_demo_samples.py --out web/samples
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


def seed_all(seed):
    global SEED
    SEED = seed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="web/samples")
    ap.add_argument("--seed", type=int, default=SEED)
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
    for i, (name, (cracks, cam, kw)) in enumerate(shots.items()):
        assert cam is not None, name
        buf, gt = render(sp, wall, cracks, cam, SEED + 10 + i, **kw)
        with open(os.path.join(a.out, name + ".jpg"), "wb") as f:
            f.write(buf.tobytes())
        w = np.concatenate([np.array(c["width_mm"])[np.array(c["visible"], bool)] for c in gt])
        meta["samples"][name] = {"image": name + ".jpg", "camera_px_per_mm": round(cam["ppm"], 2),
                                 "tilt_deg": round(cam["tilt_deg"], 1),
                                 "true_width_mm": {"median": round(float(np.median(w)), 3), "max": round(float(w.max()), 3)},
                                 "true_length_mm": round(float(sum(np.linalg.norm(np.diff(np.array(c["pts_board_mm"]), axis=0), axis=1).sum() for c in gt)), 1)}
        print(name, meta["samples"][name])
    with open(os.path.join(a.out, "samples.json"), "w") as f:
        json.dump(meta, f, indent=1)


if __name__ == "__main__":
    main()

"""E1/E4 synthetic generator: crack-like curves of known width on a procedural concrete
wall, next to a ChArUco card, seen by a virtual pinhole camera with perspective, blur,
lighting changes, noise and JPEG compression. Every quantity is defined in wall
millimetres, so the ground truth is exact.

Frames: "wall" (mm, fixed to the wall), "board" (mm, ChArUco board frame, see card.py),
"raster" (wall rendered at P px/mm), "image" (camera pixels).
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass

import cv2
import numpy as np

from .card import CARD_A6, CardSpec, render_card_page

IMG_W, IMG_H = 1600, 1200
FOCAL_PX = 1400.0
WALL_REGION = (-250.0, -250.0, 450.0, 400.0)   # x0, y0, x1, y1 (mm): texture domain


# ------------------------------------------------------------------ geometry helpers
def rot2(theta):
    c, s = math.cos(theta), math.sin(theta)
    return np.array([[c, -s], [s, c]])


def board_to_wall(card_pose):
    """3x3 affine (board mm -> wall mm) from pose (tx, ty, theta)."""
    tx, ty, th = card_pose
    A = np.eye(3)
    A[:2, :2] = rot2(th)
    A[:2, 2] = (tx, ty)
    return A


def apply_h(H, pts):
    pts = np.asarray(pts, np.float64).reshape(-1, 2)
    p = np.hstack([pts, np.ones((len(pts), 1))]) @ H.T
    return p[:, :2] / p[:, 2:3]


def rot_x(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def camera_homography(look_at_mm, ppm, tilt_deg, azimuth_deg, roll_deg):
    """Homography wall-mm -> image px for a camera looking at `look_at_mm` on the wall
    plane z=0 with the given tilt (angle between optical axis and wall normal)."""
    K = np.array([[FOCAL_PX, 0, IMG_W / 2 - 0.5], [0, FOCAL_PX, IMG_H / 2 - 0.5], [0, 0, 1]])
    az, tl, rl = map(math.radians, (azimuth_deg, tilt_deg, roll_deg))
    R_tilt = rot_z(az) @ rot_x(tl) @ rot_z(-az) @ rot_z(rl)   # camera->world
    Z = FOCAL_PX / ppm
    d = R_tilt[:, 2]
    P0 = np.array([look_at_mm[0], look_at_mm[1], 0.0])
    C = P0 - Z * d
    R = R_tilt.T                                                 # world->camera
    t = -R @ C
    H = K @ np.column_stack([R[:, 0], R[:, 1], t])
    return H / H[2, 2], C


def local_ppm(H, pt_mm):
    """Image pixels per wall mm at a point (sqrt of the Jacobian determinant)."""
    x, y = pt_mm
    e = 0.5
    p = apply_h(H, [(x, y), (x + e, y), (x, y + e)])
    J = np.column_stack([(p[1] - p[0]) / e, (p[2] - p[0]) / e])
    return math.sqrt(abs(np.linalg.det(J)))


# ------------------------------------------------------------------ wall description
@dataclass
class Wall:
    seed: int
    base: float
    octaves: list          # (scale_mm, amplitude, grid ndarray)
    pores: np.ndarray      # (n, 4): x, y, radius_mm, depth
    speckles: np.ndarray   # (n, 5): x, y, rx, ry, contrast
    joint: tuple | None    # (x0, y0, x1, y1, width_mm, depth)
    stain: tuple | None    # (x, y, r_mm, depth)


def make_wall(rng: np.random.Generator, seed: int, distractors=True) -> Wall:
    x0, y0, x1, y1 = WALL_REGION
    octaves = []
    for scale, amp in ((60, 0.10), (20, 0.06), (6, 0.05), (2, 0.04), (0.7, 0.035)):
        amp *= rng.uniform(0.6, 1.4)
        nx, ny = int((x1 - x0) / scale) + 3, int((y1 - y0) / scale) + 3
        octaves.append((scale, amp, rng.normal(size=(ny, nx)).astype(np.float32)))
    area_cm2 = (x1 - x0) * (y1 - y0) / 100.0
    n_pores = int(area_cm2 * rng.uniform(0.05, 0.5))
    pores = np.column_stack([rng.uniform(x0, x1, n_pores), rng.uniform(y0, y1, n_pores),
                             rng.lognormal(math.log(0.35), 0.5, n_pores).clip(0.12, 2.0),
                             rng.uniform(0.15, 0.6, n_pores)])
    n_sp = int(area_cm2 * rng.uniform(0.3, 1.2))
    speckles = np.column_stack([rng.uniform(x0, x1, n_sp), rng.uniform(y0, y1, n_sp),
                                rng.uniform(0.5, 4, n_sp), rng.uniform(0.5, 4, n_sp),
                                rng.normal(0, 0.06, n_sp)])
    joint = stain = None
    if distractors and rng.random() < 0.12:
        y = rng.uniform(-40, 140)
        joint = (x0, y, x1, y + rng.uniform(-15, 15), rng.uniform(3, 8), rng.uniform(0.2, 0.45))
    if distractors and rng.random() < 0.15:
        stain = (rng.uniform(80, 220), rng.uniform(0, 120), rng.uniform(10, 30), rng.uniform(0.1, 0.3))
    return Wall(seed, rng.uniform(0.45, 0.72), octaves, pores, speckles, joint, stain)


def render_wall(wall: Wall, raster_origin, P, shape, rng) -> np.ndarray:
    """Render the wall texture (float32, ~0..1) for raster pixels; pixel (u,v) centre is
    at wall mm (ox + (u+0.5)/P, oy + (v+0.5)/P)."""
    ox, oy = raster_origin
    h, w = shape
    x0, y0, _, _ = WALL_REGION
    img = np.full((h, w), wall.base, np.float32)
    for scale, amp, grid in wall.octaves:
        # raster px -> grid index: g = (wall - x0)/scale
        A = np.array([[1.0 / (P * scale), 0, (ox + 0.5 / P - x0) / scale],
                      [0, 1.0 / (P * scale), (oy + 0.5 / P - y0) / scale]], np.float64)
        layer = cv2.warpAffine(grid, A, (w, h), flags=cv2.INTER_CUBIC | cv2.WARP_INVERSE_MAP,
                               borderMode=cv2.BORDER_REFLECT)
        img += amp * layer
    sh = 4  # subpixel shift bits for drawing
    f = P * (1 << sh)

    def to_r(x, y):
        return int(round((x - ox) * f - 0.5 * (1 << sh))), int(round((y - oy) * f - 0.5 * (1 << sh)))

    inside = lambda x, y, r: (ox - r <= x <= ox + w / P + r) and (oy - r <= y <= oy + h / P + r)
    layer = np.zeros((h, w), np.float32)
    for x, y, rx, ry, c in wall.speckles:
        if inside(x, y, max(rx, ry)):
            cv2.ellipse(layer, to_r(x, y), (int(rx * f), int(ry * f)), float((x * 37) % 180), 0, 360,
                        float(c), -1, cv2.LINE_AA, sh)
    img += cv2.GaussianBlur(layer, (0, 0), 0.4 * P)
    layer[:] = 0
    for x, y, r, d in wall.pores:
        if inside(x, y, r):
            cv2.circle(layer, to_r(x, y), max(1, int(r * f)), float(d), -1, cv2.LINE_AA, sh)
    img *= 1.0 - cv2.GaussianBlur(layer, (0, 0), 0.15 * P)
    if wall.stain is not None:
        sx, sy, r, d = wall.stain
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        dist2 = ((xx + 0.5) / P + ox - sx) ** 2 + ((yy + 0.5) / P + oy - sy) ** 2
        img *= 1.0 - d * np.exp(-dist2 / (2 * r * r))
    if wall.joint is not None:
        jx0, jy0, jx1, jy1, jw, jd = wall.joint
        m = np.zeros((h, w), np.float32)
        cv2.line(m, to_r(jx0, jy0), to_r(jx1, jy1), 1.0, max(1, int(jw * P)), cv2.LINE_AA, sh)
        img *= 1.0 - jd * cv2.GaussianBlur(m, (0, 0), 0.3 * P)
    img += rng.normal(0, 0.012, img.shape).astype(np.float32)   # fine grain
    return img


# ------------------------------------------------------------------ cracks
def smooth_noise(rng, n, corr):
    """Zero-mean noise in [-1, 1] with correlation length `corr` samples."""
    k = max(3, int(corr) | 1)
    x = rng.normal(size=n + 2 * k)
    x = np.convolve(x, np.hanning(k), mode="same")[k:k + n]
    return x / (np.abs(x).max() + 1e-9)


def make_crack_polyline(rng, start, theta, length_mm, w_base, step=0.25):
    n = int(length_mm / step)
    s = np.arange(n) * step
    curv_max = 0.4 / max(w_base * 1.4, 1.0)                     # keep radius >> width
    dtheta = smooth_noise(rng, n, 8 / step) * rng.uniform(0.01, 0.03) * step * 20
    dtheta += smooth_noise(rng, n, 2 / step) * 0.15 * step
    dtheta = np.clip(dtheta, -curv_max * step, curv_max * step)
    th = theta + np.cumsum(dtheta)
    pts = np.column_stack([np.cos(th), np.sin(th)]) * step
    pts = np.vstack([[0, 0], np.cumsum(pts, axis=0)[:-1]]) + np.asarray(start)
    prof = 1.0 + 0.3 * smooth_noise(rng, n, 10 / step)
    taper = np.minimum(1.0, 0.5 + 0.5 * np.minimum(s, s[-1] - s) / (0.12 * s[-1]))
    widths = w_base * prof * taper
    return pts, widths


def crack_polygon(pts, widths):
    t = np.gradient(pts, axis=0)
    t /= np.linalg.norm(t, axis=1, keepdims=True) + 1e-12
    nrm = np.column_stack([-t[:, 1], t[:, 0]])
    left = pts + nrm * widths[:, None] / 2
    right = pts - nrm * widths[:, None] / 2
    return np.vstack([left, right[::-1]])


def render_cracks(img, cracks, raster_origin, P, depth):
    """Darken `img` in place with exact-coverage crack polygons (4x supersampled)."""
    ox, oy = raster_origin
    h, w = img.shape
    SS = 4
    for c in cracks:
        poly = crack_polygon(c["pts_wall"], c["widths"])
        u = (poly[:, 0] - ox) * P - 0.5
        v = (poly[:, 1] - oy) * P - 0.5
        bx0, by0 = max(0, int(u.min()) - 3), max(0, int(v.min()) - 3)
        bx1, by1 = min(w, int(u.max()) + 4), min(h, int(v.max()) + 4)
        if bx1 <= bx0 or by1 <= by0:
            continue
        hs, ws = (by1 - by0) * SS, (bx1 - bx0) * SS
        m = np.zeros((hs, ws), np.uint8)
        q = np.column_stack([(u - bx0 + 0.5) * SS - 0.5, (v - by0 + 0.5) * SS - 0.5])
        cv2.fillPoly(m, [np.round(q * 16).astype(np.int32)], 255, cv2.LINE_8, 4)
        cov = cv2.resize(m.astype(np.float32) / 255.0, (bx1 - bx0, by1 - by0), interpolation=cv2.INTER_AREA)
        img[by0:by1, bx0:bx1] *= 1.0 - cov * (1.0 - depth)


# ------------------------------------------------------------------ card
def paste_card(img, spec: CardSpec, card_pose, raster_origin, P):
    page = render_card_page(spec, ppm=P).astype(np.float32) / 255.0
    page = 0.07 + 0.85 * page                                   # ink is not black, paper not white
    ox, oy = raster_origin
    bx, by = spec.board_offset_mm
    # page px -> page mm -> board mm -> wall mm -> raster px
    S1 = np.array([[1 / P, 0, 0.5 / P - bx], [0, 1 / P, 0.5 / P - by], [0, 0, 1]])
    S2 = np.array([[P, 0, -ox * P - 0.5], [0, P, -oy * P - 0.5], [0, 0, 1]])
    A = (S2 @ board_to_wall(card_pose) @ S1)[:2]
    h, w = img.shape
    warped = cv2.warpAffine(page, A, (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
    mask = cv2.warpAffine(np.ones_like(page), A, (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
    img *= 1.0 - mask
    img += warped * mask


# ------------------------------------------------------------------ scene + camera
@dataclass
class SceneParams:
    seed: int
    w_base: float
    length_mm: float
    branch: bool
    card_pose: tuple
    crack_start: tuple
    crack_theta: float
    crack_depth: float


def sample_scene(rng, seed, w_base=None) -> SceneParams:
    if w_base is None:
        w_base = float(math.exp(rng.uniform(math.log(0.2), math.log(4.0))))
    th = rng.uniform(-math.pi / 2.5, math.pi / 2.5)
    start = (rng.uniform(100, 120), rng.uniform(10, 95))
    depth = rng.uniform(0.18, 0.5)
    return SceneParams(seed, w_base, rng.uniform(40, 85), bool(rng.random() < 0.3),
                       (rng.uniform(-3, 3), rng.uniform(-3, 3), math.radians(rng.uniform(-6, 6))),
                       start, th, depth)


def build_cracks(sp: SceneParams, widen_mm=0.0, extend_mm=0.0):
    rng = np.random.default_rng(sp.seed * 7 + 1)
    pts, widths = make_crack_polyline(rng, sp.crack_start, sp.crack_theta, sp.length_mm, sp.w_base)
    cracks = [{"pts_wall": pts, "widths": widths, "branch": False}]
    if sp.branch:
        i = int(len(pts) * rng.uniform(0.35, 0.65))
        t = pts[min(i + 1, len(pts) - 1)] - pts[i]
        th = math.atan2(t[1], t[0]) + rng.choice([-1, 1]) * rng.uniform(0.5, 1.0)
        bp, bw = make_crack_polyline(rng, pts[i], th, sp.length_mm * rng.uniform(0.3, 0.5),
                                     sp.w_base * rng.uniform(0.4, 0.7))
        cracks.append({"pts_wall": bp, "widths": bw, "branch": True})
    if widen_mm or extend_mm:
        c = cracks[0]
        w = c["widths"] + widen_mm
        p = c["pts_wall"]
        if extend_mm > 0:
            erng = np.random.default_rng(sp.seed * 7 + 99)
            t = p[-1] - p[-6]
            th = math.atan2(t[1], t[0])
            ep, ew = make_crack_polyline(erng, p[-1], th, extend_mm + 1.0, 1.0)
            # extension: narrows from the old tip width to ~40 % of it
            ramp = np.linspace(1.0, 0.4, len(ep))
            ew = w[-1] * ramp
            p = np.vstack([p, ep[1:]])
            w = np.concatenate([w, ew[1:]])
        cracks[0] = {"pts_wall": p, "widths": w, "branch": False, "extended_from_index": len(c["pts_wall"]) if extend_mm > 0 else None}
    return cracks


def sample_camera(rng, look_at, hard=False):
    ppm = float(math.exp(rng.uniform(math.log(3.0), math.log(9.0))))
    tilt = float(rng.uniform(0, 45) if not hard else rng.uniform(35, 55))
    return dict(ppm=ppm, tilt_deg=tilt, azimuth_deg=float(rng.uniform(0, 360)),
                roll_deg=float(rng.uniform(-20, 20)), look_at=look_at)


def degrade(img_lin, rng, H_img):
    """Camera-side degradations on the float image (0..1). Returns uint8 BGR + params."""
    p = {}
    sigma = float(math.exp(rng.uniform(math.log(0.5), math.log(1.8))))
    p["blur_sigma_px"] = sigma
    img = cv2.GaussianBlur(img_lin, (0, 0), sigma)
    p["motion_px"] = 0
    if rng.random() < 0.15:
        L = int(rng.integers(3, 10))
        k = np.zeros((L, L), np.float32)
        k[L // 2, :] = 1.0 / L
        M = cv2.getRotationMatrix2D(((L - 1) / 2, (L - 1) / 2), float(rng.uniform(0, 180)), 1.0)
        k = cv2.warpAffine(k, M, (L, L))
        k /= k.sum()
        img = cv2.filter2D(img, -1, k)
        p["motion_px"] = L
    h, w = img.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    g = rng.uniform(-0.35, 0.35, 2)
    grad = 1.0 + g[0] * (xx / w - 0.5) + g[1] * (yy / h - 0.5)
    vig = 1.0 - rng.uniform(0, 0.35) * (((xx - w / 2) / w) ** 2 + ((yy - h / 2) / h) ** 2) * 2
    expo = float(rng.uniform(0.65, 1.25))
    img = img * grad * vig * expo
    p["exposure"] = expo
    p["glare"] = False
    if rng.random() < 0.08:
        cx, cy, r = rng.uniform(0.2, 0.8) * w, rng.uniform(0.2, 0.8) * h, rng.uniform(60, 200)
        img = img + 0.9 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r * r))
        p["glare"] = True
    noise = float(rng.uniform(0.004, 0.025))
    img = img + rng.normal(0, 1, img.shape).astype(np.float32) * (noise * np.sqrt(np.clip(img, 0.02, None) / 0.5))
    p["noise"] = noise
    img = np.clip(img, 0, 1) ** (1 / 1.1)
    tint = np.array([0.96, 1.0, 1.03], np.float32) * rng.uniform(0.97, 1.03, 3).astype(np.float32)
    bgr = np.clip(img[..., None] * tint * 255.0 + 0.5, 0, 255).astype(np.uint8)
    q = int(rng.integers(55, 96))
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, q])
    p["jpeg_quality"] = q
    return cv2.imdecode(buf, cv2.IMREAD_COLOR), buf, p


def render_view(wall: Wall, sp: SceneParams, cracks, card_pose, cam, rng, spec=CARD_A6):
    H_wall, _ = camera_homography(cam["look_at"], cam["ppm"], cam["tilt_deg"], cam["azimuth_deg"], cam["roll_deg"])
    Hinv = np.linalg.inv(H_wall)
    corners = apply_h(Hinv, [(0, 0), (IMG_W, 0), (IMG_W, IMG_H), (0, IMG_H)])
    x0, y0 = corners.min(0) - 5
    x1, y1 = corners.max(0) + 5
    x0, y0 = max(x0, WALL_REGION[0]), max(y0, WALL_REGION[1])
    x1, y1 = min(x1, WALL_REGION[2]), min(y1, WALL_REGION[3])
    ppm_max = max(local_ppm(H_wall, c) for c in apply_h(Hinv, [(0, 0), (IMG_W, 0), (IMG_W, IMG_H), (0, IMG_H), (IMG_W / 2, IMG_H / 2)]))
    P = float(np.clip(round(2.0 * ppm_max), 6, 22))
    shape = (int((y1 - y0) * P) + 1, int((x1 - x0) * P) + 1)
    img = render_wall(wall, (x0, y0), P, shape, rng)
    render_cracks(img, cracks, (x0, y0), P, sp.crack_depth)
    paste_card(img, spec, card_pose, (x0, y0), P)
    img = cv2.GaussianBlur(img, (0, 0), 0.35 * P / cam["ppm"])
    S = np.array([[1 / P, 0, x0 + 0.5 / P], [0, 1 / P, y0 + 0.5 / P], [0, 0, 1]])
    H_img_raster = H_wall @ S
    out = cv2.warpPerspective(img, H_img_raster, (IMG_W, IMG_H), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REFLECT)
    return out, H_wall


def _gt_cracks(cracks, card_pose, H_wall):
    B2W = board_to_wall(card_pose)
    W2B = np.linalg.inv(B2W)
    out = []
    for c in cracks:
        pts_b = apply_h(W2B, c["pts_wall"])
        img_pts = apply_h(H_wall, c["pts_wall"])
        vis = (img_pts[:, 0] >= 2) & (img_pts[:, 0] < IMG_W - 2) & (img_pts[:, 1] >= 2) & (img_pts[:, 1] < IMG_H - 2)
        ppm_loc = [local_ppm(H_wall, p) for p in c["pts_wall"][:: max(1, len(c["pts_wall"]) // 20)]]
        out.append({
            "branch": bool(c["branch"]),
            "pts_board_mm": np.round(pts_b, 4).tolist(),
            "width_mm": np.round(c["widths"], 4).tolist(),
            "visible": vis.astype(int).tolist(),
            "extended_from_index": c.get("extended_from_index"),
            "img_ppm_median": float(np.median(ppm_loc)),
        })
    return out


def card_visibility(H_wall, card_pose, spec=CARD_A6):
    """Number of ChArUco inner corners that project inside the image."""
    from .card import make_board
    corners = make_board(spec).getChessboardCorners()[:, :2]
    p = apply_h(H_wall @ board_to_wall(card_pose), corners)
    return int(((p[:, 0] > 5) & (p[:, 0] < IMG_W - 5) & (p[:, 1] > 5) & (p[:, 1] < IMG_H - 5)).sum())


def _choose_camera(rng, sp, cracks, card_pose, hard=False):
    cpts = np.vstack([c["pts_wall"] for c in cracks])
    B2W = board_to_wall(card_pose)
    card_c = apply_h(B2W, [(37.5, 52.5)])[0]
    for _ in range(60):
        crack_c = cpts.mean(0)
        a = rng.uniform(0.35, 0.75)
        look = tuple(card_c * (1 - a) + crack_c * a + rng.normal(0, 8, 2))
        cam = sample_camera(rng, look, hard)
        Hw, C = camera_homography(look, cam["ppm"], cam["tilt_deg"], cam["azimuth_deg"], cam["roll_deg"])
        ip = apply_h(Hw, cpts)
        vis = ((ip[:, 0] > 20) & (ip[:, 0] < IMG_W - 20) & (ip[:, 1] > 20) & (ip[:, 1] < IMG_H - 20)).mean()
        if vis > 0.7 and card_visibility(Hw, card_pose) >= 12:
            return cam, Hw
    return None, None


def generate_sample(seed, out_dir, w_base=None, distractors=True, hard=False):
    rng = np.random.default_rng(seed)
    sp = sample_scene(rng, seed, w_base)
    wall = make_wall(rng, seed, distractors)
    cracks = build_cracks(sp)
    cam, Hw = _choose_camera(rng, sp, cracks, sp.card_pose, hard)
    if cam is None:
        return None
    lin, Hw = render_view(wall, sp, cracks, sp.card_pose, cam, rng)
    img, buf, deg = degrade(lin, rng, Hw)
    name = f"e1_{seed:05d}"
    with open(os.path.join(out_dir, name + ".jpg"), "wb") as f:
        f.write(buf.tobytes())
    H_img_board = Hw @ board_to_wall(sp.card_pose)
    gt = {
        "id": name, "image": name + ".jpg", "seed": seed, "card": CARD_A6.name,
        "H_img_from_board": (H_img_board / H_img_board[2, 2]).tolist(),
        "camera": cam, "degradations": deg, "crack_depth": sp.crack_depth,
        "w_base_mm": sp.w_base,
        "distractors": {"joint": wall.joint is not None, "stain": wall.stain is not None},
        "cracks": _gt_cracks(cracks, sp.card_pose, Hw),
    }
    allw = np.concatenate([np.array(c["width_mm"])[np.array(c["visible"], bool)] for c in gt["cracks"]] or [np.zeros(0)])
    gt["max_width_mm"] = float(allw.max()) if allw.size else None
    gt["median_width_mm"] = float(np.median(allw)) if allw.size else None
    with open(os.path.join(out_dir, name + ".json"), "w") as f:
        json.dump(gt, f)
    return gt


def generate_pair(seed, out_dir, widen_mm, extend_mm, move_card):
    """E4: same wall seen twice; visit 2 has the main crack widened/extended and the card
    possibly re-glued at a slightly different pose."""
    rng = np.random.default_rng(seed)
    sp = sample_scene(rng, seed, w_base=float(math.exp(rng.uniform(math.log(0.4), math.log(3.0)))))
    sp.branch = False
    wall = make_wall(rng, seed, distractors=False)
    res = {"id": f"e4_{seed:05d}", "widen_mm": widen_mm, "extend_mm": extend_mm, "card_moved": move_card, "visits": []}
    for v in (1, 2):
        cracks = build_cracks(sp) if v == 1 else build_cracks(sp, widen_mm, extend_mm)
        pose = sp.card_pose
        if v == 2 and move_card:
            pose = (pose[0] + rng.uniform(-8, 8), pose[1] + rng.uniform(-8, 8), pose[2] + math.radians(rng.uniform(-5, 5)))
        vrng = np.random.default_rng(seed * 10 + v)
        cam, Hw = _choose_camera(vrng, sp, cracks, pose)
        if cam is None:
            return None
        lin, Hw = render_view(wall, sp, cracks, pose, cam, vrng)
        img, buf, deg = degrade(lin, vrng, Hw)
        name = f"{res['id']}_v{v}"
        with open(os.path.join(out_dir, name + ".jpg"), "wb") as f:
            f.write(buf.tobytes())
        H_img_board = Hw @ board_to_wall(pose)
        res["visits"].append({"image": name + ".jpg", "card_pose": list(pose),
                              "H_img_from_board": (H_img_board / H_img_board[2, 2]).tolist(),
                              "camera": cam, "degradations": deg,
                              "cracks": _gt_cracks(cracks, pose, Hw)})
    # board(v2) -> board(v1) transform (identity when the card did not move)
    p1, p2 = res["visits"][0]["card_pose"], res["visits"][1]["card_pose"]
    T = np.linalg.inv(board_to_wall(p1)) @ board_to_wall(p2)
    res["T_board1_from_board2"] = T.tolist()
    with open(os.path.join(out_dir, res["id"] + ".json"), "w") as f:
        json.dump(res, f)
    return res

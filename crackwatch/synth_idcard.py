"""Synthetic scenes for the wallet-card (ID-1) reference, built on synth.py's walls, cracks and cameras.

Each scene is rendered twice with the SAME wall, cracks, camera and camera degradations:
  - twin "charuco": the printed A6 ChArUco card glued on the wall (as synth.py);
  - twin "idcard":  an ID-1 card (85.60 x 53.98 mm, r = 3.18 mm) instead, rendered as a 0.76 mm thick slab
    standing on the wall: face plane 0.76 mm in front of the wall, visible side wall (white core or face
    colour) on the edges that face the camera, optional contact shadow, random face design with card
    number digits, optional gloss, optional finger (tip on the card, crossing one edge or one corner, or
    laid along a short edge).
So the scale error and the crack-width error of the two references can be compared scene by scene.
Colour pipeline: the grey wall of synth.py is tinted (plaster colours); camera degradations as synth.degrade
(same distributions) applied per channel.
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from . import synth
from .card import CARD_A6
from .idcard import ID1_CORNER_R_MM, ID1_H_MM, ID1_THICK_MM, ID1_W_MM

IMG_W, IMG_H = synth.IMG_W, synth.IMG_H


# ------------------------------------------------------------------------------------------- camera
def camera(look_at_mm, ppm, tilt_deg, azimuth_deg, roll_deg, focal_px):
    """Same construction as synth.camera_homography, with a free focal length. -> K, R (world->cam), C."""
    K = np.array([[focal_px, 0, IMG_W / 2 - 0.5], [0, focal_px, IMG_H / 2 - 0.5], [0, 0, 1]])
    az, tl, rl = map(math.radians, (azimuth_deg, tilt_deg, roll_deg))
    R_tilt = synth.rot_z(az) @ synth.rot_x(tl) @ synth.rot_z(-az) @ synth.rot_z(rl)
    Z = focal_px / ppm
    P0 = np.array([look_at_mm[0], look_at_mm[1], 0.0])
    C = P0 - Z * R_tilt[:, 2]
    return K, R_tilt.T, C


def plane_h(K, R, C, z):
    """Homography wall-xy (mm) -> image px for the plane z (z < 0 is in front of the wall)."""
    t = -R @ C
    H = K @ np.column_stack([R[:, 0], R[:, 1], z * R[:, 2] + t])
    return H / H[2, 2]


def card_to_wall(pose):
    """Card frame (mm, origin at a virtual corner) -> wall mm, pose = (cx, cy, theta) of the card centre."""
    cx, cy, th = pose
    c, s = math.cos(th), math.sin(th)
    return np.array([[c, -s, cx - c * ID1_W_MM / 2 + s * ID1_H_MM / 2],
                     [s, c, cy - s * ID1_W_MM / 2 - c * ID1_H_MM / 2], [0, 0, 1.0]])


def rounded_rect(r=ID1_CORNER_R_MM, n_arc=10, w=ID1_W_MM, h=ID1_H_MM):
    pts = []
    for cx, cy, a0 in ((w - r, r, -90), (w - r, h - r, 0), (r, h - r, 90), (r, r, 180)):
        for k in range(n_arc + 1):
            a = math.radians(a0 + 90 * k / n_arc)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return np.array(pts)


# ------------------------------------------------------------------------------------------- card face
PALETTE = [(0.55, 0.28, 0.08), (0.12, 0.12, 0.70), (0.20, 0.50, 0.15), (0.10, 0.10, 0.10), (0.25, 0.60, 0.80),
           (0.72, 0.72, 0.72), (0.93, 0.93, 0.93), (0.55, 0.15, 0.45), (0.15, 0.45, 0.95), (0.60, 0.55, 0.10),
           (0.85, 0.80, 0.70), (0.35, 0.20, 0.05)]


def render_face(rng, P):
    """Card face raster (BGR float 0..1) at P px/mm + alpha (rounded corners) + digits box (card mm)."""
    Wp, Hp = int(round(ID1_W_MM * P)), int(round(ID1_H_MM * P))
    style = rng.choice(["solid", "gradient", "diag", "pattern", "light", "dark"], p=[0.2, 0.2, 0.15, 0.2, 0.12, 0.13])
    pal = [np.array(c, np.float32) for c in PALETTE]
    c1 = pal[rng.integers(len(pal))] * rng.uniform(0.85, 1.1)
    c2 = pal[rng.integers(len(pal))] * rng.uniform(0.85, 1.1)
    if style == "light":
        c1 = np.array([0.93, 0.94, 0.95], np.float32) * rng.uniform(0.92, 1.05)
    if style == "dark":
        c1 = np.array([0.10, 0.10, 0.12], np.float32) * rng.uniform(0.7, 1.5)
    yy, xx = np.mgrid[0:Hp, 0:Wp].astype(np.float32)
    img = np.empty((Hp, Wp, 3), np.float32)
    img[:] = c1
    if style == "gradient":
        a = (xx / Wp)[..., None]
        img = c1 * (1 - a) + c2 * a
    elif style == "diag":
        m = ((xx / Wp + rng.uniform(-0.3, 0.3)) > (yy / Hp))[..., None]
        img = np.where(m, c1, c2).astype(np.float32)
    elif style == "pattern":
        for _ in range(int(rng.integers(3, 9))):
            col = pal[rng.integers(len(pal))]
            lay = np.zeros((Hp, Wp), np.float32)
            if rng.random() < 0.5:
                cv2.circle(lay, (int(rng.uniform(0, Wp)), int(rng.uniform(0, Hp))), int(rng.uniform(5, 40) * P), 1.0, -1, cv2.LINE_AA)
            else:
                y0 = rng.uniform(0, Hp)
                cv2.line(lay, (0, int(y0)), (Wp, int(y0 + rng.uniform(-Hp, Hp))), 1.0, int(rng.uniform(2, 12) * P), cv2.LINE_AA)
            a = (lay * rng.uniform(0.3, 0.8))[..., None]
            img = img * (1 - a) + col * a
    img = img.astype(np.float32)
    # chip, logo, digits, name
    if rng.random() < 0.7:
        x0, y0 = rng.uniform(8, 12) * P, rng.uniform(18, 22) * P
        cv2.rectangle(img, (int(x0), int(y0)), (int(x0 + 11.5 * P), int(y0 + 8.5 * P)), (0.35, 0.62, 0.80), -1, cv2.LINE_AA)
        cv2.line(img, (int(x0), int(y0 + 4.2 * P)), (int(x0 + 11.5 * P), int(y0 + 4.2 * P)), (0.25, 0.45, 0.6), max(1, int(0.3 * P)), cv2.LINE_AA)
    if rng.random() < 0.8:
        cv2.circle(img, (int(rng.uniform(62, 76) * P), int(rng.uniform(8, 14) * P)), int(rng.uniform(4, 7) * P),
                   tuple(float(v) for v in pal[rng.integers(len(pal))]), -1, cv2.LINE_AA)
    lum = float(img.mean())
    ink = (0.95, 0.95, 0.95) if lum < 0.5 else (0.08, 0.08, 0.08)
    digits = " ".join("".join(str(int(d)) for d in rng.integers(0, 10, 4)) for _ in range(4))
    dy = rng.uniform(36, 42)
    sc = 4.0 * P / 22.0
    name = "".join(chr(int(c)) for c in rng.integers(65, 91, 10))
    txt = np.zeros((Hp, Wp), np.uint8)               # putText draws on 8-bit images only (OpenCV 5)
    cv2.putText(txt, digits, (int(7 * P), int(dy * P)), cv2.FONT_HERSHEY_SIMPLEX, sc, 255, max(1, int(0.5 * P)), cv2.LINE_AA)
    cv2.putText(txt, name, (int(7 * P), int((dy + 8) * P)), cv2.FONT_HERSHEY_SIMPLEX, sc * 0.7, 255, max(1, int(0.35 * P)), cv2.LINE_AA)
    a = (txt.astype(np.float32) / 255.0)[..., None]
    img = img * (1 - a) + np.array(ink, np.float32) * a
    alpha = np.zeros((Hp, Wp), np.float32)
    rr = (rounded_rect() * P - 0.5) * 16
    cv2.fillPoly(alpha, [np.round(rr).astype(np.int32)], 1.0, cv2.LINE_AA, 4)
    return np.clip(img, 0, 1), alpha, (6.0, dy - 5.0, 80.0, dy + 10.0), str(style)


# ------------------------------------------------------------------------------------------- finger
def finger_polygon(rng, kind):
    """Finger outline in card mm (capsule), or None."""
    w = rng.uniform(15, 18)
    if kind == "none":
        return None
    if kind == "press_centre":           # fingertip pressing the card's centre, finger crossing a long edge
        side = 1.0 if rng.random() < 0.5 else -1.0
        ang = rng.uniform(-0.5, 0.5)
        d = np.array([math.sin(ang), side * math.cos(ang)])
        a = np.array([ID1_W_MM / 2 + rng.uniform(-8, 8), ID1_H_MM / 2 + rng.uniform(-5, 5)])
        return _capsule(a, a + d * 90.0, rng.uniform(16, 20))
    if kind == "hand_long":              # hand / palm over most of a long edge (two short fragments stay visible)
        side = 1.0 if rng.random() < 0.5 else -1.0
        c = np.array([ID1_W_MM / 2 + rng.uniform(-5, 5), ID1_H_MM / 2 + side * (ID1_H_MM / 2 + rng.uniform(8, 14))])
        rx, ry = rng.uniform(30, 34), rng.uniform(20, 26)
        t = np.linspace(0, 2 * math.pi, 48, endpoint=False)
        return np.column_stack([c[0] + rx * np.cos(t), c[1] + ry * np.sin(t)])
    if kind == "short_full":            # finger laid along a short edge: hides it almost entirely
        x = 0.0 if rng.random() < 0.5 else ID1_W_MM
        c = np.array([x + rng.uniform(-2, 2), ID1_H_MM / 2 + rng.uniform(-3, 3)])
        d = np.array([0.0, 1.0])
        L = rng.uniform(55, 70)
        a, b = c - d * L / 2, c + d * L / 2
    else:
        if kind == "short_mid":
            side = rng.integers(2)
            edge = np.array([0.0 if side == 0 else ID1_W_MM, ID1_H_MM / 2 + rng.uniform(-8, 8)])
            d = np.array([-1.0 if side == 0 else 1.0, 0.0])
        elif kind == "long_mid":
            side = rng.integers(2)
            edge = np.array([ID1_W_MM / 2 + rng.uniform(-20, 20), 0.0 if side == 0 else ID1_H_MM])
            d = np.array([0.0, -1.0 if side == 0 else 1.0])
        else:                            # corner
            cx = 0.0 if rng.random() < 0.5 else ID1_W_MM
            cy = 0.0 if rng.random() < 0.5 else ID1_H_MM
            edge = np.array([cx, cy])
            d = np.array([-1.0 if cx == 0 else 1.0, -1.0 if cy == 0 else 1.0]) / math.sqrt(2)
            ang = rng.uniform(-0.4, 0.4)
            d = np.array([math.cos(ang) * d[0] - math.sin(ang) * d[1], math.sin(ang) * d[0] + math.cos(ang) * d[1]])
        a = edge - d * rng.uniform(8, 15)            # fingertip inside the card
        b = a + d * 70.0
    return _capsule(a, b, w)


def _capsule(a, b, w):
    dd = (b - a) / np.linalg.norm(b - a)
    nn = np.array([-dd[1], dd[0]])
    pts = []
    for k in range(16):
        t = math.pi / 2 + math.pi * k / 15
        pts.append(a + (dd * math.cos(t) + nn * math.sin(t)) * w / 2)
    for k in range(16):
        t = -math.pi / 2 + math.pi * k / 15
        pts.append(b + (dd * math.cos(t) + nn * math.sin(t)) * w / 2)
    return np.array(pts)


# ------------------------------------------------------------------------------------------- degradations
def degrade_color(img, rng):
    """synth.degrade for a colour float image (same distributions, applied per channel)."""
    p = {}
    sigma = float(math.exp(rng.uniform(math.log(0.5), math.log(1.8))))
    p["blur_sigma_px"] = sigma
    img = cv2.GaussianBlur(img, (0, 0), sigma)
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
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    g = rng.uniform(-0.35, 0.35, 2)
    grad = 1.0 + g[0] * (xx / w - 0.5) + g[1] * (yy / h - 0.5)
    vig = 1.0 - rng.uniform(0, 0.35) * (((xx - w / 2) / w) ** 2 + ((yy - h / 2) / h) ** 2) * 2
    expo = float(rng.uniform(0.65, 1.25))
    img = img * (grad * vig * expo)[..., None]
    p["exposure"] = expo
    p["glare"] = False
    if rng.random() < 0.08:
        cx, cy, r = rng.uniform(0.2, 0.8) * w, rng.uniform(0.2, 0.8) * h, rng.uniform(60, 200)
        img = img + (0.9 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r * r)))[..., None]
        p["glare"] = True
    noise = float(rng.uniform(0.004, 0.025))
    img = img + rng.normal(0, 1, img.shape).astype(np.float32) * (noise * np.sqrt(np.clip(img, 0.02, None) / 0.5))
    p["noise"] = noise
    img = np.clip(img, 0, 1) ** (1 / 1.1)
    bgr = np.clip(img * 255.0 + 0.5, 0, 255).astype(np.uint8)
    q = int(rng.integers(55, 96))
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, q])
    p["jpeg_quality"] = q
    return cv2.imdecode(buf, cv2.IMREAD_COLOR), p


# ------------------------------------------------------------------------------------------- scene
WALL_TINTS = [(0.93, 0.97, 1.0), (1.0, 1.0, 1.0), (0.86, 0.94, 1.0), (0.97, 0.98, 0.96), (0.80, 0.88, 0.95)]
FINGER_KINDS = (("none", 0.40), ("short_mid", 0.10), ("corner", 0.12), ("long_mid", 0.06), ("short_full", 0.08),
                ("press_centre", 0.14), ("hand_long", 0.10))


def _visible(H, pts, margin):
    q = synth.apply_h(H, pts)
    return (q[:, 0] > margin) & (q[:, 0] < IMG_W - margin) & (q[:, 1] > margin) & (q[:, 1] < IMG_H - margin)


def make_scene(seed, finger=None, hard=False, w_base=None, max_tilt=None, both=False):
    """-> dict with the two twin images (BGR uint8) and the ground truth, or None if no valid camera.
    `both`: the wallet-card image also keeps the ChArUco card (wallet card placed below it), as in the
    owner's comparison photos."""
    rng = np.random.default_rng(seed)
    sp = synth.sample_scene(rng, seed, w_base)
    wall = synth.make_wall(rng, seed)
    cracks = synth.build_cracks(sp)
    B2W = synth.board_to_wall(sp.card_pose)
    board_c = synth.apply_h(B2W, [(37.5, 52.5)])[0]
    base = 0.0 if rng.random() < 0.6 else math.pi / 2
    cpose = (board_c[0] + rng.uniform(-6, 6), board_c[1] + rng.uniform(-6, 6), base + math.radians(rng.uniform(-25, 25)))
    if both:
        cpose = (board_c[0] + rng.uniform(-6, 6), board_c[1] + 125.0, math.radians(rng.uniform(-15, 15)))
    C2W = card_to_wall(cpose)
    outline_wall = synth.apply_h(C2W, rounded_rect())
    cpts = np.vstack([c["pts_wall"] for c in cracks])
    kinds, probs = zip(*FINGER_KINDS)
    fkind = finger if finger is not None else str(rng.choice(kinds, p=probs))
    cam = None
    for _ in range(80):
        a = rng.uniform(0.35, 0.75)
        look = tuple(board_c * (1 - a) + cpts.mean(0) * a + rng.normal(0, 8, 2))
        c = synth.sample_camera(rng, look, hard)
        if max_tilt is not None and c["tilt_deg"] > max_tilt:
            continue
        # phone main cameras: 23-30 mm in 35 mm equivalent (on the image diagonal), incl. 16:9 / 4:3 crops
        c["focal_px"] = float(rng.uniform(23.0, 30.0) / 43.27 * math.hypot(IMG_W, IMG_H))
        K, R, Cc = camera(look, c["ppm"], c["tilt_deg"], c["azimuth_deg"], c["roll_deg"], c["focal_px"])
        Hw = plane_h(K, R, Cc, 0.0)
        if _visible(Hw, cpts, 20).mean() > 0.7 and _visible(Hw, outline_wall, 15).all() \
                and synth.card_visibility(Hw, sp.card_pose) >= 12:
            cam = c
            break
    if cam is None:
        return None
    K, R, Cc = camera(cam["look_at"], cam["ppm"], cam["tilt_deg"], cam["azimuth_deg"], cam["roll_deg"], cam["focal_px"])
    Hw = plane_h(K, R, Cc, 0.0)
    Hf = plane_h(K, R, Cc, -ID1_THICK_MM)
    # wall raster (as synth.render_view)
    Hinv = np.linalg.inv(Hw)
    corners = synth.apply_h(Hinv, [(0, 0), (IMG_W, 0), (IMG_W, IMG_H), (0, IMG_H)])
    x0, y0 = np.maximum(corners.min(0) - 5, synth.WALL_REGION[:2])
    x1, y1 = np.minimum(corners.max(0) + 5, synth.WALL_REGION[2:])
    ppm_max = max(synth.local_ppm(Hw, q) for q in synth.apply_h(Hinv, [(0, 0), (IMG_W, 0), (IMG_W, IMG_H), (0, IMG_H), (IMG_W / 2, IMG_H / 2)]))
    P = float(np.clip(round(2.0 * ppm_max), 6, 22))
    shape = (int((y1 - y0) * P) + 1, int((x1 - x0) * P) + 1)
    raster = synth.render_wall(wall, (x0, y0), P, shape, rng)
    synth.render_cracks(raster, cracks, (x0, y0), P, sp.crack_depth)
    tint = np.array(WALL_TINTS[rng.integers(len(WALL_TINTS))], np.float32)
    S = np.array([[1 / P, 0, x0 + 0.5 / P], [0, 1 / P, y0 + 0.5 / P], [0, 0, 1]])
    shadow = rng.random() < 0.6
    sh_off = rng.normal(0, 0.5, 2)
    sh_str = rng.uniform(0.08, 0.3)

    def to_image(r):
        r = cv2.GaussianBlur(r, (0, 0), 0.35 * P / cam["ppm"])
        g = cv2.warpPerspective(r, Hw @ S, (IMG_W, IMG_H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
        return g[..., None] * tint

    # twin A: ChArUco card
    rA = raster.copy()
    synth.paste_card(rA, CARD_A6, sp.card_pose, (x0, y0), P)
    imgA = to_image(rA)
    # twin B: wallet card
    rB = rA.copy() if both else raster.copy()
    if shadow:
        m = np.zeros(shape, np.float32)
        o = (synth.apply_h(C2W, rounded_rect() + sh_off) - (x0, y0)) * P - 0.5
        cv2.fillPoly(m, [np.round(o * 16).astype(np.int32)], 1.0, cv2.LINE_AA, 4)
        rB *= 1.0 - sh_str * cv2.GaussianBlur(m, (0, 0), 0.5 * P)
    imgB = to_image(rB)
    # finger shadow on the wall/card (soft), drawn in image space below the card face for simplicity
    fpoly = finger_polygon(rng, fkind)
    # card slab: side wall = convex hull of the projected bottom and top outlines
    Hc_bottom, Hc_top = Hw @ C2W, Hf @ C2W
    rr = rounded_rect(n_arc=12)
    hull = cv2.convexHull(np.vstack([synth.apply_h(Hc_bottom, rr), synth.apply_h(Hc_top, rr)]).astype(np.float32)).reshape(-1, 2)
    Pc = float(np.clip(round(2.0 * synth.local_ppm(Hc_top, (ID1_W_MM / 2, ID1_H_MM / 2))), 8, 24))
    face, alpha, digits_box, style = render_face(rng, Pc)
    side_col = np.array([0.9, 0.9, 0.9], np.float32) if rng.random() < 0.5 else np.clip(face.mean((0, 1)) * 0.8, 0, 1)
    side_mask = np.zeros((IMG_H, IMG_W), np.float32)
    cv2.fillPoly(side_mask, [np.round((hull) * 16).astype(np.int32)], 1.0, cv2.LINE_AA, 4)
    imgB = imgB * (1 - side_mask[..., None]) + side_col * side_mask[..., None]
    if rng.random() < 0.2:                         # gloss: soft specular band on the face
        yy, xx = np.mgrid[0:face.shape[0], 0:face.shape[1]].astype(np.float32)
        th = rng.uniform(0, math.pi)
        dist = (xx - rng.uniform(0, face.shape[1])) * math.cos(th) + (yy - rng.uniform(0, face.shape[0])) * math.sin(th)
        face = np.clip(face + rng.uniform(0.2, 0.5) * np.exp(-dist ** 2 / (2 * (rng.uniform(3, 10) * Pc) ** 2))[..., None], 0, 1)
    face = cv2.GaussianBlur(face, (0, 0), 0.35 * Pc / cam["ppm"])
    Sc = np.array([[1 / Pc, 0, 0.5 / Pc], [0, 1 / Pc, 0.5 / Pc], [0, 0, 1]])
    fw = cv2.warpPerspective(face, Hc_top @ Sc, (IMG_W, IMG_H), flags=cv2.INTER_LINEAR, borderValue=0)
    aw = cv2.warpPerspective(alpha, Hc_top @ Sc, (IMG_W, IMG_H), flags=cv2.INTER_LINEAR, borderValue=0)
    imgB = imgB * (1 - aw[..., None]) + fw * aw[..., None]
    if fpoly is not None:
        Hfinger = plane_h(K, R, Cc, -ID1_THICK_MM - 4.0) @ C2W
        fm = np.zeros((IMG_H, IMG_W), np.float32)
        fp = synth.apply_h(Hfinger, fpoly)
        sp_ = synth.apply_h(Hw @ C2W, fpoly + rng.normal(0, 2.0, 2))
        sm = np.zeros((IMG_H, IMG_W), np.float32)
        cv2.fillPoly(sm, [np.round(sp_ * 16).astype(np.int32)], 1.0, cv2.LINE_AA, 4)
        sm = cv2.GaussianBlur(sm, (0, 0), 2.0 * cam["ppm"])
        imgB *= 1.0 - 0.3 * sm[..., None]
        cv2.fillPoly(fm, [np.round(fp * 16).astype(np.int32)], 1.0, cv2.LINE_AA, 4)
        dist = cv2.distanceTransform((fm > 0.5).astype(np.uint8), cv2.DIST_L2, 5)
        shade = 0.65 + 0.35 * np.sqrt(np.clip(dist / max(dist.max(), 1.0), 0, 1))
        skin = np.array([0.52, 0.63, 0.86], np.float32) * rng.uniform(0.3, 1.1)     # dark to light skin
        imgB = imgB * (1 - fm[..., None]) + (skin * shade[..., None]) * fm[..., None]
    seed_deg = int(rng.integers(1 << 30))
    outA, degA = degrade_color(imgA.astype(np.float32), np.random.default_rng(seed_deg))
    outB, degB = degrade_color(imgB.astype(np.float32), np.random.default_rng(seed_deg))
    gt_cracks = []
    for c in cracks:
        vis = _visible(Hw, c["pts_wall"], 2)
        gt_cracks.append({"branch": bool(c["branch"]), "pts_board_mm": c["pts_wall"].tolist(),  # wall frame
                          "width_mm": c["widths"].tolist(), "visible": vis.astype(int).tolist()})
    return {"seed": seed, "img_charuco": outA, "img_idcard": outB, "degradations": degA, "camera": cam,
            "H_img_from_wall": Hw, "H_img_from_board_charuco": Hw @ B2W, "H_img_from_card_wall": Hw @ C2W,
            "H_img_from_card_face": Hf @ C2W, "card_pose": cpose, "finger": fkind, "face_style": style,
            "digits_box_card_mm": digits_box, "shadow": bool(shadow), "cracks": gt_cracks,
            "crack_center_wall": cpts.mean(0).tolist(), "w_base_mm": sp.w_base}


def scale_errors(H_est, H_img_from_wall, wall_pt):
    """Relative scale error of an estimated metric homography at a wall point, worst over directions:
    singular values of J_est^-1 J_true (true wall mm -> estimated mm), returned as (s_min-1, s_max-1)."""
    x = synth.apply_h(H_img_from_wall, [wall_pt])[0]
    est_pt = synth.apply_h(np.linalg.inv(H_est), [x])[0]

    def jac(H, p):
        e = 0.05
        q = synth.apply_h(H, [p, (p[0] + e, p[1]), (p[0], p[1] + e)])
        return np.column_stack([(q[1] - q[0]) / e, (q[2] - q[0]) / e])
    M = np.linalg.solve(jac(H_est, est_pt), jac(H_img_from_wall, wall_pt))
    s = np.linalg.svd(M, compute_uv=False)
    return float(s.min() - 1), float(s.max() - 1)

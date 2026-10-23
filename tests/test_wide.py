"""Wide-width measurement: printed-chart-like bars of known width (0.5 to 8 mm) next to a ChArUco
board, seen through a mild perspective, Gaussian blur, noise and JPEG. Bars are only max(4 mm, width)
apart, so the local background of each profile must not be read on the neighbouring bars. (Closer than
that, dark bars would fill more than half of the 20 mm background window, which no crack scene does.)
Run: python tests/test_wide.py   (or pytest)"""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch.card import CARD_A6, render_board  # noqa: E402
from crackwatch.measure import measure_image  # noqa: E402

WIDTHS = (0.5, 1.0, 2.0, 3.0, 4.0, 6.0, 8.0)
GAP_MM = 4.0                   # minimum edge-to-edge gap; the gap is at least the wider neighbour
PAGE = (180.0, 150.0)          # page mm (w, h); board top-left at (10, 10) on the page
OFF = (10.0, 10.0)
BOARD_RECT = (-3.0, -3.0, 75.0, 108.0)     # board area; rectify() adds a 4 mm margin


def bars_layout():
    out, x = [], 92.0 - OFF[0]
    for i, w in enumerate(WIDTHS):
        out.append((x + w / 2, 10.0, 110.0, w))     # x centre, y0, y1 (board mm), width
        x += w + max(GAP_MM, w, WIDTHS[min(i + 1, len(WIDTHS) - 1)])
    return out


def render(ppm_img=6.0, blur_px=1.0, tilt=0.08, seed=0):
    P = 20.0                                         # page raster px/mm
    page = np.full((int(PAGE[1] * P), int(PAGE[0] * P)), 1.0, np.float32)
    b = render_board(CARD_A6, P).astype(np.float32) / 255.0
    page[int(OFF[1] * P):int(OFF[1] * P) + b.shape[0], int(OFF[0] * P):int(OFF[0] * P) + b.shape[1]] = b
    for xc, y0, y1, w in bars_layout():
        page[int(round((y0 + OFF[1]) * P)):int(round((y1 + OFF[1]) * P)),
             int(round((xc - w / 2 + OFF[0]) * P)):int(round((xc + w / 2 + OFF[0]) * P))] = 0.0
    page = 0.08 + 0.80 * page                        # toner is not black, paper not white
    page = cv2.GaussianBlur(page, (0, 0), 0.4 * P / ppm_img)   # anti-alias before resampling (as synth.py)
    # page px -> board mm -> image px (mild perspective)
    S = np.array([[1 / P, 0, 0.5 / P - OFF[0]], [0, 1 / P, 0.5 / P - OFF[1]], [0, 0, 1]])
    W, H = int(PAGE[0] * ppm_img) + 120, int(PAGE[1] * ppm_img) + 120
    A = np.array([[ppm_img, 0.02 * ppm_img, 60 + OFF[0] * ppm_img], [-0.01 * ppm_img, ppm_img, 60 + OFF[1] * ppm_img],
                  [tilt / 1000.0, 0.0, 1.0]])
    canvas = cv2.warpPerspective(page, A @ S, (W, H), flags=cv2.INTER_LINEAR, borderValue=0.35)
    canvas = cv2.GaussianBlur(canvas, (0, 0), blur_px)
    rng = np.random.default_rng(seed)
    canvas = np.clip(canvas + rng.normal(0, 0.01, canvas.shape), 0, 1)
    ok, buf = cv2.imencode(".jpg", (canvas * 255 + 0.5).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 92])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def measure_bars(img):
    res = measure_image(img, keep_debug=True, paper_rect_mm=BOARD_RECT)
    comps = res.debug.get("comps") or []
    pts = np.vstack([c["pts_mm"] for c in comps]) if comps else np.zeros((0, 2))
    w = np.concatenate([c["width_mm"] for c in comps]) if comps else np.zeros(0)
    out = {}
    for xc, y0, y1, wt in bars_layout():
        on = (np.abs(pts[:, 0] - xc) < wt / 2 + 1.0) & (pts[:, 1] > y0 + 5) & (pts[:, 1] < y1 - 5)
        cover = on.sum() / ((y1 - y0 - 10) * res.debug["rect"].R) if "rect" in res.debug else 0
        out[wt] = (float(np.median(w[on])) if on.sum() >= 10 else None, float(cover))
    return out


def test_wide_bars_unbiased():
    for ppm, blur in ((6.0, 1.0), (10.0, 1.3)):
        got = measure_bars(render(ppm, blur))
        for wt, (m, cover) in got.items():
            assert m is not None and cover > 0.6, f"{wt} mm bar not measured at {ppm} px/mm (cover {cover:.2f})"
            if wt >= 1.0:   # thinner bars (< 6 photo px) are the deconvolution regime, scored by run_eval.py
                assert abs(m - wt) <= 0.05 + 0.01 * wt, f"{wt} mm bar measured {m:.3f} mm at {ppm} px/mm"


if __name__ == "__main__":
    for ppm, blur in ((6.0, 1.0), (10.0, 1.3), (4.0, 0.8)):
        got = measure_bars(render(ppm, blur))
        print(f"{ppm} px/mm, blur {blur} px: " + "  ".join(f"{wt}->{'-' if m is None else f'{m:.3f}'} ({c:.2f})" for wt, (m, c) in got.items()))
    test_wide_bars_unbiased()
    print("ok")

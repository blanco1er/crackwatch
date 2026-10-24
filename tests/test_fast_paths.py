"""The vectorised measurement paths give the same numbers as the plain per-point / per-pixel versions.
Run: python tests/test_fast_paths.py   (or pytest)"""
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch import measure as M  # noqa: E402

rng = np.random.default_rng(0)


def _thin_reference(mask):
    img = np.pad(mask.astype(np.uint8), 1)
    while True:
        changed = False
        for step in (0, 1):
            P = img
            p2, p3, p4, p5 = P[:-2, 1:-1], P[:-2, 2:], P[1:-1, 2:], P[2:, 2:]
            p6, p7, p8, p9 = P[2:, 1:-1], P[2:, :-2], P[1:-1, :-2], P[:-2, :-2]
            nb = [p2, p3, p4, p5, p6, p7, p8, p9]
            B = sum(n.astype(np.int16) for n in nb)
            A = sum(((nb[i] == 0) & (nb[(i + 1) % 8] == 1)).astype(np.int16) for i in range(8))
            c = ((p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)) if step == 0 else ((p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0))
            rm = (P[1:-1, 1:-1] == 1) & (B >= 2) & (B <= 6) & (A == 1) & c
            if rm.any():
                img[1:-1, 1:-1][rm] = 0
                changed = True
        if not changed:
            return img[1:-1, 1:-1] > 0


def test_thin_identical():
    if hasattr(cv2, "ximgproc"):
        return
    for _ in range(25):
        m = cv2.GaussianBlur(rng.random((90, 130)).astype(np.float32), (0, 0), rng.uniform(1, 4)) > rng.uniform(0.4, 0.6)
        assert np.array_equal(M.thin(m), _thin_reference(m))


def test_local_median_identical():
    for _ in range(10):
        n = int(rng.integers(5, 1500))
        pts = np.cumsum(rng.normal(0, 0.3, (n, 2)), 0)
        vals = rng.random(n)
        for r in (2.0, 3.0):
            d2 = ((pts[:, None] - pts[None]) ** 2).sum(-1)
            ref = np.nanmedian(np.where(d2 <= r * r, vals[None], np.nan), axis=1)
            assert np.array_equal(M._local_median(pts, vals, r), ref)


def test_half_max_batch_identical():
    t = np.arange(-40, 40 + 1e-9, 0.25, dtype=np.float32)
    for _ in range(200):
        w, c0 = rng.uniform(0.5, 20), rng.uniform(-3, 3)
        d = (np.exp(-((t - c0) / w) ** 2) * rng.uniform(0.05, 1) + rng.normal(0, 0.02, len(t))).astype(np.float32)
        m = int(np.argmax(d))
        ref = M._half_max_edges(d, m, d[m], t, 0.25)
        tl, tr, ok = M._half_max_edges_batch(d[None], np.array([m]), np.array([d[m]], np.float32), t, 0.25)
        assert bool(ok[0]) == (ref is not None)
        if ref is not None:
            assert (tl[0], tr[0]) == ref


if __name__ == "__main__":
    test_thin_identical()
    test_local_median_identical()
    test_half_max_batch_identical()
    print("fast-path tests passed")

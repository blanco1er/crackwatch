"""Generate the synthetic E1 (single photos) and E4 (two-visit pairs) datasets.

usage: python scripts/make_synth.py --out data/synth --n 300 --pairs 40
"""
import argparse
import os
import sys
from multiprocessing import Pool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch.synth import generate_pair, generate_sample  # noqa: E402

WIDEN = (0.0, 0.0, 0.1, 0.2, 0.3, 0.5, 1.0)
EXTEND = (0.0, 0.0, 8.0, 15.0)


def _e1(args):
    seed, out = args
    gt = generate_sample(seed, out)
    return seed, gt is not None


def _e4(args):
    seed, out = args
    widen = WIDEN[seed % len(WIDEN)]
    extend = EXTEND[(seed // len(WIDEN)) % len(EXTEND)]
    move = (seed % 3) == 0
    res = generate_pair(seed, out, widen, extend, move)
    return seed, res is not None


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/synth")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--pairs", type=int, default=40)
    ap.add_argument("--seed0", type=int, default=1000)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    e1 = os.path.join(a.out, "e1")
    e4 = os.path.join(a.out, "e4")
    os.makedirs(e1, exist_ok=True)
    os.makedirs(e4, exist_ok=True)
    with Pool(a.workers) as pool:
        r1 = pool.map(_e1, [(a.seed0 + i, e1) for i in range(a.n)])
        r4 = pool.map(_e4, [(a.seed0 + 50000 + i, e4) for i in range(a.pairs)])
    print(f"E1: {sum(ok for _, ok in r1)}/{a.n} images, E4: {sum(ok for _, ok in r4)}/{a.pairs} pairs -> {a.out}")

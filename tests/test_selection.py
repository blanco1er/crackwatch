"""Main-crack selection (crackwatch/selection.py) on board-frame candidates, no image needed.
Scene modelled on the owner's wall: an A6 card glued ON a wandering crack (pieces above and below the card),
a straight mortar joint touching the card's side, a small dark blob next to the card and a long wall edge.
Run: python tests/test_selection.py   (or pytest)"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch.card import CARD_A6  # noqa: E402
from crackwatch.selection import centreline_wander_mm, link_across_card, score_candidate  # noqa: E402

PAPER = CARD_A6.paper_rect_in_board_frame()     # (-15, -15, 90, 133)
rng = np.random.default_rng(3)


def comp(pts, depth):
    pts = np.asarray(pts, float)
    L = float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))
    return {"pts_mm": pts, "length_mm": L, "depth_ref": depth}


def wander(y0, y1, x0, amp, n=400):
    y = np.linspace(y0, y1, n)
    x = x0 + amp * np.sin(y / 9.0) + np.cumsum(rng.normal(0, 0.15, n))
    return np.column_stack([x, y])


CRACK_UP = comp(wander(-21, -90, 28, 3.0), 0.85)           # crack above the card (board y < -15)
CRACK_DN = comp(wander(139, 230, 30, 3.0), 0.85)           # ... continues below it
JOINT = comp(np.column_stack([np.linspace(96, 180, 300), 18 + rng.normal(0, 0.1, 300)]), 0.55)   # straight mortar joint
BLOB = comp(np.column_stack([np.linspace(-22, -30, 30), np.linspace(40, 44, 30)]), 0.6)          # short dark blob
EDGE = comp(np.column_stack([-36 + rng.normal(0, 0.1, 600), np.linspace(-70, 230, 600)]), 0.45)  # straight wall edge


def test_wander():
    assert centreline_wander_mm(JOINT["pts_mm"])[0] < 1.0
    assert centreline_wander_mm(CRACK_UP["pts_mm"])[0] > 1.0


def test_link_across_card():
    groups = link_across_card([CRACK_UP, CRACK_DN, JOINT, BLOB, EDGE], PAPER)
    assert sorted(map(sorted, groups)) == [[0, 1], [2], [3], [4]], groups


def test_crack_beats_distractors():
    crack = {"pts_mm": np.vstack([CRACK_UP["pts_mm"], CRACK_DN["pts_mm"]]),
             "length_mm": CRACK_UP["length_mm"] + CRACK_DN["length_mm"], "depth_ref": 0.85}
    s_crack = score_candidate(crack, PAPER)[0]
    for name, c in (("joint", JOINT), ("blob", BLOB), ("edge", EDGE), ("one fragment", CRACK_UP)):
        s, ev = score_candidate(c, PAPER)
        assert s_crack > s, f"{name} scored {s:.1f} >= crack {s_crack:.1f} ({ev})"
    assert score_candidate(JOINT, PAPER)[1]["straight"] and score_candidate(EDGE, PAPER)[1]["straight"]


def test_far_candidate_loses_to_near():
    far = comp(wander(-300, -200, 300, 3.0), 0.85)            # same crack-like ridge, 20 cm from the card
    assert score_candidate(CRACK_UP, PAPER)[0] > score_candidate(far, PAPER)[0]


if __name__ == "__main__":
    test_wander()
    test_link_across_card()
    test_crack_beats_distractors()
    test_far_candidate_loses_to_near()
    print("selection tests passed")

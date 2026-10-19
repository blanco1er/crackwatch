"""CrackWatch command line.

  python scripts/cw.py cards [--out print]                 printable ChArUco cards + test charts
  python scripts/cw.py measure photo.jpg [--overlay o.png]  measure one photo -> JSON
  python scripts/cw.py compare v1.jpg v2.jpg                two inspections -> change JSON
  python scripts/cw.py agent photo.jpg [--previous v1.jpg]  run the decision layer (rules) with a trace
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch.agent import AgentState, RulePlanner, run_agent  # noqa: E402
from crackwatch.card import export_all  # noqa: E402
from crackwatch.change import compare  # noqa: E402
from crackwatch.measure import apply_h, measure_image  # noqa: E402


def overlay(bgr, res, path):
    out = bgr.copy()
    if res.status not in ("ok", "no_crack_found"):
        cv2.putText(out, res.status, (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)
        cv2.imwrite(path, out)
        return
    H = res.debug["card"].H_img_from_board
    for p in res.debug["card"].img_pts:
        cv2.circle(out, (int(p[0]), int(p[1])), 4, (255, 160, 0), -1)
    for c, cr in zip(res.debug["comps"], res.cracks or [None] * len(res.debug["comps"])):
        img_pts = apply_h(H, c["pts_mm"])
        w = c.get("width_smooth_mm", c["width_mm"])
        wmax = max(1e-6, np.percentile(w, 98))
        for (x, y), wi in zip(img_pts, w):
            t = float(np.clip(wi / wmax, 0, 1))
            cv2.circle(out, (int(x), int(y)), 2, (0, int(255 * (1 - t)), int(255 * t)), -1)
    for cr in res.cracks:
        x, y = apply_h(H, [cr["max_location_board_mm"]])[0]
        label = f"max {cr['width_mm']['max']:.2f}+/-{cr['uncertainty_mm']:.2f} mm"
        cv2.putText(out, label, (int(x) + 10, int(y)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 5)
        cv2.putText(out, label, (int(x) + 10, int(y)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
    cv2.imwrite(path, out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("cards")
    s.add_argument("--out", default="print")
    s = sub.add_parser("measure")
    s.add_argument("image")
    s.add_argument("--overlay")
    s = sub.add_parser("compare")
    s.add_argument("v1")
    s.add_argument("v2")
    s = sub.add_parser("agent")
    s.add_argument("image")
    s.add_argument("--previous")
    a = ap.parse_args()

    if a.cmd == "cards":
        for p in export_all(a.out):
            print(p)
    elif a.cmd == "measure":
        img = cv2.imread(a.image)
        res = measure_image(img, keep_debug=bool(a.overlay))
        if a.overlay:
            overlay(img, res, a.overlay)
        print(json.dumps(res.to_json(), indent=1))
    elif a.cmd == "compare":
        r1 = measure_image(cv2.imread(a.v1), keep_debug=True)
        r2 = measure_image(cv2.imread(a.v2), keep_debug=True)
        print(json.dumps(compare(r1, r2), indent=1))
    elif a.cmd == "agent":
        res = measure_image(cv2.imread(a.image), keep_debug=True)
        prev = measure_image(cv2.imread(a.previous), keep_debug=True) if a.previous else None
        state = AgentState("current", previous_inspection_id="previous" if prev else None)

        def do_compare(args, st):
            st.comparison = compare(prev, res)
            print("# comparison:", json.dumps({k: v for k, v in st.comparison.items() if k != "T_board1_from_board2"}))
            return res.to_json()

        def wait_for_inspector(args, st):
            print("# waiting for the inspector:", json.dumps(args))
            return None

        tools = {"compare_with_previous": do_compare, "request_retake": wait_for_inspector,
                 "request_closer_photo": wait_for_inspector}
        run_agent(res.to_json(), state, tools, RulePlanner())
        if state.ticket:
            print("# ticket pending human approval:", json.dumps(state.ticket))


if __name__ == "__main__":
    main()

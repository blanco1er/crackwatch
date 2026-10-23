"""E5 (start): scripted scenarios for the decision layer. Run: python tests/test_agent.py"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch.agent import AgentState, BedrockPlanner, decide_next_action, run_agent  # noqa: E402

Q = {"saturated_frac": 0.0, "blur_sigma_px": 1.0, "tilt_deg_est": 20, "card_px_per_mm": 6.0, "card_corners": 24}


def crack(w_max=0.6, w_med=0.5, unc=0.05, conf=0.8, ppm=6.0, depth="resolved"):
    return {"length_mm": 50, "width_mm": {"median": w_med, "mean": w_med, "p90": w_max, "max": w_max},
            "uncertainty_mm": unc, "confidence": conf, "native_px_per_mm": ppm, "depth_source": depth,
            "max_location_board_mm": [120, 40], "focus_region_board_mm": [110, 30, 130, 60]}


def obs(status="ok", q=None, cracks=None):
    return {"status": status, "quality": dict(Q, **(q or {})), "cracks": cracks if cracks is not None else [crack()]}


CMP_GROW = {"status": "ok", "width_delta_mm": {"median": 0.45}, "new_length_mm": 12.0,
            "significant_widening": True, "significant_growth": True}
# one 10 mm stretch widened by 0.5 mm, the rest unchanged: network median ~0, local test significant
CMP_LOCAL = {"status": "ok", "width_delta_mm": {"median": 0.01}, "new_length_mm": 0.0,
             "significant_widening": True, "significant_growth": False, "widening_mm": 0.5,
             "widening_location_board_mm": [120.0, 40.0], "widening_scope": "window"}
CMP_STABLE = {"status": "ok", "width_delta_mm": {"median": 0.01}, "new_length_mm": 0.0,
              "significant_widening": False, "significant_growth": False}

SCENARIOS = [
    ("no card", obs("no_card", cracks=[]), {}, "request_retake"),
    ("glare", obs(q={"saturated_frac": 0.08}), {}, "request_retake"),
    ("blurred", obs(q={"blur_sigma_px": 3.1}), {}, "request_retake"),
    ("too oblique", obs(q={"tilt_deg_est": 65}), {}, "request_retake"),
    ("retake budget used, still blurred", obs(q={"blur_sigma_px": 3.1}), {"retakes": 2}, "schedule_next_visit"),
    ("20 deg across the crack, rule off", obs(cracks=[dict(crack(), view_angle_across_deg=20.0)]), {}, "schedule_next_visit"),
    ("thin crack below resolution", obs(cracks=[crack(0.25, 0.2, ppm=4.0)]), {}, "request_closer_photo"),
    ("prior-based depth", obs(cracks=[crack(depth="prior")]), {}, "request_closer_photo"),
    ("no crack, far photo", obs("no_crack_found", q={"card_px_per_mm": 3.0}, cracks=[]), {}, "request_closer_photo"),
    ("no crack, close photo", obs("no_crack_found", cracks=[]), {}, "schedule_next_visit"),
    ("history -> compare", obs(), {"previous_inspection_id": "insp-001"}, "compare_with_previous"),
    ("fine & stable", obs(), {"previous_inspection_id": "insp-001", "compared": True, "comparison": CMP_STABLE}, "schedule_next_visit"),
    ("growth -> ticket", obs(), {"previous_inspection_id": "insp-001", "compared": True, "comparison": CMP_GROW}, "propose_ticket"),
    ("local widening -> ticket", obs(), {"previous_inspection_id": "insp-001", "compared": True, "comparison": CMP_LOCAL}, "propose_ticket"),
    ("wide crack -> ticket", obs(cracks=[crack(2.6, 2.0)]), {}, "propose_ticket"),
    ("near threshold but uncertain", obs(cracks=[crack(1.05, 0.9, unc=0.1)]), {}, "schedule_next_visit"),
    ("step budget", obs(), {"step": 6}, "stop"),
]


def test_scenarios():
    ok = 0
    for name, o, st, expected in SCENARIOS:
        a = decide_next_action(o, AgentState("insp-002", **st))
        good = a.name == expected
        ok += good
        print(f"{'OK ' if good else 'BAD'} {name:38s} -> {a.name:22s} ({a.reason})")
        if a.name == "propose_ticket":
            assert a.requires_human_approval
    print(f"{ok}/{len(SCENARIOS)} scenarios")
    assert ok == len(SCENARIOS)


def test_view_angle_rule():
    from crackwatch.agent import Policy
    pol = Policy(max_view_angle_across_deg=10.0)
    assert decide_next_action(obs(cracks=[dict(crack(), view_angle_across_deg=20.0)]), AgentState("i"), pol).name == "request_retake"
    assert decide_next_action(obs(cracks=[dict(crack(), view_angle_across_deg=6.0)]), AgentState("i"), pol).name == "schedule_next_visit"


def test_loop_trace():
    # closer photo -> resolved -> compare -> growth -> ticket pending approval
    seq = iter([obs(), obs()])
    state = AgentState("insp-002", previous_inspection_id="insp-001")

    def closer(args, s):
        return next(seq)

    def compare(args, s):
        s.comparison = CMP_GROW
        return obs()

    tr = run_agent(obs(cracks=[crack(0.25, 0.2, ppm=4.0)]), state,
                   {"request_closer_photo": closer, "compare_with_previous": compare}, log=lambda *_: None)
    names = [t["action"]["name"] for t in tr]
    print("trace:", names)
    assert names == ["request_closer_photo", "compare_with_previous", "propose_ticket"]
    assert state.ticket["status"] == "pending_human_approval"


def test_bedrock_request_shape():
    req = BedrockPlanner().build_request(obs(), AgentState("insp-002"))
    assert req["model"].startswith("anthropic.") and req["tool_choice"] == {"type": "auto"}
    assert all(t["strict"] for t in req["tools"])
    a = BedrockPlanner().next_action(obs(), AgentState("insp-002"))   # no client -> rules
    assert a.planner.startswith("rules")


if __name__ == "__main__":
    test_scenarios()
    test_view_angle_rule()
    test_loop_trace()
    test_bedrock_request_shape()
    print("all agent tests passed")

"""The model may only choose an action whose measured precondition holds. Replays two real follow-ups (recorded
observations, tests/fixtures) with a fake Nova that always asks for a closer photo, as seen live on 24 Oct 2026:
the rules decide instead, the comparison is never skipped, and the trace says the model was overridden.
Run: python tests/test_agent_guard.py   (or pytest)"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from crackwatch.agent import AgentState, NovaConversePlanner, decide_next_action, run_agent  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


class FakeNova:
    """Bedrock Converse stand-in that always answers with the same tool call."""
    def __init__(self, name, args):
        self.name, self.args, self.calls = name, args, 0

    def converse(self, **req):
        self.calls += 1
        return {"output": {"message": {"content": [{"text": "closer"}, {"toolUse": {"name": self.name, "input": self.args}}]}},
                "stopReason": "tool_use", "usage": {"inputTokens": 900, "outputTokens": 40}}


def replay(fixture, tool="request_closer_photo", args=None):
    f = json.load(open(os.path.join(FIX, fixture)))
    obs, cmp = f["observation_v2"], f["comparison"]
    nova = FakeNova(tool, args or {"zoom_factor": 3.0})
    planner = NovaConversePlanner(client=nova)
    state = AgentState("insp", previous_inspection_id="previous-visit")

    def compare(_args, st):
        st.comparison = cmp
        return obs
    trace = run_agent(obs, state, {"compare_with_previous": compare}, planner, log=lambda *_: None)
    return trace, state, nova


def test_closer_photo_rejected_on_real_followups():
    for fx in ("followup_1654_1656.json", "followup_1639_1640.json"):
        trace, state, nova = replay(fx)
        names = [t["action"]["name"] for t in trace]
        assert names == ["compare_with_previous", "propose_ticket"], (fx, names)   # = the rules (wide crack, stable)
        assert state.compared and state.comparison["status"] == "ok"
        assert nova.calls == 2
        for t in trace:
            a = t["action"]
            assert "overridden" in a["planner"] and a["meta"]["llm_proposed"] == "request_closer_photo", a
            assert a["meta"]["agrees_with_rules"] is False


def test_rule_closer_photo_carries_its_reason():
    f = json.load(open(os.path.join(FIX, "followup_1639_1640.json")))
    obs = json.loads(json.dumps(f["observation_v2"]))
    c = obs["cracks"][0]
    c["width_mm"]["median"] = 0.3
    c["native_px_per_mm"] = 6.0                     # 1.8 px across: really too thin at this distance
    a = decide_next_action(obs, AgentState("i"))
    assert a.name == "request_closer_photo" and a.args["why"] == "thin"
    obs = json.loads(json.dumps(f["observation_v2"]))
    obs["cracks"][0]["confidence"] = 0.3            # wide and resolved, but the measurement is not trusted
    a = decide_next_action(obs, AgentState("i"))
    assert a.name == "request_closer_photo" and a.args["why"] == "confidence"


def test_agreeing_model_is_kept():
    trace, state, _ = replay("followup_1639_1640.json", tool="compare_with_previous", args={})
    assert trace[0]["action"]["name"] == "compare_with_previous" and trace[0]["action"]["meta"]["agrees_with_rules"] is True


if __name__ == "__main__":
    test_closer_photo_rejected_on_real_followups()
    test_rule_closer_photo_carries_its_reason()
    test_agreeing_model_is_kept()
    print("agent guard tests passed")

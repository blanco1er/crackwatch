"""Fast tests of the hosted-demo layer (no image processing, no AWS): routes, cost guards, anonymous
visits, owner report, Nova planner fallback and guard-rails. Run: python tests/test_api.py"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["CW_VISIT_SECRET"] = "test-secret-for-unit-tests-only-0000"
from crackwatch import api, visits  # noqa: E402
from crackwatch.agent import AgentState, NovaConversePlanner  # noqa: E402
from crackwatch.store import MemStore  # noqa: E402
from scripts.visits_report import summarize  # noqa: E402

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile Safari/604.1"


class FakeBlobs:
    def presign_post(self, key, max_bytes):
        return {"url": "https://example-bucket.s3.amazonaws.com/", "fields": {"key": key}}

    def get(self, key):
        raise KeyError(key)


def app():
    return api.App(MemStore(), FakeBlobs(), log=lambda *_: None)


def test_static_and_health():
    a = app()
    r = a.handle("GET", "/", {}, b"", {}, "1.1.1.1")
    assert r.status == 200 and b"CrackWatch" in r.body and "content-security-policy" in r.headers
    assert a.handle("GET", "/samples/close.jpg", {}, b"", {}, "1").status == 200
    assert a.handle("GET", "/samples/../api.py", {}, b"", {}, "1").status == 404
    assert a.handle("GET", "/card.pdf", {}, b"", {}, "1").body[:4] == b"%PDF"
    h = json.loads(a.handle("GET", "/api/health", {}, b"", {}, "1").body)
    assert h["opencv"].startswith("5.") and h["limits"]["llm_calls_per_day"] > 0


def test_upload_key_and_bad_refs():
    a = app()
    up = json.loads(a.handle("POST", "/api/upload-url", {}, b"{}", {}, "1").body)
    assert api.KEY_RE.fullmatch(up["key"])
    for ref in ({"key": "../secret"}, {"sample": "nope"}, "x"):
        r = a.handle("POST", "/api/inspect", {"user-agent": UA}, json.dumps({"image": ref}).encode(), {}, "1")
        assert r.status == 400, r.body
    r = a.handle("POST", "/api/inspect", {"user-agent": UA}, json.dumps({"image": {"key": up["key"]}}).encode(), {}, "1")
    assert r.status == 400 and json.loads(r.body)["error"] == "image_unavailable"


def test_daily_limits():
    a = app()
    old = dict(api.LIMITS)
    api.LIMITS.update(inspections_per_visitor_day=2)
    try:
        codes = [a.handle("POST", "/api/inspect", {"user-agent": UA}, b'{"image":{"sample":"nope"}}', {}, "9.9.9.9").status for _ in range(3)]
        assert codes == [400, 400, 429], codes
        assert a.handle("POST", "/api/inspect", {"user-agent": UA}, b'{"image":{"sample":"nope"}}', {}, "8.8.8.8").status == 400
    finally:
        api.LIMITS.update(old)


def test_ticket_decision_once():
    a = app()
    a.store.put("TICKET#abcdef0123", "META", {"status": "pending_human_approval", "ticket": {}})
    r = json.loads(a.handle("POST", "/api/tickets/abcdef0123/decision", {}, b'{"decision":"approve"}', {}, "1").body)
    assert r["status"] == "approved"
    r = json.loads(a.handle("POST", "/api/tickets/abcdef0123/decision", {}, b'{"decision":"reject"}', {}, "1").body)
    assert r["status"] == "approved" and r["already_decided"]
    assert a.handle("POST", "/api/tickets/abcdef0123/decision", {}, b'{"decision":"maybe"}', {}, "1").status == 400


def test_visits_anonymous_and_internal():
    st = MemStore()
    assert visits.log_visit(st, {"user-agent": UA, "referer": "https://devpost.com/x"}, "203.0.113.7", {"type": "view", "lang": "en"})
    row = next(iter(st.items.values()))
    blob = json.dumps(row)
    assert "203.0.113.7" not in blob and row["os"] == "iOS" and row["ref"] == "devpost.com" and len(row["visitor"]) == 16
    assert not visits.log_visit(st, {"user-agent": UA, "x-crackwatch-visit": "internal"}, "1", {"type": "view"})
    assert not visits.log_visit(st, {"user-agent": UA, "cookie": f"a=b; cw_internal={visits.internal_key()}"}, "1", {"type": "view"})
    assert not visits.log_visit(st, {"user-agent": UA}, "1", {"type": "made-up"})
    visits.log_visit(st, {"user-agent": UA}, "1", {"type": "inspect", "detail": "mail me at a.b@example.com or +33 6 12 34 56 78"})
    assert "example.com" not in json.dumps(list(st.items.values())) and "56 78" not in json.dumps(list(st.items.values()))
    a = app()
    r = a.handle("GET", "/internal", {}, b"", {"k": visits.internal_key()}, "1")
    assert r.status == 302 and "cw_internal=" in r.headers["set-cookie"]
    assert a.handle("GET", "/internal", {}, b"", {"k": "wrong"}, "1").status == 404


def test_owner_report_french():
    st = MemStore()
    for t, extra in (("view", {}), ("inspect", {"sample": "blurry", "action": "request_retake", "planner": "us.amazon.nova-2-lite-v1:0"}),
                     ("ticket", {"action": "approved"})):
        visits.log_visit(st, {"user-agent": UA}, "203.0.113.7", dict(type=t, **extra))
    rows = [v for (pk, _), v in st.items.items() if pk.startswith("VISIT#")]
    txt = summarize(rows, {"2026-10-21": {"inspections": 3, "llm_calls": 4}}, "2026-10-21", "2026-10-21")
    assert "Visiteurs uniques : 1" in txt and "ticket validé : 1" in txt and "Nova 2 Lite 1" in txt and "appel(s) Nova 2 Lite" in txt


class FakeBedrock:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc, self.calls = resp, exc, 0

    def converse(self, **req):
        self.calls += 1
        assert req["toolConfig"]["toolChoice"] == {"auto": {}} and len(req["toolConfig"]["tools"]) == 5
        assert "H_img_from_board" not in json.dumps(req)     # compact observation only
        if self.exc:
            raise self.exc
        return self.resp


def obs_blurred():
    return {"status": "ok", "quality": {"blur_sigma_px": 3.1, "saturated_frac": 0, "tilt_deg_est": 10, "card_px_per_mm": 6, "card_corners": 24},
            "card": {"spec": "A6", "corners": 24, "reproj_rms_px": 0.1, "H_img_from_board": [[1, 0, 0], [0, 1, 0], [0, 0, 1]]}, "cracks": []}


def tool_resp(name, args, text="Blur 3.1 px exceeds 2.2 px."):
    return {"stopReason": "tool_use", "usage": {"inputTokens": 1500, "outputTokens": 80},
            "output": {"message": {"content": [{"text": text}, {"toolUse": {"toolUseId": "t1", "name": name, "input": args}}]}}}


def test_nova_planner_paths():
    # agrees with the rules
    p = NovaConversePlanner(client=FakeBedrock(tool_resp("request_retake", {"reason": "blur", "instruction": "Hold the phone still."})))
    a = p.next_action(obs_blurred(), AgentState("i"))
    assert a.name == "request_retake" and a.planner.startswith("us.amazon.nova") and a.meta["agrees_with_rules"] and a.meta["cost_usd"] > 0
    # LLM tries to compare on an unusable photo -> overridden by the rules
    p = NovaConversePlanner(client=FakeBedrock(tool_resp("compare_with_previous", {"previous_id": "x"})))
    a = p.next_action(obs_blurred(), AgentState("i", previous_inspection_id="p"))
    assert a.name == "request_retake" and "overridden" in a.planner
    # error -> rules, visible in the trace
    p = NovaConversePlanner(client=FakeBedrock(exc=TimeoutError("slow")))
    a = p.next_action(obs_blurred(), AgentState("i"))
    assert a.name == "request_retake" and a.planner == "rules (LLM error: TimeoutError)"
    # daily budget exhausted -> no call at all
    fb = FakeBedrock(tool_resp("request_retake", {"reason": "blur", "instruction": "x"}))
    a = NovaConversePlanner(client=fb, allow_call=lambda: False).next_action(obs_blurred(), AgentState("i"))
    assert fb.calls == 0 and "budget" in a.planner


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
    print("all api tests passed")

"""CrackWatch decision layer ("agentic vision").

The OpenCV outputs (quality, scale, width + uncertainty, change) decide the next action:

    request_retake(reason, instruction)          photo unusable (no card, blur, glare)
    request_closer_photo(region, zoom_factor)    active perception: width below resolution
    compare_with_previous(previous_id)           history exists and not compared yet
    propose_ticket(severity, evidence)           threshold exceeded -> ALWAYS human approval
    schedule_next_visit(days)                    nothing alarming
    stop(reason)                                 budget exhausted -> hand over to a human

`decide_next_action` is a pure function (deterministic policy, also the fallback when
the LLM is unavailable). `NovaConversePlanner` is the deployed planner: Amazon Nova 2 Lite on
Amazon Bedrock through the Converse API, validated by the rules. `BedrockPlanner` is the same
idea for Claude through the Anthropic Messages API on Bedrock (kept for when the Anthropic
use-case form is filled; not deployed).
Thresholds are configurable triage defaults, NOT engineering norms: they must be set by
a qualified structural engineer for each building.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Protocol

ACTIONS = ("request_retake", "request_closer_photo", "compare_with_previous",
           "propose_ticket", "schedule_next_visit", "stop")


@dataclass
class Policy:
    max_steps: int = 6
    max_retakes: int = 2
    max_blur_px: float = 2.2               # card-edge blur sigma (photo px)
    max_saturated_frac: float = 0.03
    max_tilt_deg: float = 55.0
    # Seen at an angle across it, a crack's near lip hides part of its dark interior: the apparent width
    # loses ~ depth x tan(angle) (a crack looks dark where it is at least about as deep as wide, so 10 deg
    # already hides ~18 %). On the owner's real cracks the width drops by 20-30 % from <= 7 deg to 13-22 deg.
    # OFF by default: the threshold has not been validated on photos other than those it was seen on, and
    # the synthetic demo photos (flat cracks, no depth) are taken at 13-21 deg. Set e.g. 10.0 to enforce.
    max_view_angle_across_deg: float | None = None
    min_confidence: float = 0.5
    min_px_across_crack: float = 3.0       # want >= 3 photo px across the median width
    ticket_width_mm: float = 1.0           # indicative triage threshold (configurable)
    urgent_width_mm: float = 2.0
    ticket_growth_mm: float = 0.2          # widening between visits
    ticket_new_length_mm: float = 5.0


@dataclass
class AgentState:
    inspection_id: str
    previous_inspection_id: str | None = None
    step: int = 0
    retakes: int = 0
    compared: bool = False
    comparison: dict | None = None
    ticket: dict | None = None


@dataclass
class Action:
    name: str
    args: dict = field(default_factory=dict)
    reason: str = ""
    requires_human_approval: bool = False
    planner: str = "rules"
    meta: dict = field(default_factory=dict)   # LLM usage, latency, agreement with the rule policy

    def to_json(self):
        return asdict(self)


def _main_crack(obs):
    cr = obs.get("cracks") or []
    return max(cr, key=lambda c: c["length_mm"]) if cr else None


def decide_next_action(obs: dict, state: AgentState, policy: Policy = Policy()) -> Action:
    """Pure policy: CV observation (MeasureResult.to_json()) + state -> next action."""
    q = obs.get("quality", {})
    if state.step >= policy.max_steps:
        return Action("stop", {"handover": "human"}, "step budget exhausted")
    can_retake = state.retakes < policy.max_retakes

    # 1. photo usability
    if obs.get("status") in ("no_card", "reference_rejected"):
        if can_retake and q.get("retake_reason"):        # wallet card (idcard.py): its own reason + instruction
            args = {"reason": q["retake_reason"], "instruction": q.get("retake_instruction", "")}
            if q.get("card_occluded_edge"):
                args["edge"] = q["card_occluded_edge"]
            if q.get("card_occluded_corners"):
                args["corner"] = q["card_occluded_corners"][0]
            return Action("request_retake", args, q.get("retake_detail") or q["retake_reason"])
        if can_retake:
            return Action("request_retake", {"reason": "card_not_found",
                                             "instruction": "Frame the whole ChArUco card and the crack; avoid reflections on the card."},
                          "no ChArUco card detected -> no metric scale")
        return Action("stop", {"handover": "human"}, "card never detected")
    if q.get("saturated_frac", 0) > policy.max_saturated_frac and can_retake:
        return Action("request_retake", {"reason": "glare", "instruction": "Turn off the flash or step sideways to remove the glare."},
                      f"{100 * q['saturated_frac']:.1f}% saturated pixels")
    if q.get("blur_sigma_px", 0) > policy.max_blur_px and can_retake:
        return Action("request_retake", {"reason": "blur", "instruction": "Hold still, tap to focus on the crack, use more light."},
                      f"edge blur sigma {q['blur_sigma_px']:.2f} px > {policy.max_blur_px}")
    if q.get("tilt_deg_est", 0) > policy.max_tilt_deg and can_retake:
        return Action("request_retake", {"reason": "oblique", "instruction": "Face the wall more directly."},
                      f"estimated tilt {q['tilt_deg_est']:.0f} deg")

    crack = _main_crack(obs)
    if crack is None:
        ppm = q.get("card_px_per_mm", 0)
        if ppm and ppm < 5 and can_retake:
            return Action("request_closer_photo", {"region_board_mm": None, "zoom_factor": round(6.0 / ppm, 1), "why": "far"},
                          f"no crack found at {ppm:.1f} px/mm; fine cracks may be invisible at this distance")
        return Action("schedule_next_visit", {"days": 90}, "no crack detected (visual check by a human recommended)")

    va = crack.get("view_angle_across_deg")
    if va is not None and policy.max_view_angle_across_deg is not None and va > policy.max_view_angle_across_deg and can_retake:
        return Action("request_retake", {"reason": "oblique_across_crack",
                                         "instruction": "Stand square to the crack: step sideways until the phone faces it straight on."},
                      f"seen {va:.0f} deg across the crack (> {policy.max_view_angle_across_deg:.0f}): its lip hides part of the width")

    # 2. active perception: is the width actually resolved?
    w_med = crack["width_mm"]["median"]
    px_across = w_med * crack["native_px_per_mm"]
    unresolved = px_across < policy.min_px_across_crack or crack["depth_source"] == "prior" \
        or crack["confidence"] < policy.min_confidence
    if unresolved and can_retake:
        need_ppm = policy.min_px_across_crack / max(w_med, 0.05)
        zoom = max(1.5, min(4.0, need_ppm / max(crack["native_px_per_mm"], 0.1)))
        why = "thin" if px_across < policy.min_px_across_crack else "depth" if crack["depth_source"] == "prior" else "confidence"
        return Action("request_closer_photo",
                      {"region_board_mm": crack["focus_region_board_mm"], "zoom_factor": round(zoom, 1), "why": why,
                       "instruction": f"Move about {zoom:.1f}x closer to the highlighted part of the crack, card still visible."},
                      f"median width {w_med:.2f} mm spans only {px_across:.1f} px (confidence {crack['confidence']}, depth {crack['depth_source']})")

    # 3. history
    if state.previous_inspection_id and not state.compared:
        return Action("compare_with_previous", {"previous_id": state.previous_inspection_id},
                      "previous inspection on record")

    # 4. thresholds -> ticket (human approval mandatory)
    evidence = {"max_width_mm": crack["width_mm"]["max"], "uncertainty_mm": crack["uncertainty_mm"],
                "location_board_mm": crack["max_location_board_mm"]}
    sev = None
    w_low = crack["width_mm"]["max"] - 2 * crack["uncertainty_mm"]   # conservative bound
    if w_low >= policy.urgent_width_mm:
        sev = "high"
    elif w_low >= policy.ticket_width_mm:
        sev = "medium"
    cmp = state.comparison or {}
    if cmp.get("status") == "ok":
        evidence.update({"width_delta_median_mm": cmp["width_delta_mm"]["median"], "new_length_mm": cmp["new_length_mm"]})
        # largest statistically significant widening (whole crack or one ~10 mm stretch of it)
        widen = cmp.get("widening_mm")
        if widen is None:
            widen = cmp["width_delta_mm"]["median"] or 0
        if cmp.get("widening_location_board_mm"):
            evidence.update({"widening_mm": widen, "widening_location_board_mm": cmp["widening_location_board_mm"]})
        grew = (cmp.get("significant_widening") and widen >= policy.ticket_growth_mm) \
            or (cmp.get("significant_growth") and cmp["new_length_mm"] >= policy.ticket_new_length_mm)
        if grew:
            sev = "high" if sev == "high" or (cmp.get("significant_widening") and widen >= 2 * policy.ticket_growth_mm) else "medium"
    if sev and state.ticket is None:
        return Action("propose_ticket", {"severity": sev, "evidence": evidence}, "triage threshold exceeded",
                      requires_human_approval=True)
    days = 30 if crack["width_mm"]["max"] >= policy.ticket_width_mm else (90 if crack["width_mm"]["max"] >= 0.3 else 180)
    return Action("schedule_next_visit", {"days": days}, f"max width {crack['width_mm']['max']:.2f} mm, no alarming change")


# --------------------------------------------------------------------- planners
class Planner(Protocol):
    def next_action(self, obs: dict, state: AgentState) -> Action: ...


class RulePlanner:
    def __init__(self, policy: Policy = Policy()):
        self.policy = policy

    def next_action(self, obs, state):
        return decide_next_action(obs, state, self.policy)


TOOL_SCHEMAS = [
    {"name": "request_retake", "description": "Ask the inspector for a new photo because the current one is unusable.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["reason", "instruction"],
                      "properties": {"reason": {"type": "string", "enum": ["card_not_found", "blur", "glare", "oblique", "card_cut_by_frame",
                                                                     "card_too_small", "card_too_oblique", "card_occluded",
                                                                     "card_not_flat", "card_wrong_size"]},
                                     "instruction": {"type": "string"},
                                     "edge": {"type": "string", "enum": ["left", "right", "top", "bottom"],
                                              "description": "wallet card edge hidden (card_occluded)"},
                                     "corner": {"type": "string", "enum": ["top-left", "top-right", "bottom-left", "bottom-right"],
                                                "description": "wallet card corner hidden (card_occluded)"}}}},
    {"name": "request_closer_photo", "description": "Active perception: ask for a closer photo of a board-frame region (mm) where the width is not resolved.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["region_board_mm", "zoom_factor", "instruction"],
                      "properties": {"region_board_mm": {"type": "array", "items": {"type": "number"}},
                                     "zoom_factor": {"type": "number"}, "instruction": {"type": "string"}}}},
    {"name": "compare_with_previous", "description": "Register this inspection against the previous one and measure the change.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["previous_id"],
                      "properties": {"previous_id": {"type": "string"}}}},
    {"name": "propose_ticket", "description": "Propose a maintenance ticket. It is never sent without a human approval.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["severity", "rationale"],
                      "properties": {"severity": {"type": "string", "enum": ["medium", "high"]}, "rationale": {"type": "string"}}}},
    {"name": "schedule_next_visit", "description": "Plan the next inspection.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["days"],
                      "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 365}}}},
]

SYSTEM_PROMPT = (
    "You orchestrate CrackWatch, a crack-monitoring assistant. You receive measurements produced by an "
    "OpenCV pipeline (metric scale from a ChArUco card, crack width in mm with an uncertainty, image quality, "
    "and optionally a comparison with the previous inspection). Choose exactly one tool call as the next step. "
    "Never invent measurements; only use the numbers given. You are a triage aid, not a structural diagnosis: "
    "tickets always wait for a human approval. Prefer asking for a better photo when the measurement is "
    "unreliable. The deterministic policy's suggestion is provided; explain any deviation."
)


def compact_observation(obs: dict, state: AgentState, max_cracks: int = 3) -> dict:
    """What the LLM sees: the CV numbers that matter for the decision (no homography matrices,
    no rejected-component dump), so a call stays around 1.5-2k input tokens."""
    q = obs.get("quality", {})
    keep_q = ("blur_sigma_px", "saturated_frac", "tilt_deg_est", "card_px_per_mm", "card_corners")
    cracks = []
    for c in (obs.get("cracks") or [])[:max_cracks]:
        cracks.append({k: c.get(k) for k in ("length_mm", "width_mm", "uncertainty_mm", "confidence", "depth_source",
                                             "native_px_per_mm", "min_measurable_mm", "max_location_board_mm",
                                             "focus_region_board_mm")})
    out = {"status": obs.get("status"), "quality": {k: round(q[k], 3) for k in keep_q if k in q},
           "card": {k: (obs.get("card") or {}).get(k) for k in ("spec", "corners", "reproj_rms_px")} if obs.get("card") else None,
           "cracks": cracks, "n_cracks": len(obs.get("cracks") or [])}
    st = {"step": state.step, "retakes_used": state.retakes, "has_previous_inspection": bool(state.previous_inspection_id),
          "already_compared": state.compared, "ticket_open": state.ticket is not None}
    if state.comparison:
        st["comparison"] = {k: v for k, v in state.comparison.items() if k not in ("T_board1_from_board2", "registration")}
        st["comparison"]["registration_mode"] = (state.comparison.get("registration") or {}).get("mode")
    return {"observation": out, "state": st}


@dataclass
class BedrockPlanner:
    """Claude on Amazon Bedrock as the planner, with the rule policy as guard-rail and fallback.

    Intended client (not imported here): `anthropic.AnthropicBedrockMantle(aws_region="us-east-1")`,
    model id "anthropic.claude-opus-5-5" (or "anthropic.claude-haiku-5-5" if the owner picks
    the cheaper model). `client` is injected so tests never touch AWS."""
    client: object | None = None
    model: str = "anthropic.claude-opus-5-5"
    effort: str = "low"
    policy: Policy = field(default_factory=Policy)

    def build_request(self, obs: dict, state: AgentState) -> dict:
        suggestion = decide_next_action(obs, state, self.policy)
        payload = {"observation": obs, "state": asdict(state), "rule_suggestion": suggestion.to_json()}
        tools = [dict(t, strict=True) for t in TOOL_SCHEMAS]
        return {
            "model": self.model,
            "max_tokens": 2000,
            "system": SYSTEM_PROMPT,
            "tools": tools,
            "tool_choice": {"type": "auto"},          # forced tool_choice is rejected on Opus 5.5
            "output_config": {"effort": self.effort},
            "messages": [{"role": "user", "content": json.dumps(payload, sort_keys=True)}],
        }

    def next_action(self, obs, state):
        fallback = decide_next_action(obs, state, self.policy)
        if self.client is None:
            fallback.planner = "rules (no LLM client configured)"
            return fallback
        try:
            resp = self.client.messages.create(**self.build_request(obs, state))
            calls = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
            if resp.stop_reason == "refusal" or not calls:
                raise ValueError(f"no tool call (stop_reason={resp.stop_reason})")
            act = Action(calls[0].name, dict(calls[0].input), "LLM choice", planner=self.model)
            return validate_action(act, fallback)
        except Exception as e:  # deterministic fallback, logged in the trace
            fallback.planner = f"rules (LLM error: {type(e).__name__})"
            return fallback


NOVA_SYSTEM_PROMPT = SYSTEM_PROMPT + (
    " Write the tool arguments for a non-expert inspector holding a phone: short, concrete, in English. "
    "Use region_board_mm and zoom_factor from the rule suggestion when you ask for a closer photo. "
    "Before the tool call, give a one-sentence rationale that cites the numbers you used."
)


@dataclass
class NovaConversePlanner:
    """Amazon Nova 2 Lite (or any Converse tool-use model) on Amazon Bedrock as the planner.

    The rule policy runs first; its suggestion is given to the model, and the model's tool call
    is validated against it (`validate_action`). Any error, refusal, missing tool call or
    exhausted daily budget falls back to the rules, and the trace says so.
    `client` is a boto3 `bedrock-runtime` client (injected: tests use a fake one).
    `allow_call()` is the cost guard (daily cap); it returns False when the budget is used up."""
    client: object | None = None
    model: str = "us.amazon.nova-2-lite-v1:0"
    max_tokens: int = 600
    policy: Policy = field(default_factory=Policy)
    allow_call: Callable[[], bool] = lambda: True
    price_in_per_mtok: float = 0.33     # USD, us-east-1 on-demand, AWS Price List API (19 Oct 2026)
    price_out_per_mtok: float = 2.75

    def build_request(self, obs: dict, state: AgentState) -> dict:
        suggestion = decide_next_action(obs, state, self.policy)
        payload = dict(compact_observation(obs, state), rule_suggestion={k: v for k, v in suggestion.to_json().items()
                                                                         if k in ("name", "args", "reason")})
        tools = [{"toolSpec": {"name": t["name"], "description": t["description"],
                               "inputSchema": {"json": t["input_schema"]}}} for t in TOOL_SCHEMAS]
        return {"modelId": self.model,
                "system": [{"text": NOVA_SYSTEM_PROMPT}],
                "messages": [{"role": "user", "content": [{"text": json.dumps(payload, sort_keys=True, default=str)}]}],
                "toolConfig": {"tools": tools, "toolChoice": {"auto": {}}},
                "inferenceConfig": {"maxTokens": self.max_tokens, "temperature": 0.0}}

    def next_action(self, obs, state):
        rule = decide_next_action(obs, state, self.policy)
        if rule.name == "stop":                       # budget/terminal decisions stay deterministic
            return rule
        if self.client is None:
            rule.planner = "rules (no LLM client configured)"
            return rule
        if not self.allow_call():
            rule.planner = "rules (daily LLM budget reached)"
            return rule
        t0 = time.time()
        try:
            resp = self.client.converse(**self.build_request(obs, state))
            blocks = resp["output"]["message"]["content"]
            calls = [b["toolUse"] for b in blocks if "toolUse" in b]
            text = " ".join(b["text"] for b in blocks if "text" in b).strip()
            usage = resp.get("usage", {})
            meta = {"model": self.model, "latency_ms": round(1000 * (time.time() - t0)),
                    "input_tokens": usage.get("inputTokens"), "output_tokens": usage.get("outputTokens"),
                    "cost_usd": round((usage.get("inputTokens", 0) * self.price_in_per_mtok
                                       + usage.get("outputTokens", 0) * self.price_out_per_mtok) / 1e6, 6),
                    "rationale": text[:400], "rule_suggestion": rule.name}
            if resp.get("stopReason") != "tool_use" or not calls:
                raise ValueError(f"no tool call (stopReason={resp.get('stopReason')})")
            act = Action(calls[0]["name"], dict(calls[0].get("input") or {}), text[:300] or "LLM choice",
                         planner=self.model, meta=meta)
            act = validate_action(act, rule)
            overrode = act is rule                     # the model's choice was rejected: the rules decided
            act.meta = dict(meta, **(act.meta or {})) if overrode else dict(meta)
            act.meta["agrees_with_rules"] = (not overrode) and act.name == rule.name
            return act
        except Exception as e:  # deterministic fallback, visible in the trace
            rule.planner = f"rules (LLM error: {type(e).__name__})"
            rule.meta = {"model": self.model, "error": str(e)[:200], "latency_ms": round(1000 * (time.time() - t0))}
            return rule


PRECONDITION = {   # an action the model may choose only when the measured condition behind it holds
    "request_retake": "the photo is not usable (card, glare, blur, angle)",
    "request_closer_photo": "the crack is not resolved at this distance (too few pixels across, assumed depth or "
                            "low confidence) or no crack was found on a far photo",
    "compare_with_previous": "a previous visit exists and has not been compared yet",
}


def validate_action(act: Action, rule: Action) -> Action:
    """Guard-rails on LLM output: unknown tool -> rules; an action whose measured precondition does not hold ->
    rules (the rule policy evaluates exactly those preconditions: the model may only pick such an action when the
    rules pick it too); a pending comparison with the previous visit is never skipped; a ticket always needs
    approval; a ticket the rules did not justify is downgraded to a human review request."""
    def overridden(why):
        rule.planner = f"rules (LLM proposed {act.name}: {why}; overridden)"
        rule.meta = dict(act.meta or {}, llm_proposed=act.name, override_reason=why)
        return rule
    if act.name not in ACTIONS:
        rule.planner += " (LLM proposed unknown tool)"
        return rule
    if act.name in PRECONDITION and act.name != rule.name:
        return overridden(f"precondition not met ({PRECONDITION[act.name]})")
    if rule.name == "compare_with_previous" and act.name != "compare_with_previous":
        return overridden("the previous visit must be compared first")
    if act.name == "request_closer_photo" and rule.name == "request_closer_photo":
        act.args.setdefault("region_board_mm", rule.args.get("region_board_mm"))
        act.args.setdefault("zoom_factor", rule.args.get("zoom_factor"))
    if act.name == "compare_with_previous":
        act.args = dict(rule.args) if rule.name == "compare_with_previous" else act.args
    if act.name == "schedule_next_visit" and rule.name == "propose_ticket":
        # the model may not silently drop a ticket the measured thresholds justify
        rule.planner = "rules (LLM tried to skip a threshold-justified ticket; overridden)"
        rule.meta = act.meta
        return rule
    if act.name == "propose_ticket":
        act.requires_human_approval = True
        if rule.name == "propose_ticket":
            act.args.setdefault("evidence", rule.args.get("evidence"))
            act.args["rule_severity"] = rule.args.get("severity")
        else:
            act.args["note"] = "not supported by measured thresholds; flagged for human review"
    return act


# --------------------------------------------------------------------- loop + trace
def run_agent(obs: dict, state: AgentState, tools: dict, planner: Planner | None = None, log: Callable = print):
    """Execute planner decisions until a terminal action. `tools[name](args, state)` returns a
    new observation dict (or None for terminal / waiting-for-human actions).
    Returns the trace (list of dicts) that shows how CV outputs changed each decision."""
    planner = planner or RulePlanner()
    trace = []
    while True:
        t0 = time.time()
        act = planner.next_action(obs, state)
        crack = _main_crack(obs)
        trace.append({"step": state.step, "action": act.to_json(), "latency_ms": round(1000 * (time.time() - t0), 1),
                      "cv": {"status": obs.get("status"), "blur_px": obs.get("quality", {}).get("blur_sigma_px"),
                             "max_width_mm": crack["width_mm"]["max"] if crack else None,
                             "uncertainty_mm": crack["uncertainty_mm"] if crack else None,
                             "confidence": crack["confidence"] if crack else None}})
        log(json.dumps(trace[-1]))
        state.step += 1
        if act.name in ("stop", "schedule_next_visit"):
            break
        if act.name == "propose_ticket":
            state.ticket = {"status": "pending_human_approval", **act.args}
            break
        if act.name in ("request_retake", "request_closer_photo"):
            state.retakes += 1
        if act.name == "compare_with_previous":
            state.compared = True
        new_obs = tools[act.name](act.args, state)
        if new_obs is None:          # waiting for the inspector (async in the real app)
            break
        obs = new_obs
    return trace

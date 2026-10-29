import copy
import time
from datetime import datetime, timezone
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph

from .model import DecisionModel
from .schemas import ACTION_ADAPTER, Brief, RunConfig
from .tools import LocalTools


class GraphState(TypedDict):
    context: dict


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def pending(context: dict) -> list[str]:
    items = []
    if context["missing_fields"]:
        items.extend(context["missing_fields"])
    if not context["materials"]:
        items.append("retrieved_materials")
    if not context["script"]:
        items.append("script")
    if not context["duration"] or not context["duration"]["passed"]:
        items.append("passed_duration_check")
    if not context["rule_check"] or not context["rule_check"]["passed"]:
        items.append("passed_rule_check")
    return items


def stop(context: dict, status: str, reason: str) -> None:
    context["status"] = status
    context["stop_reason"] = reason


def execute(action: dict, context: dict, tools: LocalTools) -> dict:
    name = action["action"]
    if name == "request_input":
        context["requested_fields"] = action["fields"]
        stop(context, "needs_input", action["reason"])
        return {"requested_fields": action["fields"]}
    if name == "finish":
        if action["status"] == "completed" and pending(context):
            raise ValueError("completion requires current passing checks")
        stop(context, action["status"], action["reason"])
        return {"status": context["status"]}
    if name == "save_script":
        if context["missing_fields"] or not context["materials"]:
            raise ValueError("script requires complete brief and retrieved materials")
        context["script"] = action["script"]
        context["revision"] += 1
        context["duration"] = None
        context["rule_check"] = None
        return {"revision": context["revision"], "checks_invalidated": True}
    args = {"query": action["query"]} if name == "search_materials" else {
        "script": copy.deepcopy(context["script"]), "revision": context["revision"]}
    if name != "search_materials" and not context["script"]:
        raise ValueError("no current script")
    # Record precisely what tools consume, including evidence for the rule checker.
    if name == "estimate_duration":
        args.update(target_duration_seconds=context["brief"]["target_duration_seconds"],
                    config=context["config"])
    if name == "check_script":
        args.update(materials=copy.deepcopy(context["materials"]), rules=context["rules"])
    context["effective_tool_arguments"] = args
    result = tools.invoke(name, args, context)
    if name == "search_materials":
        old = {m["id"]: m for m in context["materials"]}
        old.update({m["id"]: m for m in result["materials"]})
        context["materials"] = list(old.values())
    elif name == "estimate_duration":
        context["duration"] = result
    elif name == "check_script":
        context["rule_check"] = result
    return result


def run_agent(brief: Brief, model: DecisionModel, tools: LocalTools,
              config: RunConfig | None = None) -> tuple[dict, dict]:
    config = config or tools.config
    if config != tools.config:
        raise ValueError("agent and tool configurations must match")
    context = {"brief": brief.model_dump(), "missing_fields": brief.missing_fields(),
               "config": config.model_dump(), "materials": [], "script": None,
               "duration": None, "rule_check": None, "revision": 0,
               "last_observation": None, "history": [], "status": "running",
               "requested_fields": [], "tool_calls": 0, "steps": 0,
               "stop_reason": "", "rules": {}}
    trace = {"run_id": str(uuid4()), "mode": model.mode, "model": model.model_id,
             "started_at": now(), "config": config.model_dump(), "steps": []}
    try:
        context["rules"] = tools.load_rules()
    except Exception as error:
        stop(context, "failed", "rules_load_error : " + type(error).__name__)

    def turn(state: GraphState) -> GraphState:
        ctx = copy.deepcopy(state["context"])
        ctx["steps"] += 1
        started = time.perf_counter()
        entry = {"step": ctx["steps"], "time": now(),
                 "observed_step": ctx["history"][-1]["step"] if ctx["history"] else None}
        ctx.pop("effective_tool_arguments", None)
        try:
            # Copies prevent a model adapter from modifying runtime state.
            visible = {k: v for k, v in ctx.items() if k != "effective_tool_arguments"}
            raw = model.decide(copy.deepcopy(visible))
            action = ACTION_ADAPTER.validate_python(raw).model_dump()
            entry["decision"] = action
        except Exception as error:
            entry["observation"] = {"ok": False, "tool": "model_decision",
                                    "error": "model_error : " + type(error).__name__}
            stop(ctx, "failed", entry["observation"]["error"])
        else:
            tool_name = action["action"]
            is_tool = tool_name in ("search_materials", "estimate_duration", "check_script")
            if is_tool and ctx["tool_calls"] >= config.max_tool_calls:
                stop(ctx, "incomplete", "max_tool_calls reached")
                observation = {"ok": False, "tool": tool_name, "error": ctx["stop_reason"]}
            else:
                if is_tool:
                    ctx["tool_calls"] += 1
                try:
                    data = execute(action, ctx, tools)
                    observation = {"ok": True, "tool": tool_name, "result": data}
                except Exception as error:
                    observation = {"ok": False, "tool": tool_name,
                                   "error": "action_error : " + type(error).__name__}
            entry["observation"] = observation
            if "effective_tool_arguments" in ctx:
                entry["tool_arguments"] = ctx.pop("effective_tool_arguments")
            ctx["last_observation"] = observation
        entry["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 2)
        if ctx["status"] == "running" and ctx["steps"] >= config.max_graph_steps:
            stop(ctx, "incomplete", "max_graph_steps reached")
        # Tool calls at the limit can still be followed by a non-tool finish/request action.
        entry["status_after_step"] = ctx["status"]
        ctx["history"].append(copy.deepcopy(entry))
        return {"context": ctx}

    if context["status"] == "running":
        builder = StateGraph(GraphState)
        builder.add_node("model_and_action", turn)
        builder.add_edge(START, "model_and_action")
        builder.add_conditional_edges("model_and_action", lambda s:
                                      "continue" if s["context"]["status"] == "running" else "stop",
                                      {"continue": "model_and_action", "stop": END})
        graph = builder.compile()
        context = graph.invoke({"context": context},
                               {"recursion_limit": config.max_graph_steps + 2})["context"]
    result = make_result(context, model.mode)
    trace["steps"] = context["history"]
    for index, entry in enumerate(trace["steps"]):
        following = trace["steps"][index + 1] if index + 1 < len(trace["steps"]) else None
        entry["next_action"] = following.get("decision", {}).get("action") if following else None
    trace.update(finished_at=now(), status=result["status"], final_output=copy.deepcopy(result))
    return result, trace


def make_result(context: dict, mode: str) -> dict:
    script = context["script"] or {"title": "", "scenes": []}
    duration = context["duration"] or {}
    rules = context["rule_check"] or {}
    timings = {s["scene_id"]: s for s in duration.get("scenes", [])}
    reports = {s["scene_id"]: s for s in rules.get("scenes", [])}
    scenes = []
    for scene in script["scenes"]:
        scenes.append({**scene, "duration_seconds": timings.get(scene["scene_id"], {}).get("duration_seconds"),
                       "rule_check": reports.get(scene["scene_id"], {"passed": False, "issues": ["not_checked"]})})
    risks = []
    for step in context["history"]:
        obs = step["observation"]
        if not obs["ok"]:
            risks.append(obs["error"])
    if context["status"] != "completed":
        risks.append(context["stop_reason"])
    if rules and not rules["passed"]:
        risks.extend(rules["issues"])
        for scene_report in rules["scenes"]:
            risks.extend(scene_report["scene_id"] + " : " + issue for issue in scene_report["issues"])
    if duration and not duration["passed"]:
        risks.append("duration_out_of_range")
    return {"mode": mode, "status": context["status"], "title": script["title"],
            "target_duration_seconds": context["brief"]["target_duration_seconds"],
            "estimated_total_seconds": duration.get("estimated_total_seconds"),
            "scenes": scenes, "risks": list(dict.fromkeys(risks)),
            "checks": {"duration_passed": bool(duration.get("passed")),
                       "brand_rules_passed": bool(rules.get("passed"))},
            "check_details": {"duration": context["duration"], "rules": context["rule_check"]},
            "requested_fields": context["requested_fields"], "pending_items": pending(context),
            "stop_reason": context["stop_reason"],
            "usage": {"graph_steps": context["steps"], "tool_calls": context["tool_calls"]}}

import copy
import json

import pytest

from conftest import ROOT, RecordingModel, SequenceModel, action
from script_agent.graph import run_agent
from script_agent.model import MockModel, demo_script
from script_agent.schemas import Brief, RunConfig
from script_agent.tools import LocalTools


def test_normal_revises_overlong_script(brief, tools):
    model = RecordingModel()
    output, trace = run_agent(brief, model, tools)
    assert output["status"] == "completed"
    assert output["estimated_total_seconds"] == 30
    steps = trace["steps"]
    assert [s["decision"]["action"] for s in steps] == [
        "search_materials", "save_script", "estimate_duration", "save_script",
        "estimate_duration", "check_script", "finish"]
    assert steps[2]["observation"]["result"]["estimated_total_seconds"] == 38.4
    assert not model.contexts[3]["duration"]["passed"]
    assert model.contexts[4]["duration"] is None
    assert trace["final_output"] == output
    assert all(s["material_source_ids"] == ["P01"] for s in output["scenes"])
    assert all(s["rule_check"]["passed"] for s in output["scenes"])
    assert output["pending_items"] == []
    for i in range(1, len(model.contexts)):
        assert model.contexts[i]["last_observation"] == steps[i - 1]["observation"]
        assert steps[i]["observed_step"] == i


@pytest.mark.parametrize("field", ["topic", "audience", "platform", "target_duration_seconds", "style"])
def test_missing_fields(field, brief, tools):
    data = brief.model_dump()
    data.pop(field)
    output, trace = run_agent(Brief.model_validate(data), MockModel(), tools)
    assert output["status"] == "needs_input"
    assert field in output["requested_fields"]
    assert output["scenes"] == []
    assert len(trace["steps"]) == 1


def test_no_materials(brief, tools):
    brief.topic = "咖啡机"
    output, trace = run_agent(brief, MockModel(), tools)
    assert output["status"] == "needs_input"
    assert trace["steps"][0]["observation"]["result"]["materials"] == []
    assert trace["steps"][1]["decision"]["action"] == "request_input"
    assert output["scenes"] == []


def test_model_rewrites_query_after_empty_result(brief, tools):
    model = SequenceModel([action("search_materials", query="咖啡机"),
                           action("search_materials", query="字幕"),
                           action("request_input", fields=["creative_direction"])])
    _, trace = run_agent(brief, model, tools)
    assert model.contexts[1]["last_observation"]["result"]["count"] == 0
    assert model.contexts[2]["last_observation"]["result"]["count"] == 1
    assert trace["steps"][0]["next_action"] == "search_materials"


@pytest.mark.parametrize("name", ["search_materials", "estimate_duration", "check_script"])
def test_tool_error_reaches_model(name, brief, config):
    tools = LocalTools(ROOT / "data/materials.json", ROOT / "data/brand_rules.json", config, name)
    model = RecordingModel()
    output, trace = run_agent(brief, model, tools)
    assert output["status"] == "failed"
    assert model.contexts[-1]["last_observation"]["ok"] is False
    assert model.contexts[-1]["last_observation"]["tool"] == name
    assert any("RuntimeError" in risk for risk in output["risks"])
    assert trace["steps"][-1]["decision"]["status"] == "failed"


@pytest.mark.parametrize("kind", ["steps", "tools"])
def test_execution_budget(kind, brief):
    config = RunConfig(max_graph_steps=3 if kind == "steps" else 12,
                       max_tool_calls=8 if kind == "steps" else 2)
    tools = LocalTools(ROOT / "data/materials.json", ROOT / "data/brand_rules.json", config)
    model = SequenceModel([action("search_materials", query="字幕")] * 15)
    output, _ = run_agent(brief, model, tools)
    assert output["status"] == "incomplete"
    assert ("max_graph_steps" if kind == "steps" else "max_tool_calls") in output["stop_reason"]
    assert output["usage"]["tool_calls"] == (3 if kind == "steps" else 2)
    assert output["pending_items"]


def test_limit_allows_finish_with_last_check(brief):
    config = RunConfig(max_tool_calls=4)
    tools = LocalTools(ROOT / "data/materials.json", ROOT / "data/brand_rules.json", config)
    output, _ = run_agent(brief, MockModel(), tools)
    assert output["status"] == "completed"
    assert output["usage"]["tool_calls"] == 4


def test_stale_checks_cannot_complete(brief, tools):
    material = json.loads((ROOT / "data/materials.json").read_text(encoding="utf-8"))[0]
    script = demo_script(30, tools.config, tools.load_rules(), material)
    model = SequenceModel([action("search_materials", query="字幕"),
                           action("save_script", script=script), action("estimate_duration"),
                           action("check_script"), action("save_script", script=script),
                           action("finish", status="completed"), action("finish", status="failed")])
    output, trace = run_agent(brief, model, tools)
    assert output["status"] == "failed"
    assert not trace["steps"][5]["observation"]["ok"]
    assert output["estimated_total_seconds"] is None
    assert not output["checks"]["brand_rules_passed"]


def test_rule_failure_can_be_repaired_by_model(brief, tools):
    material = json.loads((ROOT / "data/materials.json").read_text(encoding="utf-8"))[0]
    script = demo_script(30, tools.config, tools.load_rules(), material)
    bad = copy.deepcopy(script)
    bad["title"] = "效率提升80%"
    model = SequenceModel([action("search_materials", query="字幕"),
                           action("save_script", script=bad), action("check_script"),
                           action("save_script", script=script), action("estimate_duration"),
                           action("check_script"), action("finish", status="completed")])
    output, _ = run_agent(brief, model, tools)
    assert not model.contexts[3]["rule_check"]["passed"]
    assert output["status"] == "completed"


def test_model_error_is_explicit_and_sanitized(brief, tools):
    class BrokenModel(MockModel):
        def decide(self, context):
            raise RuntimeError("secret-token-must-not-appear")
    output, trace = run_agent(brief, BrokenModel(), tools)
    assert output["status"] == "failed"
    assert "secret-token" not in json.dumps(trace)
    assert "RuntimeError" in output["stop_reason"]


def test_malformed_action_is_rejected(brief, tools):
    model = SequenceModel([{"action": "run_shell", "reason": "not allowed", "command": "whoami"}])
    output, trace = run_agent(brief, model, tools)
    assert output["status"] == "failed"
    assert "decision" not in trace["steps"][0]


def test_model_cannot_mutate_state(brief, tools):
    class MutatingModel(MockModel):
        def decide(self, context):
            context["status"] = "completed"
            return action("finish", status="completed")
    output, _ = run_agent(brief, MutatingModel(), tools)
    assert output["status"] == "incomplete"
    assert not output["checks"]["duration_passed"]


def test_over_target_cannot_finish_even_if_rules_pass(brief, tools):
    material = json.loads((ROOT / "data/materials.json").read_text(encoding="utf-8"))[0]
    script = demo_script(31, tools.config, tools.load_rules(), material)
    model = SequenceModel([action("search_materials", query="字幕"),
                           action("save_script", script=script), action("estimate_duration"),
                           action("check_script"), action("finish", status="completed"),
                           action("finish", status="failed")])
    output, trace = run_agent(brief, model, tools)
    assert model.contexts[4]["rule_check"]["passed"]
    assert not model.contexts[4]["duration"]["passed"]
    assert output["status"] == "failed"
    assert not trace["steps"][4]["observation"]["ok"]

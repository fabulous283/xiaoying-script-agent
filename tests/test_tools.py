import copy
import json

import pytest

from conftest import ROOT
from script_agent.model import demo_script
from script_agent.schemas import RunConfig, Script
from script_agent.tools import check, estimate, sentences, speech_units


@pytest.fixture
def rules(tools):
    return tools.load_rules()


@pytest.fixture
def materials():
    return json.loads((ROOT / "data/materials.json").read_text(encoding="utf-8"))


@pytest.fixture
def script(config, rules, materials):
    return demo_script(30, config, rules, materials[0])


def test_speech_units():
    assert speech_units("字幕 AI editor，80%！") == 5
    assert sentences("支持字幕。功能以实际版本为准。") == ["支持字幕。", "功能以实际版本为准。"]


@pytest.mark.parametrize("seconds,passed", [(27, True), (30, True), (26.99, False),
                                           (30.01, False), (33, False)])
def test_duration_boundaries(seconds, passed):
    # 104 spoken units at 4/s => 26 seconds, plus a valid scene overhead.
    script = Script.model_validate({"title": "test", "scenes": [{
        "scene_id": "S1", "visual": "test", "voiceover": "字" * 104,
        "material_source_ids": ["P01"], "pause_seconds": 0.0}]})
    result = estimate(script, 30, RunConfig(characters_per_second=4.0,
                                          scene_overhead_seconds=seconds - 26))
    assert result["passed"] is passed


def test_fact_and_scene_checks(script, materials, rules, config):
    result = check(Script.model_validate(script), materials, rules)
    assert result["passed"]
    timing = estimate(Script.model_validate(script), 30, config)
    assert timing["passed"]
    assert round(sum(s["duration_seconds"] for s in timing["scenes"]), 2) == timing["estimated_total_seconds"]


@pytest.mark.parametrize("attack", ["claim", "voiceover", "visual", "title", "id", "unretrieved",
                                   "disclaimer", "duplicate", "unused_claim", "no_claim"])
def test_reject_unfounded_content(attack, script, materials, rules):
    bad = copy.deepcopy(script)
    scene = bad["scenes"][1]
    if attack == "claim":
        scene["claims"][0]["text"] = "效率提升80%"
        scene["voiceover"] = "效率提升80%。"
    elif attack == "voiceover":
        scene["voiceover"] += "支持人脸识别。"
    elif attack == "visual":
        scene["visual"] = "展示自动生成字幕的按钮"
    elif attack == "title":
        bad["title"] = "效率提升80%"
    elif attack == "id":
        scene["material_source_ids"] = ["P99"]
    elif attack == "unretrieved":
        materials = []
    elif attack == "disclaimer":
        for item in bad["scenes"]:
            item["voiceover"] = item["voiceover"].replace(rules["required_disclaimer"], "") or "支持字幕。"
    elif attack == "duplicate":
        scene["scene_id"] = "S1"
    elif attack == "unused_claim":
        scene["voiceover"] = rules["neutral_narration"][0]
    elif attack == "no_claim":
        scene["claims"] = []
    assert not check(Script.model_validate(bad), materials, rules)["passed"]


def test_search_returns_empty_and_does_not_invent(tools):
    assert tools.invoke("search_materials", {"query": "咖啡机"}, {})["count"] == 0
    result = tools.invoke("search_materials", {"query": "字幕"}, {})
    assert result["materials"][0]["id"] == "P01"

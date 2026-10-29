import json
import re
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

from script_agent.cli import write_json
from script_agent.schemas import ACTION_ADAPTER, Brief, RunConfig, Script
from script_agent.tools import LocalTools, check, estimate


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def replay_duration_policy(result, brief, config, legacy):
    """Replay immutable historical evidence under its original, explicitly labelled policy."""
    if not legacy:
        return result
    result = result.copy()
    target = brief.target_duration_seconds
    low, high = target * (1 - config.duration_tolerance), target * (1 + config.duration_tolerance)
    result["accepted_range_seconds"] = [round(low, 4), round(high, 4)]
    result["passed"] = low - 1e-8 <= result["estimated_total_seconds"] <= high + 1e-8
    return result


runs = []
replayed = 0
for folder in sorted(Path("examples/runs").iterdir()):
    trace = read(folder / "trace.json")
    output = read(folder / "output.json")
    brief = Brief.model_validate(read(folder / "input.json"))
    metadata = read(folder / "run_config.json")
    config = RunConfig.model_validate(trace["config"])
    # Only these archived runs predate the hard-cap change; new runs always use current rules.
    legacy = folder.name in {"real-no-materials", "real-normal-refined", "real-normal-timeout",
                             "real-normal-timeout-retry", "real-normal-timeout-fix", "real-short-refined"}
    tools = LocalTools(Path("data/materials.json"), Path("data/brand_rules.json"),
                       config, metadata.get("fail_tool"))
    assert trace["final_output"] == output, folder
    assert trace["status"] == output["status"], folder
    assert trace["mode"] == output["mode"], folder
    state = {"script": None, "brief": brief.model_dump(), "materials": []}
    current_duration = None
    current_rules = None
    attempts = 0
    for i, step in enumerate(trace["steps"]):
        assert step["step"] == i + 1
        assert step["observed_step"] == (i if i else None)
        following = trace["steps"][i + 1] if i + 1 < len(trace["steps"]) else None
        assert step["next_action"] == (following.get("decision", {}).get("action") if following else None)
        observation = step["observation"]
        if "decision" not in step:
            assert not observation["ok"] and observation["tool"] == "model_decision"
            continue
        decision = ACTION_ADAPTER.validate_python(step["decision"]).model_dump()
        name = decision["action"]
        if name == "save_script" and observation["ok"]:
            state["script"] = decision["script"]
            current_duration = current_rules = None
        if name in ("search_materials", "estimate_duration", "check_script"):
            if observation.get("error") == "max_tool_calls reached":
                assert attempts == config.max_tool_calls
                continue
            attempts += 1
            arguments = step["tool_arguments"]
            if name != "search_materials":
                assert arguments["script"] == state["script"]
            try:
                actual = tools.invoke(name, arguments, state)
                if name == "estimate_duration":
                    actual = replay_duration_policy(actual, brief, config, legacy)
            except Exception as error:
                assert not observation["ok"]
                assert type(error).__name__ in observation["error"]
            else:
                assert observation["ok"] and observation["result"] == actual, (folder, i)
                if name == "search_materials":
                    materials = {m["id"]: m for m in state["materials"]}
                    materials.update({m["id"]: m for m in actual["materials"]})
                    state["materials"] = list(materials.values())
                elif name == "estimate_duration":
                    current_duration = actual
                else:
                    current_rules = actual
            replayed += 1
    assert output["usage"] == {"graph_steps": len(trace["steps"]), "tool_calls": attempts}
    assert len(trace["steps"]) <= config.max_graph_steps and attempts <= config.max_tool_calls
    assert output["check_details"] == {"duration": current_duration, "rules": current_rules}
    if output["status"] == "completed":
        assert not brief.missing_fields()
        script = Script.model_validate(state["script"])
        duration = replay_duration_policy(estimate(script, brief.target_duration_seconds, config),
                                          brief, config, legacy)
        rules = check(script, state["materials"], tools.load_rules())
        assert duration["passed"] and rules["passed"]
        assert output["check_details"] == {"duration": duration, "rules": rules}
        assert output["title"] == script.title
        assert output["estimated_total_seconds"] == duration["estimated_total_seconds"]
        assert not output["pending_items"]
        for scene, timing, report, emitted in zip(script.scenes, duration["scenes"], rules["scenes"],
                                                  output["scenes"], strict=True):
            assert emitted == {**scene.model_dump(), "duration_seconds": timing["duration_seconds"],
                               "rule_check": report}
    runs.append({"case": folder.name, "mode": trace["mode"], "status": output["status"],
                 "steps": len(trace["steps"]), "tool_calls": attempts, "verified": True,
                 "duration_policy": "legacy_symmetric_tolerance" if legacy else "target_hard_cap",
                 "completed_within_current_hard_cap": (output["estimated_total_seconds"] <=
                     brief.target_duration_seconds) if output["status"] == "completed" else None})

broken_links = []
for path in [Path("README.md"), *Path("docs").glob("*.md")]:
    for link in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
        if "://" not in link and not (path.parent / link.split("#")[0]).exists():
            broken_links.append({"file": str(path), "link": link})
assert not broken_links, broken_links
key = dotenv_values(".env").get("SCRIPT_AGENT_API_KEY", "")
files = [p for directory in ("src", "tests", "scripts", "docs", "data", "examples")
         for p in Path(directory).rglob("*") if p.is_file() and p.suffix in (".py", ".json", ".md", ".txt")]
assert not key or all(key not in p.read_text(encoding="utf-8") for p in files)
report = {"reviewed_at": datetime.now(timezone.utc).isoformat(), "runs": runs,
          "replayed_tool_calls": replayed, "broken_local_document_links": broken_links,
          "exact_credential_scan": "passed", "git_repository_present": Path(".git").exists()}
write_json(Path("examples/submission-review-checks.json"), report)
print("submission artifacts verified : runs = " + str(len(runs)) + " ; replayed_tool_calls = " + str(replayed))

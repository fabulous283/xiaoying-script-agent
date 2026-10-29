"""Archive synthetic-input real runs after replaying successful final checks locally."""
import argparse
import json
import os
from pathlib import Path

from script_agent.cli import load_model_config, write_json
from script_agent.prompts import SYSTEM_PROMPT
from script_agent.schemas import Brief, RunConfig, Script
from script_agent.tools import check, estimate


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    load_model_config()
    brief = Brief.model_validate(read_json(args.input))
    output = read_json(args.run_dir / "output.json")
    trace = read_json(args.run_dir / "trace.json")
    assert output == trace["final_output"], "output and trace differ"
    assert trace["mode"] == output["mode"] == "real_model", "not a real model run"
    config = RunConfig.model_validate(trace["config"])
    if output["status"] == "completed":
        assert not output["pending_items"]
        latest = next(s["decision"]["script"] for s in reversed(trace["steps"])
                      if s.get("decision", {}).get("action") == "save_script")
        script = Script.model_validate(latest)
        materials = {}
        for step in trace["steps"]:
            observation = step["observation"]
            if observation["ok"] and observation["tool"] == "search_materials":
                materials.update({m["id"]: m for m in observation["result"]["materials"]})
        duration = estimate(script, brief.target_duration_seconds, config)
        rules = check(script, list(materials.values()), read_json(Path("data/brand_rules.json")))
        assert duration["passed"] and rules["passed"], "final script failed replay"
        assert output["check_details"] == {"duration": duration, "rules": rules}
        assert output["estimated_total_seconds"] == duration["estimated_total_seconds"]
        for scene, timing, report, rendered in zip(script.scenes, duration["scenes"],
                                                    rules["scenes"], output["scenes"], strict=True):
            assert rendered == {**scene.model_dump(), "duration_seconds": timing["duration_seconds"],
                                "rule_check": report}
    metadata = {"mode": "real_model", "model": trace["model"], "config": trace["config"],
                "duration_policy": "target_hard_cap",
                "request_config_source": "archive process environment ; archive immediately after run",
                "request_config": {
                    "read_timeout_seconds": float(os.environ.get("SCRIPT_AGENT_READ_TIMEOUT_SECONDS", "180")),
                    "max_tokens": int(os.environ.get("SCRIPT_AGENT_MAX_TOKENS", "4096")),
                    "enable_thinking": os.environ.get("SCRIPT_AGENT_ENABLE_THINKING", "")},
                "system_prompt": SYSTEM_PROMPT,
                "final_checks_replayed": output["status"] == "completed"}
    documents = {"input.json": brief.model_dump(), "output.json": output,
                 "trace.json": trace, "run_config.json": metadata}
    key = os.environ.get("SCRIPT_AGENT_API_KEY", "")
    for document in documents.values():
        assert not key or key not in json.dumps(document, ensure_ascii=False), "credential detected"
    for filename, document in documents.items():
        write_json(args.destination / filename, document)
    print("real run archived : status = " + output["status"] + " ; checks_replayed = "
          + str(metadata["final_checks_replayed"]))


if __name__ == "__main__":
    main()

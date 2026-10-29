"""Reproduce actual offline artifacts and capture pytest output. No running services."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from script_agent.cli import write_json
from script_agent.graph import run_agent
from script_agent.model import MockModel
from script_agent.schemas import Brief, RunConfig
from script_agent.tools import LocalTools


def main() -> int:
    summaries = []
    cases = [
        ("normal", "normal", None, RunConfig()),
        ("missing_info", "missing_info", None, RunConfig()),
        ("no_materials", "no_materials", None, RunConfig()),
        ("tool_failure", "normal", "search_materials", RunConfig()),
        ("budget_limit", "normal", None, RunConfig(max_graph_steps=3)),
    ]
    for name, input_name, failure, config in cases:
        data = json.loads((ROOT / f"examples/inputs/{input_name}.json").read_text(encoding="utf-8"))
        folder = ROOT / "examples" / "runs" / name
        tools = LocalTools(ROOT / "data/materials.json", ROOT / "data/brand_rules.json", config, failure)
        output, trace = run_agent(Brief.model_validate(data), MockModel(), tools, config)
        output["trace_path"] = "trace.json"
        trace["final_output"] = output.copy()
        write_json(folder / "input.json", data)
        write_json(folder / "output.json", output)
        write_json(folder / "trace.json", trace)
        write_json(folder / "run_config.json", {"mode": "mock", "fail_tool": failure,
                                               "duration_policy": "target_hard_cap",
                                               "config": config.model_dump()})
        summaries.append({"case": name, "status": output["status"], "mode": "mock",
                          "estimated_total_seconds": output["estimated_total_seconds"]})
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    test_run = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=ROOT, env=env,
                              capture_output=True, text=True, encoding="utf-8")
    (ROOT / "examples/test-results.txt").write_text(test_run.stdout + test_run.stderr, encoding="utf-8")
    real_runs = []
    for path in sorted((ROOT / "examples/runs").glob("real-*/trace.json")):
        trace = json.loads(path.read_text(encoding="utf-8"))
        if trace["mode"] == "real_model":
            real_runs.append({"case": path.parent.name, "status": trace["status"],
                              "model": trace["model"], "trace_path": path.relative_to(ROOT).as_posix()})
    write_json(ROOT / "examples/summary.json", {"cases": summaries, "test_exit_code": test_run.returncode,
                                               "real_model_evidence": real_runs or "not_run"})
    print(test_run.stdout)
    print("examples generated : count = " + str(len(cases)) + " ; mode = mock")
    return test_run.returncode


if __name__ == "__main__":
    raise SystemExit(main())

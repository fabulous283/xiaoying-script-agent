import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

from .graph import run_agent
from .model import CompatibleModel, MockModel
from .schemas import Brief, RunConfig
from .tools import LocalTools


def load_model_config() -> None:
    """Read the workspace-local secret file without overriding process settings."""
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False, interpolate=False)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Auditable short-video script agent")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--mode", choices=["mock", "real"], required=True)
    parser.add_argument("--materials", type=Path, default=Path("data/materials.json"))
    parser.add_argument("--rules", type=Path, default=Path("data/brand_rules.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("runs/latest"))
    parser.add_argument("--max-steps", type=int, default=12)
    parser.add_argument("--max-tool-calls", type=int, default=8)
    parser.add_argument("--fail-tool", choices=["search_materials", "estimate_duration", "check_script"],
                        help="Explicit fault injection for evaluation only")
    args = parser.parse_args()
    try:
        brief = Brief.model_validate(json.loads(args.input.read_text(encoding="utf-8-sig")))
        config = RunConfig(max_graph_steps=args.max_steps, max_tool_calls=args.max_tool_calls)
        if args.mode == "real":
            load_model_config()
        model = MockModel() if args.mode == "mock" else CompatibleModel()
        tools = LocalTools(args.materials, args.rules, config, args.fail_tool)
        output, trace = run_agent(brief, model, tools, config)
        output["trace_path"] = "trace.json"
        trace["final_output"] = output.copy()
        write_json(args.output_dir / "output.json", output)
        write_json(args.output_dir / "trace.json", trace)
    except Exception as error:
        # ValidationError and HTTP exceptions can contain secrets or private input.
        print("run failed : error_type = " + type(error).__name__ +
              " ; check input schema , configuration and writable output directory", file=sys.stderr)
        return 2
    print("run finished : mode = " + output["mode"] + " ; status = " + output["status"] +
          " ; output = " + str(args.output_dir / "output.json"))
    return {"completed": 0, "needs_input": 3, "failed": 4, "incomplete": 5}[output["status"]]


if __name__ == "__main__":
    raise SystemExit(main())

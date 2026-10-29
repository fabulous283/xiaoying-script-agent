"""Deterministic local tools. No network, model calls or hidden retries."""

import copy
import json
import re
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from .schemas import RunConfig, Script


def speech_units(text: str) -> int:
    # One CJK character or one Latin/number word is one unit. Punctuation is silent.
    return len(re.findall(r"[\u3400-\u9fff]|[A-Za-z0-9]+(?:['’-][A-Za-z0-9]+)*", text))


def hundredths(value: float) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def estimate(script: Script, target: float, config: RunConfig) -> dict:
    scenes = []
    for scene in script.scenes:
        units = speech_units(scene.voiceover)
        ticks = hundredths(units / config.characters_per_second
                           + config.scene_overhead_seconds + scene.pause_seconds)
        scenes.append({"scene_id": scene.scene_id, "speech_units": units,
                       "duration_seconds": ticks / 100})
    total = sum(hundredths(s["duration_seconds"]) for s in scenes) / 100
    low = target * (1 - config.duration_tolerance)
    high = target
    return {"passed": low - 1e-8 <= total <= high + 1e-8,
            "estimated_total_seconds": total, "scenes": scenes,
            "accepted_range_seconds": [round(low, 4), round(high, 4)],
            "characters_per_second": config.characters_per_second,
            "scene_overhead_seconds": config.scene_overhead_seconds,
            "method": "CJK characters + Latin words ; punctuation excluded ; rounded per scene"}


def sentences(text: str) -> list[str]:
    return [part.strip() for part in re.findall(r"[^。！？!?；;\n]+[。！？!?；;]?", text)
            if part.strip()]


def check(script: Script, materials: list[dict], rules: dict) -> dict:
    sources = {item["id"]: item for item in materials}
    reports = []
    global_issues = []
    if script.title not in rules["allowed_titles"]:
        global_issues.append("title_not_approved")
    if len({s.scene_id for s in script.scenes}) != len(script.scenes):
        global_issues.append("duplicate_scene_id")
    all_text = script.title + "\n" + "\n".join(
        s.visual + "\n" + s.voiceover for s in script.scenes)
    for term in rules["forbidden_expressions"]:
        if term.casefold() in all_text.casefold():
            global_issues.append("forbidden_expression : " + term)
    if rules["required_disclaimer"] not in "".join(s.voiceover for s in script.scenes):
        global_issues.append("missing_required_disclaimer")
    for scene in script.scenes:
        issues = []
        if scene.visual not in rules["allowed_visuals"]:
            issues.append("visual_not_approved")
        for source_id in scene.material_source_ids:
            if source_id not in sources:
                issues.append("unknown_or_unretrieved_source : " + source_id)
        supported = []
        for claim in scene.claims:
            material = sources.get(claim.source_id)
            if (claim.source_id not in scene.material_source_ids or not material
                    or claim.text not in material["facts"]):
                issues.append("unsupported_claim : " + claim.text)
            else:
                supported.append(claim.text + "。")
            if claim.text not in scene.voiceover:
                issues.append("claim_not_in_voiceover : " + claim.text)
        allowed = rules["neutral_narration"] + supported
        for sentence in sentences(scene.voiceover):
            if sentence not in allowed:
                issues.append("unsupported_voiceover : " + sentence)
        reports.append({"scene_id": scene.scene_id, "passed": not issues, "issues": issues})
    if not any(s.claims for s in script.scenes):
        global_issues.append("missing_product_fact")
    return {"passed": not global_issues and all(s["passed"] for s in reports),
            "issues": global_issues, "scenes": reports,
            "policy": "Exact approved facts and neutral sentences ; no semantic entailment claim"}


class LocalTools:
    def __init__(self, materials_path: Path, rules_path: Path,
                 config: RunConfig, fail_tool: str | None = None):
        self.materials_path = materials_path
        self.rules_path = rules_path
        self.config = config
        self.fail_tool = fail_tool

    def load_rules(self) -> dict:
        rules = json.loads(self.rules_path.read_text(encoding="utf-8"))
        for key in ("forbidden_expressions", "allowed_titles", "allowed_visuals", "neutral_narration"):
            if not isinstance(rules.get(key), list) or not all(isinstance(v, str) for v in rules[key]):
                raise ValueError("invalid rule list")
        if not isinstance(rules.get("required_disclaimer"), str) or not rules["required_disclaimer"]:
            raise ValueError("invalid disclaimer")
        return rules

    def invoke(self, name: str, arguments: dict, state: dict) -> dict:
        if name == self.fail_tool:
            raise RuntimeError("injected tool failure")
        if name == "search_materials":
            materials = json.loads(self.materials_path.read_text(encoding="utf-8"))
            ids = [m["id"] for m in materials]
            if len(set(ids)) != len(ids):
                raise ValueError("duplicate material ID")
            query = arguments["query"].casefold()
            matches = [m for m in materials if any(
                word.casefold() in query for word in m["keywords"])]
            return {"materials": copy.deepcopy(matches), "count": len(matches)}
        script = Script.model_validate(state["script"])
        if name == "estimate_duration":
            return estimate(script, state["brief"]["target_duration_seconds"], self.config)
        if name == "check_script":
            return check(script, state["materials"], self.load_rules())
        raise ValueError("unknown tool")

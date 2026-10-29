import copy
import json
import os
from typing import Protocol
from urllib.parse import urlsplit

import httpx

from .prompts import SYSTEM_PROMPT
from .schemas import ACTION_ADAPTER, RunConfig, Script
from .tools import estimate, speech_units


class DecisionModel(Protocol):
    mode: str
    model_id: str

    def decide(self, context: dict) -> dict: ...


class CompatibleModel:
    mode = "real_model"

    def __init__(self):
        self.model_id = os.environ.get("SCRIPT_AGENT_MODEL", "")
        base = os.environ.get("SCRIPT_AGENT_BASE_URL", "").rstrip("/")
        self.api_key = os.environ.get("SCRIPT_AGENT_API_KEY", "")
        if not all((self.model_id, base, self.api_key)):
            raise ValueError("missing model configuration")
        parsed = urlsplit(base)
        if parsed.scheme not in ("https", "http") or not parsed.netloc or parsed.username or parsed.query:
            raise ValueError("invalid model base URL")
        self.url = base + "/chat/completions"
        self.read_timeout = float(os.environ.get("SCRIPT_AGENT_READ_TIMEOUT_SECONDS", "180"))
        self.max_tokens = int(os.environ.get("SCRIPT_AGENT_MAX_TOKENS", "4096"))
        if not 1 <= self.read_timeout <= 600 or not 256 <= self.max_tokens <= 16384:
            raise ValueError("invalid model request limits")
        thinking = os.environ.get("SCRIPT_AGENT_ENABLE_THINKING", "").strip().lower()
        if thinking not in ("", "true", "false"):
            raise ValueError("invalid thinking setting")
        self.enable_thinking = None if not thinking else thinking == "true"

    def _request_context(self, context: dict) -> dict:
        compact = copy.deepcopy(context)
        # Keep observations and the current script; omit duplicate historic script bodies.
        for entry in compact.get("history", []):
            entry.pop("tool_arguments", None)
            if entry.get("decision"):
                entry["decision"].pop("script", None)
        # Counts are authoring references, never a substitute for checking the saved script.
        compact["writing_reference"] = {
            "neutral_sentences": [{"text": text, "speech_units": speech_units(text)}
                                  for text in compact.get("rules", {}).get("neutral_narration", [])],
            "fact_sentences": [{"text": fact + "。", "speech_units": speech_units(fact + "。"),
                                "claim_text": fact, "source_id": material["id"]}
                               for material in compact.get("materials", []) for fact in material["facts"]]}
        return compact

    def decide(self, context: dict) -> dict:
        payload = {"model": self.model_id,
                   "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                {"role": "user", "content": json.dumps({
                                    "action_schema": ACTION_ADAPTER.json_schema(),
                                    "context": self._request_context(context)}, ensure_ascii=False,
                                    separators=(",", ":"))}],
                   "response_format": {"type": "json_object"}, "max_tokens": self.max_tokens}
        if self.enable_thinking is not None:
            payload["enable_thinking"] = self.enable_thinking
        # Do not log headers, raw HTTP failures, response bodies or endpoint URLs.
        timeout = httpx.Timeout(self.read_timeout, connect=10, write=30, pool=10)
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            response = client.post(self.url, json=payload,
                                   headers={"Authorization": "Bearer " + self.api_key})
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content)


def demo_script(target: float, config: RunConfig, rules: dict, material: dict) -> dict:
    """Deterministic fixture authoring; it is explicitly NOT an LLM."""
    phrases = rules["neutral_narration"]
    fact = material["facts"][0]
    scenes = [{"scene_id": f"S{i + 1}", "visual": rules["allowed_visuals"][i],
               "voiceover": "", "material_source_ids": [material["id"]],
               "claims": [], "pause_seconds": 0.0} for i in range(3)]
    scenes[0]["voiceover"] = phrases[0]
    scenes[1]["voiceover"] = fact + "。"
    scenes[1]["claims"] = [{"text": fact, "source_id": material["id"]}]
    scenes[2]["voiceover"] = rules["required_disclaimer"]
    script = {"title": rules["allowed_titles"][0], "scenes": scenes}
    for i in range(50):
        candidate = copy.deepcopy(script)
        candidate["scenes"][i % 3]["voiceover"] += phrases[1 + i % (len(phrases) - 2)]
        seconds = estimate(Script.model_validate(candidate), target, config)["estimated_total_seconds"]
        if seconds > target:
            break
        script = candidate
    current = estimate(Script.model_validate(script), target, config)["estimated_total_seconds"]
    rest = max(0, target - current)
    for scene in script["scenes"]:
        pause = round(min(5, rest), 2)
        scene["pause_seconds"] = pause
        rest = round(rest - pause, 2)
    return script


class MockModel:
    mode = "mock"
    model_id = "offline-observation-fixture-v1"

    def decide(self, context: dict) -> dict:
        def action(name: str, reason: str, **kwargs) -> dict:
            return {"action": name, "reason": reason, **kwargs}

        missing = context["missing_fields"]
        if missing:
            return action("request_input", "关键输入缺失，无法生成完整脚本。", fields=missing)
        last = context["last_observation"]
        if last and not last["ok"]:
            return action("finish", "上一动作失败，离线演示终止并保留错误。", status="failed")
        if not context["materials"]:
            if last and last["tool"] == "search_materials":
                return action("request_input", "检索结果为空，需要相关产品资料。", fields=["product_materials"])
            return action("search_materials", "检索主题相关的产品事实。", query=context["brief"]["topic"])
        target = context["brief"]["target_duration_seconds"]
        config = RunConfig.model_validate(context["config"])
        if not context["script"]:
            return action("save_script", "使用已检索事实建立首稿，演示后续时长检查。",
                          script=demo_script(round(target * 1.28, 2), config,
                                             context["rules"], context["materials"][0]))
        if not context["duration"]:
            return action("estimate_duration", "当前稿件尚无时长检查。")
        if not context["duration"]["passed"]:
            if context["revision"] >= 3:
                return action("finish", "修订后仍无法满足目标时长。", status="failed")
            return action("save_script", "实测时长超出容差，调整旁白并重新检查。",
                          script=demo_script(target, config, context["rules"], context["materials"][0]))
        if not context["rule_check"]:
            return action("check_script", "时长已通过，检查事实引用和品牌规则。")
        if not context["rule_check"]["passed"]:
            return action("finish", "规则检查存在问题，不能标记成功。", status="failed")
        return action("finish", "当前稿件的时长和规则检查均通过。", status="completed")

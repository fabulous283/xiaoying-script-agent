import json
import os
import subprocess
import sys

import httpx
import pytest

from conftest import ROOT, action
from script_agent.model import CompatibleModel


def test_writing_reference_counts_actual_allowed_sentences(monkeypatch):
    monkeypatch.setenv("SCRIPT_AGENT_MODEL", "test-model")
    monkeypatch.setenv("SCRIPT_AGENT_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("SCRIPT_AGENT_API_KEY", "synthetic-test-key")
    context = {"rules": {"neutral_narration": ["今天从字幕开始。", "AI editor。"]},
               "materials": [{"id": "P01", "facts": ["支持字幕"]}], "history": []}
    compact = CompatibleModel()._request_context(context)
    reference = compact["writing_reference"]
    assert reference["neutral_sentences"] == [
        {"text": "今天从字幕开始。", "speech_units": 7},
        {"text": "AI editor。", "speech_units": 2}]
    assert reference["fact_sentences"] == [{"text": "支持字幕。", "speech_units": 4,
                                            "claim_text": "支持字幕", "source_id": "P01"}]
    assert "writing_reference" not in context


def test_local_model_config_preserves_environment(tmp_path, monkeypatch):
    from script_agent.cli import load_model_config

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SCRIPT_AGENT_API_KEY", raising=False)
    monkeypatch.delenv("SCRIPT_AGENT_BASE_URL", raising=False)
    monkeypatch.setenv("SCRIPT_AGENT_MODEL", "environment-model")
    (tmp_path / ".env").write_text(
        'SCRIPT_AGENT_BASE_URL="https://example.invalid/v1"\n'
        'SCRIPT_AGENT_MODEL="local-model"\n'
        'SCRIPT_AGENT_API_KEY="synthetic-test-key"\n', encoding="utf-8")
    load_model_config()
    assert os.environ["SCRIPT_AGENT_BASE_URL"] == "https://example.invalid/v1"
    assert os.environ["SCRIPT_AGENT_MODEL"] == "environment-model"
    assert os.environ["SCRIPT_AGENT_API_KEY"] == "synthetic-test-key"


def test_real_adapter_uses_actual_response(monkeypatch):
    monkeypatch.setenv("SCRIPT_AGENT_MODEL", "test-provider-model")
    monkeypatch.setenv("SCRIPT_AGENT_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("SCRIPT_AGENT_API_KEY", "synthetic-test-key")
    seen = []

    def handle(request):
        seen.append(json.loads(request.content))
        assert str(request.url) == "https://example.invalid/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(
            action("request_input", fields=["audience"]))}}]})

    original = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs:
                        original(transport=httpx.MockTransport(handle), **kwargs))
    decision = CompatibleModel().decide({"last_observation": {"ok": True, "result": {"count": 0}}})
    assert decision["action"] == "request_input"
    assert "last_observation" in seen[0]["messages"][1]["content"]
    assert "synthetic-test-key" not in json.dumps(seen)


def test_real_mode_never_silently_falls_back(monkeypatch):
    for key in ("SCRIPT_AGENT_MODEL", "SCRIPT_AGENT_BASE_URL", "SCRIPT_AGENT_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValueError, match="missing model configuration"):
        CompatibleModel()


def test_request_limits_and_compact_history(monkeypatch):
    monkeypatch.setenv("SCRIPT_AGENT_MODEL", "test-model")
    monkeypatch.setenv("SCRIPT_AGENT_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("SCRIPT_AGENT_API_KEY", "synthetic-test-key")
    monkeypatch.setenv("SCRIPT_AGENT_READ_TIMEOUT_SECONDS", "180")
    monkeypatch.setenv("SCRIPT_AGENT_MAX_TOKENS", "2048")
    monkeypatch.setenv("SCRIPT_AGENT_ENABLE_THINKING", "false")
    observation = {"ok": True, "tool": "estimate_duration", "result": {"passed": False}}
    context = {"script": {"title": "current"}, "last_observation": observation,
               "history": [{"step": 1, "decision": action("save_script", script={"title": "old"}),
                            "tool_arguments": {"script": "duplicated script"},
                            "observation": observation}]}
    captured = []
    original = httpx.Client

    def handle(request):
        payload = json.loads(request.content)
        captured.append(payload)
        assert request.extensions["timeout"]["read"] == 180
        assert request.extensions["timeout"]["connect"] == 10
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(action("estimate_duration"))}}]})

    monkeypatch.setattr(httpx, "Client", lambda **kwargs:
                        original(transport=httpx.MockTransport(handle), **kwargs))
    model = CompatibleModel()
    model.decide(context)
    payload = captured[0]
    assert payload["enable_thinking"] is False
    assert payload["max_tokens"] == 2048
    compact = json.loads(payload["messages"][1]["content"])["context"]
    assert compact["script"] == context["script"]
    assert compact["last_observation"] == observation
    assert compact["history"][0]["observation"] == observation
    assert "tool_arguments" not in compact["history"][0]
    assert "script" not in compact["history"][0]["decision"]
    assert "script" in context["history"][0]["decision"]


@pytest.mark.parametrize("name,value", [
    ("SCRIPT_AGENT_READ_TIMEOUT_SECONDS", "0"),
    ("SCRIPT_AGENT_READ_TIMEOUT_SECONDS", "nan"),
    ("SCRIPT_AGENT_MAX_TOKENS", "0"),
    ("SCRIPT_AGENT_ENABLE_THINKING", "sometimes")])
def test_invalid_request_configuration(monkeypatch, name, value):
    monkeypatch.setenv("SCRIPT_AGENT_MODEL", "test-model")
    monkeypatch.setenv("SCRIPT_AGENT_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("SCRIPT_AGENT_API_KEY", "synthetic-test-key")
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        CompatibleModel()


@pytest.mark.parametrize("case,exit_code,status", [
    ("normal", 0, "completed"), ("missing_info", 3, "needs_input"),
    ("no_materials", 3, "needs_input")])
def test_cli_artifacts(case, exit_code, status, tmp_path):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run([sys.executable, "-m", "script_agent.cli", "--mode", "mock",
                             "--input", str(ROOT / f"examples/inputs/{case}.json"),
                             "--output-dir", str(tmp_path)], cwd=ROOT, env=env,
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == exit_code, result.stderr
    output = json.loads((tmp_path / "output.json").read_text(encoding="utf-8"))
    trace = json.loads((tmp_path / "trace.json").read_text(encoding="utf-8"))
    assert output["status"] == status
    assert trace["final_output"] == output
    assert trace["mode"] == "mock"

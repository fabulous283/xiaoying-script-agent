import copy
import json
from pathlib import Path

import pytest

from script_agent.model import MockModel
from script_agent.schemas import Brief, RunConfig
from script_agent.tools import LocalTools


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def brief():
    return Brief.model_validate(json.loads((ROOT / "examples/inputs/normal.json").read_text(encoding="utf-8")))


@pytest.fixture
def config():
    return RunConfig()


@pytest.fixture
def tools(config):
    return LocalTools(ROOT / "data/materials.json", ROOT / "data/brand_rules.json", config)


class RecordingModel(MockModel):
    def __init__(self):
        self.contexts = []

    def decide(self, context):
        self.contexts.append(copy.deepcopy(context))
        return super().decide(context)


class SequenceModel:
    mode = "mock"
    model_id = "test-sequence"

    def __init__(self, actions):
        self.actions = iter(actions)
        self.contexts = []

    def decide(self, context):
        self.contexts.append(copy.deepcopy(context))
        return next(self.actions)


def action(name, **kwargs):
    return {"action": name, "reason": "Controlled test decision.", **kwargs}

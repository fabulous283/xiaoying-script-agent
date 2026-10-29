from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Brief(StrictModel):
    topic: str = ""
    audience: str = ""
    platform: str = ""
    target_duration_seconds: float | None = Field(default=None, gt=0, le=600)
    style: str = ""

    def missing_fields(self) -> list[str]:
        return [name for name, value in self.model_dump().items()
                if value is None or (isinstance(value, str) and not value.strip())]


class Claim(StrictModel):
    text: str = Field(min_length=1, max_length=300)
    source_id: str = Field(min_length=1, max_length=50)


class Scene(StrictModel):
    scene_id: str = Field(pattern=r"^S[1-9][0-9]*$")
    visual: str = Field(min_length=1, max_length=500)
    voiceover: str = Field(min_length=1, max_length=2000)
    material_source_ids: list[str] = Field(min_length=1, max_length=10)
    claims: list[Claim] = Field(default_factory=list, max_length=20)
    pause_seconds: float = Field(default=0.0, ge=0, le=5)


class Script(StrictModel):
    title: str = Field(min_length=1, max_length=100)
    scenes: list[Scene] = Field(min_length=1, max_length=12)


class ActionBase(StrictModel):
    reason: str = Field(min_length=1, max_length=300)


class SearchAction(ActionBase):
    action: Literal["search_materials"]
    query: str = Field(min_length=1, max_length=200)


class DraftAction(ActionBase):
    action: Literal["save_script"]
    script: Script


class DurationAction(ActionBase):
    action: Literal["estimate_duration"]


class CheckAction(ActionBase):
    action: Literal["check_script"]


class InputAction(ActionBase):
    action: Literal["request_input"]
    fields: list[str] = Field(min_length=1)


class FinishAction(ActionBase):
    action: Literal["finish"]
    status: Literal["completed", "failed"]


Action = Annotated[Union[SearchAction, DraftAction, DurationAction, CheckAction,
                         InputAction, FinishAction], Field(discriminator="action")]
ACTION_ADAPTER = TypeAdapter(Action)


class RunConfig(StrictModel):
    max_graph_steps: int = Field(default=12, ge=1, le=100)
    max_tool_calls: int = Field(default=8, ge=1, le=100)
    characters_per_second: float = Field(default=4.0, gt=0, le=20)
    scene_overhead_seconds: float = Field(default=0.8, ge=0, le=10)
    duration_tolerance: float = Field(default=0.1, ge=0, le=0.5,
                                      description="Allowed shortfall ratio only ; target is a hard upper limit")

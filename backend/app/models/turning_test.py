from typing import Any, Dict, Literal

from pydantic import BaseModel, ConfigDict, Field


class TurningTestAIRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=1000)


class TurningTestAIResponse(BaseModel):
    answer: str
    word_count: int
    model: str


class TurningTestRewriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["light_polish", "improve_clarity", "major_rewrite"]
    selected_text: str = Field(min_length=1, max_length=20_000)


class TurningTestRewriteResponse(BaseModel):
    rewritten_text: str
    model: str


class PangramSubmitRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


class PangramTaskResponse(BaseModel):
    task_id: str
    requested_model: str
    response: Dict[str, Any]

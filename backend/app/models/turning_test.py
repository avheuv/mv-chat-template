from typing import Any, Dict, Literal

from pydantic import BaseModel, Field, field_validator


class TurningTestAIRequest(BaseModel):
    action: Literal["generate", "rewrite", "grammar"]
    prompt_id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(default="", max_length=20_000)

    @field_validator("answer")
    @classmethod
    def draft_required_for_edits(cls, value: str, info):
        if info.data.get("action") in {"rewrite", "grammar"} and not value.strip():
            raise ValueError("A draft is required for this action.")
        return value


class TurningTestAIResponse(BaseModel):
    answer: str
    word_count: int
    model: str


class PangramSubmitRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


class PangramTaskResponse(BaseModel):
    task_id: str
    requested_model: str
    response: Dict[str, Any]

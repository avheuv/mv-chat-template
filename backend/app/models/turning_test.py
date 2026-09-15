from typing import Any, Dict, Literal

from pydantic import BaseModel, Field, field_validator


class TurningTestAIRequest(BaseModel):
    action: Literal["generate", "rewrite"]
    prompt_id: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(default="", max_length=20_000)
    custom_prompt: str = Field(default="", max_length=2_000)

    @field_validator("answer")
    @classmethod
    def draft_required_for_edits(cls, value: str, info):
        if info.data.get("action") == "rewrite" and not value.strip():
            raise ValueError("Highlighted text is required for Rewrite.")
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

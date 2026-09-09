from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class Belief(BaseModel):
    id: str
    statement: str
    confidence: float = Field(ge=0, le=1)
    sources: List[str] = Field(default_factory=list)
    deduction: bool = False


class BeliefChange(BaseModel):
    operation: Literal["add", "update", "remove"]
    belief_id: str
    statement: Optional[str] = None
    confidence: Optional[float] = Field(default=None, ge=0, le=1)
    evidence: List[str] = Field(default_factory=list)
    explanation: str


class LearnerProposal(BaseModel):
    reply: str
    changes: List[BeliefChange] = Field(default_factory=list)
    unresolved_questions: List[str] = Field(default_factory=list)
    reply_claims: List[Dict[str, Any]] = Field(default_factory=list)


class TeachBotStartRequest(BaseModel):
    lesson_code: str
    learner_profile: str = "blank_slate"


class TeachBotTurnRequest(BaseModel):
    session_id: str
    content: str
    request_id: str


class SnapshotRequest(BaseModel):
    name: str = "Snapshot"


class RestoreRequest(BaseModel):
    snapshot_id: str

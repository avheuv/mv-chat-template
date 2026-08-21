from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from datetime import datetime

class Message(BaseModel):
    id: str
    role: str
    content: str
    reasoning_summary: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class ChatSession(BaseModel):
    id: str
    prototype_id: str
    inputs: Dict[str, str] = Field(default_factory=dict)
    assessment_objectives: List[str] = Field(default_factory=list)
    meryl_stage: int = 1
    meryl_turn_count: int = 0
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    messages: List[Message] = []

class ChatStartRequest(BaseModel):
    prototype_id: str
    inputs: Dict[str, str] = Field(default_factory=dict)

class ChatSendRequest(BaseModel):
    session_id: str
    content: str

class ChatResponse(BaseModel):
    message: Message
    structured_data: Optional[Dict[str, Any]] = None

class RealtimeClientSecretRequest(BaseModel):
    session_id: str

class SaveScoreRequest(BaseModel):
    user_id: str
    lesson_topic: str
    score: Optional[int] = None
    engagement_score: Optional[int] = None
    summary: str
    sub_objectives: List[Dict[str, Any]] = Field(default_factory=list)

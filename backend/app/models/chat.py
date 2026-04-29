from pydantic import BaseModel, Field
from typing import List, Optional, Any, Dict
from datetime import datetime

class Message(BaseModel):
    id: str
    role: str
    content: str
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class ChatSession(BaseModel):
    id: str
    prototype_id: str
    inputs: Dict[str, str] = Field(default_factory=dict)
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

class SaveScoreRequest(BaseModel):
    user_id: str
    lesson_topic: str
    score: int
    engagement_score: int
    summary: str

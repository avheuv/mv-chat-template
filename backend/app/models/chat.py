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
    user_id: str
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    messages: List[Message] = []

class ChatStartRequest(BaseModel):
    prototype_id: str
    user_id: str

class ChatSendRequest(BaseModel):
    session_id: str
    content: str

class ChatResponse(BaseModel):
    message: Message
    structured_data: Optional[Dict[str, Any]] = None

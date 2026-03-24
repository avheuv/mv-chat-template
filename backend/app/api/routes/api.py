from fastapi import APIRouter, HTTPException
from typing import List

from app.core.prototype_loader import prototype_loader, PrototypeConfig
from app.models.chat import ChatStartRequest, ChatSession, ChatSendRequest, ChatResponse
from app.services.chat_service import chat_service

router = APIRouter()

@router.get("/health")
async def health_check():
    return {"status": "ok"}

@router.get("/api/prototypes", response_model=List[PrototypeConfig])
async def get_prototypes():
    return prototype_loader.get_all()

@router.get("/api/prototypes/{prototype_id}", response_model=PrototypeConfig)
async def get_prototype(prototype_id: str):
    prototype = prototype_loader.get_prototype(prototype_id)
    if not prototype:
        raise HTTPException(status_code=404, detail="Prototype not found")
    return prototype

@router.post("/api/chat/start", response_model=ChatSession)
async def start_chat(request: ChatStartRequest):
    try:
        session = await chat_service.start_session(request)
        return session
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/api/chat/send", response_model=ChatResponse)
async def send_chat(request: ChatSendRequest):
    try:
        response = await chat_service.send_message(request)
        return response
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

@router.get("/api/chat/session/{session_id}", response_model=ChatSession)
async def get_session(session_id: str):
    session = await chat_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session
from fastapi import APIRouter, HTTPException
from typing import List

from app.core.prototype_loader import prototype_loader, PrototypeConfig
from app.models.chat import ChatStartRequest, ChatSession, ChatSendRequest, ChatResponse
from app.services.chat_service import chat_service
from app.services.firestore_service import firestore_service

router = APIRouter()

@router.get("/health")
async def health_check():
    return {"status": "ok"}

@router.get("/api/prototypes", response_model=List[PrototypeConfig])
async def get_prototypes():
    prototypes = prototype_loader.get_all()

    # We load overrides on demand. Since fetching all overrides could be slow,
    # we'll just return the base config here. The detailed overrides happen
    # on the individual `get_prototype` and during `chat/start`.
    # Alternatively, you could fire all `get_system_prompt_override` calls in parallel.
    # To keep it performant, we only enforce the override deeply when a specific prototype is requested or chat starts.
    return prototypes

@router.get("/api/prototypes/{prototype_id}", response_model=PrototypeConfig)
async def get_prototype(prototype_id: str):
    prototype = prototype_loader.get_prototype(prototype_id)
    if not prototype:
        raise HTTPException(status_code=404, detail="Prototype not found")

    # Inject Firestore override before returning
    overrides = await firestore_service.get_prototype_overrides(
        prototype_id, prototype.systemPrompt, prototype.model
    )

    # Create a deep copy to avoid mutating the cached loader state
    # This ensures that we always read from DB instead of returning a mutated memory object
    prototype_copy = prototype.model_copy()
    prototype_copy.systemPrompt = overrides["systemPrompt"]
    prototype_copy.model = overrides["model"]

    return prototype_copy

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
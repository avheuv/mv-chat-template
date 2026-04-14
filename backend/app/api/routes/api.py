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

async def _seed_lesson_topics_if_empty():
    collection = await firestore_service.get_collection("lesson_topics")
    if not collection:
        # Seed default topics
        defaults = [
            {"id": "quadratics", "title": "Quadratic Equations", "objectives": "Understand the standard form ax^2 + bx + c = 0."},
            {"id": "biology", "title": "Cell Structure", "objectives": "Understand the function of the mitochondria."},
            {"id": "default", "title": "General Math", "objectives": "Practice core skills."}
        ]
        for item in defaults:
            doc_id = item.pop("id")
            await firestore_service.set_document("lesson_topics", doc_id, item)

async def _populate_dynamic_options(prototype: PrototypeConfig) -> PrototypeConfig:
    # Deep copy to avoid mutating cached object
    prototype_copy = prototype.model_copy(deep=True)

    for i, input_config in enumerate(prototype_copy.ui.inputs):
        if input_config.dynamicOptions:
            # Check if this requires seeding (specific to lesson_topics in this template)
            if input_config.dynamicOptions.collection == "lesson_topics":
                await _seed_lesson_topics_if_empty()

            docs = await firestore_service.get_collection(input_config.dynamicOptions.collection)
            options = []
            for doc in docs:
                label = doc.get(input_config.dynamicOptions.labelField, "Unknown")
                val = doc.get(input_config.dynamicOptions.valueField, doc.get("id"))
                options.append({"label": str(label), "value": str(val)})

            # Update the input options
            prototype_copy.ui.inputs[i].options = options

    return prototype_copy

@router.get("/api/prototypes", response_model=List[PrototypeConfig])
async def get_prototypes():
    prototypes = prototype_loader.get_all()

    # We load overrides on demand, but we MUST populate dynamic options
    populated_prototypes = []
    for p in prototypes:
        populated_prototypes.append(await _populate_dynamic_options(p))

    return populated_prototypes

@router.get("/api/prototypes/{prototype_id}", response_model=PrototypeConfig)
async def get_prototype(prototype_id: str):
    prototype = prototype_loader.get_prototype(prototype_id)
    if not prototype:
        raise HTTPException(status_code=404, detail="Prototype not found")

    populated_prototype = await _populate_dynamic_options(prototype)

    # Inject Firestore override before returning
    overrides = await firestore_service.get_prototype_overrides(
        prototype_id, populated_prototype.systemPrompt, populated_prototype.model
    )

    populated_prototype.systemPrompt = overrides["systemPrompt"]
    populated_prototype.model = overrides["model"]

    return populated_prototype

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
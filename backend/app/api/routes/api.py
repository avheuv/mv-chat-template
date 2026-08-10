from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from typing import List

from app.core.prototype_loader import prototype_loader, PrototypeConfig
import uuid
from app.models.chat import ChatStartRequest, ChatSession, ChatSendRequest, ChatResponse, SaveScoreRequest, RealtimeClientSecretRequest
from app.services.chat_service import chat_service
from app.services.course_factory_service import course_factory_service
from app.services.firestore_service import firestore_service
from app.core.config import settings
import httpx

router = APIRouter()

@router.get("/health")
async def health_check():
    return {"status": "ok"}

async def _seed_lesson_topics_if_empty():
    collection = await firestore_service.get_collection("lesson_topics")
    if not collection:
        # Seed default topics
        defaults = [
            {"id": "quadratics", "title": "Quadratic Equations", "objectives": "Understand the standard form ax^2 + bx + c = 0.", "video": {"title": "Intro to Quadratics", "url": "https://example.com/quadratics"}},
            {"id": "biology", "title": "Cell Structure", "objectives": "Understand the function of the mitochondria.", "video": {"title": "The Powerhouse of the Cell", "url": "https://example.com/mitochondria"}},
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

            # If Firestore is disabled, provide some mock options so UI doesn't break
            if not firestore_service.db and not options and input_config.dynamicOptions.collection == "lesson_topics":
                options = [
                    {"label": "Quadratic Equations", "value": "quadratics"},
                    {"label": "Cell Structure", "value": "biology"},
                    {"label": "General Math", "value": "default"}
                ]

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
        prototype_id, populated_prototype.systemPrompt, populated_prototype.model, populated_prototype.stagePrompts
    )

    populated_prototype.systemPrompt = overrides["systemPrompt"]
    populated_prototype.model = overrides["model"]
    populated_prototype.stagePrompts = overrides.get("stagePrompts")

    return populated_prototype


@router.get("/api/course-factory/stream")
async def stream_course_factory(subject: str):
    return StreamingResponse(
        course_factory_service.stream_course(subject),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@router.post("/api/chat/start", response_model=ChatSession)
async def start_chat(request: ChatStartRequest):
    try:
        session = await chat_service.start_session(request)
        return session
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Internal server error")

from pydantic import BaseModel

class AdvanceMerylRequest(BaseModel):
    session_id: str

@router.post("/api/chat/advance-meryl", response_model=ChatResponse)
async def advance_meryl(request: dict):
    try:
        session_id = request.get("session_id")
        if not session_id:
            raise ValueError("session_id is required")
        response = await chat_service.advance_meryl_stage(session_id)
        return response
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

@router.post("/api/realtime/client-secret")
async def create_realtime_client_secret(request: RealtimeClientSecretRequest):
    session = await chat_service.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    prototype = prototype_loader.get_prototype(session.prototype_id)
    if not prototype:
        raise HTTPException(status_code=404, detail="Prototype not found")

    if prototype.ui.mode not in {"voice_assessment", "sketch"}:
        raise HTTPException(status_code=400, detail="Prototype is not configured for realtime voice")

    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OpenAI API key is not configured")

    system_message = next((m for m in session.messages if m.role == "system"), None)
    instructions = system_message.content if system_message else prototype.systemPrompt
    overrides = await firestore_service.get_prototype_overrides(
        prototype.id, prototype.systemPrompt, prototype.model
    )
    model_to_use = overrides["model"]

    assessment_tools = [
        {
            "type": "function",
            "name": "update_assessment_scores",
            "description": "Update the visible assessment scores after a substantive student response.",
            "parameters": {
                "type": "object",
                "properties": {
                    "current_sub_objective_index": {"type": "integer", "minimum": 0, "maximum": 2},
                    "sub_objective_scores": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "integer", "minimum": 0, "maximum": 100}},
                    "summary": {"type": "string"},
                    "tip": {"type": "string"}
                },
                "required": ["current_sub_objective_index", "sub_objective_scores", "summary", "tip"],
                "additionalProperties": False
            }
        }
    ]

    session_config = {
        "session": {
            "type": "realtime",
            "model": model_to_use,
            "instructions": instructions,
            "audio": {
                "output": {"voice": "marin"}
            },
            "tools": assessment_tools if prototype.ui.mode == "voice_assessment" else [],
            "tool_choice": "auto"
        }
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/realtime/client_secrets",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json"
                },
                json=session_config
            )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        detail = e.response.text or "Failed to create realtime client secret"
        raise HTTPException(status_code=e.response.status_code, detail=detail)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create realtime client secret: {str(e)}")

@router.get("/api/chat/session/{session_id}", response_model=ChatSession)
async def get_session(session_id: str):
    session = await chat_service.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session

@router.post("/api/chat/save-score")
async def save_score(request: SaveScoreRequest):
    try:
        if not firestore_service.db:
            return {"status": "mock_saved", "message": "Firestore disabled, score logged."}

        from google.cloud import firestore
        assessment_id = str(uuid.uuid4())
        payload = {
            "lesson_topic": request.lesson_topic,
            "score": request.score,
            "engagement_score": request.engagement_score,
            "summary": request.summary,
            "sub_objectives": request.sub_objectives,
            "created_at": firestore.SERVER_TIMESTAMP
        }

        await firestore_service.set_document(
            f"users/{request.user_id}/assessments",
            assessment_id,
            payload
        )
        return {"status": "success", "assessment_id": assessment_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save score: {str(e)}")
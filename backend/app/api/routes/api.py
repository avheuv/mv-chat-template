from fastapi import APIRouter, HTTPException
from typing import List

from app.core.prototype_loader import prototype_loader, PrototypeConfig
import uuid
from app.models.chat import ChatStartRequest, ChatSession, ChatSendRequest, ChatResponse, SaveScoreRequest, RealtimeClientSecretRequest
from app.services.chat_service import chat_service
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

@router.post("/api/realtime/client-secret")
async def create_realtime_client_secret(request: RealtimeClientSecretRequest):
    session = await chat_service.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    prototype = prototype_loader.get_prototype(session.prototype_id)
    if not prototype:
        raise HTTPException(status_code=404, detail="Prototype not found")

    if prototype.ui.mode != "voice_assessment":
        raise HTTPException(status_code=400, detail="Prototype is not configured for realtime voice assessment")

    if not settings.openai_api_key:
        raise HTTPException(status_code=500, detail="OpenAI API key is not configured")

    system_message = next((m for m in session.messages if m.role == "system"), None)
    instructions = system_message.content if system_message else prototype.systemPrompt
    overrides = await firestore_service.get_prototype_overrides(
        prototype.id, prototype.systemPrompt, prototype.model
    )
    model_to_use = overrides["model"]

    session_config = {
        "session": {
            "type": "realtime",
            "model": model_to_use,
            "instructions": instructions,
            "audio": {
                "output": {"voice": "marin"}
            },
            "tools": [
                {
                    "type": "function",
                    "name": "update_assessment_scores",
                    "description": "Update the visible assessment scores after a substantive student response.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "current_sub_objective_index": {
                                "type": "integer",
                                "description": "Zero-based index of the current sub-objective being assessed.",
                                "minimum": 0,
                                "maximum": 2
                            },
                            "sub_objective_scores": {
                                "type": "array",
                                "description": "Exactly three student understanding scores from 0 to 100, one for each sequenced sub-objective. Keep future objective scores at 0 until assessed.",
                                "minItems": 3,
                                "maxItems": 3,
                                "items": {
                                    "type": "integer",
                                    "minimum": 0,
                                    "maximum": 100
                                }
                            },
                            "summary": {
                                "type": "string",
                                "description": "Brief evaluative summary of the student's understanding so far."
                            },
                            "tip": {
                                "type": "string",
                                "description": "Instructional nudge of 20 words or less."
                            }
                        },
                        "required": ["current_sub_objective_index", "sub_objective_scores", "summary", "tip"],
                        "additionalProperties": False
                    }
                }
            ],
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
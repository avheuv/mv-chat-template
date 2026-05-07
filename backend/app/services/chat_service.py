import uuid
import json
from typing import Dict, Any, List, Optional
from datetime import datetime

from app.models.chat import ChatSession, Message, ChatStartRequest, ChatSendRequest, ChatResponse
from app.core.prototype_loader import prototype_loader
from app.services.llm_service import llm_service
from app.services.firestore_service import firestore_service
from app.context_builders.registry import registry as context_registry
from app.save_handlers.registry import registry as save_registry

def normalize_question(text: str) -> str:
    text = text.lower().strip()
    for char in ["?", ".", ",", "!", ":", ";"]:
        text = text.replace(char, "")
    return text

def is_repeated_question(new_question: str, previous_questions: List[str]) -> bool:
    normalized_new = normalize_question(new_question)
    new_words = set(normalized_new.split())

    for old_question in previous_questions:
        normalized_old = normalize_question(old_question)
        old_words = set(normalized_old.split())

        if normalized_new == normalized_old:
            return True

        if not new_words or not old_words:
            continue

        overlap = len(new_words & old_words) / len(new_words | old_words)

        if overlap > 0.65:
            return True

    return False

class ChatService:
    async def start_session(self, request: ChatStartRequest) -> ChatSession:
        prototype = prototype_loader.get_prototype(request.prototype_id)
        if not prototype:
            raise ValueError(f"Prototype {request.prototype_id} not found")

        session_id = str(uuid.uuid4())
        session = ChatSession(
            id=session_id,
            prototype_id=request.prototype_id,
            inputs=request.inputs,
            messages=[]
        )

        # Initialize Assessment State if this is the chat_based_assessment prototype
        if request.prototype_id == "chat_based_assessment":
            lesson_code = request.inputs.get("lesson_code", "default")
            doc = await firestore_service.get_document("lesson_topics", lesson_code) if firestore_service.db else None

            title = doc.get("title", "Unknown Lesson") if doc else "Unknown Lesson"
            objectives = doc.get("objectives", "No objectives provided.") if doc else "No objectives provided."
            concept_targets = doc.get("concept_targets", []) if doc else []

            session.assessment_state = {
                "session_id": session_id,
                "student_name": request.inputs.get("user_id", "Unknown"),
                "lesson_topic": title,
                "objectives": objectives,
                "concept_targets": concept_targets,
                "question_history": [],
                "concept_scores": [
                    {"concept_id": t.get("concept_id"), "score": 0, "evidence": ""} for t in concept_targets
                ],
                "current_score": 40
            }

        # Load Overrides from Firestore
        overrides = await firestore_service.get_prototype_overrides(
            request.prototype_id, prototype.systemPrompt, prototype.model
        )

        # Build Context String if needed
        context_parts = []
        for source in prototype.contextSources:
            builder = context_registry.get(source)
            if builder:
                part = await builder(request.inputs, session_id)
                context_parts.append(f"[{source}]\n{part}")
            else:
                print(f"Warning: Context builder '{source}' not found.")

        # Create the system prompt using the override
        system_content = overrides["systemPrompt"]
        model_to_use = overrides["model"]
        if context_parts:
            system_content += "\n\n--- BACKGROUND CONTEXT ---\n" + "\n\n".join(context_parts)

        system_message = Message(
            id=str(uuid.uuid4()),
            role="system",
            content=system_content
        )

        session.messages.append(system_message)

        # If an initialMessagePrompt exists, let's trigger the LLM to write the first greeting.
        if prototype.initialMessagePrompt:
            # We temporarily append the prompt as a user message to trigger the greeting
            # without confusing the AI's internal state logic.
            trigger_message = Message(
                id=str(uuid.uuid4()),
                role="user",
                content=prototype.initialMessagePrompt
            )
            session.messages.append(trigger_message)

            # Prepare messages for LLM
            llm_messages = [{"role": m.role, "content": m.content} for m in session.messages]

            # Call LLM
            content, structured_data = await llm_service.generate_response(
                messages=llm_messages,
                model=model_to_use,
                temperature=prototype.temperature,
                max_tokens=prototype.maxTokens,
                output_schema=prototype.outputSpec
            )

            # Remove the hidden trigger prompt so the user never sees it in the chat history
            session.messages.pop()

            if not content and structured_data and "reply" in structured_data:
                content = structured_data["reply"]

            # Append the assistant's generated personalized greeting
            assistant_greeting = Message(
                id=str(uuid.uuid4()),
                role="assistant",
                content=content
            )
            session.messages.append(assistant_greeting)

        # Save session to Firestore
        await firestore_service.set_document("sessions", session_id, session.dict())

        return session

    async def get_session(self, session_id: str) -> Optional[ChatSession]:
        data = await firestore_service.get_document("sessions", session_id)
        if data:
            return ChatSession(**data)
        return None

    async def send_message(self, request: ChatSendRequest) -> ChatResponse:
        session = await self.get_session(request.session_id)
        if not session:
            raise ValueError(f"Session {request.session_id} not found")

        prototype = prototype_loader.get_prototype(session.prototype_id)
        if not prototype:
            raise ValueError(f"Prototype {session.prototype_id} not found")

        # Append user message
        user_message = Message(
            id=str(uuid.uuid4()),
            role="user",
            content=request.content
        )
        session.messages.append(user_message)

        # Prepare messages for LLM
        # We only send system, user, and assistant roles.
        llm_messages = [{"role": m.role, "content": m.content} for m in session.messages]

        # Inject assessment state into the last user message if applicable
        if prototype.id == "chat_based_assessment" and session.assessment_state:
            state_json = json.dumps(session.assessment_state, indent=2)
            llm_messages[-1]["content"] += f"\n\n--- CURRENT ASSESSMENT STATE ---\n{state_json}"
            print(f"DEBUG: Injecting assessment state for session {session.id}:\n{state_json}")

        # Fetch model override dynamically
        overrides = await firestore_service.get_prototype_overrides(
            prototype.id, prototype.systemPrompt, prototype.model
        )

        content = None
        structured_data = None

        if prototype.id == "chat_based_assessment":
            max_retries = 3
            retry_count = 0

            while retry_count < max_retries:
                content, structured_data = await llm_service.generate_response(
                    messages=llm_messages,
                    model=overrides["model"],
                    temperature=prototype.temperature,
                    max_tokens=prototype.maxTokens,
                    output_schema=prototype.outputSpec
                )

                if structured_data and "next_question" in structured_data:
                    next_question = structured_data["next_question"]
                    previous_questions = [q["question_text"] for q in session.assessment_state.get("question_history", [])]

                    if is_repeated_question(next_question, previous_questions):
                        print(f"DEBUG: Rejected repeated question: {next_question}")
                        llm_messages.append({"role": "system", "content": "The previous question was too similar to one already asked. Please ask a different question targeting a concept that still needs evidence."})
                        retry_count += 1
                        continue
                    else:
                        break # Valid question
                else:
                    print("DEBUG: Missing 'next_question' in structured output, retrying...")
                    llm_messages.append({"role": "system", "content": "Your structured output was missing 'next_question'. Please provide a valid structured response."})
                    retry_count += 1

            if retry_count == max_retries:
                raise ValueError("Failed to generate a valid, non-repeated question after multiple attempts.")

            # Calculate overall score and update state
            if structured_data and "updated_concept_scores" in structured_data:
                scores = structured_data["updated_concept_scores"]

                # Validation of scores
                for s in scores:
                    if s["score"] not in [0, 1, 2]:
                        s["score"] = max(0, min(2, s["score"])) # Clamp

                session.assessment_state["concept_scores"] = scores

                total_points = sum(s["score"] for s in scores)
                max_points = 6
                current_score = round(40 + (total_points / max_points) * 60)
                session.assessment_state["current_score"] = current_score

                # Update the previous question with the student's reply
                if session.assessment_state["question_history"]:
                    session.assessment_state["question_history"][-1]["student_reply"] = request.content

                # Append the new question to the history
                target_id = structured_data.get("next_question_target", "Unknown")
                session.assessment_state["question_history"].append({
                    "question_id": f"q{len(session.assessment_state['question_history']) + 1}",
                    "question_text": structured_data["next_question"],
                    "student_reply": "",
                    "concept_target": target_id
                })

                # Map fields so frontend continues to work
                content = structured_data["next_question"]
                structured_data["reply"] = structured_data["next_question"]
                structured_data["score"] = current_score

        else:
            # Standard flow for other prototypes
            content, structured_data = await llm_service.generate_response(
                messages=llm_messages,
                model=overrides["model"],
                temperature=prototype.temperature,
                max_tokens=prototype.maxTokens,
                output_schema=prototype.outputSpec
            )

            if not content and structured_data and "reply" in structured_data:
                content = structured_data["reply"]

        # Append assistant message
        assistant_message = Message(
            id=str(uuid.uuid4()),
            role="assistant",
            content=content
        )
        session.messages.append(assistant_message)

        # Handle Save Handlers
        if prototype.saveHandler and structured_data:
            handler = save_registry.get(prototype.saveHandler)
            if handler:
                try:
                    user_id = session.inputs.get("user_id", "unknown")
                    await handler(session.id, user_id, prototype.id, structured_data)
                except Exception as e:
                    print(f"Error in save handler {prototype.saveHandler}: {e}")
            else:
                print(f"Warning: Save handler '{prototype.saveHandler}' not found.")

        # Save updated session
        await firestore_service.set_document("sessions", session.id, session.dict())

        return ChatResponse(
            message=assistant_message,
            structured_data=structured_data
        )

chat_service = ChatService()
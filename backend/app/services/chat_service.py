import uuid
from typing import Dict, Any, List, Optional
from datetime import datetime

from app.models.chat import ChatSession, Message, ChatStartRequest, ChatSendRequest, ChatResponse
from app.core.prototype_loader import prototype_loader
from app.services.llm_service import llm_service
from app.services.firestore_service import firestore_service
from app.context_builders.registry import registry as context_registry
from app.save_handlers.registry import registry as save_registry

class ChatService:
    def __init__(self):
        self._local_sessions: Dict[str, ChatSession] = {}

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

        # Load Overrides from Firestore
        overrides = await firestore_service.get_prototype_overrides(
            request.prototype_id, prototype.systemPrompt, prototype.model, prototype.stagePrompts
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

        # Inject meryl stage prompt if applicable
        if prototype.ui.mode == "meryl" and overrides.get("stagePrompts"):
            stage_prompt = overrides["stagePrompts"].get(str(session.meryl_stage))
            if stage_prompt:
                system_content = stage_prompt

        if context_parts:
            system_content += "\n\n--- BACKGROUND CONTEXT ---\n" + "\n\n".join(context_parts)

        if prototype.ui.mode == "voice_assessment":
            lesson_context = next((part for part in context_parts if part.startswith("[fetchLessonData]")), "")
            sub_objective_model = model_to_use if not model_to_use.startswith("gpt-realtime") else "gpt-4o"
            session.assessment_objectives = await llm_service.generate_sub_objectives(
                lesson_context or system_content,
                model=sub_objective_model
            )
            objectives_text = "\n".join(f"{index + 1}. {objective}" for index, objective in enumerate(session.assessment_objectives))
            system_content += (
                "\n\n--- ASSESSMENT SUB-OBJECTIVES ---\n"
                f"{objectives_text}\n\n"
                "Assess these objectives in order. Focus only on the current objective until the student scores at least 85 on it, "
                "then acknowledge mastery and move to the next objective. Do not mark future objectives as mastered early."
            )

        system_message = Message(
            id=str(uuid.uuid4()),
            role="system",
            content=system_content
        )

        session.messages.append(system_message)

        # If an initialMessagePrompt exists, let's trigger the LLM to write the first greeting.
        if prototype.initialMessagePrompt:
            if prototype.ui.mode == "twenty_questions":
                content, reasoning_summary, response_id = await llm_service.generate_twenty_questions_turn(
                    model=model_to_use,
                    instructions=system_content,
                    input_text=prototype.initialMessagePrompt,
                    previous_response_id=None,
                    reasoning=prototype.reasoning or {},
                    max_tokens=prototype.maxTokens,
                )
                session.previous_response_id = response_id
                session.question_count = 1
                session.messages.append(Message(
                    id=str(uuid.uuid4()), role="assistant", content=content,
                    reasoning_summary=reasoning_summary
                ))
            else:
                # Temporarily add the trigger without exposing it in chat history.
                trigger_message = Message(
                    id=str(uuid.uuid4()),
                    role="user",
                    content=prototype.initialMessagePrompt
                )
                session.messages.append(trigger_message)
                llm_messages = [{"role": m.role, "content": m.content} for m in session.messages]
                content, structured_data, _, reasoning_summary = await llm_service.generate_response(
                    messages=llm_messages,
                    model=model_to_use,
                    temperature=prototype.temperature,
                    max_tokens=prototype.maxTokens,
                    output_schema=prototype.outputSpec,
                    tools=prototype.tools,
                    reasoning=prototype.reasoning
                )
                session.messages.pop()
                if not content and structured_data and "reply" in structured_data:
                    content = structured_data["reply"]
                session.messages.append(Message(
                    id=str(uuid.uuid4()),
                    role="assistant",
                    content=content,
                    reasoning_summary=reasoning_summary
                ))

        # Save session to Firestore (and locally for fallback)
        self._local_sessions[session_id] = session
        await firestore_service.set_document("sessions", session_id, session.dict())

        return session

    async def get_session(self, session_id: str) -> Optional[ChatSession]:
        data = await firestore_service.get_document("sessions", session_id)
        if data:
            return ChatSession(**data)
        return self._local_sessions.get(session_id)

    async def send_message(self, request: ChatSendRequest) -> ChatResponse:
        session = await self.get_session(request.session_id)
        if not session:
            raise ValueError(f"Session {request.session_id} not found")

        prototype = prototype_loader.get_prototype(session.prototype_id)
        if not prototype:
            raise ValueError(f"Prototype {session.prototype_id} not found")

        # Append user message
        if prototype.ui.mode == "twenty_questions" and request.content not in {"Yes", "No"}:
            raise ValueError("20 Questions answers must be Yes or No.")
        if prototype.ui.mode == "twenty_questions" and session.question_count >= 20:
            raise ValueError("This game has reached Question 20. Start a new game to play again.")

        user_message = Message(
            id=str(uuid.uuid4()),
            role="user",
            content=request.content
        )
        session.messages.append(user_message)

        if prototype.ui.mode == "twenty_questions":
            overrides = await firestore_service.get_prototype_overrides(
                prototype.id, prototype.systemPrompt, prototype.model, prototype.stagePrompts
            )
            instructions = next(m.content for m in session.messages if m.role == "system")
            content, reasoning_summary, response_id = await llm_service.generate_twenty_questions_turn(
                model=overrides["model"], instructions=instructions, input_text=request.content,
                previous_response_id=session.previous_response_id,
                reasoning=prototype.reasoning or {}, max_tokens=prototype.maxTokens,
            )
            session.previous_response_id = response_id
            session.question_count += 1
            assistant_message = Message(
                id=str(uuid.uuid4()), role="assistant", content=content,
                reasoning_summary=reasoning_summary
            )
            session.messages.append(assistant_message)
            self._local_sessions[session.id] = session
            await firestore_service.set_document("sessions", session.id, session.dict())
            return ChatResponse(message=assistant_message)

        # Increment Meryl turn count
        if prototype.ui.mode == "meryl":
            session.meryl_turn_count += 1

        # Prepare messages for LLM
        # We only send system, user, and assistant roles.
        llm_messages = [{"role": m.role, "content": m.content} for m in session.messages]

        # Fetch model override dynamically (so it works even if we restart or clear cache)
        # Note: system prompt is fixed during start_session, but model can be dynamic per turn
        overrides = await firestore_service.get_prototype_overrides(
            prototype.id, prototype.systemPrompt, prototype.model, prototype.stagePrompts
        )

        # If it's Meryl and we need to update the system prompt for the new stage
        if prototype.ui.mode == "meryl" and overrides.get("stagePrompts"):
            system_msg_index = next((i for i, m in enumerate(session.messages) if m.role == "system"), None)
            if system_msg_index is not None:
                stage_prompt = overrides["stagePrompts"].get(str(session.meryl_stage))
                if stage_prompt:
                    # Look for background context to re-append
                    bg_context = ""
                    if "--- BACKGROUND CONTEXT ---" in session.messages[system_msg_index].content:
                        bg_context = "\n\n--- BACKGROUND CONTEXT ---\n" + session.messages[system_msg_index].content.split("--- BACKGROUND CONTEXT ---")[1].strip()
                    session.messages[system_msg_index].content = stage_prompt + bg_context

        # Re-build llm_messages because we might have just updated the system prompt
        llm_messages = [{"role": m.role, "content": m.content} for m in session.messages]

        # Inject a hidden instruction if the user just unlocked the Next Stage button
        if prototype.ui.mode == "meryl" and getattr(session, "meryl_turn_count", 0) == 3 and session.meryl_stage < 3:
            llm_messages.append({
                "role": "system",
                "content": "The student has completed enough turns in this stage. At the end of your response, explicitly let them know they can click the 'Next Stage' button below when they feel ready to move on, or they can keep practicing here."
            })
        elif prototype.ui.mode == "meryl" and getattr(session, "meryl_turn_count", 0) == 3 and session.meryl_stage == 3:
             llm_messages.append({
                "role": "system",
                "content": "The student has completed enough turns in this final stage. At the end of your response, explicitly let them know they can click the 'End Lesson' button below to conclude the lesson."
            })

        # Call LLM (Note: Meryl no longer uses tools, so we just pass what the prototype has)
        content, structured_data, tool_name_called, reasoning_summary = await llm_service.generate_response(
            messages=llm_messages,
            model=overrides["model"],
            temperature=prototype.temperature,
            max_tokens=prototype.maxTokens,
            output_schema=prototype.outputSpec,
            tools=prototype.tools,
            reasoning=prototype.reasoning
        )

        # If the output schema requires 'reply', LLM service might not populate content
        # Check if structured_data has a 'reply' string to use as the actual message content
        if not content and structured_data and "reply" in structured_data:
            content = structured_data["reply"]

        if not content:
            content = "Great! Let's continue to the next stage."

        # Append assistant message
        assistant_message = Message(
            id=str(uuid.uuid4()),
            role="assistant",
            content=content,
            reasoning_summary=reasoning_summary
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
        self._local_sessions[session.id] = session
        self._local_sessions[session.id] = session
        await firestore_service.set_document("sessions", session.id, session.dict())

        return ChatResponse(
            message=assistant_message,
            structured_data=structured_data
        )

    async def advance_meryl_stage(self, session_id: str) -> ChatResponse:
        session = await self.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        prototype = prototype_loader.get_prototype(session.prototype_id)
        if not prototype or prototype.ui.mode != "meryl":
            raise ValueError("Invalid prototype for this action.")

        # Ensure they have had enough turns and aren't already at the end
        if session.meryl_turn_count < 3 or session.meryl_stage > 3:
            raise ValueError("Cannot advance stage yet.")

        # Advance stage and reset turn count
        session.meryl_stage += 1
        session.meryl_turn_count = 0

        # Load Overrides from Firestore to get dynamic prompts
        overrides = await firestore_service.get_prototype_overrides(
            prototype.id, prototype.systemPrompt, prototype.model, prototype.stagePrompts
        )

        # Update System Prompt in history for the next pass
        system_msg_index = next((i for i, m in enumerate(session.messages) if m.role == "system"), None)
        if system_msg_index is not None and overrides.get("stagePrompts"):
            stage_prompt = overrides["stagePrompts"].get(str(session.meryl_stage))
            if stage_prompt:
                bg_context = ""
                if "--- BACKGROUND CONTEXT ---" in session.messages[system_msg_index].content:
                    bg_context = "\n\n--- BACKGROUND CONTEXT ---\n" + session.messages[system_msg_index].content.split("--- BACKGROUND CONTEXT ---")[1].strip()
                session.messages[system_msg_index].content = stage_prompt + bg_context

        # Trigger LLM to get the transitional text now that the stage is updated
        llm_messages = [{"role": m.role, "content": m.content} for m in session.messages]

        # Inject instruction so it transitions smoothly
        if session.meryl_stage == 4:
            trigger_content = "The student has clicked 'End Lesson'. Please provide a brief concluding message to wrap up the learning session. Congratulate them on their effort."
            fallback_content = "Great job today! You've successfully completed the lesson. Feel free to keep chatting if you have more questions."
        else:
            stage_names = {2: "Demonstration", 3: "Application"}
            new_stage_name = stage_names.get(session.meryl_stage, str(session.meryl_stage))
            trigger_content = f"The student is ready to move on. Please acknowledge the transition to the {new_stage_name} stage and begin the next stage of instruction."
            fallback_content = f"Great! Let's continue to the {new_stage_name} stage."

        # Using role='system' ensures this specific trigger instruction is hidden from the frontend UI
        trigger_message = Message(
            id=str(uuid.uuid4()),
            role="system",
            content=trigger_content
        )
        session.messages.append(trigger_message)
        llm_messages.append({"role": "system", "content": trigger_message.content})

        content, structured_data, _, reasoning_summary = await llm_service.generate_response(
            messages=llm_messages,
            model=overrides["model"],
            temperature=prototype.temperature,
            max_tokens=prototype.maxTokens,
            output_schema=prototype.outputSpec,
            tools=None,
            reasoning=prototype.reasoning
        )

        if not content and structured_data and "reply" in structured_data:
            content = structured_data["reply"]

        if not content:
            content = fallback_content

        # Append assistant message
        assistant_message = Message(
            id=str(uuid.uuid4()),
            role="assistant",
            content=content,
            reasoning_summary=reasoning_summary
        )
        session.messages.append(assistant_message)

        # Save updated session
        await firestore_service.set_document("sessions", session.id, session.dict())

        return ChatResponse(
            message=assistant_message,
            structured_data=structured_data
        )

chat_service = ChatService()

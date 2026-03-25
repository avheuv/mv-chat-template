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

        # Load System Prompt Override from Firestore
        override_prompt = await firestore_service.get_system_prompt_override(
            request.prototype_id, prototype.systemPrompt
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
        system_content = override_prompt
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
                model=prototype.model,
                temperature=prototype.temperature,
                max_tokens=prototype.maxTokens,
                output_schema=prototype.outputSpec
            )

            # Remove the hidden trigger prompt so the user never sees it in the chat history
            session.messages.pop()

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

        # Call LLM
        content, structured_data = await llm_service.generate_response(
            messages=llm_messages,
            model=prototype.model,
            temperature=prototype.temperature,
            max_tokens=prototype.maxTokens,
            output_schema=prototype.outputSpec
        )

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
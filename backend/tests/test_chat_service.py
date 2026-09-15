import asyncio

from app.models.chat import ChatStartRequest
from app.services.chat_service import ChatService


def test_static_initial_message_does_not_call_model(monkeypatch):
    service = ChatService()
    model_was_called = False

    async def overrides(*args, **kwargs):
        return {"systemPrompt": args[1], "model": args[2], "stagePrompts": {}}

    async def save(*args, **kwargs):
        return None

    async def generate(*args, **kwargs):
        nonlocal model_was_called
        model_was_called = True
        raise AssertionError("A static opening message must not call the model")

    monkeypatch.setattr(
        "app.services.chat_service.firestore_service.get_prototype_overrides", overrides
    )
    monkeypatch.setattr("app.services.chat_service.firestore_service.set_document", save)
    monkeypatch.setattr("app.services.chat_service.llm_service.generate_response", generate)

    session = asyncio.run(
        service.start_session(ChatStartRequest(prototype_id="pip", inputs={}))
    )

    assert model_was_called is False
    assert [message.role for message in session.messages] == ["system", "assistant"]
    assert session.messages[-1].content == (
        "“What makes something alive? Give me a definition, and I’ll see what qualifies.”"
    )

import asyncio

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.core.prototype_loader import prototype_loader
from app.models.turning_test import TurningTestAIRequest, TurningTestRewriteRequest
from app.services import turning_test_service as service


@pytest.fixture(autouse=True)
def turning_test_config(monkeypatch):
    config = prototype_loader.get_prototype("turning_test").config.copy()
    config["openaiModel"] = prototype_loader.get_prototype("turning_test").model

    async def get_config():
        return config

    monkeypatch.setattr(service, "get_turning_test_config", get_config)
    return config


def test_count_words_ignores_repeated_whitespace():
    assert service.count_words(" one   two\n\tthree ") == 3
    assert service.count_words(" \n\t ") == 0


def test_generate_prompt_requests_approximately_450_words():
    request = TurningTestAIRequest(
        prompt_id="science", question="Why is the sky blue?"
    )

    messages = service._input(request)

    assert "approximately 450 words" in messages[0]["content"]
    assert "Why is the sky blue?" in messages[1]["content"]


def test_corrective_generate_prompt_uses_accepted_word_range():
    request = TurningTestAIRequest(
        prompt_id="science", question="Why is the sky blue?"
    )

    messages = service._input(request, corrective=True)

    assert "400–500 words" in messages[0]["content"]


def test_generation_request_rejects_removed_rewrite_fields():
    with pytest.raises(ValidationError):
        TurningTestAIRequest(
            prompt_id="science",
            question="Why is the sky blue?",
            action="rewrite",
            answer="Selected text",
            custom_prompt="Use shorter sentences.",
        )


@pytest.mark.parametrize("word_count", [400, 500])
def test_generate_accepts_word_count_boundaries(monkeypatch, word_count):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")

    class Response:
        output_text = "word " * word_count

    async def create(**kwargs):
        return Response()

    monkeypatch.setattr(service.client.responses, "create", create)
    request = TurningTestAIRequest(
        prompt_id="science", question="A question"
    )

    _, returned_word_count, _ = asyncio.run(service.generate_starting_text(request))

    assert returned_word_count == word_count


@pytest.mark.parametrize(
    ("action", "instruction"),
    [
        (
            "light_polish",
            "Make only small improvements to the selected text. Fix grammar, awkward phrasing, and minor word-choice issues while preserving the original sentence structure, tone, meaning, and as much of the original wording as possible.",
        ),
        (
            "improve_clarity",
            "Revise the selected text to make it clearer, smoother, and easier to read. You may change wording and sentence structure, but preserve the original meaning, tone, and level of detail. Make moderate changes rather than completely rewriting the passage.",
        ),
        (
            "major_rewrite",
            "Substantially rewrite the selected text to improve clarity, flow, and overall quality. Preserve the core meaning and important details, but feel free to significantly change wording, sentence structure, organization, and style.",
        ),
    ],
)
def test_rewrite_uses_exact_action_prompt_and_selected_text(monkeypatch, action, instruction):
    monkeypatch.setattr(settings, "openai_api_key", "test-key")
    captured = {}

    class Response:
        output_text = "Revised selection."

    async def create(**kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(service.client.responses, "create", create)
    request = TurningTestRewriteRequest(action=action, selected_text="Original selection.")

    result = asyncio.run(service.rewrite_selected_text(request))

    assert result == ("Revised selection.", "gpt-4o-mini")
    assert service.REWRITE_INSTRUCTIONS[action] == instruction
    assert captured["input"][0]["content"] == (
        instruction
        + " Return only the revised text, with no preamble, quotes, commentary, or Markdown."
    )
    assert captured["input"][1]["content"] == (
        "<selected_text>\nOriginal selection.\n</selected_text>"
    )


def test_pangram_defaults_to_current_text_api():
    config = prototype_loader.get_prototype("turning_test").config
    assert config["pangramApiBaseUrl"] == "https://text.external-api.pangram.com"
    assert config["pangramModel"] == "pangram-4"
    assert prototype_loader.get_prototype("turning_test").model == "gpt-4o-mini"
    assert config["evaluationMinWords"] == 50


def test_submit_pangram_uses_current_endpoint_and_api_key_header(monkeypatch, turning_test_config):
    monkeypatch.setattr(settings, "pangram_api_key", "test-key")
    turning_test_config["evaluationMinWords"] = 2
    request = {}

    async def fake_post(self, url, **kwargs):
        request.update(url=url, **kwargs)
        return httpx.Response(200, json={"task_id": "task-1"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    task_id, payload, model = asyncio.run(service.submit_pangram("enough words"))

    assert task_id == "task-1"
    assert payload == {"task_id": "task-1"}
    assert model == "pangram-4"
    assert request["url"] == "https://text.external-api.pangram.com/task"
    assert request["headers"] == {"x-api-key": "test-key", "Content-Type": "application/json"}
    assert request["json"] == {"text": "enough words", "model": "pangram-4"}


def test_get_pangram_task_uses_current_endpoint_and_api_key_header(monkeypatch):
    monkeypatch.setattr(settings, "pangram_api_key", "test-key")
    request = {}

    async def fake_get(self, url, **kwargs):
        request.update(url=url, **kwargs)
        return httpx.Response(200, json={"stage": "STAGE_SUCCESS"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    assert asyncio.run(service.get_pangram_task("task-1")) == ({"stage": "STAGE_SUCCESS"}, "pangram-4")
    assert request["url"] == "https://text.external-api.pangram.com/task/task-1"
    assert request["headers"] == {"x-api-key": "test-key", "Content-Type": "application/json"}


def test_failed_pangram_task_is_an_error(monkeypatch, turning_test_config):
    monkeypatch.setattr(settings, "pangram_api_key", "test-key")
    turning_test_config["pangramModel"] = "test-model"

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json={"stage": "STAGE_FAILED", "error": "provider failure"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    with pytest.raises(service.TurningTestError, match="could not complete"):
        asyncio.run(service.get_pangram_task("task-1"))


def test_success_response_is_preserved_including_zero_false_and_extra_fields(monkeypatch, turning_test_config):
    monkeypatch.setattr(settings, "pangram_api_key", "test-key")
    turning_test_config["pangramModel"] = "test-model"
    payload = {
        "stage": "STAGE_SUCCESS", "fraction_ai": 0, "is_humanized": False,
        "extra_future_field": {"kept": True},
    }

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    assert asyncio.run(service.get_pangram_task("task-1")) == (payload, "test-model")


def test_provider_validation_error_includes_pangram_detail():
    response = httpx.Response(
        422,
        json={"detail": "model must be pangram-4"},
        request=httpx.Request("POST", "https://text.external-api.pangram.com/task"),
    )

    error = service._provider_error(response)

    assert error.status_code == 502
    assert str(error) == "Pangram rejected the request (HTTP 422). model must be pangram-4"

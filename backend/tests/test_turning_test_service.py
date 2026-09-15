import asyncio

import httpx
import pytest

from app.core.config import settings
from app.services import turning_test_service as service


def test_count_words_ignores_repeated_whitespace():
    assert service.count_words(" one   two\n\tthree ") == 3
    assert service.count_words(" \n\t ") == 0


def test_pangram_defaults_to_current_text_api():
    assert settings.pangram_api_base_url == "https://text.external-api.pangram.com"
    assert settings.pangram_model == "pangram-4"


def test_submit_pangram_uses_current_endpoint_and_api_key_header(monkeypatch):
    monkeypatch.setattr(settings, "pangram_api_key", "test-key")
    monkeypatch.setattr(settings, "pangram_model", "pangram-4")
    monkeypatch.setattr(settings, "turning_test_evaluation_min_words", 2)
    request = {}

    async def fake_post(self, url, **kwargs):
        request.update(url=url, **kwargs)
        return httpx.Response(200, json={"task_id": "task-1"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    task_id, payload = asyncio.run(service.submit_pangram("enough words"))

    assert task_id == "task-1"
    assert payload == {"task_id": "task-1"}
    assert request["url"] == "https://text.external-api.pangram.com/task"
    assert request["headers"] == {"x-api-key": "test-key", "Content-Type": "application/json"}
    assert request["json"] == {"text": "enough words", "model": "pangram-4"}


def test_get_pangram_task_uses_current_endpoint_and_api_key_header(monkeypatch):
    monkeypatch.setattr(settings, "pangram_api_key", "test-key")
    monkeypatch.setattr(settings, "pangram_model", "pangram-4")
    request = {}

    async def fake_get(self, url, **kwargs):
        request.update(url=url, **kwargs)
        return httpx.Response(200, json={"stage": "STAGE_SUCCESS"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    assert asyncio.run(service.get_pangram_task("task-1")) == {"stage": "STAGE_SUCCESS"}
    assert request["url"] == "https://text.external-api.pangram.com/task/task-1"
    assert request["headers"] == {"x-api-key": "test-key", "Content-Type": "application/json"}


def test_failed_pangram_task_is_an_error(monkeypatch):
    monkeypatch.setattr(settings, "pangram_api_key", "test-key")
    monkeypatch.setattr(settings, "pangram_model", "test-model")

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json={"stage": "STAGE_FAILED", "error": "provider failure"}, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    with pytest.raises(service.TurningTestError, match="could not complete"):
        asyncio.run(service.get_pangram_task("task-1"))


def test_success_response_is_preserved_including_zero_false_and_extra_fields(monkeypatch):
    monkeypatch.setattr(settings, "pangram_api_key", "test-key")
    monkeypatch.setattr(settings, "pangram_model", "test-model")
    payload = {
        "stage": "STAGE_SUCCESS", "fraction_ai": 0, "is_humanized": False,
        "extra_future_field": {"kept": True},
    }

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    assert asyncio.run(service.get_pangram_task("task-1")) == payload


def test_provider_validation_error_includes_pangram_detail():
    response = httpx.Response(
        422,
        json={"detail": "model must be pangram-4"},
        request=httpx.Request("POST", "https://text.external-api.pangram.com/task"),
    )

    error = service._provider_error(response)

    assert error.status_code == 502
    assert str(error) == "Pangram rejected the request (HTTP 422). model must be pangram-4"

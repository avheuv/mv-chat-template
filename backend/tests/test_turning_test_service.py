import asyncio

import httpx
import pytest

from app.core.config import settings
from app.services import turning_test_service as service


def test_count_words_ignores_repeated_whitespace():
    assert service.count_words(" one   two\n\tthree ") == 3
    assert service.count_words(" \n\t ") == 0


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

from typing import Any, Dict

import httpx

from app.core.config import settings
from app.core.prototype_loader import prototype_loader
from app.models.turning_test import TurningTestAIRequest
from app.services.firestore_service import firestore_service
from app.services.llm_service import client


def count_words(text: str) -> int:
    return len(text.strip().split()) if text.strip() else 0


class TurningTestError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


ACTION_INSTRUCTIONS = {
    "generate": (
        "Write a clear, accurate answer to the academic question in approximately 300 words. Use ordinary "
        "language suitable for a general audience. Include useful examples or explanation where appropriate."
    ),
    "rewrite": (
        "Rewrite only the highlighted passage according to the user's rewrite instructions. Preserve its core meaning "
        "and keep the result proportionate to the selected passage unless the user explicitly requests otherwise."
    ),
}


async def get_turning_test_config() -> Dict[str, Any]:
    prototype = prototype_loader.get_prototype("turning_test")
    if not prototype:
        raise TurningTestError("Turning Test configuration is unavailable.", 503)
    overrides = await firestore_service.get_prototype_overrides(
        prototype.id,
        prototype.systemPrompt,
        prototype.model,
        prototype.stagePrompts,
        prototype.config,
    )
    config = overrides["config"]
    config["openaiModel"] = overrides["model"]
    return config


def _input(request: TurningTestAIRequest, corrective: bool = False) -> list[dict[str, str]]:
    instruction = ACTION_INSTRUCTIONS[request.action]
    if corrective:
        instruction += " Your previous result was outside the required range. Revise it once to contain 285–315 words."
    rewrite_instructions = request.custom_prompt.strip() or "Make the passage sound more natural while preserving its meaning."
    return [
        {"role": "system", "content": instruction + " Return only the requested text, with no preamble, quotes, commentary, or Markdown."},
        {"role": "user", "content": f"<question>\n{request.question}\n</question>\n<highlighted_text>\n{request.answer}\n</highlighted_text>\n<rewrite_instructions>\n{rewrite_instructions}\n</rewrite_instructions>"},
    ]


async def run_ai_action(request: TurningTestAIRequest) -> tuple[str, int, str]:
    if not settings.openai_api_key:
        raise TurningTestError("OpenAI is not configured. Set OPENAI_API_KEY on the server.", 503)
    config = await get_turning_test_config()
    model = str(config["openaiModel"])
    for attempt in range(2):
        response = await client.responses.create(
            model=model,
            input=_input(request, corrective=attempt == 1),
            max_output_tokens=800,
        )
        output = response.output_text.strip()
        if not output:
            raise TurningTestError("OpenAI returned an empty answer. Your draft was not changed.")
        words = count_words(output)
        if request.action == "rewrite" or 100 <= words <= 500:
            return output, words, model
    raise TurningTestError("OpenAI could not produce an approximately 300-word answer after one correction.", 422)


def _pangram_headers() -> dict[str, str]:
    return {"x-api-key": settings.pangram_api_key, "Content-Type": "application/json"}


def _provider_error(response: httpx.Response) -> TurningTestError:
    if response.status_code in {401, 403}:
        return TurningTestError("Pangram authentication failed or this account cannot access the configured model.", response.status_code)
    if response.status_code == 429:
        return TurningTestError("Pangram rate limit reached. Wait briefly and try again.", 429)
    if response.status_code == 404:
        return TurningTestError("The configured Pangram model or task was not found.", 404)
    detail = ""
    try:
        payload = response.json()
        detail = str(payload.get("detail") or payload.get("message") or payload.get("error") or "").strip()
    except (ValueError, AttributeError):
        pass
    suffix = f" {detail}" if detail else ""
    return TurningTestError(f"Pangram rejected the request (HTTP {response.status_code}).{suffix}", 502)


async def submit_pangram(text: str) -> tuple[str, Dict[str, Any], str]:
    config = await get_turning_test_config()
    minimum_words = int(config["evaluationMinWords"])
    model = str(config["pangramModel"])
    base_url = str(config["pangramApiBaseUrl"])
    if count_words(text) < minimum_words:
        raise TurningTestError(f"Pangram evaluation requires at least {minimum_words} words.", 422)
    if not settings.pangram_api_key:
        raise TurningTestError("Pangram is not configured. Set PANGRAM_API_KEY on the server.", 503)
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            response = await http.post(
                f"{base_url.rstrip('/')}/task",
                headers=_pangram_headers(),
                json={"text": text, "model": model},
            )
    except httpx.TimeoutException as exc:
        raise TurningTestError("Pangram submission timed out. Try again.", 504) from exc
    if not response.is_success:
        raise _provider_error(response)
    data = response.json()
    task_id = data.get("task_id") or data.get("id")
    if not task_id:
        raise TurningTestError("Pangram did not return a task ID.")
    return str(task_id), data, model


async def get_pangram_task(task_id: str) -> tuple[Dict[str, Any], str]:
    config = await get_turning_test_config()
    model = str(config["pangramModel"])
    base_url = str(config["pangramApiBaseUrl"])
    if not settings.pangram_api_key:
        raise TurningTestError("Pangram is not configured on the server.", 503)
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            response = await http.get(f"{base_url.rstrip('/')}/task/{task_id}", headers=_pangram_headers())
    except httpx.TimeoutException as exc:
        raise TurningTestError("Pangram status check timed out. Try again.", 504) from exc
    if not response.is_success:
        raise _provider_error(response)
    data = response.json()
    stage = str(data.get("stage") or data.get("status") or "").upper()
    if stage == "STAGE_FAILED":
        raise TurningTestError("Pangram could not complete this evaluation. No score was recorded.")
    return data, model

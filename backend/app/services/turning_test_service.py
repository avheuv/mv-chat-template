from typing import Any, Dict

import httpx

from app.core.config import settings
from app.core.prototype_loader import prototype_loader
from app.models.turning_test import TurningTestAIRequest, TurningTestRewriteRequest
from app.services.firestore_service import firestore_service
from app.services.llm_service import client


def count_words(text: str) -> int:
    return len(text.strip().split()) if text.strip() else 0


class TurningTestError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


GENERATION_INSTRUCTION = (
    "Write a clear, accurate answer to the academic question in approximately 450 words. Use ordinary "
    "language suitable for a general audience. Include useful examples or explanation where appropriate."
)

REWRITE_INSTRUCTIONS = {
    "light_polish": "Make only small improvements to the selected text. Fix grammar, awkward phrasing, and minor word-choice issues while preserving the original sentence structure, tone, meaning, and as much of the original wording as possible.",
    "improve_clarity": "Revise the selected text to make it clearer, smoother, and easier to read. You may change wording and sentence structure, but preserve the original meaning, tone, and level of detail. Make moderate changes rather than completely rewriting the passage.",
    "major_rewrite": "Substantially rewrite the selected text to improve clarity, flow, and overall quality. Preserve the core meaning and important details, but feel free to significantly change wording, sentence structure, organization, and style.",
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
    instruction = GENERATION_INSTRUCTION
    if corrective:
        instruction += " Your previous result was outside the required range. Revise it once to contain 400–500 words."
    return [
        {"role": "system", "content": instruction + " Return only the requested text, with no preamble, quotes, commentary, or Markdown."},
        {"role": "user", "content": f"<question>\n{request.question}\n</question>"},
    ]


async def generate_starting_text(request: TurningTestAIRequest) -> tuple[str, int, str]:
    if not settings.openai_api_key:
        raise TurningTestError("OpenAI is not configured. Set OPENAI_API_KEY on the server.", 503)
    config = await get_turning_test_config()
    model = str(config["openaiModel"])
    for attempt in range(2):
        response = await client.responses.create(
            model=model,
            input=_input(request, corrective=attempt == 1),
            max_output_tokens=1000,
        )
        output = response.output_text.strip()
        if not output:
            raise TurningTestError("OpenAI returned an empty answer. No starting text was created.")
        words = count_words(output)
        if 400 <= words <= 500:
            return output, words, model
    raise TurningTestError("OpenAI could not produce a 400–500-word answer after one correction.", 422)


async def rewrite_selected_text(request: TurningTestRewriteRequest) -> tuple[str, str]:
    if not settings.openai_api_key:
        raise TurningTestError("OpenAI is not configured. Set OPENAI_API_KEY on the server.", 503)
    config = await get_turning_test_config()
    model = str(config["openaiModel"])
    response = await client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": REWRITE_INSTRUCTIONS[request.action] + " Return only the revised text, with no preamble, quotes, commentary, or Markdown."},
            {"role": "user", "content": f"<selected_text>\n{request.selected_text}\n</selected_text>"},
        ],
        max_output_tokens=1200,
    )
    output = response.output_text.strip()
    if not output:
        raise TurningTestError("OpenAI returned an empty revision. The selected text was not changed.")
    return output, model


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

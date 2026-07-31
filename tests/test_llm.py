from types import SimpleNamespace

import httpx
import pytest

from tech_news_purifier.llm import LLMClient


@pytest.mark.asyncio
async def test_complete_retries_rate_limit_and_honors_retry_after() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "valid structured response"}}]},
        )

    settings = SimpleNamespace(
        one_api_key="test-secret",
        one_api_url="http://one-api.test/v1/chat/completions",
        primary_model="primary",
        fallback_model="fallback",
        max_ai_concurrency=3,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = LLMClient(settings, http_client, request_interval_seconds=0)
        text, model, attempts = await client.complete(
            "prompt", max_tokens=50, temperature=0, min_length=5
        )

    assert text == "valid structured response"
    assert model == "primary"
    assert attempts == 2
    assert calls == 2

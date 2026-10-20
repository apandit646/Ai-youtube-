import json

import httpx
import pytest

from app.services.content.schemas import ContentBrief
from app.services.llm.base import (
    GeminiProvider,
    GrokProvider,
    LLMError,
    LLMUnavailableError,
    OpenAIProvider,
    extract_json,
)
from app.services.llm.router import LLMRouter
from tests.helpers import chat_response, gemini_response, no_sleep, sample_brief


def test_extract_json_handles_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! Here it is: {"a": {"b": 2}} hope that helps') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        extract_json("no json here")
    with pytest.raises(ValueError):
        extract_json("[1, 2, 3]")


def _provider(cls, handler, **kw):
    return cls("key-123456789", "test-model", "https://example.test/v1", transport=httpx.MockTransport(handler),
               sleep=no_sleep, max_retries=kw.get("max_retries", 2))


def test_openai_compatible_request_shape():
    seen = {}

    def handler(req: httpx.Request):
        seen["auth"] = req.headers["authorization"]
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.read())
        return chat_response({"ok": True})

    resp = _provider(GrokProvider, handler).complete("sys", "user")
    assert resp.provider == "grok" and resp.model == "test-model"
    assert seen["auth"] == "Bearer key-123456789"
    assert seen["url"].endswith("/chat/completions")
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["model"] == "test-model"


def test_retries_rate_limits_then_succeeds():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, json={"error": {"message": "slow down"}}, headers={"retry-after": "1"})
        return chat_response({"ok": True})

    assert _provider(OpenAIProvider, handler).complete("s", "u").text == '{"ok": true}'
    assert calls["n"] == 3


def test_non_retryable_error_is_raised_immediately():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    with pytest.raises(LLMError) as exc:
        _provider(OpenAIProvider, handler).complete("s", "u")
    assert calls["n"] == 1 and "401" in str(exc.value) and not exc.value.retryable


def test_timeout_is_retryable_and_reported():
    def handler(req):
        raise httpx.ReadTimeout("timeout", request=req)

    with pytest.raises(LLMError, match="timed out"):
        _provider(GrokProvider, handler, max_retries=1).complete("s", "u")


def test_gemini_puts_key_in_header_not_url():
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["key"] = req.headers.get("x-goog-api-key")
        return gemini_response({"ok": 1})

    assert _provider(GeminiProvider, handler).complete("s", "u").text == '{"ok": 1}'
    assert "key-123456789" not in seen["url"] and seen["key"] == "key-123456789"
    assert seen["url"].endswith("/models/test-model:generateContent")


def test_unconfigured_provider_raises():
    with pytest.raises(LLMError, match="not configured"):
        GrokProvider("", "", "https://x").complete("s", "u")


def _router(handlers: dict) -> LLMRouter:
    providers = {}
    for name, cls in (("grok", GrokProvider), ("openai", OpenAIProvider), ("gemini", GeminiProvider)):
        if name in handlers:
            providers[name] = _provider(cls, handlers[name], max_retries=0)
        else:
            providers[name] = cls("", "", "https://x")
    return LLMRouter(providers)


def test_router_validates_and_falls_back_to_next_provider():
    brief = sample_brief(1)
    router = _router({
        "grok": lambda r: httpx.Response(503, json={"error": "down"}),
        "openai": lambda r: chat_response(brief),
    })
    result = router.generate("script", "sys", "user", ContentBrief)
    assert result.provider == "openai"
    assert result.data.title == brief["title"]
    assert [a["ok"] for a in result.attempts] == [False, True]


def test_router_repairs_invalid_output_once():
    brief = sample_brief(0)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return chat_response({"title": "x"})  # schema-invalid
        assert "previous answer was rejected" in req.read().decode()
        return chat_response(brief)

    result = _router({"grok": handler}).generate("script", "sys", "user", ContentBrief)
    assert result.provider == "grok" and calls["n"] == 2


def test_router_raises_when_everything_fails():
    router = _router({"grok": lambda r: chat_response("not json at all"),
                      "gemini": lambda r: httpx.Response(400, json={"error": {"message": "bad"}})})
    with pytest.raises(LLMUnavailableError) as exc:
        router.generate("script", "sys", "user", ContentBrief)
    assert {a["provider"] for a in exc.value.attempts} == {"grok", "gemini"}


def test_router_with_no_providers():
    with pytest.raises(LLMUnavailableError, match="No AI provider"):
        _router({}).generate("script", "s", "u", ContentBrief)


def test_review_excludes_generator_provider():
    router = _router({"grok": lambda r: chat_response({}), "gemini": lambda r: chat_response({})})
    assert [p.name for p in router.order_for("review", exclude="grok")] == ["gemini"]

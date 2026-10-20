"""Provider-agnostic LLM interface with retry, timeout and rate-limit handling."""

import json
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)


class LLMError(Exception):
    """A single provider call failed."""

    def __init__(self, message: str, *, provider: str = "", retryable: bool = False, status_code: int | None = None):
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable
        self.status_code = status_code


class LLMUnavailableError(Exception):
    """No configured provider could produce a valid response."""

    def __init__(self, message: str, attempts: list[dict] | None = None):
        super().__init__(message)
        self.attempts = attempts or []


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    usage: dict = field(default_factory=dict)


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def extract_json(text: str) -> dict:
    """Parse a JSON object from model output, tolerating markdown fences and leading prose."""
    cleaned = _FENCE.sub("", text.strip()).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("Response did not contain a JSON object") from None
        try:
            value = json.loads(cleaned[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"Malformed JSON in response: {exc.msg}") from None
    if not isinstance(value, dict):
        raise ValueError("Top-level JSON value must be an object")
    return value


class LLMProvider:
    """Base class: subclasses implement `_request` returning (text, usage)."""

    name: str = "base"
    label: str = "Base"

    def __init__(self, api_key: str, model: str, base_url: str, *, timeout: float = 90.0, max_retries: int = 3,
                 transport: httpx.BaseTransport | None = None, sleep=time.sleep):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._transport = transport
        self._sleep = sleep

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model)

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=httpx.Timeout(self.timeout, connect=10.0), transport=self._transport)

    def _request(self, client: httpx.Client, system: str, user: str, temperature: float) -> tuple[str, dict]:
        raise NotImplementedError

    def complete(self, system: str, user: str, *, temperature: float = 0.8) -> LLMResponse:
        if not self.configured:
            raise LLMError(f"{self.label} is not configured (API key and model required)", provider=self.name)
        last: LLMError | None = None
        with self._client() as client:
            for attempt in range(self.max_retries + 1):
                try:
                    text, usage = self._request(client, system, user, temperature)
                    return LLMResponse(text=text, provider=self.name, model=self.model, usage=usage)
                except httpx.TimeoutException:
                    last = LLMError(f"{self.label} request timed out", provider=self.name, retryable=True)
                except httpx.TransportError as exc:
                    last = LLMError(f"{self.label} network error: {type(exc).__name__}", provider=self.name,
                                    retryable=True)
                except LLMError as exc:
                    last = exc
                if not last.retryable or attempt >= self.max_retries:
                    break
                delay = min(2 ** attempt, 30)
                log.warning("LLM call failed, retrying", extra={"provider": self.name})
                self._sleep(delay)
        assert last is not None
        raise last

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        retryable = resp.status_code == 429 or resp.status_code >= 500
        try:
            body = resp.json()
            detail = body.get("error", {}).get("message") if isinstance(body.get("error"), dict) else body.get("error")
        except (ValueError, AttributeError):
            detail = None
        detail = (str(detail) if detail else resp.text[:200]) or resp.reason_phrase
        if resp.status_code == 429:
            retry_after = resp.headers.get("retry-after")
            if retry_after and retry_after.isdigit():
                self._sleep(min(int(retry_after), 60))
            detail = f"rate limited: {detail}"
        raise LLMError(f"{self.label} HTTP {resp.status_code}: {detail}", provider=self.name,
                       retryable=retryable, status_code=resp.status_code)


class OpenAICompatibleProvider(LLMProvider):
    """Chat Completions API — used for both OpenAI (ChatGPT) and xAI (Grok), which expose compatible endpoints."""

    def _request(self, client: httpx.Client, system: str, user: str, temperature: float) -> tuple[str, dict]:
        resp = client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            json={
                "model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "temperature": temperature,
                "response_format": {"type": "json_object"},
            },
        )
        self._raise_for_status(resp)
        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"] or ""
        except (ValueError, KeyError, IndexError, TypeError):
            raise LLMError(f"{self.label} returned an unexpected response shape", provider=self.name) from None
        return text, data.get("usage") or {}


class GrokProvider(OpenAICompatibleProvider):
    name = "grok"
    label = "Grok (xAI)"


class OpenAIProvider(OpenAICompatibleProvider):
    name = "openai"
    label = "ChatGPT (OpenAI)"


class GeminiProvider(LLMProvider):
    name = "gemini"
    label = "Gemini (Google)"

    def _request(self, client: httpx.Client, system: str, user: str, temperature: float) -> tuple[str, dict]:
        # API key goes in a header, never the URL, so it can't leak into access logs.
        resp = client.post(
            f"{self.base_url}/models/{self.model}:generateContent",
            headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
            json={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"},
            },
        )
        self._raise_for_status(resp)
        try:
            data = resp.json()
            candidate = data["candidates"][0]
            text = "".join(p.get("text", "") for p in candidate["content"]["parts"])
        except (ValueError, KeyError, IndexError, TypeError):
            reason = None
            try:
                reason = resp.json().get("promptFeedback", {}).get("blockReason")
            except ValueError:
                pass
            msg = f"{self.label} returned no content" + (f" (blocked: {reason})" if reason else "")
            raise LLMError(msg, provider=self.name) from None
        return text, data.get("usageMetadata") or {}


PROVIDER_CLASSES: dict[str, type[LLMProvider]] = {
    "grok": GrokProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
}

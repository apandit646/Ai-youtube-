"""Multi-model router: picks Grok / ChatGPT / Gemini per task, validates structured output, and falls back."""

import logging
from dataclasses import dataclass, field
from typing import Generic, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings
from app.core.security import decrypt_secret
from app.models import AppSettings
from app.services.llm.base import (
    PROVIDER_CLASSES,
    LLMError,
    LLMProvider,
    LLMUnavailableError,
    extract_json,
)

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

TASKS = ("ideas", "script", "metadata", "trend_analysis", "recommendations", "review")
PROVIDERS = ("grok", "openai", "gemini")

# Grok is the primary creative model; the others act as fallbacks and independent reviewers.
DEFAULT_ROUTING: dict[str, list[str]] = {
    "ideas": ["grok", "openai", "gemini"],
    "script": ["grok", "openai", "gemini"],
    "metadata": ["grok", "openai", "gemini"],
    "trend_analysis": ["grok", "gemini", "openai"],
    "recommendations": ["grok", "gemini", "openai"],
    "review": ["gemini", "openai", "grok"],
}


@dataclass
class LLMResult(Generic[T]):
    data: T
    provider: str
    model: str
    attempts: list[dict] = field(default_factory=list)


def _env_credentials(settings: Settings) -> dict[str, tuple[str, str, str]]:
    return {
        "grok": (settings.xai_api_key, settings.xai_model, settings.xai_base_url),
        "openai": (settings.openai_api_key, settings.openai_model, settings.openai_base_url),
        "gemini": (settings.gemini_api_key, settings.gemini_model, settings.gemini_base_url),
    }


class LLMRouter:
    def __init__(self, providers: dict[str, LLMProvider], routing: dict[str, list[str]] | None = None):
        self.providers = providers
        self.routing = {**DEFAULT_ROUTING, **(routing or {})}

    @classmethod
    def from_settings(cls, app_settings: AppSettings | None = None, *, settings: Settings | None = None,
                      transport: httpx.BaseTransport | None = None) -> "LLMRouter":
        settings = settings or get_settings()
        creds = _env_credentials(settings)
        providers: dict[str, LLMProvider] = {}
        for name, (env_key, env_model, base_url) in creds.items():
            key, model = env_key, env_model
            if app_settings is not None:
                enc = (app_settings.encrypted_api_keys or {}).get(name)
                if enc:
                    key = decrypt_secret(enc) or key
                model = (app_settings.llm_models or {}).get(name) or model
            providers[name] = PROVIDER_CLASSES[name](
                key, model, base_url, timeout=settings.llm_timeout_seconds,
                max_retries=settings.llm_max_retries, transport=transport,
            )
        routing = None
        if app_settings is not None and app_settings.llm_routing:
            routing = {t: [p for p in v if p in PROVIDERS] for t, v in app_settings.llm_routing.items() if t in TASKS}
        return cls(providers, routing)

    def status(self) -> list[dict]:
        return [
            {"provider": p.name, "label": p.label, "configured": p.configured, "model": p.model or None}
            for p in self.providers.values()
        ]

    @property
    def any_configured(self) -> bool:
        return any(p.configured for p in self.providers.values())

    def order_for(self, task: str, exclude: str | None = None) -> list[LLMProvider]:
        names = self.routing.get(task) or list(PROVIDERS)
        # Append any configured provider not explicitly listed so fallbacks still work.
        names = names + [n for n in PROVIDERS if n not in names]
        return [self.providers[n] for n in names if n in self.providers and self.providers[n].configured
                and n != exclude]

    def generate(self, task: str, system: str, user: str, schema: type[T], *, temperature: float = 0.8,
                 exclude: str | None = None, prefer: str | None = None) -> LLMResult[T]:
        candidates = self.order_for(task, exclude=exclude)
        if prefer:
            candidates.sort(key=lambda p: p.name != prefer)
        if not candidates:
            raise LLMUnavailableError("No AI provider is configured. Add a Grok, OpenAI or Gemini API key and model.")
        attempts: list[dict] = []
        schema_hint = schema.model_json_schema()
        for provider in candidates:
            prompt = user
            for repair_round in range(2):  # one repair attempt per provider for malformed output
                try:
                    resp = provider.complete(system, prompt, temperature=temperature)
                    data = schema.model_validate(extract_json(resp.text))
                    attempts.append({"provider": provider.name, "model": provider.model, "ok": True})
                    return LLMResult(data=data, provider=provider.name, model=provider.model, attempts=attempts)
                except LLMError as exc:
                    attempts.append({"provider": provider.name, "model": provider.model, "ok": False,
                                     "error": str(exc)})
                    log.warning("LLM provider failed: %s", exc, extra={"provider": provider.name})
                    break  # transport/API errors already retried inside the provider
                except (ValueError, ValidationError) as exc:
                    err = _short_validation_error(exc)
                    attempts.append({"provider": provider.name, "model": provider.model, "ok": False,
                                     "error": f"invalid structured output: {err}"})
                    if repair_round == 0:
                        prompt = (f"{user}\n\nYour previous answer was rejected: {err}\n"
                                  f"Return ONLY a JSON object matching this JSON schema:\n{schema_hint}")
        raise LLMUnavailableError(f"All configured AI providers failed for task '{task}'", attempts)


def _short_validation_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        parts = [f"{'.'.join(str(x) for x in e['loc'])}: {e['msg']}" for e in exc.errors()[:5]]
        return "; ".join(parts)
    return str(exc)[:300]

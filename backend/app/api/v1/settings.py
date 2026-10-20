from fastapi import APIRouter

from app.api.deps import DB, CurrentUser, UserSettings
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.security import decrypt_secret, encrypt_secret, mask_secret
from app.models import AppSettings
from app.schemas.api import ApiKeyUpdate, ProviderStatus, SettingsOut, SettingsUpdate
from app.services.audit import audit
from app.services.llm.base import LLMError
from app.services.llm.router import PROVIDERS, TASKS, LLMRouter
from app.services.media.audio import EspeakNarrationProvider
from app.services.media.ffmpeg import ffmpeg_available
from app.services.media.fonts import font_report
from app.services.youtube.oauth import oauth_configured

router = APIRouter(prefix="/settings", tags=["settings"])


def provider_statuses(app_settings: AppSettings) -> list[ProviderStatus]:
    s = get_settings()
    env_keys = {"grok": s.xai_api_key, "openai": s.openai_api_key, "gemini": s.gemini_api_key}
    llm = LLMRouter.from_settings(app_settings)
    out = []
    for st in llm.status():
        enc = (app_settings.encrypted_api_keys or {}).get(st["provider"])
        key = decrypt_secret(enc) if enc else None
        source = "settings" if key else ("environment" if env_keys[st["provider"]] else None)
        out.append(ProviderStatus(**st, key_source=source, key_hint=mask_secret(key or env_keys[st["provider"]])))
    return out


@router.get("", response_model=dict)
def get_app_settings_endpoint(app_settings: UserSettings) -> dict:
    return {
        "settings": SettingsOut.model_validate(app_settings).model_dump(mode="json"),
        "providers": [p.model_dump() for p in provider_statuses(app_settings)],
        "tasks": list(TASKS),
        "youtube": {"oauth_configured": oauth_configured(), "api_key_configured": bool(get_settings().youtube_api_key)},
        "media": {"ffmpeg": ffmpeg_available(), "tts": EspeakNarrationProvider().available(), **font_report()},
    }


@router.put("", response_model=SettingsOut)
def update_settings(body: SettingsUpdate, app_settings: UserSettings, db: DB, user: CurrentUser) -> AppSettings:
    data = body.model_dump(exclude_unset=True)
    if "llm_routing" in data:
        routing = {}
        for task, providers in (data["llm_routing"] or {}).items():
            if task not in TASKS or any(p not in PROVIDERS for p in providers):
                raise AppError(f"Invalid routing for task '{task}'")
            routing[task] = list(dict.fromkeys(providers))
        data["llm_routing"] = routing
    start = data.get("publish_window_start_hour", app_settings.publish_window_start_hour)
    end = data.get("publish_window_end_hour", app_settings.publish_window_end_hour)
    if end <= start:
        raise AppError("Publishing window end hour must be after the start hour")
    if data.get("auto_publish_enabled") and not data.get("dry_run", app_settings.dry_run) \
            and app_settings.private_test_passed_at is None:
        raise AppError("Auto-publishing can only be enabled after a successful private test upload "
                       "(or while dry-run mode is on).")
    if (data.get("dry_run") is False and app_settings.auto_publish_enabled
            and app_settings.private_test_passed_at is None):
        raise AppError("Disable auto-publishing or complete a private test upload before turning off dry-run.")
    for k, v in data.items():
        setattr(app_settings, k, v)
    audit(db, user.id, "settings.updated", "app_settings", app_settings.id, fields=",".join(sorted(data)))
    db.commit()
    return app_settings


@router.put("/api-keys", response_model=list[ProviderStatus])
def set_api_key(body: ApiKeyUpdate, app_settings: UserSettings, db: DB, user: CurrentUser) -> list[ProviderStatus]:
    """Write-only: keys are encrypted at rest and never returned to the browser."""
    keys = dict(app_settings.encrypted_api_keys or {})
    keys[body.provider] = encrypt_secret(body.api_key.strip())
    app_settings.encrypted_api_keys = keys
    if body.model:
        app_settings.llm_models = {**(app_settings.llm_models or {}), body.provider: body.model.strip()}
    audit(db, user.id, "settings.api_key_set", "provider", body.provider)
    db.commit()
    return provider_statuses(app_settings)


@router.delete("/api-keys/{provider}", response_model=list[ProviderStatus])
def delete_api_key(provider: str, app_settings: UserSettings, db: DB, user: CurrentUser) -> list[ProviderStatus]:
    if provider not in PROVIDERS:
        raise AppError("Unknown provider")
    keys = dict(app_settings.encrypted_api_keys or {})
    keys.pop(provider, None)
    app_settings.encrypted_api_keys = keys
    audit(db, user.id, "settings.api_key_deleted", "provider", provider)
    db.commit()
    return provider_statuses(app_settings)


@router.post("/test-provider/{provider}")
def test_provider(provider: str, app_settings: UserSettings) -> dict:
    """Make one tiny live call to verify credentials and the configured model name."""
    if provider not in PROVIDERS:
        raise AppError("Unknown provider")
    llm = LLMRouter.from_settings(app_settings)
    p = llm.providers[provider]
    p.max_retries = 0
    try:
        resp = p.complete("Reply with a JSON object only.", 'Return {"ok": true}', temperature=0)
        return {"provider": provider, "ok": True, "model": p.model, "sample": resp.text[:200]}
    except LLMError as exc:
        return {"provider": provider, "ok": False, "model": p.model or None, "error": str(exc)}

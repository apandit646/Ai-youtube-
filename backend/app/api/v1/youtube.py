import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse

from app.api.deps import DB, CurrentUser
from app.core.config import get_settings
from app.core.security import decode_state_token
from app.models import User
from app.services.audit import audit
from app.services.youtube import oauth

log = logging.getLogger(__name__)
router = APIRouter(prefix="/youtube", tags=["youtube"])


@router.get("/auth")
def start_auth(user: CurrentUser) -> dict:
    """Returns the Google consent URL. The SPA navigates to it (a redirect can't carry the bearer token)."""
    return {"auth_url": oauth.build_auth_url(user.id), "scopes": oauth.SCOPES}


@router.get("/callback", include_in_schema=True)
def oauth_callback(db: DB, code: str | None = Query(None), state: str | None = Query(None),
                   error: str | None = Query(None)) -> RedirectResponse:
    """Google redirects here. Authenticated by the signed, short-lived `state` token."""
    front = get_settings().frontend_url.rstrip("/")

    def back(**params: str) -> RedirectResponse:
        return RedirectResponse(f"{front}/settings?{urlencode(params)}", status_code=302)

    if error:
        return back(youtube="error", reason=error[:100])
    data = decode_state_token(state or "")
    if not data or not code:
        return back(youtube="error", reason="invalid_state")
    user = db.get(User, int(data["uid"]))
    if user is None:
        return back(youtube="error", reason="unknown_user")
    try:
        channel = oauth.exchange_code(db, user.id, code)
    except Exception as exc:  # noqa: BLE001 - report the failure to the UI instead of a raw 500
        log.warning("OAuth exchange failed: %s", exc)
        db.rollback()
        return back(youtube="error", reason=str(exc)[:150])
    audit(db, user.id, "youtube.connected", "channel", channel.channel_id, title=channel.title)
    db.commit()
    return back(youtube="connected")


@router.get("/channel")
def channel_status(db: DB, user: CurrentUser) -> dict:
    ch = oauth.active_channel(db, user.id)
    if ch is None:
        return {"connected": False, "oauth_configured": oauth.oauth_configured()}
    return {
        "connected": True, "oauth_configured": oauth.oauth_configured(), "channel_id": ch.channel_id,
        "title": ch.title, "thumbnail_url": ch.thumbnail_url, "subscriber_count": ch.subscriber_count,
        "video_count": ch.video_count, "scopes": ch.scopes.split(),
        "has_refresh_token": bool(ch.encrypted_refresh_token),
        "connected_at": ch.created_at,
    }


@router.post("/revoke")
def revoke_access(db: DB, user: CurrentUser) -> dict:
    result = oauth.revoke(db, user.id)
    audit(db, user.id, "youtube.revoked", "channel", "", **result)
    db.commit()
    return {**result, "manual_step": "You can also remove access at https://myaccount.google.com/permissions"}

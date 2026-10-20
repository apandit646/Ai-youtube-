"""Google OAuth 2.0 for the channel owner: consent URL, code exchange, token refresh and revocation."""

import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import ConfigurationError, ExternalServiceError, NotFoundError
from app.core.security import create_state_token, decrypt_secret, encrypt_secret
from app.models import ConnectedYouTubeChannel
from app.services.youtube.client import YouTubeAuthError, YouTubeDataClient

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]


def oauth_configured() -> bool:
    s = get_settings()
    return bool(s.google_oauth_client_id and s.google_oauth_client_secret and s.google_oauth_redirect_uri)


def build_auth_url(owner_id: int) -> str:
    if not oauth_configured():
        raise ConfigurationError("Google OAuth is not configured. Set GOOGLE_OAUTH_CLIENT_ID, "
                                 "GOOGLE_OAUTH_CLIENT_SECRET and GOOGLE_OAUTH_REDIRECT_URI.")
    s = get_settings()
    params = {
        "client_id": s.google_oauth_client_id,
        "redirect_uri": s.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": create_state_token({"uid": owner_id}),
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def _token_request(data: dict, transport: httpx.BaseTransport | None = None) -> dict:
    with httpx.Client(timeout=30, transport=transport) as client:
        try:
            resp = client.post(TOKEN_URL, data=data)
        except httpx.TransportError as exc:
            raise ExternalServiceError(f"Could not reach Google OAuth: {type(exc).__name__}") from None
    if resp.status_code >= 400:
        try:
            err = resp.json()
            detail = f"{err.get('error')}: {err.get('error_description', '')}"
        except ValueError:
            detail = resp.text[:200]
        if resp.status_code in (400, 401) and "invalid_grant" in detail:
            raise YouTubeAuthError(f"Google rejected the refresh token ({detail}); reconnect the channel.",
                                   status_code=resp.status_code, reason="invalid_grant")
        raise ExternalServiceError(f"Google OAuth token request failed: {detail}")
    return resp.json()


def exchange_code(db: Session, owner_id: int, code: str, *,
                  transport: httpx.BaseTransport | None = None) -> ConnectedYouTubeChannel:
    s = get_settings()
    tokens = _token_request({
        "code": code, "client_id": s.google_oauth_client_id, "client_secret": s.google_oauth_client_secret,
        "redirect_uri": s.google_oauth_redirect_uri, "grant_type": "authorization_code",
    }, transport)
    access = tokens["access_token"]
    with YouTubeDataClient(access_token=access, transport=transport) as yt:
        ch = yt.channel(mine=True)
    if not ch:
        raise ExternalServiceError("The authorised Google account has no YouTube channel.")
    channel = db.scalar(select(ConnectedYouTubeChannel).where(ConnectedYouTubeChannel.channel_id == ch["id"]))
    if channel and channel.owner_id != owner_id:
        raise ExternalServiceError("This YouTube channel is already connected to another account.")
    if channel is None:
        channel = ConnectedYouTubeChannel(owner_id=owner_id, channel_id=ch["id"])
        db.add(channel)
    # Single-channel MVP: deactivate any other channel for this owner.
    for other in db.scalars(select(ConnectedYouTubeChannel).where(ConnectedYouTubeChannel.owner_id == owner_id)):
        if other is not channel:
            other.is_active = False
    snippet, stats = ch.get("snippet", {}), ch.get("statistics", {})
    channel.title = snippet.get("title", "")
    channel.thumbnail_url = (snippet.get("thumbnails", {}).get("default") or {}).get("url")
    channel.subscriber_count = None if stats.get("hiddenSubscriberCount") else _int(stats.get("subscriberCount"))
    channel.video_count = _int(stats.get("videoCount"))
    channel.encrypted_access_token = encrypt_secret(access)
    if tokens.get("refresh_token"):
        channel.encrypted_refresh_token = encrypt_secret(tokens["refresh_token"])
    channel.token_expires_at = datetime.now(UTC) + timedelta(seconds=int(tokens.get("expires_in", 3600)))
    channel.scopes = tokens.get("scope", "")
    channel.is_active, channel.revoked_at = True, None
    db.flush()
    return channel


def _int(v: object) -> int | None:
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def active_channel(db: Session, owner_id: int) -> ConnectedYouTubeChannel | None:
    return db.scalar(select(ConnectedYouTubeChannel).where(ConnectedYouTubeChannel.owner_id == owner_id,
                                                           ConnectedYouTubeChannel.is_active.is_(True)))


def get_access_token(db: Session, channel: ConnectedYouTubeChannel, *,
                     transport: httpx.BaseTransport | None = None) -> str:
    """Return a valid access token, refreshing (and persisting) it if it is about to expire."""
    expires = channel.token_expires_at
    if expires is not None and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    access = decrypt_secret(channel.encrypted_access_token) if channel.encrypted_access_token else None
    if access and expires and expires > datetime.now(UTC) + timedelta(seconds=90):
        return access
    refresh = decrypt_secret(channel.encrypted_refresh_token) if channel.encrypted_refresh_token else None
    if not refresh:
        raise YouTubeAuthError("No refresh token stored; reconnect the YouTube channel.", reason="no_refresh_token")
    s = get_settings()
    tokens = _token_request({"client_id": s.google_oauth_client_id, "client_secret": s.google_oauth_client_secret,
                             "refresh_token": refresh, "grant_type": "refresh_token"}, transport)
    channel.encrypted_access_token = encrypt_secret(tokens["access_token"])
    channel.token_expires_at = datetime.now(UTC) + timedelta(seconds=int(tokens.get("expires_in", 3600)))
    db.flush()
    return tokens["access_token"]


def revoke(db: Session, owner_id: int, *, transport: httpx.BaseTransport | None = None) -> dict:
    channel = active_channel(db, owner_id)
    if not channel:
        raise NotFoundError("No connected YouTube channel")
    token = None
    if channel.encrypted_refresh_token:
        token = decrypt_secret(channel.encrypted_refresh_token)
    revoked_remote = False
    if token:
        try:
            with httpx.Client(timeout=20, transport=transport) as client:
                resp = client.post(REVOKE_URL, data={"token": token})
            revoked_remote = resp.status_code == 200
        except httpx.TransportError:
            revoked_remote = False
    channel.encrypted_access_token = None
    channel.encrypted_refresh_token = None
    channel.token_expires_at = None
    channel.is_active = False
    channel.revoked_at = datetime.now(UTC)
    db.flush()
    return {"revoked_at_google": revoked_remote, "local_tokens_deleted": True}

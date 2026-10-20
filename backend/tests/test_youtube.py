from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.core.security import decrypt_secret, encrypt_secret
from app.models import ConnectedYouTubeChannel
from app.services.youtube import oauth
from app.services.youtube.client import (
    YouTubeAnalyticsClient,
    YouTubeAPIError,
    YouTubeDataClient,
    YouTubeQuotaError,
    parse_iso_duration,
)
from app.services.youtube.uploader import ResumableUploader
from tests.helpers import no_sleep


def test_parse_iso_duration():
    assert parse_iso_duration("PT1M5S") == 65
    assert parse_iso_duration("PT2H") == 7200
    assert parse_iso_duration("P1DT1S") == 86401
    assert parse_iso_duration("bogus") is None and parse_iso_duration(None) is None


def test_search_and_videos_with_quota_accounting():
    def handler(req: httpx.Request):
        if req.url.path.endswith("/search"):
            assert req.url.params["safeSearch"] == "strict" and req.url.params["key"] == "k"
            return httpx.Response(200, json={"items": [{"id": {"videoId": "a"}}, {"id": {"videoId": "b"}}]})
        assert req.url.params["id"] == "a,b"
        return httpx.Response(200, json={"items": [{"id": "a"}, {"id": "b"}]})

    with YouTubeDataClient(api_key="k", transport=httpx.MockTransport(handler)) as yt:
        ids = yt.search_videos("rhymes")
        assert ids == ["a", "b"] and len(yt.videos(ids)) == 2
        assert yt.quota_used == 101


def test_quota_error_and_retry_on_5xx():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, json={"error": {"message": "backend"}})
        return httpx.Response(403, json={"error": {"message": "quota", "errors": [{"reason": "quotaExceeded"}]}})

    with YouTubeDataClient(api_key="k", transport=httpx.MockTransport(handler), sleep=no_sleep) as yt:
        with pytest.raises(YouTubeQuotaError) as exc:
            yt.search_videos("x")
    assert exc.value.reason == "quotaExceeded" and calls["n"] == 2


def test_requires_credentials():
    with pytest.raises(YouTubeAPIError):
        YouTubeDataClient()


def test_resumable_upload_resumes_after_server_error(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"0123456789")
    state = {"received": 0, "puts": 0, "failed_once": False}

    def handler(req: httpx.Request):
        if req.method == "POST":
            assert req.url.params["uploadType"] == "resumable"
            assert req.headers["x-upload-content-length"] == "10"
            return httpx.Response(200, headers={"location": "https://upload.test/session"})
        state["puts"] += 1
        cr = req.headers["content-range"]
        if cr.startswith("bytes */"):
            return httpx.Response(308, headers={"range": f"bytes=0-{state['received'] - 1}"})
        if state["received"] == 4 and not state["failed_once"]:
            state["failed_once"] = True
            return httpx.Response(503)
        state["received"] += len(req.read())
        if state["received"] >= 10:
            return httpx.Response(200, json={"id": "newvid", "status": {"privacyStatus": "private"}})
        return httpx.Response(308, headers={"range": f"bytes=0-{state['received'] - 1}"})

    up = ResumableUploader("tok", transport=httpx.MockTransport(handler), sleep=no_sleep, chunk_size=4)
    uri = up.start_session({"snippet": {}}, 10)
    progress = []
    result = up.upload(video, uri, progress.append)
    assert result["id"] == "newvid" and state["failed_once"] and progress[-1] == 1.0


def test_oauth_url_contains_offline_access_and_signed_state():
    url = oauth.build_auth_url(42)
    q = parse_qs(urlparse(url).query)
    assert q["access_type"] == ["offline"] and q["prompt"] == ["consent"]
    assert "youtube.upload" in q["scope"][0] and "yt-analytics.readonly" in q["scope"][0]
    from app.core.security import decode_state_token

    assert decode_state_token(q["state"][0])["uid"] == 42


def _google(handler_extra=None):
    def handler(req: httpx.Request):
        if req.url.host == "oauth2.googleapis.com" and req.url.path == "/token":
            body = parse_qs(req.read().decode())
            if body["grant_type"] == ["refresh_token"]:
                if body["refresh_token"] == ["revoked"]:
                    return httpx.Response(400, json={"error": "invalid_grant", "error_description": "revoked"})
                return httpx.Response(200, json={"access_token": "ya29.new", "expires_in": 3600})
            return httpx.Response(200, json={"access_token": "ya29.first", "refresh_token": "1//refresh",
                                             "expires_in": 3600, "scope": " ".join(oauth.SCOPES)})
        if req.url.path.endswith("/channels"):
            assert req.headers["authorization"] == "Bearer ya29.first"
            return httpx.Response(200, json={"items": [{"id": "UCabc", "snippet": {"title": "Rhyme Time"},
                                                        "statistics": {"subscriberCount": "12", "videoCount": "3"}}]})
        if req.url.path == "/revoke":
            return httpx.Response(200)
        raise AssertionError(f"unexpected {req.url}")
    return httpx.MockTransport(handler)


def test_exchange_refresh_and_revoke(db, user):
    t = _google()
    ch = oauth.exchange_code(db, user.id, "code", transport=t)
    assert ch.channel_id == "UCabc" and ch.subscriber_count == 12
    assert decrypt_secret(ch.encrypted_refresh_token) == "1//refresh"
    assert "ya29" not in (ch.encrypted_access_token or "")  # stored encrypted
    assert oauth.get_access_token(db, ch, transport=t) == "ya29.first"  # still valid, no refresh
    ch.token_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    assert oauth.get_access_token(db, ch, transport=t) == "ya29.new"
    result = oauth.revoke(db, user.id, transport=t)
    assert result["revoked_at_google"] and not ch.is_active and ch.encrypted_refresh_token is None


def test_refresh_with_revoked_grant_raises_auth_error(db, user):
    ch = ConnectedYouTubeChannel(owner_id=user.id, channel_id="UCx", encrypted_refresh_token=encrypt_secret("revoked"),
                                 token_expires_at=datetime.now(UTC) - timedelta(hours=1))
    db.add(ch)
    db.flush()
    from app.services.youtube.client import YouTubeAuthError

    with pytest.raises(YouTubeAuthError, match="reconnect"):
        oauth.get_access_token(db, ch, transport=_google())


def test_analytics_rows_as_dicts():
    report = {"columnHeaders": [{"name": "day"}, {"name": "views"}], "rows": [["2026-01-01", 5]]}
    assert YouTubeAnalyticsClient.rows_as_dicts(report) == [{"day": "2026-01-01", "views": 5}]
    assert YouTubeAnalyticsClient.rows_as_dicts({"columnHeaders": []}) == []

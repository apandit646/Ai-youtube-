"""Thin, testable clients for the official YouTube Data API v3 and YouTube Analytics API v2."""

import logging
import re
import time
from collections.abc import Callable
from datetime import date

import httpx

from app.core.config import get_settings

log = logging.getLogger(__name__)

DATA_API = "https://www.googleapis.com/youtube/v3"
UPLOAD_API = "https://www.googleapis.com/upload/youtube/v3/videos"
ANALYTICS_API = "https://youtubeanalytics.googleapis.com/v2/reports"

# Documented quota costs (units) for the calls we make.
QUOTA_COST = {"search": 100, "videos": 1, "channels": 1, "playlistItems": 1, "videos.insert": 1600,
              "thumbnails.set": 50}


class YouTubeAPIError(Exception):
    def __init__(self, message: str, *, status_code: int | None = None, reason: str = "", retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason
        self.retryable = retryable


class YouTubeQuotaError(YouTubeAPIError):
    pass


class YouTubeAuthError(YouTubeAPIError):
    pass


def parse_error(resp: httpx.Response) -> YouTubeAPIError:
    reason, message = "", resp.text[:300]
    try:
        err = resp.json().get("error", {})
        message = err.get("message", message)
        errors = err.get("errors") or []
        if errors:
            reason = errors[0].get("reason", "")
    except (ValueError, AttributeError):
        pass
    msg = f"YouTube API HTTP {resp.status_code}: {message}"
    if reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded", "userRateLimitExceeded"):
        return YouTubeQuotaError(msg, status_code=resp.status_code, reason=reason,
                                 retryable=reason in ("rateLimitExceeded", "userRateLimitExceeded"))
    if resp.status_code == 401:
        return YouTubeAuthError(msg, status_code=401, reason=reason or "unauthorized")
    return YouTubeAPIError(msg, status_code=resp.status_code, reason=reason, retryable=resp.status_code >= 500)


_ISO_DURATION = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def parse_iso_duration(value: str | None) -> int | None:
    if not value:
        return None
    m = _ISO_DURATION.fullmatch(value)
    if not m:
        return None
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s


class YouTubeDataClient:
    def __init__(self, *, api_key: str | None = None, access_token: str | None = None,
                 transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep,
                 max_retries: int = 3):
        if not api_key and not access_token:
            raise YouTubeAuthError("YouTube research needs YOUTUBE_API_KEY or a connected channel (OAuth).")
        self.api_key = api_key
        self.access_token = access_token
        self.quota_used = 0
        self._sleep = sleep
        self.max_retries = max_retries
        self._client = httpx.Client(timeout=get_settings().youtube_http_timeout_seconds, transport=transport)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "YouTubeDataClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get(self, resource: str, params: dict) -> dict:
        headers = {}
        params = {k: v for k, v in params.items() if v is not None}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        else:
            params["key"] = self.api_key
        for attempt in range(self.max_retries + 1):
            try:
                resp = self._client.get(f"{DATA_API}/{resource}", params=params, headers=headers)
            except httpx.TransportError as exc:
                err: YouTubeAPIError = YouTubeAPIError(f"Network error calling YouTube: {type(exc).__name__}",
                                                       retryable=True)
            else:
                if resp.status_code < 400:
                    self.quota_used += QUOTA_COST.get(resource, 1)
                    return resp.json()
                err = parse_error(resp)
            if not err.retryable or attempt >= self.max_retries:
                raise err
            self._sleep(min(2 ** attempt, 30))
        raise AssertionError("unreachable")

    def search_videos(self, query: str, *, max_results: int = 25, published_after: str | None = None,
                      published_before: str | None = None, relevance_language: str | None = None,
                      video_duration: str | None = None, order: str = "viewCount",
                      channel_id: str | None = None) -> list[str]:
        data = self._get("search", {
            "part": "id", "type": "video", "q": query or None, "maxResults": min(max_results, 50),
            "publishedAfter": published_after, "publishedBefore": published_before,
            "relevanceLanguage": relevance_language, "videoDuration": video_duration, "order": order,
            "channelId": channel_id, "safeSearch": "strict",
        })
        return [item["id"]["videoId"] for item in data.get("items", []) if item.get("id", {}).get("videoId")]

    def videos(self, ids: list[str], parts: str = "snippet,contentDetails,statistics") -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(ids), 50):
            data = self._get("videos", {"part": parts, "id": ",".join(ids[i:i + 50]),
                                        "maxResults": 50})
            out.extend(data.get("items", []))
        return out

    def channel(self, channel_id: str | None = None, *, mine: bool = False) -> dict | None:
        params = {"part": "snippet,contentDetails,statistics"}
        if mine:
            params["mine"] = "true"
        else:
            params["id"] = channel_id
        items = self._get("channels", params).get("items", [])
        return items[0] if items else None

    def channel_recent_video_ids(self, channel_id: str, max_results: int = 50) -> list[str]:
        ch = self.channel(channel_id)
        if not ch:
            raise YouTubeAPIError(f"Channel {channel_id} not found", status_code=404, reason="channelNotFound")
        uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
        data = self._get("playlistItems", {"part": "contentDetails", "playlistId": uploads,
                                           "maxResults": min(max_results, 50)})
        return [it["contentDetails"]["videoId"] for it in data.get("items", [])]


class YouTubeAnalyticsClient:
    """YouTube Analytics API v2 (requires OAuth with yt-analytics.readonly scope)."""

    def __init__(self, access_token: str, *, transport: httpx.BaseTransport | None = None):
        self.access_token = access_token
        self._client = httpx.Client(timeout=get_settings().youtube_http_timeout_seconds, transport=transport)

    def close(self) -> None:
        self._client.close()

    def query(self, *, start: date, end: date, metrics: list[str], dimensions: str | None = None,
              filters: str | None = None, sort: str | None = None, max_results: int | None = None) -> dict:
        params = {"ids": "channel==MINE", "startDate": start.isoformat(), "endDate": end.isoformat(),
                  "metrics": ",".join(metrics), "dimensions": dimensions, "filters": filters, "sort": sort,
                  "maxResults": max_results}
        resp = self._client.get(ANALYTICS_API, params={k: v for k, v in params.items() if v is not None},
                                headers={"Authorization": f"Bearer {self.access_token}"})
        if resp.status_code >= 400:
            raise parse_error(resp)
        return resp.json()

    @staticmethod
    def rows_as_dicts(report: dict) -> list[dict]:
        headers = [h["name"] for h in report.get("columnHeaders", [])]
        return [dict(zip(headers, row, strict=False)) for row in report.get("rows", []) or []]

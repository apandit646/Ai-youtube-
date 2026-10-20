"""Resumable video upload via the official videos.insert endpoint, with resume-after-failure support."""

import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from app.services.youtube.client import UPLOAD_API, YouTubeAPIError, parse_error

log = logging.getLogger(__name__)

CHUNK_SIZE = 8 * 1024 * 1024  # must be a multiple of 256 KiB
THUMBNAIL_API = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"


def build_video_resource(*, title: str, description: str, tags: list[str], category_id: str, language: str,
                         privacy_status: str, publish_at: str | None, made_for_kids: bool) -> dict:
    status: dict = {"privacyStatus": privacy_status, "selfDeclaredMadeForKids": made_for_kids,
                    "embeddable": True, "license": "youtube"}
    if publish_at:
        # YouTube only honours publishAt for private videos.
        status["privacyStatus"] = "private"
        status["publishAt"] = publish_at
    lang = "hi" if language in ("hi", "bilingual") else "en"
    return {
        "snippet": {"title": title[:100], "description": description[:5000], "tags": tags[:30],
                    "categoryId": category_id, "defaultLanguage": lang, "defaultAudioLanguage": lang},
        "status": status,
    }


class ResumableUploader:
    def __init__(self, access_token: str, *, transport: httpx.BaseTransport | None = None,
                 sleep: Callable[[float], None] = time.sleep, max_retries: int = 5, chunk_size: int = CHUNK_SIZE):
        self.access_token = access_token
        self._client = httpx.Client(timeout=httpx.Timeout(120.0, connect=15.0), transport=transport)
        self._sleep = sleep
        self.max_retries = max_retries
        self.chunk_size = chunk_size

    def close(self) -> None:
        self._client.close()

    def _auth(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    def start_session(self, resource: dict, file_size: int) -> str:
        resp = self._client.post(
            UPLOAD_API, params={"uploadType": "resumable", "part": "snippet,status"},
            headers={**self._auth(), "Content-Type": "application/json; charset=UTF-8",
                     "X-Upload-Content-Length": str(file_size), "X-Upload-Content-Type": "video/mp4"},
            content=json.dumps(resource).encode(),
        )
        if resp.status_code >= 400:
            raise parse_error(resp)
        location = resp.headers.get("location")
        if not location:
            raise YouTubeAPIError("YouTube did not return a resumable upload session URI")
        return location

    def _query_offset(self, session_uri: str, total: int) -> int | dict:
        """Ask the server how many bytes it has. Returns an offset, or the final resource if already complete."""
        resp = self._client.put(session_uri, headers={**self._auth(), "Content-Range": f"bytes */{total}",
                                                      "Content-Length": "0"})
        if resp.status_code in (200, 201):
            return resp.json()
        if resp.status_code == 308:
            rng = resp.headers.get("range")
            return int(rng.split("-")[1]) + 1 if rng else 0
        if resp.status_code == 404:
            raise YouTubeAPIError("Upload session expired", status_code=404, reason="sessionExpired")
        raise parse_error(resp)

    def upload(self, path: Path, session_uri: str, progress: Callable[[float], None] | None = None,
               resume: bool = False) -> dict:
        total = os.path.getsize(path)
        offset = 0
        if resume:
            state = self._query_offset(session_uri, total)
            if isinstance(state, dict):
                return state
            offset = state
        retries = 0
        with open(path, "rb") as fh:
            while True:
                fh.seek(offset)
                chunk = fh.read(self.chunk_size)
                end = offset + len(chunk) - 1
                try:
                    resp = self._client.put(session_uri, content=chunk, headers={
                        **self._auth(), "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {offset}-{end}/{total}", "Content-Type": "video/mp4"})
                except httpx.TransportError:
                    resp = None
                if resp is not None and resp.status_code in (200, 201):
                    if progress:
                        progress(1.0)
                    return resp.json()
                if resp is not None and resp.status_code == 308:
                    rng = resp.headers.get("range")
                    offset = int(rng.split("-")[1]) + 1 if rng else 0
                    retries = 0
                    if progress:
                        progress(offset / total)
                    continue
                if resp is not None and resp.status_code < 500 and resp.status_code != 429:
                    raise parse_error(resp)
                retries += 1
                if retries > self.max_retries:
                    raise YouTubeAPIError("Upload failed after repeated server/network errors", retryable=True)
                self._sleep(min(2 ** retries, 64))
                state = self._query_offset(session_uri, total)
                if isinstance(state, dict):
                    return state
                offset = state

    def set_thumbnail(self, video_id: str, thumbnail_path: Path) -> None:
        data = thumbnail_path.read_bytes()
        resp = self._client.post(THUMBNAIL_API, params={"videoId": video_id},
                                 headers={**self._auth(), "Content-Type": "image/png"}, content=data)
        if resp.status_code >= 400:
            raise parse_error(resp)

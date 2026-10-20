"""Public YouTube research: collect permitted public metadata/statistics, derive metrics, store snapshots,
and compute transparent observations. Only official Data API endpoints are used."""

import json
import logging
import re
import statistics
from collections import Counter, defaultdict
from datetime import UTC, datetime

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import CompetitorVideoSnapshot, ResearchQuery, TrendReport
from app.models.enums import JobStatus, ResearchType
from app.services.content import prompts
from app.services.llm.base import LLMUnavailableError
from app.services.llm.router import LLMRouter
from app.services.youtube.client import YouTubeDataClient, parse_iso_duration

log = logging.getLogger(__name__)

THEME_KEYWORDS: dict[str, list[str]] = {
    "animals": ["animal", "cat", "dog", "cow", "elephant", "lion", "monkey", "duck", "bird", "fish", "farm",
                "जानवर", "हाथी", "बिल्ली", "कुत्ता", "गाय", "शेर", "बंदर", "चिड़िया", "मछली", "तोता"],
    "numbers": ["number", "count", "1 2 3", "123", "counting", "गिनती", "संख्या", "एक दो"],
    "colors": ["color", "colour", "रंग"],
    "shapes": ["shape", "circle", "triangle", "square", "आकार"],
    "alphabet": ["abc", "alphabet", "phonics", "letter", "वर्णमाला", "क ख ग", "अ आ"],
    "bedtime": ["lullaby", "bedtime", "sleep", "लोरी", "सोजा", "नींद"],
    "kindness": ["kind", "share", "manners", "sorry", "thank you", "अच्छी आदत", "good habits"],
    "hygiene": ["bath", "brush", "wash", "clean", "नहाना", "दाँत"],
    "fruits": ["fruit", "apple", "mango", "banana", "फल", "आम", "केला"],
    "vehicles": ["car", "bus", "train", "truck", "गाड़ी", "रेल", "बस"],
    "family": ["mother", "father", "grandma", "family", "माँ", "पापा", "दादी", "नानी", "परिवार"],
    "nature": ["rain", "sun", "moon", "star", "बारिश", "चंदा", "सूरज", "तारे"],
}

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_LATIN = re.compile(r"[A-Za-z]")


class ResearchFilters(BaseModel):
    language: str | None = Field(default=None, pattern="^(hi|en|bilingual)$")
    published_after: datetime | None = None
    published_before: datetime | None = None
    video_format: str | None = Field(default=None, pattern="^(short|long)$")
    min_views: int = Field(default=0, ge=0)
    max_results: int = Field(default=25, ge=1, le=50)
    order: str = Field(default="viewCount", pattern="^(viewCount|date|relevance|rating)$")


def detect_language(text: str) -> str:
    dev, lat = len(_DEVANAGARI.findall(text)), len(_LATIN.findall(text))
    if dev == 0 and lat == 0:
        return "unknown"
    if dev and lat and min(dev, lat) / max(dev, lat) > 0.25:
        return "bilingual"
    if dev > lat:
        return "hi"
    # Romanised Hindi ("Machli jal ki rani") is common; flag it with a few marker words.
    lower = text.lower()
    if any(w in lower for w in (" ki ", " ka ", " hai", "hindi", " mama", "balgeet", "kavita")):
        return "hi"
    return "en"


def classify_format(duration: int | None, text: str) -> str:
    if duration is None:
        return "unknown"
    if duration <= 60 or (duration <= 180 and "#short" in text.lower()):
        return "short"
    return "long"


def detect_topics(text: str) -> list[str]:
    lower = text.lower()
    return [theme for theme, words in THEME_KEYWORDS.items() if any(w in lower for w in words)]


def _int(v: object) -> int | None:
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def snapshot_from_item(item: dict, now: datetime) -> dict:
    sn, st, cd = item.get("snippet", {}), item.get("statistics", {}), item.get("contentDetails", {})
    published = None
    if sn.get("publishedAt"):
        published = datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00"))
    duration = parse_iso_duration(cd.get("duration"))
    views, likes, comments = _int(st.get("viewCount")), _int(st.get("likeCount")), _int(st.get("commentCount"))
    text = f"{sn.get('title', '')}\n{sn.get('description', '')}"
    vpd = None
    if views is not None and published:
        age_days = max((now - published).total_seconds() / 86400, 1.0)
        vpd = round(views / age_days, 2)
    engagement = None
    if views and (likes is not None or comments is not None):
        engagement = round(((likes or 0) + (comments or 0)) / views, 5)
    return {
        "video_id": item["id"], "channel_id": sn.get("channelId", ""), "channel_title": sn.get("channelTitle", ""),
        "title": sn.get("title", "")[:512], "description": sn.get("description", "")[:5000],
        "published_at": published, "duration_seconds": duration, "view_count": views, "like_count": likes,
        "comment_count": comments, "views_per_day": vpd, "engagement_rate": engagement,
        "language": detect_language(text), "video_format": classify_format(duration, text),
        "topics": detect_topics(text),
    }


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 2) if values else None


def compute_observations(snaps: list[CompetitorVideoSnapshot]) -> dict:
    """Pure function: facts derived only from stored public data."""
    if not snaps:
        return {"video_count": 0, "note": "No videos matched the query and filters."}

    def group(key) -> dict:
        buckets: dict[str, list[CompetitorVideoSnapshot]] = defaultdict(list)
        for s in snaps:
            for k in key(s):
                buckets[k].append(s)
        return {k: {"videos": len(v), "median_views": _median([x.view_count for x in v if x.view_count is not None]),
                    "median_views_per_day": _median([x.views_per_day for x in v if x.views_per_day is not None])}
                for k, v in sorted(buckets.items(), key=lambda kv: -len(kv[1]))}

    weekday = Counter(s.published_at.strftime("%A") for s in snaps if s.published_at)
    hour = Counter(s.published_at.hour for s in snaps if s.published_at)
    durations = [s.duration_seconds for s in snaps if s.duration_seconds is not None]
    top = sorted((s for s in snaps if s.views_per_day is not None), key=lambda s: -s.views_per_day)[:10]
    channels = Counter(s.channel_title for s in snaps)
    words = Counter()
    for s in snaps:
        for w in re.findall(r"[\wऀ-ॿ]{3,}", s.title.lower()):
            if w not in {"the", "and", "for", "song", "songs", "kids", "rhymes", "nursery", "baby", "with", "shorts",
                         "rhyme", "children", "हिंदी", "बच्चों", "के", "लिए"}:
                words[w] += 1
    obs = {
        "video_count": len(snaps),
        "captured_at": max(s.captured_at for s in snaps).isoformat() if snaps[0].captured_at else None,
        "published_range": {
            "earliest": min((s.published_at for s in snaps if s.published_at), default=None),
            "latest": max((s.published_at for s in snaps if s.published_at), default=None),
        },
        "median_views": _median([s.view_count for s in snaps if s.view_count is not None]),
        "median_views_per_day": _median([s.views_per_day for s in snaps if s.views_per_day is not None]),
        "median_engagement_rate": _median([s.engagement_rate for s in snaps if s.engagement_rate is not None]),
        "by_language": group(lambda s: [s.language]),
        "by_format": group(lambda s: [s.video_format]),
        "top_topics": [{"topic": k, **v} for k, v in group(lambda s: s.topics or ["unclassified"]).items()],
        "upload_weekday_utc": dict(weekday.most_common()),
        "upload_hour_utc": {str(h): c for h, c in sorted(hour.items())},
        "duration_seconds": {"median": _median(durations), "min": min(durations, default=None),
                             "max": max(durations, default=None)},
        "frequent_title_words": [w for w, _ in words.most_common(15)],
        "top_by_views_per_day": [{"video_id": s.video_id, "title": s.title, "channel": s.channel_title,
                                  "views_per_day": s.views_per_day, "language": s.language,
                                  "format": s.video_format} for s in top],
        "channels": dict(channels.most_common(10)),
        "data_limits": [
            "Public statistics only: competitors' CTR, retention, impressions, revenue and subscriber analytics "
            "are not available through the API and are never inferred.",
            "Search results are a ranked sample, not the full population of videos.",
            "Language/format/topic labels are heuristic classifications of titles, descriptions and durations.",
        ],
    }
    return json.loads(json.dumps(obs, default=lambda v: v.isoformat() if isinstance(v, datetime) else str(v)))


class ResearchService:
    def __init__(self, db: Session, owner_id: int, router: LLMRouter | None = None,
                 yt_factory=None):
        self.db = db
        self.owner_id = owner_id
        self.router = router
        self._yt_factory = yt_factory

    def _client(self, access_token: str | None) -> YouTubeDataClient:
        if self._yt_factory:
            return self._yt_factory()
        api_key = get_settings().youtube_api_key
        return YouTubeDataClient(api_key=api_key or None, access_token=None if api_key else access_token)

    def run(self, query: ResearchQuery, access_token: str | None = None) -> TrendReport:
        filters = ResearchFilters.model_validate(query.filters or {})
        query.status = JobStatus.RUNNING
        self.db.flush()
        now = datetime.now(UTC)
        with self._client(access_token) as yt:
            if query.query_type == ResearchType.CHANNEL:
                ids = yt.channel_recent_video_ids(query.query_text.strip(), filters.max_results)
            else:
                ids = yt.search_videos(
                    query.query_text, max_results=filters.max_results,
                    published_after=_rfc3339(filters.published_after),
                    published_before=_rfc3339(filters.published_before),
                    relevance_language="hi" if filters.language in ("hi", "bilingual") else filters.language,
                    video_duration="short" if filters.video_format == "short" else None,
                    order=filters.order,
                )
            items = yt.videos(ids) if ids else []
            query.quota_units_used = yt.quota_used

        kept = 0
        for item in items:
            data = snapshot_from_item(item, now)
            if filters.min_views and (data["view_count"] or 0) < filters.min_views:
                continue
            if filters.language and data["language"] != filters.language:
                continue
            if filters.video_format and data["video_format"] != filters.video_format:
                continue
            self.db.add(CompetitorVideoSnapshot(research_query_id=query.id, captured_at=now, **data))
            kept += 1
        query.result_count = kept
        query.status = JobStatus.SUCCEEDED
        self.db.flush()
        return self.build_report(query)

    def build_report(self, query: ResearchQuery) -> TrendReport:
        self.db.refresh(query)
        observations = compute_observations(list(query.snapshots))
        report = TrendReport(owner_id=self.owner_id, research_query_id=query.id, observations=observations)
        if self.router and self.router.any_configured and observations.get("video_count"):
            from app.services.research.schemas import TrendSummary

            try:
                res = self.router.generate("trend_analysis", prompts.SYSTEM_ANALYST,
                                           prompts.trend_prompt(observations), TrendSummary, temperature=0.3)
                report.ai_summary = res.data.model_dump()
                report.provider, report.model = res.provider, res.model
            except LLMUnavailableError as exc:
                report.error = f"AI summary unavailable: {exc}"
        elif observations.get("video_count"):
            report.error = "AI summary skipped: no AI provider configured. Observations are still valid."
        self.db.add(report)
        self.db.flush()
        return report


def _rfc3339(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

"""Authorised channel analytics collection, transparent comparisons and evidence-based recommendations."""

import logging
import statistics
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import AnalyticsSnapshot, PublishedVideo, Recommendation
from app.services.content import prompts
from app.services.llm.base import LLMUnavailableError
from app.services.llm.router import LLMRouter
from app.services.youtube.client import YouTubeAnalyticsClient, YouTubeAPIError, YouTubeDataClient

log = logging.getLogger(__name__)

CHANNEL_METRICS = ["views", "estimatedMinutesWatched", "averageViewDuration", "subscribersGained",
                   "subscribersLost"]
VIDEO_METRICS = ["views", "estimatedMinutesWatched", "averageViewDuration", "averageViewPercentage", "likes",
                 "subscribersGained"]
# Not exposed by the YouTube Analytics API v2 targeted queries we use; shown as unavailable, never estimated.
NEVER_AVAILABLE = ["impressions", "impressionsClickThroughRate"]


class AnalyticsCollector:
    def __init__(self, db: Session, owner_id: int, access_token: str, *, transport=None):
        self.db = db
        self.owner_id = owner_id
        self.client = YouTubeAnalyticsClient(access_token, transport=transport)
        self.data_client = YouTubeDataClient(access_token=access_token, transport=transport)

    def close(self) -> None:
        self.client.close()
        self.data_client.close()

    def _upsert(self, scope: str, video_id: str, day: date, metrics: dict, unavailable: list[str],
                source: str = "youtube_analytics_v2") -> None:
        self.db.execute(delete(AnalyticsSnapshot).where(
            AnalyticsSnapshot.owner_id == self.owner_id, AnalyticsSnapshot.scope == scope,
            AnalyticsSnapshot.youtube_video_id == video_id, AnalyticsSnapshot.day == day))
        self.db.add(AnalyticsSnapshot(owner_id=self.owner_id, scope=scope, youtube_video_id=video_id, day=day,
                                      metrics=metrics, unavailable_metrics=unavailable, source=source))

    def collect(self, days: int = 28) -> dict:
        end = datetime.now(UTC).date() - timedelta(days=1)  # analytics lag; today is always incomplete
        start = end - timedelta(days=days - 1)
        summary: dict = {"start": start.isoformat(), "end": end.isoformat(), "errors": []}

        try:
            report = self.client.query(start=start, end=end, metrics=CHANNEL_METRICS, dimensions="day", sort="day")
            rows = YouTubeAnalyticsClient.rows_as_dicts(report)
            for row in rows:
                d = date.fromisoformat(row.pop("day"))
                self._upsert("channel", "", d, row, NEVER_AVAILABLE)
            summary["channel_days"] = len(rows)
        except YouTubeAPIError as exc:
            summary["errors"].append(f"channel daily metrics: {exc}")

        try:
            report = self.client.query(start=start, end=end, metrics=["views", "estimatedMinutesWatched"],
                                       dimensions="insightTrafficSourceType", sort="-views")
            sources = YouTubeAnalyticsClient.rows_as_dicts(report)
            self._upsert("traffic", "", end, {"sources": sources}, [])
            summary["traffic_sources"] = len(sources)
        except YouTubeAPIError as exc:
            summary["errors"].append(f"traffic sources: {exc}")

        videos = list(self.db.scalars(select(PublishedVideo).where(PublishedVideo.owner_id == self.owner_id)))
        ids = [v.youtube_video_id for v in videos]
        summary["videos"] = 0
        for i in range(0, len(ids), 200):
            batch = ids[i:i + 200]
            try:
                report = self.client.query(start=date(2005, 4, 23), end=end, metrics=VIDEO_METRICS,
                                           dimensions="video", filters=f"video=={','.join(batch)}",
                                           sort="-views", max_results=200)
                for row in YouTubeAnalyticsClient.rows_as_dicts(report):
                    vid = row.pop("video")
                    self._upsert("video", vid, end, {**row, "period": "lifetime"}, NEVER_AVAILABLE)
                    summary["videos"] += 1
            except YouTubeAPIError as exc:
                summary["errors"].append(f"per-video metrics: {exc}")
        # Audience retention curve for the most recent videos (exposed per video via elapsedVideoTimeRatio).
        for v in sorted(videos, key=lambda v: v.created_at, reverse=True)[:5]:
            try:
                report = self.client.query(start=date(2005, 4, 23), end=end, metrics=["audienceWatchRatio"],
                                           dimensions="elapsedVideoTimeRatio", filters=f"video=={v.youtube_video_id}")
                curve = YouTubeAnalyticsClient.rows_as_dicts(report)
                if curve:
                    self._upsert("retention", v.youtube_video_id, end, {"curve": curve}, [])
            except YouTubeAPIError as exc:
                summary["errors"].append(f"retention {v.youtube_video_id}: {exc}")
        # Public counters straight from the Data API (cheap; useful while Analytics data is still processing).
        try:
            for item in self.data_client.videos(ids, "statistics,status") if ids else []:
                st = item.get("statistics", {})
                self._upsert("public", item["id"], datetime.now(UTC).date(),
                             {k: int(v) for k, v in st.items() if str(v).isdigit()}, [], source="youtube_data_v3")
                pv = next((v for v in videos if v.youtube_video_id == item["id"]), None)
                if pv:
                    pv.privacy_status = item.get("status", {}).get("privacyStatus", pv.privacy_status)
        except YouTubeAPIError as exc:
            summary["errors"].append(f"public statistics: {exc}")
        self.db.flush()
        return summary


def _latest_video_metrics(db: Session, owner_id: int) -> dict[str, dict]:
    out: dict[str, dict] = {}
    rows = db.scalars(select(AnalyticsSnapshot).where(AnalyticsSnapshot.owner_id == owner_id,
                                                      AnalyticsSnapshot.scope.in_(["video", "public"]))
                      .order_by(AnalyticsSnapshot.captured_at, AnalyticsSnapshot.id))
    for snap in rows:
        cur = out.setdefault(snap.youtube_video_id, {})
        if snap.scope == "video":
            cur.update(snap.metrics)
        else:
            cur.setdefault("public_view_count", snap.metrics.get("viewCount"))
            cur["public_view_count"] = snap.metrics.get("viewCount", cur.get("public_view_count"))
    return out


def duration_bucket(seconds: float | None) -> str:
    if seconds is None:
        return "unknown"
    if seconds <= 60:
        return "≤60s"
    if seconds <= 180:
        return "61-180s"
    if seconds <= 600:
        return "3-10min"
    return ">10min"


def video_table(db: Session, owner_id: int) -> list[dict]:
    metrics = _latest_video_metrics(db, owner_id)
    rows = []
    for v in db.scalars(select(PublishedVideo).where(PublishedVideo.owner_id == owner_id)
                        .order_by(PublishedVideo.created_at.desc())):
        m = metrics.get(v.youtube_video_id, {})
        publish = v.publish_at or v.created_at
        rows.append({
            "youtube_video_id": v.youtube_video_id, "title": v.title, "language": v.language, "topic": v.topic,
            "format": v.video_format, "duration_seconds": v.duration_seconds, "privacy_status": v.privacy_status,
            "published_at": publish.isoformat() if publish else None,
            "publish_hour_utc": publish.hour if publish else None,
            "views": m.get("views", m.get("public_view_count")),
            "views_source": "analytics" if "views" in m else ("public" if "public_view_count" in m else None),
            "estimated_minutes_watched": m.get("estimatedMinutesWatched"),
            "average_view_duration": m.get("averageViewDuration"),
            "average_view_percentage": m.get("averageViewPercentage"),
            "likes": m.get("likes"), "subscribers_gained": m.get("subscribersGained"),
            "impressions": None, "ctr": None,  # unavailable via API; never estimated
        })
    return rows


def compare(db: Session, owner_id: int) -> dict:
    rows = [r for r in video_table(db, owner_id) if r["views"] is not None]

    def group(key: str) -> list[dict]:
        buckets: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            k = r[key] if key != "duration" else duration_bucket(r["duration_seconds"])
            buckets[str(k) if k is not None else "unknown"].append(r)
        out = []
        for k, items in buckets.items():
            views = [r["views"] for r in items]
            avp = [r["average_view_percentage"] for r in items if r["average_view_percentage"] is not None]
            out.append({"group": k, "videos": len(items), "mean_views": round(statistics.mean(views), 1),
                        "median_views": statistics.median(views),
                        "mean_avg_view_percentage": round(statistics.mean(avp), 1) if avp else None})
        return sorted(out, key=lambda g: -g["median_views"])

    return {"video_count": len(rows), "by_language": group("language"), "by_topic": group("topic"),
            "by_format": group("format"), "by_duration": group("duration"),
            "by_publish_hour_utc": group("publish_hour_utc"),
            "experiments": "No title/thumbnail A/B experiment data is recorded; comparisons are observational."}


def confidence_for(n_small: int) -> str:
    if n_small >= 15:
        return "high"
    if n_small >= 5:
        return "medium"
    return "low"


def statistical_recommendations(stats: dict) -> list[dict]:
    """Transparent rule: recommend a dimension value when its median views beat the runner-up by ≥50% and both
    groups have at least 3 videos."""
    recs = []
    labels = {"by_language": "language", "by_topic": "topic", "by_format": "format", "by_duration": "duration",
              "by_publish_hour_utc": "timing"}
    for key, category in labels.items():
        groups = [g for g in stats.get(key, []) if g["videos"] >= 3 and g["group"] != "unknown"]
        if len(groups) < 2:
            continue
        best, second = groups[0], groups[1]
        if second["median_views"] > 0 and best["median_views"] >= 1.5 * second["median_views"]:
            ratio = best["median_views"] / second["median_views"]
            recs.append({
                "category": category,
                "title": f"Make more {category} = {best['group']} videos",
                "body": (f"Median views for {category} '{best['group']}' ({best['median_views']:.0f}, "
                         f"n={best['videos']}) are {ratio:.1f}x those for '{second['group']}' "
                         f"({second['median_views']:.0f}, n={second['videos']}). Observational data only: other "
                         "factors may explain the gap, so test it in the next batch rather than switching entirely."),
                "supporting_data": {"best": best, "runner_up": second},
                "confidence": confidence_for(min(best["videos"], second["videos"])),
            })
    if stats.get("video_count", 0) < 6:
        recs.append({
            "category": "general", "title": "Collect more data before drawing conclusions",
            "body": f"Only {stats.get('video_count', 0)} published videos have metrics. Keep a consistent schedule and "
                    "vary one factor at a time (e.g. language or topic) so comparisons become meaningful.",
            "supporting_data": {"video_count": stats.get("video_count", 0)}, "confidence": "high",
        })
    return recs


class LLMRec(BaseModel):
    category: str = "general"
    title: str = Field(min_length=3, max_length=255)
    body: str = Field(min_length=5)
    evidence: str = ""
    confidence: str = "low"


class LLMRecList(BaseModel):
    recommendations: list[LLMRec] = Field(default_factory=list, max_length=5)


def generate_recommendations(db: Session, owner_id: int, router: LLMRouter | None) -> list[Recommendation]:
    stats = compare(db, owner_id)
    created: list[Recommendation] = []
    for r in statistical_recommendations(stats):
        rec = Recommendation(owner_id=owner_id, source="statistics", **r)
        db.add(rec)
        created.append(rec)
    if router and router.any_configured and stats["video_count"] >= 3:
        try:
            res = router.generate("recommendations", prompts.SYSTEM_ANALYST, prompts.recommendations_prompt(stats),
                                  LLMRecList, temperature=0.3)
            for r in res.data.recommendations:
                conf = r.confidence if r.confidence in ("low", "medium", "high") else "low"
                if stats["video_count"] < 10:
                    conf = "low"  # never let the model overstate confidence on tiny samples
                rec = Recommendation(owner_id=owner_id, category=r.category[:32], title=r.title, body=r.body,
                                     supporting_data={"evidence": r.evidence, "stats_snapshot": stats},
                                     confidence=conf, source=res.provider)
                db.add(rec)
                created.append(rec)
        except LLMUnavailableError as exc:
            log.warning("AI recommendations unavailable: %s", exc)
    db.flush()
    return created

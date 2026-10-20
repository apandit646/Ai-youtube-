from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query, status
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, Paging, owned
from app.core.errors import ConfigurationError
from app.models import AnalyticsSnapshot, Recommendation
from app.models.enums import JobKind, RecommendationStatus
from app.schemas.api import JobOut, Page, RecommendationOut, RecommendationUpdate
from app.services import jobs
from app.services.analytics.service import NEVER_AVAILABLE, compare, video_table
from app.services.youtube.oauth import active_channel

router = APIRouter(tags=["analytics"])


@router.get("/analytics/overview")
def overview(db: DB, user: CurrentUser, days: int = Query(28, ge=7, le=365)) -> dict:
    channel = active_channel(db, user.id)
    since = datetime.now(UTC).date() - timedelta(days=days)
    snaps = list(db.scalars(select(AnalyticsSnapshot).where(
        AnalyticsSnapshot.owner_id == user.id, AnalyticsSnapshot.scope == "channel", AnalyticsSnapshot.day >= since)
        .order_by(AnalyticsSnapshot.day)))
    traffic = db.scalar(select(AnalyticsSnapshot).where(AnalyticsSnapshot.owner_id == user.id,
                                                        AnalyticsSnapshot.scope == "traffic")
                        .order_by(AnalyticsSnapshot.day.desc()).limit(1))
    last = db.scalar(select(func.max(AnalyticsSnapshot.captured_at)).where(AnalyticsSnapshot.owner_id == user.id))
    totals: dict = {}
    for s in snaps:
        for k, v in s.metrics.items():
            if isinstance(v, int | float) and k != "averageViewDuration":
                totals[k] = totals.get(k, 0) + v
    avd = [s.metrics.get("averageViewDuration") for s in snaps if s.metrics.get("averageViewDuration") is not None]
    if avd:
        totals["averageViewDuration"] = round(sum(avd) / len(avd), 1)
    return {
        "connected": channel is not None,
        "has_data": bool(snaps),
        "last_collected_at": last,
        "series": [{"day": s.day.isoformat(), **s.metrics} for s in snaps],
        "totals": totals,
        "traffic_sources": traffic.metrics.get("sources", []) if traffic else [],
        "unavailable_metrics": NEVER_AVAILABLE,
        "channel": {"title": channel.title, "subscriber_count": channel.subscriber_count} if channel else None,
        "note": None if snaps else ("No analytics collected yet. Connect a channel and run a refresh; YouTube "
                                    "Analytics data typically lags 24-72 hours."),
    }


@router.get("/analytics/videos")
def videos(db: DB, user: CurrentUser, paging: Paging) -> dict:
    rows = video_table(db, user.id)
    return {"items": rows[paging.offset: paging.offset + paging.page_size], "total": len(rows), "page": paging.page,
            "page_size": paging.page_size, "unavailable_metrics": NEVER_AVAILABLE}


@router.get("/analytics/videos/{youtube_video_id}/retention")
def retention(youtube_video_id: str, db: DB, user: CurrentUser) -> dict:
    snap = db.scalar(select(AnalyticsSnapshot).where(AnalyticsSnapshot.owner_id == user.id,
                                                     AnalyticsSnapshot.scope == "retention",
                                                     AnalyticsSnapshot.youtube_video_id == youtube_video_id)
                     .order_by(AnalyticsSnapshot.day.desc()).limit(1))
    return {"available": snap is not None, "curve": snap.metrics.get("curve", []) if snap else []}


@router.get("/analytics/compare")
def comparisons(db: DB, user: CurrentUser) -> dict:
    return compare(db, user.id)


@router.post("/analytics/refresh", status_code=status.HTTP_202_ACCEPTED, response_model=JobOut)
def refresh(db: DB, user: CurrentUser):
    if active_channel(db, user.id) is None:
        raise ConfigurationError("Connect a YouTube channel to collect analytics.")
    job = jobs.enqueue(db, user.id, JobKind.ANALYTICS, {"days": 28})
    db.commit()
    return job


@router.get("/recommendations", response_model=Page[RecommendationOut])
def recommendations(db: DB, user: CurrentUser, paging: Paging, status_filter: RecommendationStatus | None =
                    Query(None, alias="status")) -> dict:
    base = select(Recommendation).where(Recommendation.owner_id == user.id)
    if status_filter:
        base = base.where(Recommendation.status == status_filter)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    items = db.scalars(base.order_by(Recommendation.id.desc()).offset(paging.offset).limit(paging.page_size))
    return {"items": list(items), "total": total, "page": paging.page, "page_size": paging.page_size}


@router.post("/recommendations/generate", status_code=status.HTTP_202_ACCEPTED, response_model=JobOut)
def generate(db: DB, user: CurrentUser):
    job = jobs.enqueue(db, user.id, JobKind.RECOMMEND, {})
    db.commit()
    return job


@router.put("/recommendations/{rec_id}", response_model=RecommendationOut)
def update_recommendation(rec_id: int, body: RecommendationUpdate, db: DB, user: CurrentUser) -> Recommendation:
    """Accepting a recommendation only records the decision; it never changes settings automatically."""
    rec = owned(db.get(Recommendation, rec_id), user, "Recommendation")
    rec.status = RecommendationStatus(body.status)
    db.commit()
    return rec

"""Health, dashboard, automation controls and audit log."""

import os
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, status
from sqlalchemy import func, select, text

from app.api.deps import DB, CurrentUser, Paging, UserSettings
from app.core.config import get_settings
from app.models import AuditLog, Job, PublishingJob, VideoProject
from app.models.enums import JobKind, JobStatus, ProjectStatus, PublishStatus
from app.schemas.api import AuditOut, JobOut, Page
from app.services import jobs
from app.services.analytics.service import NEVER_AVAILABLE
from app.services.audit import audit
from app.services.llm.router import LLMRouter
from app.services.media.audio import EspeakNarrationProvider
from app.services.media.ffmpeg import ffmpeg_available
from app.services.youtube.oauth import active_channel, oauth_configured
from app.workers.main import heartbeat_path

from .settings import provider_statuses
from .videos import pj_out, project_out

router = APIRouter(tags=["system"])


def _worker_heartbeat() -> str | None:
    try:
        return heartbeat_path().read_text().strip() or None
    except OSError:
        return None


@router.get("/health")
def health(db: DB) -> dict:
    """Public liveness/readiness: DB connectivity, FFmpeg and media volume. Never exposes secrets."""
    s = get_settings()
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db_ok = False
    media_ok = os.access(s.media_root, os.W_OK) if s.media_root.exists() else False
    return {
        "status": "ok" if db_ok else "degraded",
        "time": datetime.now(UTC),
        "components": {"database": db_ok, "ffmpeg": ffmpeg_available(), "media_volume_writable": media_ok,
                       "tts": EspeakNarrationProvider().available()},
        "configuration": {
            "ai_provider_env": any([s.xai_api_key and s.xai_model, s.openai_api_key and s.openai_model,
                                    s.gemini_api_key and s.gemini_model]),
            "google_oauth": oauth_configured(),
            "youtube_api_key": bool(s.youtube_api_key),
            "default_secret_key": s.secret_key.startswith("change-me"),
        },
    }


@router.get("/dashboard")
def dashboard(db: DB, user: CurrentUser, app_settings: UserSettings) -> dict:
    now = datetime.now(UTC)
    counts = dict(db.execute(select(Job.status, func.count(Job.id)).where(Job.owner_id == user.id)
                             .group_by(Job.status)).all())
    failed_recent = db.scalar(select(func.count(Job.id)).where(
        Job.owner_id == user.id, Job.status == JobStatus.FAILED, Job.finished_at >= now - timedelta(days=7))) or 0
    by_status = dict(db.execute(select(VideoProject.status, func.count(VideoProject.id))
                                .where(VideoProject.owner_id == user.id).group_by(VideoProject.status)).all())
    recent = db.scalars(select(VideoProject).where(VideoProject.owner_id == user.id)
                        .order_by(VideoProject.id.desc()).limit(6))
    upcoming = db.scalars(select(PublishingJob).where(
        PublishingJob.owner_id == user.id, PublishingJob.publish_at >= now,
        PublishingJob.status.in_([PublishStatus.QUEUED, PublishStatus.UPLOADING, PublishStatus.SCHEDULED]))
        .order_by(PublishingJob.publish_at).limit(5))
    running = db.scalars(select(Job).where(Job.owner_id == user.id, Job.status.in_([JobStatus.RUNNING,
                                                                                    JobStatus.QUEUED]))
                         .order_by(Job.id.desc()).limit(8))
    channel = active_channel(db, user.id)
    from app.api.v1.analytics import overview

    analytics = overview(db, user, 28)
    heartbeat = _worker_heartbeat()
    llm = LLMRouter.from_settings(app_settings)
    return {
        "channel": {"connected": channel is not None, "title": channel.title if channel else None,
                    "subscriber_count": channel.subscriber_count if channel else None,
                    "video_count": channel.video_count if channel else None},
        "analytics": {"has_data": analytics["has_data"], "totals": analytics["totals"],
                      "last_collected_at": analytics["last_collected_at"], "unavailable": NEVER_AVAILABLE},
        "jobs": {"queued": counts.get(JobStatus.QUEUED, 0), "running": counts.get(JobStatus.RUNNING, 0),
                 "failed_last_7_days": failed_recent, "succeeded": counts.get(JobStatus.SUCCEEDED, 0)},
        "active_jobs": [JobOut.model_validate(j).model_dump(mode="json") for j in running],
        "projects_by_status": {k.value: v for k, v in by_status.items()},
        "recent_videos": [project_out(p).model_dump(mode="json") for p in recent],
        "upcoming": [{**pj_out(p).model_dump(mode="json"), "project_title": p.project.title} for p in upcoming],
        "automation": {"enabled": app_settings.automation_enabled, "paused": app_settings.paused,
                       "dry_run": app_settings.dry_run, "auto_publish": app_settings.auto_publish_enabled,
                       "private_test_passed_at": app_settings.private_test_passed_at},
        "connections": {
            "ai_providers": [p.model_dump() for p in provider_statuses(app_settings)],
            "ai_configured": llm.any_configured,
            "youtube_oauth_configured": oauth_configured(),
            "youtube_connected": channel is not None,
            "worker_heartbeat": heartbeat,
            "worker_alive": bool(heartbeat) and (now - datetime.fromisoformat(heartbeat)).total_seconds() < 60,
        },
    }


@router.post("/automation/pause")
def pause(db: DB, user: CurrentUser, app_settings: UserSettings) -> dict:
    """Global stop: no new uploads or automated runs. Queued upload/pipeline jobs are cancelled."""
    app_settings.paused = True
    cancelled = 0
    for job in db.scalars(select(Job).where(Job.owner_id == user.id, Job.status == JobStatus.QUEUED,
                                            Job.kind.in_([JobKind.UPLOAD, JobKind.PIPELINE]))):
        jobs.mark_cancelled(job)
        cancelled += 1
    for pj in db.scalars(select(PublishingJob).where(PublishingJob.owner_id == user.id,
                                                     PublishingJob.status == PublishStatus.QUEUED)):
        pj.status = PublishStatus.CANCELLED
        pj.last_error = "Cancelled by global pause"
        project = db.get(VideoProject, pj.project_id)
        if project and project.status == ProjectStatus.UPLOADING:
            project.status = ProjectStatus.READY
    audit(db, user.id, "automation.paused", "app_settings", app_settings.id, cancelled_jobs=cancelled)
    db.commit()
    return {"paused": True, "cancelled_jobs": cancelled,
            "note": "Videos already scheduled on YouTube keep their publish time; change them in YouTube Studio."}


@router.post("/automation/resume")
def resume(db: DB, user: CurrentUser, app_settings: UserSettings) -> dict:
    app_settings.paused = False
    audit(db, user.id, "automation.resumed", "app_settings", app_settings.id)
    db.commit()
    return {"paused": False}


@router.post("/automation/run", status_code=status.HTTP_202_ACCEPTED, response_model=JobOut)
def run_now(db: DB, user: CurrentUser, app_settings: UserSettings):
    """Start one end-to-end pipeline run now (research → script → render → publish policy)."""
    from app.services.publishing import PublishBlocked

    if app_settings.paused:
        raise PublishBlocked("Automation is paused")
    job = jobs.enqueue(db, user.id, JobKind.PIPELINE, {"trigger": "manual"})
    audit(db, user.id, "automation.run", "job", job.id)
    db.commit()
    return job


@router.get("/audit", response_model=Page[AuditOut])
def audit_log(db: DB, user: CurrentUser, paging: Paging) -> dict:
    base = select(AuditLog).where(AuditLog.owner_id == user.id)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    items = db.scalars(base.order_by(AuditLog.id.desc()).offset(paging.offset).limit(paging.page_size))
    return {"items": list(items), "total": total, "page": paging.page, "page_size": paging.page_size}

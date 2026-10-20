"""Publishing policy, scheduling slots, idempotent uploads and YouTube result recording."""

import logging
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, ConfigurationError, ConflictError, InvalidStateError
from app.models import AppSettings, PublishedVideo, PublishingJob, RhymeScript, VideoProject
from app.models.enums import JobKind, ProjectStatus, PublishStatus
from app.services import jobs
from app.services.audit import audit
from app.services.media.storage import safe_path
from app.services.workflow import transition
from app.services.youtube.client import YouTubeAPIError
from app.services.youtube.oauth import active_channel, get_access_token
from app.services.youtube.uploader import ResumableUploader, build_video_resource

log = logging.getLogger(__name__)

ACTIVE_STATUSES = (PublishStatus.QUEUED, PublishStatus.UPLOADING, PublishStatus.SCHEDULED, PublishStatus.PUBLISHED,
                   PublishStatus.UPLOADED_PRIVATE)
PACIFIC = ZoneInfo("America/Los_Angeles")  # YouTube API quota resets at midnight Pacific time


class PublishRequest(BaseModel):
    publish_at: datetime | None = None
    privacy_status: str = Field(default="private", pattern="^(private|unlisted|public)$")
    is_test_upload: bool = False
    title: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = None
    made_for_kids: bool | None = None


class PublishBlocked(AppError):
    status_code = 409
    code = "publishing_blocked"


def validate_metadata(title: str, description: str, tags: list[str]) -> list[str]:
    errors = []
    if not title.strip():
        errors.append("Title is required")
    if len(title) > 100:
        errors.append("Title must be at most 100 characters")
    if "<" in title or ">" in title or "<" in description or ">" in description:
        errors.append("Title/description must not contain < or >")
    if len(description.encode()) > 5000:
        errors.append("Description must be at most 5000 bytes")
    if sum(len(t) + (2 if " " in t else 0) for t in tags) + max(len(tags) - 1, 0) > 500:
        errors.append("Tags exceed YouTube's 500 character limit")
    return errors


def _tz(app_settings: AppSettings) -> ZoneInfo:
    try:
        return ZoneInfo(app_settings.timezone)
    except Exception:  # noqa: BLE001 - invalid tz name stored
        return ZoneInfo("UTC")


def next_publish_slot(db: Session, app_settings: AppSettings, *, after: datetime | None = None) -> datetime:
    """First free slot inside the publishing window, respecting allowed weekdays and the per-day cap."""
    tz = _tz(app_settings)
    earliest = max(after or datetime.now(UTC), datetime.now(UTC) + timedelta(hours=1))
    start_h = app_settings.publish_window_start_hour
    end_h = max(app_settings.publish_window_end_hour, start_h + 1)
    cap = max(app_settings.max_uploads_per_day, 1)
    days = set(app_settings.publish_days or range(7))
    local = earliest.astimezone(tz)
    for offset in range(0, 60):
        day = local.date() + timedelta(days=offset)
        if day.weekday() not in days:
            continue
        day_start = datetime.combine(day, time(0), tz)
        taken = list(db.scalars(select(PublishingJob.publish_at).where(
            PublishingJob.owner_id == app_settings.owner_id, PublishingJob.status.in_(ACTIVE_STATUSES),
            PublishingJob.is_test_upload.is_(False), PublishingJob.publish_at >= day_start.astimezone(UTC),
            PublishingJob.publish_at < (day_start + timedelta(days=1)).astimezone(UTC))))
        if len(taken) >= cap:
            continue
        span = (end_h - start_h) * 60
        step = span // cap if cap else span
        for i in range(cap):
            candidate = datetime.combine(day, time(start_h), tz) + timedelta(minutes=step * i)
            cand_utc = candidate.astimezone(UTC)
            if cand_utc < earliest:
                continue
            if any(abs((_utc(t) - cand_utc).total_seconds()) < 60 for t in taken):
                continue
            return cand_utc.replace(second=0, microsecond=0)
    raise PublishBlocked("No free publishing slot in the next 60 days; adjust the publishing window or cap.")


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def uploads_today(db: Session, owner_id: int, tz: ZoneInfo) -> int:
    start = datetime.combine(datetime.now(tz).date(), time(0), tz).astimezone(UTC)
    return db.scalar(select(func.count(PublishedVideo.id)).join(PublishingJob).where(
        PublishedVideo.owner_id == owner_id, PublishedVideo.created_at >= start,
        PublishingJob.is_test_upload.is_(False))) or 0


def create_publishing_job(db: Session, project: VideoProject, app_settings: AppSettings,
                          req: PublishRequest) -> PublishingJob:
    if project.status not in (ProjectStatus.READY, ProjectStatus.SCHEDULED, ProjectStatus.PUBLISHED):
        raise InvalidStateError("Only rendered, validated (READY) videos can be uploaded")
    if not project.validation.get("passed"):
        raise InvalidStateError("Video has not passed technical validation")
    if app_settings.paused:
        raise PublishBlocked("Automation is paused. Resume it before uploading.")
    existing = db.scalars(select(PublishingJob).where(PublishingJob.project_id == project.id,
                                                      PublishingJob.is_test_upload.is_(req.is_test_upload),
                                                      PublishingJob.status.in_(ACTIVE_STATUSES))).first()
    if existing:
        raise ConflictError(f"This video already has an active {'test ' if req.is_test_upload else ''}upload "
                            f"(publishing job #{existing.id}, {existing.status.value}).",
                            details={"publishing_job_id": existing.id})
    if not req.is_test_upload and not app_settings.dry_run and app_settings.private_test_passed_at is None:
        raise PublishBlocked("Complete a successful private test upload before scheduling or publishing.")
    publish_at = req.publish_at
    if publish_at is not None:
        publish_at = _utc(publish_at)
        if publish_at < datetime.now(UTC) + timedelta(minutes=15):
            raise AppError("publish_at must be at least 15 minutes in the future")
    script: RhymeScript | None = project.script
    seo = (script.seo if script else {}) or {}
    title = (req.title or seo.get("title") or project.title)[:100]
    description = req.description or seo.get("description") or ""
    hashtags = seo.get("hashtags", [])
    if hashtags and not any(h in description for h in hashtags):
        description = f"{description}\n\n{' '.join(hashtags)}"
    tags = req.tags if req.tags is not None else [k for k in seo.get("keywords", [])][:15]
    errors = validate_metadata(title, description, tags)
    if errors:
        raise AppError("Invalid upload metadata: " + "; ".join(errors), details={"errors": errors})
    previous = db.scalar(select(func.count(PublishingJob.id)).where(PublishingJob.project_id == project.id)) or 0
    privacy = "private" if (req.is_test_upload or publish_at) else req.privacy_status
    pj = PublishingJob(
        owner_id=project.owner_id, project_id=project.id, status=PublishStatus.QUEUED, privacy_status=privacy,
        publish_at=publish_at, title=title, description=description, tags=tags,
        category_id=app_settings.youtube_category_id,
        default_language=(script.language.value if script else app_settings.default_language.value),
        made_for_kids=app_settings.made_for_kids_default if req.made_for_kids is None else req.made_for_kids,
        is_test_upload=req.is_test_upload, dry_run=app_settings.dry_run,
        idempotency_key=f"project:{project.id}:{'test' if req.is_test_upload else 'publish'}:{previous + 1}",
    )
    channel = active_channel(db, project.owner_id)
    pj.channel_id = channel.id if channel else None
    if not pj.dry_run and channel is None:
        raise ConfigurationError("Connect a YouTube channel first (Settings → YouTube).")
    db.add(pj)
    db.flush()
    job = jobs.enqueue(db, project.owner_id, JobKind.UPLOAD, {"publishing_job_id": pj.id}, project_id=project.id,
                       dedupe_key=f"upload:{pj.idempotency_key}")
    pj.job_id = job.id
    audit(db, project.owner_id, "publish.queued", "publishing_job", pj.id, project_id=project.id,
          test=req.is_test_upload, dry_run=pj.dry_run, publish_at=str(publish_at))
    return pj


def apply_auto_publish_policy(db: Session, project: VideoProject, app_settings: AppSettings) -> PublishingJob | None:
    """Called when a project becomes READY. Only acts when the owner explicitly enabled auto-publishing."""
    if not (app_settings.automation_enabled and app_settings.auto_publish_enabled) or app_settings.paused:
        return None
    if not app_settings.dry_run and app_settings.private_test_passed_at is None:
        return None
    slot = next_publish_slot(db, app_settings)
    return create_publishing_job(db, project, app_settings, PublishRequest(publish_at=slot))


class PublishingService:
    def __init__(self, db: Session, *, transport=None, uploader_factory=None):
        self.db = db
        self._transport = transport
        self._uploader_factory = uploader_factory or (lambda token: ResumableUploader(token, transport=transport))

    def execute(self, pj: PublishingJob, app_settings: AppSettings, progress=None) -> PublishingJob:
        project = self.db.get(VideoProject, pj.project_id)
        if pj.status in (PublishStatus.SCHEDULED, PublishStatus.PUBLISHED, PublishStatus.UPLOADED_PRIVATE,
                         PublishStatus.DRY_RUN):
            return pj  # idempotent: already done
        if pj.published_video is not None:
            return pj
        if app_settings.paused:
            raise PublishBlocked("Automation is paused")
        video = safe_path(project.output_path) if project and project.output_path else None
        if not video or not video.exists():
            raise InvalidStateError("Rendered video file is missing; re-render the project")
        resource = build_video_resource(
            title=pj.title, description=pj.description, tags=pj.tags, category_id=pj.category_id,
            language=pj.default_language, privacy_status=pj.privacy_status,
            publish_at=pj.publish_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if pj.publish_at else None,
            made_for_kids=pj.made_for_kids,
        )
        if pj.dry_run:
            pj.status = PublishStatus.DRY_RUN
            pj.last_error = None
            pj.upload_progress = 0.0
            audit(self.db, pj.owner_id, "publish.dry_run", "publishing_job", pj.id, request=str(resource)[:2000])
            if pj.is_test_upload:
                pass  # a dry run never counts as a successful private test upload
            return pj
        tz = _tz(app_settings)
        if uploads_today(self.db, pj.owner_id, tz) >= max(app_settings.max_uploads_per_day, 1) \
                and not pj.is_test_upload:
            raise DailyLimitReached(next_local_midnight(tz))
        channel = active_channel(self.db, pj.owner_id)
        if channel is None:
            raise ConfigurationError("No connected YouTube channel")
        if project.status == ProjectStatus.READY and not pj.is_test_upload:
            transition(project, ProjectStatus.UPLOADING)
        pj.status = PublishStatus.UPLOADING
        pj.attempts += 1
        self.db.commit()

        token = get_access_token(self.db, channel, transport=self._transport)
        uploader = self._uploader_factory(token)
        try:
            resume = bool(pj.resumable_session_uri)
            if not resume:
                pj.resumable_session_uri = uploader.start_session(resource, video.stat().st_size)
                self.db.commit()  # persist before sending bytes so a crash resumes instead of duplicating

            def _progress(frac: float) -> None:
                pj.upload_progress = round(frac, 3)
                if progress:
                    progress(frac)

            try:
                result = uploader.upload(video, pj.resumable_session_uri, _progress, resume=resume)
            except YouTubeAPIError as exc:
                if exc.reason == "sessionExpired":
                    pj.resumable_session_uri = None
                raise
            thumb_warning = None
            if project.thumbnail_path:
                try:
                    uploader.set_thumbnail(result["id"], safe_path(project.thumbnail_path))
                except (YouTubeAPIError, OSError) as exc:
                    thumb_warning = f"Custom thumbnail not set: {exc}"
        finally:
            uploader.close()
        return self._record(pj, project, app_settings, result, thumb_warning)

    def _record(self, pj: PublishingJob, project: VideoProject, app_settings: AppSettings, result: dict,
                thumb_warning: str | None) -> PublishingJob:
        status = result.get("status", {})
        api_privacy = status.get("privacyStatus", pj.privacy_status)
        script = project.script
        pv = PublishedVideo(
            owner_id=pj.owner_id, publishing_job_id=pj.id, project_id=project.id, youtube_video_id=result["id"],
            channel_id=result.get("snippet", {}).get("channelId", ""), privacy_status=api_privacy,
            publish_at=_parse_dt(status.get("publishAt")), upload_status=status.get("uploadStatus", "uploaded"),
            language=script.language.value if script else "", topic=script.topic if script else "",
            video_format=project.video_format.value, duration_seconds=project.duration_seconds, title=pj.title,
            api_response={"id": result["id"], "status": status, "snippet": {
                k: result.get("snippet", {}).get(k) for k in ("title", "channelId", "publishedAt")}},
        )
        pj.published_video = pv
        pj.upload_progress = 1.0
        pj.last_error = thumb_warning
        pj.resumable_session_uri = None
        # Only claim a state YouTube actually confirmed.
        if status.get("publishAt"):
            pj.status = PublishStatus.SCHEDULED
        elif api_privacy == "public":
            pj.status = PublishStatus.PUBLISHED
        else:
            pj.status = PublishStatus.UPLOADED_PRIVATE
        if pj.is_test_upload:
            app_settings.private_test_passed_at = datetime.now(UTC)
        elif project.status == ProjectStatus.UPLOADING:
            transition(project, ProjectStatus.SCHEDULED if pj.status == PublishStatus.SCHEDULED else
                       ProjectStatus.PUBLISHED if pj.status == PublishStatus.PUBLISHED else ProjectStatus.READY,
                       f"YouTube video {result['id']} ({api_privacy})")
        audit(self.db, pj.owner_id, "publish.uploaded", "published_video", result["id"], privacy=api_privacy,
              publish_at=status.get("publishAt"), test=pj.is_test_upload)
        self.db.flush()
        return pj


class DailyLimitReached(Exception):
    def __init__(self, retry_at: datetime):
        super().__init__("Daily upload limit reached")
        self.retry_at = retry_at


def next_local_midnight(tz: ZoneInfo) -> datetime:
    tomorrow: date = datetime.now(tz).date() + timedelta(days=1)
    return datetime.combine(tomorrow, time(0, 5), tz).astimezone(UTC)


def next_quota_reset() -> datetime:
    return next_local_midnight(PACIFIC)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def reschedule(db: Session, pj: PublishingJob, publish_at: datetime) -> PublishingJob:
    if pj.status != PublishStatus.QUEUED:
        raise InvalidStateError("Only queued (not yet uploaded) items can be rescheduled here. Videos already on "
                                "YouTube must be rescheduled in YouTube Studio.")
    publish_at = _utc(publish_at)
    if publish_at < datetime.now(UTC) + timedelta(minutes=15):
        raise AppError("publish_at must be at least 15 minutes in the future")
    pj.publish_at = publish_at
    pj.privacy_status = "private"
    db.flush()
    return pj


def cancel_publishing(db: Session, pj: PublishingJob) -> PublishingJob:
    if pj.status not in (PublishStatus.QUEUED, PublishStatus.FAILED):
        raise InvalidStateError("Only queued or failed uploads can be cancelled")
    pj.status = PublishStatus.CANCELLED
    if pj.job_id:
        from app.models import Job
        from app.models.enums import JobStatus

        job = db.get(Job, pj.job_id)
        if job and job.status in (JobStatus.QUEUED, JobStatus.FAILED):
            jobs.mark_cancelled(job)
    db.flush()
    return pj


def media_file(project: VideoProject) -> Path | None:
    return safe_path(project.output_path) if project.output_path else None

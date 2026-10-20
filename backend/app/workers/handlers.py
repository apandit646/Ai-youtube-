"""Job handlers executed by the worker. Each step is recorded on the Job with timestamps and errors."""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import ContentIdea, Job, PublishingJob, ResearchQuery, RhymeScript, VideoProject
from app.models.enums import JobKind, Language, ProjectStatus, PublishStatus, ResearchType, VideoFormat
from app.services import jobs
from app.services.analytics.service import AnalyticsCollector, generate_recommendations
from app.services.audit import audit
from app.services.content.service import ContentService, GenerationRequest
from app.services.llm.base import LLMUnavailableError
from app.services.llm.router import LLMRouter
from app.services.media.pipeline import CancelledError, MediaPipeline, Providers
from app.services.projects import create_project
from app.services.publishing import PublishingService, apply_auto_publish_policy
from app.services.research.service import ResearchService
from app.services.settings_service import get_app_settings
from app.services.workflow import fail_project, transition
from app.services.youtube.oauth import active_channel, get_access_token

log = logging.getLogger(__name__)

THEME_ROTATION = ["animals", "numbers", "colors", "shapes", "bedtime", "alphabet", "kindness", "nature"]


@dataclass
class Context:
    db: Session
    job: Job
    providers: Providers | None = None
    transport: object = None  # httpx transport override (tests)
    uploader_factory: Callable | None = None
    yt_factory: Callable | None = None

    def cancelled(self) -> bool:
        self.db.refresh(self.job, attribute_names=["cancel_requested"])
        return self.job.cancel_requested

    def step(self, name: str) -> None:
        if self.cancelled():
            raise CancelledError("Cancelled by user")
        jobs.step_start(self.job, name)
        self.db.commit()

    def done(self, **extra) -> None:
        jobs.step_finish(self.job, **extra)
        self.db.commit()

    def progress(self, _step: str, frac: float) -> None:
        self.job.progress = round(frac, 3)
        self.db.commit()


def _router(ctx: Context) -> LLMRouter:
    app_settings = get_app_settings(ctx.db, ctx.job.owner_id)
    return LLMRouter.from_settings(app_settings, transport=ctx.transport)


def _access_token(ctx: Context) -> str | None:
    channel = active_channel(ctx.db, ctx.job.owner_id)
    if channel is None:
        return None
    try:
        return get_access_token(ctx.db, channel, transport=ctx.transport)
    except Exception as exc:  # noqa: BLE001 - research can fall back to the API key
        log.warning("Could not refresh channel token: %s", exc)
        return None


def handle_research(ctx: Context) -> dict:
    query = ctx.db.get(ResearchQuery, ctx.job.payload["query_id"])
    ctx.step("RESEARCHING")
    try:
        report = ResearchService(ctx.db, ctx.job.owner_id, _router(ctx), yt_factory=ctx.yt_factory).run(
            query, access_token=_access_token(ctx))
    except Exception as exc:
        query.status, query.error = jobs.JobStatus.FAILED, str(exc)[:2000]
        ctx.db.commit()
        raise
    ctx.done(videos=query.result_count, quota_units=query.quota_units_used)
    return {"query_id": query.id, "trend_report_id": report.id, "videos": query.result_count,
            "ai_summary": bool(report.ai_summary), "ai_error": report.error}


def handle_generate(ctx: Context) -> dict:
    app_settings = get_app_settings(ctx.db, ctx.job.owner_id)
    mode = ctx.job.payload.get("mode", "script")
    service = ContentService(ctx.db, ctx.job.owner_id, _router(ctx), app_settings)
    if mode == "ideas":
        ctx.step("IDEAS")
        p = ctx.job.payload
        ideas = service.generate_ideas(count=int(p.get("count", 5)), language=Language(p["language"]),
                                       video_format=VideoFormat(p["video_format"]),
                                       trend_report_id=p.get("trend_report_id"))
        ctx.done(created=len(ideas))
        return {"idea_ids": [i.id for i in ideas]}
    if mode == "regenerate":
        ctx.step("REGENERATING")
        script = ctx.db.get(RhymeScript, ctx.job.payload["script_id"])
        service.regenerate_section(script, ctx.job.payload["section"], ctx.job.payload.get("instructions", ""))
        ctx.done(section=ctx.job.payload["section"])
        return {"script_id": script.id, "section": ctx.job.payload["section"],
                "originality_passed": script.originality_report.get("passed")}
    req = GenerationRequest.model_validate(ctx.job.payload["request"])
    project = ctx.db.get(VideoProject, ctx.job.project_id) if ctx.job.project_id else None
    if project and project.status != ProjectStatus.SCRIPTING:
        transition(project, ProjectStatus.SCRIPTING)
    ctx.step("SCRIPTING")
    script = service.generate_script(req)
    ctx.done(provider=script.provider, fallback=script.is_fallback)
    result = {"script_id": script.id, "provider": script.provider, "is_fallback": script.is_fallback}
    if project:
        project.script_id = script.id
        project.title = script.title
        transition(project, ProjectStatus.PENDING, "script ready")
        if ctx.job.payload.get("auto_render"):
            result.update(_run_media(ctx, project, app_settings))
    return result


def _run_media(ctx: Context, project: VideoProject, app_settings) -> dict:
    script = ctx.db.get(RhymeScript, project.script_id) if project.script_id else None
    if script is None:
        raise PermanentJobError("Project has no script; generate one in the Content Studio first")
    if project.status in (ProjectStatus.GENERATING_MEDIA, ProjectStatus.RENDERING, ProjectStatus.VALIDATING):
        # Re-entry after a retry or worker crash: media generation restarts cleanly from scratch.
        project.status = ProjectStatus.PENDING
    pipeline = MediaPipeline(ctx.db, ctx.providers, progress=ctx.progress, is_cancelled=ctx.cancelled)
    transition(project, ProjectStatus.GENERATING_MEDIA)
    ctx.step("GENERATING_MEDIA")
    media = pipeline.generate_media(project, script)
    ctx.done(seconds=round(media["total_seconds"], 2))
    transition(project, ProjectStatus.RENDERING)
    ctx.step("RENDERING")
    video = pipeline.render(project, media, narration_volume=app_settings.narration_volume,
                            music_volume=app_settings.music_volume)
    ctx.done()
    transition(project, ProjectStatus.VALIDATING)
    ctx.step("VALIDATING")
    validation = pipeline.validate(project, video, media["total_seconds"])
    if not validation["passed"]:
        failed = [c for c in validation["checks"] if not c["passed"]]
        ctx.done(status="failed", error="validation failed")
        raise PermanentJobError("Technical validation failed: " + "; ".join(f"{c['name']}: {c['detail']}"
                                                                             for c in failed))
    ctx.done()
    transition(project, ProjectStatus.READY, "validated")
    ctx.db.commit()
    publishing = None
    ctx.step("PUBLISH_POLICY")
    try:
        pj = apply_auto_publish_policy(ctx.db, project, app_settings)
    except AppError as exc:
        # The video is valid and stays READY; the owner can publish it manually.
        ctx.db.rollback()
        ctx.done(status="skipped", error=exc.message)
        publishing = {"error": exc.message}
    else:
        if pj:
            publishing = {"publishing_job_id": pj.id,
                          "publish_at": pj.publish_at.isoformat() if pj.publish_at else None}
        ctx.done(auto_publish=bool(pj))
    return {"project_id": project.id, "video": project.output_path, "duration": project.duration_seconds,
            "publishing": publishing}


def handle_render(ctx: Context) -> dict:
    project = ctx.db.get(VideoProject, ctx.job.payload["project_id"])
    app_settings = get_app_settings(ctx.db, ctx.job.owner_id)
    return _run_media(ctx, project, app_settings)


def handle_upload(ctx: Context) -> dict:
    pj = ctx.db.get(PublishingJob, ctx.job.payload["publishing_job_id"])
    if pj.status == PublishStatus.CANCELLED:
        return {"skipped": "cancelled"}
    app_settings = get_app_settings(ctx.db, ctx.job.owner_id)
    ctx.step("UPLOADING")
    svc = PublishingService(ctx.db, transport=ctx.transport, uploader_factory=ctx.uploader_factory)
    pj = svc.execute(pj, app_settings, progress=lambda f: ctx.progress("UPLOADING", f))
    ctx.done(status=pj.status.value.lower() if pj.status != PublishStatus.UPLOADING else "succeeded")
    pv = pj.published_video
    return {"publishing_job_id": pj.id, "status": pj.status.value,
            "youtube_video_id": pv.youtube_video_id if pv else None, "dry_run": pj.dry_run,
            "warning": pj.last_error}


def handle_analytics(ctx: Context) -> dict:
    channel = active_channel(ctx.db, ctx.job.owner_id)
    if channel is None:
        raise PermanentJobError("No connected YouTube channel; analytics require OAuth authorisation.")
    ctx.step("COLLECTING_ANALYTICS")
    token = get_access_token(ctx.db, channel, transport=ctx.transport)
    collector = AnalyticsCollector(ctx.db, ctx.job.owner_id, token, transport=ctx.transport)
    try:
        summary = collector.collect(days=int(ctx.job.payload.get("days", 28)))
    finally:
        collector.close()
    ctx.done(errors=len(summary["errors"]))
    if ctx.job.payload.get("recommend", True):
        ctx.step("RECOMMENDING")
        recs = generate_recommendations(ctx.db, ctx.job.owner_id, _router(ctx))
        ctx.done(created=len(recs))
        summary["recommendations"] = len(recs)
    return summary


def handle_recommend(ctx: Context) -> dict:
    ctx.step("RECOMMENDING")
    recs = generate_recommendations(ctx.db, ctx.job.owner_id, _router(ctx))
    ctx.done(created=len(recs))
    return {"recommendations": len(recs)}


def handle_pipeline(ctx: Context) -> dict:
    """Full automation: research → ideas → script → media → render → validate → ready → publish policy."""
    db, owner = ctx.db, ctx.job.owner_id
    app_settings = get_app_settings(db, owner)
    payload = ctx.job.payload
    language = Language(payload.get("language") or app_settings.default_language.value)
    fmt = VideoFormat(payload.get("video_format") or app_settings.default_format.value)
    project = db.get(VideoProject, ctx.job.project_id) if ctx.job.project_id else None
    if project is None:
        project = create_project(db, owner, app_settings, script=None, video_format=fmt,
                                 title="Automated rhyme (in progress)")
        ctx.job.project_id = project.id
        db.commit()
    result: dict = {"project_id": project.id}
    router = _router(ctx)

    # 1-3: research + snapshots
    if project.status == ProjectStatus.PENDING and project.script_id is None:
        transition(project, ProjectStatus.RESEARCHING)
        ctx.step("RESEARCHING")
        topic_query = payload.get("research_query") or (
            "hindi balgeet nursery rhymes" if language == Language.HINDI else "nursery rhymes for kids")
        try:
            q = ResearchQuery(owner_id=owner, query_type=ResearchType.TOPIC, query_text=topic_query,
                              filters={"max_results": 25, "video_format": fmt.value})
            db.add(q)
            db.flush()
            report = ResearchService(db, owner, router, yt_factory=ctx.yt_factory).run(
                q, access_token=_access_token(ctx))
            result["trend_report_id"] = report.id
            ctx.done(videos=q.result_count)
        except Exception as exc:  # noqa: BLE001 - research is advisory; continue without it
            db.rollback()  # discard partial snapshots; committed step/transition records remain
            ctx.done(status="skipped", error=f"Research unavailable: {str(exc)[:300]}")
            result["research_error"] = str(exc)[:300]

    # 4-5: candidate topic + validated original script
    if project.script_id is None:
        transition(project, ProjectStatus.SCRIPTING)
        ctx.step("SCRIPTING")
        idea = None
        if router.any_configured:
            try:
                ideas = ContentService(db, owner, router, app_settings).generate_ideas(
                    count=3, language=language, video_format=fmt)
                idea = ideas[0] if ideas else None
            except LLMUnavailableError as exc:
                result["ideas_error"] = str(exc)
        if idea is None:
            used = db.scalars(select(RhymeScript.theme).where(RhymeScript.owner_id == owner)).all()
            theme = min(THEME_ROTATION, key=lambda t: list(used).count(t))
            idea = ContentIdea(owner_id=owner, topic=f"{theme.title()} sing-along", theme=theme, language=language,
                               video_format=fmt, objective=f"Learn {theme} through song",
                               rationale="Theme rotation (no AI idea available)", provider="rotation")
            db.add(idea)
            db.flush()
        req = GenerationRequest(topic=idea.topic, theme=idea.theme, language=idea.language, video_format=fmt,
                                target_age=idea.target_age, idea_id=idea.id,
                                duration_seconds=45 if fmt == VideoFormat.SHORT else 180)
        script = ContentService(db, owner, router, app_settings).generate_script(req)
        if script.safety_flags:
            ctx.done(status="failed", error=f"Safety flags: {script.safety_flags}")
            raise PermanentJobError(f"Script #{script.id} was flagged for review: {script.safety_flags}. "
                                    "Review it in the Content Studio.")
        project.script_id, project.title = script.id, script.title
        ctx.done(script_id=script.id, provider=script.provider, fallback=script.is_fallback)
        result["script_id"] = script.id

    # 6-13: media, render, validation, policy
    if project.status not in (ProjectStatus.READY, ProjectStatus.UPLOADING, ProjectStatus.SCHEDULED,
                              ProjectStatus.PUBLISHED):
        result.update(_run_media(ctx, project, app_settings))
    return result


class PermanentJobError(Exception):
    """A failure that retrying will not fix."""


HANDLERS: dict[JobKind, Callable[[Context], dict]] = {
    JobKind.RESEARCH: handle_research,
    JobKind.GENERATE_CONTENT: handle_generate,
    JobKind.RENDER: handle_render,
    JobKind.UPLOAD: handle_upload,
    JobKind.ANALYTICS: handle_analytics,
    JobKind.RECOMMEND: handle_recommend,
    JobKind.PIPELINE: handle_pipeline,
}


def run_job(db: Session, job: Job, **ctx_kwargs) -> Job:
    """Execute a claimed job with uniform error handling, retry policy and project-state bookkeeping."""
    from app.core.errors import AppError, ConfigurationError
    from app.services.media.ffmpeg import MediaError
    from app.services.publishing import DailyLimitReached, PublishBlocked, next_quota_reset
    from app.services.youtube.client import YouTubeAPIError, YouTubeAuthError, YouTubeQuotaError

    ctx = Context(db=db, job=job, **ctx_kwargs)
    handler = HANDLERS[job.kind]
    log.info("job started", extra={"job_id": job.id, "step": job.kind.value})
    try:
        result = handler(ctx)
        job = ctx.job
        jobs.succeed(job, result)
        db.commit()
        return job
    except CancelledError:
        db.rollback()
        job = db.get(Job, job.id)
        jobs.step_finish(job, status="cancelled")
        jobs.mark_cancelled(job)
        _project_terminal(db, job, cancelled=True, error="Cancelled by user")
        audit(db, job.owner_id, "job.cancelled", "job", job.id)
        db.commit()
        return job
    except Exception as exc:  # noqa: BLE001 - classify and persist every failure
        db.rollback()
        job = db.get(Job, job.id)
        retry_at = None
        if isinstance(exc, DailyLimitReached):
            job.attempts = max(job.attempts - 1, 0)  # deferral isn't a failed attempt
            retryable, retry_at, message = True, exc.retry_at, "Daily upload limit reached; deferred"
        elif isinstance(exc, YouTubeQuotaError):
            retryable = True
            retry_at = None if exc.retryable else next_quota_reset()
            message = f"YouTube quota: {exc}"
        elif isinstance(exc, YouTubeAuthError | ConfigurationError | PublishBlocked | PermanentJobError):
            retryable, message = False, str(exc)
        elif isinstance(exc, YouTubeAPIError):
            retryable, message = exc.retryable, str(exc)
        elif isinstance(exc, LLMUnavailableError):
            retryable, message = True, f"{exc} {exc.attempts}"
        elif isinstance(exc, MediaError | AppError):
            retryable, message = False, getattr(exc, "message", str(exc))
        else:
            log.exception("Unexpected job failure", extra={"job_id": job.id})
            retryable, message = True, f"{type(exc).__name__}: {exc}"
        jobs.step_finish(job, status="failed", error=message[:1000])
        requeued = jobs.fail(job, message, retryable=retryable, retry_at=retry_at)
        if job.kind == JobKind.UPLOAD:
            pj = db.get(PublishingJob, job.payload.get("publishing_job_id"))
            if pj:
                pj.last_error = message[:2000]
                pj.status = PublishStatus.QUEUED if requeued else PublishStatus.FAILED
        if not requeued:
            _project_terminal(db, job, cancelled=False, error=message)
        log.warning("job failed (requeued=%s): %s", requeued, message[:300], extra={"job_id": job.id})
        db.commit()
        return job


def _project_terminal(db: Session, job: Job, *, cancelled: bool, error: str) -> None:
    if not job.project_id:
        return
    project = db.get(VideoProject, job.project_id)
    if project is None:
        return
    if job.kind == JobKind.UPLOAD and project.status != ProjectStatus.UPLOADING:
        return  # failed test uploads don't change the project state
    if project.status in (ProjectStatus.PUBLISHED, ProjectStatus.SCHEDULED, ProjectStatus.CANCELLED):
        return
    if cancelled:
        transition(project, ProjectStatus.CANCELLED, error)
    elif project.status != ProjectStatus.FAILED:
        fail_project(project, error)


def worker_settings_snapshot() -> dict:
    s = get_settings()
    return {"poll_interval": s.worker_poll_interval_seconds, "concurrency": s.max_concurrent_jobs,
            "started_at": datetime.now(UTC).isoformat()}

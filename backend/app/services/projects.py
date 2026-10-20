from sqlalchemy.orm import Session

from app.core.errors import InvalidStateError
from app.models import AppSettings, RhymeScript, VideoProject
from app.models.enums import JobKind, ProjectStatus, VideoFormat
from app.services import jobs
from app.services.media.pipeline import parse_resolution
from app.services.workflow import retry_target, transition


def dimensions_for(app_settings: AppSettings, video_format: VideoFormat) -> tuple[int, int]:
    res = app_settings.shorts_resolution if video_format == VideoFormat.SHORT else app_settings.long_resolution
    w, h = parse_resolution(res)
    # Enforce orientation regardless of user typo: Shorts vertical, long-form horizontal.
    if video_format == VideoFormat.SHORT and w > h or video_format == VideoFormat.LONG and h > w:
        w, h = h, w
    return w, h


def create_project(db: Session, owner_id: int, app_settings: AppSettings, *, script: RhymeScript | None,
                   video_format: VideoFormat, title: str | None = None) -> VideoProject:
    w, h = dimensions_for(app_settings, video_format)
    project = VideoProject(owner_id=owner_id, script_id=script.id if script else None,
                           title=(title or (script.title if script else "Untitled rhyme"))[:255],
                           video_format=video_format, width=w, height=h, fps=app_settings.fps,
                           status=ProjectStatus.PENDING, status_history=[], validation={}, quality_warnings=[])
    db.add(project)
    db.flush()
    return project


def enqueue_render(db: Session, project: VideoProject) -> "jobs.Job":
    if project.script_id is None:
        raise InvalidStateError("Project has no script to render")
    if project.status in (ProjectStatus.GENERATING_MEDIA, ProjectStatus.RENDERING, ProjectStatus.VALIDATING,
                          ProjectStatus.UPLOADING):
        raise InvalidStateError(f"Project is busy ({project.status.value})")
    if project.status in (ProjectStatus.SCHEDULED, ProjectStatus.PUBLISHED):
        raise InvalidStateError("Project has already been uploaded; duplicate it to make a new version")
    return jobs.enqueue(db, project.owner_id, JobKind.RENDER, {"project_id": project.id}, project_id=project.id)


def retry_project(db: Session, project: VideoProject) -> "jobs.Job | None":
    if project.status not in (ProjectStatus.FAILED, ProjectStatus.CANCELLED):
        raise InvalidStateError("Only failed or cancelled projects can be retried")
    target = retry_target(project)
    if target == ProjectStatus.READY:
        transition(project, ProjectStatus.READY, "retry: back to ready for upload")
        return None
    if target == ProjectStatus.SCRIPTING and project.script_id is None:
        raise InvalidStateError("This project has no script; generate a new script in the Content Studio")
    return jobs.enqueue(db, project.owner_id, JobKind.RENDER, {"project_id": project.id, "retry": True},
                        project_id=project.id)

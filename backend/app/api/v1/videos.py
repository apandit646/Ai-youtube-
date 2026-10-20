from datetime import UTC, datetime, timedelta

import jwt
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, Paging, UserSettings, owned
from app.core.config import get_settings
from app.core.errors import InvalidStateError
from app.models import PublishingJob, RhymeScript, VideoProject
from app.models.enums import AssetKind, ProjectStatus, PublishStatus, VideoFormat
from app.schemas.api import (
    JobOut,
    Page,
    ProjectCreate,
    ProjectDetail,
    ProjectOut,
    PublishingJobOut,
    ScheduleRequest,
    UploadRequest,
)
from app.services.audit import audit
from app.services.media.storage import delete_project_media, safe_path
from app.services.projects import create_project, enqueue_render, retry_project
from app.services.publishing import PublishRequest, create_publishing_job, next_publish_slot

router = APIRouter(prefix="/videos", tags=["videos"])

MEDIA_TOKEN_MINUTES = 60


def pj_out(pj: PublishingJob) -> PublishingJobOut:
    out = PublishingJobOut.model_validate(pj)
    out.youtube_video_id = pj.published_video.youtube_video_id if pj.published_video else None
    return out


def project_out(p: VideoProject, cls=ProjectOut):
    out = cls.model_validate(p)
    out.has_video = bool(p.output_path) and p.status not in (ProjectStatus.GENERATING_MEDIA, ProjectStatus.RENDERING)
    out.has_thumbnail = bool(p.thumbnail_path)
    out.language = p.script.language.value if p.script else None
    active = [j for j in p.publishing_jobs if not j.is_test_upload and j.status != PublishStatus.CANCELLED]
    latest = max(active or p.publishing_jobs, key=lambda j: j.id, default=None)
    out.publication = pj_out(latest) if latest else None
    if cls is ProjectDetail:
        out.publishing_jobs = [pj_out(j) for j in sorted(p.publishing_jobs, key=lambda j: -j.id)]
    return out


@router.get("", response_model=Page[ProjectOut])
def list_projects(db: DB, user: CurrentUser, paging: Paging,
                  status_filter: ProjectStatus | None = Query(None, alias="status"),
                  video_format: VideoFormat | None = None) -> dict:
    base = select(VideoProject).where(VideoProject.owner_id == user.id)
    if status_filter:
        base = base.where(VideoProject.status == status_filter)
    if video_format:
        base = base.where(VideoProject.video_format == video_format)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    items = db.scalars(base.order_by(VideoProject.id.desc()).offset(paging.offset).limit(paging.page_size))
    return {"items": [project_out(p) for p in items], "total": total, "page": paging.page,
            "page_size": paging.page_size}


@router.post("", status_code=status.HTTP_201_CREATED)
def create(body: ProjectCreate, db: DB, user: CurrentUser, app_settings: UserSettings) -> dict:
    script = owned(db.get(RhymeScript, body.script_id), user, "Script")
    if not script.originality_report.get("passed"):
        raise InvalidStateError("Script failed originality/safety checks; edit or regenerate it first")
    project = create_project(db, user.id, app_settings, script=script,
                             video_format=body.video_format or script.video_format)
    job = enqueue_render(db, project) if body.render else None
    audit(db, user.id, "video.created", "project", project.id, script_id=script.id)
    db.commit()
    return {"project": project_out(project), "job": JobOut.model_validate(job) if job else None}


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: int, db: DB, user: CurrentUser):
    return project_out(owned(db.get(VideoProject, project_id), user, "Video"), ProjectDetail)


@router.post("/{project_id}/render", status_code=status.HTTP_202_ACCEPTED, response_model=JobOut)
def render(project_id: int, db: DB, user: CurrentUser):
    project = owned(db.get(VideoProject, project_id), user, "Video")
    job = enqueue_render(db, project)
    db.commit()
    return job


@router.post("/{project_id}/retry", status_code=status.HTTP_202_ACCEPTED)
def retry(project_id: int, db: DB, user: CurrentUser) -> dict:
    project = owned(db.get(VideoProject, project_id), user, "Video")
    job = retry_project(db, project)
    audit(db, user.id, "video.retry", "project", project.id)
    db.commit()
    return {"project": project_out(project), "job": JobOut.model_validate(job) if job else None}


@router.delete("/{project_id}/media")
def delete_media(project_id: int, db: DB, user: CurrentUser, confirm: bool = Query(False)) -> dict:
    project = owned(db.get(VideoProject, project_id), user, "Video")
    if not confirm:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pass confirm=true to delete local media files")
    if project.status in (ProjectStatus.GENERATING_MEDIA, ProjectStatus.RENDERING, ProjectStatus.VALIDATING,
                          ProjectStatus.UPLOADING):
        raise InvalidStateError("Cannot delete media while a job is using it")
    freed = delete_project_media(project.id)
    for a in list(project.assets):
        db.delete(a)
    project.output_path = project.thumbnail_path = project.subtitles_path = None
    project.validation = {}
    if project.status == ProjectStatus.READY:
        project.status = ProjectStatus.PENDING
        project.status_history = [*project.status_history, {"from": "READY", "to": "PENDING",
                                                           "at": datetime.now(UTC).isoformat(),
                                                           "note": "local media deleted"}]
    audit(db, user.id, "video.media_deleted", "project", project.id, bytes=freed)
    db.commit()
    return {"deleted_bytes": freed}


@router.get("/{project_id}/media-token")
def media_token(project_id: int, db: DB, user: CurrentUser) -> dict:
    """Short-lived token for <video>/<img> tags, which can't send Authorization headers."""
    owned(db.get(VideoProject, project_id), user, "Video")
    exp = datetime.now(UTC) + timedelta(minutes=MEDIA_TOKEN_MINUTES)
    token = jwt.encode({"pid": project_id, "uid": user.id, "typ": "media", "exp": exp}, get_settings().secret_key,
                       algorithm="HS256")
    return {"token": token, "expires_at": exp}


@router.get("/{project_id}/file/{kind}")
def media_file(project_id: int, kind: str, db: DB, token: str = Query(...), download: bool = False) -> FileResponse:
    try:
        claims = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired media token") from None
    if claims.get("typ") != "media" or claims.get("pid") != project_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Token not valid for this video")
    project = db.get(VideoProject, project_id)
    if project is None or project.owner_id != claims.get("uid"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    paths = {"video": (project.output_path, "video/mp4"), "thumbnail": (project.thumbnail_path, None),
             "subtitles": (project.subtitles_path, "application/x-subrip")}
    if kind.startswith("scene-"):
        idx = kind.removeprefix("scene-")
        asset = next((a for a in project.assets if a.kind == AssetKind.SCENE_IMAGE
                      and str(a.extra.get("scene_index")) == idx), None)
        paths[kind] = (asset.path if asset else None, "image/png")
    if kind not in paths or not paths[kind][0]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not available")
    rel, mime = paths[kind]
    path = safe_path(rel)
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File missing on disk")
    filename = f"rhymepilot-{project_id}-{kind}{path.suffix}"
    return FileResponse(path, media_type=mime or ("image/png" if path.suffix == ".png" else "image/jpeg"),
                        filename=filename if download else None)


@router.post("/{project_id}/upload", status_code=status.HTTP_202_ACCEPTED, response_model=PublishingJobOut)
def upload(project_id: int, body: UploadRequest, db: DB, user: CurrentUser, app_settings: UserSettings):
    project = owned(db.get(VideoProject, project_id), user, "Video")
    pj = create_publishing_job(db, project, app_settings, PublishRequest(
        is_test_upload=body.test, privacy_status=body.privacy_status, title=body.title, description=body.description,
        tags=body.tags, made_for_kids=body.made_for_kids))
    db.commit()
    return pj_out(pj)


@router.post("/{project_id}/schedule", status_code=status.HTTP_202_ACCEPTED, response_model=PublishingJobOut)
def schedule(project_id: int, body: ScheduleRequest, db: DB, user: CurrentUser, app_settings: UserSettings):
    project = owned(db.get(VideoProject, project_id), user, "Video")
    publish_at = body.publish_at or next_publish_slot(db, app_settings)
    pj = create_publishing_job(db, project, app_settings, PublishRequest(publish_at=publish_at,
                                                                         made_for_kids=body.made_for_kids))
    db.commit()
    return pj_out(pj)

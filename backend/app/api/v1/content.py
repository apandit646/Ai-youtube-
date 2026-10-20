from fastapi import APIRouter, Query, status
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.deps import DB, CurrentUser, Paging, UserSettings, owned
from app.core.errors import AppError, ConfigurationError, InvalidStateError
from app.models import ContentIdea, RhymeScript, StoryboardScene, VideoProject
from app.models.enums import JobKind, Language
from app.schemas.api import (
    GenerateRequest,
    IdeaOut,
    IdeasRequest,
    JobOut,
    Page,
    RegenerateRequest,
    ScriptOut,
    ScriptSummary,
    ScriptUpdate,
)
from app.services import jobs
from app.services.audit import audit
from app.services.content.schemas import SceneSpec, SEOMetadata
from app.services.content.service import ContentService
from app.services.llm.router import LLMRouter
from app.services.projects import create_project

router = APIRouter(prefix="/content", tags=["content"])


@router.post("/ideas", status_code=status.HTTP_202_ACCEPTED, response_model=JobOut)
def generate_ideas(body: IdeasRequest, db: DB, user: CurrentUser, app_settings: UserSettings):
    if not LLMRouter.from_settings(app_settings).any_configured:
        raise ConfigurationError("Idea generation needs at least one AI provider (Grok, ChatGPT or Gemini).")
    job = jobs.enqueue(db, user.id, JobKind.GENERATE_CONTENT, {"mode": "ideas", **body.model_dump(mode="json")})
    db.commit()
    return job


@router.get("/ideas", response_model=Page[IdeaOut])
def list_ideas(db: DB, user: CurrentUser, paging: Paging,
               status_filter: str | None = Query(None, alias="status", pattern="^(new|used|dismissed)$")) -> dict:
    base = select(ContentIdea).where(ContentIdea.owner_id == user.id)
    if status_filter:
        base = base.where(ContentIdea.status == status_filter)
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    items = db.scalars(base.order_by(ContentIdea.id.desc()).offset(paging.offset).limit(paging.page_size))
    return {"items": list(items), "total": total, "page": paging.page, "page_size": paging.page_size}


@router.post("/ideas/{idea_id}/dismiss", response_model=IdeaOut)
def dismiss_idea(idea_id: int, db: DB, user: CurrentUser) -> ContentIdea:
    idea = owned(db.get(ContentIdea, idea_id), user, "Idea")
    idea.status = "dismissed"
    db.commit()
    return idea


@router.post("/generate", status_code=status.HTTP_202_ACCEPTED)
def generate(body: GenerateRequest, db: DB, user: CurrentUser, app_settings: UserSettings) -> dict:
    if body.idea_id:
        owned(db.get(ContentIdea, body.idea_id), user, "Idea")
    if not body.allow_fallback and not LLMRouter.from_settings(app_settings).any_configured:
        raise ConfigurationError("No AI provider configured and fallback templates are disabled.")
    project = None
    if body.create_project or body.auto_render:
        project = create_project(db, user.id, app_settings, script=None, video_format=body.video_format,
                                 title=f"{body.topic} (scripting)")
    request = body.model_dump(mode="json", exclude={"create_project", "auto_render"})
    job = jobs.enqueue(db, user.id, JobKind.GENERATE_CONTENT,
                       {"mode": "script", "request": request, "auto_render": body.auto_render},
                       project_id=project.id if project else None)
    db.commit()
    return {"job": JobOut.model_validate(job), "project_id": project.id if project else None}


@router.get("", response_model=Page[ScriptSummary])
def list_scripts(db: DB, user: CurrentUser, paging: Paging, language: Language | None = None,
                 q: str | None = Query(None, max_length=100)) -> dict:
    base = select(RhymeScript).where(RhymeScript.owner_id == user.id)
    if language:
        base = base.where(RhymeScript.language == language)
    if q:
        base = base.where(RhymeScript.title.ilike(f"%{q}%") | RhymeScript.topic.ilike(f"%{q}%"))
    total = db.scalar(select(func.count()).select_from(base.subquery()))
    items = db.scalars(base.order_by(RhymeScript.id.desc()).offset(paging.offset).limit(paging.page_size))
    return {"items": list(items), "total": total, "page": paging.page, "page_size": paging.page_size}


@router.get("/{script_id}", response_model=ScriptOut)
def get_script(script_id: int, db: DB, user: CurrentUser) -> RhymeScript:
    return owned(db.get(RhymeScript, script_id), user, "Script")


@router.put("/{script_id}", response_model=ScriptOut)
def update_script(script_id: int, body: ScriptUpdate, db: DB, user: CurrentUser,
                  app_settings: UserSettings) -> RhymeScript:
    script = owned(db.get(RhymeScript, script_id), user, "Script")
    data = body.model_dump(exclude_unset=True)
    if "seo" in data:
        try:
            data["seo"] = SEOMetadata.model_validate(data["seo"]).model_dump()
        except ValidationError as exc:
            raise AppError("Invalid metadata", details={"errors": exc.errors(include_url=False)}) from None
    if "scenes" in data:
        script.scenes.clear()
        db.flush()
        new = []
        for i, sc in enumerate(body.scenes or []):
            spec = SceneSpec(description=sc.description, lyric_lines=sc.lyric_text.split("\n"),
                             duration_seconds=sc.duration_seconds, **{k: v for k, v in sc.visual.items()
                                                                      if k in ("background", "characters",
                                                                               "objects", "mood")})
            new.append(StoryboardScene(order_index=i, description=spec.description, lyric_text=sc.lyric_text,
                                       duration_seconds=spec.duration_seconds,
                                       visual={"background": spec.background, "characters": spec.characters,
                                               "objects": spec.objects, "mood": spec.mood}))
        script.scenes = new
        data.pop("scenes")
    for k, v in data.items():
        setattr(script, k, v)
    if {"lyrics", "title", "seo"} & set(data) or body.scenes is not None:
        try:
            ContentService(db, user.id, LLMRouter({}), app_settings).revalidate(script)
        except ValidationError as exc:
            raise AppError("Edited script is invalid", details={"errors": exc.errors(include_url=False)}) from None
        if body.approved is None:
            script.approved = False  # material edits require re-approval
    if body.approved and not script.originality_report.get("passed"):
        raise InvalidStateError("Cannot approve: originality/safety checks have not passed")
    audit(db, user.id, "content.updated", "script", script.id, fields=",".join(sorted(body.model_fields_set)))
    db.commit()
    db.refresh(script)
    return script


@router.post("/{script_id}/regenerate", status_code=status.HTTP_202_ACCEPTED, response_model=JobOut)
def regenerate(script_id: int, body: RegenerateRequest, db: DB, user: CurrentUser, app_settings: UserSettings):
    owned(db.get(RhymeScript, script_id), user, "Script")
    if not LLMRouter.from_settings(app_settings).any_configured:
        raise ConfigurationError("Regenerating a section needs an AI provider; edit the text manually instead.")
    job = jobs.enqueue(db, user.id, JobKind.GENERATE_CONTENT,
                       {"mode": "regenerate", "script_id": script_id, **body.model_dump()})
    db.commit()
    return job


@router.delete("/{script_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_script(script_id: int, db: DB, user: CurrentUser) -> None:
    script = owned(db.get(RhymeScript, script_id), user, "Script")
    if db.scalar(select(func.count(VideoProject.id)).where(VideoProject.script_id == script_id)):
        raise InvalidStateError("Script is used by a video project; delete the project's media first")
    db.delete(script)
    audit(db, user.id, "content.deleted", "script", script_id)
    db.commit()

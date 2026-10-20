"""Content planning and rhyme generation: AI-first with validation, cross-model review and labelled fallback."""

import json
import logging

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError, NotFoundError
from app.models import (
    AppSettings,
    CompetitorVideoSnapshot,
    ContentIdea,
    ResearchQuery,
    RhymeScript,
    StoryboardScene,
    TrendReport,
)
from app.models.enums import Language, VideoFormat
from app.services.content import prompts
from app.services.content.fallback import build_fallback_brief
from app.services.content.originality import check_brief, content_hash
from app.services.content.schemas import (
    ContentBrief,
    IdeaList,
    IdeaSpec,
    ReviewResult,
    SceneSpec,
    SectionRegeneration,
)
from app.services.llm.base import LLMUnavailableError
from app.services.llm.router import LLMRouter

log = logging.getLogger(__name__)


class GenerationRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=200)
    theme: str = "general"
    language: Language = Language.HINDI
    video_format: VideoFormat = VideoFormat.SHORT
    target_age: str = "2-5"
    duration_seconds: int = Field(default=45, ge=10, le=900)
    style: str = Field(default="", max_length=300)
    idea_id: int | None = None
    allow_fallback: bool = True
    preferred_provider: str | None = None


class OriginalityRejected(AppError):
    status_code = 422
    code = "originality_rejected"


def _previous_lyrics(db: Session, owner_id: int, limit: int = 200, exclude_id: int | None = None) -> list[str]:
    stmt = select(RhymeScript.lyrics).where(RhymeScript.owner_id == owner_id)
    if exclude_id is not None:
        stmt = stmt.where(RhymeScript.id != exclude_id)
    rows = db.scalars(stmt.order_by(RhymeScript.id.desc()).limit(limit))
    return list(rows)


def _competitor_texts(db: Session, owner_id: int, limit: int = 300) -> list[str]:
    rows = db.execute(
        select(CompetitorVideoSnapshot.title, CompetitorVideoSnapshot.description)
        .join(ResearchQuery).where(ResearchQuery.owner_id == owner_id)
        .order_by(CompetitorVideoSnapshot.id.desc()).limit(limit)
    )
    return [f"{t}\n{d[:1000]}" for t, d in rows]


def _trend_context(db: Session, owner_id: int) -> str:
    report = db.scalar(select(TrendReport).where(TrendReport.owner_id == owner_id)
                       .order_by(TrendReport.id.desc()).limit(1))
    if not report:
        return ""
    obs = report.observations or {}
    return json.dumps({"top_topics": obs.get("top_topics", [])[:10], "by_language": obs.get("by_language"),
                       "by_format": obs.get("by_format")}, ensure_ascii=False, default=str)[:2000]


class ContentService:
    def __init__(self, db: Session, owner_id: int, router: LLMRouter, app_settings: AppSettings | None = None):
        self.db = db
        self.owner_id = owner_id
        self.router = router
        self.app_settings = app_settings

    # ---- Ideas -------------------------------------------------------------------------------------------
    def generate_ideas(self, *, count: int, language: Language, video_format: VideoFormat,
                       trend_report_id: int | None = None) -> list[ContentIdea]:
        report = None
        if trend_report_id:
            report = self.db.get(TrendReport, trend_report_id)
            if not report or report.owner_id != self.owner_id:
                raise NotFoundError("Trend report not found")
        elif (report := self.db.scalar(select(TrendReport).where(TrendReport.owner_id == self.owner_id)
                                       .order_by(TrendReport.id.desc()).limit(1))):
            pass
        observations = report.observations if report else {"note": "no research data collected yet"}
        existing = list(self.db.scalars(select(RhymeScript.topic).where(RhymeScript.owner_id == self.owner_id)))
        result = self.router.generate(
            "ideas", prompts.SYSTEM_ANALYST,
            prompts.ideas_prompt(count=count, language=language.value, video_format=video_format.value,
                                 observations=observations, existing_topics=existing),
            IdeaList, temperature=0.9,
        )
        ideas = [self._store_idea(spec, report, result.provider) for spec in result.data.ideas[:count]]
        self.db.flush()
        return ideas

    def _store_idea(self, spec: IdeaSpec, report: TrendReport | None, provider: str) -> ContentIdea:
        idea = ContentIdea(owner_id=self.owner_id, trend_report_id=report.id if report else None, topic=spec.topic,
                           theme=spec.theme, language=Language(spec.language), video_format=VideoFormat(spec.format),
                           target_age=spec.target_age, objective=spec.objective, rationale=spec.rationale,
                           provider=provider)
        self.db.add(idea)
        return idea

    # ---- Brief / script ----------------------------------------------------------------------------------
    def generate_script(self, req: GenerationRequest) -> RhymeScript:
        previous = _previous_lyrics(self.db, self.owner_id)
        competitors = _competitor_texts(self.db, self.owner_id)
        avoid_titles = [t.split("\n", 1)[0] for t in competitors[:30]]
        user_prompt = prompts.brief_prompt(
            topic=req.topic, theme=req.theme, language=req.language.value, video_format=req.video_format.value,
            target_age=req.target_age, duration_seconds=req.duration_seconds, style=req.style,
            avoid_titles=avoid_titles, trend_context=_trend_context(self.db, self.owner_id),
        )
        brief: ContentBrief | None = None
        provider, model, is_fallback = "fallback-template", "", False
        attempts: list[dict] = []
        rejection: dict | None = None

        if self.router.any_configured:
            for _ in range(2):  # one retry if the originality gate rejects the first draft
                try:
                    result = self.router.generate("script", prompts.SYSTEM_CREATIVE, user_prompt, ContentBrief,
                                                  prefer=req.preferred_provider)
                except LLMUnavailableError as exc:
                    attempts.extend(exc.attempts)
                    break
                attempts.extend(result.attempts)
                report = check_brief(result.data, previous_lyrics=previous, competitor_texts=competitors)
                if report["passed"]:
                    brief, provider, model = result.data, result.provider, result.model
                    break
                rejection = report
                user_prompt += ("\n\nYour previous draft was rejected by the originality/safety gate: "
                                + "; ".join(c["detail"] for c in report["checks"] if not c["passed"])
                                + ". Write a completely different, original rhyme.")

        if brief is None:
            if not req.allow_fallback:
                if rejection:
                    raise OriginalityRejected("Generated content failed originality/safety checks",
                                              details={"report": rejection, "attempts": attempts})
                raise LLMUnavailableError("AI generation failed and fallback templates are disabled", attempts)
            brief = None
            for variant in range(6):
                candidate = build_fallback_brief(topic=req.topic, theme=req.theme, language=req.language.value,
                                                 video_format=req.video_format.value, target_age=req.target_age,
                                                 variant=variant + len(previous))
                if check_brief(candidate, previous_lyrics=previous, competitor_texts=competitors)["passed"]:
                    brief = candidate
                    break
            if brief is None:
                raise OriginalityRejected("Fallback templates for this topic are exhausted (too similar to existing "
                                          "scripts). Configure an AI provider or choose another theme.")
            is_fallback = True

        report = check_brief(brief, previous_lyrics=previous, competitor_texts=competitors)
        review = self._cross_review(brief, provider) if not is_fallback else None
        script = self._persist(brief, req, provider=provider, model=model, is_fallback=is_fallback,
                               prompt=user_prompt, report={**report, "attempts": attempts}, review=review)
        return script

    def _cross_review(self, brief: ContentBrief, generator: str) -> dict | None:
        if self.app_settings is not None and not self.app_settings.cross_model_review:
            return None
        if not self.router.order_for("review", exclude=generator):
            return {"skipped": True, "reason": "No second AI provider configured for an independent review"}
        try:
            res = self.router.generate("review", prompts.SYSTEM_REVIEWER,
                                       prompts.review_prompt(brief.model_dump_json()), ReviewResult,
                                       temperature=0.2, exclude=generator)
        except LLMUnavailableError as exc:
            return {"skipped": True, "reason": str(exc), "attempts": exc.attempts}
        return {**res.data.model_dump(), "provider": res.provider, "model": res.model}

    def _persist(self, brief: ContentBrief, req: GenerationRequest, *, provider: str, model: str,
                 is_fallback: bool, prompt: str, report: dict, review: dict | None) -> RhymeScript:
        flags = list(brief.safety_flags)
        if review and not review.get("skipped") and not review.get("approved", True):
            flags.append("cross_model_review_not_approved")
        script = RhymeScript(
            owner_id=self.owner_id, idea_id=req.idea_id, title=brief.title, language=Language(brief.language),
            topic=brief.topic, theme=brief.theme, target_age=brief.target_age_range, objective=brief.objective,
            story_concept=brief.story_concept, lyrics="\n".join(brief.lyrics),
            audio_instructions=brief.audio_instructions,
            suggested_duration_seconds=brief.suggested_duration_seconds,
            video_format=VideoFormat.SHORT if brief.aspect_ratio == "9:16" else VideoFormat.LONG,
            seo=brief.metadata.model_dump(), safety_flags=flags, originality_report=report, review=review,
            prompt=f"[{prompts.PROMPT_VERSION}]\n{prompt}", provider=provider, model=model,
            is_fallback=is_fallback, content_hash=content_hash(brief.lyrics),
        )
        script.scenes = [_scene_model(i, s) for i, s in enumerate(brief.storyboard)]
        self.db.add(script)
        if req.idea_id:
            idea = self.db.get(ContentIdea, req.idea_id)
            if idea and idea.owner_id == self.owner_id:
                idea.status = "used"
        self.db.flush()
        return script

    # ---- Editing -----------------------------------------------------------------------------------------
    def regenerate_section(self, script: RhymeScript, section: str, instructions: str = "") -> RhymeScript:
        if section not in ("lyrics", "storyboard", "metadata"):
            raise AppError("section must be one of lyrics, storyboard, metadata")
        brief_json = json.dumps(script_to_brief_dict(script), ensure_ascii=False)
        res = self.router.generate("metadata" if section == "metadata" else "script", prompts.SYSTEM_CREATIVE,
                                   prompts.regenerate_prompt(section, brief_json, instructions), SectionRegeneration)
        data = res.data
        if section == "lyrics" and data.lyrics:
            script.lyrics = "\n".join(line.strip() for line in data.lyrics if line.strip())
        elif section == "storyboard" and data.storyboard:
            script.scenes.clear()
            self.db.flush()
            script.scenes = [_scene_model(i, s) for i, s in enumerate(data.storyboard)]
        elif section == "metadata" and data.metadata:
            script.seo = data.metadata.model_dump()
        else:
            raise AppError(f"The AI response did not include a '{section}' section")
        self.revalidate(script)
        script.provider, script.model, script.is_fallback = res.provider, res.model, False
        script.approved = False  # regenerated content needs a fresh human approval
        self.db.flush()
        return script

    def revalidate(self, script: RhymeScript) -> dict:
        brief = ContentBrief.model_validate(script_to_brief_dict(script))
        previous = _previous_lyrics(self.db, self.owner_id, exclude_id=script.id)
        competitors = _competitor_texts(self.db, self.owner_id)
        report = check_brief(brief, previous_lyrics=previous, competitor_texts=competitors)
        script.originality_report = report
        script.content_hash = content_hash(brief.lyrics)
        return report


def _scene_model(i: int, s: SceneSpec) -> StoryboardScene:
    return StoryboardScene(order_index=i, description=s.description, lyric_text="\n".join(s.lyric_lines),
                           duration_seconds=s.duration_seconds,
                           visual={"background": s.background, "characters": s.characters, "objects": s.objects,
                                   "mood": s.mood})


def script_to_brief_dict(script: RhymeScript) -> dict:
    return {
        "title": script.title, "topic": script.topic, "theme": script.theme, "language": script.language.value,
        "target_age_range": script.target_age, "objective": script.objective or "Educational sing-along",
        "story_concept": script.story_concept or "Original sing-along",
        "lyrics": [x for x in script.lyrics.split("\n") if x.strip()],
        "storyboard": [{"description": s.description, "lyric_lines": [x for x in s.lyric_text.split("\n") if x],
                        "duration_seconds": s.duration_seconds, **(s.visual or {})} for s in script.scenes],
        "suggested_duration_seconds": script.suggested_duration_seconds,
        "aspect_ratio": "9:16" if script.video_format == VideoFormat.SHORT else "16:9",
        "audio_instructions": script.audio_instructions, "metadata": script.seo,
        "safety_flags": script.safety_flags, "originality_notes": "",
    }

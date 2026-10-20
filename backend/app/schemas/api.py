"""Request/response schemas for the REST API."""

from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.enums import Language, VideoFormat

T = TypeVar("T")


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


# ---- Auth ------------------------------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    display_name: str = Field(default="", max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(ORM):
    id: int
    email: str
    display_name: str
    created_at: datetime


# ---- Settings --------------------------------------------------------------------------------------------
class SettingsOut(ORM):
    default_language: Language
    default_format: VideoFormat
    default_target_age: str
    timezone: str
    publish_window_start_hour: int
    publish_window_end_hour: int
    max_uploads_per_day: int
    publish_days: list[int]
    made_for_kids_default: bool
    default_privacy: str
    youtube_category_id: str
    automation_enabled: bool
    auto_publish_enabled: bool
    paused: bool
    dry_run: bool
    private_test_passed_at: datetime | None
    llm_routing: dict
    llm_models: dict
    cross_model_review: bool
    shorts_resolution: str
    long_resolution: str
    fps: int
    music_volume: float
    narration_volume: float
    setup_completed: bool


class SettingsUpdate(BaseModel):
    default_language: Language | None = None
    default_format: VideoFormat | None = None
    default_target_age: str | None = Field(default=None, pattern=r"^\d{1,2}-\d{1,2}$")
    timezone: str | None = None
    publish_window_start_hour: int | None = Field(default=None, ge=0, le=23)
    publish_window_end_hour: int | None = Field(default=None, ge=1, le=24)
    max_uploads_per_day: int | None = Field(default=None, ge=1, le=10)
    publish_days: list[int] | None = None
    made_for_kids_default: bool | None = None
    default_privacy: str | None = Field(default=None, pattern="^(private|unlisted|public)$")
    youtube_category_id: str | None = Field(default=None, pattern=r"^\d{1,3}$")
    automation_enabled: bool | None = None
    auto_publish_enabled: bool | None = None
    dry_run: bool | None = None
    llm_routing: dict[str, list[str]] | None = None
    llm_models: dict[str, str] | None = None
    cross_model_review: bool | None = None
    shorts_resolution: str | None = Field(default=None, pattern=r"^\d{3,4}x\d{3,4}$")
    long_resolution: str | None = Field(default=None, pattern=r"^\d{3,4}x\d{3,4}$")
    fps: int | None = Field(default=None, ge=12, le=60)
    music_volume: float | None = Field(default=None, ge=0, le=2)
    narration_volume: float | None = Field(default=None, ge=0, le=3)
    setup_completed: bool | None = None

    @field_validator("publish_days")
    @classmethod
    def _days(cls, v: list[int] | None) -> list[int] | None:
        if v is not None and (not v or any(d < 0 or d > 6 for d in v)):
            raise ValueError("publish_days must be a non-empty list of weekday numbers 0 (Mon) - 6 (Sun)")
        return sorted(set(v)) if v else v

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str | None) -> str | None:
        if v is None:
            return v
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown IANA time zone") from None
        return v

    @field_validator("llm_models")
    @classmethod
    def _models(cls, v: dict | None) -> dict | None:
        if v is None:
            return v
        for k, model in v.items():
            if k not in ("grok", "openai", "gemini"):
                raise ValueError(f"Unknown provider '{k}'")
            if model and not all(ch.isalnum() or ch in "-._:/" for ch in model):
                raise ValueError(f"Invalid model name for {k}")
        return v


class ApiKeyUpdate(BaseModel):
    provider: str = Field(pattern="^(grok|openai|gemini)$")
    api_key: str = Field(min_length=8, max_length=300)
    model: str | None = Field(default=None, max_length=128)


class ProviderStatus(BaseModel):
    provider: str
    label: str
    configured: bool
    model: str | None
    key_source: str | None
    key_hint: str | None


# ---- Research --------------------------------------------------------------------------------------------
class ResearchSearchRequest(BaseModel):
    query_type: str = Field(default="topic", pattern="^(topic|channel)$")
    query: str = Field(min_length=2, max_length=200)
    language: str | None = Field(default=None, pattern="^(hi|en|bilingual)$")
    published_after: datetime | None = None
    published_before: datetime | None = None
    video_format: str | None = Field(default=None, pattern="^(short|long)$")
    min_views: int = Field(default=0, ge=0)
    max_results: int = Field(default=25, ge=1, le=50)
    order: str = Field(default="viewCount", pattern="^(viewCount|date|relevance|rating)$")


class ResearchQueryOut(ORM):
    id: int
    query_type: str
    query_text: str
    filters: dict
    status: str
    result_count: int
    quota_units_used: int
    error: str | None
    created_at: datetime


class SnapshotOut(ORM):
    id: int
    research_query_id: int
    video_id: str
    channel_id: str
    channel_title: str
    title: str
    published_at: datetime | None
    duration_seconds: int | None
    view_count: int | None
    like_count: int | None
    comment_count: int | None
    views_per_day: float | None
    engagement_rate: float | None
    language: str
    video_format: str
    topics: list
    captured_at: datetime


class TrendReportOut(ORM):
    id: int
    research_query_id: int | None
    observations: dict
    ai_summary: dict | None
    provider: str | None
    model: str | None
    error: str | None
    created_at: datetime


# ---- Content ---------------------------------------------------------------------------------------------
class IdeasRequest(BaseModel):
    count: int = Field(default=5, ge=1, le=10)
    language: Language = Language.HINDI
    video_format: VideoFormat = VideoFormat.SHORT
    trend_report_id: int | None = None


class IdeaOut(ORM):
    id: int
    topic: str
    theme: str
    language: Language
    video_format: VideoFormat
    target_age: str
    objective: str
    rationale: str
    status: str
    provider: str | None
    created_at: datetime


class GenerateRequest(BaseModel):
    topic: str = Field(min_length=2, max_length=200)
    theme: str = "general"
    language: Language = Language.HINDI
    video_format: VideoFormat = VideoFormat.SHORT
    target_age: str = Field(default="2-5", pattern=r"^\d{1,2}-\d{1,2}$")
    duration_seconds: int = Field(default=45, ge=10, le=900)
    style: str = Field(default="", max_length=300)
    idea_id: int | None = None
    allow_fallback: bool = True
    preferred_provider: str | None = Field(default=None, pattern="^(grok|openai|gemini)$")
    create_project: bool = False
    auto_render: bool = False


class SceneOut(ORM):
    id: int
    order_index: int
    description: str
    lyric_text: str
    duration_seconds: float
    visual: dict


class SceneIn(BaseModel):
    description: str = Field(min_length=3, max_length=600)
    lyric_text: str = Field(default="", max_length=1000)
    duration_seconds: float = Field(ge=2, le=30)
    visual: dict = Field(default_factory=dict)


class ScriptSummary(ORM):
    id: int
    title: str
    language: Language
    topic: str
    theme: str
    video_format: VideoFormat
    provider: str
    model: str
    is_fallback: bool
    approved: bool
    safety_flags: list
    created_at: datetime
    updated_at: datetime


class ScriptOut(ScriptSummary):
    target_age: str
    objective: str
    story_concept: str
    lyrics: str
    audio_instructions: str
    suggested_duration_seconds: int
    seo: dict
    originality_report: dict
    review: dict | None
    prompt: str
    scenes: list[SceneOut]


class ScriptUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=100)
    lyrics: str | None = Field(default=None, min_length=10, max_length=6000)
    story_concept: str | None = Field(default=None, max_length=1500)
    audio_instructions: str | None = Field(default=None, max_length=800)
    seo: dict | None = None
    scenes: list[SceneIn] | None = Field(default=None, max_length=20)
    approved: bool | None = None


class RegenerateRequest(BaseModel):
    section: str = Field(pattern="^(lyrics|storyboard|metadata)$")
    instructions: str = Field(default="", max_length=500)


# ---- Videos / jobs / publishing --------------------------------------------------------------------------
class ProjectCreate(BaseModel):
    script_id: int
    video_format: VideoFormat | None = None
    render: bool = True


class AssetOut(ORM):
    id: int
    kind: str
    path: str
    mime_type: str
    size_bytes: int
    width: int | None
    height: int | None
    duration_seconds: float | None
    provider: str
    is_placeholder: bool


class PublishingJobOut(ORM):
    id: int
    project_id: int
    status: str
    privacy_status: str
    publish_at: datetime | None
    title: str
    made_for_kids: bool
    is_test_upload: bool
    dry_run: bool
    attempts: int
    last_error: str | None
    upload_progress: float
    job_id: int | None
    created_at: datetime
    youtube_video_id: str | None = None


class ProjectOut(ORM):
    id: int
    script_id: int | None
    title: str
    video_format: VideoFormat
    width: int
    height: int
    fps: int
    status: str
    status_history: list
    error: str | None
    duration_seconds: float | None
    file_size_bytes: int | None
    validation: dict
    quality_warnings: list
    has_video: bool = False
    has_thumbnail: bool = False
    language: str | None = None
    publication: PublishingJobOut | None = None
    created_at: datetime
    updated_at: datetime


class ProjectDetail(ProjectOut):
    assets: list[AssetOut] = []
    publishing_jobs: list[PublishingJobOut] = []


class JobOut(ORM):
    id: int
    kind: str
    status: str
    project_id: int | None
    payload: dict
    result: dict | None
    step: str | None
    progress: float
    steps: list
    error: str | None
    attempts: int
    max_attempts: int
    cancel_requested: bool
    run_after: datetime
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class UploadRequest(BaseModel):
    test: bool = Field(default=True, description="Private test upload")
    privacy_status: str = Field(default="private", pattern="^(private|unlisted|public)$")
    title: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = None
    made_for_kids: bool | None = None


class ScheduleRequest(BaseModel):
    publish_at: datetime | None = Field(default=None, description="UTC; omit to use the next free slot")
    made_for_kids: bool | None = None


class RescheduleRequest(BaseModel):
    publish_at: datetime


# ---- Analytics -------------------------------------------------------------------------------------------
class RecommendationOut(ORM):
    id: int
    category: str
    title: str
    body: str
    supporting_data: dict
    confidence: str
    source: str
    status: str
    created_at: datetime


class RecommendationUpdate(BaseModel):
    status: str = Field(pattern="^(proposed|accepted|dismissed)$")


class AnalyticsPoint(BaseModel):
    day: date
    metrics: dict


class AuditOut(ORM):
    id: int
    action: str
    entity_type: str
    entity_id: str
    details: dict
    created_at: datetime

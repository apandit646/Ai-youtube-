"""SQLAlchemy ORM models. Large binaries live on the media volume; only paths/metadata are stored here."""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, utcnow
from app.models.enums import (
    AssetKind,
    JobKind,
    JobStatus,
    Language,
    ProjectStatus,
    PublishStatus,
    RecommendationStatus,
    ResearchType,
    VideoFormat,
)


def _enum(e: type) -> Enum:
    # Stored as VARCHAR + CHECK-free strings so new states don't require PG enum migrations.
    return Enum(e, native_enum=False, length=32, validate_strings=True, values_callable=lambda x: [m.value for m in x])


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    settings: Mapped["AppSettings"] = relationship(back_populates="owner", uselist=False, cascade="all, delete-orphan")


class AppSettings(TimestampMixin, Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)

    default_language: Mapped[Language] = mapped_column(_enum(Language), default=Language.HINDI)
    default_format: Mapped[VideoFormat] = mapped_column(_enum(VideoFormat), default=VideoFormat.SHORT)
    default_target_age: Mapped[str] = mapped_column(String(16), default="2-5")
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    publish_window_start_hour: Mapped[int] = mapped_column(Integer, default=17)
    publish_window_end_hour: Mapped[int] = mapped_column(Integer, default=20)
    max_uploads_per_day: Mapped[int] = mapped_column(Integer, default=1)
    publish_days: Mapped[list] = mapped_column(JSON, default=lambda: [0, 1, 2, 3, 4, 5, 6])
    made_for_kids_default: Mapped[bool] = mapped_column(Boolean, default=True)
    default_privacy: Mapped[str] = mapped_column(String(16), default="private")
    youtube_category_id: Mapped[str] = mapped_column(String(8), default="27")  # Education

    automation_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_publish_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True)
    private_test_passed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Multi-model AI configuration
    llm_routing: Mapped[dict] = mapped_column(JSON, default=dict)  # task -> [provider, ...]
    llm_models: Mapped[dict] = mapped_column(JSON, default=dict)  # provider -> model override
    encrypted_api_keys: Mapped[dict] = mapped_column(JSON, default=dict)  # provider -> fernet ciphertext
    cross_model_review: Mapped[bool] = mapped_column(Boolean, default=True)

    # Rendering
    shorts_resolution: Mapped[str] = mapped_column(String(16), default="1080x1920")
    long_resolution: Mapped[str] = mapped_column(String(16), default="1920x1080")
    fps: Mapped[int] = mapped_column(Integer, default=30)
    music_volume: Mapped[float] = mapped_column(Float, default=0.25)
    narration_volume: Mapped[float] = mapped_column(Float, default=1.0)
    setup_completed: Mapped[bool] = mapped_column(Boolean, default=False)

    owner: Mapped[User] = relationship(back_populates="settings")


class ConnectedYouTubeChannel(TimestampMixin, Base):
    __tablename__ = "youtube_channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    thumbnail_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    subscriber_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    video_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ResearchQuery(TimestampMixin, Base):
    __tablename__ = "research_queries"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    query_type: Mapped[ResearchType] = mapped_column(_enum(ResearchType))
    query_text: Mapped[str] = mapped_column(String(255))
    filters: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus), default=JobStatus.QUEUED)
    result_count: Mapped[int] = mapped_column(Integer, default=0)
    quota_units_used: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    snapshots: Mapped[list["CompetitorVideoSnapshot"]] = relationship(
        back_populates="query", cascade="all, delete-orphan"
    )


class CompetitorVideoSnapshot(Base):
    __tablename__ = "competitor_video_snapshots"
    __table_args__ = (
        UniqueConstraint("research_query_id", "video_id", name="uq_snapshot_query_video"),
        Index("ix_snapshot_video_captured", "video_id", "captured_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    research_query_id: Mapped[int] = mapped_column(ForeignKey("research_queries.id", ondelete="CASCADE"), index=True)
    video_id: Mapped[str] = mapped_column(String(32))
    channel_id: Mapped[str] = mapped_column(String(64), index=True)
    channel_title: Mapped[str] = mapped_column(String(255), default="")
    title: Mapped[str] = mapped_column(String(512))
    description: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    view_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    like_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    views_per_day: Mapped[float | None] = mapped_column(Float, nullable=True)
    engagement_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    language: Mapped[str] = mapped_column(String(16), default="unknown")
    video_format: Mapped[str] = mapped_column(String(16), default="unknown")
    topics: Mapped[list] = mapped_column(JSON, default=list)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    query: Mapped[ResearchQuery] = relationship(back_populates="snapshots")


class TrendReport(Base):
    __tablename__ = "trend_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    research_query_id: Mapped[int | None] = mapped_column(
        ForeignKey("research_queries.id", ondelete="SET NULL"), nullable=True, index=True
    )
    observations: Mapped[dict] = mapped_column(JSON, default=dict)  # computed facts from stored data
    ai_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # LLM interpretation (assumptions)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ContentIdea(Base):
    __tablename__ = "content_ideas"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    trend_report_id: Mapped[int | None] = mapped_column(
        ForeignKey("trend_reports.id", ondelete="SET NULL"), nullable=True
    )
    topic: Mapped[str] = mapped_column(String(255))
    theme: Mapped[str] = mapped_column(String(64), default="general")
    language: Mapped[Language] = mapped_column(_enum(Language))
    video_format: Mapped[VideoFormat] = mapped_column(_enum(VideoFormat), default=VideoFormat.SHORT)
    target_age: Mapped[str] = mapped_column(String(16), default="2-5")
    objective: Mapped[str] = mapped_column(Text, default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="new")
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RhymeScript(TimestampMixin, Base):
    __tablename__ = "rhyme_scripts"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    idea_id: Mapped[int | None] = mapped_column(ForeignKey("content_ideas.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    language: Mapped[Language] = mapped_column(_enum(Language), index=True)
    topic: Mapped[str] = mapped_column(String(255), index=True)
    theme: Mapped[str] = mapped_column(String(64), default="general")
    target_age: Mapped[str] = mapped_column(String(16), default="2-5")
    objective: Mapped[str] = mapped_column(Text, default="")
    story_concept: Mapped[str] = mapped_column(Text, default="")
    lyrics: Mapped[str] = mapped_column(Text)
    audio_instructions: Mapped[str] = mapped_column(Text, default="")
    suggested_duration_seconds: Mapped[int] = mapped_column(Integer, default=45)
    video_format: Mapped[VideoFormat] = mapped_column(_enum(VideoFormat), default=VideoFormat.SHORT)
    seo: Mapped[dict] = mapped_column(JSON, default=dict)  # titles, description, hashtags, keywords, thumbnail
    safety_flags: Mapped[list] = mapped_column(JSON, default=list)
    originality_report: Mapped[dict] = mapped_column(JSON, default=dict)
    review: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # cross-model review
    prompt: Mapped[str] = mapped_column(Text, default="")
    provider: Mapped[str] = mapped_column(String(32), default="fallback")
    model: Mapped[str] = mapped_column(String(128), default="")
    is_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    approved: Mapped[bool] = mapped_column(Boolean, default=False)

    scenes: Mapped[list["StoryboardScene"]] = relationship(
        back_populates="script", cascade="all, delete-orphan", order_by="StoryboardScene.order_index"
    )


class StoryboardScene(Base):
    __tablename__ = "storyboard_scenes"
    __table_args__ = (UniqueConstraint("script_id", "order_index", name="uq_scene_script_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    script_id: Mapped[int] = mapped_column(ForeignKey("rhyme_scripts.id", ondelete="CASCADE"), index=True)
    order_index: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    lyric_text: Mapped[str] = mapped_column(Text, default="")
    duration_seconds: Mapped[float] = mapped_column(Float, default=6.0)
    visual: Mapped[dict] = mapped_column(JSON, default=dict)  # background, characters, objects, palette, mood

    script: Mapped[RhymeScript] = relationship(back_populates="scenes")


class VideoProject(TimestampMixin, Base):
    __tablename__ = "video_projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    script_id: Mapped[int | None] = mapped_column(
        ForeignKey("rhyme_scripts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    video_format: Mapped[VideoFormat] = mapped_column(_enum(VideoFormat))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    fps: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[ProjectStatus] = mapped_column(_enum(ProjectStatus), default=ProjectStatus.PENDING, index=True)
    status_history: Mapped[list] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    subtitles_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    validation: Mapped[dict] = mapped_column(JSON, default=dict)
    quality_warnings: Mapped[list] = mapped_column(JSON, default=list)

    script: Mapped[RhymeScript | None] = relationship()
    assets: Mapped[list["MediaAsset"]] = relationship(back_populates="project", cascade="all, delete-orphan")
    publishing_jobs: Mapped[list["PublishingJob"]] = relationship(back_populates="project")


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("video_projects.id", ondelete="CASCADE"), index=True)
    kind: Mapped[AssetKind] = mapped_column(_enum(AssetKind))
    path: Mapped[str] = mapped_column(String(1024))
    mime_type: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    provider: Mapped[str] = mapped_column(String(64), default="local")
    is_placeholder: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[VideoProject] = relationship(back_populates="assets")


class Job(TimestampMixin, Base):
    """Persistent background job processed by the worker (DB-backed queue)."""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[JobKind] = mapped_column(_enum(JobKind))
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus), default=JobStatus.QUEUED)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    steps: Mapped[list] = mapped_column(JSON, default=list)  # [{step, status, started_at, finished_at, error}]
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dedupe_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)


class PublishingJob(TimestampMixin, Base):
    __tablename__ = "publishing_jobs"
    __table_args__ = (Index("ix_publishing_status_publish_at", "status", "publish_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("video_projects.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[int | None] = mapped_column(
        ForeignKey("youtube_channels.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[PublishStatus] = mapped_column(_enum(PublishStatus), default=PublishStatus.QUEUED)
    privacy_status: Mapped[str] = mapped_column(String(16), default="private")
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    category_id: Mapped[str] = mapped_column(String(8), default="27")
    default_language: Mapped[str] = mapped_column(String(8), default="hi")
    made_for_kids: Mapped[bool] = mapped_column(Boolean, default=True)
    is_test_upload: Mapped[bool] = mapped_column(Boolean, default=False)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    upload_progress: Mapped[float] = mapped_column(Float, default=0.0)
    resumable_session_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True)

    project: Mapped[VideoProject] = relationship(back_populates="publishing_jobs")
    published_video: Mapped["PublishedVideo | None"] = relationship(back_populates="publishing_job", uselist=False)


class PublishedVideo(TimestampMixin, Base):
    __tablename__ = "published_videos"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    publishing_job_id: Mapped[int] = mapped_column(ForeignKey("publishing_jobs.id", ondelete="CASCADE"), unique=True)
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("video_projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    youtube_video_id: Mapped[str] = mapped_column(String(32), unique=True)
    channel_id: Mapped[str] = mapped_column(String(64), default="")
    privacy_status: Mapped[str] = mapped_column(String(16))
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    upload_status: Mapped[str] = mapped_column(String(32), default="uploaded")
    language: Mapped[str] = mapped_column(String(16), default="")
    topic: Mapped[str] = mapped_column(String(255), default="")
    video_format: Mapped[str] = mapped_column(String(16), default="")
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    api_response: Mapped[dict] = mapped_column(JSON, default=dict)

    publishing_job: Mapped[PublishingJob] = relationship(back_populates="published_video")


class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"
    __table_args__ = (
        UniqueConstraint("owner_id", "scope", "youtube_video_id", "day", name="uq_analytics_scope_video_day"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scope: Mapped[str] = mapped_column(String(16))  # channel | video
    youtube_video_id: Mapped[str] = mapped_column(String(32), default="")  # "" for channel scope
    day: Mapped[date] = mapped_column(Date, index=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    unavailable_metrics: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(64), default="youtube_analytics_v2")
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    category: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    supporting_data: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[str] = mapped_column(String(16), default="low")
    source: Mapped[str] = mapped_column(String(32), default="statistics")  # statistics | <llm provider>
    status: Mapped[RecommendationStatus] = mapped_column(
        _enum(RecommendationStatus), default=RecommendationStatus.PROPOSED
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(64), default="")
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

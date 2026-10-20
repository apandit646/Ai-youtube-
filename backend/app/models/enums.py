import enum


class StrEnum(str, enum.Enum):
    def __str__(self) -> str:
        return self.value


class Language(StrEnum):
    HINDI = "hi"
    ENGLISH = "en"
    BILINGUAL = "bilingual"


class VideoFormat(StrEnum):
    SHORT = "short"  # 9:16 YouTube Shorts
    LONG = "long"  # 16:9 long-form


class ProjectStatus(StrEnum):
    PENDING = "PENDING"
    RESEARCHING = "RESEARCHING"
    SCRIPTING = "SCRIPTING"
    GENERATING_MEDIA = "GENERATING_MEDIA"
    RENDERING = "RENDERING"
    VALIDATING = "VALIDATING"
    READY = "READY"
    UPLOADING = "UPLOADING"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobKind(StrEnum):
    RESEARCH = "research"
    GENERATE_CONTENT = "generate_content"
    RENDER = "render"
    UPLOAD = "upload"
    ANALYTICS = "analytics"
    RECOMMEND = "recommend"
    PIPELINE = "pipeline"  # full end-to-end automation run


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PublishStatus(StrEnum):
    QUEUED = "QUEUED"
    UPLOADING = "UPLOADING"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    UPLOADED_PRIVATE = "UPLOADED_PRIVATE"
    DRY_RUN = "DRY_RUN"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AssetKind(StrEnum):
    SCENE_IMAGE = "scene_image"
    NARRATION = "narration"
    MUSIC = "music"
    VIDEO = "video"
    THUMBNAIL = "thumbnail"
    SUBTITLES = "subtitles"


class ResearchType(StrEnum):
    TOPIC = "topic"
    CHANNEL = "channel"


class RecommendationStatus(StrEnum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    DISMISSED = "dismissed"

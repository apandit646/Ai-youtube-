"""Strict structured-output schemas for AI content generation."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.services.media.vocabulary import BACKGROUNDS, CHARACTERS, MOODS, normalize_object

THEMES = ["animals", "numbers", "colors", "shapes", "bedtime", "alphabet", "kindness", "nature", "family",
          "hygiene", "fruits", "vehicles", "general"]


class SceneSpec(BaseModel):
    description: str = Field(min_length=5, max_length=600)
    lyric_lines: list[str] = Field(default_factory=list, max_length=8)
    duration_seconds: float = Field(ge=2, le=30)
    background: str = "meadow"
    characters: list[str] = Field(default_factory=list, max_length=4)
    objects: list[str] = Field(default_factory=list, max_length=8)
    mood: str = "happy"

    @field_validator("background")
    @classmethod
    def _bg(cls, v: str) -> str:
        v = v.strip().lower()
        return v if v in BACKGROUNDS else "meadow"

    @field_validator("characters")
    @classmethod
    def _chars(cls, v: list[str]) -> list[str]:
        return [c.strip().lower() for c in v if c.strip().lower() in CHARACTERS]

    @field_validator("objects")
    @classmethod
    def _objs(cls, v: list[str]) -> list[str]:
        return [o for o in (normalize_object(x) for x in v) if o]

    @field_validator("mood")
    @classmethod
    def _mood(cls, v: str) -> str:
        return v if v in MOODS else "happy"


class SEOMetadata(BaseModel):
    title: str = Field(min_length=5, max_length=100)
    description: str = Field(min_length=20, max_length=4500)
    hashtags: list[str] = Field(default_factory=list)  # trimmed to 5 below
    keywords: list[str] = Field(default_factory=list)  # trimmed to 15 below
    thumbnail_text: str = Field(min_length=1, max_length=40)
    thumbnail_design: str = Field(default="", max_length=400)

    @field_validator("hashtags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        out = []
        for tag in v:
            tag = "#" + "".join(ch for ch in tag.lstrip("#") if ch.isalnum() or ch == "_")
            if len(tag) > 1 and tag.lower() not in {t.lower() for t in out}:
                out.append(tag)
        return out[:5]

    @field_validator("keywords")
    @classmethod
    def _keywords(cls, v: list[str]) -> list[str]:
        return [k.strip()[:60] for k in v if k.strip()][:15]

    @field_validator("title", "description")
    @classmethod
    def _no_angle_brackets(cls, v: str) -> str:
        return v.replace("<", "").replace(">", "").strip()  # YouTube rejects angle brackets


class ContentBrief(BaseModel):
    title: str = Field(min_length=3, max_length=100)
    topic: str = Field(min_length=2, max_length=200)
    theme: str = "general"
    language: Literal["hi", "en", "bilingual"]
    target_age_range: str = Field(default="2-5", max_length=16)
    objective: str = Field(min_length=5, max_length=500)
    story_concept: str = Field(min_length=10, max_length=1500)
    lyrics: list[str] = Field(min_length=4, max_length=48)
    storyboard: list[SceneSpec] = Field(min_length=2, max_length=20)
    suggested_duration_seconds: int = Field(ge=10, le=900)
    aspect_ratio: Literal["9:16", "16:9"]
    audio_instructions: str = Field(default="", max_length=800)
    metadata: SEOMetadata
    safety_flags: list[str] = Field(default_factory=list)
    originality_notes: str = Field(default="", max_length=800)

    @field_validator("theme")
    @classmethod
    def _theme(cls, v: str) -> str:
        return v if v in THEMES else "general"

    @field_validator("lyrics")
    @classmethod
    def _lyrics(cls, v: list[str]) -> list[str]:
        lines = [line.strip() for line in v if line.strip()]
        if len(lines) < 4:
            raise ValueError("lyrics must contain at least 4 non-empty lines")
        if any(len(line) > 120 for line in lines):
            raise ValueError("each lyric line must be at most 120 characters")
        return lines


class IdeaSpec(BaseModel):
    topic: str = Field(min_length=2, max_length=200)
    theme: str = "general"
    language: Literal["hi", "en", "bilingual"]
    format: Literal["short", "long"] = "short"
    target_age: str = "2-5"
    objective: str = Field(min_length=5, max_length=400)
    rationale: str = Field(min_length=5, max_length=800)

    @field_validator("theme")
    @classmethod
    def _theme(cls, v: str) -> str:
        return v if v in THEMES else "general"


class IdeaList(BaseModel):
    ideas: list[IdeaSpec] = Field(min_length=1, max_length=12)


class ReviewResult(BaseModel):
    approved: bool
    originality_score: int = Field(ge=0, le=10)
    age_appropriate: bool
    issues: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class SectionRegeneration(BaseModel):
    lyrics: list[str] | None = None
    storyboard: list[SceneSpec] | None = None
    metadata: SEOMetadata | None = None

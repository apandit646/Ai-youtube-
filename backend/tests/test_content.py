import httpx
import pytest
from pydantic import ValidationError

from app.models import RhymeScript
from app.models.enums import Language, VideoFormat
from app.services.content.fallback import build_fallback_brief
from app.services.content.originality import check_brief, normalize
from app.services.content.schemas import THEMES, ContentBrief, SEOMetadata
from app.services.content.service import ContentService, GenerationRequest, OriginalityRejected
from app.services.llm.base import GeminiProvider, GrokProvider, OpenAIProvider
from app.services.llm.router import LLMRouter
from app.services.settings_service import get_app_settings
from tests.helpers import chat_response, gemini_response, no_sleep, sample_brief


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("language", ["hi", "en", "bilingual"])
def test_fallback_templates_are_valid_and_pass_checks(theme, language):
    brief = build_fallback_brief(topic="Happy song", theme=theme, language=language, video_format="short",
                                 target_age="2-5")
    assert brief.language == language
    assert sum(s.duration_seconds for s in brief.storyboard) <= 60
    report = check_brief(brief)
    assert report["passed"], report


def test_fallback_is_deterministic_and_variants_differ():
    a = build_fallback_brief(topic="Zoo", theme="animals", language="en", video_format="short", target_age="2-5")
    b = build_fallback_brief(topic="Zoo", theme="animals", language="en", video_format="short", target_age="2-5")
    c = build_fallback_brief(topic="Zoo", theme="animals", language="en", video_format="short", target_age="2-5",
                             variant=3)
    assert a.lyrics == b.lyrics
    assert a.lyrics != c.lyrics


def test_originality_rejects_known_rhymes_brands_and_bait():
    brief = ContentBrief.model_validate(sample_brief(1))
    brief.lyrics = ["Twinkle twinkle little star,", "how I wonder", "what you are", "up above"]
    report = check_brief(brief)
    assert not report["passed"]
    assert not next(c for c in report["checks"] if c["name"] == "not_existing_rhyme")["passed"]

    brief = ContentBrief.model_validate(sample_brief(1))
    brief.metadata.description = "Like and subscribe for more CoComelon style fun!"
    names = {c["name"] for c in check_brief(brief)["checks"] if not c["passed"]}
    assert {"no_third_party_brands", "no_engagement_bait"} <= names


def test_originality_flags_similarity_to_own_catalog_and_competitors():
    brief = ContentBrief.model_validate(sample_brief(1))
    same = "\n".join(brief.lyrics)
    assert not check_brief(brief, previous_lyrics=[same])["passed"]
    assert not check_brief(brief, competitor_texts=[f"Random title\n{same}"])["passed"]
    assert check_brief(brief, previous_lyrics=["totally different words about trains and buses going"])["passed"]


def test_hindi_normalisation_keeps_matras():
    assert normalize("चाकू!") == "चाकू"
    assert normalize("मछली जल की रानी है।") == "मछली जल की रानी है"


def test_schema_validation_rules():
    data = sample_brief(0)
    data["lyrics"] = ["one", "two"]
    with pytest.raises(ValidationError):
        ContentBrief.model_validate(data)
    data = sample_brief(0)
    data["storyboard"][0]["background"] = "volcano"
    data["storyboard"][0]["characters"] = ["dragon", "cat"]
    data["storyboard"][0]["objects"] = ["number:99", "letter:b", "shape:circle", "sword"]
    scene = ContentBrief.model_validate(data).storyboard[0]
    assert scene.background == "meadow" and scene.characters == ["cat"]
    assert scene.objects == ["letter:B", "shape:circle"]
    meta = SEOMetadata(title="<b>Hi</b> there", description="x" * 30, hashtags=["a", "#b", "#B", "c d", "e", "f", "g"],
                       thumbnail_text="Hi")
    assert "<" not in meta.title and len(meta.hashtags) == 5 and "#cd" in meta.hashtags


def _router(grok_handler=None, review_handler=None) -> LLMRouter:
    def mk(cls, h):
        return cls("key-abcdefgh1", "m", "https://x.test", transport=httpx.MockTransport(h), sleep=no_sleep,
                   max_retries=0) if h else cls("", "", "https://x")
    return LLMRouter({"grok": mk(GrokProvider, grok_handler), "openai": mk(OpenAIProvider, None),
                      "gemini": mk(GeminiProvider, review_handler)})


def test_generate_script_with_ai_and_cross_model_review(db, user):
    review = {"approved": True, "originality_score": 9, "age_appropriate": True, "issues": [], "suggestions": []}
    router = _router(lambda r: chat_response(sample_brief(0)), lambda r: gemini_response(review))
    svc = ContentService(db, user.id, router, get_app_settings(db, user.id))
    script = svc.generate_script(GenerationRequest(topic="Counting sweets", theme="numbers", language=Language.HINDI))
    db.commit()
    assert script.provider == "grok" and not script.is_fallback
    assert script.review["provider"] == "gemini" and script.review["approved"]
    assert script.originality_report["passed"]
    assert len(script.scenes) == 3 and script.scenes[0].visual["background"] == "classroom"
    assert script.prompt.startswith("[") and "Counting sweets" in script.prompt


def test_generate_rejects_duplicate_ai_output_then_uses_labelled_fallback(db, user):
    router = _router(lambda r: chat_response(sample_brief(0)))
    svc = ContentService(db, user.id, router, get_app_settings(db, user.id))
    first = svc.generate_script(GenerationRequest(topic="Laddoo", theme="numbers", language=Language.HINDI))
    db.commit()
    second = svc.generate_script(GenerationRequest(topic="Laddoo", theme="numbers", language=Language.HINDI))
    assert not first.is_fallback
    assert second.is_fallback and second.provider == "fallback-template"
    assert second.originality_report["passed"]


def test_generate_without_fallback_raises_when_rejected(db, user):
    router = _router(lambda r: chat_response(sample_brief(0)))
    svc = ContentService(db, user.id, router, get_app_settings(db, user.id))
    svc.generate_script(GenerationRequest(topic="Laddoo", theme="numbers", language=Language.HINDI))
    with pytest.raises(OriginalityRejected):
        svc.generate_script(GenerationRequest(topic="Laddoo", theme="numbers", language=Language.HINDI,
                                              allow_fallback=False))


def test_no_ai_configured_uses_fallback_and_never_pretends(db, user):
    svc = ContentService(db, user.id, _router(), get_app_settings(db, user.id))
    script = svc.generate_script(GenerationRequest(topic="Bedtime", theme="bedtime", language=Language.ENGLISH,
                                                   video_format=VideoFormat.LONG))
    assert script.is_fallback and script.provider == "fallback-template" and script.model == ""
    assert script.review is None
    assert db.get(RhymeScript, script.id).video_format == VideoFormat.LONG


def test_regenerate_metadata_section(db, user):
    meta = {"metadata": {"title": "A Brand New Title", "description": "A fresh description for parents.",
                         "hashtags": ["#KidsSongs"], "keywords": ["k"], "thumbnail_text": "New!"}}
    router = _router(lambda r: chat_response(meta))
    svc = ContentService(db, user.id, router, get_app_settings(db, user.id))
    script = ContentService(db, user.id, _router(), None).generate_script(
        GenerationRequest(topic="Shapes", theme="shapes", language=Language.ENGLISH))
    svc.regenerate_section(script, "metadata")
    assert script.seo["title"] == "A Brand New Title" and script.provider == "grok"

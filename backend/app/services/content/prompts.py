"""Prompt templates. Kept separate so they are versionable and testable."""

import json

from app.services.content.schemas import THEMES
from app.services.media.vocabulary import VOCABULARY_PROMPT

PROMPT_VERSION = "2026-10-v1"

SYSTEM_CREATIVE = (
    "You are a children's songwriter and early-childhood educator creating ORIGINAL nursery rhymes for a "
    "YouTube channel for toddlers and preschoolers. Rules:\n"
    "- Never reproduce, translate, or closely paraphrase existing rhymes, songs, melodies, scripts, characters or "
    "branding (e.g. no 'Twinkle Twinkle', 'Machli Jal Ki Rani', 'Baby Shark', no CoComelon/ChuChu characters).\n"
    "- Content must be gentle, positive, age-appropriate, free of violence, fear, brand names, URLs and "
    "engagement bait ('like and subscribe' etc.).\n"
    "- Hindi must be written in Devanagari script with simple words toddlers know.\n"
    "- Use repetition, rhythm and an educational hook.\n"
    "- Respond with a single JSON object only. No markdown."
)

SYSTEM_ANALYST = (
    "You are a careful YouTube content analyst for a children's channel. You only draw conclusions that are "
    "supported by the data you are given, clearly separate observations (in the data) from hypotheses "
    "(assumptions), never invent metrics, and never promise views, virality, rankings or income. "
    "Respond with a single JSON object only."
)

SYSTEM_REVIEWER = (
    "You are an independent reviewer of children's content. Assess originality (is it a copy or close "
    "paraphrase of a known rhyme or song?), age appropriateness, safety and YouTube made-for-kids policy fit. "
    "Be strict but fair. Respond with a single JSON object only."
)

LANG_NAMES = {"hi": "Hindi (Devanagari)", "en": "English", "bilingual": "bilingual Hindi + English"}


def brief_prompt(*, topic: str, theme: str, language: str, video_format: str, target_age: str,
                 duration_seconds: int, style: str, avoid_titles: list[str], trend_context: str) -> str:
    aspect = "9:16" if video_format == "short" else "16:9"
    scene_hint = "4-8 scenes, total under 58 seconds" if video_format == "short" else "8-16 scenes"
    return f"""Create an original rhyme video brief.

Topic: {topic}
Theme (one of {THEMES}): {theme}
Language: {LANG_NAMES.get(language, language)}
Target age: {target_age}
Format: {"YouTube Short" if video_format == "short" else "long-form video"} ({aspect}), about {duration_seconds}s
Style: {style or "cheerful, simple, sing-along"}

Storyboard visual vocabulary (the renderer can ONLY draw these; use exact tokens):
{VOCABULARY_PROMPT}

Avoid these existing titles and anything similar to them:
{json.dumps(avoid_titles[:30], ensure_ascii=False)}

Broad trend context (inform the topic choice only; never copy):
{trend_context or "none"}

Return JSON with keys:
title, topic, theme, language ("hi"|"en"|"bilingual"), target_age_range, objective, story_concept,
lyrics (array of lines), storyboard (array, {scene_hint}; each: description, lyric_lines (subset of lyrics in
order), duration_seconds, background, characters, objects, mood), suggested_duration_seconds,
aspect_ratio ("{aspect}"), audio_instructions, metadata {{title (<=100 chars, no clickbait), description
(2-4 short paragraphs, parent-facing, no external links), hashtags (2-4 relevant), keywords (5-10),
thumbnail_text (2-4 words), thumbnail_design}}, safety_flags (array of concerns, empty if none),
originality_notes (how this differs from common rhymes)."""


def ideas_prompt(*, count: int, language: str, video_format: str, observations: dict,
                 existing_topics: list[str]) -> str:
    return f"""Suggest {count} ORIGINAL content ideas for a children's rhyme channel.
Preferred language: {LANG_NAMES.get(language, language)} (you may include a bilingual idea).
Preferred format: {video_format}
Allowed themes: {THEMES}

Observed public research data (facts computed from YouTube Data API results — treat as observations):
{json.dumps(observations, ensure_ascii=False, default=str)[:6000]}

Topics we already made (avoid repeats): {json.dumps(existing_topics[:50], ensure_ascii=False)}

Return JSON: {{"ideas": [{{"topic", "theme", "language": "hi"|"en"|"bilingual", "format": "short"|"long",
"target_age", "objective", "rationale" (cite which observation supports it, or say it is an untested
hypothesis)}}]}}"""


def trend_prompt(observations: dict) -> str:
    return f"""Here are observations computed from public YouTube Data API results for nursery-rhyme videos:
{json.dumps(observations, ensure_ascii=False, default=str)[:9000]}

Return JSON: {{"summary": str, "observations": [str] (facts directly visible in the data, cite numbers),
"hypotheses": [str] (possible explanations; label as unverified), "opportunities": [{{"topic", "language",
"format", "why"}}], "caveats": [str] (data limits, e.g. public stats exclude CTR/retention/revenue)}}"""


def review_prompt(brief_json: str) -> str:
    return f"""Review this children's rhyme brief:
{brief_json}

Return JSON: {{"approved": bool, "originality_score": 0-10 (10 = fully original), "age_appropriate": bool,
"issues": [str], "suggestions": [str]}}"""


def regenerate_prompt(section: str, brief_json: str, instructions: str) -> str:
    shape = {
        "lyrics": '{"lyrics": [str, ...]}',
        "storyboard": '{"storyboard": [{description, lyric_lines, duration_seconds, background, characters, '
                      'objects, mood}, ...]}',
        "metadata": '{"metadata": {title, description, hashtags, keywords, thumbnail_text, thumbnail_design}}',
    }[section]
    return f"""Here is an existing original rhyme brief:
{brief_json}

Regenerate ONLY the "{section}" section. Keep it original and consistent with the rest of the brief.
Extra instructions from the editor: {instructions or "none"}
Storyboard vocabulary (if relevant): {VOCABULARY_PROMPT}
Return JSON exactly shaped like: {shape}"""


def recommendations_prompt(stats: dict) -> str:
    return f"""Here are aggregated performance statistics of OUR OWN channel videos, from the YouTube Analytics API:
{json.dumps(stats, ensure_ascii=False, default=str)[:8000]}

Suggest at most 5 next-batch recommendations grounded ONLY in these numbers. If sample sizes are small,
say so and set confidence "low". Return JSON:
{{"recommendations": [{{"category": "topic"|"language"|"format"|"duration"|"timing"|"general", "title", "body",
"evidence" (which numbers support it), "confidence": "low"|"medium"|"high"}}]}}"""

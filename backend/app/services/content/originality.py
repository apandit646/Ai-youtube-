"""Originality, safety and structure checks applied to every generated brief before it is stored."""

import hashlib
import re
import unicodedata

from app.services.content.schemas import ContentBrief

# Well-known existing rhymes / songs. New content must not reproduce them (even when public domain, the
# platform's goal is distinct, original work). Matched on normalised text.
KNOWN_RHYME_PHRASES = [
    "twinkle twinkle little star", "baa baa black sheep", "johny johny yes papa", "wheels on the bus",
    "old macdonald had a farm", "humpty dumpty sat on a wall", "itsy bitsy spider", "baby shark doo doo",
    "row row row your boat", "mary had a little lamb", "jack and jill went up the hill", "london bridge is falling",
    "head shoulders knees and toes", "if you're happy and you know it", "five little monkeys jumping",
    "rain rain go away", "hickory dickory dock", "the itsy bitsy", "bingo was his name",
    "मछली जल की रानी है", "चंदा मामा दूर के", "लकड़ी की काठी", "नानी तेरी मोरनी", "आलू कचालू",
    "एक मोटा हाथी", "हाथी राजा कहाँ चले", "चूँ चूँ करती आई चिड़िया", "बिल्ली मौसी बिल्ली मौसी",
]

# Distinctive third-party brands/characters that must never appear in our content or metadata.
BRAND_TERMS = [
    "cocomelon", "pinkfong", "chuchu", "chu chu tv", "bluey", "peppa", "disney", "paw patrol", "little baby bum",
    "super simple", "babybus", "masha", "doraemon", "chhota bheem", "motu patlu", "infobells", "jugnu kids",
]

UNSAFE_TERMS = [
    "kill", "blood", "gun", "knife", "die", "dead", "scary", "monster attack", "hate", "stupid", "beat you",
    "मार डालो", "खून", "बंदूक", "चाकू",
]

ENGAGEMENT_BAIT = ["subscribe now", "like and subscribe", "comment below", "smash the like", "click the bell"]

_URL = re.compile(r"https?://|www\.", re.I)


def normalize(text: str) -> str:
    """Lowercase, NFC, punctuation/symbols → spaces. Keeps combining marks so Devanagari matras survive."""
    text = unicodedata.normalize("NFC", text.lower())
    text = "".join(" " if unicodedata.category(ch)[0] in "PSZC" and ch != "\n" else ch for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def ngrams(text: str, n: int = 3) -> set[tuple[str, ...]]:
    words = normalize(text).split()
    return {tuple(words[i : i + n]) for i in range(max(len(words) - n + 1, 0))}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def content_hash(lyrics: list[str]) -> str:
    return hashlib.sha256(normalize("\n".join(lyrics)).encode()).hexdigest()


def check_brief(brief: ContentBrief, *, previous_lyrics: list[str] | None = None,
                competitor_texts: list[str] | None = None, max_similarity: float = 0.35) -> dict:
    """Return a report {passed, max_similarity, checks:[{name, passed, detail}]}. `passed` is False if any
    blocking check fails; `warnings` are non-blocking."""
    checks: list[dict] = []
    lyrics_text = "\n".join(brief.lyrics)
    norm_lyrics = normalize(lyrics_text)
    all_text = normalize(" ".join([lyrics_text, brief.title, brief.metadata.title, brief.metadata.description]))

    hits = [p for p in KNOWN_RHYME_PHRASES if normalize(p) in norm_lyrics]
    checks.append({"name": "not_existing_rhyme", "passed": not hits, "blocking": True,
                   "detail": f"Matches known rhyme phrases: {hits}" if hits else "No known rhyme phrases found"})

    brands = [b for b in BRAND_TERMS if b in all_text]
    checks.append({"name": "no_third_party_brands", "passed": not brands, "blocking": True,
                   "detail": f"Mentions brands/characters: {brands}" if brands else "No third-party brands"})

    unsafe = [w for w in UNSAFE_TERMS if re.search(rf"(?<!\w){re.escape(normalize(w))}(?!\w)", all_text)]
    checks.append({"name": "child_safe_language", "passed": not unsafe, "blocking": True,
                   "detail": f"Potentially unsafe terms: {unsafe}" if unsafe else "No unsafe terms"})

    bait = [b for b in ENGAGEMENT_BAIT if b in all_text]
    checks.append({"name": "no_engagement_bait", "passed": not bait, "blocking": True,
                   "detail": f"Engagement bait not allowed in kids content: {bait}" if bait else "OK"})

    urls = bool(_URL.search(lyrics_text))
    checks.append({"name": "no_urls_in_lyrics", "passed": not urls, "blocking": True,
                   "detail": "Lyrics contain URLs" if urls else "OK"})

    lines = brief.lyrics
    unique_ratio = len({normalize(x) for x in lines}) / max(len(lines), 1)
    checks.append({"name": "structure", "passed": 4 <= len(lines) <= 48 and unique_ratio >= 0.3, "blocking": True,
                   "detail": f"{len(lines)} lines, {unique_ratio:.0%} unique"})

    script_seconds = sum(s.duration_seconds for s in brief.storyboard)
    fmt_ok = brief.aspect_ratio == "16:9" or script_seconds <= 60
    checks.append({"name": "format_duration", "passed": fmt_ok, "blocking": False,
                   "detail": f"Storyboard length {script_seconds:.0f}s for {brief.aspect_ratio}"})

    grams = ngrams(lyrics_text)
    max_prev = max((jaccard(grams, ngrams(p)) for p in previous_lyrics or []), default=0.0)
    checks.append({"name": "distinct_from_own_catalog", "passed": max_prev <= max_similarity, "blocking": True,
                   "detail": f"Max 3-gram similarity to previous scripts: {max_prev:.2f} (limit {max_similarity})"})

    max_comp = 0.0
    comp_title_match = False
    title_norm = normalize(brief.metadata.title)
    for text in competitor_texts or []:
        max_comp = max(max_comp, jaccard(grams, ngrams(text)))
        if title_norm and title_norm == normalize(text.split("\n", 1)[0]):
            comp_title_match = True
    checks.append({"name": "distinct_from_competitors", "passed": max_comp <= max_similarity and not comp_title_match,
                   "blocking": True,
                   "detail": f"Max similarity to researched public videos: {max_comp:.2f}"
                             + ("; title identical to a competitor title" if comp_title_match else "")})

    hashtags_ok = len(brief.metadata.hashtags) <= 5
    checks.append({"name": "hashtag_count", "passed": hashtags_ok, "blocking": False,
                   "detail": f"{len(brief.metadata.hashtags)} hashtags (max 5 recommended)"})

    passed = all(c["passed"] for c in checks if c["blocking"])
    return {
        "passed": passed,
        "max_similarity_own": round(max_prev, 3),
        "max_similarity_competitors": round(max_comp, 3),
        "checks": checks,
        "warnings": [c["detail"] for c in checks if not c["passed"] and not c["blocking"]],
    }

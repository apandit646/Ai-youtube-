"""Deterministic, original template-based rhymes used ONLY when no AI provider is available.

Every output is explicitly labelled `is_fallback=True` / provider "fallback-template" so the UI never
presents it as AI-generated. Templates were written for this project; they are not adaptations of
existing nursery rhymes.
"""

import hashlib
import random

from app.services.content.schemas import ContentBrief, SceneSpec, SEOMetadata

ANIMALS = [
    {"en": "cat", "hi": "बिल्ली", "sound_en": "Meow", "sound_hi": "म्याऊँ", "act_en": "chases a ball of string",
     "act_hi": "धागे की गेंद से खेले", "char": "cat", "bg": "garden"},
    {"en": "duck", "hi": "बत्तख", "sound_en": "Quack", "sound_hi": "क्वैक", "act_en": "paddles round the pond",
     "act_hi": "पानी में छप-छप तैरे", "char": "duck", "bg": "ocean"},
    {"en": "cow", "hi": "गाय", "sound_en": "Moo", "sound_hi": "मूँ", "act_en": "munches grass all day",
     "act_hi": "हरी घास चरती जाए", "char": "cow", "bg": "farm"},
    {"en": "elephant", "hi": "हाथी", "sound_en": "Pawoo", "sound_hi": "पों-पों", "act_en": "sprays water with its trunk",
     "act_hi": "सूँड से पानी बरसाए", "char": "elephant", "bg": "forest"},
    {"en": "frog", "hi": "मेंढक", "sound_en": "Ribbit", "sound_hi": "टर्र", "act_en": "hops from leaf to leaf",
     "act_hi": "पत्ते-पत्ते कूद लगाए", "char": "frog", "bg": "garden"},
    {"en": "owl", "hi": "उल्लू", "sound_en": "Hoo", "sound_hi": "हू-हू", "act_en": "blinks its big round eyes",
     "act_hi": "गोल-गोल आँखें मटकाए", "char": "owl", "bg": "night"},
    {"en": "monkey", "hi": "बंदर", "sound_en": "Ooh-ooh", "sound_hi": "ऊँ-ऊँ", "act_en": "swings from tree to tree",
     "act_hi": "डाल-डाल पर झूला झूले", "char": "monkey", "bg": "forest"},
]

COLORS = [
    {"en": "red", "hi": "लाल", "thing_en": "apple", "thing_hi": "सेब", "obj": "apple"},
    {"en": "yellow", "hi": "पीला", "thing_en": "sunshine", "thing_hi": "सूरज", "obj": "star"},
    {"en": "green", "hi": "हरा", "thing_en": "leafy tree", "thing_hi": "पेड़", "obj": "tree"},
    {"en": "blue", "hi": "नीला", "thing_en": "boat at sea", "thing_hi": "सागर", "obj": "boat"},
    {"en": "pink", "hi": "गुलाबी", "thing_en": "flower bloom", "thing_hi": "फूल", "obj": "flower"},
    {"en": "orange", "hi": "नारंगी", "thing_en": "juicy mango", "thing_hi": "आम", "obj": "mango"},
]

SHAPES = [
    {"en": "circle", "hi": "गोला", "desc_en": "round and round, no corners found", "desc_hi": "गोल-गोल, कोई कोना नहीं"},
    {"en": "square", "hi": "चौकोर", "desc_en": "four equal sides, neat and square", "desc_hi": "चार बराबर भुजाएँ"},
    {"en": "triangle", "hi": "त्रिकोण", "desc_en": "three straight sides, pointing high",
     "desc_hi": "तीन भुजाएँ, ऊपर नोक"},
    {"en": "star", "hi": "तारा", "desc_en": "five little points that shine", "desc_hi": "पाँच कोनों से चमके"},
    {"en": "heart", "hi": "दिल", "desc_en": "a shape that says I care", "desc_hi": "प्यार का प्यारा आकार"},
]

NUMBER_WORDS_HI = ["शून्य", "एक", "दो", "तीन", "चार", "पाँच", "छह", "सात", "आठ", "नौ", "दस"]
NUMBER_WORDS_EN = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
COUNT_THINGS = [
    {"en": "balloons", "hi": "गुब्बारे", "obj": "balloon"},
    {"en": "flowers", "hi": "फूल", "obj": "flower"},
    {"en": "stars", "hi": "तारे", "obj": "star"},
    {"en": "apples", "hi": "सेब", "obj": "apple"},
]

LETTERS = [
    ("A", "ant", "अ", "अनार"), ("B", "boat", "आ", "आम"), ("C", "cloud", "इ", "इमली"),
    ("D", "duck", "ई", "ईख"), ("E", "elephant", "उ", "उल्लू"), ("F", "frog", "ऊ", "ऊन"),
]

KINDNESS = [
    {"en": "share my toys with you", "hi": "खिलौने मिलकर खेलें", "obj": "ball"},
    {"en": "say thank you, please, and sorry too", "hi": "धन्यवाद और कृपया बोलें", "obj": "heart"},
    {"en": "help a friend who falls", "hi": "गिरे दोस्त को उठाएँ", "obj": "heart"},
    {"en": "give a hug to grandma", "hi": "दादी को गले लगाएँ", "obj": "flower"},
]


def _rng(*parts: str) -> random.Random:
    seed = int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:16], 16)
    return random.Random(seed)


def _verses(theme: str, language: str, rng: random.Random, topic: str) -> list[tuple[list[str], SceneSpec]]:
    """Returns (lines, scene) pairs. Language 'bilingual' interleaves English and Hindi lines."""
    hi = language == "hi"
    bi = language == "bilingual"
    out: list[tuple[list[str], SceneSpec]] = []

    def pick(lines_en: list[str], lines_hi: list[str]) -> list[str]:
        if bi:
            return [lines_en[0], lines_hi[1], lines_en[2], lines_hi[3]]
        return lines_hi if hi else lines_en

    if theme == "animals":
        for a in rng.sample(ANIMALS, 3):
            lines = pick(
                [f"Here comes the {a['en']}, hello, hello!", f"{a['sound_en']}, {a['sound_en']}, off we go!",
                 f"The {a['en']} {a['act_en']},", "and waves to you, so slow!"],
                [f"देखो आया {a['hi']}, नमस्ते, नमस्ते!", f"{a['sound_hi']}, {a['sound_hi']}, गाते हँसते!",
                 f"{a['hi']} {a['act_hi']},", "सबको प्यार से बुलाए रस्ते!"],
            )
            out.append((lines, SceneSpec(description=f"A friendly {a['en']} {a['act_en']}", lyric_lines=lines,
                                         duration_seconds=8, background=a["bg"], characters=[a["char"]],
                                         objects=["flower"], mood="playful")))
    elif theme == "colors":
        for c in rng.sample(COLORS, 3):
            lines = pick(
                [f"{c['en'].capitalize()}, {c['en']}, can you see?", f"A {c['en']} {c['thing_en']} waves at me!",
                 f"Point to {c['en']}, one, two, three,", f"{c['en'].capitalize()} is bright as bright can be!"],
                [f"{c['hi']}, {c['hi']}, देखो ज़रा,", f"{c['hi']} रंग का {c['thing_hi']} खड़ा!",
                 f"उँगली से छू लो {c['hi']} रंग,", "खेलें हम सब मिलकर संग!"],
            )
            out.append((lines, SceneSpec(description=f"A big {c['en']} {c['thing_en']} in the center",
                                         lyric_lines=lines, duration_seconds=8, background="meadow",
                                         objects=[c["obj"], f"color:{c['en']}"], mood="happy")))
    elif theme == "shapes":
        for s in rng.sample(SHAPES, 3):
            lines = pick(
                [f"I am a {s['en']}, look at me,", f"{s['desc_en'].capitalize()},",
                 f"Draw a {s['en']} in the air,", "Shapes are hiding everywhere!"],
                [f"मैं हूँ {s['hi']}, मुझको देखो,", f"{s['desc_hi']},",
                 f"हवा में {s['hi']} बनाओ,", "हर जगह आकार पाओ!"],
            )
            out.append((lines, SceneSpec(description=f"A smiling {s['en']} shape bouncing", lyric_lines=lines,
                                         duration_seconds=8, background="classroom",
                                         objects=[f"shape:{s['en']}"], mood="curious")))
    elif theme == "numbers":
        thing = rng.choice(COUNT_THINGS)
        start = rng.choice([1, 2, 3])
        for n in range(start, start + 3):
            lines = pick(
                [f"{NUMBER_WORDS_EN[n].capitalize()} little {thing['en']}, count with me,",
                 f"{', '.join(NUMBER_WORDS_EN[1:n + 1])}... yippee!",
                 f"Hold up {NUMBER_WORDS_EN[n]} fingers high,", "Counting makes the time fly by!"],
                [f"{NUMBER_WORDS_HI[n]} प्यारे {thing['hi']}, गिनो मेरे साथ,",
                 f"{', '.join(NUMBER_WORDS_HI[1:n + 1])}... वाह, क्या बात!",
                 f"{NUMBER_WORDS_HI[n]} उँगलियाँ ऊपर करो,", "गिनती से मन खुशियों से भरो!"],
            )
            out.append((lines, SceneSpec(description=f"{n} {thing['en']} appear one by one", lyric_lines=lines,
                                         duration_seconds=9, background="sky",
                                         objects=[f"number:{n}"] + [thing["obj"]] * min(n, 5), mood="playful")))
    elif theme == "alphabet":
        start = rng.randrange(0, len(LETTERS) - 2)
        for letter, word, hi_letter, hi_word in LETTERS[start:start + 3]:
            lines = pick(
                [f"{letter} is for {word}, say it with me,", f"{letter}, {letter}, {word}, easy as can be!",
                 f"Trace a big {letter} with your hand,", "Letters help us understand!"],
                [f"{hi_letter} से {hi_word}, बोलो साथ,", f"{hi_letter}, {hi_letter}, {hi_word}, सुंदर बात!",
                 f"हवा में {hi_letter} लिखो ज़रा,", "अक्षर-अक्षर ज्ञान भरा!"],
            )
            out.append((lines, SceneSpec(description=f"The letter {letter} next to a {word}", lyric_lines=lines,
                                         duration_seconds=8, background="classroom",
                                         objects=[f"letter:{letter}", "book"], mood="curious")))
    elif theme == "bedtime":
        steps = [("brush our teeth", "दाँत चमकाएँ"), ("hug our teddy tight", "टेडी को गले लगाएँ"),
                 ("close our eyes", "आँखें बंद करें")]
        for en, hi_ in steps:
            lines = pick(
                ["The moon is up, the sky is deep,", f"Now we {en} before we sleep,",
                 "Hush now, hush now, stars peep,", "Sweet dreams, my little sheep."],
                ["चंदा निकला, रात हुई,", f"अब हम {hi_}, बात हुई,",
                 "धीरे-धीरे तारे जागे,", "मीठे सपने आएँ आगे।"],
            )
            out.append((lines, SceneSpec(description=f"A sleepy child getting ready to {en}", lyric_lines=lines,
                                         duration_seconds=9, background="night", characters=["moon", "child"],
                                         objects=["star", "cloud"], mood="sleepy")))
    elif theme == "kindness":
        for k in rng.sample(KINDNESS, 3):
            lines = pick(
                ["Kind little hands, kind little heart,", f"Every day I {k['en']},",
                 "A smile is the very best start,", "Being kind is a kind of art!"],
                ["छोटे हाथ, बड़ा सा दिल,", f"आओ {k['hi']},",
                 "मुस्कान से सब जाएँ खिल,", "प्यार से रहें हम सब मिल!"],
            )
            out.append((lines, SceneSpec(description=f"Children learning to {k['en']}", lyric_lines=lines,
                                         duration_seconds=8, background="garden", characters=["child", "rabbit"],
                                         objects=[k["obj"]], mood="happy")))
    else:  # general / nature and anything else: a topic-driven nature walk
        places = [("meadow", "flower", "बगिया"), ("beach", "boat", "सागर किनारे"), ("forest", "tree", "जंगल")]
        for bg, obj, hi_place in rng.sample(places, 3):
            lines = pick(
                [f"Let's go walking to the {bg},", f"Singing of {topic[:30]} as we go,",
                 "Tap your toes and clap with me,", "What a happy world to see!"],
                [f"चलो घूमने {hi_place},", f"{hi_place} में गाएँ सारे,",
                 "ताली बजाओ, पैर थिरकाओ,", "दुनिया कितनी प्यारी, देखो आओ!"],
            )
            out.append((lines, SceneSpec(description=f"A cheerful walk through the {bg}", lyric_lines=lines,
                                         duration_seconds=8, background=bg, characters=["child", "bird"],
                                         objects=[obj], mood="happy")))
    return out


def _chorus(language: str) -> list[str]:
    if language == "hi":
        return ["ला-ला-ला, गाओ सब,", "ताली बजाओ, नाचो अब!"]
    if language == "bilingual":
        return ["La-la-la, sing along,", "ताली बजाओ, गाओ गाना!"]
    return ["La-la-la, sing along,", "Clap your hands and join the song!"]


def build_fallback_brief(*, topic: str, theme: str, language: str, video_format: str, target_age: str,
                         variant: int = 0) -> ContentBrief:
    rng = _rng(topic.lower(), theme, language, str(variant))
    verses = _verses(theme, language, rng, topic)
    chorus = _chorus(language)
    lyrics: list[str] = []
    scenes: list[SceneSpec] = [SceneSpec(
        description=f"Title card: {topic}", lyric_lines=[], duration_seconds=3,
        background=verses[0][1].background, characters=verses[0][1].characters[:1], objects=["star"], mood="happy",
    )]
    for i, (lines, scene) in enumerate(verses):
        lyrics.extend(lines)
        scenes.append(scene)
        if i < len(verses) - 1:
            lyrics.extend(chorus)
            scenes.append(SceneSpec(description="Chorus: everyone claps along", lyric_lines=chorus,
                                    duration_seconds=4, background="meadow", characters=["child", "bird"],
                                    objects=["balloon", "rainbow"], mood="playful"))
    if video_format == "short":
        # Keep Shorts comfortably under 60 seconds.
        while sum(s.duration_seconds for s in scenes) > 55 and len(scenes) > 3:
            scenes.pop(-2)
    duration = int(sum(s.duration_seconds for s in scenes))
    title_word = topic.strip().title()[:60]
    if language == "hi":
        title = f"{title_word} | बच्चों का गीत"
        desc = (f"{topic} पर एक नया, मौलिक बाल-गीत। बच्चे गाएँ, ताली बजाएँ और सीखें।\n\n"
                "Original song created for young children.")
    else:
        title = f"{title_word} Song for Kids"
        desc = (f"An original sing-along about {topic} for little learners aged {target_age}. "
                "Clap, count and sing together!")
    tags_lang = "#HindiRhymes" if language == "hi" else "#KidsSongs"
    return ContentBrief(
        title=title[:100],
        topic=topic,
        theme=theme,
        language=language,  # type: ignore[arg-type]
        target_age_range=target_age,
        objective=f"Introduce {theme} concepts through repetition and movement",
        story_concept=f"A gentle, repetitive sing-along about {topic} with clapping breaks.",
        lyrics=lyrics,
        storyboard=scenes,
        suggested_duration_seconds=max(duration, 10),
        aspect_ratio="9:16" if video_format == "short" else "16:9",
        audio_instructions="Slow, clear narration at a child-friendly pace; light original background melody.",
        metadata=SEOMetadata(title=title[:100], description=desc, hashtags=[tags_lang, "#NurseryRhymes"],
                             keywords=[topic, theme, "kids song", "nursery rhyme"],
                             thumbnail_text=title_word[:24] or "Sing Along",
                             thumbnail_design="Big friendly character, bright background, 2-4 words of text"),
        safety_flags=[],
        originality_notes="Deterministic local template (no AI provider was used).",
    )

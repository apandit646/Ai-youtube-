"""Render one of the example original rhymes to a local video + thumbnail without any external service.

Usage (from backend/):  python scripts_render_example.py [index] [--out ../examples/output] [--long]
Uses a throwaway SQLite database; requires FFmpeg on PATH.
"""

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("index", nargs="?", type=int, default=0)
parser.add_argument("--out", default=str(Path(__file__).resolve().parent.parent / "examples" / "output"))
parser.add_argument("--resolution", default="540x960", help="e.g. 1080x1920 for full HD Shorts")
args = parser.parse_args()

tmp = Path(tempfile.mkdtemp(prefix="rhymepilot-example-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tmp / 'example.db'}")
os.environ["DATABASE_URL"] = f"sqlite:///{tmp / 'example.db'}"
os.environ["MEDIA_ROOT"] = str(tmp / "media")

from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, get_engine  # noqa: E402
from app.models import RhymeScript, User  # noqa: E402
from app.models.enums import Language, VideoFormat  # noqa: E402
from app.services.content.originality import check_brief, content_hash  # noqa: E402
from app.services.content.schemas import ContentBrief  # noqa: E402
from app.services.content.service import _scene_model  # noqa: E402
from app.services.media.pipeline import MediaPipeline  # noqa: E402
from app.services.media.storage import safe_path  # noqa: E402
from app.services.projects import create_project  # noqa: E402
from app.services.settings_service import get_app_settings  # noqa: E402

examples = json.loads((Path(__file__).resolve().parent.parent / "examples" / "original_rhymes.json").read_text("utf-8"))
brief = ContentBrief.model_validate(examples[args.index])
report = check_brief(brief)
print("originality checks passed:", report["passed"])

Base.metadata.create_all(get_engine())
db = SessionLocal()
user = User(email="example@local", hashed_password="!")
db.add(user)
db.flush()
settings = get_app_settings(db, user.id)
settings.shorts_resolution = args.resolution
script = RhymeScript(owner_id=user.id, title=brief.title, language=Language(brief.language), topic=brief.topic,
                     theme=brief.theme, lyrics="\n".join(brief.lyrics), seo=brief.metadata.model_dump(),
                     originality_report=report, content_hash=content_hash(brief.lyrics), provider="example",
                     video_format=VideoFormat.SHORT if brief.aspect_ratio == "9:16" else VideoFormat.LONG)
script.scenes = [_scene_model(i, s) for i, s in enumerate(brief.storyboard)]
db.add(script)
db.flush()
project = create_project(db, user.id, settings, script=script, video_format=script.video_format)
pipe = MediaPipeline(db)
media = pipe.generate_media(project, script)
video = pipe.render(project, media)
result = pipe.validate(project, video, media["total_seconds"])
out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
stem = f"example_{args.index}"
shutil.copy(video, out / f"{stem}.mp4")
shutil.copy(safe_path(project.thumbnail_path), out / f"{stem}_thumbnail{Path(project.thumbnail_path).suffix}")
shutil.copy(safe_path(project.subtitles_path), out / f"{stem}.srt")
print("validation passed:", result["passed"])
print("warnings:", *project.quality_warnings, sep="\n  - ")
print("written to", out)

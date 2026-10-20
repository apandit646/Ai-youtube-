import wave

import pytest

from app.models import RhymeScript
from app.models.enums import AssetKind, Language, ProjectStatus, VideoFormat
from app.services.content.service import ContentService, GenerationRequest
from app.services.llm.router import LLMRouter
from app.services.media import ffmpeg
from app.services.media.audio import ProceduralMelodyProvider, SilentNarrationProvider, concat_wavs, wav_duration
from app.services.media.pipeline import CancelledError, MediaPipeline, build_srt, format_srt_time, parse_resolution
from app.services.media.storage import safe_path
from app.services.projects import create_project, dimensions_for
from app.services.settings_service import get_app_settings

pytestmark = pytest.mark.skipif(not ffmpeg.ffmpeg_available(), reason="FFmpeg not installed")


def _script(db, user, fmt=VideoFormat.SHORT, lang=Language.HINDI) -> RhymeScript:
    s = ContentService(db, user.id, LLMRouter({}), None).generate_script(
        GenerationRequest(topic="Farm friends", theme="animals", language=lang, video_format=fmt))
    db.commit()
    return s


def test_srt_and_resolution_helpers():
    assert format_srt_time(3661.5) == "01:01:01,500"
    srt = build_srt([(0, 4, ["line one", "line two"]), (4, 2, [])])
    assert "1\n00:00:00,000 --> 00:00:01,950\nline one" in srt and "2\n00:00:02,000" in srt
    assert parse_resolution("1081x1921") == (1080, 1920)
    with pytest.raises(ValueError):
        parse_resolution("10x10")


def test_audio_providers(tmp_path):
    clip = SilentNarrationProvider().synthesize("one two three four", "en", tmp_path / "n.wav")
    assert clip.is_placeholder and clip.duration >= 1.5
    music = ProceduralMelodyProvider().compose(3.0, tmp_path / "m.wav", seed=1)
    assert abs(wav_duration(music.path) - 3.0) < 0.05
    total = concat_wavs([(clip.path, 2.5), (None, 1.0)], tmp_path / "all.wav")
    assert abs(total - 3.5) < 0.01
    with wave.open(str(tmp_path / "all.wav")) as w:
        assert w.getnchannels() == 1


def test_orientation_is_enforced(db, user):
    s = get_app_settings(db, user.id)
    s.shorts_resolution = "1920x1080"  # wrong orientation typed by a user
    assert dimensions_for(s, VideoFormat.SHORT) == (1080, 1920)
    assert dimensions_for(s, VideoFormat.LONG) == (480, 270)


@pytest.mark.parametrize("fmt", [VideoFormat.SHORT, VideoFormat.LONG])
def test_full_render_produces_valid_playable_video(db, user, fast_providers, fmt):
    script = _script(db, user, fmt)
    settings = get_app_settings(db, user.id)
    project = create_project(db, user.id, settings, script=script, video_format=fmt)
    pipe = MediaPipeline(db, fast_providers)
    media = pipe.generate_media(project, script)
    video = pipe.render(project, media)
    result = pipe.validate(project, video, media["total_seconds"])
    assert result["passed"], result
    info = ffmpeg.probe(video)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (v["width"], v["height"]) == ((270, 480) if fmt == VideoFormat.SHORT else (480, 270))
    kinds = {a.kind for a in project.assets}
    assert {AssetKind.SCENE_IMAGE, AssetKind.NARRATION, AssetKind.MUSIC, AssetKind.SUBTITLES, AssetKind.THUMBNAIL,
            AssetKind.VIDEO} <= kinds
    assert safe_path(project.thumbnail_path).exists()
    assert "-->" in safe_path(project.subtitles_path).read_text(encoding="utf-8")
    assert any("SILENT" in w for w in project.quality_warnings)  # placeholder audio is disclosed


def test_validation_detects_wrong_dimensions(db, user, fast_providers):
    script = _script(db, user)
    project = create_project(db, user.id, get_app_settings(db, user.id), script=script, video_format=VideoFormat.SHORT)
    pipe = MediaPipeline(db, fast_providers)
    media = pipe.generate_media(project, script)
    video = pipe.render(project, media)
    project.width, project.height = 1080, 1920
    result = pipe.validate(project, video, media["total_seconds"])
    assert not result["passed"]
    assert not next(c for c in result["checks"] if c["name"] == "dimensions")["passed"]


def test_cancellation_between_scenes(db, user, fast_providers):
    script = _script(db, user)
    project = create_project(db, user.id, get_app_settings(db, user.id), script=script, video_format=VideoFormat.SHORT)
    pipe = MediaPipeline(db, fast_providers, is_cancelled=lambda: True)
    with pytest.raises(CancelledError):
        pipe.generate_media(project, script)
    assert project.status == ProjectStatus.PENDING


def test_safe_path_blocks_traversal():
    from app.core.errors import AppError

    with pytest.raises(AppError):
        safe_path("../../etc/passwd")
    with pytest.raises(AppError):
        safe_path("/etc/passwd")

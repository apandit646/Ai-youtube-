from datetime import UTC, datetime, timedelta

import pytest

from app.core.errors import AppError, ConfigurationError, ConflictError, InvalidStateError
from app.core.security import encrypt_secret
from app.models import ConnectedYouTubeChannel, PublishedVideo, PublishingJob, RhymeScript
from app.models.enums import JobStatus, Language, ProjectStatus, PublishStatus, VideoFormat
from app.services import jobs
from app.services.media.storage import project_dir, relative
from app.services.projects import create_project
from app.services.publishing import (
    PublishBlocked,
    PublishingService,
    PublishRequest,
    create_publishing_job,
    next_publish_slot,
    validate_metadata,
)
from app.services.settings_service import get_app_settings
from app.services.youtube.client import YouTubeAPIError, YouTubeQuotaError
from app.services.youtube.uploader import build_video_resource
from app.workers.handlers import run_job


class FakeUploader:
    def __init__(self, fail_with: Exception | None = None):
        self.fail_with = fail_with
        self.sessions = 0
        self.uploads = 0
        self.resources = []

    def start_session(self, resource, size):
        self.sessions += 1
        self.resources.append(resource)
        return "https://upload.example/session/1"

    def upload(self, path, uri, progress=None, resume=False):
        self.uploads += 1
        if self.fail_with:
            raise self.fail_with
        res = self.resources[-1] if self.resources else {"status": {"privacyStatus": "private"}}
        return {"id": f"vid{self.uploads:08d}", "snippet": {"channelId": "UC123", "title": "t"},
                "status": {**res["status"], "uploadStatus": "uploaded"}}

    def set_thumbnail(self, video_id, path):
        raise YouTubeAPIError("forbidden: account not verified", status_code=403)

    def close(self):
        pass


@pytest.fixture
def ready(db, user):
    script = RhymeScript(owner_id=user.id, title="Puddle Parade", language=Language.ENGLISH, topic="rain",
                         lyrics="a\nb\nc\nd", content_hash="x", originality_report={"passed": True},
                         seo={"title": "Puddle Parade Song", "description": "An original song.",
                              "hashtags": ["#KidsSongs"], "keywords": ["rain", "colours"], "thumbnail_text": "Rain"})
    db.add(script)
    db.flush()
    s = get_app_settings(db, user.id)
    s.timezone = "UTC"
    p = create_project(db, user.id, s, script=script, video_format=VideoFormat.SHORT)
    video = project_dir(p.id) / "video.mp4"
    video.write_bytes(b"\x00" * 2048)
    p.output_path = relative(video)
    thumb = project_dir(p.id) / "thumbnail.png"
    thumb.write_bytes(b"\x89PNG")
    p.thumbnail_path = relative(thumb)
    p.status = ProjectStatus.READY
    p.validation = {"passed": True}
    db.add(ConnectedYouTubeChannel(owner_id=user.id, channel_id="UC123", title="My Kids Channel",
                                   encrypted_access_token=encrypt_secret("ya29.test"),
                                   encrypted_refresh_token=encrypt_secret("refresh"),
                                   token_expires_at=datetime.now(UTC) + timedelta(hours=1)))
    db.commit()
    return p


def test_video_resource_sets_kids_and_schedule():
    r = build_video_resource(title="T", description="D", tags=["a"], category_id="27", language="bilingual",
                             privacy_status="public", publish_at="2030-01-01T10:00:00Z", made_for_kids=True)
    assert r["status"] == {"privacyStatus": "private", "selfDeclaredMadeForKids": True, "embeddable": True,
                           "license": "youtube", "publishAt": "2030-01-01T10:00:00Z"}
    assert r["snippet"]["defaultLanguage"] == "hi"


def test_metadata_validation():
    assert validate_metadata("ok", "fine", ["x"]) == []
    assert validate_metadata("", "<b>", ["t" * 501])  # several errors


def test_next_slot_respects_window_cap_and_days(db, user):
    s = get_app_settings(db, user.id)
    s.timezone, s.publish_window_start_hour, s.publish_window_end_hour, s.max_uploads_per_day = "UTC", 17, 19, 2
    tomorrow = datetime.now(UTC).date() + timedelta(days=1)
    s.publish_days = [tomorrow.weekday()]
    after = datetime.combine(tomorrow, datetime.min.time(), UTC)
    first = next_publish_slot(db, s, after=after)
    assert first.date() == tomorrow and first.hour == 17
    for t in (first, first + timedelta(hours=1)):
        db.add(PublishingJob(owner_id=user.id, project_id=_dummy_project(db, user).id, title="x", publish_at=t,
                             status=PublishStatus.SCHEDULED, idempotency_key=f"k{t.timestamp()}"))
    db.flush()
    nxt = next_publish_slot(db, s, after=after)
    assert nxt.date() == tomorrow + timedelta(days=7)  # only that weekday is allowed and the day is full


def _dummy_project(db, user):
    return create_project(db, user.id, get_app_settings(db, user.id), script=None, video_format=VideoFormat.SHORT)


def test_publishing_guards(db, user, ready):
    s = get_app_settings(db, user.id)
    s.dry_run = False
    with pytest.raises(PublishBlocked, match="private test upload"):
        create_publishing_job(db, ready, s, PublishRequest())
    s.paused = True
    with pytest.raises(PublishBlocked, match="paused"):
        create_publishing_job(db, ready, s, PublishRequest(is_test_upload=True))
    s.paused = False
    pj = create_publishing_job(db, ready, s, PublishRequest(is_test_upload=True))
    assert pj.privacy_status == "private" and pj.made_for_kids and "#KidsSongs" in pj.description
    with pytest.raises(ConflictError):
        create_publishing_job(db, ready, s, PublishRequest(is_test_upload=True))
    with pytest.raises(AppError, match="15 minutes"):
        s.private_test_passed_at = datetime.now(UTC)
        create_publishing_job(db, ready, s, PublishRequest(publish_at=datetime.now(UTC)))
    ready.status = ProjectStatus.PENDING
    with pytest.raises(InvalidStateError):
        create_publishing_job(db, ready, s, PublishRequest(is_test_upload=False))


def test_no_channel_required_only_outside_dry_run(db, user, ready):
    db.query(ConnectedYouTubeChannel).delete()
    s = get_app_settings(db, user.id)
    s.dry_run = False
    with pytest.raises(ConfigurationError):
        create_publishing_job(db, ready, s, PublishRequest(is_test_upload=True))
    s.dry_run = True
    assert create_publishing_job(db, ready, s, PublishRequest()).dry_run


def test_dry_run_never_calls_youtube(db, user, ready):
    s = get_app_settings(db, user.id)
    assert s.dry_run  # default
    pj = create_publishing_job(db, ready, s, PublishRequest(is_test_upload=True))
    up = FakeUploader()
    PublishingService(db, uploader_factory=lambda t: up).execute(pj, s)
    assert pj.status == PublishStatus.DRY_RUN and up.sessions == 0
    assert s.private_test_passed_at is None  # a dry run doesn't count as a real test


def test_private_test_upload_then_scheduled_publish(db, user, ready):
    s = get_app_settings(db, user.id)
    s.dry_run = False
    up = FakeUploader()
    svc = PublishingService(db, uploader_factory=lambda t: up)
    test = create_publishing_job(db, ready, s, PublishRequest(is_test_upload=True))
    svc.execute(test, s)
    assert test.status == PublishStatus.UPLOADED_PRIVATE and s.private_test_passed_at is not None
    assert "thumbnail" in test.last_error  # non-fatal thumbnail failure surfaced
    assert ready.status == ProjectStatus.READY  # test uploads don't advance the project

    when = datetime.now(UTC) + timedelta(days=1)
    pj = create_publishing_job(db, ready, s, PublishRequest(publish_at=when))
    svc.execute(pj, s)
    assert pj.status == PublishStatus.SCHEDULED and ready.status == ProjectStatus.SCHEDULED
    assert up.resources[-1]["status"]["publishAt"].startswith(when.strftime("%Y-%m-%dT%H:%M"))
    pv = db.query(PublishedVideo).filter_by(publishing_job_id=pj.id).one()
    assert pv.youtube_video_id == "vid00000002"
    # Idempotency: executing again does not upload twice.
    svc.execute(pj, s)
    assert up.uploads == 2


def _run_upload(db, user, ready, uploader, test=False):
    s = get_app_settings(db, user.id)
    s.dry_run = False
    s.private_test_passed_at = datetime.now(UTC)
    pj = create_publishing_job(db, ready, s, PublishRequest(is_test_upload=test, privacy_status="public"))
    db.commit()
    job = run_job(db, jobs.claim_next(db, "t"), uploader_factory=lambda t: uploader)
    db.refresh(pj)
    return job, pj


def test_transient_upload_error_requeues_and_keeps_session(db, user, ready):
    job, pj = _run_upload(db, user, ready, FakeUploader(YouTubeAPIError("backend error", status_code=503,
                                                                         retryable=True)))
    assert job.status == JobStatus.QUEUED and pj.status == PublishStatus.QUEUED
    assert pj.resumable_session_uri  # resume next time instead of re-inserting
    assert db.get(type(ready), ready.id).status == ProjectStatus.UPLOADING


def test_permanent_upload_error_fails_project(db, user, ready):
    job, pj = _run_upload(db, user, ready, FakeUploader(YouTubeAPIError("invalid title", status_code=400)))
    assert job.status == JobStatus.FAILED and pj.status == PublishStatus.FAILED
    project = db.get(type(ready), ready.id)
    assert project.status == ProjectStatus.FAILED and "invalid title" in project.error


def test_quota_exhaustion_defers_until_reset(db, user, ready):
    job, pj = _run_upload(db, user, ready, FakeUploader(YouTubeQuotaError("quota", reason="quotaExceeded")))
    assert job.status == JobStatus.QUEUED
    assert job.run_after > datetime.now(UTC) + timedelta(minutes=5)


def test_public_upload_result_reflects_api_confirmation(db, user, ready):
    job, pj = _run_upload(db, user, ready, FakeUploader())
    assert job.status == JobStatus.SUCCEEDED and pj.status == PublishStatus.PUBLISHED
    assert job.result["youtube_video_id"] == "vid00000001"

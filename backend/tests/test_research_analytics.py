from datetime import UTC, date, datetime, timedelta

import httpx

from app.core.security import encrypt_secret
from app.models import (
    AnalyticsSnapshot,
    CompetitorVideoSnapshot,
    ConnectedYouTubeChannel,
    PublishedVideo,
    PublishingJob,
    ResearchQuery,
)
from app.models.enums import JobKind, JobStatus, ResearchType, VideoFormat
from app.services import jobs
from app.services.analytics.service import (
    AnalyticsCollector,
    compare,
    generate_recommendations,
    statistical_recommendations,
    video_table,
)
from app.services.projects import create_project
from app.services.research.service import (
    ResearchService,
    classify_format,
    compute_observations,
    detect_language,
    detect_topics,
    snapshot_from_item,
)
from app.services.settings_service import get_app_settings
from app.workers.handlers import run_job


def _item(vid, title, views, days_ago, duration="PT45S", desc=""):
    published = (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": vid, "snippet": {"title": title, "description": desc, "channelId": "UCc", "channelTitle": "Comp",
                                   "publishedAt": published},
            "contentDetails": {"duration": duration},
            "statistics": {"viewCount": str(views), "likeCount": "10", "commentCount": "0"}}


def test_classifiers():
    assert detect_language("हाथी राजा का गाना") == "hi"
    assert detect_language("Elephant song for kids") == "en"
    assert detect_language("Machli jal ki rani hai") == "hi"  # romanised Hindi
    assert detect_language("Elephant हाथी song गाना for kids बच्चे") == "bilingual"
    assert classify_format(45, "") == "short" and classify_format(150, "#Shorts") == "short"
    assert classify_format(150, "") == "long" and classify_format(None, "") == "unknown"
    assert set(detect_topics("Counting animals 1 2 3 गिनती")) >= {"animals", "numbers"}


def test_snapshot_derived_metrics():
    snap = snapshot_from_item(_item("a", "Cat song", 1000, 10), datetime.now(UTC))
    assert 99 <= snap["views_per_day"] <= 101
    assert snap["engagement_rate"] == 0.01 and snap["video_format"] == "short"
    no_stats = _item("b", "x", 0, 1)
    no_stats["statistics"] = {}
    s2 = snapshot_from_item(no_stats, datetime.now(UTC))
    assert s2["view_count"] is None and s2["views_per_day"] is None  # never fabricated


class FakeYT:
    quota_used = 101

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def search_videos(self, q, **kw):
        assert kw["video_duration"] == "short"
        return ["a", "b", "c"]

    def videos(self, ids):
        return [_item("a", "हाथी गीत", 5000, 5), _item("b", "Counting song", 200, 20),
                _item("c", "Long story", 9000, 30, duration="PT10M")]


def test_research_run_stores_snapshots_and_report(db, user):
    q = ResearchQuery(owner_id=user.id, query_type=ResearchType.TOPIC, query_text="rhymes",
                      filters={"video_format": "short", "min_views": 100})
    db.add(q)
    db.commit()
    report = ResearchService(db, user.id, None, yt_factory=FakeYT).run(q)
    assert q.status == JobStatus.SUCCEEDED and q.result_count == 2 and q.quota_units_used == 101
    obs = report.observations
    assert obs["video_count"] == 2 and "by_language" in obs and obs["data_limits"]
    assert report.ai_summary is None and "no AI provider" in report.error
    assert db.query(CompetitorVideoSnapshot).count() == 2


def test_observations_empty():
    assert compute_observations([])["video_count"] == 0


def test_research_job_without_credentials_fails_cleanly(db, user):
    q = ResearchQuery(owner_id=user.id, query_type=ResearchType.TOPIC, query_text="rhymes", filters={})
    db.add(q)
    db.flush()
    jobs.enqueue(db, user.id, JobKind.RESEARCH, {"query_id": q.id})
    db.commit()
    job = run_job(db, jobs.claim_next(db, "t"))
    assert job.status == JobStatus.FAILED and "YOUTUBE_API_KEY" in job.error
    db.refresh(q)
    assert q.status == JobStatus.FAILED


def _published(db, user, n, language, topic, views):
    s = get_app_settings(db, user.id)
    for i in range(n):
        p = create_project(db, user.id, s, script=None, video_format=VideoFormat.SHORT)
        pj = PublishingJob(owner_id=user.id, project_id=p.id, title="t", idempotency_key=f"{language}{topic}{i}")
        db.add(pj)
        db.flush()
        vid = f"{language}{topic}{i}"[:11]
        db.add(PublishedVideo(owner_id=user.id, publishing_job_id=pj.id, project_id=p.id, youtube_video_id=vid,
                              privacy_status="public", language=language, topic=topic, video_format="short",
                              duration_seconds=40))
        db.add(AnalyticsSnapshot(owner_id=user.id, scope="video", youtube_video_id=vid, day=date.today(),
                                 metrics={"views": views + i, "averageViewPercentage": 70.0}))
    db.flush()


def test_compare_and_statistical_recommendations(db, user):
    _published(db, user, 3, "hi", "animals", 900)
    _published(db, user, 3, "en", "colors", 300)
    rows = video_table(db, user.id)
    assert len(rows) == 6 and rows[0]["impressions"] is None and rows[0]["ctr"] is None
    stats = compare(db, user.id)
    assert stats["by_language"][0]["group"] == "hi"
    recs = statistical_recommendations(stats)
    lang = next(r for r in recs if r["category"] == "language")
    assert "hi" in lang["title"] and lang["confidence"] == "low"  # n=3 per group
    created = generate_recommendations(db, user.id, None)
    assert all(r.source == "statistics" for r in created)


def test_recommendations_with_no_data_ask_for_more_data(db, user):
    recs = statistical_recommendations(compare(db, user.id))
    assert len(recs) == 1 and recs[0]["category"] == "general"


def test_analytics_collector_with_mocked_api(db, user):
    db.add(ConnectedYouTubeChannel(owner_id=user.id, channel_id="UC1", encrypted_access_token=encrypt_secret("t"),
                                   token_expires_at=datetime.now(UTC) + timedelta(hours=1)))
    _published(db, user, 1, "hi", "animals", 10)

    def handler(req: httpx.Request):
        p = req.url.params
        if req.url.host == "youtubeanalytics.googleapis.com":
            dims = p.get("dimensions")
            if dims == "day":
                return httpx.Response(200, json={"columnHeaders": [{"name": "day"}, {"name": "views"},
                                                                   {"name": "averageViewDuration"}],
                                                 "rows": [["2026-10-01", 50, 30], ["2026-10-02", 70, 32]]})
            if dims == "insightTrafficSourceType":
                return httpx.Response(200, json={"columnHeaders": [{"name": "insightTrafficSourceType"},
                                                                   {"name": "views"}], "rows": [["SHORTS", 100]]})
            if dims == "video":
                return httpx.Response(200, json={"columnHeaders": [{"name": "video"}, {"name": "views"}],
                                                 "rows": [["hianimals0", 123]]})
            return httpx.Response(403, json={"error": {"message": "Forbidden for made-for-kids content"}})
        return httpx.Response(200, json={"items": [{"id": "hianimals0", "statistics": {"viewCount": "130"},
                                                    "status": {"privacyStatus": "public"}}]})

    c = AnalyticsCollector(db, user.id, "token", transport=httpx.MockTransport(handler))
    summary = c.collect()
    c.close()
    assert summary["channel_days"] == 2 and summary["videos"] == 1
    assert any("retention" in e for e in summary["errors"])  # unavailable data is reported, not invented
    assert video_table(db, user.id)[0]["views"] == 123

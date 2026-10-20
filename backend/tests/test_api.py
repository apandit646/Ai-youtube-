import pytest

from app.core.security import create_access_token
from app.models import Job
from app.models.enums import JobStatus
from app.services import jobs
from app.services.media import ffmpeg
from app.workers.handlers import run_job


def test_health_is_public_and_hides_secrets(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    assert body["components"]["database"] is True
    assert "secret" not in r.text.lower().replace("default_secret_key", "")


def test_openapi_docs(client):
    r = client.get("/api/v1/openapi.json")
    assert r.status_code == 200 and "/api/v1/videos/{project_id}/upload" in r.json()["paths"]


def test_register_once_then_login(client):
    assert client.get("/api/v1/auth/setup-status").json() == {"needs_owner": True}
    r = client.post("/api/v1/auth/register", json={"email": "Me@Example.com", "password": "a-strong-passphrase"})
    assert r.status_code == 201 and r.json()["access_token"]
    assert client.get("/api/v1/auth/setup-status").json() == {"needs_owner": False}
    r2 = client.post("/api/v1/auth/register", json={"email": "x@example.com", "password": "another-passphrase"})
    assert r2.status_code == 403
    assert client.post("/api/v1/auth/login", json={"email": "me@example.com", "password": "wrong"}).status_code == 401
    tok = client.post("/api/v1/auth/login", json={"email": "me@example.com",
                                                   "password": "a-strong-passphrase"}).json()["access_token"]
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()
    assert me["email"] == "me@example.com"


def test_weak_password_rejected(client):
    r = client.post("/api/v1/auth/register", json={"email": "a@b.co", "password": "short"})
    assert r.status_code == 422 and r.json()["error"] == "validation_error"


@pytest.mark.parametrize("path", ["/api/v1/dashboard", "/api/v1/settings", "/api/v1/videos", "/api/v1/content",
                                  "/api/v1/jobs", "/api/v1/analytics/overview", "/api/v1/publishing/calendar"])
def test_protected_routes_require_auth(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_settings_roundtrip_and_validation(client, auth):
    r = client.get("/api/v1/settings", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["settings"]["dry_run"] is True and body["settings"]["made_for_kids_default"] is True
    assert {p["provider"] for p in body["providers"]} == {"grok", "openai", "gemini"}
    r = client.put("/api/v1/settings", headers=auth, json={"timezone": "Mars/Base"})
    assert r.status_code == 422
    r = client.put("/api/v1/settings", headers=auth, json={"publish_window_start_hour": 20,
                                                           "publish_window_end_hour": 10})
    assert r.status_code == 400
    r = client.put("/api/v1/settings", headers=auth, json={"dry_run": False, "auto_publish_enabled": True})
    assert r.status_code == 400 and "private test upload" in r.json()["detail"]
    r = client.put("/api/v1/settings", headers=auth, json={"llm_routing": {"script": ["gemini", "grok"]},
                                                           "timezone": "Asia/Kolkata"})
    assert r.status_code == 200 and r.json()["llm_routing"]["script"] == ["gemini", "grok"]


def test_api_keys_are_write_only(client, auth):
    r = client.put("/api/v1/settings/api-keys", headers=auth,
                   json={"provider": "grok", "api_key": "xai-supersecretvalue1234", "model": "grok-test-model"})
    assert r.status_code == 200
    grok = next(p for p in r.json() if p["provider"] == "grok")
    assert grok["configured"] and grok["key_hint"] == "…1234" and grok["model"] == "grok-test-model"
    full = client.get("/api/v1/settings", headers=auth).text
    assert "supersecret" not in full
    r = client.delete("/api/v1/settings/api-keys/grok", headers=auth)
    assert not next(p for p in r.json() if p["provider"] == "grok")["configured"]


def test_research_requires_youtube_credentials(client, auth):
    r = client.post("/api/v1/research/search", headers=auth, json={"query": "nursery rhymes"})
    assert r.status_code == 412 and r.json()["error"] == "not_configured"


def test_ideas_require_ai_provider(client, auth):
    r = client.post("/api/v1/content/ideas", headers=auth, json={"count": 3})
    assert r.status_code == 412


@pytest.mark.skipif(not ffmpeg.ffmpeg_available(), reason="FFmpeg not installed")
def test_content_to_video_workflow(client, auth, db, user, fast_providers):
    r = client.post("/api/v1/content/generate", headers=auth,
                    json={"topic": "Colourful kites", "theme": "colors", "language": "en"})
    assert r.status_code == 202
    job_id = r.json()["job"]["id"]
    run_job(db, jobs.claim_next(db, "t"))
    job = client.get(f"/api/v1/jobs/{job_id}", headers=auth).json()
    assert job["status"] == "SUCCEEDED" and job["result"]["is_fallback"] is True
    script_id = job["result"]["script_id"]
    script = client.get(f"/api/v1/content/{script_id}", headers=auth).json()
    assert script["provider"] == "fallback-template" and script["scenes"]

    # Edit lyrics → re-validated and approval reset
    r = client.put(f"/api/v1/content/{script_id}", headers=auth,
                   json={"lyrics": script["lyrics"] + "\nOne more happy line!", "approved": True})
    assert r.status_code == 200 and r.json()["approved"] is True
    bad = client.put(f"/api/v1/content/{script_id}", headers=auth,
                     json={"lyrics": "Twinkle twinkle little star\nhow I wonder\nwhat you are\nup above"})
    assert bad.status_code == 200 and bad.json()["originality_report"]["passed"] is False
    assert client.put(f"/api/v1/content/{script_id}", headers=auth, json={"approved": True}).status_code == 409
    client.put(f"/api/v1/content/{script_id}", headers=auth, json={"lyrics": script["lyrics"]})

    r = client.post("/api/v1/videos", headers=auth, json={"script_id": script_id})
    assert r.status_code == 201
    project_id = r.json()["project"]["id"]
    job = db.get(Job, r.json()["job"]["id"])
    run_job(db, jobs.claim_next(db, "t"), providers=fast_providers)
    db.refresh(job)
    assert job.status == JobStatus.SUCCEEDED, job.error
    detail = client.get(f"/api/v1/videos/{project_id}", headers=auth).json()
    assert detail["status"] == "READY" and detail["has_video"] and detail["validation"]["passed"]

    token = client.get(f"/api/v1/videos/{project_id}/media-token", headers=auth).json()["token"]
    f = client.get(f"/api/v1/videos/{project_id}/file/video", params={"token": token})
    assert f.status_code == 200 and f.headers["content-type"] == "video/mp4"
    assert client.get(f"/api/v1/videos/{project_id}/file/video", params={"token": "bad"}).status_code == 401
    assert client.get(f"/api/v1/videos/{project_id}/file/thumbnail", params={"token": token}).status_code == 200

    # Dry-run test upload (default settings) never contacts YouTube
    r = client.post(f"/api/v1/videos/{project_id}/upload", headers=auth, json={"test": True})
    assert r.status_code == 202 and r.json()["dry_run"] is True
    run_job(db, jobs.claim_next(db, "t"))
    queue = client.get("/api/v1/publishing/queue", headers=auth, params={"include_done": True}).json()
    assert queue[0]["status"] == "DRY_RUN" and queue[0]["youtube_video_id"] is None

    dash = client.get("/api/v1/dashboard", headers=auth).json()
    assert dash["projects_by_status"]["READY"] == 1 and dash["analytics"]["has_data"] is False

    assert client.delete(f"/api/v1/videos/{project_id}/media", headers=auth).status_code == 400
    r = client.delete(f"/api/v1/videos/{project_id}/media", headers=auth, params={"confirm": True})
    assert r.status_code == 200 and r.json()["deleted_bytes"] > 0


def test_cross_user_authorization(client, auth, db, user, other_user):
    r = client.post("/api/v1/content/generate", headers=auth, json={"topic": "Moon", "theme": "bedtime"})
    job_id = r.json()["job"]["id"]
    run_job(db, jobs.claim_next(db, "t"))
    script_id = client.get(f"/api/v1/jobs/{job_id}", headers=auth).json()["result"]["script_id"]
    intruder = {"Authorization": f"Bearer {create_access_token(str(other_user.id))}"}
    assert client.get(f"/api/v1/content/{script_id}", headers=intruder).status_code == 404
    assert client.get(f"/api/v1/jobs/{job_id}", headers=intruder).status_code == 404
    assert client.post(f"/api/v1/jobs/{job_id}/cancel", headers=intruder).status_code == 404
    assert client.post("/api/v1/videos", headers=intruder, json={"script_id": script_id}).status_code == 404
    assert client.get("/api/v1/content", headers=intruder).json()["total"] == 0


def test_pause_resume_and_run(client, auth):
    assert client.post("/api/v1/automation/pause", headers=auth).json()["paused"] is True
    r = client.post("/api/v1/automation/run", headers=auth)
    assert r.status_code == 409
    assert client.post("/api/v1/automation/resume", headers=auth).json()["paused"] is False
    r = client.post("/api/v1/automation/run", headers=auth)
    assert r.status_code == 202 and r.json()["kind"] == "pipeline"
    cancelled = client.post(f"/api/v1/jobs/{r.json()['id']}/cancel", headers=auth).json()
    assert cancelled["status"] == "CANCELLED"


def test_youtube_endpoints_without_connection(client, auth):
    assert client.get("/api/v1/youtube/channel", headers=auth).json()["connected"] is False
    r = client.get("/api/v1/youtube/auth", headers=auth)
    assert r.status_code == 200 and r.json()["auth_url"].startswith("https://accounts.google.com/")
    cb = client.get("/api/v1/youtube/callback", params={"code": "x", "state": "forged"}, follow_redirects=False)
    assert cb.status_code == 302 and "invalid_state" in cb.headers["location"]
    assert client.post("/api/v1/youtube/revoke", headers=auth).status_code == 404
    assert client.post("/api/v1/analytics/refresh", headers=auth).status_code == 412


def test_analytics_empty_states_are_explicit(client, auth):
    ov = client.get("/api/v1/analytics/overview", headers=auth).json()
    assert ov["has_data"] is False and ov["note"] and "impressionsClickThroughRate" in ov["unavailable_metrics"]
    assert client.get("/api/v1/analytics/videos", headers=auth).json()["total"] == 0
    r = client.post("/api/v1/recommendations/generate", headers=auth)
    assert r.status_code == 202

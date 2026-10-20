#!/usr/bin/env python3
"""RhymePilot AI smoke test (stdlib only).

Checks backend health, database connectivity, the media toolchain, frontend availability and required
configuration. With --e2e it also signs in (or creates the owner on a fresh install), generates a rhyme,
renders a video through the background worker and performs a dry-run test upload. It never publishes
anything to YouTube: --e2e refuses to run unless dry-run mode is enabled.

Usage:
  python scripts/smoke_test.py [--frontend http://localhost:8080] [--api http://localhost:8000]
  python scripts/smoke_test.py --e2e --email owner@example.com --password '...'
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

OK, WARN, FAIL = "\033[32m✔\033[0m", "\033[33m!\033[0m", "\033[31m✘\033[0m"
failures = 0


def report(ok: bool | None, label: str, detail: str = "") -> None:
    global failures
    mark = OK if ok else (WARN if ok is None else FAIL)
    if ok is False:
        failures += 1
    print(f" {mark} {label}" + (f" — {detail}" if detail else ""))


def request(base: str, path: str, method: str = "GET", body: dict | None = None, token: str | None = None,
            timeout: float = 15) -> tuple[int, dict | str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read().decode(), exc.code
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        return 0, str(exc)
    try:
        return status, json.loads(raw)
    except json.JSONDecodeError:
        return status, raw


def basic_checks(api: str, frontend: str) -> None:
    print("Backend")
    status, health = request(api, "/api/v1/health")
    report(status == 200, "API reachable", f"{api} → HTTP {status}" if status else str(health))
    if status != 200 or not isinstance(health, dict):
        return
    comps, conf = health["components"], health["configuration"]
    report(comps["database"], "Database connectivity")
    report(comps["ffmpeg"], "FFmpeg available")
    report(comps["media_volume_writable"], "Media volume writable")
    report(comps["tts"] or None, "Local TTS (espeak-ng)", "" if comps["tts"] else "narration will be silent")
    print("Configuration")
    report(not conf["default_secret_key"], "SECRET_KEY changed from default")
    report(conf["ai_provider_env"] or None, "AI provider in environment",
           "" if conf["ai_provider_env"] else "none in env (keys may still be set in Settings)")
    report(conf["google_oauth"] or None, "Google OAuth client configured",
           "" if conf["google_oauth"] else "YouTube connect/upload disabled until set")
    report(conf["youtube_api_key"] or None, "YOUTUBE_API_KEY for research",
           "" if conf["youtube_api_key"] else "research will use the connected channel's OAuth token")
    print("Frontend")
    status, body = request(frontend, "/")
    report(status == 200 and "RhymePilot" in str(body), "Frontend serves the app", f"{frontend} → HTTP {status}")
    status, body = request(frontend, "/api/v1/health")
    report(status == 200, "Frontend proxies /api to the backend", f"HTTP {status}")


def e2e(api: str, email: str, password: str) -> None:
    print("End-to-end (dry run)")
    _, setup = request(api, "/api/v1/auth/setup-status")
    path = "/api/v1/auth/register" if isinstance(setup, dict) and setup.get("needs_owner") else "/api/v1/auth/login"
    status, tok = request(api, path, "POST", {"email": email, "password": password, "display_name": "Smoke Test"})
    report(status in (200, 201), "Authenticate", f"{path} → HTTP {status}")
    if status not in (200, 201):
        return
    token = tok["access_token"]
    _, settings = request(api, "/api/v1/settings", token=token)
    if not settings["settings"]["dry_run"]:
        report(False, "Dry-run mode", "disabled — refusing to run the e2e test against a live channel")
        return
    report(True, "Dry-run mode enabled")
    status, gen = request(api, "/api/v1/content/generate", "POST", {
        "topic": "Smoke test sing-along", "theme": "shapes", "language": "hi", "video_format": "short",
        "auto_render": True}, token=token)
    report(status == 202, "Queue generate + render job", f"HTTP {status}")
    if status != 202:
        return
    job_id = gen["job"]["id"]
    deadline = time.time() + 600
    job: dict = {}
    while time.time() < deadline:
        _, job = request(api, f"/api/v1/jobs/{job_id}", token=token)
        if job.get("status") in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(3)
    report(job.get("status") == "SUCCEEDED", "Worker generated script and rendered video",
           f"{job.get('status')} steps={[s['step'] for s in job.get('steps', [])]} {job.get('error') or ''}")
    if job.get("status") != "SUCCEEDED":
        return
    project_id = job["result"]["project_id"]
    _, video = request(api, f"/api/v1/videos/{project_id}", token=token)
    report(video["validation"].get("passed"), "Technical validation",
           f"{video['width']}x{video['height']} {video['duration_seconds']}s, provider={job['result']['provider']}")
    status, pj = request(api, f"/api/v1/videos/{project_id}/upload", "POST", {"test": True}, token=token)
    report(status == 202 and pj.get("dry_run"), "Queue dry-run test upload", f"HTTP {status}")
    for _ in range(40):
        _, video = request(api, f"/api/v1/videos/{project_id}", token=token)
        states = [p["status"] for p in video["publishing_jobs"]]
        if "DRY_RUN" in states or "FAILED" in states:
            break
        time.sleep(1.5)
    report("DRY_RUN" in states, "Dry-run upload recorded without contacting YouTube", str(states))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--frontend", default="http://localhost:8080")
    p.add_argument("--e2e", action="store_true", help="also run a full dry-run generate → render → upload test")
    p.add_argument("--email", default="owner@example.com")
    p.add_argument("--password", default="")
    args = p.parse_args()
    basic_checks(args.api, args.frontend)
    if args.e2e:
        if len(args.password) < 10:
            print("--e2e needs --password (min 10 chars) for the owner account")
            return 2
        e2e(args.api, args.email, args.password)
    print(f"\n{'All checks passed' if failures == 0 else f'{failures} check(s) failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

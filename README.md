# RhymePilot AI

Automation platform for **original Hindi and English baby-rhyme videos** on YouTube. It researches public trends, writes original rhymes with a multi-model AI layer (**Grok**, **ChatGPT** and **Gemini**), renders Shorts (9:16) and long-form (16:9) videos with Pillow and FFmpeg, uploads and schedules them through the official YouTube Data API, and analyses your own channel's results.

> RhymePilot does not promise views, virality, rankings or income. It measures what actually happens and makes recommendations from your stored metrics.

---

## Architecture

```mermaid
flowchart LR
  subgraph Browser
    UI[React + Vite dashboard]
  end
  subgraph Docker Compose
    NGINX[frontend: nginx<br/>static SPA + /api proxy]
    API[api: FastAPI<br/>REST /api/v1, JWT auth]
    W[worker: job runner + APScheduler]
    DB[(PostgreSQL 16)]
    VOL[(media volume<br/>videos, images, audio)]
  end
  subgraph External APIs
    GROK[xAI Grok]
    OAI[OpenAI ChatGPT]
    GEM[Google Gemini]
    YTD[YouTube Data API v3]
    YTA[YouTube Analytics API v2]
    GOA[Google OAuth 2.0]
  end
  UI --> NGINX --> API
  API --> DB
  API --> VOL
  W --> DB
  W --> VOL
  W -- FFmpeg / Pillow / espeak-ng --> VOL
  W --> GROK & OAI & GEM
  W --> YTD & YTA
  API --> GOA
```

* **API** (FastAPI): validates requests, enforces ownership on every resource and enqueues work. It never renders or uploads inside a request.
* **Worker**: a PostgreSQL-backed job queue (`SELECT … FOR UPDATE SKIP LOCKED`) plus APScheduler for periodic tasks: daily automation, analytics every 6 hours, stale-job recovery. Redis/Celery are **not** used. For a single-channel MVP the database queue is durable, observable, retryable and cancellable without adding another service.
* **Media** lives on a persistent volume. Only paths and metadata are stored in PostgreSQL.

### Pipeline (state machine)

`PENDING → RESEARCHING → SCRIPTING → GENERATING_MEDIA → RENDERING → VALIDATING → READY → UPLOADING → SCHEDULED/PUBLISHED`, with terminal `FAILED`/`CANCELLED` states and safe retries. A retry resumes from scripting, media generation, or "ready to upload", depending on where the failure happened. Each job records its steps with timestamps, errors and attempt counts, and you can cancel it between steps.

1. Research public trends (Data API) and store timestamped snapshots
2. Compute transparent observations, plus an optional AI interpretation labelled as hypotheses
3. Generate ideas grounded in those observations
4. Write an original brief (lyrics, storyboard, audio notes, SEO) with structured JSON validated by Pydantic
5. Originality, safety and structure gate (known rhymes, brands, unsafe words, engagement bait, 3-gram similarity against your catalogue and researched videos), then an optional **cross-model review** by a different provider
6. Scene art (Pillow), narration (TTS provider), original melody, FFmpeg render, SRT subtitles, thumbnail
7. Technical validation (ffprobe: dimensions, codec, duration, audio, decodability, size)
8. Publishing policy, then resumable upload, then `publishAt` scheduling, recording the YouTube video ID
9. Analytics collection, comparisons and recommendations

### Multi-model AI

| Task | Default order | Notes |
|---|---|---|
| Ideas, lyrics/storyboard, metadata | Grok → ChatGPT → Gemini | Grok is the primary creative model |
| Trend analysis, recommendations | Grok → Gemini → ChatGPT | Only summarises supplied numbers |
| Independent review | Gemini → ChatGPT → Grok | Always a *different* provider from the generator |

* Every call uses JSON mode, is parsed and validated against a Pydantic schema, and is repaired once if the output is malformed. If a provider fails (timeout, 429, 5xx, invalid output), the next configured provider is tried.
* Retries use exponential backoff and respect `Retry-After`; timeouts are configurable.
* You can change the routing per task in **Settings → AI models**.
* **Model names are never assumed.** Set them in `.env` or in the UI.
* If no provider is available, deterministic local templates are used. They are always labelled `fallback-template` / `is_fallback=true` and never presented as AI output.

---

## Quick start (Docker)

Prerequisites: Docker 24+ with Compose v2.

```bash
cp .env.example .env
# Edit .env: at minimum set SECRET_KEY and POSTGRES_PASSWORD
python3 -c "import secrets; print(secrets.token_urlsafe(48))"   # → SECRET_KEY

docker compose up -d --build
docker compose ps                         # db, api, worker, frontend should become healthy
python3 scripts/smoke_test.py             # health, DB, FFmpeg, frontend, configuration
```

Open **http://localhost:8080**, create the owner account (registration closes after the first account), and follow the setup wizard. The API docs are at http://localhost:8000/api/docs.

The full dry-run end-to-end check generates a rhyme, renders it in the worker and records a dry-run upload. It refuses to run if dry-run mode is off:

```bash
python3 scripts/smoke_test.py --e2e --email you@example.com --password 'your-owner-password'
```

### Services and ports

| Service | Port | Purpose |
|---|---|---|
| `frontend` | `${FRONTEND_PORT:-8080}` | nginx serving the SPA and proxying `/api` (including SSE) |
| `api` | `${API_PORT:-8000}` | FastAPI; runs `alembic upgrade head` on start |
| `worker` | – | background jobs and schedules; heartbeat on the media volume |
| `db` | – (internal) | PostgreSQL 16, volume `pgdata` |

All application containers run as non-root users and have health checks. Secrets are only passed at runtime through `.env`; nothing is baked into images.

---

## Configuration

### AI providers

Set any of these in `.env`, or paste keys in **Settings → AI models**. Keys entered in the UI are encrypted with Fernet in the database and are write-only: the browser only ever sees `…last4`.

```
XAI_API_KEY=...      XAI_MODEL=<model id from console.x.ai>
OPENAI_API_KEY=...   OPENAI_MODEL=<chat model id that supports JSON mode>
GEMINI_API_KEY=...   GEMINI_MODEL=<Gemini model id>
```

Use **Test** next to each provider to make one tiny live call and verify the key and model name.

### YouTube OAuth (to connect the channel, upload, and read analytics)

1. In [Google Cloud Console](https://console.cloud.google.com/) create a project and enable **YouTube Data API v3** and **YouTube Analytics API**.
2. Configure the **OAuth consent screen** (External, add yourself as a test user) with scopes `youtube.upload`, `youtube.readonly` and `yt-analytics.readonly`.
3. Create an **OAuth client ID** of type *Web application*. Add the authorised redirect URI exactly:
   `http://localhost:8080/api/v1/youtube/callback` (or your public URL plus `/api/v1/youtube/callback`).
4. Put the values in `.env`: `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI`, and set `FRONTEND_URL` to the dashboard URL. Then run `docker compose up -d`.
5. In **Settings → YouTube**, click **Connect YouTube** and choose the channel owner's account.
6. Optional: create an **API key** for public research and set `YOUTUBE_API_KEY`. Without it, research uses the connected channel's OAuth token.

**Important platform limits**

* Videos uploaded by **unverified** API projects are locked to *private* until the project passes Google's API audit. Plan for this before going live.
* The default quota is 10,000 units/day. An upload costs about 1,600 units and a search about 100. RhymePilot tracks quota use per research query, defers uploads after `quotaExceeded` until the Pacific-time reset, and enforces your *max uploads per day*.
* `publishAt` scheduling only works for private videos, and RhymePilot sets that automatically. A status is shown as scheduled or published **only after the API confirms it**.

### Publishing safety rails

* **Dry-run mode is on by default.** Uploads are validated and recorded, but YouTube is never called.
* **A private test upload must succeed** before scheduling, publishing or auto-publishing can be enabled.
* **Global pause** stops new uploads and automated runs and cancels queued uploads. Videos already scheduled on YouTube keep their time, so change those in YouTube Studio.
* **Made for Kids** is on by default (`selfDeclaredMadeForKids=true`, category Education). No engagement-bait phrases are allowed in generated text.
* Idempotency: at most one active upload per project (enforced by a unique key). The resumable session URI is persisted before bytes are sent, so a crash resumes the upload instead of creating a duplicate.
* **Revoke access** under Settings → YouTube → *Disconnect & revoke*. This revokes the token at Google and deletes local tokens. You can also remove access at https://myaccount.google.com/permissions.

---

## Local development (without Docker)

```bash
# Backend (Python 3.12+, PostgreSQL, FFmpeg; optional: espeak-ng, fonts-noto-core)
cd backend
python3.12 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
export DATABASE_URL=postgresql+psycopg://rhymepilot:rhymepilot@localhost:5432/rhymepilot
alembic upgrade head
uvicorn app.main:app --reload            # API on :8000
python -m app.workers.main               # worker (second terminal)

# Frontend
cd frontend && npm install && npm run dev   # http://localhost:5173 (proxies /api to :8000)
```

For local OAuth, set `GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/api/v1/youtube/callback` and `FRONTEND_URL=http://localhost:5173`.

### Example render (no services required)

```bash
cd backend && python scripts_render_example.py 0 --resolution 1080x1920
# → examples/output/example_0.mp4, example_0_thumbnail.png, example_0.srt
```

`examples/original_rhymes.json` contains hand-written original sample briefs in Hindi and English. These are the same structure the AI must produce.

---

## Tests

```bash
cd backend && ruff check . && pytest -q                     # 132 tests, SQLite by default
TEST_DATABASE_URL=postgresql+psycopg://.../rhymepilot_test pytest -q   # same suite on PostgreSQL
cd frontend && npx tsc -b && npx vitest run && npx vite build
```

The tests cover settings validation, password hashing/JWT/encryption/log redaction, LLM JSON parsing, retries, fallback and repair, routing and cross-review, rhyme generation and fallback templates, the originality gate, real FFmpeg renders and validation (Shorts and long-form), job-state transitions, queue claim/retry/cancel/stale recovery, scheduling slots, the publishing guards and dry run, mocked YouTube uploads with resume/5xx/quota/permanent errors, OAuth exchange/refresh/revoke, research parsing and observations, analytics collection and recommendations, API authentication and cross-user authorisation, Alembic upgrade/check/downgrade, and React components and pages. **No test calls a real external service or publishes anything.** CI (`.github/workflows/ci.yml`) runs all of this, builds the images and runs the end-to-end smoke test.

---

## Operations

```bash
docker compose logs -f api worker           # structured JSON logs (secrets redacted)
docker compose restart worker
docker compose exec api alembic upgrade head          # migrations (also run on api start)
docker compose exec api alembic revision --autogenerate -m "change"   # new migration (dev)
docker compose down                          # stop (volumes kept)

# Backups
docker compose exec -T db pg_dump -U rhymepilot rhymepilot | gzip > backups/db-$(date +%F).sql.gz
docker run --rm -v rhymepilot_media:/data -v "$PWD/backups":/b alpine tar czf /b/media-$(date +%F).tgz -C /data .
# Restore
gunzip -c backups/db-YYYY-MM-DD.sql.gz | docker compose exec -T db psql -U rhymepilot rhymepilot
```

**Production deployment:** put the `frontend` service behind HTTPS (for example Caddy, Traefik, or a cloud load balancer), set `ENVIRONMENT=production` (the API refuses to start with the default `SECRET_KEY`), a strong `POSTGRES_PASSWORD`, a dedicated `TOKEN_ENCRYPTION_KEY`, your public `FRONTEND_URL`, `GOOGLE_OAUTH_REDIRECT_URI` and `CORS_ORIGINS`, and keep the API port private if nginx is the only entry point.

### Troubleshooting

| Symptom | Fix |
|---|---|
| Dashboard says *Background worker not detected* | `docker compose ps worker` / `docker compose logs worker`. Jobs stay queued without it. |
| *Google OAuth is not configured* | Set the three `GOOGLE_OAUTH_*` variables and restart `api`. |
| `redirect_uri_mismatch` from Google | The redirect URI in Google Cloud must exactly match `GOOGLE_OAUTH_REDIRECT_URI`. |
| Uploads stay private | Unverified API project. Request an audit from Google. |
| Job deferred with *YouTube quota* | Quota is exhausted. It retries automatically after midnight Pacific time. |
| *invalid_grant* / reconnect | The refresh token was revoked or expired (test-mode consent screens expire after 7 days). Reconnect the channel. |
| Hindi text shows boxes | The image needs `fonts-noto-core` and `libraqm0` (included in the Docker image). |
| Narration is silent | `espeak-ng` is not installed (included in the Docker image). The UI and API flag this. |
| AI fails with HTTP 404/400 | Check the model name with **Settings → Test**. |

---

## What's implemented and the known limitations

See **[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)**.

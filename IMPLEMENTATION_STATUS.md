# Implementation status

Status as of this commit. ✅ means implemented and covered by automated tests or the end-to-end smoke test.

## Implemented

### Platform
- ✅ FastAPI backend: versioned `/api/v1` routes, Pydantic request/response schemas, central error handling, OpenAPI at `/api/docs`
- ✅ SQLAlchemy 2 models for all required entities (User, AppSettings, ConnectedYouTubeChannel, ResearchQuery, CompetitorVideoSnapshot, TrendReport, ContentIdea, RhymeScript, StoryboardScene, MediaAsset, VideoProject, PublishingJob, PublishedVideo, AnalyticsSnapshot, Recommendation, AuditLog) plus `Job` for the durable queue. Includes FKs, indexes, unique constraints and string-backed enums.
- ✅ Alembic initial migration. Tested with upgrade, `alembic check` (models and migration match) and downgrade.
- ✅ Single-owner auth (PBKDF2 password hashing, JWT with expiry). Registration closes after the first account. Every resource is ownership-checked (cross-user access returns 404).
- ✅ Secrets: API keys and OAuth tokens are Fernet-encrypted at rest and write-only towards the UI. Logs are JSON with redaction of keys and tokens.
- ✅ DB-backed worker queue with `SKIP LOCKED`, retries with exponential backoff, cancellation, stale-job recovery, dedupe keys and a heartbeat. APScheduler handles daily automation and 6-hourly analytics.
- ✅ Docker Compose (db, api, worker, frontend), non-root images, health checks, persistent volumes, `.env.example`
- ✅ CI workflow: lint, tests on SQLite and PostgreSQL, frontend type-check, tests and build, Docker build and e2e smoke test
- ✅ `scripts/smoke_test.py`: health, DB, FFmpeg, media volume, configuration, frontend and proxy; `--e2e` dry-run pipeline

### AI (multi-model)
- ✅ Grok (xAI), ChatGPT (OpenAI) and Gemini providers over HTTP with timeouts, retries, `Retry-After` handling and clear error messages
- ✅ Per-task routing with automatic fallback, a schema-repair round, configurable models (never hardcoded) and a live "Test" button
- ✅ Cross-model review: a different provider rates originality, safety and age-appropriateness
- ✅ Labelled deterministic fallback templates (8 themes × Hindi/English/bilingual)

### Content
- ✅ Ideas grounded in research observations
- ✅ Structured brief: lyrics, storyboard constrained to the drawable vocabulary, audio notes, SEO metadata (≤5 hashtags), safety flags
- ✅ Originality/safety gate: known rhymes, third-party brands, unsafe terms, engagement bait, URLs, structure, similarity to own catalogue and to researched competitors. Failing drafts are retried, then fall back or are rejected.
- ✅ Editing with re-validation, approval workflow, per-section regeneration (lyrics, storyboard, metadata)
- ✅ Stored prompt (versioned), provider, model, fallback flag and timestamps

### Research
- ✅ Topic search and channel-uploads lookup via the official Data API. Filters: language, date, format, minimum views, order. Quota accounting.
- ✅ Derived metrics (views/day, engagement), heuristic language, format and topic labels, timestamped snapshots
- ✅ Observations computed only from data, plus an optional AI summary split into observations, hypotheses and caveats

### Media
- ✅ Pluggable providers: Pillow procedural visuals (10 backgrounds, 16 characters, objects, numbers, letters, shapes, colours), espeak-ng narration (or labelled silent fallback), an original procedurally composed melody
- ✅ FFmpeg render per scene (character bounce/sway overlay, fades), concat, audio mix, 9:16 and 16:9, configurable resolution, fps and volumes
- ✅ SRT subtitles, burned-in lyric captions, 1280×720 thumbnail (correct Devanagari shaping with libraqm and Noto)
- ✅ ffprobe validation: streams, dimensions, codec, duration, Shorts length, size, decode test, thumbnail, subtitles
- ✅ Placeholder-quality warnings are stored per video and shown in the UI

### Publishing
- ✅ OAuth 2.0 (signed `state`, offline access, token refresh, revoke), channel status
- ✅ Resumable `videos.insert` with resume-after-error, persisted session URI (no duplicate uploads), thumbnail upload (non-fatal), Made for Kids, category, language
- ✅ Private test upload gate, dry-run mode (default on), global pause, publishing window/day/cap slot allocation, daily upload limit, deferral on quota errors, reschedule and cancel of queued items
- ✅ Status recorded only from the API response (`SCHEDULED` / `PUBLISHED` / `UPLOADED_PRIVATE`)

### Analytics
- ✅ YouTube Analytics v2: daily channel metrics, traffic sources, lifetime per-video metrics, retention curves (where exposed), plus public counters from the Data API
- ✅ Unavailable metrics (impressions, CTR) are explicitly labelled, never estimated
- ✅ Comparisons by language, topic, format, duration and publish hour. Transparent statistical recommendations with confidence by sample size. Optional AI recommendations whose confidence is capped on small samples. Accept/dismiss only records the decision and never changes settings.

### Dashboard (React, TypeScript, Vite, Tailwind, shadcn-style UI, TanStack Query, Recharts)
- ✅ Login / owner setup, setup wizard, Dashboard, Research Studio, Content Studio and script editor, Video Library (preview, download, retry, delete media, test upload, schedule), Publishing Calendar, Analytics, Settings (AI keys and routing, YouTube, publishing, automation, rendering, system status, audit log)
- ✅ Loading, empty and error states, toasts, pagination, live job progress with cancel and retry, accessible labels

## Known limitations (by design for the zero-budget MVP)
- **Media quality:** visuals are procedural flat cartoons with simple motion, narration is robotic espeak-ng speech (spoken, not sung), and the music is a simple synthesised tune. The provider interfaces (`VisualProvider`, `NarrationProvider`, `MusicProvider`) are where licensed TTS, singing or animation services plug in.
- **Captions** are burned into the video and exported as SRT, but not uploaded to YouTube (`captions.insert` needs the broader `youtube.force-ssl` scope).
- **Already-uploaded** videos cannot be rescheduled or paused from RhymePilot (that needs `videos.update` with a broader scope). Use YouTube Studio.
- **Impressions and CTR** are not collected (not available through the Analytics API queries used here). They are labelled as such.
- **No title/thumbnail A/B experiments** are recorded, so comparisons are observational only.
- **Single owner** per installation (the data model is per-owner throughout, ready for multi-user).
- Google may keep uploads private until the API project passes its audit. Quota limits roughly 6 uploads per day on the default quota.

## Verified in this environment
- Backend: 132 tests pass on SQLite and on PostgreSQL 16; `ruff` clean
- Frontend: type-check, 11 tests and the production build pass
- Docker Compose: all four services healthy; `smoke_test.py --e2e` passed (1080×1920 Hindi Short rendered with espeak-ng narration in the worker; dry-run upload recorded)
- Not verified here: real Grok/OpenAI/Gemini calls and real YouTube OAuth, upload and analytics. No credentials are available, so these paths are covered by mocked-HTTP tests only.

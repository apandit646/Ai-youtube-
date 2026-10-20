export type Language = "hi" | "en" | "bilingual";
export type VideoFormat = "short" | "long";
export type JobStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";

export interface Page<T> { items: T[]; total: number; page: number; page_size: number }

export interface Job {
  id: number; kind: string; status: JobStatus; project_id: number | null; payload: Record<string, unknown>;
  result: Record<string, any> | null; step: string | null; progress: number;
  steps: { step: string; status: string; started_at: string; finished_at?: string; error?: string }[];
  error: string | null; attempts: number; max_attempts: number; cancel_requested: boolean; run_after: string;
  started_at: string | null; finished_at: string | null; created_at: string;
}

export interface ProviderStatus { provider: string; label: string; configured: boolean; model: string | null; key_source: string | null; key_hint: string | null }

export interface AppSettings {
  default_language: Language; default_format: VideoFormat; default_target_age: string; timezone: string;
  publish_window_start_hour: number; publish_window_end_hour: number; max_uploads_per_day: number; publish_days: number[];
  made_for_kids_default: boolean; default_privacy: string; youtube_category_id: string; automation_enabled: boolean;
  auto_publish_enabled: boolean; paused: boolean; dry_run: boolean; private_test_passed_at: string | null;
  llm_routing: Record<string, string[]>; llm_models: Record<string, string>; cross_model_review: boolean;
  shorts_resolution: string; long_resolution: string; fps: number; music_volume: number; narration_volume: number;
  setup_completed: boolean;
}

export interface SettingsResponse {
  settings: AppSettings; providers: ProviderStatus[]; tasks: string[];
  youtube: { oauth_configured: boolean; api_key_configured: boolean };
  media: { ffmpeg: boolean; tts: boolean; fonts: string[]; devanagari_font: string | null; raqm: boolean };
}

export interface Scene { id: number; order_index: number; description: string; lyric_text: string; duration_seconds: number; visual: { background?: string; characters?: string[]; objects?: string[]; mood?: string } }

export interface OriginalityCheck { name: string; passed: boolean; detail: string; blocking?: boolean }

export interface ScriptSummary {
  id: number; title: string; language: Language; topic: string; theme: string; video_format: VideoFormat; provider: string;
  model: string; is_fallback: boolean; approved: boolean; safety_flags: string[]; created_at: string; updated_at: string;
}

export interface Script extends ScriptSummary {
  target_age: string; objective: string; story_concept: string; lyrics: string; audio_instructions: string;
  suggested_duration_seconds: number;
  seo: { title?: string; description?: string; hashtags?: string[]; keywords?: string[]; thumbnail_text?: string; thumbnail_design?: string };
  originality_report: { passed?: boolean; checks?: OriginalityCheck[]; warnings?: string[]; attempts?: { provider: string; ok: boolean; error?: string }[] };
  review: { approved?: boolean; originality_score?: number; issues?: string[]; suggestions?: string[]; provider?: string; skipped?: boolean; reason?: string } | null;
  prompt: string; scenes: Scene[];
}

export interface Idea { id: number; topic: string; theme: string; language: Language; video_format: VideoFormat; target_age: string; objective: string; rationale: string; status: string; provider: string | null; created_at: string }

export interface PublishingJob {
  id: number; project_id: number; status: string; privacy_status: string; publish_at: string | null; title: string;
  made_for_kids: boolean; is_test_upload: boolean; dry_run: boolean; attempts: number; last_error: string | null;
  upload_progress: number; job_id: number | null; created_at: string; youtube_video_id: string | null;
  project_title?: string; date?: string;
}

export interface Asset { id: number; kind: string; path: string; mime_type: string; size_bytes: number; width: number | null; height: number | null; duration_seconds: number | null; provider: string; is_placeholder: boolean }

export interface Project {
  id: number; script_id: number | null; title: string; video_format: VideoFormat; width: number; height: number; fps: number;
  status: string; status_history: { from: string; to: string; at: string; note?: string }[]; error: string | null;
  duration_seconds: number | null; file_size_bytes: number | null; validation: { passed?: boolean; checks?: OriginalityCheck[] };
  quality_warnings: string[]; has_video: boolean; has_thumbnail: boolean; language: Language | null;
  publication: PublishingJob | null; created_at: string; updated_at: string;
}

export interface ProjectDetail extends Project { assets: Asset[]; publishing_jobs: PublishingJob[] }

export interface Snapshot {
  id: number; research_query_id: number; video_id: string; channel_id: string; channel_title: string; title: string;
  published_at: string | null; duration_seconds: number | null; view_count: number | null; like_count: number | null;
  comment_count: number | null; views_per_day: number | null; engagement_rate: number | null; language: string;
  video_format: string; topics: string[]; captured_at: string;
}

export interface ResearchQuery { id: number; query_type: string; query_text: string; filters: Record<string, unknown>; status: string; result_count: number; quota_units_used: number; error: string | null; created_at: string }

export interface TrendReport {
  id: number; research_query_id: number | null; observations: Record<string, any>; provider: string | null; model: string | null; error: string | null; created_at: string;
  ai_summary: { summary: string; observations: string[]; hypotheses: string[]; opportunities: { topic: string; language: string; format: string; why: string }[]; caveats: string[] } | null;
}

export interface Recommendation { id: number; category: string; title: string; body: string; supporting_data: Record<string, any>; confidence: string; source: string; status: string; created_at: string }

export type Level = 'A1' | 'A2' | 'B1' | 'B2' | 'C1' | 'C2'
export type CardKind = 'listening' | 'phrase' | 'cloze' | 'knowledge'
export type TemplateId = 'immersive' | 'dictionary' | 'minimal'
export type Provider = 'local' | 'mimo' | 'openai-compatible' | 'claude' | 'gemini'
export type TtsProvider = 'disabled' | 'mimo' | 'grok' | 'gemini' | 'openai-compatible'
export type SourceMode = 'local' | 'url' | 'document'
export type UrlImportMode = 'video' | 'subtitles'
export type SettingsTab = 'api' | 'tts' | 'env'
export type SegmentFilter = 'all' | 'recommended' | 'needs_review' | 'reject' | 'duplicate'
export type PhraseReviewStatus = 'recommended' | 'needs_review' | 'reject' | 'duplicate' | 'unreviewed' | string
export type ResizeDirection =
  | 'East'
  | 'North'
  | 'NorthEast'
  | 'NorthWest'
  | 'South'
  | 'SouthEast'
  | 'SouthWest'
  | 'West'

export type ContentToggles = {
  daily: boolean
  slang: boolean
  sarcasm: boolean
  business: boolean
  culture: boolean
  profanity: boolean
  romance: boolean
  rare: boolean
}

export type ApiConfig = {
  provider: Provider
  base_url: string
  api_key: string
  model: string
  capabilities: string[]
  tts_provider?: string
  tts_model?: string
  tts_config: TtsConfig
}

export type TtsConfig = {
  enabled: boolean
  provider: TtsProvider
  base_url: string
  api_key: string
  model: string
  voice: string
  language: string
  sample_rate: number
  bit_rate: number
}

export type ApiPreset = {
  id: string
  label: string
  provider: Provider
  base_url: string
  model: string
  capabilities: string[]
  note: string
  key_hint: string
}

export type TtsPreset = {
  id: string
  label: string
  provider: TtsProvider
  base_url: string
  model: string
  voice: string
  note: string
  key_hint: string
}

export type ApiTestResult = {
  ok: boolean
  provider: string
  model: string
  message: string
  latency_ms?: number
}

export type TtsTestResult = {
  ok: boolean
  provider: string
  model: string
  voice: string
  message: string
  latency_ms?: number
  bytes?: number
}

export type ExportResult = {
  apkg_path: string
  media_dir: string
  deck_name?: string
  media_prefix?: string
  media_manifest?: Record<string, { sha256: string; bytes: number }>
  cards: number
  segments: number
  media_summary?: {
    video_segments: number
    video_files: number
    original_audio_files: number
    sentence_tts_files: number
    phrase_tts_files: number
    media_files: number
    media_bytes: number
    media_mb: number
  }
  warnings?: string[]
}

export type AnkiVerifyResult = {
  ok: boolean
  message: string
  failed_checks: string[]
  deck_name?: string
  card_count?: number
  expected_cards?: number | null
  media_count_expected?: number
  media_count_referenced?: number
  media_count_checked?: number
  missing_media?: string[]
  mismatched_media?: Array<{ file: string; expected_sha256: string; actual_sha256: string }>
  unexpected_media_references?: string[]
  unreferenced_expected_media?: string[]
}

export type WorkerProgress = {
  job_id?: string
  command: string
  stage: string
  percent: number
  message: string
}

export type WorkerCommand = 'generate' | 'export' | 'verify_anki_import'

export type WorkerErrorCode =
  | 'ENV_PYTHON_MISSING'
  | 'ENV_FFMPEG_MISSING'
  | 'YOUTUBE_RATE_LIMIT'
  | 'YOUTUBE_N_CHALLENGE'
  | 'YOUTUBE_SUBTITLE_UNAVAILABLE'
  | 'MODEL_AUTH_FAILED'
  | 'MODEL_TIMEOUT'
  | 'MODEL_JSON_INVALID'
  | 'TTS_AUTH_FAILED'
  | 'TTS_TIMEOUT'
  | 'FFMPEG_SLICE_FAILED'
  | 'ANKI_EXPORT_FAILED'
  | 'ANKI_VERIFY_FAILED'
  | 'WORKER_CANCELLED'
  | 'WORKER_TIMEOUT'

export type WorkerJob = {
  job_id: string
}

export type WorkerOperation = {
  status: 'idle' | 'running' | 'cancelling' | 'succeeded' | 'failed'
  command?: WorkerCommand
  jobId?: string
}

export type ResponsiveMode = 'wide' | 'medium' | 'compact'
export type InspectorState = 'open' | 'collapsed' | 'sheet'

export type QualityFunnel = {
  subtitle_cues?: number
  candidate_segments?: number
  reviewed_keep?: number
  mimo_kept?: number
  recommended_cards?: number
  review_cards?: number
  rejected_cards?: number
  rejected_segments?: number
  duplicate_segments?: number
  average_phrase_score?: number | null
  short_reason?: string
}

export type WorkerFinishedEvent = {
  job_id: string
  command: WorkerCommand
  ok: boolean
  result?: unknown
  error?: string
  error_code?: WorkerErrorCode | string
  stage?: string
  retryable?: boolean
  fallbacks?: string[]
  cancelled?: boolean
}

export type EnvStatusItem = {
  id: string
  label: string
  status: 'ok' | 'action' | 'blocked'
  detail: string
  fix?: string
}

export type GenerateRequest = {
  title: string
  source_mode: SourceMode
  source_url: string
  url_import_mode: UrlImportMode
  url_auto_subtitle_fallback: boolean
  skip_video_slicing: boolean
  video_path: string
  subtitle_path: string
  document_path: string
  language: string
  level: Level
  collection_levels: Level[]
  template_id: TemplateId
  content_toggles: ContentToggles
  card_types: CardKind[]
  max_segments: number
  api_config: ApiConfig
}

export type Card = {
  id: string
  type: CardKind
  type_label: string
  enabled: boolean
  card_role?: 'primary' | 'specialist' | string
  learning_goal?: string
  decision_reason?: string
  skipped_card_types?: Record<string, string>
  phrase_value_score?: number | string | null
  phrase_decision_reason?: string
  phrase_reject_reason?: string
  phrase_card_focus?: string
  phrase_review_status?: PhraseReviewStatus
  english: string
  chinese: string
  phrase: string
  definition: string
  collocations: string
  context: string
  example: string
  chinese_feel: string
  why: string
  difficulty: string
  teacher_note: string
  cloze: string
  quality?: {
    score: number
    status: 'recommended' | 'needs_review' | 'reject'
    issues: string[]
  }
}

export type Segment = {
  id: string
  start: number
  end: number
  media_start?: number
  media_end?: number
  media_source_time?: string
  source_time: string
  text: string
  duration: number
  recommendation: number
  phrase: string
  phrase_value_score?: number | string | null
  phrase_decision_reason?: string
  phrase_reject_reason?: string
  phrase_card_focus?: string
  phrase_review_status?: PhraseReviewStatus
  phrase_review_source?: string
  cards: Card[]
}

export type Project = {
  schema_version?: number
  id: string
  title: string
  source_mode?: SourceMode
  source_url?: string
  source_info?: {
    title?: string
    webpage_url?: string
    duration?: number
    uploader?: string
    download_dir?: string
  } | null
  video_path: string
  subtitle_path: string
  document_path?: string
  language: string
  level: Level
  collection_levels?: Level[]
  template_id: TemplateId
  content_toggles: ContentToggles
  card_types: CardKind[]
  max_segments?: number
  auto_max_segments?: boolean
  skip_video_slicing?: boolean
  quality_funnel?: QualityFunnel
  segments: Segment[]
  warnings?: string[]
  error_code?: WorkerErrorCode | string
  stage?: string
  retryable?: boolean
  fallbacks?: string[]
  warning?: string | null
  created_at: number
}

export type EnvStatus = {
  python?: string
  python_executable?: string
  venv?: boolean
  ffmpeg?: boolean
  ffmpeg_path?: string
  ffmpeg_version?: string
  genanki?: boolean
  yt_dlp?: boolean
  yt_dlp_version?: string
  yt_dlp_js_runtime?: string
  anki_connect?: boolean
  anki_connect_detail?: string
  packages?: Record<string, string>
  status_items?: EnvStatusItem[]
  worker?: string
}

export type SecretPrefs = {
  rememberModelKey: boolean
  rememberTtsKey: boolean
}

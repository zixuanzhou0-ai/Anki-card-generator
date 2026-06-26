import type { BatchSourceItem } from './batch'

export type Level = 'A1' | 'A2' | 'B1' | 'B2' | 'C1' | 'C2'
export type LevelMode = 'auto' | 'manual'
export type CardKind = 'listening' | 'phrase' | 'cloze' | 'knowledge'
export type LearningLanguageCode = 'en' | 'fr' | 'es' | 'ja' | 'ru'
export type LanguageFocus = 'phrases' | 'vocabulary' | 'grammar' | 'listening'
export type DocumentFocus = 'concepts' | 'arguments' | 'terms' | 'examples'
export type DocumentStudyMode = 'knowledge' | 'language_reading'
export type DocumentAnswerLanguage =
  | 'zh'
  | 'en'
  | 'bilingual'
  | 'ja'
  | 'ko'
  | 'es'
  | 'fr'
  | 'de'
  | 'ru'
  | 'pt'
  | 'it'
  | 'ar'
export type DocumentDepth = 'quick' | 'standard' | 'deep'
export type DocumentAnswerLength = 'short' | 'medium' | 'long'
export type StudyDepth = 'standard' | 'deep'
export type SelectionStrategy = 'catch_all' | 'curated' | 'exhaustive'
export type ReviewDensity = 'full' | 'fast'
export type TemplateId = 'immersive_v11' | 'ciba_tianxia_v1' | 'immersive' | 'dictionary' | 'minimal'
export type CardStyleId = 'warm_paper' | 'minimal_white' | 'dark_immersive'
export type Provider = 'local' | 'mimo' | 'openai-compatible' | 'claude' | 'gemini' | 'gemini-vertex'
export type TtsProvider = 'disabled' | 'mimo' | 'qwen' | 'grok' | 'gemini' | 'gemini-vertex' | 'openai-compatible'
export type SourceMode = 'local' | 'url' | 'document'
export type UrlImportMode = 'video' | 'subtitles'
export type SettingsTab = 'api' | 'tts' | 'env' | 'about'
export type SegmentFilter = 'all' | 'selected' | 'unselected'
export type PhraseReviewStatus = 'recommended' | 'needs_review' | 'reject' | 'duplicate' | 'unreviewed' | string
export type CandidateKind =
  | 'expression'
  | 'contextual_vocab'
  | 'grammar_pattern'
  | 'listening_feature'
  | 'pragmatic_risk'
  | string
export type LearningContentKind = 'phrase' | 'vocabulary' | 'grammar' | 'listening' | 'knowledge' | string
export type DocumentCardKind = 'knowledge' | 'language_reading'
export type GenerationBasis = 'audio_verified' | 'subtitle_inferred' | 'dictionary_only'
export type PronunciationConfidence = 'high' | 'medium' | 'low'
export type PronunciationIssueSeverity = 'block' | 'warn' | 'info'
export type PronunciationField =
  | 'phonetic_ipa'
  | 'spoken_ipa'
  | 'source_spoken_ipa'
  | 'pronunciation_note'
  | 'pronunciation_meta'
export type PronunciationIssue = {
  field: PronunciationField
  severity: PronunciationIssueSeverity
  code: string
  message: string
}
export type PronunciationFieldAction = 'kept' | 'hidden' | 'cleared' | 'downgraded' | 'not_generated'
export type PronunciationFieldChange = {
  field: Exclude<PronunciationField, 'pronunciation_meta'>
  action: PronunciationFieldAction
  code: string
  message: string
  original_value?: string
}
export type PronunciationMeta = {
  language_code: LearningLanguageCode
  accent_profile: string
  notation_system: string
  generation_basis: GenerationBasis
  field_confidence: {
    phonetic_ipa?: PronunciationConfidence
    spoken_ipa?: PronunciationConfidence
    source_spoken_ipa?: PronunciationConfidence
    pronunciation_note?: PronunciationConfidence
  }
  same_as_standard_reason?: string | null
  pitch_confidence?: PronunciationConfidence | 'unknown'
  validation_issues: PronunciationIssue[]
  field_changes?: PronunciationFieldChange[]
}
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
  output_volume?: number
}

export type TtsSemanticVerificationConfig = {
  asr_provider?: 'whisper-cli' | 'whisper' | 'openai-whisper' | 'asr-command' | string
  asr_command?: string
  asr_command_args?: string[]
  whisper_command?: string
  whisper_model?: string
  whisper_language?: string
  whisper_timeout_seconds?: number
  asr_timeout_seconds?: number
  require_pass_for_export?: boolean
  strict?: boolean
  block_unverified?: boolean
  fail_on_manual_review?: boolean
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

export type SavedProfileAuth = 'api_key' | 'gcloud' | 'none'

export type SavedApiProfile = {
  id: string
  label: string
  provider: Provider
  base_url: string
  model: string
  capabilities: string[]
  auth: SavedProfileAuth
  has_api_key: boolean
  updated_at: string
  last_test_ok?: boolean
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

export type SavedTtsProfile = {
  id: string
  label: string
  enabled: boolean
  provider: TtsProvider
  base_url: string
  model: string
  voice: string
  language: string
  sample_rate: number
  bit_rate: number
  output_volume?: number
  auth: SavedProfileAuth
  has_api_key: boolean
  updated_at: string
  last_test_ok?: boolean
}

export type ApiTestResult = {
  ok: boolean
  provider: string
  model: string
  message: string
  error_code?: WorkerErrorCode | string
  stage?: string
  retryable?: boolean
  latency_ms?: number
}

export type TtsTestResult = {
  ok: boolean
  provider: string
  model: string
  voice: string
  message: string
  error_code?: WorkerErrorCode | string
  stage?: string
  retryable?: boolean
  latency_ms?: number
  bytes?: number
}

export type TtsSemanticSummary = {
  automatic_semantic_check?: 'available' | 'unavailable' | string
  status?: 'passed' | 'mismatch' | 'manual_review_required' | 'not_applicable' | string
  passed?: number
  failed?: number
  manual_review_required?: number
  high_risk_items?: number
}

export type TtsSemanticItem = {
  file: string
  role?: 'sentence_tts' | 'phrase_tts' | string
  field?: string
  card_id?: string
  learning_point_id?: string
  segment_id?: string
  source_time?: string
  tts_text?: string
  text_hash?: string
  semantic_verification?: string
  semantic_review_reasons?: string[]
  asr_provider?: string
  asr_transcript?: string
  expected_text_normalized?: string
  actual_text_normalized?: string
}

export type CardMediaLedgerItem = {
  card_id: string
  source_card_id?: string
  learning_point_id?: string
  segment_id?: string
  source_time?: string
  media_start?: number
  media_end?: number
  media_source_time?: string
  media_alignment_status?: string
  media_alignment_text?: string
  media_alignment_source_text?: string
  media_subtitle_alignment_status?: string
  media_subtitle_alignment_reason?: string
  media_subtitle_overlap_score?: number
  media_subtitle_time?: string
  media_subtitle_cue_count?: number
  media_window_subtitle_text?: string
  subtitle_path?: string
  card_display_sentence?: string
  answer?: string
  sentence_tts_text?: string
  phrase_tts_text?: string
  video_webm?: string
  video_mp4?: string
  poster?: string
  original_audio?: string
  sentence_tts_audio?: string
  phrase_tts_audio?: string
  sentence_tts_semantic_verification?: string
  sentence_tts_asr_transcript?: string
  phrase_tts_semantic_verification?: string
  phrase_tts_asr_transcript?: string
  template_label?: string
  template_version?: string
}

export type AudioAuditItem = {
  card_id: string
  learning_point_id?: string
  segment_id?: string
  source_time?: string
  media_start?: number
  media_end?: number
  media_source_time?: string
  media_alignment_status?: string
  media_alignment_text?: string
  media_alignment_source_text?: string
  media_subtitle_alignment_status?: string
  media_subtitle_alignment_reason?: string
  media_subtitle_overlap_score?: number
  media_subtitle_time?: string
  media_subtitle_cue_count?: number
  media_window_subtitle_text?: string
  subtitle_path?: string
  card_display_sentence?: string
  source_sentence?: string
  visible_answer?: string
  sentence_tts_expected_text?: string
  phrase_tts_expected_text?: string
  video_webm?: string
  video_mp4?: string
  poster?: string
  original_audio?: string
  sentence_tts_file?: string
  phrase_tts_file?: string
  sentence_tts_asr_transcript?: string
  phrase_tts_asr_transcript?: string
  sentence_tts_semantic_verification?: string
  phrase_tts_semantic_verification?: string
  semantic_review_reasons?: string[]
  sentence_tts_semantic_review_reasons?: string[]
  phrase_tts_semantic_review_reasons?: string[]
  media_hashes?: Record<string, string>
  tts_text_hashes?: Record<string, string>
  deck?: string
  model?: string
  template?: string
  anki_note_id?: number | string
  anki_fields?: Record<string, string[]>
  anki_media_exists?: Record<string, boolean>
}

export type AudioAuditSummary = {
  status?: 'passed' | 'mismatch' | 'manual_review_required' | 'not_applicable' | string
  items?: number
  expected_items?: number
  passed?: number
  failed?: number
  manual_review_required?: number
  mismatches?: number
  media_subtitle_alignment?: {
    matched?: number
    partial?: number
    mismatch?: number
    unknown?: number
  }
  verify_path?: string
}

export type ExportResult = {
  apkg_path: string
  apkg_relative_path?: string
  apkg_sha256?: string
  apkg_size_bytes?: number
  apkg_mtime_ms?: number
  source_identity?: Record<string, unknown>
  source_fingerprint?: string
  media_dir: string
  deck_name?: string
  deck_names?: string[]
  model_name?: string
  template_name?: string
  template_version?: string
  anki_tag?: string
  anki_manual_import_hint?: string
  anki_verify_after_manual_import_supported?: boolean
  media_prefix?: string
  media_manifest?: Record<string, MediaManifestEntry>
  media_ledger?: MediaLedgerItem[]
  card_media_ledger?: CardMediaLedgerItem[]
  tts_manual_review_items?: TtsSemanticItem[]
  tts_semantic_failures?: TtsSemanticItem[]
  tts_semantic_verification?: TtsSemanticSummary
  audio_audit_path?: string
  audio_audit_markdown_path?: string
  audio_audit_summary?: AudioAuditSummary
  audio_audit_items?: AudioAuditItem[]
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
    card_media_ledger_items?: number
    tts_cache_hits?: number
    tts_cache_misses?: number
    tts_cache_total?: number
    media_cache_hits?: number
    media_cache_misses?: number
    media_cache_total?: number
    media_reused_segments?: number
    tts_concurrency?: number
    media_concurrency?: number
    tts_manual_review_items?: number
    tts_semantic_passed_items?: number
    tts_semantic_failed_items?: number
    tts_high_risk_manual_review_items?: number
    subtitle_diagnostic_status?: string
    subtitle_path?: string
    media_subtitle_alignment?: {
      matched?: number
      partial?: number
      mismatch?: number
      unknown?: number
    }
  }
  timing_ms?: Record<string, number>
  cache_summary?: Record<string, unknown>
  generation_reconciliation?: Record<string, unknown>
  retryable_failures?: Array<Record<string, unknown>>
  warnings?: string[]
  deck_kind?: 'video_language' | 'subtitle_language' | 'document_knowledge' | 'document_reading' | string
}

export type AnkiVerifyResult = {
  ok: boolean
  message: string
  failed_checks: string[]
  apkg_path?: string
  apkg_relative_path?: string
  apkg_sha256?: string
  apkg_size_bytes?: number
  apkg_mtime_ms?: number
  source_identity?: Record<string, unknown> | null
  source_fingerprint?: string | null
  deck_name?: string
  model_names?: string[]
  import_attempted?: boolean
  import_result?: unknown
  import_error?: string | null
  card_count?: number
  expected_cards?: number | null
  imported_card_count?: number
  duplicate_imported_card_count?: number
  duplicate_imported_cards?: Array<{ card_id: string; anki_card_id: string }>
  media_count_expected?: number
  media_count_referenced?: number
  media_count_checked?: number
  missing_media?: string[]
  mismatched_media?: Array<{ file: string; expected_sha256: string; actual_sha256: string }>
  unexpected_media_references?: string[]
  unreferenced_expected_media?: string[]
  ledger_missing_manifest?: string[]
  manifest_tts_without_ledger?: string[]
  ledger_text_hash_mismatch?: Array<{ file: string; expected_text_hash: string; ledger_text_hash: string }>
  card_media_ledger_count?: number | null
  card_media_ledger_mismatches?: Array<{
    card_id: string
    field: string
    expected: string[]
    actual: string[]
    missing_expected: string[]
    unexpected_actual: string[]
  }>
  media_ledger_card_text_mismatches?: Array<Record<string, unknown>>
  tts_manual_review_items?: TtsSemanticItem[]
  tts_semantic_failures?: TtsSemanticItem[]
  tts_semantic_verification?: TtsSemanticSummary
  audio_audit_verify_path?: string
  audio_audit_verify_markdown_path?: string
  audio_audit_mismatches?: Array<Record<string, unknown>>
  audio_audit_write_errors?: Array<Record<string, unknown>>
  audio_audit_summary?: AudioAuditSummary
  timing_ms?: Record<string, number>
}

export type WorkerProgress = {
  job_id?: string
  command: string
  stage: string
  stage_label?: string
  phase?: string
  percent: number
  message: string
  completed_batches?: number
  total_batches?: number
  elapsed_ms?: number
  cache_hits?: number
  cache_misses?: number
}

export type WorkerCommand =
  | 'extract_learning_points'
  | 'generate_cards_from_learning_points'
  | 'generate'
  | 'export'
  | 'verify_anki_import'

export type WorkerErrorCode =
  | 'ENV_PYTHON_MISSING'
  | 'ENV_FFMPEG_MISSING'
  | 'YOUTUBE_RATE_LIMIT'
  | 'YOUTUBE_N_CHALLENGE'
  | 'YOUTUBE_SUBTITLE_UNAVAILABLE'
  | 'LOCAL_SUBTITLE_MISSING'
  | 'MODEL_AUTH_FAILED'
  | 'MODEL_CONNECTION_FAILED'
  | 'MODEL_NOT_FOUND'
  | 'MODEL_QUOTA_EXCEEDED'
  | 'MODEL_TIMEOUT'
  | 'MODEL_JSON_INVALID'
  | 'MODEL_REVIEW_BAD_JSON'
  | 'MODEL_REVIEW_FAILED'
  | 'TTS_AUTH_FAILED'
  | 'TTS_CONNECTION_FAILED'
  | 'TTS_NOT_FOUND'
  | 'TTS_QUOTA_EXCEEDED'
  | 'TTS_TIMEOUT'
  | 'TTS_SEMANTIC_MISMATCH'
  | 'TTS_SEMANTIC_UNVERIFIED'
  | 'UNSAFE_ASR_COMMAND'
  | 'UNSAFE_VERIFY_OUTPUT_DIR'
  | 'REMOTE_ANKI_CONNECT_BLOCKED'
  | 'PRIVATE_NETWORK_URL_BLOCKED'
  | 'YTDLP_REMOTE_COMPONENTS_CONFIRMATION_REQUIRED'
  | 'LOCAL_PATH_ACCESS_CONFIRMATION_REQUIRED'
  | 'EXPORT_QUALITY_GATE_FAILED'
  | 'MEDIA_SUBTITLE_ALIGNMENT_MISMATCH'
  | 'FFMPEG_SLICE_FAILED'
  | 'ANKI_EXPORT_FAILED'
  | 'ANKI_VERIFY_FAILED'
  | 'WORKER_CANCELLED'
  | 'WORKER_TIMEOUT'
  | 'UNKNOWN_WORKER_ERROR'

export type WorkerJob = {
  job_id: string
}

export type WorkerOperation = {
  status: 'idle' | 'running' | 'cancelling' | 'succeeded' | 'failed'
  command?: WorkerCommand
  jobId?: string
}

export type WorkspaceStage = 'source' | 'generate' | 'review'
export type ResponsiveMode = 'wide' | 'medium' | 'compact'
export type InspectorState = 'open' | 'collapsing' | 'collapsed' | 'sheet'

export type QualityFunnel = {
  subtitle_cues?: number
  source_sentence_count?: number
  candidate_segments?: number
  learning_point_count?: number
  recommended_learning_point_count?: number
  review_learning_point_count?: number
  card_count?: number
  selected_card_count?: number
  exportable_card_count?: number
  repair_required_card_count?: number
  selected_exportable_card_count?: number
  selected_repair_required_card_count?: number
  recommended_card_count?: number
  review_card_count?: number
  rejected_learning_point_count?: number
  duplicate_learning_point_count?: number
  usable_card_count?: number
  filtered_learning_point_count?: number
  low_value_filtered_count?: number
  blocked_quality_issue_count?: number
  selected_learning_point_count?: number
  eligible_learning_point_count?: number
  successful_learning_point_count?: number
  generation_queue_count?: number
  generation_success_count?: number
  generation_missing_count?: number
  generation_reconciliation_status?: 'ok' | 'partial' | string
  card_generation_missing_learning_point_count?: number
  card_generation_filtered_card_count?: number
  card_generation_skipped_learning_point_count?: number
  user_selected_fallback_card_count?: number
  ai_repaired_card_count?: number
  candidate_only_learning_point_count?: number
  hidden_duplicate_learning_point_count?: number
  hard_blocked_learning_point_count?: number
  ai_review_cache_hits?: number
  ai_review_cache_misses?: number
  ai_review_cache_read_enabled?: boolean
  ai_review_cache_write_enabled?: boolean
  ai_review_concurrency?: number
  ai_review_timing_ms?: Record<string, number>
  learning_point_timing_ms?: Record<string, number>
  generation_timing_ms?: Record<string, number>
  generation_timing_aggregate_batch_count?: number
  generation_timing_aggregate_complete?: boolean
  generation_batch_size?: number
  generation_batch_count?: number
  generation_batch_completed?: number
  generation_batch_completed_learning_points?: number
  card_generation_cache_hits?: number
  card_generation_cache_misses?: number
  card_generation_cache_read_enabled?: boolean
  card_generation_cache_write_enabled?: boolean
  card_generation_cache_namespace?: string
  card_generation_cache_aggregate_batch_count?: number
  card_generation_cache_aggregate_complete?: boolean
  card_generation_cache_policy_consistent?: boolean
  card_generation_cache_namespace_consistent?: boolean
  level_mode?: LevelMode | string
  learning_points_per_source_distribution?: Record<string, number>
  enabled_cards_per_source_distribution?: Record<string, number>
  max_learning_points_per_source?: number
  source_expansion?: {
    mode?: 'auto' | 'full' | 'off' | string
    eligible_source_groups?: number
    requested_source_groups?: number
    added_candidates?: number
    rejected_candidates?: number
  } | null
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

export type MaterialContext = {
  summary?: string
  topic?: string
  scene?: string
  speakers_or_author?: string
  tone?: string
  key_points?: string[]
  learning_opportunities?: string[]
  source?: 'ai' | 'heuristic' | string
}

export type CardGenerationDiagnosticItem = {
  learning_point_id: string
  answer_core?: string
  status:
    | 'skipped'
    | 'model_missing'
    | 'hard_failed'
    | 'filtered'
    | 'ai_repaired'
    | 'fallback_from_selected_learning_point'
    | string
  reason: string
  missing_ai_fields?: string[]
  fallback_fields_filled?: string[]
}

export type CardGenerationDiagnostics = {
  processed_learning_point_count?: number
  selected_learning_point_count?: number
  eligible_learning_point_count?: number
  successful_learning_point_count?: number
  generated_card_count?: number
  exportable_card_count?: number
  missing_learning_point_count?: number
  model_missing_learning_point_count?: number
  filtered_learning_point_count?: number
  skipped_learning_point_count?: number
  hard_failure_items?: CardGenerationDiagnosticItem[]
  fallback_card_count?: number
  missing_ai_fields?: Record<string, string[]>
  media_integrity_summary?: Record<string, unknown>
  items?: CardGenerationDiagnosticItem[]
}

export type GenerationRunState =
  | 'source_ready'
  | 'learning_points_ready'
  | 'generation_confirming'
  | 'generation_running'
  | 'cards_ready'
  | 'export_running'
  | 'export_failed_retryable'
  | 'export_ready'
  | 'anki_verified'

export type GenerationRunProgress = {
  state: GenerationRunState
  stage_label: string
  percent: number
  selected_count: number
  processed_count: number
  generated_count: number
  exportable_count: number
  hard_failure_count: number
  batch_completed?: number
  batch_total?: number
}

export type GenerationRunSummary = {
  selected_count: number
  processed_count: number
  generated_count: number
  exportable_count: number
  hard_failure_count: number
  fallback_card_count?: number
  retryable_failure_count?: number
}

export type WorkerFinishedEvent = {
  job_id: string
  command: WorkerCommand
  ok: boolean
  result?: unknown
  result_ref?: string
  result_size_bytes?: number
  result_summary?: Record<string, unknown>
  finished_at_ms?: number
  error?: string
  error_code?: WorkerErrorCode | string
  stage?: string
  retryable?: boolean
  fallbacks?: string[]
  details?: Record<string, unknown>
  cancelled?: boolean
}

export type EnvStatusItem = {
  id: string
  label: string
  status: 'ok' | 'action' | 'blocked'
  detail: string
  fix?: string
}

export type EnvRepairTarget =
  | 'all'
  | 'auto'
  | 'python_runtime'
  | 'python_packages'
  | 'ffmpeg'
  | 'js_runtime'
  | 'anki'
  | 'anki_connect'

export type EnvRepairAction = {
  id: string
  label: string
  status: 'success' | 'failed' | 'skipped' | 'manual'
  detail: string
  command?: string
  next_step?: string
}

export type EnvRepairResult = {
  ok: boolean
  target: EnvRepairTarget
  summary: string
  actions: EnvRepairAction[]
}

export type GenerateRequest = {
  title: string
  source_mode: SourceMode
  source_url: string
  url_import_mode: UrlImportMode
  url_auto_subtitle_fallback: boolean
  allow_private_network_url?: boolean
  allow_ytdlp_remote_components?: boolean
  local_path_access_confirmed?: boolean
  skip_video_slicing: boolean
  batch_enabled: boolean
  batch_items: BatchSourceItem[]
  video_path: string
  subtitle_path: string
  document_path: string
  language: LearningLanguageCode
  level_mode: LevelMode
  level: Level
  collection_levels: Level[]
  template_id: TemplateId
  card_style: CardStyleId
  review_density: ReviewDensity
  content_toggles: ContentToggles
  language_focus: LanguageFocus[]
  document_focus: DocumentFocus[]
  document_study_mode: DocumentStudyMode
  document_answer_language: DocumentAnswerLanguage
  document_depth: DocumentDepth
  document_answer_length: DocumentAnswerLength
  study_depth: StudyDepth
  selection_strategy: SelectionStrategy
  reuse_ai_review_cache: boolean
  card_types: CardKind[]
  max_segments: number
  api_config: ApiConfig
}

export type LearningPoint = {
  id: string
  kind: CandidateKind
  exact_span: string
  exact_span_start?: number | null
  exact_span_end?: number | null
  answer_core: string
  difficulty?: Level | string
  value_score?: number | string | null
  reason?: string
  suggested_card_type?: CardKind | string
  content_kind?: LearningContentKind
  normalized_answer?: string
  source_evidence?: string
  usage_boundary?: string
  confusable_note?: string
  phonetic_ipa?: string
  spoken_ipa?: string
  source_spoken_ipa?: string
  pronunciation_note?: string
  pronunciation_confidence?: 'high' | 'medium' | 'low' | string
  pronunciation_status?: string
  source_pronunciation_status?: string
  pronunciation_meta?: PronunciationMeta | string | null
  learning_action?: string
  learning_action_key?: string
  source?: 'local' | 'model' | 'repaired' | string
  confidence?: 'high' | 'medium' | 'low' | string
  validation_status?: 'valid' | 'repaired' | 'candidate_only' | 'hidden_duplicate' | 'hard_blocked' | 'reject' | string
  validation_issues?: string[]
  repair_history?: string[]
}

export type LearningPointInventoryStatus = 'card_generated' | 'candidate_only' | 'hidden_duplicate' | 'hard_blocked'

export type LearningPointInventoryItem = {
  id: string
  source_segment_id: string
  source_time: string
  source_sentence: string
  exact_span: string
  exact_span_start?: number | null
  exact_span_end?: number | null
  answer_core: string
  normalized_answer?: string
  candidate_kind: CandidateKind
  phrase_type?: string
  estimated_level?: string
  value_score?: number
  learning_action: string
  learning_action_key?: string
  source?: 'local' | 'model' | 'repaired' | string
  confidence?: 'high' | 'medium' | 'low' | string
  validation_status?: 'valid' | 'repaired' | 'candidate_only' | 'hidden_duplicate' | 'hard_blocked' | 'reject' | string
  repair_history?: string[]
  reason: string
  status: LearningPointInventoryStatus
  card_id?: string
  filter_reason?: string
  block_reason?: string
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
  phrase_type?: string
  learning_point_id?: string
  candidate_kind?: CandidateKind
  exact_span?: string
  exact_span_start?: number | null
  exact_span_end?: number | null
  normalized_answer?: string
  candidate_source?: string
  contract_source?: string
  learning_point_schema_version?: number
  learning_action?: string
  learning_action_key?: string
  confidence?: 'high' | 'medium' | 'low' | string
  validation_status?: 'valid' | 'repaired' | 'candidate_only' | 'hidden_duplicate' | 'hard_blocked' | 'reject' | string
  repair_history?: string[]
  content_kind?: LearningContentKind
  source_evidence?: string
  knowledge_type?: DocumentFocus | string
  document_card_kind?: DocumentCardKind | string
  score_breakdown?: Record<string, number | string>
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
  estimated_level?: Level | string
  difficulty_reason?: string
  teacher_note: string
  cloze: string
  learning_target?: string
  why_it_matters?: string
  how_to_use_it?: string
  natural_chinese?: string
  retrieval_prompt?: string
  answer_core?: string
  usage_boundary?: string
  confusable_note?: string
  phonetic_ipa?: string
  spoken_ipa?: string
  source_spoken_ipa?: string
  pronunciation_note?: string
  pronunciation_confidence?: 'high' | 'medium' | 'low' | string
  pronunciation_status?: string
  source_pronunciation_status?: string
  pronunciation_meta?: PronunciationMeta | string | null
  generation_source?: 'ai_complete' | 'ai_repaired' | 'fallback_from_selected_learning_point' | string
  missing_ai_fields?: string[]
  fallback_fields_filled?: string[]
  replacement_examples?: string | string[]
  avoid_reason?: string
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
  media_alignment_status?: 'source_sentence_window' | 'display_sentence_window' | 'source_sentence_fallback' | string
  media_alignment_phrase?: string
  media_alignment_phrase_located?: boolean
  media_alignment_text?: string
  media_alignment_source_text?: string
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
  phrase_type?: string
  learning_point_id?: string
  candidate_kind?: CandidateKind
  exact_span?: string
  exact_span_start?: number | null
  exact_span_end?: number | null
  normalized_answer?: string
  answer_core?: string
  candidate_source?: string
  contract_source?: string
  learning_point_schema_version?: number
  learning_action?: string
  learning_action_key?: string
  confidence?: 'high' | 'medium' | 'low' | string
  validation_status?: 'valid' | 'repaired' | 'candidate_only' | 'hidden_duplicate' | 'hard_blocked' | 'reject' | string
  repair_history?: string[]
  source_segment_id?: string
  content_kind?: LearningContentKind
  source_evidence?: string
  knowledge_type?: DocumentFocus | string
  document_card_kind?: DocumentCardKind | string
  score_breakdown?: Record<string, number | string>
  learning_points?: LearningPoint[]
  cards: Card[]
}

export type UrlSourceInfo = {
  title?: string
  webpage_url?: string
  duration?: number
  uploader?: string
  download_dir?: string
  download_mode?: string
  transcript_only?: boolean
  skip_video_slicing?: boolean
}

export type LocalSourceInfo = {
  title?: string
  video_path?: string
  subtitle_path?: string
  subtitle_source?: 'manual' | 'auto_matched' | 'embedded' | string
  video_fingerprint?: string
  subtitle_fingerprint?: string
}

export type DocumentSourceInfo = {
  title?: string
  document_path?: string
  document_study_mode?: DocumentStudyMode
}

export type Project = {
  schema_version?: number
  id: string
  title: string
  source_mode?: SourceMode
  source_url?: string
  source_info?: UrlSourceInfo | LocalSourceInfo | DocumentSourceInfo | null
  video_path: string
  subtitle_path: string
  document_path?: string
  language: LearningLanguageCode | string
  level_mode?: LevelMode | string
  level: Level
  collection_levels?: Level[]
  template_id: TemplateId
  card_style?: CardStyleId | string
  review_density?: ReviewDensity
  content_toggles: ContentToggles
  language_focus?: LanguageFocus[]
  document_focus?: DocumentFocus[]
  document_study_mode?: DocumentStudyMode
  document_answer_language?: DocumentAnswerLanguage
  document_depth?: DocumentDepth
  document_answer_length?: DocumentAnswerLength
  study_depth?: StudyDepth
  selection_strategy?: SelectionStrategy
  material_context?: MaterialContext | null
  card_types: CardKind[]
  max_segments?: number
  auto_max_segments?: boolean
  skip_video_slicing?: boolean
  batch_enabled?: boolean
  batch_items?: BatchSourceItem[]
  quality_funnel?: QualityFunnel
  card_generation_diagnostics?: CardGenerationDiagnostics
  learning_point_inventory?: LearningPointInventoryItem[]
  generated_learning_point_ids?: string[]
  generated_document_point_ids?: string[]
  source_fingerprint?: string
  tts_semantic_verification?: TtsSemanticVerificationConfig
  segments: Segment[]
  warnings?: string[]
  error_code?: WorkerErrorCode | string
  model_error_code?: WorkerErrorCode | string
  model_stage?: string
  model_retryable?: boolean
  stage?: string
  retryable?: boolean
  fallbacks?: string[]
  warning?: string | null
  created_at: number
}

export type MediaManifestEntry = {
  sha256: string
  bytes: number
  role?: 'video' | 'poster' | 'original_audio' | 'sentence_tts' | 'phrase_tts' | string
  segment_id?: string
  card_id?: string
  learning_point_id?: string
  tts_text?: string
  text_hash?: string
  semantic_verification?: string
  manual_review_required?: boolean
  semantic_review_reasons?: string[]
  asr_provider?: string
  asr_transcript?: string
  expected_text_normalized?: string
  actual_text_normalized?: string
  field?: string
  source_time?: string
}

export type MediaLedgerItem = MediaManifestEntry & {
  file: string
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
  anki_installed?: boolean
  anki_path?: string
  anki_running?: boolean
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

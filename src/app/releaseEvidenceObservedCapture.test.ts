import { describe, expect, it } from 'vitest'

import type { LearningPointExtractionResult } from '../domain/learningPoints'
import {
  buildVideoReleaseRunInitializerPlan,
  type VideoReleaseCaseId,
  type VideoReleaseCaseManifest,
} from '../domain/releaseEvidenceLayout'
import type { AnkiVerifyResult, ExportResult, Project } from '../domain/types'
import { buildReleaseTimingCacheArtifactWritePlan } from './releaseEvidenceArtifacts'
import { compactExportResultForUi } from './exportResultState'
import { buildReleaseObservedTimingCacheInputSnapshotFromJson } from './releaseEvidenceObservedInput'
import {
  buildReleaseObservedRawJsonFromRawCapture,
  buildReleaseObservedRawSnapshotHandoffArtifact,
  buildReleaseObservedSnapshotFromAppState,
  buildReleaseObservedSnapshotFromRawCapture,
  buildReleaseObservedTimingCacheWriterHandoffArtifact,
  buildReleaseObservedTimingCacheWriterDryRunEvidence,
  buildReleaseObservedTimingCacheWritePlanFromAppState,
  buildReleaseObservedTimingCacheWritePlanFromRawCapture,
  emptyReleaseEvidenceRawSnapshot,
  reduceReleaseEvidenceRawSnapshot,
} from './releaseEvidenceObservedCapture'

function manifestFor(caseId: VideoReleaseCaseId): VideoReleaseCaseManifest {
  const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
  return JSON.parse(
    plan.seedFiles.find((file) => file.relativePath === `cases/${caseId}/case_manifest.json`)?.content ?? '{}',
  )
}

function completeFixture() {
  const manifest = manifestFor('youtube_a_full1_cold')
  manifest.source_candidate = {
    url: 'https://www.youtube.com/watch?v=m7IlyBEyi3c',
    video_id: 'm7IlyBEyi3c',
    source_fingerprint: 'yt:779a15b6499710bd',
    material_manifest:
      'E:\\ANKI\\test_runs\\video_material_rotation_20260619_124902_slice104_verified_youtube_ab\\material_manifest.json',
    cache_probe_status: 'no_existing_url_cache_found',
  }

  const learningPointResult = {
    id: 'lp-run',
    title: 'release fixture',
    source_mode: 'url',
    video_path: '',
    subtitle_path: '',
    language: 'en',
    level_mode: 'single',
    level: 'B1',
    source_sentences: [],
    learning_points: [],
    learning_point_summary: { total: 1, recommended: 1, candidate_only: 0, hidden_duplicate: 0, hard_blocked: 0 },
    timing_ms: {
      source_prepare_ms: 1,
      learning_point_extract_ms: 2,
      ai_review_ms: 3,
    },
    quality_funnel: {
      ai_review_cache_read_enabled: false,
      ai_review_cache_write_enabled: true,
      ai_review_cache_hits: 0,
      ai_review_cache_misses: 1,
    },
  } as unknown as LearningPointExtractionResult

  const project = {
    id: 'project-1',
    title: 'release project',
    source_mode: 'url',
    video_path: '',
    subtitle_path: '',
    language: 'en',
    level: 'B1',
    template_id: 'immersive_repetition_v11',
    content_toggles: {},
    card_types: ['phrase'],
    segments: [],
    created_at: 1,
    quality_funnel: {
      card_count: 1,
      generation_timing_ms: { card_body_ms: 4 },
      card_generation_cache_read_enabled: false,
      card_generation_cache_write_enabled: true,
      card_generation_cache_hits: 0,
      card_generation_cache_misses: 1,
    },
  } as unknown as Project

  const exportResult: ExportResult = {
    schema_version: 2,
    apkg_path:
      'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542\\cases\\youtube_a_full1_cold\\apkg\\youtube_a_full1_cold.apkg',
    apkg_sha256: 'd'.repeat(64),
    apkg_size_bytes: 123456,
    apkg_mtime_ms: 1781740000000,
    source_identity: { source_fingerprint: 'yt:779a15b6499710bd', source_mode: 'url' },
    source_fingerprint: 'yt:779a15b6499710bd',
    media_dir: 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542\\media',
    cards: 1,
    segments: 1,
    deck_name: 'Video Release Smoke',
    deck_names: ['Video Release Smoke'],
    deck_kind: 'video_language',
    model_name: 'Anki Card Generator V15 - 沉浸复读 V11',
    note_model_id: 1028904201,
    template_name: '沉浸复读 V11',
    template_family: 'language-immersive-v11',
    template_schema: 'V15',
    template_version: 'V15',
    compatibility_contract_version: 1,
    note_model_contract_digest: '966edeadbcbe64511e93343d854007f23ad851c17d81e79a672dbad4b4d74e4c',
    anki_tag: 'anki_card_generator_v15',
    media_manifest: {
      'clip.mp4': {
        sha256: 'a'.repeat(64),
        bytes: 100,
        role: 'video',
        segment_id: 'segment-1',
        card_id: '',
        field: 'Video',
      },
    },
    media_ledger: [
      {
        file: 'clip.mp4',
        sha256: 'a'.repeat(64),
        bytes: 100,
        role: 'video',
        segment_id: 'segment-1',
        card_id: '',
        field: 'Video',
      },
    ],
    card_media_ledger: [
      {
        card_id: 'card-1',
        segment_id: 'segment-1',
        deck_name: 'Video Release Smoke',
        note_tags: ['anki_card_generator_v15', 'English', 'B1', 'immersive_v11', 'phrase', 'repetition'],
        note_content_sha256: 'b'.repeat(64),
        video_mp4: 'clip.mp4',
      },
    ],
    note_content_fingerprint: {
      schema_version: 1,
      algorithm: 'sha256',
      serialization: 'json-field-pairs-v1',
      field_names: ['CardId', 'Answer'],
      card_count: 1,
    },
    audio_audit_items: [{ card_id: 'card-1' }],
    timing_ms: {
      tts_ms: 5,
      media_slice_ms: 6,
      apkg_pack_ms: 7,
    },
    media_summary: {
      video_segments: 1,
      video_files: 1,
      original_audio_files: 0,
      sentence_tts_files: 0,
      phrase_tts_files: 0,
      media_files: 1,
      media_bytes: 100,
      media_mb: 0,
      card_media_ledger_items: 1,
      tts_cache_hits: 0,
      tts_cache_misses: 2,
      tts_cache_total: 2,
      media_cache_hits: 0,
      media_cache_misses: 1,
      media_cache_total: 1,
    },
    warnings: [],
  }

  const ankiVerifyResult: AnkiVerifyResult = {
    ok: true,
    message: 'verified',
    failed_checks: [],
    apkg_path: exportResult.apkg_path,
    apkg_sha256: exportResult.apkg_sha256,
    apkg_size_bytes: exportResult.apkg_size_bytes,
    apkg_mtime_ms: exportResult.apkg_mtime_ms,
    source_identity: exportResult.source_identity,
    source_fingerprint: exportResult.source_fingerprint,
    card_count: 1,
    expected_cards: 1,
    deck_name: 'Video Release Smoke',
    timing_ms: { anki_verify_ms: 8 },
  }

  return {
    caseId: 'youtube_a_full1_cold' as const,
    manifest,
    learningPointResult,
    project,
    exportResult,
    compactExport: compactExportResultForUi(exportResult),
    ankiVerifyResult,
  }
}

function completeRawCapture(fixture: ReturnType<typeof completeFixture>) {
  const afterExtraction = reduceReleaseEvidenceRawSnapshot(emptyReleaseEvidenceRawSnapshot(), {
    type: 'learning_point_result',
    result: fixture.learningPointResult,
    jobId: 'extract-job',
  })
  const afterProject = reduceReleaseEvidenceRawSnapshot(afterExtraction, {
    type: 'project_for_export',
    project: fixture.project,
    jobId: 'generate-job',
  })
  const afterExport = reduceReleaseEvidenceRawSnapshot(afterProject, {
    type: 'export_result',
    result: fixture.exportResult,
    jobId: 'export-job',
  })
  return reduceReleaseEvidenceRawSnapshot(afterExport, {
    type: 'verify_result',
    result: fixture.ankiVerifyResult,
    verifiedExportApkgPath: fixture.exportResult.apkg_path,
    jobId: 'verify-job',
  })
}

describe('releaseEvidenceObservedCapture', () => {
  it('captures raw release inputs from controller state and the full export ref', () => {
    const fixture = completeFixture()
    const snapshot = buildReleaseObservedSnapshotFromAppState({
      ...fixture,
      lastLearningPointResult: null,
      lastExport: fixture.compactExport,
      lastExportFull: fixture.exportResult,
      coldCacheReadsDisabled: true,
    })

    expect(snapshot.ok).toBe(true)
    expect(snapshot.matrixPassCreated).toBe(false)
    expect(snapshot.rawObservedJson).toMatchObject({ case_id: 'youtube_a_full1_cold' })
    expect(snapshot.observedInput?.exportResult).toMatchObject({
      media_manifest: fixture.exportResult.media_manifest,
      media_ledger: fixture.exportResult.media_ledger,
      card_media_ledger: fixture.exportResult.card_media_ledger,
      audio_audit_items: fixture.exportResult.audio_audit_items,
    })

    if (!snapshot.observedInput) throw new Error('expected observed input')
    const plan = buildReleaseTimingCacheArtifactWritePlan({
      ...snapshot.observedInput,
      runDir: 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542',
    })
    expect(plan.ok).toBe(true)
    expect(plan.writes).toHaveLength(2)
  })

  it('falls back to the last raw learning-point result after visible extraction state is cleared', () => {
    const fixture = completeFixture()
    const snapshot = buildReleaseObservedSnapshotFromAppState({
      ...fixture,
      learningPointResult: null,
      lastLearningPointResult: fixture.learningPointResult,
      lastExport: fixture.compactExport,
      lastExportFull: fixture.exportResult,
      coldCacheReadsDisabled: true,
    })

    expect(snapshot.ok).toBe(true)
    expect(snapshot.failedChecks).not.toContain('observed_learning_point_result_missing')
    expect(snapshot.observedInput?.learningPointResult).toBe(fixture.learningPointResult)
  })

  it('blocks compact-only export state instead of treating UI export as raw evidence', () => {
    const fixture = completeFixture()
    const snapshot = buildReleaseObservedSnapshotFromAppState({
      ...fixture,
      lastLearningPointResult: null,
      lastExport: fixture.compactExport,
      lastExportFull: null,
      coldCacheReadsDisabled: true,
    })

    expect(snapshot.ok).toBe(false)
    expect(snapshot.failedChecks).toEqual([
      'app_snapshot_full_export_result_missing',
      'observed_export_full_audio_audit_items_missing',
      'observed_verified_export_apkg_path_missing',
    ])
    expect(snapshot.observedInput).toBeNull()
    expect(snapshot.rawObservedJson).toBeNull()
  })

  it('does not revive a stale full export ref after compact export state was cleared', () => {
    const fixture = completeFixture()
    const snapshot = buildReleaseObservedSnapshotFromAppState({
      ...fixture,
      lastLearningPointResult: null,
      lastExport: null,
      lastExportFull: fixture.exportResult,
      coldCacheReadsDisabled: true,
    })

    expect(snapshot.ok).toBe(false)
    expect(snapshot.failedChecks).toEqual(
      expect.arrayContaining([
        'app_snapshot_compact_export_result_missing',
        'observed_export_result_missing',
        'observed_verified_export_apkg_path_missing',
      ]),
    )
    expect(snapshot.observedInput).toBeNull()
  })

  it('blocks stale Anki verify state after the current export state was cleared', () => {
    const fixture = completeFixture()
    const snapshot = buildReleaseObservedSnapshotFromAppState({
      ...fixture,
      lastLearningPointResult: null,
      lastExport: null,
      lastExportFull: null,
      verifiedExportApkgPath: fixture.exportResult.apkg_path,
      coldCacheReadsDisabled: true,
    })

    expect(snapshot.ok).toBe(false)
    expect(snapshot.failedChecks).toEqual(
      expect.arrayContaining([
        'app_snapshot_verify_result_without_current_export',
        'observed_export_result_missing',
        'observed_verified_export_apkg_path_missing',
      ]),
    )
    expect(snapshot.observedInput).toBeNull()
  })

  it('blocks stale Anki verify state that no longer matches the current export', () => {
    const fixture = completeFixture()
    const snapshot = buildReleaseObservedSnapshotFromAppState({
      ...fixture,
      ankiVerifyResult: {
        ...fixture.ankiVerifyResult,
        expected_cards: 20,
        deck_name: 'Old Deck',
      },
      lastLearningPointResult: null,
      lastExport: fixture.compactExport,
      lastExportFull: fixture.exportResult,
      verifiedExportApkgPath: 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542\\old.apkg',
      coldCacheReadsDisabled: true,
    })

    expect(snapshot.ok).toBe(false)
    expect(snapshot.failedChecks).toEqual(
      expect.arrayContaining([
        'observed_verify_expected_cards_mismatch',
        'observed_verify_deck_name_mismatch',
        'observed_verify_apkg_path_mismatch',
      ]),
    )
    expect(snapshot.observedInput).toBeNull()
  })

  it('blocks stale full export refs with mismatched APKG identity', () => {
    const fixture = completeFixture()
    const snapshot = buildReleaseObservedSnapshotFromAppState({
      ...fixture,
      lastLearningPointResult: null,
      lastExport: fixture.compactExport,
      lastExportFull: {
        ...fixture.exportResult,
        apkg_sha256: 'e'.repeat(64),
      },
      coldCacheReadsDisabled: true,
    })

    expect(snapshot.ok).toBe(false)
    expect(snapshot.failedChecks).toContain('app_snapshot_export_ref_mismatch')
    expect(snapshot.observedInput).toBeNull()
  })

  it('passes completed multi-batch aggregate timing/cache evidence through unchanged', () => {
    const fixture = completeFixture()
    const project = {
      ...fixture.project,
      quality_funnel: {
        ...fixture.project.quality_funnel,
        generation_batch_count: 2,
        generation_batch_completed: 2,
        generation_timing_aggregate_batch_count: 2,
        generation_timing_aggregate_complete: true,
        card_generation_cache_aggregate_batch_count: 2,
        card_generation_cache_aggregate_complete: true,
        card_generation_cache_policy_consistent: true,
        card_generation_cache_namespace_consistent: true,
      },
    } as Project
    const snapshot = buildReleaseObservedSnapshotFromAppState({
      ...fixture,
      project,
      lastLearningPointResult: null,
      lastExport: fixture.compactExport,
      lastExportFull: fixture.exportResult,
      coldCacheReadsDisabled: true,
    })

    expect(snapshot.ok).toBe(true)
    expect(snapshot.observedInput?.project?.quality_funnel).toMatchObject({
      generation_timing_aggregate_complete: true,
      card_generation_cache_aggregate_complete: true,
      generation_timing_aggregate_batch_count: 2,
      card_generation_cache_aggregate_batch_count: 2,
    })
  })

  it('reduces hydrated worker results into a raw capture without reviving invalidated evidence', () => {
    const fixture = completeFixture()
    const afterExtraction = reduceReleaseEvidenceRawSnapshot(emptyReleaseEvidenceRawSnapshot(), {
      type: 'learning_point_result',
      result: fixture.learningPointResult,
      jobId: 'extract-job',
    })
    const afterProject = reduceReleaseEvidenceRawSnapshot(afterExtraction, {
      type: 'project_result',
      project: fixture.project,
      jobId: 'generate-job',
    })
    const afterExport = reduceReleaseEvidenceRawSnapshot(afterProject, {
      type: 'export_result',
      result: fixture.exportResult,
      jobId: 'export-job',
    })
    const afterVerify = reduceReleaseEvidenceRawSnapshot(afterExport, {
      type: 'verify_result',
      result: fixture.ankiVerifyResult,
      verifiedExportApkgPath: fixture.exportResult.apkg_path,
      jobId: 'verify-job',
    })

    const snapshot = buildReleaseObservedSnapshotFromRawCapture({
      capture: afterVerify,
      caseId: fixture.caseId,
      manifest: fixture.manifest,
      coldCacheReadsDisabled: true,
    })
    expect(snapshot.ok).toBe(true)
    expect(afterVerify.jobIds).toEqual({
      extraction: 'extract-job',
      generation: 'generate-job',
      export: 'export-job',
      ankiVerify: 'verify-job',
    })

    const invalidated = reduceReleaseEvidenceRawSnapshot(afterVerify, {
      type: 'invalidate',
      scope: 'export_and_verify',
    })
    const blocked = buildReleaseObservedSnapshotFromRawCapture({
      capture: invalidated,
      caseId: fixture.caseId,
      manifest: fixture.manifest,
      coldCacheReadsDisabled: true,
    })
    expect(blocked.ok).toBe(false)
    expect(blocked.failedChecks).toContain('observed_export_result_missing')
    expect(blocked.failedChecks).toContain('observed_anki_verify_result_missing')
  })

  it('builds a guarded app-side timing/cache write plan from raw capture without creating matrix proof', () => {
    const fixture = completeFixture()
    const afterExtraction = reduceReleaseEvidenceRawSnapshot(emptyReleaseEvidenceRawSnapshot(), {
      type: 'learning_point_result',
      result: fixture.learningPointResult,
      jobId: 'extract-job',
    })
    const afterProject = reduceReleaseEvidenceRawSnapshot(afterExtraction, {
      type: 'project_for_export',
      project: fixture.project,
      jobId: 'generate-job',
    })
    const afterExport = reduceReleaseEvidenceRawSnapshot(afterProject, {
      type: 'export_result',
      result: fixture.exportResult,
      jobId: 'export-job',
    })
    const capture = reduceReleaseEvidenceRawSnapshot(afterExport, {
      type: 'verify_result',
      result: fixture.ankiVerifyResult,
      verifiedExportApkgPath: fixture.exportResult.apkg_path,
      jobId: 'verify-job',
    })

    const writerSnapshot = buildReleaseObservedTimingCacheWritePlanFromRawCapture({
      capture,
      caseId: fixture.caseId,
      manifest: fixture.manifest,
      coldCacheReadsDisabled: true,
      runDir: 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542',
    })

    expect(writerSnapshot.ok).toBe(true)
    expect(writerSnapshot.status).toBe('ready_to_write')
    expect(writerSnapshot.matrixPassCreated).toBe(false)
    expect(writerSnapshot.rawObservedJson).toMatchObject({
      case_id: fixture.caseId,
      job_ids: {
        extraction: 'extract-job',
        generation: 'generate-job',
        export: 'export-job',
        ankiVerify: 'verify-job',
      },
    })
    expect(writerSnapshot.writePlan?.matrixPassCreated).toBe(false)
    expect(writerSnapshot.writePlan?.writes).toHaveLength(2)
    expect(writerSnapshot.writePlan?.writes.map((write) => write.relativePath)).toEqual([
      'cases/youtube_a_full1_cold/timing.json',
      'cases/youtube_a_full1_cold/cache_summary.json',
    ])
    expect(writerSnapshot.writePlan?.writes.map((write) => write.relativePath)).not.toContain(
      'cases/youtube_a_full1_cold/case_manifest.json',
    )

    const dryRunEvidence = buildReleaseObservedTimingCacheWriterDryRunEvidence(writerSnapshot)
    expect(dryRunEvidence).toMatchObject({
      status: 'ready_to_write',
      matrix_pass_created: false,
      write_requested: false,
      written_files: [],
      raw_observed_json: { case_id: fixture.caseId },
      writer: { ok: true, failed_checks: [] },
    })
    expect(dryRunEvidence.planned_writes).toHaveLength(2)
    expect(dryRunEvidence.planned_writes[0]).toMatchObject({
      kind: 'timing',
      relative_path: 'cases/youtube_a_full1_cold/timing.json',
      write_mode: 'exclusive_create',
    })
    expect(dryRunEvidence.planned_writes[0].bytes).toBeGreaterThan(0)
    expect(dryRunEvidence.planned_writes[0]).not.toHaveProperty('content')
    expect(JSON.stringify(dryRunEvidence.planned_writes)).not.toContain('source_prepare_ms')

    const handoffArtifact = buildReleaseObservedTimingCacheWriterHandoffArtifact(writerSnapshot)
    expect(handoffArtifact).toMatchObject({
      schema_kind: 'release_timing_cache_writer_handoff_audit',
      artifact_kind: 'timing_cache_writer_handoff',
      evidence_role: 'non_final_writer_handoff',
      artifact_scope: 'timing_cache_writer_only',
      matrix_eligibility: 'never',
      release_case_evidence: false,
      matrix_pass_created: false,
      matrix_pass_verified: false,
      write_requested: false,
      final_artifacts_written: false,
      handoff_written_files: [],
      raw_observed_json: { case_id: fixture.caseId },
    })
    expect(handoffArtifact.final_artifacts).toEqual({
      timing_json_written: false,
      cache_summary_json_written: false,
      manifests_updated: false,
      matrix_summary_updated: false,
      apkg_created: false,
      anki_verified: false,
      computer_use_actions_created: false,
      screenshots_created: false,
    })
    expect(handoffArtifact.planned_writes).toHaveLength(2)
    expect(JSON.stringify(handoffArtifact.planned_writes)).not.toContain('source_prepare_ms')
  })

  it('blocks app-side write planning when the raw app snapshot is blocked', () => {
    const fixture = completeFixture()
    const writerSnapshot = buildReleaseObservedTimingCacheWritePlanFromAppState({
      ...fixture,
      lastLearningPointResult: null,
      lastExport: fixture.compactExport,
      lastExportFull: null,
      coldCacheReadsDisabled: true,
      runDir: 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542',
    })

    expect(writerSnapshot.ok).toBe(false)
    expect(writerSnapshot.status).toBe('blocked')
    expect(writerSnapshot.failedChecks).toEqual(
      expect.arrayContaining(['app_snapshot_full_export_result_missing', 'observed_snapshot_blocked']),
    )
    expect(writerSnapshot.rawObservedJson).toBeNull()
    expect(writerSnapshot.writePlan).toBeNull()

    const dryRunEvidence = buildReleaseObservedTimingCacheWriterDryRunEvidence(writerSnapshot)
    expect(dryRunEvidence.status).toBe('blocked')
    expect(dryRunEvidence.raw_observed_json).toBeNull()
    expect(dryRunEvidence.planned_writes).toEqual([])
    expect(dryRunEvidence.writer.failed_checks).toContain('observed_snapshot_blocked')

    const handoffArtifact = buildReleaseObservedTimingCacheWriterHandoffArtifact(writerSnapshot)
    expect(handoffArtifact.status).toBe('blocked')
    expect(handoffArtifact.matrix_pass_created).toBe(false)
    expect(handoffArtifact.matrix_pass_verified).toBe(false)
    expect(handoffArtifact.raw_observed_json).toBeNull()
    expect(handoffArtifact.planned_writes).toEqual([])
    expect(handoffArtifact.written_files).toEqual([])
    expect(handoffArtifact.final_artifacts_written).toBe(false)
    expect(handoffArtifact.writer.failed_checks).toContain('observed_snapshot_blocked')
  })

  it('keeps raw observed JSON available but refuses unsafe run directories before returning writes', () => {
    const fixture = completeFixture()
    const writerSnapshot = buildReleaseObservedTimingCacheWritePlanFromAppState({
      ...fixture,
      lastLearningPointResult: null,
      lastExport: fixture.compactExport,
      lastExportFull: fixture.exportResult,
      coldCacheReadsDisabled: true,
      runDir:
        'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542\\..\\video_release_hardening_20260619_044542',
    })

    expect(writerSnapshot.ok).toBe(false)
    expect(writerSnapshot.status).toBe('blocked')
    expect(writerSnapshot.rawObservedJson).toMatchObject({ case_id: fixture.caseId })
    expect(writerSnapshot.failedChecks).toContain('run_dir_path_unsafe')
    expect(writerSnapshot.writePlan?.writes).toEqual([])
  })

  it('exports canonical raw observed JSON from raw capture without compacting export evidence', () => {
    const fixture = completeFixture()
    const capture = completeRawCapture(fixture)
    const rawObserved = buildReleaseObservedRawJsonFromRawCapture({
      capture,
      caseId: fixture.caseId,
      manifest: fixture.manifest,
      coldCacheReadsDisabled: true,
      sourceCacheProbeStatus: 'no_existing_url_cache_found',
      existingUrlCacheDirs: ['E:\\ANKI\\cache\\existing-url'],
    })

    expect(rawObserved).toMatchObject({
      case_id: fixture.caseId,
      verified_export_apkg_path: fixture.exportResult.apkg_path,
      cold_cache_reads_disabled: true,
      source_cache_probe_status: 'no_existing_url_cache_found',
      existing_url_cache_dirs: ['E:\\ANKI\\cache\\existing-url'],
      job_ids: {
        extraction: 'extract-job',
        generation: 'generate-job',
        export: 'export-job',
        ankiVerify: 'verify-job',
      },
    })
    expect(rawObserved.learning_point_result).toBe(fixture.learningPointResult)
    expect(rawObserved.project).toBe(fixture.project)
    expect(rawObserved.anki_verify_result).toBe(fixture.ankiVerifyResult)

    const exportResult = rawObserved.export_result as ExportResult
    expect(exportResult).toBe(fixture.exportResult)
    expect(exportResult.media_manifest).toEqual(fixture.exportResult.media_manifest)
    expect(exportResult.media_ledger).toEqual(fixture.exportResult.media_ledger)
    expect(exportResult.card_media_ledger).toEqual(fixture.exportResult.card_media_ledger)
    expect(exportResult.audio_audit_items).toEqual(fixture.exportResult.audio_audit_items)
  })

  it('wraps raw observed JSON in a non-final handoff while preserving blocked snapshots for recovery', () => {
    const fixture = completeFixture()
    const capture = reduceReleaseEvidenceRawSnapshot(emptyReleaseEvidenceRawSnapshot(), {
      type: 'learning_point_result',
      result: fixture.learningPointResult,
      jobId: 'extract-job',
    })

    const handoffArtifact = buildReleaseObservedRawSnapshotHandoffArtifact({
      capture,
      caseId: fixture.caseId,
      manifest: fixture.manifest,
      coldCacheReadsDisabled: true,
    })

    expect(handoffArtifact).toMatchObject({
      schema_kind: 'release_raw_observed_snapshot_handoff_audit',
      artifact_kind: 'raw_observed_snapshot_handoff',
      handoff_kind: 'raw_observed_snapshot_non_final_handoff',
      evidence_role: 'non_final_raw_observed_handoff',
      artifact_scope: 'raw_observed_input_only',
      matrix_eligibility: 'never',
      release_case_evidence: false,
      matrix_pass_created: false,
      matrix_pass_verified: false,
      write_requested: false,
      written_files: [],
      final_artifacts_written: false,
      case_id: fixture.caseId,
      status: 'captured_with_blockers',
    })
    expect(handoffArtifact.failed_checks).toEqual(
      expect.arrayContaining([
        'observed_project_missing',
        'observed_export_result_missing',
        'observed_anki_verify_result_missing',
      ]),
    )
    expect(handoffArtifact.raw_observed_json).toMatchObject({
      case_id: fixture.caseId,
      learning_point_result: fixture.learningPointResult,
      project: null,
      export_result: null,
      anki_verify_result: null,
      verified_export_apkg_path: null,
      cold_cache_reads_disabled: true,
      job_ids: { extraction: 'extract-job' },
    })
    expect(handoffArtifact.capture_state).toMatchObject({
      ok: false,
      present: {
        learning_point_result: true,
        project: false,
        export_result: false,
        anki_verify_result: false,
        verified_export_apkg_path: false,
      },
      job_ids: { extraction: 'extract-job' },
    })
    expect(handoffArtifact.final_artifacts).toEqual({
      timing_json_written: false,
      cache_summary_json_written: false,
      manifests_updated: false,
      matrix_summary_updated: false,
      apkg_created: false,
      anki_verified: false,
      computer_use_actions_created: false,
      screenshots_created: false,
    })
  })

  it('lets existing observed JSON adapters unwrap ready raw snapshot handoffs without making release evidence', () => {
    const fixture = completeFixture()
    const capture = completeRawCapture(fixture)
    const handoffArtifact = buildReleaseObservedRawSnapshotHandoffArtifact({
      capture,
      caseId: fixture.caseId,
      manifest: fixture.manifest,
      coldCacheReadsDisabled: true,
      sourceCacheProbeStatus: 'no_existing_url_cache_found',
    })

    const snapshot = buildReleaseObservedTimingCacheInputSnapshotFromJson({
      caseId: fixture.caseId,
      manifest: fixture.manifest,
      rawObserved: handoffArtifact,
    })

    expect(handoffArtifact.status).toBe('ready_for_downstream_validation')
    expect(handoffArtifact.release_case_evidence).toBe(false)
    expect(handoffArtifact.matrix_pass_created).toBe(false)
    expect(snapshot.ok).toBe(true)
    expect(snapshot.matrixPassCreated).toBe(false)
    expect(snapshot.observedInput).toMatchObject({
      caseId: fixture.caseId,
      coldCacheReadsDisabled: true,
      sourceCacheProbeStatus: 'no_existing_url_cache_found',
      exportResult: {
        apkg_path: fixture.exportResult.apkg_path,
        apkg_sha256: fixture.exportResult.apkg_sha256,
      },
      ankiVerifyResult: {
        card_count: fixture.ankiVerifyResult.card_count,
        timing_ms: fixture.ankiVerifyResult.timing_ms,
      },
    })
  })
})

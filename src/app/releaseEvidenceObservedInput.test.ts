import { describe, expect, it } from 'vitest'

import {
  buildVideoReleaseRunInitializerPlan,
  type VideoReleaseCaseId,
  type VideoReleaseCaseManifest,
} from '../domain/releaseEvidenceLayout'
import {
  buildReleaseTimingCacheArtifactWritePlan,
  type BuildReleaseTimingCacheArtifactsInput,
} from './releaseEvidenceArtifacts'
import { buildReleaseEvidenceSummary } from './releaseEvidenceSummary'
import {
  buildReleaseObservedTimingCacheInputSnapshot,
  buildReleaseObservedTimingCacheInputSnapshotFromJson,
  type BuildReleaseObservedTimingCacheInputSnapshotInput,
} from './releaseEvidenceObservedInput'

function manifestFor(caseId: VideoReleaseCaseId): VideoReleaseCaseManifest {
  const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
  return JSON.parse(
    plan.seedFiles.find((file) => file.relativePath === `cases/${caseId}/case_manifest.json`)?.content ?? '{}',
  )
}

function completeColdObservedInput(): BuildReleaseObservedTimingCacheInputSnapshotInput {
  const manifest = manifestFor('youtube_a_full1_cold')
  manifest.source_candidate = {
    url: 'https://www.youtube.com/watch?v=m7IlyBEyi3c',
    video_id: 'm7IlyBEyi3c',
    source_fingerprint: 'yt:779a15b6499710bd',
    material_manifest:
      'E:\\ANKI\\test_runs\\video_material_rotation_20260619_124902_slice104_verified_youtube_ab\\material_manifest.json',
    cache_probe_status: 'no_existing_url_cache_found',
  }

  return {
    caseId: 'youtube_a_full1_cold',
    manifest,
    verifiedExportApkgPath:
      'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542\\cases\\youtube_a_full1_cold\\apkg\\youtube_a_full1_cold.apkg',
    coldCacheReadsDisabled: true,
    learningPointResult: {
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
    },
    project: {
      quality_funnel: {
        card_count: 1,
        generation_timing_ms: { card_body_ms: 4 },
        card_generation_cache_read_enabled: false,
        card_generation_cache_write_enabled: true,
        card_generation_cache_hits: 0,
        card_generation_cache_misses: 1,
      },
    },
    exportResult: {
      apkg_path:
        'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542\\cases\\youtube_a_full1_cold\\apkg\\youtube_a_full1_cold.apkg',
      apkg_sha256: 'd'.repeat(64),
      apkg_size_bytes: 123456,
      apkg_mtime_ms: 1781740000000,
      source_identity: { source_fingerprint: 'yt:779a15b6499710bd', source_mode: 'url' },
      source_fingerprint: 'yt:779a15b6499710bd',
      cards: 1,
      deck_name: 'Video Release Smoke',
      media_manifest: {},
      media_ledger: [],
      card_media_ledger: [],
      audio_audit_items: [],
      timing_ms: {
        tts_ms: 5,
        media_slice_ms: 6,
        apkg_pack_ms: 7,
      },
      media_summary: {
        video_segments: 1,
        video_files: 1,
        original_audio_files: 1,
        sentence_tts_files: 1,
        phrase_tts_files: 1,
        media_files: 4,
        media_bytes: 400,
        media_mb: 0.4,
        tts_cache_hits: 0,
        tts_cache_misses: 2,
        tts_cache_total: 2,
        media_cache_hits: 0,
        media_cache_misses: 1,
        media_cache_total: 1,
      },
    },
    ankiVerifyResult: {
      ok: true,
      message: 'verified',
      failed_checks: [],
      apkg_path:
        'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542\\cases\\youtube_a_full1_cold\\apkg\\youtube_a_full1_cold.apkg',
      apkg_sha256: 'd'.repeat(64),
      apkg_size_bytes: 123456,
      apkg_mtime_ms: 1781740000000,
      source_identity: { source_fingerprint: 'yt:779a15b6499710bd', source_mode: 'url' },
      source_fingerprint: 'yt:779a15b6499710bd',
      card_count: 1,
      expected_cards: 1,
      deck_name: 'Video Release Smoke',
      timing_ms: { anki_verify_ms: 8 },
    },
  }
}

describe('releaseEvidenceObservedInput', () => {
  it('builds a raw observed snapshot that can feed the existing write plan without claiming matrix pass', () => {
    const snapshot = buildReleaseObservedTimingCacheInputSnapshot(completeColdObservedInput())

    expect(snapshot.ok).toBe(true)
    expect(snapshot.status).toBe('ready_for_write_plan')
    expect(snapshot.matrixPassCreated).toBe(false)
    expect(snapshot.failedChecks).toEqual([])
    expect(snapshot.observedInput).toMatchObject({
      caseId: 'youtube_a_full1_cold',
      coldCacheReadsDisabled: true,
    })

    if (!snapshot.observedInput) throw new Error('expected raw observed input')
    const plan = buildReleaseTimingCacheArtifactWritePlan({
      ...snapshot.observedInput,
      runDir: 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542',
    })

    expect(plan.ok).toBe(true)
    expect(plan.matrixPassCreated).toBe(false)
    expect(plan.writes).toHaveLength(2)
  })

  it('rejects release evidence summaries because they are display summaries, not raw timing/cache inputs', () => {
    const input = completeColdObservedInput()
    const artifactInput = input as BuildReleaseTimingCacheArtifactsInput
    const summary = buildReleaseEvidenceSummary({
      learningPointResult: artifactInput.learningPointResult as never,
      project: artifactInput.project as never,
      exportResult: artifactInput.exportResult as never,
      ankiVerifyResult: artifactInput.ankiVerifyResult as never,
    })

    const snapshot = buildReleaseObservedTimingCacheInputSnapshot({
      ...input,
      learningPointResult: summary,
    })

    expect(snapshot.ok).toBe(false)
    expect(snapshot.status).toBe('blocked')
    expect(snapshot.failedChecks).toContain('observed_release_evidence_summary_not_raw')
    expect(snapshot.observedInput).toBeNull()
  })

  it('rejects worker progress, Rust result summaries, and batch fragments before artifact planning', () => {
    const input = completeColdObservedInput()
    const exportResult = input.exportResult as NonNullable<BuildReleaseTimingCacheArtifactsInput['exportResult']>
    const snapshot = buildReleaseObservedTimingCacheInputSnapshot({
      ...input,
      learningPointResult: {
        command: 'extract_learning_points',
        stage: 'done',
        percent: 100,
        message: 'done',
      },
      project: {
        queueIds: ['lp1'],
        activeBatchIds: ['lp1'],
        totalBatches: 2,
        completedBatches: 1,
      },
      exportResult: {
        command: 'export',
        cards: 1,
        media_summary: exportResult.media_summary,
      },
    })

    expect(snapshot.ok).toBe(false)
    expect(snapshot.failedChecks).toEqual(
      expect.arrayContaining([
        'observed_worker_progress_not_raw',
        'observed_generation_batch_fragment_not_raw',
        'observed_worker_result_summary_not_raw',
      ]),
    )
    expect(snapshot.observedInput).toBeNull()
  })

  it('rejects compact UI export state because it is missing full export ledgers', () => {
    const input = completeColdObservedInput()
    const {
      audio_audit_items: _audioAuditItems,
      media_manifest: _mediaManifest,
      media_ledger: _mediaLedger,
      card_media_ledger: _cardMediaLedger,
      ...compactExport
    } = input.exportResult as Record<string, unknown>

    const snapshot = buildReleaseObservedTimingCacheInputSnapshot({
      ...input,
      exportResult: compactExport,
    })

    expect(snapshot.ok).toBe(false)
    expect(snapshot.failedChecks).toEqual(
      expect.arrayContaining([
        'observed_export_full_media_manifest_missing',
        'observed_export_full_media_ledger_missing',
        'observed_export_full_card_media_ledger_missing',
        'observed_export_full_audio_audit_items_missing',
      ]),
    )
    expect(snapshot.observedInput).toBeNull()
  })

  it('rejects incomplete multi-batch generation state until timing/cache aggregation exists', () => {
    const input = completeColdObservedInput()
    const snapshot = buildReleaseObservedTimingCacheInputSnapshot({
      ...input,
      project: {
        quality_funnel: {
          ...(input.project as BuildReleaseTimingCacheArtifactsInput['project'])?.quality_funnel,
          generation_reconciliation_status: 'partial',
          generation_missing_count: 1,
          generation_batch_count: 3,
          generation_batch_completed: 2,
        },
      },
    })

    expect(snapshot.ok).toBe(false)
    expect(snapshot.failedChecks).toEqual(
      expect.arrayContaining([
        'observed_generation_reconciliation_not_ok',
        'observed_generation_missing_count_nonzero',
        'observed_generation_timing_aggregate_missing',
        'observed_card_generation_cache_aggregate_missing',
        'observed_generation_batch_aggregate_missing',
        'observed_generation_batch_incomplete',
      ]),
    )
    expect(snapshot.observedInput).toBeNull()
  })

  it('allows multi-batch generation only when explicit aggregate timing/cache evidence is complete', () => {
    const input = completeColdObservedInput()
    const snapshot = buildReleaseObservedTimingCacheInputSnapshot({
      ...input,
      project: {
        quality_funnel: {
          ...(input.project as BuildReleaseTimingCacheArtifactsInput['project'])?.quality_funnel,
          generation_batch_count: 2,
          generation_batch_completed: 2,
          generation_timing_aggregate_batch_count: 2,
          generation_timing_aggregate_complete: true,
          card_generation_cache_aggregate_batch_count: 2,
          card_generation_cache_aggregate_complete: true,
          card_generation_cache_policy_consistent: true,
          card_generation_cache_namespace_consistent: true,
        },
      },
    })

    expect(snapshot.ok).toBe(true)
    expect(snapshot.failedChecks).toEqual([])
    expect(snapshot.observedInput).toMatchObject({
      caseId: 'youtube_a_full1_cold',
      project: {
        quality_funnel: {
          generation_batch_count: 2,
          generation_timing_aggregate_complete: true,
          card_generation_cache_aggregate_complete: true,
        },
      },
    })
  })

  it('rejects multi-batch aggregate evidence when completed batch count is missing', () => {
    const input = completeColdObservedInput()
    const snapshot = buildReleaseObservedTimingCacheInputSnapshot({
      ...input,
      project: {
        quality_funnel: {
          ...(input.project as BuildReleaseTimingCacheArtifactsInput['project'])?.quality_funnel,
          generation_batch_count: 2,
          generation_timing_aggregate_batch_count: 2,
          generation_timing_aggregate_complete: true,
          card_generation_cache_aggregate_batch_count: 2,
          card_generation_cache_aggregate_complete: true,
          card_generation_cache_policy_consistent: true,
          card_generation_cache_namespace_consistent: true,
        },
      },
    })

    expect(snapshot.ok).toBe(false)
    expect(snapshot.failedChecks).toContain('observed_generation_batch_incomplete')
    expect(snapshot.observedInput).toBeNull()
  })

  it('rejects stale Anki verify objects that no longer match the export result', () => {
    const input = completeColdObservedInput()
    const exportResult = input.exportResult as Record<string, unknown>
    const ankiVerifyResult = input.ankiVerifyResult as Record<string, unknown>
    const snapshot = buildReleaseObservedTimingCacheInputSnapshot({
      ...input,
      exportResult: {
        ...exportResult,
        deck_name: 'Current Deck',
      },
      verifiedExportApkgPath: 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542\\old.apkg',
      ankiVerifyResult: {
        ...ankiVerifyResult,
        expected_cards: 20,
        deck_name: 'Old Deck',
      },
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

  it('rejects Anki verify timing that did not come from a clean successful verify', () => {
    const input = completeColdObservedInput()
    const snapshot = buildReleaseObservedTimingCacheInputSnapshot({
      ...input,
      ankiVerifyResult: {
        ...(input.ankiVerifyResult as Record<string, unknown>),
        ok: false,
        failed_checks: ['missing_media'],
      },
    })

    expect(snapshot.ok).toBe(false)
    expect(snapshot.failedChecks).toEqual(
      expect.arrayContaining(['observed_anki_verify_not_ok', 'observed_anki_verify_failed_checks_present']),
    )
    expect(snapshot.observedInput).toBeNull()
  })

  it('rejects Anki verify timing when source identity is missing or stale', () => {
    const input = completeColdObservedInput()
    const missingSource = buildReleaseObservedTimingCacheInputSnapshot({
      ...input,
      ankiVerifyResult: {
        ...(input.ankiVerifyResult as Record<string, unknown>),
        source_identity: undefined,
        source_fingerprint: undefined,
      },
    })

    expect(missingSource.ok).toBe(false)
    expect(missingSource.failedChecks).toContain('observed_verify_source_fingerprint_missing')
    expect(missingSource.observedInput).toBeNull()

    const staleSource = buildReleaseObservedTimingCacheInputSnapshot({
      ...input,
      ankiVerifyResult: {
        ...(input.ankiVerifyResult as Record<string, unknown>),
        source_identity: { source_fingerprint: 'yt:stale0000000000', source_mode: 'url' },
        source_fingerprint: 'yt:stale0000000000',
      },
    })

    expect(staleSource.ok).toBe(false)
    expect(staleSource.failedChecks).toContain('observed_verify_source_fingerprint_mismatch')
    expect(staleSource.observedInput).toBeNull()
  })

  it('maps snake_case observed JSON through the same raw snapshot boundary used by the CLI', () => {
    const input = completeColdObservedInput()
    const snapshot = buildReleaseObservedTimingCacheInputSnapshotFromJson({
      caseId: 'youtube_a_full1_cold',
      manifest: input.manifest,
      rawObserved: {
        case_id: 'youtube_a_full1_cold',
        learning_point_result: input.learningPointResult,
        project: input.project,
        export_result: input.exportResult,
        anki_verify_result: input.ankiVerifyResult,
        verified_export_apkg_path: input.verifiedExportApkgPath,
        cold_cache_reads_disabled: true,
        source_cache_probe_status: 'no_existing_url_cache_found',
        existing_url_cache_dirs: [],
      },
    })

    expect(snapshot.ok).toBe(true)
    expect(snapshot.observedInput).toMatchObject({
      caseId: 'youtube_a_full1_cold',
      coldCacheReadsDisabled: true,
      sourceCacheProbeStatus: 'no_existing_url_cache_found',
    })
  })

  it('unwraps a non-final writer handoff audit through raw_observed_json without treating the audit as final evidence', () => {
    const input = completeColdObservedInput()
    const snapshot = buildReleaseObservedTimingCacheInputSnapshotFromJson({
      caseId: 'youtube_a_full1_cold',
      manifest: input.manifest,
      rawObserved: {
        schema_kind: 'release_timing_cache_writer_handoff_audit',
        handoff_kind: 'timing_cache_writer_dry_run_handoff',
        evidence_role: 'non_final_writer_handoff',
        artifact_scope: 'timing_cache_writer_only',
        matrix_eligibility: 'never',
        release_case_evidence: false,
        matrix_pass_created: false,
        matrix_pass_verified: false,
        case_id: 'youtube_a_full1_cold',
        write_requested: false,
        written_files: [],
        planned_writes: [{ kind: 'timing', relative_path: 'cases/youtube_a_full1_cold/timing.json' }],
        writer: { ok: true, failed_checks: [], warnings: [] },
        raw_observed_json: {
          case_id: 'youtube_a_full1_cold',
          learning_point_result: input.learningPointResult,
          project: input.project,
          export_result: input.exportResult,
          anki_verify_result: input.ankiVerifyResult,
          verified_export_apkg_path: input.verifiedExportApkgPath,
          cold_cache_reads_disabled: true,
        },
      },
    })

    expect(snapshot.ok).toBe(true)
    expect(snapshot.matrixPassCreated).toBe(false)
    expect(snapshot.observedInput).toMatchObject({
      caseId: 'youtube_a_full1_cold',
      coldCacheReadsDisabled: true,
    })
  })

  it('rejects unsafe writer handoff envelopes before unwrapped observed data can feed the writer', () => {
    const input = completeColdObservedInput()
    const snapshot = buildReleaseObservedTimingCacheInputSnapshotFromJson({
      caseId: 'youtube_a_full1_cold',
      manifest: input.manifest,
      rawObserved: {
        schema_kind: 'release_timing_cache_writer_handoff_audit',
        evidence_role: 'non_final_writer_handoff',
        matrix_eligibility: 'maybe',
        release_case_evidence: true,
        matrix_pass_created: true,
        matrix_pass_verified: true,
        case_id: 'youtube_a_full1_cold',
        write_requested: true,
        written_files: [
          'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542\\cases\\youtube_a_full1_cold\\timing.json',
        ],
        raw_observed_json: {
          case_id: 'youtube_a_full1_cold',
          learning_point_result: input.learningPointResult,
          project: input.project,
          export_result: input.exportResult,
          anki_verify_result: input.ankiVerifyResult,
          verified_export_apkg_path: input.verifiedExportApkgPath,
          cold_cache_reads_disabled: true,
        },
      },
    })

    expect(snapshot.ok).toBe(false)
    expect(snapshot.observedInput).toBeNull()
    expect(snapshot.failedChecks).toEqual(
      expect.arrayContaining([
        'observed_handoff_matrix_pass_created_not_false',
        'observed_handoff_matrix_pass_verified_not_false',
        'observed_handoff_write_requested_not_false',
        'observed_handoff_final_written_files_present',
        'observed_handoff_release_case_evidence_not_false',
        'observed_handoff_matrix_eligibility_not_never',
      ]),
    )
  })

  it('rejects case id mismatches in observed JSON before planning writes', () => {
    const input = completeColdObservedInput()
    const snapshot = buildReleaseObservedTimingCacheInputSnapshotFromJson({
      caseId: 'youtube_a_full1_cold',
      manifest: input.manifest,
      rawObserved: {
        case_id: 'local_srt_full1_cold',
        learning_point_result: input.learningPointResult,
        project: input.project,
        export_result: input.exportResult,
        anki_verify_result: input.ankiVerifyResult,
        verified_export_apkg_path: input.verifiedExportApkgPath,
      },
    })

    expect(snapshot.ok).toBe(false)
    expect(snapshot.failedChecks).toContain('observed_case_id_mismatch')
    expect(snapshot.observedInput).toBeNull()
  })
})

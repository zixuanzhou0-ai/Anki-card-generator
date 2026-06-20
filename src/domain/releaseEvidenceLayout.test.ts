import { describe, expect, it } from 'vitest'

import {
  VIDEO_RELEASE_CASES,
  VIDEO_RELEASE_CASE_EVIDENCE_ITEMS,
  buildVideoReleaseCaseCacheTimingPlan,
  buildVideoReleaseEvidenceLayout,
  buildVideoReleaseRunInitializerPlan,
  evaluateVideoReleaseCaseCompletionEvidence,
  evaluateVideoReleaseCaseStartPreflight,
  videoReleaseCaseEvidencePaths,
  videoReleaseRunDirName,
} from './releaseEvidenceLayout'

const COMPUTER_USE_SESSION_ID = 'computer-use-session-release-proof-1'
const SCREENSHOT_SHA256 = 'a'.repeat(64)
const OTHER_SCREENSHOT_SHA256 = 'b'.repeat(64)

function playbackActionRefs(index: number) {
  return {
    video: `card-${index}-video-click`,
    original_audio: `card-${index}-original-audio-click`,
    sentence_tts: `card-${index}-sentence-tts-click`,
    phrase_tts: `card-${index}-phrase-tts-click`,
  }
}

function screenshotFileName(index: number) {
  return `card${String(index).padStart(2, '0')}_before.png`
}

function screenshotFileEvidence(index: number, sha256 = SCREENSHOT_SHA256) {
  return {
    path: screenshotFileName(index),
    relative_path: `cases/youtube_a_full1_cold/screenshots/${screenshotFileName(index)}`,
    sha256,
    size_bytes: 128,
    mtime_ms: 1781880000000,
  }
}

function screenshotManifestFor(indices: number[]) {
  return indices.map((index) => ({
    screenshot_id: `card-${index}-before`,
    session_id: COMPUTER_USE_SESSION_ID,
    card_index: index,
    path: screenshotFileName(index),
    sha256: SCREENSHOT_SHA256,
  }))
}

function screenshotManifestArtifactFor(caseId: string, indices: number[], overrides: Record<string, unknown> = {}) {
  return {
    schema_version: 1,
    case_id: caseId,
    session_id: COMPUTER_USE_SESSION_ID,
    screenshots: screenshotManifestFor(indices),
    ...overrides,
  }
}

function fullObservationItem(index: number) {
  const screenshot = screenshotFileName(index)
  return {
    index,
    session_id: COMPUTER_USE_SESSION_ID,
    anki_card_observed: true,
    expected: {
      visible_answer: `answer ${index}`,
      source_sentence: `This is source sentence ${index}.`,
      source_time: '00:00:01.000 - 00:00:03.000',
      media_source_time: '00:00:01.000 - 00:00:03.000',
    },
    visible: {
      answer_seen: true,
      source_sentence_seen: true,
      time_seen: true,
      controls_seen: {
        video: true,
        phrase_tts: true,
        original_audio: true,
        sentence_tts: true,
      },
      visible_text_lines: [`answer ${index}`, `This is source sentence ${index}.`, '00:00:01.000 - 00:00:03.000'],
    },
    screenshots: {
      before: screenshot,
    },
    playback_action_refs: playbackActionRefs(index),
    checks: {
      no_wrong_audio: true,
      no_video_misalignment: true,
      no_field_mixing: true,
      no_missing_media: true,
      no_crash: true,
    },
    audio_claim: {
      computer_use_heard_speaker_audio: false,
      correctness_backing: ['audio_audit.verify.json', 'media_manifest', 'card_media_ledger', 'verify_anki_import'],
    },
  }
}

function computerUseActionsFor(caseId: string, indices: number[]) {
  const actions: Record<string, unknown>[] = []
  const playbackCounts = {
    video: 0,
    original_audio: 0,
    sentence_tts: 0,
    phrase_tts: 0,
  }
  for (const index of indices) {
    const refs = playbackActionRefs(index)
    for (const role of ['video', 'original_audio', 'sentence_tts', 'phrase_tts'] as const) {
      playbackCounts[role] += 1
      actions.push({
        order: actions.length + 1,
        action_id: refs[role],
        session_id: COMPUTER_USE_SESSION_ID,
        card_index: index,
        role,
        action: 'click',
        outcome: 'played',
        ok: true,
      })
    }
  }
  return {
    case_id: caseId,
    session_id: COMPUTER_USE_SESSION_ID,
    previewed_cards: indices.length,
    playback_counts: playbackCounts,
    actions,
  }
}

function writerHandoffArtifact(caseId = 'youtube_a_full1_cold') {
  return {
    schema_version: 1,
    schema_kind: 'release_timing_cache_writer_handoff_audit',
    artifact_kind: 'timing_cache_writer_handoff',
    handoff_kind: 'timing_cache_writer_dry_run_handoff',
    evidence_role: 'non_final_writer_handoff',
    artifact_scope: 'timing_cache_writer_only',
    matrix_eligibility: 'never',
    release_case_evidence: false,
    matrix_pass_created: false,
    matrix_pass_verified: false,
    case_id: caseId,
    write_requested: false,
    written_files: [],
    raw_observed_json: { case_id: caseId },
    planned_writes: [
      {
        kind: 'timing',
        relative_path: `cases/${caseId}/timing.json`,
        absolute_path: `E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542\\cases\\${caseId}\\timing.json`,
        write_mode: 'exclusive_create',
        bytes: 583,
      },
    ],
    writer: { ok: true, failed_checks: [], warnings: [] },
  }
}

function sourceCandidateFor(caseId: string) {
  if (caseId.startsWith('local_srt')) {
    return {
      video_path:
        'E:\\ANKI\\test_runs\\video_material_rotation_20260619_132237_slice109_local_srt_youtube_a_download\\url_01\\source.mp4',
      subtitle_path:
        'E:\\ANKI\\test_runs\\video_material_rotation_20260619_132237_slice109_local_srt_youtube_a_download\\url_01\\source.en-GB.srt',
      video_bytes: 10706306,
      subtitle_bytes: 9440,
      video_sha256: '968c50e3449f71a3f65bc945a7205d5cca4699b312fa28560a7adadaaec5c9d6',
      subtitle_sha256: '0ba2394c6d6bd9485a845d4f5b91209d06c9b04e44bab17b37803855d92314a4',
      source_fingerprint: 'file:968c50e3449f71a3',
      material_manifest:
        'E:\\ANKI\\test_runs\\video_material_rotation_20260619_132237_slice109_local_srt_youtube_a_download\\material_manifest.json',
      cache_probe_status: 'no_existing_url_cache_found',
    }
  }
  return {
    url: 'https://www.youtube.com/watch?v=m7IlyBEyi3c',
    video_id: 'm7IlyBEyi3c',
    source_fingerprint: 'yt:779a15b6499710bd',
    material_manifest:
      'E:\\ANKI\\test_runs\\video_material_rotation_20260619_124902_slice104_verified_youtube_ab\\material_manifest.json',
    cache_probe_status: 'no_existing_url_cache_found',
  }
}

function apkgEvidenceFor(caseId: string) {
  return {
    path: `E:\\ANKI\\test_runs\\video_release_hardening_20260619_045000\\cases\\${caseId}\\apkg\\${caseId}.apkg`,
    relative_path: `cases/${caseId}/apkg/${caseId}.apkg`,
    sha256: 'd'.repeat(64),
    size_bytes: 123456,
    mtime_ms: 1781740000000,
  }
}

function artifactIdentityFor(caseId: string) {
  return {
    case_id: caseId,
    source_fingerprint: sourceCandidateFor(caseId).source_fingerprint,
    apkg_relative_path: `cases/${caseId}/apkg/${caseId}.apkg`,
    apkg_sha256: 'd'.repeat(64),
    apkg_size_bytes: 123456,
    apkg_mtime_ms: 1781740000000,
  }
}

function sourceProvenanceFor(caseId: string) {
  const candidate = sourceCandidateFor(caseId) as Record<string, string | number | undefined>
  if (caseId.startsWith('local_srt')) {
    return {
      schema_version: 1,
      case_id: caseId,
      source_kind: 'local_video_srt',
      source_fingerprint: candidate.source_fingerprint,
      project_source_mode: 'local',
      manifest_video_path: candidate.video_path,
      manifest_subtitle_path: candidate.subtitle_path,
      project_video_path: candidate.video_path,
      project_subtitle_path: candidate.subtitle_path,
      project_video_fingerprint: 'abc123def456abc123def456',
      project_subtitle_fingerprint: 'def456abc123def456abc123',
      manifest_video_sha256: candidate.video_sha256,
      manifest_subtitle_sha256: candidate.subtitle_sha256,
      manifest_video_bytes: candidate.video_bytes,
      manifest_subtitle_bytes: candidate.subtitle_bytes,
    }
  }
  return {
    schema_version: 1,
    case_id: caseId,
    source_kind: 'youtube_url',
    source_fingerprint: candidate.source_fingerprint,
    project_source_mode: 'url',
    manifest_video_id: candidate.video_id,
    project_video_id: candidate.video_id,
    manifest_url: candidate.url,
    project_source_url: candidate.url,
    transcript_only: false,
    skip_video_slicing: false,
  }
}

describe('video release evidence layout', () => {
  it('keeps the final desktop and Anki matrix explicit', () => {
    expect(VIDEO_RELEASE_CASES.map((releaseCase) => releaseCase.id)).toEqual([
      'youtube_a_full1_cold',
      'youtube_a_quick20_cold',
      'youtube_a_quick20_hot',
      'youtube_b_quick20_cold',
      'local_srt_full1_cold',
      'local_srt_quick20_cold',
      'local_srt_quick20_hot',
      'stress_100_plus_one_click',
    ])

    expect(VIDEO_RELEASE_CASES.map((releaseCase) => releaseCase.sourceKind)).not.toContain('document')
  })

  it('captures the required card counts and inspection depth', () => {
    const byId = Object.fromEntries(VIDEO_RELEASE_CASES.map((releaseCase) => [releaseCase.id, releaseCase]))

    expect(byId.youtube_a_full1_cold).toMatchObject({
      sourceKind: 'youtube_url',
      mode: 'full',
      cacheState: 'cold',
      targetCardCount: 1,
      requiredPreviewCards: 1,
      inspection: 'all_cards',
    })
    expect(byId.youtube_a_quick20_hot).toMatchObject({
      mode: 'quick',
      cacheState: 'hot',
      targetCardCount: 20,
      requiredPreviewCards: 20,
    })
    expect(byId.local_srt_quick20_hot).toMatchObject({
      sourceKind: 'local_video_srt',
      mode: 'quick',
      cacheState: 'hot',
      targetCardCount: 20,
      requiredPreviewCards: 20,
    })
    expect(byId.stress_100_plus_one_click).toMatchObject({
      targetCardCount: 100,
      minimumGeneratedCards: 100,
      requiredPreviewCards: 10,
      inspection: 'sample_open_middle_end',
    })
  })

  it('requires the artifacts needed to prove APKG, Anki, audio, timing, cache, and screenshots', () => {
    expect(VIDEO_RELEASE_CASE_EVIDENCE_ITEMS.map((item) => item.key)).toEqual([
      'case_manifest',
      'apkg',
      'source_provenance',
      'deck_metadata',
      'anki_verify',
      'audio_audit',
      'timing',
      'cache_summary',
      'observations',
      'computer_use_actions',
      'screenshot_manifest',
      'screenshots',
    ])

    expect(videoReleaseCaseEvidencePaths('youtube_b_quick20_cold')).toEqual([
      'cases/youtube_b_quick20_cold/case_manifest.json',
      'cases/youtube_b_quick20_cold/apkg',
      'cases/youtube_b_quick20_cold/source_provenance.json',
      'cases/youtube_b_quick20_cold/deck_metadata.json',
      'cases/youtube_b_quick20_cold/anki_verify.stdout.json',
      'cases/youtube_b_quick20_cold/audio_audit.verify.json',
      'cases/youtube_b_quick20_cold/timing.json',
      'cases/youtube_b_quick20_cold/cache_summary.json',
      'cases/youtube_b_quick20_cold/observations.json',
      'cases/youtube_b_quick20_cold/computer_use_actions.json',
      'cases/youtube_b_quick20_cold/screenshots/manifest.json',
      'cases/youtube_b_quick20_cold/screenshots',
    ])
  })

  it('builds timestamped run directories and rejects ambiguous names', () => {
    expect(videoReleaseRunDirName('20260619_044200')).toBe('video_release_hardening_20260619_044200')
    expect(() => videoReleaseRunDirName('latest')).toThrow('YYYYMMDD_HHMMSS')

    const layout = buildVideoReleaseEvidenceLayout('20260619_044200')

    expect(layout.runDirName).toBe('video_release_hardening_20260619_044200')
    expect(layout.topLevelEvidence).toEqual(['matrix_summary.json', 'release_risk_report.md', 'run_observations.md'])
    expect(layout.cases).toHaveLength(8)
    expect(layout.cases[0].relativeDir).toBe('cases/youtube_a_full1_cold')
    expect(layout.cases[0].evidencePaths).toContain('cases/youtube_a_full1_cold/anki_verify.stdout.json')
  })

  it('builds a non-passing initializer plan for the final run directory', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')

    expect(plan.runDirName).toBe('video_release_hardening_20260619_045000')
    expect(plan.directories).toContain('cases/youtube_a_quick20_cold/apkg')
    expect(plan.directories).toContain('cases/youtube_a_quick20_cold/screenshots')
    expect(plan.directories).toContain('cases/stress_100_plus_one_click/screenshots')
    expect(plan.seedFiles.map((file) => file.relativePath)).toContain('matrix_summary.json')
    expect(plan.seedFiles.map((file) => file.relativePath)).toContain('release_risk_report.md')
    expect(plan.seedFiles.map((file) => file.relativePath)).toContain('run_observations.md')
    expect(plan.seedFiles.map((file) => file.relativePath)).toContain('cases/local_srt_quick20_hot/case_manifest.json')
  })

  it('seeds checklists without pretending verification artifacts already passed', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const seededPaths = plan.seedFiles.map((file) => file.relativePath)

    expect(seededPaths).not.toContain('cases/youtube_a_quick20_cold/anki_verify.stdout.json')
    expect(seededPaths).not.toContain('cases/youtube_a_quick20_cold/audio_audit.verify.json')
    expect(seededPaths).not.toContain('cases/youtube_a_quick20_cold/timing.json')

    const matrixSummary = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'matrix_summary.json')?.content ?? '{}',
    )
    expect(matrixSummary).toMatchObject({
      run_dir: 'video_release_hardening_20260619_045000',
      status: 'not_started',
      release_ready: false,
    })
    expect(matrixSummary.cases).toHaveLength(8)

    const stressManifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/stress_100_plus_one_click/case_manifest.json')
        ?.content ?? '{}',
    )
    expect(stressManifest).toMatchObject({
      case_id: 'stress_100_plus_one_click',
      status: 'not_started',
      target_card_count: 100,
      minimum_generated_cards: 100,
      required_preview_cards: 10,
      required_playback_checks: ['video', 'original_audio', 'sentence_tts', 'phrase_tts'],
      pass_criteria: {
        verify_anki_import_ok: true,
        failed_checks: [],
        media_hash_mismatch_count: 0,
        audio_audit_count_equals_video_card_count: true,
      },
    })
    expect(stressManifest.required_evidence).toContain('cases/stress_100_plus_one_click/anki_verify.stdout.json')
    expect(stressManifest.required_evidence).toContain('cases/stress_100_plus_one_click/audio_audit.verify.json')
  })

  it('preflights a YouTube A cold case only when live debug app and Computer Use evidence are available', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.source_candidate = {
      url: 'https://www.youtube.com/watch?v=m7IlyBEyi3c',
      video_id: 'm7IlyBEyi3c',
      source_fingerprint: 'yt:779a15b6499710bd',
      material_manifest:
        'E:\\ANKI\\test_runs\\video_material_rotation_20260619_124902_slice104_verified_youtube_ab\\material_manifest.json',
      cache_probe_status: 'no_existing_url_cache_found',
    }
    const launcherReadiness = {
      ready_for_release_matrix: true,
      failed_checks: [],
      vite_ready: true,
      vite_still_ready: true,
      tauri_is_expected_debug_executable: true,
      tauri_still_running: true,
      webview_pid: 71036,
      window_pid: 7808,
      window_bound_to_tauri_pid: true,
    }

    const ready = evaluateVideoReleaseCaseStartPreflight({
      caseId: 'youtube_a_full1_cold',
      manifest,
      launcherReadiness,
      computerUseAvailable: true,
      coldCacheReadsDisabled: true,
    })

    expect(ready).toMatchObject({
      ok: true,
      failedChecks: [],
    })
    expect(ready.requiredEvidence).toContain('cases/youtube_a_full1_cold/computer_use_actions.json')

    const withoutComputerUse = evaluateVideoReleaseCaseStartPreflight({
      caseId: 'youtube_a_full1_cold',
      manifest,
      launcherReadiness,
      computerUseAvailable: false,
      coldCacheReadsDisabled: true,
    })

    expect(withoutComputerUse.ok).toBe(false)
    expect(withoutComputerUse.failedChecks).toContain('computer_use_unavailable')

    const withoutColdCacheReadDisable = evaluateVideoReleaseCaseStartPreflight({
      caseId: 'youtube_a_full1_cold',
      manifest,
      launcherReadiness,
      computerUseAvailable: true,
    })

    expect(withoutColdCacheReadDisable.ok).toBe(false)
    expect(withoutColdCacheReadDisable.failedChecks).toContain('cold_youtube_requires_disabled_cache_reads')
  })

  it('blocks cold YouTube timing when the candidate may already have cache unless cache reads are disabled', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_b_quick20_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.source_candidate = {
      url: 'https://www.youtube.com/watch?v=vOuhs1mA0xo',
      video_id: 'vOuhs1mA0xo',
      source_fingerprint: 'yt:21aa74fa7215f3d8',
      material_manifest:
        'E:\\ANKI\\test_runs\\video_material_rotation_20260619_124902_slice104_verified_youtube_ab\\material_manifest.json',
      cache_probe_status: 'possible_existing_cache',
    }
    const launcherReadiness = {
      ready_for_release_matrix: true,
      failed_checks: [],
      vite_ready: true,
      vite_still_ready: true,
      tauri_is_expected_debug_executable: true,
      tauri_still_running: true,
      webview_pid: 71036,
      window_pid: 7808,
      window_bound_to_tauri_pid: true,
    }

    const blocked = evaluateVideoReleaseCaseStartPreflight({
      caseId: 'youtube_b_quick20_cold',
      manifest,
      launcherReadiness,
      computerUseAvailable: true,
    })

    expect(blocked.ok).toBe(false)
    expect(blocked.failedChecks).toContain('cold_youtube_requires_disabled_cache_reads')
    expect(blocked.failedChecks).toContain('cold_youtube_possible_cache_requires_disabled_cache_reads')

    const allowedWithDisabledCacheReads = evaluateVideoReleaseCaseStartPreflight({
      caseId: 'youtube_b_quick20_cold',
      manifest,
      launcherReadiness,
      computerUseAvailable: true,
      coldCacheReadsDisabled: true,
    })

    expect(allowedWithDisabledCacheReads.failedChecks).not.toContain('cold_youtube_requires_disabled_cache_reads')
    expect(allowedWithDisabledCacheReads.failedChecks).not.toContain(
      'cold_youtube_possible_cache_requires_disabled_cache_reads',
    )
  })

  it('plans cold YouTube cache and timing evidence without pretending observations exist', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.source_candidate = {
      url: 'https://www.youtube.com/watch?v=m7IlyBEyi3c',
      video_id: 'm7IlyBEyi3c',
      source_fingerprint: 'yt:779a15b6499710bd',
      material_manifest:
        'E:\\ANKI\\test_runs\\video_material_rotation_20260619_124902_slice104_verified_youtube_ab\\material_manifest.json',
      cache_probe_status: 'no_existing_url_cache_found',
    }

    const cacheTimingPlan = buildVideoReleaseCaseCacheTimingPlan({
      caseId: 'youtube_a_full1_cold',
      manifest,
      coldCacheReadsDisabled: true,
      existingUrlCacheDirs: [],
    })

    expect(cacheTimingPlan).toMatchObject({
      status: 'planned_not_observed',
      matrix_pass_created: false,
      declared_cache_state: 'cold',
      source_cache_probe_status: 'no_existing_url_cache_found',
      cold_cache_reads_disabled: true,
      cold_claim_scope: 'source_probe_clean_ai_card_cache_reads_disabled',
      planned_payload_flags: {
        disable_ai_review_cache_read: true,
        disable_ai_review_cache_write: false,
        disable_card_generation_cache_read: true,
        disable_card_generation_cache_write: false,
      },
      artifact_paths: {
        timing: 'cases/youtube_a_full1_cold/timing.json',
        cache_summary: 'cases/youtube_a_full1_cold/cache_summary.json',
      },
    })
    expect(cacheTimingPlan.required_timing_fields).toContain('per_card_ms')
    expect(cacheTimingPlan.required_cache_summary_fields).toContain('card_generation_cache.misses')
  })

  it('labels possible source cache separately from disabled AI/card cache reads', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_b_quick20_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.source_candidate = {
      url: 'https://www.youtube.com/watch?v=vOuhs1mA0xo',
      video_id: 'vOuhs1mA0xo',
      source_fingerprint: 'yt:21aa74fa7215f3d8',
      material_manifest:
        'E:\\ANKI\\test_runs\\video_material_rotation_20260619_124902_slice104_verified_youtube_ab\\material_manifest.json',
      cache_probe_status: 'possible_existing_cache',
    }

    const blockedPlan = buildVideoReleaseCaseCacheTimingPlan({
      caseId: 'youtube_b_quick20_cold',
      manifest,
      coldCacheReadsDisabled: false,
      existingUrlCacheDirs: ['E:\\ANKI\\projects\\url_cache\\url_89fa2c5b'],
    })
    expect(blockedPlan.cold_claim_scope).toBe('invalid_until_cache_reads_disabled')
    expect(blockedPlan.planned_payload_flags.disable_ai_review_cache_read).toBe(false)

    const disabledPlan = buildVideoReleaseCaseCacheTimingPlan({
      caseId: 'youtube_b_quick20_cold',
      manifest,
      coldCacheReadsDisabled: true,
      existingUrlCacheDirs: ['E:\\ANKI\\projects\\url_cache\\url_89fa2c5b'],
    })
    expect(disabledPlan.cold_claim_scope).toBe('ai_card_cache_cold_source_cache_possible')
    expect(disabledPlan.existing_url_cache_dirs).toEqual(['E:\\ANKI\\projects\\url_cache\\url_89fa2c5b'])
    expect(disabledPlan.planned_payload_flags.disable_card_generation_cache_read).toBe(true)
  })

  it('blocks local video plus SRT cases until material paths and cold cache policy are explicit', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/local_srt_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    const launcherReadiness = {
      ready_for_release_matrix: true,
      failed_checks: [],
      vite_ready: true,
      vite_still_ready: true,
      tauri_is_expected_debug_executable: true,
      tauri_still_running: true,
      webview_pid: 71036,
      window_pid: 7808,
      window_bound_to_tauri_pid: true,
    }

    const missingSource = evaluateVideoReleaseCaseStartPreflight({
      caseId: 'local_srt_full1_cold',
      manifest,
      launcherReadiness,
      computerUseAvailable: true,
      coldCacheReadsDisabled: true,
    })
    expect(missingSource.ok).toBe(false)
    expect(missingSource.failedChecks).toContain('local_srt_source_candidate_missing')

    manifest.source_candidate = {
      downloaded_video_path:
        'E:\\ANKI\\test_runs\\video_material_rotation_20260614_160531_rc_candidates_bbc_teded_sublangs\\url_01\\source.mp4',
      subtitle_path:
        'E:\\ANKI\\test_runs\\video_material_rotation_20260614_160531_rc_candidates_bbc_teded_sublangs\\url_01\\source.en-GB.srt',
      source_fingerprint: 'file:285b15cc10916ac5',
      material_manifest:
        'E:\\ANKI\\test_runs\\video_material_rotation_20260614_160531_rc_candidates_bbc_teded_sublangs\\material_manifest.json',
    }

    const missingFileEvidence = evaluateVideoReleaseCaseStartPreflight({
      caseId: 'local_srt_full1_cold',
      manifest,
      launcherReadiness,
      computerUseAvailable: true,
      coldCacheReadsDisabled: true,
    })
    expect(missingFileEvidence.ok).toBe(false)
    expect(missingFileEvidence.failedChecks).toContain('local_srt_source_candidate_video_bytes_missing')
    expect(missingFileEvidence.failedChecks).toContain('local_srt_source_candidate_subtitle_bytes_missing')
    expect(missingFileEvidence.failedChecks).toContain('local_srt_source_candidate_video_sha256_missing')
    expect(missingFileEvidence.failedChecks).toContain('local_srt_source_candidate_subtitle_sha256_missing')

    manifest.source_candidate = {
      downloaded_video_path:
        'E:\\ANKI\\test_runs\\video_material_rotation_20260614_160531_rc_candidates_bbc_teded_sublangs\\url_01\\source.mp4',
      subtitle_path:
        'E:\\ANKI\\test_runs\\video_material_rotation_20260614_160531_rc_candidates_bbc_teded_sublangs\\url_01\\source.en-GB.srt',
      video_bytes: 123456,
      subtitle_bytes: 4567,
      video_sha256: 'a'.repeat(64),
      subtitle_sha256: 'b'.repeat(64),
      source_fingerprint: 'file:285b15cc10916ac5',
      material_manifest:
        'E:\\ANKI\\test_runs\\video_material_rotation_20260614_160531_rc_candidates_bbc_teded_sublangs\\material_manifest.json',
    }

    const missingColdCachePolicy = evaluateVideoReleaseCaseStartPreflight({
      caseId: 'local_srt_full1_cold',
      manifest,
      launcherReadiness,
      computerUseAvailable: true,
    })
    expect(missingColdCachePolicy.ok).toBe(false)
    expect(missingColdCachePolicy.failedChecks).toContain('cold_local_srt_requires_disabled_cache_reads')

    const ready = evaluateVideoReleaseCaseStartPreflight({
      caseId: 'local_srt_full1_cold',
      manifest,
      launcherReadiness,
      computerUseAvailable: true,
      coldCacheReadsDisabled: true,
    })
    expect(ready.failedChecks).not.toContain('local_srt_source_candidate_missing')
    expect(ready.failedChecks).not.toContain('cold_local_srt_requires_disabled_cache_reads')
  })

  it('plans local video plus SRT cache and timing evidence as local cold AI/card cache only', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/local_srt_quick20_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.source_candidate = {
      downloaded_video_path:
        'E:\\ANKI\\test_runs\\video_material_rotation_20260614_160531_rc_candidates_bbc_teded_sublangs\\url_01\\source.mp4',
      subtitle_path:
        'E:\\ANKI\\test_runs\\video_material_rotation_20260614_160531_rc_candidates_bbc_teded_sublangs\\url_01\\source.en-GB.srt',
      video_bytes: 123456,
      subtitle_bytes: 4567,
      video_sha256: 'a'.repeat(64),
      subtitle_sha256: 'b'.repeat(64),
      source_fingerprint: 'file:285b15cc10916ac5',
      material_manifest:
        'E:\\ANKI\\test_runs\\video_material_rotation_20260614_160531_rc_candidates_bbc_teded_sublangs\\material_manifest.json',
    }

    const cacheTimingPlan = buildVideoReleaseCaseCacheTimingPlan({
      caseId: 'local_srt_quick20_cold',
      manifest,
      coldCacheReadsDisabled: true,
    })

    expect(cacheTimingPlan).toMatchObject({
      declared_cache_state: 'cold',
      source_kind: 'local_video_srt',
      target_card_count: 20,
      cold_cache_reads_disabled: true,
      cold_claim_scope: 'source_probe_clean_ai_card_cache_reads_disabled',
      planned_payload_flags: {
        disable_ai_review_cache_read: true,
        disable_card_generation_cache_read: true,
      },
      artifact_paths: {
        timing: 'cases/local_srt_quick20_cold/timing.json',
        cache_summary: 'cases/local_srt_quick20_cold/cache_summary.json',
      },
    })
  })

  it('does not allow an empty final-matrix skeleton to count as completed evidence', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
    })

    expect(completion.ok).toBe(false)
    expect(completion.failedChecks).toContain('case_manifest_not_passed')
    expect(completion.failedChecks).toContain('apkg_missing')
    expect(completion.failedChecks).toContain('source_provenance_missing')
    expect(completion.failedChecks).toContain('anki_verify_missing')
    expect(completion.failedChecks).toContain('audio_audit_missing')
    expect(completion.failedChecks).toContain('timing_missing')
    expect(completion.failedChecks).toContain('cache_summary_missing')
    expect(completion.failedChecks).toContain('observations_missing')
    expect(completion.failedChecks).toContain('computer_use_actions_missing')
    expect(completion.failedChecks).toContain('screenshots_below_required_preview_count')
  })

  it('does not accept Computer Use playback summary counters without raw card-indexed action coverage', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
      computerUseActions: {
        case_id: 'youtube_a_full1_cold',
        previewed_cards: 1,
        playback_counts: {
          video: 1,
          original_audio: 1,
          sentence_tts: 1,
          phrase_tts: 1,
        },
        actions: [{ order: 1, card_index: 1, role: 'video', ok: true }],
      },
    })

    expect(completion.failedChecks).toContain('computer_use_action_trace_missing_required_playback_coverage')
  })

  it('rejects Computer Use action rows without explicit successful click/play outcomes', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'
    const computerUseActions = computerUseActionsFor('youtube_a_full1_cold', [1])
    for (const action of computerUseActions.actions) {
      delete action.outcome
    }

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
      computerUseActions,
    })

    expect(completion.failedChecks).toContain('computer_use_action_rows_missing_explicit_successful_playback_outcome')
    expect(completion.failedChecks).toContain('computer_use_action_trace_missing_required_playback_coverage')
  })

  it('rejects Computer Use action rows with duplicate or non-positive order values', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'
    const computerUseActions = computerUseActionsFor('youtube_a_full1_cold', [1])
    computerUseActions.actions[0].order = 0
    computerUseActions.actions[1].order = 1
    computerUseActions.actions[2].order = 1

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
      computerUseActions,
    })

    expect(completion.failedChecks).toContain('computer_use_action_order_not_positive_unique')
    expect(completion.failedChecks).toContain('computer_use_action_trace_missing_required_playback_coverage')
  })

  it('rejects Computer Use playback rows whose role is not explicit', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'
    const computerUseActions = computerUseActionsFor('youtube_a_full1_cold', [1])
    for (const action of computerUseActions.actions) {
      action.kind = action.role
      delete action.role
    }

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
      computerUseActions,
    })

    expect(completion.failedChecks).toContain('computer_use_action_role_missing_or_invalid')
    expect(completion.failedChecks).toContain('computer_use_action_trace_missing_required_playback_coverage')
  })

  it('rejects Computer Use action rows outside the case card-index range', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'
    const computerUseActions = computerUseActionsFor('youtube_a_full1_cold', [1])
    for (const action of computerUseActions.actions) {
      action.card_index = 2
    }

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
      computerUseActions,
    })

    expect(completion.failedChecks).toContain('computer_use_action_card_index_out_of_bounds')
    expect(completion.failedChecks).toContain('computer_use_action_trace_missing_required_playback_coverage')
  })

  it('derives Computer Use playback counts from valid action rows instead of trusting playback_counts', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'
    const computerUseActions = computerUseActionsFor('youtube_a_full1_cold', [1])
    computerUseActions.playback_counts.video = 2

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
      computerUseActions,
    })

    expect(completion.failedChecks).toContain('computer_use_playback_counts_disagree_with_action_trace')
    expect(completion.failedChecks).not.toContain('computer_use_action_trace_missing_required_playback_coverage')
  })

  it('rejects observations and Computer Use actions from different sessions', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'
    const computerUseActions = computerUseActionsFor('youtube_a_full1_cold', [1])
    computerUseActions.session_id = 'computer-use-session-other'
    for (const action of computerUseActions.actions) {
      action.session_id = 'computer-use-session-other'
    }

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
      screenshotFiles: ['card01_before.png'],
      screenshotManifest: screenshotManifestArtifactFor('youtube_a_full1_cold', [1]),
      observations: {
        case_id: 'youtube_a_full1_cold',
        session_id: COMPUTER_USE_SESSION_ID,
        count: 1,
        observations: [fullObservationItem(1)],
      },
      computerUseActions,
    })

    expect(completion.failedChecks).toContain('computer_use_session_id_mismatch')
    expect(completion.failedChecks).not.toContain('computer_use_action_trace_missing_required_playback_coverage')
  })

  it('rejects Computer Use action rows without the declared session id', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'
    const computerUseActions = computerUseActionsFor('youtube_a_full1_cold', [1])
    delete computerUseActions.actions[0].session_id

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
      computerUseActions,
    })

    expect(completion.failedChecks).toContain('computer_use_action_session_id_missing_or_mismatch')
    expect(completion.failedChecks).not.toContain('computer_use_action_trace_missing_required_playback_coverage')
  })

  it('rejects full observations without a screenshot manifest', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
      screenshotFiles: ['card01_before.png'],
      observations: {
        case_id: 'youtube_a_full1_cold',
        session_id: COMPUTER_USE_SESSION_ID,
        count: 1,
        observations: [fullObservationItem(1)],
      },
      computerUseActions: computerUseActionsFor('youtube_a_full1_cold', [1]),
    })

    expect(completion.failedChecks).toContain('screenshot_manifest_missing')
    expect(completion.failedChecks).not.toContain('observations_missing_required_full_card_evidence')
  })

  it('rejects observation screenshots that are not backed by the screenshot manifest', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
      screenshotFiles: ['card01_before.png'],
      screenshotManifest: screenshotManifestArtifactFor('youtube_a_full1_cold', [], {
        screenshots: [
          {
            screenshot_id: 'wrong-card-before',
            session_id: COMPUTER_USE_SESSION_ID,
            card_index: 1,
            path: 'wrong_card_before.png',
            sha256: SCREENSHOT_SHA256,
          },
        ],
      }),
      observations: {
        case_id: 'youtube_a_full1_cold',
        session_id: COMPUTER_USE_SESSION_ID,
        count: 1,
        observations: [fullObservationItem(1)],
      },
      computerUseActions: computerUseActionsFor('youtube_a_full1_cold', [1]),
    })

    expect(completion.failedChecks).toContain('screenshot_manifest_entry_invalid')
    expect(completion.failedChecks).toContain('screenshot_manifest_file_not_found')
    expect(completion.failedChecks).toContain('observations_item_screenshot_not_in_manifest')
    expect(completion.failedChecks).not.toContain('observations_item_screenshot_not_found')
  })

  it('accepts nested observation screenshot metadata without treating hashes as screenshot references', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'
    const screenshot = screenshotFileName(1)
    const observation = {
      ...fullObservationItem(1),
      screenshots: {
        after_playback: screenshot,
        after_playback_relative_path: `cases/youtube_a_full1_cold/screenshots/${screenshot}`,
        after_playback_sha256: SCREENSHOT_SHA256,
      },
    }

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
      screenshotFiles: [screenshotFileEvidence(1)],
      screenshotManifest: screenshotManifestArtifactFor('youtube_a_full1_cold', [1]),
      observations: {
        case_id: 'youtube_a_full1_cold',
        session_id: COMPUTER_USE_SESSION_ID,
        count: 1,
        observations: [observation],
      },
      computerUseActions: computerUseActionsFor('youtube_a_full1_cold', [1]),
    })

    expect(completion.failedChecks).not.toContain('observations_item_screenshot_not_in_manifest')
    expect(completion.failedChecks).not.toContain('observations_item_screenshot_not_found')
  })

  it('rejects observation screenshots whose manifest card index points at a different card', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_quick20_cold/case_manifest.json')
        ?.content ?? '{}',
    )
    manifest.status = 'passed'

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_quick20_cold',
      manifest,
      screenshotFiles: ['card01_before.png'],
      screenshotManifest: screenshotManifestArtifactFor('youtube_a_quick20_cold', [], {
        screenshots: [
          {
            ...screenshotManifestFor([1])[0],
            card_index: 2,
          },
        ],
      }),
      observations: {
        case_id: 'youtube_a_quick20_cold',
        session_id: COMPUTER_USE_SESSION_ID,
        count: 1,
        observations: [fullObservationItem(1)],
      },
      computerUseActions: computerUseActionsFor('youtube_a_quick20_cold', [1]),
    })

    expect(completion.failedChecks).toContain('observations_item_screenshot_card_index_mismatch')
    expect(completion.failedChecks).not.toContain('observations_item_screenshot_not_in_manifest')
  })

  it('rejects screenshot manifests whose sha256 does not match the actual screenshot file', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
      screenshotFiles: [screenshotFileEvidence(1, OTHER_SCREENSHOT_SHA256)],
      screenshotManifest: screenshotManifestArtifactFor('youtube_a_full1_cold', [1]),
      observations: {
        case_id: 'youtube_a_full1_cold',
        session_id: COMPUTER_USE_SESSION_ID,
        count: 1,
        observations: [fullObservationItem(1)],
      },
      computerUseActions: computerUseActionsFor('youtube_a_full1_cold', [1]),
    })

    expect(completion.failedChecks).toContain('screenshot_manifest_sha256_mismatch')
    expect(completion.failedChecks).not.toContain('screenshot_manifest_file_not_found')
  })

  it('rejects screenshot manifest entries that reuse one screenshot file for multiple card indices', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_quick20_cold/case_manifest.json')
        ?.content ?? '{}',
    )
    manifest.status = 'passed'

    const sharedScreenshot = 'shared_card_preview.png'
    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_quick20_cold',
      manifest,
      screenshotFiles: [
        {
          path: sharedScreenshot,
          relative_path: `cases/youtube_a_quick20_cold/screenshots/${sharedScreenshot}`,
          sha256: SCREENSHOT_SHA256,
          size_bytes: 128,
          mtime_ms: 1781880000000,
        },
      ],
      screenshotManifest: screenshotManifestArtifactFor('youtube_a_quick20_cold', [], {
        screenshots: [
          {
            screenshot_id: 'card-1-before',
            session_id: COMPUTER_USE_SESSION_ID,
            card_index: 1,
            path: sharedScreenshot,
            sha256: SCREENSHOT_SHA256,
          },
          {
            screenshot_id: 'card-2-before',
            session_id: COMPUTER_USE_SESSION_ID,
            card_index: 2,
            path: sharedScreenshot,
            sha256: SCREENSHOT_SHA256,
          },
        ],
      }),
    })

    expect(completion.failedChecks).toContain('screenshot_manifest_file_reused_for_multiple_card_indices')
    expect(completion.failedChecks).not.toContain('screenshot_manifest_file_not_found')
  })

  it('rejects completed evidence when observations contain only card indices', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
      screenshotFiles: ['card01_before.png'],
      observations: {
        case_id: 'youtube_a_full1_cold',
        count: 1,
        observations: [{ index: 1 }],
      },
    })

    expect(completion.ok).toBe(false)
    expect(completion.failedChecks).toContain('observations_missing_required_full_card_evidence')
    expect(completion.failedChecks).toContain('observations_missing_required_card_indices')
  })

  it('rejects full observations that do not link to raw Computer Use action rows', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'
    const observationWithoutActionLinks = fullObservationItem(1)
    delete (observationWithoutActionLinks as Record<string, unknown>).playback_action_refs

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
      screenshotFiles: ['card01_before.png'],
      screenshotManifest: screenshotManifestArtifactFor('youtube_a_full1_cold', [1]),
      observations: {
        case_id: 'youtube_a_full1_cold',
        session_id: COMPUTER_USE_SESSION_ID,
        count: 1,
        observations: [observationWithoutActionLinks],
      },
      computerUseActions: computerUseActionsFor('youtube_a_full1_cold', [1]),
    })

    expect(completion.ok).toBe(false)
    expect(completion.failedChecks).toContain('observations_missing_computer_use_action_links')
    expect(completion.failedChecks).toContain('observations_missing_required_card_indices')
    expect(completion.failedChecks).not.toContain('computer_use_action_trace_missing_required_playback_coverage')
  })

  it('rejects writer handoff audits if they are placed into final case evidence slots', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'
    const handoff = writerHandoffArtifact()

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
      sourceProvenance: handoff,
      ankiVerify: handoff,
      timing: handoff,
      cacheSummary: handoff,
      observations: handoff,
      computerUseActions: handoff,
    })

    expect(completion.ok).toBe(false)
    expect(completion.failedChecks).toEqual(
      expect.arrayContaining([
        'source_provenance_writer_handoff_artifact_present',
        'anki_verify_writer_handoff_artifact_present',
        'timing_writer_handoff_artifact_present',
        'cache_summary_writer_handoff_artifact_present',
        'observations_writer_handoff_artifact_present',
        'computer_use_writer_handoff_artifact_present',
      ]),
    )
  })

  it('rejects final artifacts that do not match the canonical APKG and source identity', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'
    manifest.source_candidate = sourceCandidateFor('youtube_a_full1_cold')
    const identity = artifactIdentityFor('youtube_a_full1_cold')

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
      apkgFiles: [apkgEvidenceFor('youtube_a_full1_cold')],
      sourceProvenance: {
        ...sourceProvenanceFor('youtube_a_full1_cold'),
        source_fingerprint: 'yt:eeeeeeeeeeeeeeee',
      },
      deckMetadata: {
        ...identity,
        apkg_sha256: 'e'.repeat(64),
        deck_name: '视频语言卡 - release proof',
        model_name: 'Anki Card Generator V12 - 沉浸复读 V11',
        card_count: 1,
      },
      ankiVerify: {
        ...identity,
        source_fingerprint: 'yt:ffffffffffffffff',
        ok: true,
        import_attempted: true,
        import_result: true,
        failed_checks: [],
        card_count: 1,
        expected_cards: 1,
        imported_card_count: 1,
        card_media_ledger_count: 1,
        media_count_expected: 4,
        media_count_referenced: 4,
        media_count_checked: 4,
        mismatched_media: [],
        missing_media: [],
        audio_audit_mismatches: [],
        card_media_ledger_mismatches: [],
        media_ledger_card_text_mismatches: [],
        unexpected_media_references: [],
        unreferenced_expected_media: [],
        ledger_text_hash_mismatch: [],
        missing_video_field_media: [],
        imported_tts_text_hash_mismatch: [],
        inaccessible_media: [],
        ledger_missing_manifest: [],
        manifest_tts_without_ledger: [],
        audio_audit_write_errors: [],
        ciba_model_names: [],
        video_template_mismatches: [],
        document_template_mismatches: [],
        audio_audit_summary: {
          status: 'passed',
          items: 1,
          expected_items: 1,
        },
      },
      timing: {
        ...identity,
        apkg_relative_path: 'cases/youtube_a_full1_cold/apkg/stale.apkg',
        schema_version: 1,
        declared_cache_state: 'cold',
        observed_cache_state: 'cold',
        source_prepare_ms: 1,
        learning_point_extract_ms: 2,
        ai_review_ms: 3,
        card_body_ms: 4,
        tts_ms: 5,
        media_slice_ms: 6,
        apkg_pack_ms: 7,
        anki_verify_ms: 8,
        total_ms: 36,
        timing_card_count: 1,
        per_card_ms: 36,
        stage_per_card_ms: {
          card_body: 4,
          tts: 5,
          media_slice: 6,
          apkg_pack: 7,
          anki_verify: 8,
          total: 36,
        },
        bottleneck_stage: 'anki_verify',
        bottleneck_ms: 8,
      },
      cacheSummary: {
        ...identity,
        apkg_sha256: 'f'.repeat(64),
        schema_version: 1,
        declared_cache_state: 'cold',
        observed_cache_state: 'cold',
        source_cache_probe_status: 'no_existing_url_cache_found',
        existing_url_cache_dirs: [],
        cold_cache_reads_disabled: true,
        cold_claim_scope: 'source_probe_clean_ai_card_cache_reads_disabled',
        ai_review_cache: { read_enabled: false, write_enabled: true, hits: 0, misses: 1, total: 1 },
        card_generation_cache: { read_enabled: false, write_enabled: true, hits: 0, misses: 1, total: 1 },
        tts_cache: { hits: 0, misses: 2, total: 2 },
        media_cache: { hits: 0, misses: 1, total: 1 },
      },
    })

    expect(completion.ok).toBe(false)
    expect(completion.failedChecks).toEqual(
      expect.arrayContaining([
        'deck_metadata_apkg_sha256_mismatch',
        'source_provenance_source_fingerprint_mismatch',
        'anki_verify_source_fingerprint_mismatch',
        'timing_apkg_path_mismatch',
        'cache_summary_apkg_sha256_mismatch',
      ]),
    )
  })

  it('rejects a direct APKG file whose name is not the canonical case id', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'
    manifest.source_candidate = sourceCandidateFor('youtube_a_full1_cold')

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
      apkgFiles: [
        {
          ...apkgEvidenceFor('youtube_a_full1_cold'),
          path: 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_045000\\cases\\youtube_a_full1_cold\\apkg\\case.apkg',
          relative_path: 'cases/youtube_a_full1_cold/apkg/case.apkg',
        },
      ],
    })

    expect(completion.ok).toBe(false)
    expect(completion.failedChecks).toContain('apkg_canonical_filename_mismatch')
    expect(completion.failedChecks).toContain('deck_metadata_missing')
  })

  it('rejects all-card completion when every observation is index-only', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_quick20_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_quick20_cold',
      manifest,
      screenshotFiles: Array.from({ length: 20 }, (_, index) => `card${String(index + 1).padStart(2, '0')}_before.png`),
      observations: {
        case_id: 'youtube_a_quick20_cold',
        count: 20,
        observations: Array.from({ length: 20 }, (_, index) => ({ index: index + 1 })),
      },
    })

    expect(completion.ok).toBe(false)
    expect(completion.failedChecks).toContain('observations_missing_required_full_card_evidence')
    expect(completion.failedChecks).toContain('observations_missing_required_card_indices')
  })

  it('rejects stress observations when count says ten but fewer full observations exist', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/stress_100_plus_one_click/case_manifest.json')
        ?.content ?? '{}',
    )
    manifest.status = 'passed'

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'stress_100_plus_one_click',
      manifest,
      screenshotFiles: ['card01_before.png', 'card50_before.png', 'card100_before.png'],
      screenshotManifest: screenshotManifestArtifactFor('stress_100_plus_one_click', [1, 50, 100]),
      observations: {
        case_id: 'stress_100_plus_one_click',
        session_id: COMPUTER_USE_SESSION_ID,
        count: 10,
        observations: [fullObservationItem(1), fullObservationItem(50), fullObservationItem(100)],
      },
    })

    expect(completion.ok).toBe(false)
    expect(completion.failedChecks).toContain('observations_items_below_required_preview_count')
  })

  it('accepts hot TTS cache proof when every exported TTS cache entry is a hit', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_quick20_hot/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'
    manifest.source_candidate = sourceCandidateFor('youtube_a_quick20_hot')
    const identity = artifactIdentityFor('youtube_a_quick20_hot')
    const hotCacheSummary = {
      ...identity,
      schema_version: 1,
      declared_cache_state: 'hot',
      observed_cache_state: 'hot',
      source_cache_probe_status: 'existing_url_cache_found',
      existing_url_cache_dirs: ['E:\\ANKI\\projects\\url_cache\\url_2c86c134'],
      cold_cache_reads_disabled: null,
      cold_claim_scope: 'not_cold_run',
      ai_review_cache: { read_enabled: true, write_enabled: true, hits: 4, misses: 0, total: 4 },
      card_generation_cache: { read_enabled: true, write_enabled: true, hits: 20, misses: 0, total: 20 },
      tts_cache: { hits: 39, misses: 0, total: 39 },
      media_cache: { hits: 60, misses: 0, total: 60 },
    }

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_quick20_hot',
      manifest,
      apkgFiles: [apkgEvidenceFor('youtube_a_quick20_hot')],
      cacheSummary: hotCacheSummary,
    })

    expect(completion.ok).toBe(false)
    expect(completion.failedChecks).not.toContain('cache_summary_hot_tts_hits_below_expected')

    const missedTts = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_quick20_hot',
      manifest,
      apkgFiles: [apkgEvidenceFor('youtube_a_quick20_hot')],
      cacheSummary: {
        ...hotCacheSummary,
        tts_cache: { hits: 38, misses: 1, total: 39 },
      },
    })

    expect(missedTts.failedChecks).toContain('cache_summary_hot_tts_hits_below_expected')
  })

  it('accepts a completed full-card case only with APKG, Anki, audio, timing, cache, Computer Use, and screenshots', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'
    manifest.source_candidate = sourceCandidateFor('youtube_a_full1_cold')
    const identity = artifactIdentityFor('youtube_a_full1_cold')
    const roundedDownIdentity = {
      ...identity,
      apkg_mtime_ms: identity.apkg_mtime_ms - 1,
    }

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
      apkgFiles: [apkgEvidenceFor('youtube_a_full1_cold')],
      screenshotFiles: ['card01_before.png'],
      sourceProvenance: sourceProvenanceFor('youtube_a_full1_cold'),
      deckMetadata: {
        ...identity,
        deck_name: '视频语言卡 - release proof',
        model_name: 'Anki Card Generator V12 - 沉浸复读 V11',
        card_count: 1,
      },
      ankiVerify: {
        ...identity,
        ok: true,
        import_attempted: true,
        import_result: true,
        failed_checks: [],
        card_count: 1,
        expected_cards: 1,
        imported_card_count: 1,
        card_media_ledger_count: 1,
        media_count_expected: 4,
        media_count_referenced: 4,
        media_count_checked: 4,
        mismatched_media: [],
        missing_media: [],
        audio_audit_mismatches: [],
        card_media_ledger_mismatches: [],
        media_ledger_card_text_mismatches: [],
        unexpected_media_references: [],
        unreferenced_expected_media: [],
        ledger_text_hash_mismatch: [],
        missing_video_field_media: [],
        imported_tts_text_hash_mismatch: [],
        inaccessible_media: [],
        ledger_missing_manifest: [],
        manifest_tts_without_ledger: [],
        audio_audit_write_errors: [],
        ciba_model_names: [],
        video_template_mismatches: [],
        document_template_mismatches: [],
        audio_audit_summary: {
          status: 'passed',
          items: 1,
          expected_items: 1,
        },
      },
      audioAudit: {
        summary: {
          status: 'passed',
          items: 1,
          expected_items: 1,
          failed: 0,
          mismatches: 0,
          manual_review_required: 0,
          media_subtitle_alignment: {
            matched: 1,
            partial: 0,
            mismatch: 0,
            unknown: 0,
          },
        },
        items: [
          {
            card_id: 'card_1',
            source_sentence: 'This is the source sentence.',
            card_display_sentence: 'This is the source sentence.',
            media_alignment_text: 'This is the source sentence.',
            media_alignment_source_text: 'This is the source sentence.',
            media_window_subtitle_text: 'This is the source sentence.',
            visible_answer: 'source sentence',
            media_start: 1,
            media_end: 3,
            media_source_time: '00:00:01.000 - 00:00:03.000',
            video_mp4: 'card_1.mp4',
            original_audio: 'card_1.mp3',
            sentence_tts_expected_text: 'This is the source sentence.',
            phrase_tts_expected_text: 'source sentence',
            sentence_tts_file: 'card_1_sentence.mp3',
            phrase_tts_file: 'card_1_phrase.mp3',
            media_subtitle_alignment_status: 'matched',
            media_hashes: {
              original_audio: 'a'.repeat(64),
              sentence_tts_audio: 'b'.repeat(64),
              phrase_tts_audio: 'c'.repeat(64),
            },
            tts_text_hashes: {
              sentence_tts: 'sentencehash',
              phrase_tts: 'phrasehash',
            },
            anki_fields: {
              Video: ['card_1.mp4'],
              Audio: ['card_1.mp3'],
              TtsAudio: ['card_1_sentence.mp3'],
              PhraseTtsAudio: ['card_1_phrase.mp3'],
            },
            anki_media_exists: {
              'card_1.mp4': true,
              'card_1.mp3': true,
              'card_1_sentence.mp3': true,
              'card_1_phrase.mp3': true,
            },
          },
        ],
      },
      timing: {
        ...roundedDownIdentity,
        schema_version: 1,
        case_id: 'youtube_a_full1_cold',
        declared_cache_state: 'cold',
        observed_cache_state: 'cold',
        source_prepare_ms: 1,
        learning_point_extract_ms: 2,
        ai_review_ms: 3,
        card_body_ms: 4,
        tts_ms: 5,
        media_slice_ms: 6,
        apkg_pack_ms: 7,
        anki_verify_ms: 8,
        total_ms: 36,
        timing_card_count: 1,
        per_card_ms: 36,
        stage_per_card_ms: {
          card_body: 4,
          tts: 5,
          media_slice: 6,
          apkg_pack: 7,
          anki_verify: 8,
          total: 36,
        },
        bottleneck_stage: 'anki_verify',
        bottleneck_ms: 8,
      },
      cacheSummary: {
        ...roundedDownIdentity,
        schema_version: 1,
        case_id: 'youtube_a_full1_cold',
        declared_cache_state: 'cold',
        observed_cache_state: 'cold',
        source_cache_probe_status: 'no_existing_url_cache_found',
        existing_url_cache_dirs: [],
        cold_cache_reads_disabled: true,
        cold_claim_scope: 'source_probe_clean_ai_card_cache_reads_disabled',
        ai_review_cache: {
          read_enabled: false,
          write_enabled: true,
          hits: 0,
          misses: 1,
          total: 1,
        },
        card_generation_cache: {
          read_enabled: false,
          write_enabled: true,
          hits: 0,
          misses: 1,
          total: 1,
        },
        tts_cache: {
          hits: 0,
          misses: 2,
          total: 2,
        },
        media_cache: {
          hits: 0,
          misses: 1,
          total: 1,
        },
      },
      screenshotManifest: screenshotManifestArtifactFor('youtube_a_full1_cold', [1]),
      observations: {
        case_id: 'youtube_a_full1_cold',
        session_id: COMPUTER_USE_SESSION_ID,
        count: 1,
        observations: [fullObservationItem(1)],
      },
      computerUseActions: {
        ...computerUseActionsFor('youtube_a_full1_cold', [1]),
      },
    })

    expect(completion).toMatchObject({
      ok: true,
      failedChecks: [],
      expectedCards: 1,
      requiredPreviewCards: 1,
    })
  })

  it('rejects completed evidence when media ledger TTS text disagrees with card text', () => {
    const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
    const manifest = JSON.parse(
      plan.seedFiles.find((file) => file.relativePath === 'cases/youtube_a_full1_cold/case_manifest.json')?.content ??
        '{}',
    )
    manifest.status = 'passed'

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId: 'youtube_a_full1_cold',
      manifest,
      ankiVerify: {
        ok: false,
        import_attempted: true,
        import_result: true,
        failed_checks: ['media_ledger_card_text_mismatch'],
        card_count: 1,
        expected_cards: 1,
        imported_card_count: 1,
        card_media_ledger_count: 1,
        media_count_expected: 4,
        media_count_referenced: 4,
        media_count_checked: 4,
        mismatched_media: [],
        missing_media: [],
        audio_audit_mismatches: [],
        card_media_ledger_mismatches: [],
        media_ledger_card_text_mismatches: [{ card_id: 'card_1', field: 'PhraseTtsAudio' }],
        unexpected_media_references: [],
        unreferenced_expected_media: [],
        ledger_text_hash_mismatch: [],
        missing_video_field_media: [],
        imported_tts_text_hash_mismatch: [],
        inaccessible_media: [],
        ledger_missing_manifest: [],
        manifest_tts_without_ledger: [],
        audio_audit_write_errors: [],
        ciba_model_names: [],
        video_template_mismatches: [],
        document_template_mismatches: [],
        audio_audit_summary: {
          status: 'passed',
          items: 1,
          expected_items: 1,
        },
      },
    })

    expect(completion.ok).toBe(false)
    expect(completion.failedChecks).toContain('anki_verify_failed_checks_present')
    expect(completion.failedChecks).toContain('anki_verify_media_ledger_card_text_mismatch')
  })
})

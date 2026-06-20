import { describe, expect, it } from 'vitest'

import {
  buildVideoReleaseRunInitializerPlan,
  evaluateVideoReleaseCaseCompletionEvidence,
} from '../domain/releaseEvidenceLayout'
import type { VideoReleaseCaseId, VideoReleaseCaseManifest } from '../domain/releaseEvidenceLayout'
import {
  buildReleaseAudioAuditArtifact,
  buildReleaseAudioAuditArtifactWritePlan,
} from './releaseEvidenceAudioAudit'

function manifestFor(caseId: VideoReleaseCaseId): VideoReleaseCaseManifest {
  const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
  return JSON.parse(
    plan.seedFiles.find((file) => file.relativePath === `cases/${caseId}/case_manifest.json`)?.content ?? '{}',
  )
}

function completeAuditPayload() {
  return {
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
      verify_path: 'E:\\ANKI\\out\\audio_audit.verify.json',
    },
    items: [
      {
        card_id: 'card-1',
        source_sentence: 'Ever want me to read anything, I could critique it for you.',
        card_display_sentence: 'Ever want me to read anything, I could critique it for you.',
        media_alignment_text: 'Ever want me to read anything, I could critique it for you.',
        media_alignment_source_text: 'Ever want me to read anything, I could critique it for you.',
        media_window_subtitle_text: 'Ever want me to read anything, I could critique it for you.',
        visible_answer: 'Ever want me to',
        original_audio: 'original-card-1.mp3',
        sentence_tts_expected_text: 'Ever want me to read anything, I could critique it for you.',
        phrase_tts_expected_text: 'Ever want me to',
        sentence_tts_file: 'sentence-card-1.mp3',
        phrase_tts_file: 'phrase-card-1.mp3',
        tts_text_hashes: {
          sentence_tts: 'sentence-text-hash',
          phrase_tts: 'phrase-text-hash',
        },
        media_start: 1.2,
        media_end: 3.4,
        media_source_time: '00:00:01.200-00:00:03.400',
        video_mp4: 'video-card-1.mp4',
        media_subtitle_alignment_status: 'matched',
        media_hashes: {
          original_audio: 'original-audio-sha',
          sentence_tts_audio: 'sentence-tts-sha',
          phrase_tts_audio: 'phrase-tts-sha',
        },
        anki_fields: {
          Audio: ['original-card-1.mp3'],
          TtsAudio: ['sentence-card-1.mp3'],
          PhraseTtsAudio: ['phrase-card-1.mp3'],
          Video: ['video-card-1.mp4'],
        },
        anki_media_exists: {
          'original-card-1.mp3': true,
          'sentence-card-1.mp3': true,
          'phrase-card-1.mp3': true,
          'video-card-1.mp4': true,
        },
      },
    ],
  }
}

function ankiVerifyResult() {
  return {
    ok: true,
    failed_checks: [],
    card_count: 1,
    audio_audit_verify_path: 'E:\\ANKI\\out\\audio_audit.verify.json',
    audio_audit_mismatches: [],
    audio_audit_write_errors: [],
    audio_audit_summary: completeAuditPayload().summary,
  }
}

function exportResult() {
  return {
    cards: 1,
    audio_audit_items: completeAuditPayload().items,
    audio_audit_summary: {
      status: 'passed',
      items: 1,
      expected_items: 1,
      failed: 0,
      mismatches: 0,
      manual_review_required: 0,
    },
  }
}

function audioAuditFailures(failedChecks: string[]) {
  return failedChecks.filter((check) => check === 'audio_audit_missing' || check.startsWith('audio_audit_'))
}

describe('releaseEvidenceAudioAudit', () => {
  it('builds audio audit proof that satisfies the final verifier audio-audit contract only', () => {
    const caseId = 'youtube_a_full1_cold'
    const manifest = manifestFor(caseId)
    manifest.status = 'passed'
    const artifact = buildReleaseAudioAuditArtifact({
      caseId,
      manifest,
      audioAudit: completeAuditPayload(),
      exportResult: exportResult(),
      ankiVerifyResult: ankiVerifyResult(),
    })

    expect(artifact.ok).toBe(true)
    expect(artifact.matrixPassCreated).toBe(false)
    expect(artifact.artifactPath).toBe('cases/youtube_a_full1_cold/audio_audit.verify.json')
    expect(artifact.audioAudit).toMatchObject({
      summary: { status: 'passed', items: 1, expected_items: 1 },
      items: [{ card_id: 'card-1', visible_answer: 'Ever want me to' }],
    })

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId,
      manifest,
      audioAudit: artifact.audioAudit,
    })

    expect(audioAuditFailures(completion.failedChecks)).toEqual([])
    expect(completion.ok).toBe(false)
    expect(completion.failedChecks).toEqual(
      expect.arrayContaining([
        'apkg_missing',
        'source_provenance_missing',
        'deck_metadata_missing',
        'anki_verify_missing',
        'timing_missing',
        'cache_summary_missing',
        'observations_missing',
        'computer_use_actions_missing',
      ]),
    )
  })

  it('refuses audio audit payloads that fail final verifier item requirements', () => {
    const audit = completeAuditPayload()
    delete (audit.items[0] as Record<string, unknown>).media_hashes

    const artifact = buildReleaseAudioAuditArtifact({
      caseId: 'youtube_a_full1_cold',
      manifest: manifestFor('youtube_a_full1_cold'),
      audioAudit: audit,
      ankiVerifyResult: ankiVerifyResult(),
    })

    expect(artifact.ok).toBe(false)
    expect(artifact.audioAudit).toBeNull()
    expect(artifact.failedChecks).toContain('audio_audit_item_required_fields_missing')
  })

  it('refuses stale or failed Anki verify evidence before planning an audio audit write', () => {
    const artifact = buildReleaseAudioAuditArtifact({
      caseId: 'youtube_a_full1_cold',
      manifest: manifestFor('youtube_a_full1_cold'),
      audioAudit: completeAuditPayload(),
      ankiVerifyResult: {
        ...ankiVerifyResult(),
        ok: false,
        failed_checks: ['audio_audit_mismatch'],
        audio_audit_mismatches: [{ field: 'PhraseTtsAudio' }],
      },
    })

    expect(artifact.ok).toBe(false)
    expect(artifact.failedChecks).toEqual(
      expect.arrayContaining([
        'audio_audit_anki_verify_not_ok',
        'audio_audit_anki_verify_failed_checks_present',
        'audio_audit_anki_verify_mismatches_present',
      ]),
    )
  })

  it('builds a write-once case-local audio audit write plan', () => {
    const runDir = 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_231900'
    const plan = buildReleaseAudioAuditArtifactWritePlan({
      caseId: 'youtube_a_full1_cold',
      manifest: manifestFor('youtube_a_full1_cold'),
      audioAudit: completeAuditPayload(),
      exportResult: exportResult(),
      ankiVerifyResult: ankiVerifyResult(),
      runDir,
    })

    expect(plan.ok).toBe(true)
    expect(plan.status).toBe('ready_to_write')
    expect(plan.matrixPassCreated).toBe(false)
    expect(plan.caseDir).toBe(`${runDir}\\cases\\youtube_a_full1_cold`)
    expect(plan.writes).toHaveLength(1)
    expect(plan.writes[0]).toMatchObject({
      kind: 'audio_audit',
      relativePath: 'cases/youtube_a_full1_cold/audio_audit.verify.json',
      absolutePath: `${runDir}\\cases\\youtube_a_full1_cold\\audio_audit.verify.json`,
      writeMode: 'exclusive_create',
    })
    const payload = JSON.parse(plan.writes[0]?.content ?? '{}')
    expect(payload.summary.status).toBe('passed')
    expect(payload.items).toHaveLength(1)
    expect(payload.matrix_pass_created).toBeUndefined()
  })

  it('refuses unsafe run directories and matrix-pass-shaped payloads', () => {
    const plan = buildReleaseAudioAuditArtifactWritePlan({
      caseId: 'youtube_a_full1_cold',
      manifest: manifestFor('youtube_a_full1_cold'),
      audioAudit: {
        ...completeAuditPayload(),
        matrix_pass_created: true,
      },
      runDir:
        'E:\\ANKI\\test_runs\\video_release_hardening_20260619_231900\\..\\video_release_hardening_20260619_231900',
    })

    expect(plan.ok).toBe(false)
    expect(plan.writes).toEqual([])
    expect(plan.failedChecks).toEqual(
      expect.arrayContaining(['run_dir_path_unsafe', 'audio_audit_artifact_matrix_pass_field_present']),
    )
  })
})

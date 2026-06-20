import { describe, expect, it } from 'vitest'

import {
  buildVideoReleaseRunInitializerPlan,
  evaluateVideoReleaseCaseCompletionEvidence,
} from '../domain/releaseEvidenceLayout'
import type { VideoReleaseCaseId, VideoReleaseCaseManifest } from '../domain/releaseEvidenceLayout'
import {
  buildReleaseComputerUseArtifactWritePlan,
  buildReleaseComputerUseArtifacts,
} from './releaseEvidenceComputerUseArtifacts'

const COMPUTER_USE_SESSION_ID = 'computer-use-session-release-proof-1'
const SCREENSHOT_SHA256 = 'a'.repeat(64)

function manifestFor(caseId: VideoReleaseCaseId): VideoReleaseCaseManifest {
  const plan = buildVideoReleaseRunInitializerPlan('20260619_045000')
  const manifest = JSON.parse(
    plan.seedFiles.find((file) => file.relativePath === `cases/${caseId}/case_manifest.json`)?.content ?? '{}',
  )
  manifest.status = 'passed'
  return manifest
}

function screenshotFileName(index: number) {
  return `card${String(index).padStart(2, '0')}_before.png`
}

function screenshotFileEvidence(caseId: VideoReleaseCaseId, index: number) {
  return {
    path: screenshotFileName(index),
    relative_path: `cases/${caseId}/screenshots/${screenshotFileName(index)}`,
    sha256: SCREENSHOT_SHA256,
    size_bytes: 128,
    mtime_ms: 1781880000000,
  }
}

function screenshotManifestArtifactFor(caseId: VideoReleaseCaseId, indices: number[]) {
  return {
    schema_version: 1,
    case_id: caseId,
    session_id: COMPUTER_USE_SESSION_ID,
    screenshots: indices.map((index) => ({
      screenshot_id: `card-${index}-before`,
      session_id: COMPUTER_USE_SESSION_ID,
      card_index: index,
      path: screenshotFileName(index),
      sha256: SCREENSHOT_SHA256,
    })),
  }
}

function playbackActionRefs(index: number) {
  return {
    video: `card-${index}-video-click`,
    original_audio: `card-${index}-original-audio-click`,
    sentence_tts: `card-${index}-sentence-tts-click`,
    phrase_tts: `card-${index}-phrase-tts-click`,
  }
}

function fullObservationItem(index: number) {
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
      before: screenshotFileName(index),
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

function computerUseActionRowsFor(indices: number[]) {
  const actions: Record<string, unknown>[] = []
  for (const index of indices) {
    const refs = playbackActionRefs(index)
    for (const role of ['video', 'original_audio', 'sentence_tts', 'phrase_tts'] as const) {
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
  return actions
}

function computerUseVerifierFailures(failedChecks: string[]) {
  return failedChecks.filter(
    (check) =>
      check.startsWith('screenshots_') ||
      check.startsWith('screenshot_manifest_') ||
      check.startsWith('observations_') ||
      check.startsWith('computer_use_'),
  )
}

describe('releaseEvidenceComputerUseArtifacts', () => {
  it('builds a write-once observations/actions plan that satisfies the final Computer Use verifier slots', () => {
    const caseId = 'youtube_a_full1_cold'
    const runDir = 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542'
    const manifest = manifestFor(caseId)
    const screenshotFiles = [screenshotFileEvidence(caseId, 1)]
    const screenshotManifest = screenshotManifestArtifactFor(caseId, [1])
    const plan = buildReleaseComputerUseArtifactWritePlan({
      runDir,
      caseId,
      manifest,
      sessionId: COMPUTER_USE_SESSION_ID,
      observations: [fullObservationItem(1)],
      computerUseActions: computerUseActionRowsFor([1]),
      screenshotManifest,
      screenshotFiles,
    })

    expect(plan.ok).toBe(true)
    expect(plan.status).toBe('ready_to_write')
    expect(plan.matrixPassCreated).toBe(false)
    expect(plan.caseDir).toBe(`${runDir}\\cases\\youtube_a_full1_cold`)
    expect(
      plan.writes.map((write) => ({
        kind: write.kind,
        relativePath: write.relativePath,
        absolutePath: write.absolutePath,
        writeMode: write.writeMode,
      })),
    ).toEqual([
      {
        kind: 'observations',
        relativePath: 'cases/youtube_a_full1_cold/observations.json',
        absolutePath: `${runDir}\\cases\\youtube_a_full1_cold\\observations.json`,
        writeMode: 'exclusive_create',
      },
      {
        kind: 'computer_use_actions',
        relativePath: 'cases/youtube_a_full1_cold/computer_use_actions.json',
        absolutePath: `${runDir}\\cases\\youtube_a_full1_cold\\computer_use_actions.json`,
        writeMode: 'exclusive_create',
      },
    ])

    const observations = JSON.parse(plan.writes.find((write) => write.kind === 'observations')?.content ?? '{}')
    const computerUseActions = JSON.parse(
      plan.writes.find((write) => write.kind === 'computer_use_actions')?.content ?? '{}',
    )
    expect(observations).toMatchObject({
      schema_version: 1,
      case_id: caseId,
      session_id: COMPUTER_USE_SESSION_ID,
      count: 1,
    })
    expect(computerUseActions).toMatchObject({
      schema_version: 1,
      case_id: caseId,
      session_id: COMPUTER_USE_SESSION_ID,
      previewed_cards: 1,
      playback_counts: {
        video: 1,
        original_audio: 1,
        sentence_tts: 1,
        phrase_tts: 1,
      },
    })
    expect(observations.matrix_pass_created).toBeUndefined()
    expect(computerUseActions.matrix_pass_created).toBeUndefined()

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId,
      manifest,
      screenshotFiles,
      screenshotManifest,
      observations,
      computerUseActions,
    })
    expect(completion.ok).toBe(false)
    expect(computerUseVerifierFailures(completion.failedChecks)).toEqual([])
    expect(completion.failedChecks).toEqual(
      expect.arrayContaining([
        'source_provenance_missing',
        'deck_metadata_missing',
        'anki_verify_missing',
        'audio_audit_missing',
        'timing_missing',
        'cache_summary_missing',
      ]),
    )
  })

  it('refuses observations that do not link to canonical raw Computer Use action rows', () => {
    const caseId = 'youtube_a_full1_cold'
    const observation = fullObservationItem(1)
    delete (observation as Record<string, unknown>).playback_action_refs

    const plan = buildReleaseComputerUseArtifactWritePlan({
      runDir: 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542',
      caseId,
      manifest: manifestFor(caseId),
      sessionId: COMPUTER_USE_SESSION_ID,
      observations: [observation],
      computerUseActions: computerUseActionRowsFor([1]),
      screenshotManifest: screenshotManifestArtifactFor(caseId, [1]),
      screenshotFiles: [screenshotFileEvidence(caseId, 1)],
    })

    expect(plan.ok).toBe(false)
    expect(plan.failedChecks).toContain('observations_missing_computer_use_action_links')
    expect(plan.failedChecks).toContain('observations_missing_required_card_indices')
    expect(plan.writes).toEqual([])
  })

  it('refuses string-only screenshot evidence because final screenshot SHA identity is not proven', () => {
    const caseId = 'youtube_a_full1_cold'
    const artifact = buildReleaseComputerUseArtifacts({
      caseId,
      manifest: manifestFor(caseId),
      sessionId: COMPUTER_USE_SESSION_ID,
      observations: [fullObservationItem(1)],
      computerUseActions: computerUseActionRowsFor([1]),
      screenshotManifest: screenshotManifestArtifactFor(caseId, [1]),
      screenshotFiles: [screenshotFileName(1)],
    })

    expect(artifact.ok).toBe(false)
    expect(artifact.failedChecks).toContain('computer_use_screenshot_file_sha256_missing')
    expect(artifact.observations).toBeNull()
    expect(artifact.computerUseActions).toBeNull()
  })

  it('refuses stress evidence unless the raw action trace records exactly one generation click', () => {
    const caseId = 'stress_100_plus_one_click'
    const indices = [1, 2, 3, 4, 50, 51, 52, 98, 99, 100]
    const plan = buildReleaseComputerUseArtifactWritePlan({
      runDir: 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542',
      caseId,
      manifest: manifestFor(caseId),
      sessionId: COMPUTER_USE_SESSION_ID,
      observations: indices.map(fullObservationItem),
      computerUseActions: computerUseActionRowsFor(indices),
      screenshotManifest: screenshotManifestArtifactFor(caseId, indices),
      screenshotFiles: indices.map((index) => screenshotFileEvidence(caseId, index)),
      generationClicks: 2,
    })

    expect(plan.ok).toBe(false)
    expect(plan.failedChecks).toContain('computer_use_stress_generation_click_not_one')
    expect(plan.writes).toEqual([])
  })

  it('refuses unsafe release run directories before returning write payloads', () => {
    const caseId = 'youtube_a_full1_cold'
    const plan = buildReleaseComputerUseArtifactWritePlan({
      runDir:
        'E:\\ANKI\\test_runs\\video_release_hardening_20260619_044542\\..\\video_release_hardening_20260619_044542',
      caseId,
      manifest: manifestFor(caseId),
      sessionId: COMPUTER_USE_SESSION_ID,
      observations: [fullObservationItem(1)],
      computerUseActions: computerUseActionRowsFor([1]),
      screenshotManifest: screenshotManifestArtifactFor(caseId, [1]),
      screenshotFiles: [screenshotFileEvidence(caseId, 1)],
    })

    expect(plan.ok).toBe(false)
    expect(plan.failedChecks).toContain('run_dir_path_unsafe')
    expect(plan.writes).toEqual([])
  })
})

import { describe, expect, it } from 'vitest'

import {
  buildVideoReleaseRunInitializerPlan,
  evaluateVideoReleaseCaseCompletionEvidence,
} from '../domain/releaseEvidenceLayout'
import type { VideoReleaseCaseId, VideoReleaseCaseManifest } from '../domain/releaseEvidenceLayout'
import {
  buildReleaseScreenshotManifestArtifact,
  buildReleaseScreenshotManifestArtifactWritePlan,
} from './releaseEvidenceScreenshotArtifacts'

const COMPUTER_USE_SESSION_ID = 'computer-use-session-release-proof-1'
const SCREENSHOT_SHA256 = 'b'.repeat(64)

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

function screenshotEvidence(caseId: VideoReleaseCaseId, index: number, overrides: Record<string, unknown> = {}) {
  const fileName = screenshotFileName(index)
  return {
    card_index: index,
    screenshot_id: `card-${index}-before`,
    session_id: COMPUTER_USE_SESSION_ID,
    path: fileName,
    relative_path: `cases/${caseId}/screenshots/${fileName}`,
    sha256: SCREENSHOT_SHA256,
    size_bytes: 128,
    mtime_ms: 1781880000000,
    ...overrides,
  }
}

function screenshotFailures(failedChecks: string[]) {
  return failedChecks.filter((check) => check.startsWith('screenshots_') || check.startsWith('screenshot_manifest_'))
}

describe('releaseEvidenceScreenshotArtifacts', () => {
  it('builds a case-local screenshot manifest write plan that satisfies the final screenshot verifier slots', () => {
    const caseId = 'youtube_a_full1_cold'
    const runDir = 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_235500'
    const plan = buildReleaseScreenshotManifestArtifactWritePlan({
      runDir,
      caseId,
      manifest: manifestFor(caseId),
      sessionId: COMPUTER_USE_SESSION_ID,
      screenshots: [screenshotEvidence(caseId, 1)],
    })

    expect(plan.ok).toBe(true)
    expect(plan.status).toBe('ready_to_write')
    expect(plan.matrixPassCreated).toBe(false)
    expect(plan.writes).toHaveLength(1)
    expect(plan.writes[0]).toMatchObject({
      kind: 'screenshot_manifest',
      relativePath: 'cases/youtube_a_full1_cold/screenshots/manifest.json',
      absolutePath: `${runDir}\\cases\\youtube_a_full1_cold\\screenshots\\manifest.json`,
      writeMode: 'exclusive_create',
    })

    const manifest = JSON.parse(plan.writes[0]?.content ?? '{}')
    expect(manifest).toMatchObject({
      schema_version: 1,
      case_id: caseId,
      session_id: COMPUTER_USE_SESSION_ID,
      count: 1,
      screenshots: [
        {
          screenshot_id: 'card-1-before',
          session_id: COMPUTER_USE_SESSION_ID,
          card_index: 1,
          path: screenshotFileName(1),
          relative_path: `cases/${caseId}/screenshots/${screenshotFileName(1)}`,
          sha256: SCREENSHOT_SHA256,
        },
      ],
    })
    expect(manifest.matrix_pass_created).toBeUndefined()

    const completion = evaluateVideoReleaseCaseCompletionEvidence({
      caseId,
      manifest: manifestFor(caseId),
      screenshotFiles: [screenshotEvidence(caseId, 1)],
      screenshotManifest: manifest,
    })

    expect(completion.ok).toBe(false)
    expect(screenshotFailures(completion.failedChecks)).toEqual([])
    expect(completion.failedChecks).toEqual(
      expect.arrayContaining([
        'apkg_missing',
        'source_provenance_missing',
        'deck_metadata_missing',
        'anki_verify_missing',
        'audio_audit_missing',
        'timing_missing',
        'cache_summary_missing',
        'observations_missing',
        'computer_use_actions_missing',
      ]),
    )
  })

  it('refuses screenshot evidence without actual file hash identity', () => {
    const artifact = buildReleaseScreenshotManifestArtifact({
      caseId: 'youtube_a_full1_cold',
      manifest: manifestFor('youtube_a_full1_cold'),
      sessionId: COMPUTER_USE_SESSION_ID,
      screenshots: [screenshotEvidence('youtube_a_full1_cold', 1, { sha256: '' })],
    })

    expect(artifact.ok).toBe(false)
    expect(artifact.screenshotManifest).toBeNull()
    expect(artifact.failedChecks).toContain('screenshot_manifest_sha256_missing')
  })

  it('refuses duplicate card indexes and reused screenshot files before planning a manifest write', () => {
    const plan = buildReleaseScreenshotManifestArtifactWritePlan({
      runDir: 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_235500',
      caseId: 'youtube_a_quick20_cold',
      manifest: manifestFor('youtube_a_quick20_cold'),
      sessionId: COMPUTER_USE_SESSION_ID,
      screenshots: [
        screenshotEvidence('youtube_a_quick20_cold', 1, { path: 'shared.png', relative_path: 'cases/youtube_a_quick20_cold/screenshots/shared.png' }),
        screenshotEvidence('youtube_a_quick20_cold', 1, { path: 'shared.png', relative_path: 'cases/youtube_a_quick20_cold/screenshots/shared.png' }),
      ],
    })

    expect(plan.ok).toBe(false)
    expect(plan.writes).toEqual([])
    expect(plan.failedChecks).toEqual(
      expect.arrayContaining([
        'screenshot_manifest_duplicate_card_index',
        'screenshot_manifest_file_reused_for_multiple_card_indices',
        'screenshot_manifest_missing_required_card_indices',
      ]),
    )
  })

  it('requires all-card screenshot coverage for all-card inspection cases', () => {
    const plan = buildReleaseScreenshotManifestArtifactWritePlan({
      runDir: 'E:\\ANKI\\test_runs\\video_release_hardening_20260619_235500',
      caseId: 'youtube_a_quick20_cold',
      manifest: manifestFor('youtube_a_quick20_cold'),
      sessionId: COMPUTER_USE_SESSION_ID,
      screenshots: [screenshotEvidence('youtube_a_quick20_cold', 1)],
    })

    expect(plan.ok).toBe(false)
    expect(plan.failedChecks).toContain('screenshots_below_required_preview_count')
    expect(plan.failedChecks).toContain('screenshot_manifest_missing_required_card_indices')
    expect(plan.writes).toEqual([])
  })

  it('requires stress screenshots to cover start, middle, and end samples', () => {
    const indices = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    const artifact = buildReleaseScreenshotManifestArtifact({
      caseId: 'stress_100_plus_one_click',
      manifest: manifestFor('stress_100_plus_one_click'),
      sessionId: COMPUTER_USE_SESSION_ID,
      screenshots: indices.map((index) => screenshotEvidence('stress_100_plus_one_click', index)),
    })

    expect(artifact.ok).toBe(false)
    expect(artifact.failedChecks).toContain('screenshot_manifest_stress_sample_coverage_missing')
  })

  it('refuses unsafe run directories and non-canonical screenshot paths', () => {
    const plan = buildReleaseScreenshotManifestArtifactWritePlan({
      runDir:
        'E:\\ANKI\\test_runs\\video_release_hardening_20260619_235500\\..\\video_release_hardening_20260619_235500',
      caseId: 'youtube_a_full1_cold',
      manifest: manifestFor('youtube_a_full1_cold'),
      sessionId: COMPUTER_USE_SESSION_ID,
      screenshots: [
        screenshotEvidence('youtube_a_full1_cold', 1, {
          relative_path: 'cases/youtube_a_full1_cold/card01_before.png',
        }),
      ],
    })

    expect(plan.ok).toBe(false)
    expect(plan.writes).toEqual([])
    expect(plan.failedChecks).toEqual(
      expect.arrayContaining(['run_dir_path_unsafe', 'screenshot_manifest_relative_path_mismatch']),
    )
  })
})

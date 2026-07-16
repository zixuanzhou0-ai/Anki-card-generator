import { describe, expect, it } from 'vitest'

import { defaultRequest } from '../domain/options'
import {
  buildWorkflowFileEvidence,
  checkpointContainsSecret,
  compareApkgFileEvidence,
  compareSourceFileEvidence,
  collectWorkflowSourceFileRefs,
  fingerprintWorkflowRequest,
  fingerprintWorkflowSource,
  isWorkflowArtifactReference,
  isWorkflowFileEvidence,
  isWorkflowSourceEvidenceList,
  normalizeWorkflowCheckpoint,
  parseWorkflowCheckpoint,
  remainingGenerationQueueIds,
  remainingGenerationQueueIdsAfterSuccessfulActiveBatch,
  stableWorkflowJson,
} from './workflowCheckpoint'
import type { RecoveryFileInspection } from './nativeShell'

const SHA_A = 'a'.repeat(64)
const SHA_B = 'b'.repeat(64)

function inspectedFile(overrides: Partial<RecoveryFileInspection> = {}): RecoveryFileInspection {
  return {
    ok: true,
    exists: true,
    isFile: true,
    size: 1024,
    modifiedAtMs: 123_456,
    sha256: null,
    error: null,
    ...overrides,
  }
}
describe('workflow checkpoint', () => {
  it('creates stable fingerprints independent of object key order', () => {
    expect(stableWorkflowJson({ b: 2, a: { d: 4, c: 3 } })).toBe(stableWorkflowJson({ a: { c: 3, d: 4 }, b: 2 }))
  })

  it('never includes API or TTS keys in a normalized checkpoint', () => {
    const request = {
      ...defaultRequest,
      api_config: {
        ...defaultRequest.api_config,
        api_key: 'model-secret',
        tts_config: {
          ...defaultRequest.api_config.tts_config,
          api_key: 'tts-secret',
        },
      },
    }
    const checkpoint = normalizeWorkflowCheckpoint({
      request,
      productStep: 'source',
      artifactStage: 'source_ready',
    })

    expect(checkpoint.request.api_config.api_key).toBe('')
    expect(checkpoint.request.api_config.tts_config.api_key).toBe('')
    expect(JSON.stringify(checkpoint)).not.toContain('model-secret')
    expect(JSON.stringify(checkpoint)).not.toContain('tts-secret')
  })

  it('changes request fingerprint when a meaningful model setting changes', () => {
    const original = fingerprintWorkflowRequest(defaultRequest)
    const changed = fingerprintWorkflowRequest({
      ...defaultRequest,
      api_config: { ...defaultRequest.api_config, model: 'another-model' },
    })
    expect(changed).not.toBe(original)
  })

  it('keeps source fingerprint independent from unrelated review preferences', () => {
    const original = fingerprintWorkflowSource(defaultRequest)
    const requestWithDifferentReviewDensity = {
      ...defaultRequest,
      review_density: defaultRequest.review_density === 'fast' ? ('full' as const) : ('fast' as const),
    }
    const changed = fingerprintWorkflowSource(requestWithDifferentReviewDensity)
    expect(changed).toBe(original)
  })

  it('collects every enabled local file in mixed batches and fingerprints only stable source fields', () => {
    const mixedRequest = {
      ...defaultRequest,
      source_mode: 'local' as const,
      batch_enabled: true,
      batch_items: [
        {
          id: 'local-1',
          title: 'Local lesson',
          subdeck_title: 'Local lesson',
          source_mode: 'local' as const,
          enabled: true,
          status: 'ready' as const,
          video_path: '"E:\\media\\lesson.mp4"',
          subtitle_path: 'E:\\media\\lesson.srt',
        },
        {
          id: 'url-1',
          title: 'Remote lesson',
          subdeck_title: 'Remote lesson',
          source_mode: 'url' as const,
          enabled: true,
          source_url: 'https://www.youtube.com/watch?v=example',
        },
        {
          id: 'disabled-doc',
          title: 'Disabled document',
          subdeck_title: 'Disabled document',
          source_mode: 'document' as const,
          enabled: false,
          document_path: 'E:\\private\\disabled.pdf',
        },
      ],
    }

    expect(collectWorkflowSourceFileRefs(mixedRequest)).toEqual([
      {
        id: 'batch:local-1:subtitle',
        role: 'subtitle',
        path: 'E:\\media\\lesson.srt',
        batchItemId: 'local-1',
      },
      {
        id: 'batch:local-1:video',
        role: 'video',
        path: 'E:\\media\\lesson.mp4',
        batchItemId: 'local-1',
      },
    ])

    const cosmeticChange = {
      ...mixedRequest,
      batch_items: mixedRequest.batch_items.map((item) => ({
        ...item,
        status: 'generated' as const,
        warning: 'ignored',
      })),
    }
    expect(fingerprintWorkflowSource(cosmeticChange)).toBe(fingerprintWorkflowSource(mixedRequest))
    expect(
      fingerprintWorkflowSource({
        ...mixedRequest,
        batch_items: mixedRequest.batch_items.map((item) =>
          item.id === 'url-1' ? { ...item, source_url: 'https://www.youtube.com/watch?v=changed' } : item,
        ),
      }),
    ).not.toBe(fingerprintWorkflowSource(mixedRequest))
  })

  it('rejects secrets recursively while allowing non-sensitive metadata flags', () => {
    expect(checkpointContainsSecret({ nested: { access_token: 'token' } })).toBe(true)
    expect(checkpointContainsSecret({ request: { api_key: '' }, has_api_key: true })).toBe(false)
  })

  it('parses only supported, non-sensitive checkpoints', () => {
    const checkpoint = normalizeWorkflowCheckpoint({
      request: defaultRequest,
      productStep: 'select',
      artifactStage: 'learning_points_ready',
      updatedAt: 123,
    })
    expect(parseWorkflowCheckpoint(checkpoint)).toEqual(checkpoint)
    expect(parseWorkflowCheckpoint({ ...checkpoint, schemaVersion: 2 })).toBeNull()
    expect(
      parseWorkflowCheckpoint({
        ...checkpoint,
        request: {
          ...checkpoint.request,
          api_config: { ...checkpoint.request.api_config, api_key: 'secret' },
        },
      }),
    ).toBeNull()
  })

  it('deeply rejects malformed request fields and mismatched fingerprints', () => {
    const checkpoint = normalizeWorkflowCheckpoint({
      request: defaultRequest,
      productStep: 'select',
      artifactStage: 'learning_points_ready',
      updatedAt: 123,
    })

    expect(parseWorkflowCheckpoint({ ...checkpoint, request: [] })).toBeNull()
    expect(
      parseWorkflowCheckpoint({
        ...checkpoint,
        request: { ...checkpoint.request, batch_enabled: 'false' },
      }),
    ).toBeNull()
    expect(
      parseWorkflowCheckpoint({
        ...checkpoint,
        request: {
          ...checkpoint.request,
          api_config: { ...checkpoint.request.api_config, tts_config: { enabled: true } },
        },
      }),
    ).toBeNull()
    expect(
      parseWorkflowCheckpoint({
        ...checkpoint,
        request: {
          ...checkpoint.request,
          batch_items: [
            {
              id: 'lesson-1',
              title: 'Lesson',
              subdeck_title: 'Lesson',
              source_mode: 'invalid',
              enabled: true,
            },
          ],
        },
      }),
    ).toBeNull()
    expect(parseWorkflowCheckpoint({ ...checkpoint, requestFingerprint: 'request-v1-deadbeef' })).toBeNull()
  })

  it('rejects invalid stages, queues, references, paths, hashes and task snapshots', () => {
    const checkpoint = normalizeWorkflowCheckpoint({
      request: defaultRequest,
      productStep: 'deliver',
      artifactStage: 'drafts_ready',
      generationQueue: {
        selectedIds: ['a', 'b'],
        completedIds: ['a'],
        activeBatchIds: ['b'],
      },
      learningPointResultRef: 'learning-points-safe.json',
      projectRef: 'project-safe.json',
      outputDirectory: 'E:\\cards',
      updatedAt: 123,
    })

    expect(parseWorkflowCheckpoint({ ...checkpoint, productStep: 'generate' })).toBeNull()
    expect(parseWorkflowCheckpoint({ ...checkpoint, artifactStage: 'exported' })).toBeNull()
    expect(parseWorkflowCheckpoint({ ...checkpoint, updatedAt: Number.NaN })).toBeNull()
    expect(
      parseWorkflowCheckpoint({
        ...checkpoint,
        generationQueue: { ...checkpoint.generationQueue, selectedIds: ['a', 'a'] },
      }),
    ).toBeNull()
    expect(
      parseWorkflowCheckpoint({
        ...checkpoint,
        generationQueue: { ...checkpoint.generationQueue, completedIds: ['missing'] },
      }),
    ).toBeNull()
    expect(parseWorkflowCheckpoint({ ...checkpoint, projectRef: '../project.json' })).toBeNull()
    expect(parseWorkflowCheckpoint({ ...checkpoint, projectRef: 'project.exe' })).toBeNull()
    expect(parseWorkflowCheckpoint({ ...checkpoint, outputDirectory: 'E:\\cards\u0000hidden' })).toBeNull()
    expect(parseWorkflowCheckpoint({ ...checkpoint, outputDirectory: 'relative\\cards' })).toBeNull()
    expect(parseWorkflowCheckpoint({ ...checkpoint, apkgPath: 'E:\\cards\\deck.txt' })).toBeNull()
    expect(parseWorkflowCheckpoint({ ...checkpoint, apkgSha256: 'not-a-hash' })).toBeNull()
    const apkgCheckpoint = normalizeWorkflowCheckpoint({
      request: defaultRequest,
      productStep: 'deliver',
      artifactStage: 'apkg_ready',
      apkgPath: 'E:\\cards\\deck.apkg',
      apkgSha256: SHA_A,
      apkgEvidence: {
        path: 'E:\\cards\\deck.apkg',
        size: 1024,
        modifiedAtMs: 123,
        sha256: SHA_A,
      },
      updatedAt: 123,
    })
    expect(
      parseWorkflowCheckpoint({
        ...apkgCheckpoint,
        apkgEvidence: { ...apkgCheckpoint.apkgEvidence, path: 'E:\\cards\\other.apkg' },
      }),
    ).toBeNull()
    expect(
      parseWorkflowCheckpoint({
        ...apkgCheckpoint,
        apkgEvidence: { ...apkgCheckpoint.apkgEvidence, sha256: SHA_B },
      }),
    ).toBeNull()
    expect(
      parseWorkflowCheckpoint({
        ...checkpoint,
        task: {
          schemaVersion: 1,
          id: 'job-1',
          command: 'export',
          state: 'running',
          startedAt: 1,
          updatedAt: 2,
          progress: {
            phase: 'export',
            phaseLabel: 'Export',
            phasePercent: 101,
            overallPercent: 20,
            message: 'Working',
            lastProgressAt: 2,
          },
          cancellable: true,
          inputFingerprint: checkpoint.requestFingerprint,
        },
      }),
    ).toBeNull()
  })

  it('validates artifact references with the same safety boundary as the native layer', () => {
    expect(isWorkflowArtifactReference('project-123.json')).toBe(true)
    expect(isWorkflowArtifactReference('../project.json')).toBe(false)
    expect(isWorkflowArtifactReference('nested/project.json')).toBe(false)
    expect(isWorkflowArtifactReference('CON.json')).toBe(false)
    expect(isWorkflowArtifactReference('project.exe')).toBe(false)
  })

  it('resumes only unfinished ids and retries the whole active batch', () => {
    expect(
      remainingGenerationQueueIds({
        selectedIds: ['a', 'b', 'c', 'd'],
        completedIds: ['a', 'b', 'c'],
        activeBatchIds: ['c', 'd'],
      }),
    ).toEqual(['c', 'd'])
    expect(remainingGenerationQueueIds(undefined)).toEqual([])
    expect(
      remainingGenerationQueueIdsAfterSuccessfulActiveBatch({
        selectedIds: ['a', 'b', 'c', 'd', 'e'],
        completedIds: ['a', 'b'],
        activeBatchIds: ['c', 'd'],
      }),
    ).toEqual(['e'])
  })

  it('builds persistent file evidence and normalizes SHA-256 casing', () => {
    const source = buildWorkflowFileEvidence('E:\\media\\lesson.mp4', inspectedFile())
    expect(source).toEqual({
      ok: true,
      evidence: {
        path: 'E:\\media\\lesson.mp4',
        size: 1024,
        modifiedAtMs: 123_456,
      },
    })

    const apkg = buildWorkflowFileEvidence(
      'E:\\cards\\lesson.apkg',
      inspectedFile({ sha256: SHA_A.toUpperCase() }),
      true,
    )
    expect(apkg).toMatchObject({
      ok: true,
      evidence: {
        path: 'E:\\cards\\lesson.apkg',
        sha256: SHA_A,
      },
    })
    expect(isWorkflowFileEvidence(apkg.ok ? apkg.evidence : null, true)).toBe(true)
  })

  it('rejects invalid paths, failed inspections, missing files, non-files, bad metadata and missing hashes', () => {
    expect(buildWorkflowFileEvidence('', inspectedFile())).toMatchObject({ ok: false, code: 'INVALID_PATH' })
    expect(
      buildWorkflowFileEvidence(
        'E:\\media\\lesson.mp4',
        inspectedFile({
          ok: false,
          error: { code: 'METADATA_UNAVAILABLE', message: 'metadata failed', retryable: true },
        }),
      ),
    ).toMatchObject({ ok: false, code: 'INSPECTION_FAILED' })
    expect(
      buildWorkflowFileEvidence(
        'E:\\media\\lesson.mp4',
        inspectedFile({
          error: {
            code: 'FILE_CHANGED_DURING_INSPECTION',
            message: 'changed during inspection',
            retryable: true,
          },
        }),
      ),
    ).toMatchObject({ ok: false, code: 'INSPECTION_FAILED' })
    expect(
      buildWorkflowFileEvidence('E:\\media\\lesson.mp4', inspectedFile({ exists: false, isFile: false })),
    ).toMatchObject({ ok: false, code: 'FILE_MISSING' })
    expect(
      buildWorkflowFileEvidence(
        'E:\\media\\lesson.mp4',
        inspectedFile({
          ok: false,
          isFile: false,
          error: { code: 'UNSAFE_FILE_TYPE', message: 'not a regular file', retryable: false },
        }),
      ),
    ).toMatchObject({ ok: false, code: 'NOT_REGULAR_FILE' })
    expect(buildWorkflowFileEvidence('E:\\media\\lesson.mp4', inspectedFile({ size: -1 }))).toMatchObject({
      ok: false,
      code: 'INVALID_METADATA',
    })
    expect(buildWorkflowFileEvidence('E:\\cards\\lesson.apkg', inspectedFile(), true)).toMatchObject({
      ok: false,
      code: 'SHA256_MISSING',
    })
    expect(
      buildWorkflowFileEvidence('E:\\cards\\lesson.apkg', inspectedFile({ sha256: 'bad-hash' }), true),
    ).toMatchObject({ ok: false, code: 'SHA256_INVALID' })
  })

  it('compares source files strictly by size and modification time', () => {
    const expected = {
      path: 'E:\\media\\lesson.mp4',
      size: 1024,
      modifiedAtMs: 123_456,
    }

    expect(compareSourceFileEvidence(expected, inspectedFile())).toEqual({ matches: true })
    expect(compareSourceFileEvidence(expected, inspectedFile({ size: 1025 }))).toMatchObject({
      matches: false,
      code: 'SOURCE_CHANGED',
    })
    expect(compareSourceFileEvidence(expected, inspectedFile({ modifiedAtMs: 123_457 }))).toMatchObject({
      matches: false,
      code: 'SOURCE_CHANGED',
    })
    expect(compareSourceFileEvidence(expected, inspectedFile({ exists: false, isFile: false }))).toMatchObject({
      matches: false,
      code: 'FILE_MISSING',
    })
    expect(compareSourceFileEvidence({ ...expected, size: -1 }, inspectedFile())).toMatchObject({
      matches: false,
      code: 'INVALID_METADATA',
    })
  })

  it('compares APKG files by SHA-256 and rejects missing or changed hashes', () => {
    const expected = {
      path: 'E:\\cards\\lesson.apkg',
      size: 1024,
      modifiedAtMs: 123_456,
      sha256: SHA_A.toUpperCase(),
    }

    expect(
      compareApkgFileEvidence(expected, inspectedFile({ size: 2048, modifiedAtMs: 999_999, sha256: SHA_A })),
    ).toEqual({ matches: true })
    expect(compareApkgFileEvidence(expected, inspectedFile({ sha256: SHA_B }))).toMatchObject({
      matches: false,
      code: 'APKG_CHANGED',
    })
    expect(compareApkgFileEvidence(expected, inspectedFile())).toMatchObject({
      matches: false,
      code: 'SHA256_MISSING',
    })
    expect(compareApkgFileEvidence({ ...expected, sha256: undefined }, inspectedFile({ sha256: SHA_A }))).toMatchObject(
      {
        matches: false,
        code: 'SHA256_MISSING',
      },
    )
    expect(compareApkgFileEvidence({ ...expected, size: -1 }, inspectedFile({ sha256: SHA_A }))).toMatchObject({
      matches: false,
      code: 'INVALID_METADATA',
    })
  })

  it('persists valid evidence, rejects malformed evidence, and keeps secret scanning compatible', () => {
    const sourceEvidence = {
      id: 'single:video',
      role: 'video' as const,
      path: 'E:\\media\\access_token=public-filename.mp4',
      size: 1024,
      modifiedAtMs: 123_456,
    }
    const apkgEvidence = {
      path: 'E:\\cards\\lesson.apkg',
      size: 2048,
      modifiedAtMs: 234_567,
      sha256: SHA_A,
    }
    const checkpoint = normalizeWorkflowCheckpoint({
      request: {
        ...defaultRequest,
        video_path: sourceEvidence.path,
        subtitle_path: 'E:\\media\\lesson.srt',
      },
      productStep: 'deliver',
      artifactStage: 'apkg_ready',
      sourceEvidence: [
        sourceEvidence,
        {
          ...sourceEvidence,
          id: 'single:subtitle',
          role: 'subtitle' as const,
          path: 'E:\\media\\lesson.srt',
          size: 256,
        },
      ],
      apkgEvidence,
      updatedAt: 456,
    })

    expect(checkpointContainsSecret({ sourceEvidence, apkgEvidence })).toBe(false)
    expect(isWorkflowSourceEvidenceList(checkpoint.sourceEvidence)).toBe(true)
    expect(parseWorkflowCheckpoint(checkpoint)).toEqual(checkpoint)
    expect(
      parseWorkflowCheckpoint({
        ...checkpoint,
        sourceEvidence: { ...sourceEvidence, size: -1 },
      }),
    ).toBeNull()
    expect(
      parseWorkflowCheckpoint({
        ...checkpoint,
        apkgEvidence: {
          path: apkgEvidence.path,
          size: apkgEvidence.size,
          modifiedAtMs: apkgEvidence.modifiedAtMs,
        },
      }),
    ).toBeNull()
    expect(() =>
      normalizeWorkflowCheckpoint({
        request: defaultRequest,
        productStep: 'deliver',
        artifactStage: 'apkg_ready',
        apkgEvidence: {
          path: apkgEvidence.path,
          size: apkgEvidence.size,
          modifiedAtMs: apkgEvidence.modifiedAtMs,
        },
      }),
    ).toThrow('missing SHA-256')
  })
})

import { invoke } from '@tauri-apps/api/core'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { defaultRequest } from '../domain/options'
import {
  loadWorkflowCheckpoint,
  loadWorkflowCheckpointCandidate,
  normalizeWorkflowCheckpoint,
} from './workflowCheckpoint'

vi.mock('@tauri-apps/api/core', () => ({ invoke: vi.fn() }))

const invokeMock = vi.mocked(invoke)

describe('loadWorkflowCheckpoint backup recovery', () => {
  beforeEach(() => {
    invokeMock.mockReset()
    ;(window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__ = {}
  })

  afterEach(() => {
    delete (window as Window & { __TAURI_INTERNALS__?: unknown }).__TAURI_INTERNALS__
  })

  it('uses the guarded backup when the primary JSON is structurally invalid', async () => {
    const backup = normalizeWorkflowCheckpoint({
      request: defaultRequest,
      productStep: 'select',
      artifactStage: 'learning_points_ready',
      updatedAt: 123,
    })
    invokeMock.mockResolvedValueOnce({ ...backup, schemaVersion: 2 }).mockResolvedValueOnce(backup)

    await expect(loadWorkflowCheckpoint()).resolves.toEqual(backup)
    expect(invokeMock).toHaveBeenNthCalledWith(1, 'load_workflow_checkpoint')
    expect(invokeMock).toHaveBeenNthCalledWith(2, 'load_workflow_checkpoint_backup')
  })

  it('uses a valid backup when the primary looks like a checkpoint but has invalid nested fields', async () => {
    const primary = normalizeWorkflowCheckpoint({
      request: defaultRequest,
      productStep: 'select',
      artifactStage: 'learning_points_ready',
      updatedAt: 123,
    })
    const backup = normalizeWorkflowCheckpoint({
      request: defaultRequest,
      productStep: 'source',
      artifactStage: 'source_ready',
      updatedAt: 122,
    })
    invokeMock
      .mockResolvedValueOnce({ ...primary, request: { ...primary.request, batch_enabled: 'false' } })
      .mockResolvedValueOnce(backup)

    await expect(loadWorkflowCheckpoint()).resolves.toEqual(backup)
    expect(invokeMock).toHaveBeenNthCalledWith(2, 'load_workflow_checkpoint_backup')
  })
  it('does not read the backup when no primary checkpoint exists', async () => {
    invokeMock.mockResolvedValueOnce(null)

    await expect(loadWorkflowCheckpoint()).resolves.toBeNull()
    expect(invokeMock).toHaveBeenCalledTimes(1)
    expect(invokeMock).toHaveBeenCalledWith('load_workflow_checkpoint')
  })

  it('keeps a valid primary authoritative', async () => {
    const primary = normalizeWorkflowCheckpoint({
      request: defaultRequest,
      productStep: 'source',
      artifactStage: 'source_ready',
      updatedAt: 456,
    })
    invokeMock.mockResolvedValueOnce(primary)

    await expect(loadWorkflowCheckpoint()).resolves.toEqual(primary)
    expect(invokeMock).toHaveBeenCalledTimes(1)
  })

  it('lets recovery code request the backup candidate explicitly', async () => {
    const backup = normalizeWorkflowCheckpoint({
      request: defaultRequest,
      productStep: 'deliver',
      artifactStage: 'drafts_ready',
      updatedAt: 321,
    })
    invokeMock.mockResolvedValueOnce(backup)

    await expect(loadWorkflowCheckpointCandidate('backup')).resolves.toEqual(backup)
    expect(invokeMock).toHaveBeenCalledTimes(1)
    expect(invokeMock).toHaveBeenCalledWith('load_workflow_checkpoint_backup')
  })

  it('rejects an explicitly loaded backup candidate with an invalid schema', async () => {
    invokeMock.mockResolvedValueOnce({ schemaVersion: 1, request: {} })

    await expect(loadWorkflowCheckpointCandidate('backup')).resolves.toBeNull()
  })
})

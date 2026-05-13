import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { createDemoProject } from '../../domain/demoProject'
import { defaultRequest } from '../../domain/options'
import {
  countSelectedCards,
  getQualityCounts,
  getQualityDiagnostics,
  getQualityFunnel,
  getSegmentReviewCounts,
} from '../../domain/projectMetrics'
import type { Project, SegmentFilter } from '../../domain/types'
import { ReviewWorkspace } from './ReviewWorkspace'

function renderWorkspace(project: Project | null, overrides = {}) {
  const qualityCounts = getQualityCounts(project)
  const qualityDiagnostics = getQualityDiagnostics(project, qualityCounts.recommended)
  const firstSegment = project?.segments[0]
  const props = {
    activeSegment: firstSegment,
    activeSegmentId: firstSegment?.id ?? null,
    activeSegmentVideoSrc: '',
    activeTemplateLabel: '沉浸语言 V10',
    ankiVerifying: false,
    ankiVerifyResult: null,
    appBusy: false,
    lastExport: null,
    language: 'English',
    level: 'B1' as const,
    maxSegments: 0,
    motionDuration: 0,
    prefersReducedMotion: true,
    previewPanelRef: { current: null },
    previewRate: 1,
    project,
    qualityCounts,
    qualityDiagnostics,
    qualityFunnel: getQualityFunnel(project, qualityCounts, qualityDiagnostics),
    selectedCardCount: countSelectedCards(project),
    segmentFilter: 'all' as SegmentFilter,
    segmentReviewCounts: getSegmentReviewCounts(project),
    sourceMode: 'local' as const,
    templateId: 'immersive',
    visibleSegments: project?.segments ?? [],
    onGenerate: vi.fn(),
    onOpenAnkiImport: vi.fn(),
    onOpenSettings: vi.fn(),
    onPreviewRateChange: vi.fn(),
    onRevealExport: vi.fn(),
    onSegmentFilterChange: vi.fn(),
    onSelectCardsByQuality: vi.fn(),
    onSelectSegment: vi.fn(),
    onSetCardsEnabled: vi.fn(),
    onUpdateCard: vi.fn(),
    onVerifyAnkiImport: vi.fn(),
    ...overrides,
  }

  render(<ReviewWorkspace {...props} />)
  return props
}

describe('ReviewWorkspace', () => {
  it('renders the empty workbench and forwards primary actions', () => {
    const onGenerate = vi.fn()
    const onOpenSettings = vi.fn()

    renderWorkspace(null, { onGenerate, onOpenSettings })

    fireEvent.click(screen.getByRole('button', { name: /开始生成/ }))
    fireEvent.click(screen.getByRole('button', { name: /检查 API/ }))

    expect(screen.getByRole('heading', { name: '生成工作台' })).toBeInTheDocument()
    expect(screen.getByText('把真实素材变成 Anki 复习卡')).toBeInTheDocument()
    expect(onGenerate).toHaveBeenCalledTimes(1)
    expect(onOpenSettings).toHaveBeenCalledTimes(1)
  })

  it('renders review controls and forwards selection actions', () => {
    const project = createDemoProject(defaultRequest)
    const onSetCardsEnabled = vi.fn()
    const onSelectCardsByQuality = vi.fn()
    const onSelectSegment = vi.fn()

    renderWorkspace(project, { onSelectCardsByQuality, onSelectSegment, onSetCardsEnabled })

    fireEvent.click(screen.getByRole('button', { name: '全不选' }))
    fireEvent.click(screen.getByRole('button', { name: '只保留推荐' }))
    fireEvent.click(screen.getByRole('button', { name: /in the mood/ }))

    expect(screen.getByRole('heading', { name: 'AI 评审工作台' })).toBeInTheDocument()
    expect(screen.getByText('推荐保留')).toBeInTheDocument()
    expect(onSetCardsEnabled).toHaveBeenCalledWith(false)
    expect(onSelectCardsByQuality).toHaveBeenCalledWith('recommended')
    expect(onSelectSegment).toHaveBeenCalledWith('seg_demo_001')
  })
})

import '@testing-library/jest-dom/vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { buildReliabilityManifest } from '../../domain/reliability'
import { ReliabilitySummaryPanel } from './ReliabilitySummaryPanel'

afterEach(() => cleanup())

describe('ReliabilitySummaryPanel', () => {
  it('keeps structural reliability visible without implying semantic correctness', () => {
    const manifest = buildReliabilityManifest({
      outcomes: [
        { learning_point_id: 'lp-1', card_id: 'card-1', status: 'verified', blocker_codes: [] },
        { learning_point_id: 'lp-2', card_id: 'card-2', status: 'verified', blocker_codes: [] },
      ],
    })

    render(<ReliabilitySummaryPanel manifest={manifest} />)

    expect(screen.getByRole('status', { name: '制卡可靠性门禁' })).toBeInTheDocument()
    expect(screen.getByText('/ 2 个选点已通过')).toBeInTheDocument()
    expect(screen.getByText(/不等同于独立语义校对/)).toBeInTheDocument()
    expect(screen.getByText(/structural_v1（结构级）/)).toBeInTheDocument()
    expect(screen.getByText('结构通过')).toBeInTheDocument()
  })

  it('makes blocked outcomes explicit', () => {
    const manifest = buildReliabilityManifest({
      outcomes: [
        {
          learning_point_id: 'lp-review',
          card_id: 'card-review',
          status: 'needs_review',
          blocker_codes: ['FALLBACK_CARD_REQUIRES_REVIEW'],
        },
      ],
    })

    render(<ReliabilitySummaryPanel manifest={manifest} />)

    expect(screen.getByText(/可靠性门禁已阻断/)).toBeInTheDocument()
    expect(screen.getByText('待复核')).toBeInTheDocument()
  })
})

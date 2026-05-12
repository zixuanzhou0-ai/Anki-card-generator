import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { ReadinessPanel } from './ReadinessPanel'

describe('ReadinessPanel', () => {
  it('shows ready count and item details', () => {
    render(
      <ReadinessPanel
        items={[
          { id: 'source', label: '素材', done: true, detail: '已就绪' },
          { id: 'api', label: 'API', done: false, detail: '未测试' },
        ]}
      />,
    )

    expect(screen.getByText('1/2')).toBeInTheDocument()
    expect(screen.getByText('素材')).toBeInTheDocument()
    expect(screen.getByText('未测试')).toBeInTheDocument()
  })
})


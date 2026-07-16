import { readFileSync } from 'node:fs'

import { describe, expect, it } from 'vitest'

const appCss = readFileSync('src/app.css', 'utf8')

const workbenchMarker = '/* Three-step workbench ---------------------------------------------------- */'
const contractMarker = '/* Workbench layout and accessibility contract. Keep this after legacy styles. */'
const workbenchCss = appCss.slice(appCss.indexOf(workbenchMarker))
const contractCss = appCss.slice(appCss.indexOf(contractMarker))

function squash(value) {
  return value.replace(/\s+/g, ' ').trim()
}

function sectionBetween(source, start, end) {
  const startIndex = source.indexOf(start)
  if (startIndex < 0) return ''
  const endIndex = end ? source.indexOf(end, startIndex + start.length) : -1
  return source.slice(startIndex, endIndex < 0 ? undefined : endIndex)
}

describe('desktop workbench CSS contract', () => {
  it('uses one bounded canvas and the agreed navigation breakpoints', () => {
    expect(appCss.indexOf(workbenchMarker)).toBeGreaterThanOrEqual(0)
    expect(appCss.indexOf(contractMarker)).toBeGreaterThanOrEqual(0)
    expect(squash(appCss)).toContain('html, body, #root { height: 100%; overflow: hidden; }')
    expect(squash(workbenchCss)).toContain('.desktop-workspace { width: 100%; max-width: 1680px; margin-inline: auto;')

    const wide = sectionBetween(
      contractCss,
      '@media (min-width: 1440px)',
      '@media (min-width: 1240px) and (max-width: 1439px)',
    )
    const medium = sectionBetween(
      contractCss,
      '@media (min-width: 1240px) and (max-width: 1439px)',
      '@media (max-width: 1239px)',
    )
    const compact = sectionBetween(contractCss, '@media (max-width: 1239px)', '@media (max-height: 820px)')

    expect(squash(wide)).toContain('grid-template-columns: 224px minmax(0, 1fr);')
    expect(squash(medium)).toContain('grid-template-columns: 196px minmax(0, 1fr);')
    expect(squash(compact)).toContain('grid-template-columns: minmax(0, 1fr);')
    expect(squash(compact)).toContain('.workflow-rail { position: absolute;')
  })

  it('keeps the header and action bar outside the only workbench scroll surface', () => {
    const normalized = squash(workbenchCss)

    expect(normalized).toContain(
      '.source-workspace, .workflow-step-workspace { display: grid; grid-template-rows: auto minmax(0, 1fr) auto; overflow: hidden;',
    )
    expect(normalized).toContain(
      '.source-workspace-content, .workflow-step-scroll { min-width: 0; min-height: 0; overflow-x: hidden; overflow-y: auto;',
    )
    expect(normalized).toContain('scroll-padding-block: 20px 32px;')
    expect(normalized).toContain(
      '.source-workspace-action-bar, .workflow-delivery-action-bar { position: relative; z-index: 2; display: flex;',
    )
    expect(normalized).toContain('flex: 0 0 auto; flex-wrap: wrap;')
  })

  it('enforces readable controls, visible focus and safe long-path wrapping', () => {
    const normalized = squash(contractCss)

    expect(normalized).toContain('min-height: 44px;')
    expect(normalized).toContain('font-size: max(15px, 1em);')
    expect(normalized).toContain(
      "button:focus-visible, a[href]:focus-visible, summary:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible, [role='button']:focus-visible, [tabindex]:not([tabindex='-1']):focus-visible { outline: 3px solid rgba(36, 91, 133, 0.34); outline-offset: 2px; }",
    )
    expect(normalized).toContain(
      '.batch-deck-path, .export-paths strong { min-width: 0; overflow: visible; overflow-wrap: anywhere; text-overflow: clip; white-space: normal; word-break: break-word; }',
    )
  })

  it('uses honest indeterminate progress and makes it static for reduced motion', () => {
    const normalizedContract = squash(contractCss)
    const reducedMotion = sectionBetween(contractCss, '@media (prefers-reduced-motion: reduce)')
    const normalizedReducedMotion = squash(reducedMotion)

    expect(normalizedContract).toContain('.progress-bar.indeterminate span { width: 38% !important; min-width: 72px;')
    expect(normalizedContract).toContain('@keyframes progress-indeterminate')
    expect(normalizedContract).toContain('transition: none;')
    expect(normalizedReducedMotion).toContain('.spin { animation: none !important; }')
    expect(normalizedReducedMotion).toContain(
      '.progress-bar.indeterminate span { width: 38% !important; opacity: 0.72; transform: translateX(80%); animation: none !important; }',
    )
  })
})

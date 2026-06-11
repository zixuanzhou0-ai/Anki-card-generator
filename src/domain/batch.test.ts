import { describe, expect, it } from 'vitest'

import {
  buildBatchPackage,
  buildNestedDeckName,
  createDocumentBatchItems,
  createLocalVideoBatchItems,
  createUrlBatchItems,
  parseEpisodeCode,
  sanitizeDeckPart,
} from './batch'

describe('batch learning package domain', () => {
  it('sanitizes Anki deck parts and prevents accidental nested separators', () => {
    expect(sanitizeDeckPart('  Shameless: Season 1 / 无耻之徒::第一季  ')).toBe('Shameless - Season 1 - 无耻之徒 - 第一季')
    expect(sanitizeDeckPart('')).toBe('未命名')
    expect(buildNestedDeckName('无耻之徒 第一季', 'S01E01 - Pilot')).toBe('无耻之徒 第一季::S01E01 - Pilot')
  })

  it('parses common episode codes from filenames', () => {
    expect(parseEpisodeCode('Shameless.S01E01.Pilot.mp4')).toEqual({ code: 'S01E01', title: 'Pilot' })
    expect(parseEpisodeCode('Shameless - 1x02 - Frank the Plank.mkv')).toEqual({ code: 'S01E02', title: 'Frank the Plank' })
    expect(parseEpisodeCode('EP03 Aunt Ginger.mp4')).toEqual({ code: 'E03', title: 'Aunt Ginger' })
    expect(parseEpisodeCode('第04集 Casey Casden.mp4')).toEqual({ code: 'E04', title: 'Casey Casden' })
  })

  it('creates naturally sorted local video batch items and matches subtitles by basename', () => {
    const items = createLocalVideoBatchItems([
      'D:/Shows/Shameless/S01E02 Frank the Plank.mp4',
      'D:/Shows/Shameless/S01E01 Pilot.mp4',
      'D:/Shows/Shameless/S01E01 Pilot.srt',
      'D:/Shows/Shameless/S01E02 Frank the Plank.en.srt',
      'D:/Shows/Shameless/readme.txt',
    ])

    expect(items.map((item) => item.subdeck_title)).toEqual(['S01E01 - Pilot', 'S01E02 - Frank the Plank'])
    expect(items[0]).toMatchObject({ source_mode: 'local', video_path: 'D:/Shows/Shameless/S01E01 Pilot.mp4', subtitle_path: 'D:/Shows/Shameless/S01E01 Pilot.srt' })
    expect(items[1]).toMatchObject({ source_mode: 'local', video_path: 'D:/Shows/Shameless/S01E02 Frank the Plank.mp4', subtitle_path: 'D:/Shows/Shameless/S01E02 Frank the Plank.en.srt' })
  })

  it('deduplicates multiline URLs and keeps stable subdeck order', () => {
    const items = createUrlBatchItems(`
      https://www.youtube.com/watch?v=aaa
      not a url
      https://youtu.be/bbb
      https://www.youtube.com/watch?v=aaa
    `)

    expect(items.map((item) => item.source_url)).toEqual(['https://www.youtube.com/watch?v=aaa', 'https://youtu.be/bbb'])
    expect(items.map((item) => item.subdeck_title)).toEqual(['001 - www.youtube.com', '002 - youtu.be'])
  })

  it('creates document items from supported files only', () => {
    const items = createDocumentBatchItems([
      'E:/Docs/01 Intro.md',
      'E:/Docs/02 Notes.pdf',
      'E:/Docs/cover.png',
      'E:/Docs/03 Terms.docx',
    ])

    expect(items.map((item) => item.subdeck_title)).toEqual(['01 - Intro', '02 - Notes', '03 - Terms'])
    expect(items.map((item) => item.document_path)).toEqual(['E:/Docs/01 Intro.md', 'E:/Docs/02 Notes.pdf', 'E:/Docs/03 Terms.docx'])
  })

  it('builds a package with nested deck names and collision-safe children', () => {
    const batch = buildBatchPackage({
      title: '无耻之徒 第一季',
      source_mode: 'local',
      items: [
        { id: 'a', source_mode: 'local', enabled: true, title: 'Pilot', subdeck_title: 'Pilot', video_path: 'a.mp4' },
        { id: 'b', source_mode: 'local', enabled: true, title: 'Pilot', subdeck_title: 'Pilot', video_path: 'b.mp4' },
      ],
    })

    expect(batch.parent_deck_name).toBe('无耻之徒 第一季')
    expect(batch.items.map((item) => item.deck_name)).toEqual(['无耻之徒 第一季::Pilot', '无耻之徒 第一季::Pilot (2)'])
  })
})

export type BatchItemSourceMode = 'local' | 'url' | 'document'
export type BatchItemStatus = 'pending' | 'ready' | 'failed' | 'skipped' | 'generated' | 'exported'

export type BatchSourceItem = {
  id: string
  index?: number
  title: string
  subdeck_title: string
  deck_name?: string
  source_mode: BatchItemSourceMode
  enabled: boolean
  status?: BatchItemStatus
  source_url?: string
  video_path?: string
  subtitle_path?: string
  document_path?: string
  warning?: string
}

export type BatchLearningPackage = {
  id: string
  title: string
  source_mode: BatchItemSourceMode | 'mixed'
  parent_deck_name: string
  items: BatchSourceItem[]
  created_at: number
  updated_at: number
}

const videoExtensions = new Set(['.mp4', '.mkv', '.mov', '.webm', '.avi', '.m4v'])
const subtitleExtensions = new Set(['.srt', '.vtt', '.ass', '.ssa'])
const documentExtensions = new Set(['.txt', '.md', '.markdown', '.docx', '.epub', '.pdf'])

function pathBaseName(path: string) {
  return path.replace(/\\/g, '/').split('/').filter(Boolean).pop() ?? path
}

function extensionOf(path: string) {
  const name = pathBaseName(path)
  const match = name.match(/\.[^.]+$/)
  return match ? match[0].toLowerCase() : ''
}

function stemOf(path: string) {
  return pathBaseName(path).replace(/\.[^.]+$/, '')
}

function stripLanguageSuffix(stem: string) {
  return stem.replace(/\.(en|eng|zh|zho|chs|cht|cn|ja|jp|fr|es|ru)$/iu, '')
}

function cleanTitle(value: string) {
  return value
    .replace(/\.[^.]+$/u, '')
    .replace(/[._]+/gu, ' ')
    .replace(/\s*[-–—]\s*/gu, ' - ')
    .replace(/\s+/gu, ' ')
    .trim()
}

export function sanitizeDeckPart(value: string, fallback = '未命名') {
  const cleaned = String(value ?? '')
    .trim()
    .replace(/::+/gu, ' - ')
    .replace(/[\\/:*?"<>|]+/gu, ' - ')
    .replace(/\s*-\s*/gu, ' - ')
    .replace(/\s+/gu, ' ')
    .replace(/(?: - ){2,}/gu, ' - ')
    .replace(/^[-\s]+|[-\s]+$/gu, '')
  return cleaned || fallback
}

export function buildNestedDeckName(parent: string, child: string) {
  return `${sanitizeDeckPart(parent)}::${sanitizeDeckPart(child)}`
}

export function parseEpisodeCode(filename: string): { code: string; title: string } | null {
  const cleaned = cleanTitle(pathBaseName(filename))
  const seasonEpisode = cleaned.match(/(?:^|\b)S(\d{1,2})E(\d{1,2})(?:\b|\s|-)(.*)$/iu)
  if (seasonEpisode) {
    const code = `S${seasonEpisode[1].padStart(2, '0')}E${seasonEpisode[2].padStart(2, '0')}`
    return { code, title: sanitizeDeckPart(seasonEpisode[3] || cleaned.replace(seasonEpisode[0], ''), code) }
  }

  const oneBy = cleaned.match(/(?:^|\b)(\d{1,2})x(\d{1,2})(?:\b|\s|-)(.*)$/iu)
  if (oneBy) {
    const code = `S${oneBy[1].padStart(2, '0')}E${oneBy[2].padStart(2, '0')}`
    return { code, title: sanitizeDeckPart(oneBy[3] || cleaned.replace(oneBy[0], ''), code) }
  }

  const ep = cleaned.match(/(?:^|\b)EP?\s*(\d{1,3})(?:\b|\s|-)(.*)$/iu)
  if (ep) {
    const code = `E${ep[1].padStart(2, '0')}`
    return { code, title: sanitizeDeckPart(ep[2], code) }
  }

  const zh = cleaned.match(/第\s*(\d{1,3})\s*集(?:\b|\s|-)?(.*)$/u)
  if (zh) {
    const code = `E${zh[1].padStart(2, '0')}`
    return { code, title: sanitizeDeckPart(zh[2], code) }
  }

  const numeric = cleaned.match(/^(\d{1,3})\s+(.+)$/u)
  if (numeric) {
    return { code: numeric[1].padStart(2, '0'), title: sanitizeDeckPart(numeric[2]) }
  }

  return null
}

function naturalCompare(left: string, right: string) {
  return left.localeCompare(right, undefined, { numeric: true, sensitivity: 'base' })
}

function itemId(prefix: string, value: string, index: number) {
  const safe = sanitizeDeckPart(value, prefix).toLowerCase().replace(/[^a-z0-9\u3400-\u9fff]+/giu, '-').replace(/^-|-$/g, '')
  return `${prefix}_${String(index + 1).padStart(3, '0')}_${safe.slice(0, 36) || 'item'}`
}

function subdeckTitleFromStem(stem: string, index: number) {
  const episode = parseEpisodeCode(stem)
  if (episode) return `${episode.code} - ${episode.title}`
  const cleaned = sanitizeDeckPart(cleanTitle(stem))
  const numeric = cleaned.match(/^(\d{1,3})\s+(.+)$/u)
  if (numeric) return `${numeric[1].padStart(2, '0')} - ${sanitizeDeckPart(numeric[2])}`
  return `${String(index + 1).padStart(3, '0')} - ${cleaned}`
}

export function createLocalVideoBatchItems(paths: string[]): BatchSourceItem[] {
  const subtitles = new Map<string, string>()
  for (const path of paths) {
    if (!subtitleExtensions.has(extensionOf(path))) continue
    const stem = stemOf(path)
    subtitles.set(stem.toLowerCase(), path)
    subtitles.set(stripLanguageSuffix(stem).toLowerCase(), path)
  }

  return paths
    .filter((path) => videoExtensions.has(extensionOf(path)))
    .sort((a, b) => naturalCompare(pathBaseName(a), pathBaseName(b)))
    .map((path, index) => {
      const stem = stemOf(path)
      const subdeckTitle = subdeckTitleFromStem(stem, index)
      const subtitlePath = subtitles.get(stem.toLowerCase())
      return {
        id: itemId('local', stem, index),
        index,
        title: subdeckTitle,
        subdeck_title: subdeckTitle,
        source_mode: 'local' as const,
        enabled: true,
        status: 'ready' as const,
        video_path: path,
        subtitle_path: subtitlePath,
        warning: subtitlePath ? undefined : '未找到同名字幕，可稍后补充或使用自动字幕。',
      }
    })
}

function validUrl(line: string) {
  try {
    const url = new URL(line)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url : null
  } catch {
    return null
  }
}

export function createUrlBatchItems(input: string | string[]): BatchSourceItem[] {
  const lines = Array.isArray(input) ? input : input.split(/\r?\n/u)
  const seen = new Set<string>()
  const urls: URL[] = []
  for (const raw of lines) {
    const value = raw.trim()
    if (!value) continue
    const url = validUrl(value)
    if (!url || seen.has(url.href)) continue
    seen.add(url.href)
    urls.push(url)
  }
  return urls.map((url, index) => {
    const subdeckTitle = `${String(index + 1).padStart(3, '0')} - ${sanitizeDeckPart(url.hostname)}`
    return {
      id: itemId('url', url.href, index),
      index,
      title: subdeckTitle,
      subdeck_title: subdeckTitle,
      source_mode: 'url' as const,
      enabled: true,
      status: 'ready' as const,
      source_url: url.href,
    }
  })
}

export function createDocumentBatchItems(paths: string[]): BatchSourceItem[] {
  return paths
    .filter((path) => documentExtensions.has(extensionOf(path)))
    .sort((a, b) => naturalCompare(pathBaseName(a), pathBaseName(b)))
    .map((path, index) => {
      const subdeckTitle = subdeckTitleFromStem(stemOf(path), index)
      return {
        id: itemId('doc', path, index),
        index,
        title: subdeckTitle,
        subdeck_title: subdeckTitle,
        source_mode: 'document' as const,
        enabled: true,
        status: 'ready' as const,
        document_path: path,
      }
    })
}

function dedupeSubdeckTitles(items: BatchSourceItem[]) {
  const seen = new Map<string, number>()
  return items.map((item) => {
    const base = sanitizeDeckPart(item.subdeck_title || item.title)
    const count = seen.get(base) ?? 0
    seen.set(base, count + 1)
    const subdeckTitle = count ? `${base} (${count + 1})` : base
    return { ...item, subdeck_title: subdeckTitle }
  })
}

function itemReady(item: BatchSourceItem) {
  if (item.source_mode === 'local') return Boolean(item.video_path?.trim())
  if (item.source_mode === 'url') return Boolean(item.source_url?.trim())
  if (item.source_mode === 'document') return Boolean(item.document_path?.trim())
  return false
}

export function normalizeBatchItems(value: unknown, sourceMode?: BatchItemSourceMode): BatchSourceItem[] {
  if (!Array.isArray(value)) return []
  return value
    .filter((item): item is Partial<BatchSourceItem> => Boolean(item && typeof item === 'object'))
    .map((item, index) => {
      const source_mode = item.source_mode === 'url' || item.source_mode === 'document' || item.source_mode === 'local' ? item.source_mode : sourceMode
      if (!source_mode) return null
      const subdeck = sanitizeDeckPart(String(item.subdeck_title || item.title || `素材 ${index + 1}`))
      const normalized: BatchSourceItem = {
        id: String(item.id || itemId(source_mode, subdeck, index)),
        index,
        title: subdeck,
        subdeck_title: subdeck,
        deck_name: item.deck_name ? sanitizeDeckPart(String(item.deck_name)).replace(/ - /u, '::') : undefined,
        source_mode,
        enabled: item.enabled !== false,
        status: item.status ?? 'ready',
        source_url: typeof item.source_url === 'string' ? item.source_url.trim() : undefined,
        video_path: typeof item.video_path === 'string' ? item.video_path.trim() : undefined,
        subtitle_path: typeof item.subtitle_path === 'string' ? item.subtitle_path.trim() : undefined,
        document_path: typeof item.document_path === 'string' ? item.document_path.trim() : undefined,
        warning: typeof item.warning === 'string' ? item.warning : undefined,
      }
      return itemReady(normalized) ? normalized : null
    })
    .filter((item): item is BatchSourceItem => Boolean(item))
}

export function batchItemsForSource(items: BatchSourceItem[], sourceMode: BatchItemSourceMode) {
  return items.filter((item) => item.source_mode === sourceMode)
}

export function buildBatchPackage(input: {
  id?: string
  title: string
  source_mode: BatchLearningPackage['source_mode']
  items: BatchSourceItem[]
  created_at?: number
  updated_at?: number
}): BatchLearningPackage {
  const parent = sanitizeDeckPart(input.title, '批量学习包')
  const items = dedupeSubdeckTitles(input.items).map((item, index) => ({
    ...item,
    index,
    enabled: item.enabled !== false,
    deck_name: buildNestedDeckName(parent, item.subdeck_title || item.title),
  }))
  const now = Date.now()
  return {
    id: input.id ?? itemId('batch', parent, 0),
    title: parent,
    source_mode: input.source_mode,
    parent_deck_name: parent,
    items,
    created_at: input.created_at ?? now,
    updated_at: input.updated_at ?? now,
  }
}

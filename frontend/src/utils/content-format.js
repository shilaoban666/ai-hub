const COMPLETE_HTML_DOCUMENT_RE = /^(?:(?:\s|<!--[\s\S]*?-->)|<!doctype\s+html[^>]*>)*<html(?:\s[^>]*)?>[\s\S]*<\/html\s*>(?:(?:\s|<!--[\s\S]*?-->))*$/i
const COMPLETE_HTML_BODY_RE = /^<body(?:\s[^>]*)?>[\s\S]*<\/body\s*>$/i
const COMPLETE_HTML_FRAGMENT_RE = /^<(main|section|article|div|table|form|nav|header|footer|aside|dialog|details|figure|svg|canvas|ul|ol|button)(?:\s[^>]*)?>[\s\S]*<\/\1\s*>$/i
const COMPLETE_RENDERABLE_ELEMENT_RE = /<(main|section|article|div|table|form|nav|header|footer|aside|dialog|details|figure|svg|canvas|ul|ol|button)(?:\s[^>]*)?>[\s\S]*<\/\1\s*>/i
const HTML_DOCUMENT_OPEN_RE = /(?:<!doctype\s+html[^>]*>\s*)?<html(?:\s[^>]*)?>/gi
const HTML_DOCUMENT_CLOSE_RE = /<\/html\s*>/gi
const HTML_FENCE_OPEN_RE = /^( {0,3})(`{3,}|~{3,})[ \t]*(?:(html?|xhtml|html[-_]preview|preview[-_]html)[ \t]*)?\r?$/gim
const DIV_TAG_START_RE = /<\/?div\b/gi
const HTML_HELPER_CLASS_RE = /(?:^|\s)class\s*=\s*(?:"[^"]*\bhtml-helper-box\b[^"]*"|'[^']*\bhtml-helper-box\b[^']*'|[^\s>]*\bhtml-helper-box\b[^\s>]*)/i

const isCompleteRawHtml = (source) => {
  const value = String(source || '').trim()
  if (!value || !value.endsWith('>')) return false
  if (
    COMPLETE_HTML_DOCUMENT_RE.test(value)
    || COMPLETE_HTML_BODY_RE.test(value)
    || COMPLETE_HTML_FRAGMENT_RE.test(value)
  ) {
    return true
  }

  // Generated fragments commonly place style/script siblings around the root.
  return value.startsWith('<') && COMPLETE_RENDERABLE_ELEMENT_RE.test(value)
}

const trimFenceSeparator = (source, end) => {
  if (source.slice(Math.max(0, end - 2), end) === '\r\n') return end - 2
  if (source[end - 1] === '\n') return end - 1
  return end
}

const findHtmlFenceRanges = (source) => {
  const ranges = []
  HTML_FENCE_OPEN_RE.lastIndex = 0

  let opening
  while ((opening = HTML_FENCE_OPEN_RE.exec(source)) !== null) {
    const fence = opening[2]
    const hasHtmlLanguage = Boolean(opening[3])
    const fenceChar = fence[0]
    let contentStart = opening.index + opening[0].length
    if (source[contentStart] === '\n') contentStart += 1

    const closingRe = new RegExp(
      `^(?: {0,3})${fenceChar === '`' ? '\\`' : fenceChar}{${fence.length},}[ \\t]*\\r?$`,
      'gm',
    )
    closingRe.lastIndex = contentStart
    const closing = closingRe.exec(source)

    if (!closing) {
      const content = source.slice(contentStart)
      // MessageContent calls this parser only after streaming has finished.
      // Recover a complete document when the model forgot the closing fence.
      if (isCompleteRawHtml(content)) {
        ranges.push({
          start: opening.index,
          end: source.length,
          source: content,
        })
      }
      break
    }

    const contentEnd = trimFenceSeparator(source, closing.index)
    const content = source.slice(contentStart, contentEnd)
    const rangeEnd = closing.index + closing[0].length
    HTML_FENCE_OPEN_RE.lastIndex = rangeEnd
    if (!content.trim() || (!hasHtmlLanguage && !isCompleteRawHtml(content))) continue

    ranges.push({
      start: opening.index,
      end: rangeEnd,
      source: content,
    })
  }

  return ranges
}

const findEmbeddedHtmlDocumentRange = (source) => {
  HTML_DOCUMENT_OPEN_RE.lastIndex = 0
  let opening
  while ((opening = HTML_DOCUMENT_OPEN_RE.exec(source)) !== null) {
    HTML_DOCUMENT_CLOSE_RE.lastIndex = HTML_DOCUMENT_OPEN_RE.lastIndex
    const closing = HTML_DOCUMENT_CLOSE_RE.exec(source)
    if (closing) {
      const end = closing.index + closing[0].length
      return {
        start: opening.index,
        end,
        source: source.slice(opening.index, end),
      }
    }
  }
  return null
}

const findTagEnd = (source, start) => {
  let quote = ''
  for (let index = start; index < source.length; index += 1) {
    const char = source[index]
    if (quote) {
      if (char === quote) quote = ''
    } else if (char === '"' || char === "'") {
      quote = char
    } else if (char === '>') {
      return index + 1
    }
  }
  return -1
}

const findMatchingDivEnd = (source, openingEnd) => {
  let depth = 1
  DIV_TAG_START_RE.lastIndex = openingEnd
  let match
  while ((match = DIV_TAG_START_RE.exec(source)) !== null) {
    const tagEnd = findTagEnd(source, match.index)
    if (tagEnd < 0) return -1
    const tag = source.slice(match.index, tagEnd)
    if (/^<\/div\b/i.test(tag)) {
      depth -= 1
      if (depth === 0) return tagEnd
    } else if (!/\/\s*>$/.test(tag)) {
      depth += 1
    }
    DIV_TAG_START_RE.lastIndex = tagEnd
  }
  return -1
}

const findHtmlHelperBoxRanges = (source) => {
  const ranges = []
  DIV_TAG_START_RE.lastIndex = 0
  let match
  while ((match = DIV_TAG_START_RE.exec(source)) !== null) {
    const tagEnd = findTagEnd(source, match.index)
    if (tagEnd < 0) break
    const openingTag = source.slice(match.index, tagEnd)
    DIV_TAG_START_RE.lastIndex = tagEnd
    if (/^<\/div\b/i.test(openingTag) || !HTML_HELPER_CLASS_RE.test(openingTag)) continue

    const end = findMatchingDivEnd(source, tagEnd)
    if (end < 0) {
      DIV_TAG_START_RE.lastIndex = tagEnd
      continue
    }
    ranges.push({
      start: match.index,
      end,
      source: source.slice(match.index, end),
    })
    DIV_TAG_START_RE.lastIndex = end
  }
  return ranges
}

const splitAroundRanges = (source, ranges) => {
  const segments = []
  let cursor = 0

  for (const range of ranges) {
    if (range.start > cursor) {
      segments.push({ type: 'markdown', source: source.slice(cursor, range.start) })
    }
    segments.push({ type: 'html', source: range.source })
    cursor = range.end
  }
  if (cursor < source.length) {
    segments.push({ type: 'markdown', source: source.slice(cursor) })
  }
  return segments
}

/**
 * Split a completed response into Markdown and HTML preview artifacts. HTML is
 * explicit when fenced; a standalone or embedded complete document is also
 * previewed so small formatting differences in model output do not leak source.
 */
export function parseContentSegments(text) {
  const original = String(text || '')
  if (isCompleteRawHtml(original)) {
    return [{ type: 'html', source: original }]
  }

  const fencedRanges = findHtmlFenceRanges(original)
  if (fencedRanges.length > 0) return splitAroundRanges(original, fencedRanges)

  const documentRange = findEmbeddedHtmlDocumentRange(original)
  if (documentRange) return splitAroundRanges(original, [documentRange])

  const helperBoxRanges = findHtmlHelperBoxRanges(original)
  if (helperBoxRanges.length > 0) return splitAroundRanges(original, helperBoxRanges)

  return [{ type: 'markdown', source: original }]
}

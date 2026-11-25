const LEADING_DOCUMENT_RE = /^(?:\s|<!--[\s\S]*?-->|<!doctype\s+html[^>]*>)*<html(?:\s[^>]*)?>/i
const LEADING_HEAD_RE = /^(?:\s|<!--[\s\S]*?-->|<!doctype\s+html[^>]*>)*<head(?:\s[^>]*)?>/i
const HEAD_AFTER_HTML_RE = /^(?:\s|<!--[\s\S]*?-->)*<head(?:\s[^>]*)?>/i
const MALFORMED_INLINE_HANDLER_END_RE = /(\son[a-z][\w:-]*\s*=\s*")([^"]*?)\\"(?=\s*\/?>)/gi

export function normalizeMalformedInlineHandlerEscapes(content) {
  return String(content ?? '').replace(MALFORMED_INLINE_HANDLER_END_RE, '$1$2"')
}

export const ONLINE_PREVIEW_SCROLLBAR_STYLES = `<style data-aihub-preview-scrollbars>
  * {
    scrollbar-width: thin;
    scrollbar-color: #b8c0c9 #f3f5f7;
  }
  *::-webkit-scrollbar {
    width: 8px;
    height: 8px;
  }
  *::-webkit-scrollbar-track {
    background: #f3f5f7;
  }
  *::-webkit-scrollbar-thumb {
    min-width: 28px;
    min-height: 28px;
    border: 2px solid #f3f5f7;
    border-radius: 8px;
    background: #b8c0c9;
  }
  *::-webkit-scrollbar-thumb:hover {
    background: #929ca7;
  }
  *::-webkit-scrollbar-corner {
    background: #f3f5f7;
  }
</style>`

export const ONLINE_PREVIEW_ASSET_MARKUP = [
  ONLINE_PREVIEW_SCROLLBAR_STYLES,
  `<script data-aihub-preview-inline-handler-fix>
  (() => {
    const repair = (element) => {
      const handler = element.getAttribute?.('onclick')
      if (handler?.endsWith('\\\\')) {
        element.setAttribute('onclick', handler.slice(0, -1))
      }
    }
    const repairTree = (root) => {
      if (root?.nodeType !== 1) return
      repair(root)
      root.querySelectorAll?.('[onclick]').forEach(repair)
    }
    document.addEventListener('DOMContentLoaded', () => {
      document.querySelectorAll('[onclick]').forEach(repair)
      new MutationObserver((mutations) => {
        mutations.forEach(mutation => mutation.addedNodes.forEach(repairTree))
      }).observe(document.documentElement, { childList: true, subtree: true })
    }, { once: true })
  })()
  <\/script>`,
].join('\n')

export function buildHtmlPreviewDocument(content) {
  const source = normalizeMalformedInlineHandlerEscapes(content)
  const htmlMatch = LEADING_DOCUMENT_RE.exec(source)
  if (htmlMatch) {
    const htmlEnd = htmlMatch[0].length
    const headMatch = HEAD_AFTER_HTML_RE.exec(source.slice(htmlEnd))
    if (headMatch) {
      const insertAt = htmlEnd + headMatch[0].length
      return `${source.slice(0, insertAt)}\n${ONLINE_PREVIEW_ASSET_MARKUP}${source.slice(insertAt)}`
    }
    return `${source.slice(0, htmlEnd)}\n<head>${ONLINE_PREVIEW_ASSET_MARKUP}</head>${source.slice(htmlEnd)}`
  }

  const headMatch = LEADING_HEAD_RE.exec(source)
  if (headMatch) {
    const insertAt = headMatch[0].length
    return `${source.slice(0, insertAt)}\n${ONLINE_PREVIEW_ASSET_MARKUP}${source.slice(insertAt)}`
  }

  return `${ONLINE_PREVIEW_ASSET_MARKUP}\n${source}`
}

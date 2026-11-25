import { Marked, marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js/lib/core'
import bash from 'highlight.js/lib/languages/bash'
import css from 'highlight.js/lib/languages/css'
import javascript from 'highlight.js/lib/languages/javascript'
import json from 'highlight.js/lib/languages/json'
import markdown from 'highlight.js/lib/languages/markdown'
import plaintext from 'highlight.js/lib/languages/plaintext'
import python from 'highlight.js/lib/languages/python'
import sql from 'highlight.js/lib/languages/sql'
import typescript from 'highlight.js/lib/languages/typescript'
import xml from 'highlight.js/lib/languages/xml'
import yaml from 'highlight.js/lib/languages/yaml'
import DOMPurify from 'dompurify'

Object.entries({
  bash,
  css,
  javascript,
  json,
  markdown,
  plaintext,
  python,
  sql,
  typescript,
  xml,
  yaml,
}).forEach(([name, language]) => hljs.registerLanguage(name, language))
hljs.registerAliases(['html', 'vue'], { languageName: 'xml' })
hljs.registerAliases(['js', 'jsx'], { languageName: 'javascript' })
hljs.registerAliases(['ts', 'tsx'], { languageName: 'typescript' })
hljs.registerAliases(['sh', 'shell'], { languageName: 'bash' })

// marked v18:用 marked-highlight 插件接 highlight.js 做代码块高亮
marked.use(
  markedHighlight({
    langPrefix: 'hljs language-',
    highlight(code, lang) {
      const language = lang && hljs.getLanguage(lang) ? lang : 'plaintext'
      try {
        return hljs.highlight(code, { language }).value
      } catch {
        return code
      }
    },
  })
)

marked.use({
  renderer: {
    table(token) {
      const header = token.header.map(cell => this.tablecell(cell)).join('')
      const rows = token.rows
        .map(row => this.tablerow({ text: row.map(cell => this.tablecell(cell)).join('') }))
        .join('')
      const body = rows ? `<tbody>${rows}</tbody>` : ''
      return `<div class="markdown-table-wrap" role="region" aria-label="表格" tabindex="0"><table><thead>${this.tablerow({ text: header })}</thead>${body}</table></div>`
    },
  },
})

marked.setOptions({
  gfm: true,
  breaks: true,
  html: false,
})

const streamingMarked = new Marked({
  gfm: true,
  breaks: true,
})

// 给所有 <a> 加 target=_blank(避免 marked renderer 版本差异,用 DOMPurify hook 统一处理)
DOMPurify.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName === 'A') {
    node.setAttribute('target', '_blank')
    node.setAttribute('rel', 'noopener noreferrer')
  }
})

const sanitizeOptions = {
  ADD_ATTR: ['target', 'rel'],
  // Message appearance is controlled by the shared Markdown theme.
  FORBID_ATTR: ['style'],
}

const plainTextFallback = text => `<pre class="markdown-plain-fallback">${text.replace(/[&<>"']/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
})[char])}</pre>`

const renderWithFallback = (text, parser, phase) => {
  if (!text) return ''
  const source = String(text)
  try {
    const html = DOMPurify.sanitize(parser.parse(source), sanitizeOptions)
    if (html.trim() || !source.trim()) return html
    console.error(`[markdown:${phase}] 正文清洗后为空，已显示纯文本`)
  } catch (error) {
    // Preserve the reply and leave evidence for browser-specific failures.
    console.error(`[markdown:${phase}] 正文渲染失败，已显示纯文本`, error)
  }
  // Escaping avoids depending on either the Markdown parser or sanitizer when
  // they fail. Model-provided tags must remain inert in the fallback as well.
  return plainTextFallback(source)
}

/** Render safe Markdown without losing the source if formatting fails. */
export function renderMarkdown(text) {
  return renderWithFallback(text, marked, 'completed')
}

export function renderStreamingMarkdown(text) {
  return renderWithFallback(text, streamingMarked, 'streaming')
}

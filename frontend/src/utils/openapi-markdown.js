const INLINE_HEADING_RE = /([.!?。！？；;])[	 ]+(#{1,6})[	 ]+/g
const HEADING_BEFORE_TABLE_RE = /(^|\n)(#{1,6}[^\n|]*?)[\t ]+(?=\|)/g
const FLATTENED_TABLE_ROW_RE = /\|[\t ]+\|(?=[^\n|]*\|)/g

/**
 * Restore CommonMark structure when an OpenAPI description has had its line
 * breaks collapsed to spaces while being collected by the service registry.
 */
export function normalizeOpenApiMarkdown(value) {
  if (!value) return ''

  return String(value)
    .replace(/\r\n?/g, '\n')
    .replace(INLINE_HEADING_RE, '$1\n\n$2 ')
    .replace(HEADING_BEFORE_TABLE_RE, '$1$2\n\n')
    .replace(FLATTENED_TABLE_ROW_RE, '|\n|')
}

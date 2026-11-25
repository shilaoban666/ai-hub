import assert from 'node:assert/strict'
import test from 'node:test'

import { parseContentSegments } from '../src/utils/content-format.js'
import {
  buildHtmlPreviewDocument,
  normalizeMalformedInlineHandlerEscapes,
  ONLINE_PREVIEW_ASSET_MARKUP,
  ONLINE_PREVIEW_SCROLLBAR_STYLES,
} from '../src/utils/html-preview.js'

test('preserves a complete HTML document exactly', () => {
  const html = `\n<!doctype html>
<html>
  <head><script>window.answer = 42</script></head>
  <body onclick="window.clicked = true">content</body>
</html>\n`

  assert.deepEqual(parseContentSegments(html), [{ type: 'html', source: html }])
})

test('preserves fenced HTML content without trimming it', () => {
  const fencedHtml = '  <section><script>window.answer = 42</script></section>  '
  const response = `before\n\n\`\`\`html
${fencedHtml}
\`\`\`\n\nafter`

  const segments = parseContentSegments(response)

  assert.equal(segments[1].type, 'html')
  assert.equal(segments[1].source, fencedHtml)
})

test('recognizes common HTML fence variants consistently', () => {
  const variants = [
    ['``` HTML', '```'],
    ['~~~html', '~~~'],
    ['```` html-preview', '````'],
    ['```preview_html', '```'],
  ]

  for (const [opening, closing] of variants) {
    const html = '<custom-panel><span>content</span></custom-panel>'
    const segments = parseContentSegments(`${opening}\n${html}\n${closing}`)

    assert.deepEqual(segments, [{ type: 'html', source: html }])
  }
})

test('previews a closed HTML fence even when it contains a small fragment', () => {
  assert.deepEqual(parseContentSegments('```html\n<input value="ready">\n```'), [
    { type: 'html', source: '<input value="ready">' },
  ])
})

test('previews complete HTML inside an unlabelled code fence', () => {
  const html = '<div class="html-helper-box">xxxx</div>'

  assert.deepEqual(parseContentSegments(`\`\`\`\n${html}\n\`\`\``), [
    { type: 'html', source: html },
  ])
})

test('recovers a complete HTML document when the final fence is missing', () => {
  const html = '<!doctype html><html><body>done</body></html>'

  assert.deepEqual(parseContentSegments(`\`\`\`html\n${html}`), [
    { type: 'html', source: html },
  ])
})

test('keeps an unfinished HTML fence as Markdown', () => {
  const response = '```html\n<div>still generating'

  assert.deepEqual(parseContentSegments(response), [
    { type: 'markdown', source: response },
  ])
})

test('extracts a complete HTML document surrounded by explanation text', () => {
  const html = '<!doctype html><html><body>content</body></html>'
  const segments = parseContentSegments(`预览如下：\n${html}\n以上是结果。`)

  assert.deepEqual(segments, [
    { type: 'markdown', source: '预览如下：\n' },
    { type: 'html', source: html },
    { type: 'markdown', source: '\n以上是结果。' },
  ])
})

test('extracts a complete html-helper-box and keeps surrounding text', () => {
  const html = '<div class="html-helper-box">xxxx</div>'

  assert.deepEqual(parseContentSegments(`result: ${html} done`), [
    { type: 'markdown', source: 'result: ' },
    { type: 'html', source: html },
    { type: 'markdown', source: ' done' },
  ])
})

test('matches a complete nested html-helper-box without consuming later HTML', () => {
  const html = '<div class="card html-helper-box"><div>nested</div></div>'
  const trailingHtml = '<div>ordinary</div>'

  assert.deepEqual(parseContentSegments(`before ${html} between ${trailingHtml} after`), [
    { type: 'markdown', source: 'before ' },
    { type: 'html', source: html },
    { type: 'markdown', source: ` between ${trailingHtml} after` },
  ])
})

test('extracts multiple complete html-helper-box fragments in order', () => {
  const first = '<div class="html-helper-box first">first</div>'
  const second = "<div class='second html-helper-box'><div>second</div></div>"

  assert.deepEqual(parseContentSegments(`top ${first} middle ${second} bottom`), [
    { type: 'markdown', source: 'top ' },
    { type: 'html', source: first },
    { type: 'markdown', source: ' middle ' },
    { type: 'html', source: second },
    { type: 'markdown', source: ' bottom' },
  ])
})

test('keeps an incomplete html-helper-box as source', () => {
  const response = 'before <div class="html-helper-box"><div>unfinished</div> after'

  assert.deepEqual(parseContentSegments(response), [
    { type: 'markdown', source: response },
  ])
})

test('keeps embedded ordinary HTML and typed code fences as source', () => {
  const inline = 'For example <div>content</div> stays source.'
  const typedFence = '```text\n<div>content</div>\n```'

  assert.deepEqual(parseContentSegments(inline), [{ type: 'markdown', source: inline }])
  assert.deepEqual(parseContentSegments(typedFence), [{ type: 'markdown', source: typedFence }])
})

test('does not treat non-HTML code fences as previews', () => {
  const response = '```javascript\nconst template = "<div>code</div>"\n```'

  assert.deepEqual(parseContentSegments(response), [
    { type: 'markdown', source: response },
  ])
})

test('adds online assets without rewriting an HTML fragment', () => {
  const html = '  <section onclick="run()"><style>.x { color: red }</style><script>run()</script></section>  '
  const preview = buildHtmlPreviewDocument(html)

  assert.equal(preview, `${ONLINE_PREVIEW_ASSET_MARKUP}\n${html}`)
  assert.equal(preview.slice(ONLINE_PREVIEW_ASSET_MARKUP.length + 1), html)
})

test('injects online assets into head without changing the original HTML', () => {
  const html = '<!doctype html><html lang="zh-CN"><head data-id="raw"><title>T</title></head><body><script>run()</script></body></html>'
  const preview = buildHtmlPreviewDocument(html)

  assert.equal(preview.replace(`\n${ONLINE_PREVIEW_ASSET_MARKUP}`, ''), html)
  assert.match(preview, /<head data-id="raw">\n<link rel="stylesheet"/)
  assert.match(preview, /assets\.fancyqube\.net\/online\/css\/main\.css/)
  assert.match(preview, /assets\.fancyqube\.net\/online\/vue-view-page\/bootstrap\.custom\.css/)
  assert.match(preview, /assets\.fancyqube\.net\/xadmin\/layer\/jquery\.min\.js/)
  assert.match(preview, /assets\.fancyqube\.net\/xadmin\/vendor\/bootstrap\/js\/bootstrap\.min\.js/)
  assert.match(preview, /assets\.fancyqube\.net\/online\/js\/main\.js/)
  assert.match(preview, /assets\.fancyqube\.net\/xadmin\/layer\/layer\.js/)
  assert.match(preview, /assets\.fancyqube\.net\/common\/js\/axios\.min\.js/)
  assert.match(preview, /assets\.fancyqube\.net\/online\/js\/async_run_global_function\.js/)
  assert.match(preview, /assets\.fancyqube\.net\/online\/js\/async_run_global_bubble\.js/)
  assert.doesNotMatch(preview, /online\.fancyqube\.net/)
  assert.doesNotMatch(preview, /xadmin\/css\/xadmin\.main\.css/)
})

test('loads dependencies before the preview application', () => {
  const jqueryAt = ONLINE_PREVIEW_ASSET_MARKUP.indexOf('/xadmin/layer/jquery.min.js')
  const bootstrapAt = ONLINE_PREVIEW_ASSET_MARKUP.indexOf('/xadmin/vendor/bootstrap/js/bootstrap.min.js')
  const layerAt = ONLINE_PREVIEW_ASSET_MARKUP.indexOf('/xadmin/layer/layer.js')
  const axiosAt = ONLINE_PREVIEW_ASSET_MARKUP.indexOf('/common/js/axios.min.js')
  const bubbleAt = ONLINE_PREVIEW_ASSET_MARKUP.indexOf('/online/js/async_run_global_bubble.js')
  const mainAt = ONLINE_PREVIEW_ASSET_MARKUP.indexOf('/online/js/main.js')

  assert.ok(jqueryAt >= 0)
  assert.ok(jqueryAt < bootstrapAt)
  assert.ok(bootstrapAt < layerAt)
  assert.ok(layerAt < axiosAt)
  assert.ok(axiosAt < bubbleAt)
  assert.ok(bubbleAt < mainAt)
})

test('does not mistake head-like text inside scripts for a document head', () => {
  const html = '<script>window.template = "<head>"</script><section>content</section>'
  const preview = buildHtmlPreviewDocument(html)

  assert.equal(preview, `${ONLINE_PREVIEW_ASSET_MARKUP}\n${html}`)
})

test('injects the dedicated scrollbar theme into HTML previews', () => {
  const preview = buildHtmlPreviewDocument('<div style="height: 1000px">content</div>')

  assert.ok(ONLINE_PREVIEW_SCROLLBAR_STYLES.includes('scrollbar-width: thin'))
  assert.ok(ONLINE_PREVIEW_SCROLLBAR_STYLES.includes('*::-webkit-scrollbar-thumb'))
  assert.ok(preview.includes(ONLINE_PREVIEW_SCROLLBAR_STYLES))
})

test('repairs a JSON-escaped closing quote in an inline event handler', () => {
  const html = String.raw`<a onclick="showGlobalFunctionModal('YWJj', '详情', '30%', '60%')\">福州群尚</a>`
  const normalized = normalizeMalformedInlineHandlerEscapes(html)

  assert.equal(
    normalized,
    `<a onclick="showGlobalFunctionModal('YWJj', '详情', '30%', '60%')">福州群尚</a>`,
  )
  assert.ok(buildHtmlPreviewDocument(html).endsWith(`\n${normalized}`))
})

test('keeps valid backslashes inside inline event handlers', () => {
  const html = String.raw`<button onclick="usePath('C:\\temp')">open</button>`

  assert.equal(normalizeMalformedInlineHandlerEscapes(html), html)
})

test('injects a valid runtime repair for asynchronously added handlers', () => {
  const script = ONLINE_PREVIEW_ASSET_MARKUP.match(
    /<script data-aihub-preview-inline-handler-fix>([\s\S]*?)<\/script>/,
  )

  assert.ok(script)
  assert.doesNotThrow(() => new Function(script[1]))
})

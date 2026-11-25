import assert from 'node:assert/strict'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.CHAT_TEST_URL || 'http://127.0.0.1:15178'
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
const table = '### 评分结果\n\n| 平台 | 星级 | 评论数 |\n|---|---:|---:|\n| 示例平台 | 4.3 | 412 |'

try {
  const page = await browser.newPage()
  await page.route('**/markdown-recovery-test', route => route.fulfill({
    contentType: 'text/html', body: '<!doctype html><div id="reply"></div>',
  }))
  await page.goto(`${base}/markdown-recovery-test`)
  const moduleSource = await (await page.request.get(`${base}/src/utils/markdown.js`)).text()
  assert(moduleSource.includes('parser.parse(source)'), 'Use the Vite development server for failure injection')
  const variants = {
    'parser-failure': moduleSource.replace('parser.parse(source)', '(() => { throw new Error("injected parser failure") })()'),
    'sanitizer-failure': moduleSource.replace('DOMPurify.sanitize(parser.parse(source), sanitizeOptions)', '(() => { throw new Error("injected sanitizer failure") })()'),
    'empty-render': moduleSource.replace('parser.parse(source)', '""'),
  }
  for (const [name, source] of Object.entries(variants)) {
    await page.route(`**/src/utils/${name}.js`, route => route.fulfill({ contentType: 'text/javascript', body: source }))
  }
  const results = await page.evaluate(async ({ table, variants }) => {
    const normal = await import('/src/utils/markdown.js')
    const reply = document.querySelector('#reply')
    const normalResults = []
    for (const render of [normal.renderStreamingMarkdown, normal.renderMarkdown, normal.renderMarkdown]) {
      reply.innerHTML = render(table)
      normalResults.push({ tables: reply.querySelectorAll('table').length, text: reply.innerText })
    }
    const failures = []
    const errors = []
    const originalError = console.error
    console.error = (...args) => errors.push(String(args[0]))
    try {
      for (const name of variants) {
        const module = await import(`/src/utils/${name}.js`)
        for (const render of [module.renderStreamingMarkdown, module.renderMarkdown]) {
          const source = table + '\n<script>window.markdownInjected = true</script><img src=x onerror="window.markdownInjected=true">'
          reply.innerHTML = render(source)
          failures.push({ text: reply.textContent, source, unsafe: reply.querySelectorAll('script, img, [onerror]').length })
        }
      }
    } finally { console.error = originalError }
    return { normalResults, failures, errors, injected: Boolean(window.markdownInjected) }
  }, { table, variants: Object.keys(variants) })
  for (const result of results.normalResults) {
    assert.equal(result.tables, 1)
    assert.match(result.text, /4\.3/)
  }
  for (const result of results.failures) {
    assert.equal(result.text, result.source)
    assert.equal(result.unsafe, 0)
  }
  assert.equal(results.injected, false)
  assert.equal(results.errors.length, 6)
  console.log('Passed: streaming/completed/history tables; parser/sanitizer/empty-output recovery; escaped HTML; error evidence.')
} finally {
  await browser.close()
}

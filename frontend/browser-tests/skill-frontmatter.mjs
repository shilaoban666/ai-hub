import assert from 'node:assert/strict'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.SKILL_TEST_URL || 'http://127.0.0.1:15189'
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
const sample = '---\nname: "测试技能"\ndescription: "测试技能"\nauthor: "吴张洁"\nversion: "1.0.0"\n---\n\n# 正文标题\n\n普通正文\n\n二级标题\n---'

try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/frontmatter-test', route => route.fulfill({
    contentType: 'text/html', body: '<!doctype html><html><head><meta charset="utf-8"></head><body><div id="app"></div></body></html>',
  }))
  await page.goto(`${base}/frontmatter-test`)
  await page.evaluate(async source => {
    const { mount } = await import('/browser-tests/fixtures/skill-frontmatter.js')
    window.fixture = mount(source)
  }, sample)

  const cases = [
    sample,
    '\uFEFF' + sample.replaceAll('\n', '\r\n'),
    '---\nname: test\ndescription: |\n  ' + '很长的描述'.repeat(100) + '\n  第二行\nagent_created: false\ncount: 0\n---\n\n# 正文标题',
    '---\nname: test\ndescription: "<img src=x onerror=alert(1)> **文字** `代码`"\n---',
  ]
  for (const source of cases) {
    await page.evaluate(value => window.fixture.set(value), source)
    await page.waitForFunction(() => document.querySelectorAll('.skill-frontmatter').length === 2)
    await page.waitForFunction(expected => document.querySelector('#editor .cm-content')?.textContent.includes(expected),
      source.includes('count: 0') ? 'count: 0' : source.includes('<img') ? '<img' : 'version:')
    // MdEditor debounces its preview updates.
    const metadata = source.replace(/^\uFEFF/, '').replaceAll('\r\n', '\n').split('\n---')[0].slice(4)
    await page.waitForFunction(expected => [...document.querySelectorAll('.skill-frontmatter')].every(el => el.textContent === expected), metadata)
    const blocks = await page.locator('.skill-frontmatter').evaluateAll(nodes => nodes.map(node => ({
      fontSize: getComputedStyle(node.querySelector('code')).fontSize,
      fontWeight: getComputedStyle(node.querySelector('code')).fontWeight,
      paddingStart: getComputedStyle(node.querySelector('code')).paddingInlineStart,
      fits: node.scrollWidth <= node.clientWidth,
      unsafe: node.querySelectorAll('img, script, strong').length,
    })))
    for (const block of blocks) {
      assert.equal(block.fontSize, '14px')
      assert.equal(block.fontWeight, '400')
      assert.equal(block.paddingStart, '0px')
      assert.equal(block.fits, true)
      assert.equal(block.unsafe, 0)
    }
    // CodeMirror already normalizes CRLF while loading editor text.
    assert.equal(await page.evaluate(() => window.fixture.get()), source.replaceAll('\r\n', '\n'), 'Rendering must preserve metadata and body')
    assert.equal(await page.locator('h2').filter({ hasText: /name:|description:/ }).count(), 0)
  }

  await page.evaluate(value => window.fixture.set(value), sample)
  await page.waitForFunction(() => document.querySelectorAll('h2').length === 2)
  assert.equal(await page.locator('#preview h1').innerText(), '正文标题')
  assert.equal(await page.locator('#preview h2').innerText(), '二级标题')
  if (process.env.SKILL_SCREENSHOT_PATH) await page.screenshot({ path: process.env.SKILL_SCREENSHOT_PATH, fullPage: true })

  for (const source of ['---\n\n普通正文\n\n---', '---\nname: 未闭合', '# 普通文档\n\n标题\n---']) {
    await page.evaluate(value => window.fixture.set(value), source)
    await page.waitForFunction(() => document.querySelectorAll('.skill-frontmatter').length === 0)
  }
  assert.deepEqual(errors, [])
  console.log('Passed: preview/editor metadata at 14px/400, BOM/CRLF, multiline/wrapping, HTML escaping, unchanged source, normal headings/rules and unclosed metadata.')
} finally {
  await browser.close()
}

import assert from 'node:assert/strict'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.EMBED_TEST_URL || 'http://127.0.0.1:15177'
const longName = 'mcp__online-mcp__common_service_get_i_v1_public_params_by_ename'
const table = [
  '| 发货计划号 | 发货批次号 | 发货数量 | 大件发货流程节点 | 发货区域 |',
  '| --- | --- | --- | --- | --- |',
  ...Array.from({ length: 45 }, (_, i) => `| FHJH260911-${i} | 无 | 5 | 数据库值：907，页面显示值：回收站 | 数据库值：us_south，页面显示值：美南 |`),
].join('\n')
const history = [{ id: 1, role: 'assistant', content: JSON.stringify([
  ...[longName, 'Bash', longName].flatMap((name, i) => [
    { type: 'tool_use', tool_use_id: `tool-${i}`, name, input: i === 1 ? { command: 'ls -la /workspace' } : (i === 2 ? { url: 'https://example.test/long-summary' } : {}) },
    { type: 'tool_result', tool_use_id: `tool-${i}`, content: '完成', duration_ms: 141 },
  ]),
  { type: 'text', content: `查询结果\n\n${table}\n\n查询完成。` },
]) }]

const browser = await chromium.launch({ channel: 'msedge', headless: true })
const failures = []
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/embed-layout-host') return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><head><meta charset="utf-8"></head><body style="margin:0;min-height:4000px"><p>业务页面</p><script src="/embed/assistant.js" data-aihub-url="/embed/chat?session=3"></script></body></html>` })
    if (url.pathname === '/func_process_app/aihub_embed_auth/') {
      const { action } = route.request().postDataJSON()
      return route.fulfill({ json: { code: 0, data: { user_id: 7, session_id: 'a'.repeat(64), ...(action === 'authorize' ? { access_token: 'layout-test-only', token_type: 'bearer', expires_in: 900 } : {}) } } })
    }
    if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
    let body = { items: [], total: 0 }
    if (url.pathname === '/iam/api/me') body = { id: 7, username: 'test', permissions: [] }
    if (url.pathname.endsWith('/bootstrap')) body = { assistant_id: 1 }
    if (url.pathname.endsWith('/credits/me')) body = { claimed_today: true, available_balance: 100 }
    if (url.pathname === '/aihub/api/agents/1') body = { id: 1, name: 'AI 助手', kind: 'personal_default', runtime_type: 'claude_code', default_model_id: 1, models: [{ id: 1, name: '测试模型' }], skills: [] }
    if (url.pathname.endsWith('/sessions/3/messages')) body = { session: { id: 3, source: 'web' }, items: history }
    return route.fulfill({ json: body })
  })
  await page.goto(`${base}/embed-layout-host`)
  await page.evaluate(() => window.scrollTo(0, 300))
  await page.getByRole('button', { name: '打开 AI 助手', exact: true }).click()
  const chat = page.frameLocator('iframe[title="AI Hub 对话"]')
  const messages = chat.locator('.messages')
  const wrap = chat.locator('.markdown-table-wrap')
  await wrap.waitFor()
  await chat.locator('.process-group-header').click()
  const check = (value, message) => { if (!value) failures.push(message) }
  for (const mode of ['normal', 'expanded', 'mobile']) {
    if (mode === 'expanded') await page.getByRole('button', { name: '展开面板', exact: true }).click()
    if (mode === 'mobile') await page.setViewportSize({ width: 390, height: 844 })
    await messages.evaluate(el => { el.scrollTop = 0 })
    await chat.locator('.tool-card-header').first().scrollIntoViewIfNeeded()
    for (const header of await chat.locator('.tool-card-header').all()) {
      const bounds = await header.evaluate(el => {
        const rect = selector => el.querySelector(selector).getBoundingClientRect()
        return { nameRight: rect('.tool-name').right, rightLeft: rect('.tool-right').left, rightRight: rect('.tool-right').right, headerRight: el.getBoundingClientRect().right }
      })
      check(bounds.nameRight + 5 <= bounds.rightLeft && bounds.rightRight <= bounds.headerRight, `${mode}: tool name overlaps duration or overflows header`)
    }
    for (let cycle = 0; cycle < 2; cycle++) {
      if (cycle) {
        await page.getByRole('button', { name: '收起助手', exact: true }).click()
        await page.getByRole('button', { name: '打开 AI 助手', exact: true }).click()
      }
      // Put a tall table under the pointer, away from either conversation boundary.
      await messages.evaluate(el => {
        const table = el.querySelector('.markdown-table-wrap')
        el.scrollTop += table.getBoundingClientRect().top - el.getBoundingClientRect().top + 250
      })
      const box = await messages.boundingBox()
      await page.mouse.move(box.x + box.width / 2, box.y + 100)
      assert(await wrap.evaluate(el => {
        const messages = document.querySelector('.messages').getBoundingClientRect()
        return el.contains(document.elementFromPoint(messages.x + messages.width / 2, messages.y + 100))
      }), 'Wheel target must be inside the table')
      for (const direction of [1, -1]) {
        const before = await messages.evaluate(el => el.scrollTop)
        await page.mouse.wheel(0, direction * 200)
        await page.waitForTimeout(300)
        const after = await messages.evaluate(el => el.scrollTop)
        check((after - before) * direction > 50, `${mode}, reopen ${cycle}: table blocks ${direction > 0 ? 'down' : 'up'} wheel`)
      }
      if (await wrap.evaluate(el => el.scrollWidth > el.clientWidth)) {
        await wrap.evaluate(el => { el.scrollLeft = 0 })
        await page.mouse.wheel(220, 0)
        await page.waitForTimeout(300)
        check(await wrap.evaluate(el => el.scrollLeft > 0), `${mode}: table horizontal scrolling must remain available`)
      }
      check(await page.evaluate(() => scrollY === 300), `${mode}: conversation must not scroll business page`)
    }
    for (const direction of [-1, 1]) {
      await messages.evaluate((el, dir) => { el.scrollTop = dir < 0 ? 0 : el.scrollHeight }, direction)
      const box = await messages.boundingBox()
      await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
      await page.mouse.wheel(0, direction * 500)
      await page.waitForTimeout(300)
      check(await page.evaluate(() => scrollY === 300), `${mode}: conversation boundary must not scroll business page`)
    }
    check(await chat.locator('html').evaluate(el => el.scrollWidth <= innerWidth && el.scrollHeight <= innerHeight), `${mode}: iframe must not gain document scrollbars`)
  }
  assert.deepEqual(errors, [])
  assert.deepEqual(failures, [])
  console.log('Embedded content checks passed: long tool names, vertical table wheel, horizontal table wheel, reopen, scroll boundaries; normal, expanded and mobile drawers.')
} finally {
  await browser.close()
}

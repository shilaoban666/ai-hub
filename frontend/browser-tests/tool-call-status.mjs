import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.CHAT_TEST_URL || 'http://localhost:15177'
const output = path.resolve('node_modules/.cache/tool-call-status')
await mkdir(output, { recursive: true })
const blocked = 'Error: PreToolUse:Bash hook error: [/usr/bin/python3 pre_tool_use.py]: [workspace_isolation] 拒绝:危险命令模式。所有路径与命令必须在工作区内。'
const call = (id, result, isError) => [
  { type: 'tool_use', tool_use_id: id, name: 'Bash', input: { command: 'ls -la /workspace' } },
  { type: 'tool_result', tool_use_id: id, content: result, is_error: isError },
]
const history = [
  { id: 1, role: 'assistant', content: JSON.stringify([...call('blocked', blocked, true), ...call('ok', 'file.txt', false)]) },
  { id: 2, role: 'assistant', content: JSON.stringify([
    ...call('blocked-json', JSON.stringify({ error: '[workspace_isolation] 拒绝:路径越界' }), true),
    ...call('failed', JSON.stringify({ error: 'Command exited with code 1' }), true),
    ...call('last-ok', 'Recovered', false),
  ]) },
  { id: 3, role: 'assistant', content: JSON.stringify(call('single-blocked', blocked, true)) },
  { id: 4, role: 'assistant', content: JSON.stringify([
    ...Array.from({ length: 5 }, (_, index) => [
      ...call(`consecutive-${index}`, `result-${index}`, false).map(block => ({ ...block, duration_ms: index === 4 ? 1100 : 0 })),
      { type: 'usage', usage: { input_tokens: 10 } },
      { type: 'text', content: '\n' },
    ]).flat(),
    { type: 'text', content: '五次检查已经完成，文件内容已核对。' },
  ]) },
]
history.push({ id: 5, role: 'assistant', content: JSON.stringify([
  { type: 'tool_use', tool_use_id: 'skill-used', name: 'Skill', input: { skill: 'online-business-assistant', args: 'SKU lookup' } },
  { type: 'tool_result', tool_use_id: 'skill-used', content: 'Skill loaded' },
]) })
const browser = await chromium.launch({ channel: 'msedge', headless: true })
try {
  for (const width of [1440, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 1100 } })
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => localStorage.setItem('access_token', 'tool-status-test'))
    await page.route('**/*', route => {
      const url = new URL(route.request().url())
      if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
      let body = { items: [], total: 0 }
      if (url.pathname === '/iam/api/me') body = { id: 7, username: 'test', permissions: [] }
      if (url.pathname.endsWith('/bootstrap')) body = { assistant_id: 1 }
      if (url.pathname.endsWith('/credits/me')) body = { claimed_today: true, available_balance: 100 }
      if (url.pathname === '/aihub/api/agents/1') body = { id: 1, name: 'AI 助手', icon: 'H', kind: 'personal_default', runtime_type: 'claude_code', default_model_id: 1, models: [{ id: 1, name: '测试模型' }], skills: [] }
      if (url.pathname.endsWith('/sessions/3/messages')) body = { session: { id: 3, source: 'web' }, items: history }
      if (url.pathname === '/aihub/api/agents/1/messages' && route.request().method() === 'POST') {
        return route.fulfill({ contentType: 'text/event-stream', body: [
          { type: 'run_start', run_id: 'status-test', session_id: 3 },
          ...call('live-blocked', blocked, true),
          { type: 'done' },
        ].map(event => `data: ${JSON.stringify(event)}\n\n`).join('') })
      }
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    })
    await page.goto(`${base}/embed/chat?session=3`)
    await page.locator('.process-group').nth(1).waitFor()
    const warningGroup = page.locator('.process-group').nth(0)
    const mixedGroup = page.locator('.process-group').nth(1)
    assert.equal(await warningGroup.locator('.process-title').textContent(), '部分调用被拦截')
    assert.equal(await warningGroup.locator('.process-status.is-warning').count(), 1)
    assert.equal(await warningGroup.locator('.tool-card.status-error').count(), 0)
    assert.equal(await mixedGroup.locator('.process-title').textContent(), '执行异常')
    assert.equal(await mixedGroup.locator('.process-status.is-error').count(), 1)
    assert.equal(await mixedGroup.locator('.process-step.is-last.is-error').count(), 0)
    const singleGroup = page.locator('.process-group').nth(2)
    assert.equal(await singleGroup.locator('.process-title').textContent(), '调用被拦截')
    for (const group of [warningGroup, singleGroup]) {
      assert.equal(await group.locator('.process-group-header').getAttribute('aria-expanded'), 'false', 'Historical warnings must start collapsed')
      assert.equal(await group.locator('.process-group-body').isVisible(), false)
      await group.locator('.process-group-header').click()
      assert.equal(await group.locator('.process-group-body').isVisible(), true, 'Warning details must remain available on demand')
    }
    assert.equal(await mixedGroup.locator('.process-group-header').getAttribute('aria-expanded'), 'true', 'Actual errors remain expanded')
    for (const group of [warningGroup, mixedGroup, singleGroup]) {
      const color = await group.locator('.process-status').evaluate(el => getComputedStyle(el).color)
      assert.equal(await group.locator('.process-title').evaluate(el => getComputedStyle(el).color), color)
    }
    for (const card of await page.locator('.tool-card.status-warning, .tool-card.status-error').all()) {
      await card.locator('.tool-card-header').click()
      const status = await card.getAttribute('class')
      const expected = status.includes('status-warning') ? 'rgb(230, 162, 60)' : 'rgb(245, 108, 108)'
      assert.equal(await card.locator('.tool-status').evaluate(el => getComputedStyle(el).color), expected)
      assert.equal(await card.locator('.tool-output').evaluate(el => getComputedStyle(el).color), expected)
      assert.equal(await card.evaluate(el => getComputedStyle(el.closest('.process-step'), '::after').backgroundColor), expected)
    }
    await warningGroup.scrollIntoViewIfNeeded()
    await page.screenshot({ path: path.join(output, `history-${width}.png`), animations: 'disabled' })
    const consecutiveMessage = page.locator('.message-row.assistant').nth(3)
    const consecutiveGroup = consecutiveMessage.locator('.process-group')
    assert.equal(await consecutiveGroup.count(), 1, 'Usage records must not create repeated summary rows')
    assert.equal(await consecutiveGroup.locator('.process-summary').textContent(), '5 次工具调用')
    assert.equal(await consecutiveGroup.locator('.process-summary').isVisible(), true, 'Mobile keeps the total call count')
    assert.equal(await consecutiveGroup.locator('.process-duration').textContent(), '1.1s')
    assert.equal(await consecutiveGroup.locator('.process-group-body').isVisible(), false)
    assert.equal(await consecutiveMessage.getByText('五次检查已经完成，文件内容已核对。').isVisible(), true)
    await consecutiveGroup.scrollIntoViewIfNeeded()
    await page.screenshot({ path: path.join(output, `consecutive-collapsed-${width}.png`), animations: 'disabled' })
    await consecutiveGroup.locator('.process-group-header').click()
    assert.equal(await consecutiveGroup.locator('.tool-card:visible').count(), 5)
    await consecutiveGroup.locator('.tool-card-header').nth(4).click()
    assert.equal(await consecutiveGroup.locator('.tool-output:visible').textContent(), 'result-4')
    await page.screenshot({ path: path.join(output, `consecutive-expanded-${width}.png`), animations: 'disabled' })
    await consecutiveGroup.locator('.process-group-header').click()
    const skillGroup = page.locator('.message-row.assistant').nth(4).locator('.process-group')
    await skillGroup.locator('.process-group-header').click()
    assert.equal(await skillGroup.locator('.tool-summary').textContent(), 'online-business-assistant')
    assert.equal(await skillGroup.locator('.tool-summary').getAttribute('title'), 'online-business-assistant')
    assert.equal(await skillGroup.locator('.tool-card-body').isVisible(), false, 'The skill name is visible without opening its details')
    await skillGroup.scrollIntoViewIfNeeded()
    await page.screenshot({ path: path.join(output, `skill-name-${width}.png`), animations: 'disabled' })
    await page.getByPlaceholder('输入问题或任务').fill('Check blocked command')
    const send = page.getByRole('button', { name: '发送', exact: true })
    await send.click()
    await send.waitFor()
    const liveGroup = page.locator('.process-group').last()
    assert.equal(await liveGroup.locator('.process-title').textContent(), '调用被拦截')
    assert.equal(await liveGroup.locator('.tool-card.status-warning').count(), 1)
    assert.equal(await liveGroup.locator('.tool-card.status-error').count(), 0)
    assert.equal(await liveGroup.locator('.process-group-header').getAttribute('aria-expanded'), 'false', 'Completed blocked calls must collapse automatically')
    assert.equal(await liveGroup.locator('.process-group-body').isVisible(), false)
    await page.screenshot({ path: path.join(output, `completed-warning-${width}.png`), animations: 'disabled' })
    await liveGroup.locator('.process-group-header').click()
    assert.equal(await liveGroup.locator('.process-status').evaluate(el => getComputedStyle(el).color),
      await liveGroup.locator('.tool-status').evaluate(el => getComputedStyle(el).color))
    await liveGroup.locator('.tool-card-header').click()
    await page.screenshot({ path: path.join(output, `live-${width}.png`), animations: 'disabled' })
    assert.deepEqual(errors, [])
    await page.close()
  }
  console.log('Tool status browser checks passed: history, live messages, warnings, mixed errors, JSON output, desktop and mobile.')
} finally {
  await browser.close()
}

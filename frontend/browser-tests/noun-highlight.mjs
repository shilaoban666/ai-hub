import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.CHAT_TEST_URL || 'http://127.0.0.1:15179'
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 1080 } })
page.setDefaultTimeout(12000)
const errors = []
const model = { id: 1, name: '测试模型', scope: 'platform', is_enabled: true, has_api_key: true, api_protocol: 'anthropic-messages' }
let published = { version: 1, assistant_name: '默认助手', assistant_icon: 'H', assistant_mascot: '@cow', default_model_id: 1 }
let draft = null
let agent = { id: 9, name: '库存专家', user_id: 7, kind: 'expert', runtime_type: 'claude_code',
  default_model_id: 1, models: [model], skills: [], can_edit: true }
let nounRequests = 0, failNouns = false
const question = '请解释我方测算库龄与库龄，SKU、sku。'
const sentQuestion = '请解释我方测算库'
const response = '我方测算库龄，`我方测算库龄`，[我方测算库龄](https://existing.example/)\n\n| 指标 |\n| --- |\n| 我方测算库龄 |\n\n```text\n我方测算库龄\n```'
const history = [
  { id: 1, role: 'user', content: question },
  { id: 2, role: 'assistant', content: JSON.stringify([{ type: 'text', content: response }]) },
]
await page.addInitScript(() => {
  localStorage.setItem('access_token', 'noun-highlight-test-only')
  const original = window.fetch
  window.fetch = async (...args) => {
    const response = await original(...args)
    if (!response.headers.get('content-type')?.includes('text/event-stream')) return response
    const initial = await response.text()
    const encoder = new TextEncoder()
    return new Response(new ReadableStream({
      start(controller) {
        controller.enqueue(encoder.encode(initial))
        window.appendNounStream = (events, close = false) => {
          controller.enqueue(encoder.encode(events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('')))
          if (close) controller.close()
        }
      },
    }), { headers: { 'content-type': 'text/event-stream' } })
  }
})
page.on('pageerror', error => errors.push(error.message))
await page.route('**/*', async route => {
  const url = new URL(route.request().url()), path = url.pathname, method = route.request().method()
  if (!/^\/(aihub|iam)\/api\//.test(path)) return route.continue()
  let body = { items: [], total: 0 }
  if (path === '/iam/api/me') body = { id: 7, username: 'tester', is_superuser: true, permissions: [] }
  else if (path === '/iam/api/noun-explanations/names') {
    nounRequests++
    if (failNouns) return route.fulfill({ status: 503, json: { message: 'temporarily unavailable' } })
    body = { code: 200, data: { items: ['我方测算库龄', '库龄', 'SKU', '主体业务', '审核通过的FN头程费',
      '组合SKU的可用数量', '函数管理中的接口函数id', '通过数据渲染后的模板字符串', 'ASIN的BSRid', 'ASIN的BSR排名'] } }
  } else if (path.endsWith('/admin/platform-models') || path.endsWith('/models')) body = { items: [model] }
  else if (path.endsWith('/admin/workbench-settings')) body = { published, draft }
  else if (path.endsWith('/admin/workbench-settings/draft')) body = draft = { ...route.request().postDataJSON(), version: published.version + 1 }
  else if (path.endsWith('/admin/workbench-settings/publish')) {
    body = published = { ...route.request().postDataJSON(), version: published.version + 1 }
    draft = null
  } else if (path.endsWith('/bootstrap')) body = { assistant_id: 1,
    assistant: { ...agent, id: 1, kind: 'personal_default', name: '默认助手',
      noun_highlight_enabled: published.noun_highlight_enabled, noun_explanation_url: published.noun_explanation_url },
    credit: { claimed_today: true, available_balance: 100 } }
  else if (path === '/aihub/api/agents/9') {
    if (method === 'PUT') agent = { ...agent, ...route.request().postDataJSON() }
    body = agent
  } else if (path === '/aihub/api/agents') body = { items: [agent], total: 1 }
  else if (path.endsWith('/sessions/3/messages')) body = { session: { id: 3, title: '名词验证', source: 'web', model_id: 1 }, items: history }
  else if (path.endsWith('/sessions')) body = { items: [{ id: 3, title: '名词验证', source: 'web', model_id: 1 }], total: 1 }
  else if (path.endsWith('/messages') && method === 'POST') {
    assert.equal(route.request().postDataJSON().content, sentQuestion)
    const events = [{ type: 'run_start', run_id: 'noun-run', session_id: 3 }, { type: 'text', content: '请看我方测算' }]
    return route.fulfill({ contentType: 'text/event-stream', body: events.map(event => `data: ${JSON.stringify(event)}\n\n`).join('') })
  } else if (path.endsWith('/runtime-status')) body = { status: 'not_applicable', runtime_type: 'claude_code' }
  else if (path.endsWith('/files')) body = { type: 'dir', items: [] }
  return route.fulfill({ json: body })
})
const switchControl = scope => scope.getByRole('switch', { name: '名词解释高亮', exact: true }).locator('..')
const linkInput = scope => scope.locator('.el-form-item').filter({ has: page.locator('label').filter({ hasText: '名词解释链接' }) }).getByRole('textbox')
const links = scope => scope.locator('a.noun-explanation-link')
const navigate = path => page.evaluate(async path => (await import('/src/router/index.js')).default.push(path), path)
try {
  await page.goto(`${base}/admin/workbench-settings`)
  await switchControl(page).waitFor()
  assert.equal(await switchControl(page).locator('input').getAttribute('aria-checked'), 'true')
  const destination = 'https://glossary.example/info?source=chat&name='
  await linkInput(page).fill(destination)
  await switchControl(page).click()
  assert(await linkInput(page).isDisabled())
  await page.getByRole('button', { name: '保存草稿', exact: true }).click()
  await page.getByText('草稿已保存', { exact: true }).waitFor()
  assert.equal(draft.noun_highlight_enabled, false)
  await switchControl(page).click()
  await page.getByRole('button', { name: '保存并发布', exact: true }).click()
  await page.getByRole('dialog').getByRole('button', { name: '确定', exact: true }).click()
  await page.getByText('默认助手设置已发布', { exact: true }).waitFor()
  assert.equal(published.noun_explanation_url, destination)
  await page.reload()
  await linkInput(page).waitFor()
  assert.equal(await linkInput(page).inputValue(), destination)
  await mkdir('node_modules/.cache/noun-highlight', { recursive: true })
  await page.locator('.settings-section').first().screenshot({ path: 'node_modules/.cache/noun-highlight/settings.png' })

  await page.goto(`${base}/admin/chat?session=3`)
  const user = page.locator('.message-row.user').first()
  await links(user).first().waitFor()
  assert.equal(await links(user).count(), 3)
  const nounLink = new URL(await links(user).first().getAttribute('href'))
  assert.equal(nounLink.href, destination + encodeURIComponent('我方测算库龄'))
  assert.equal(nounLink.searchParams.get('source'), 'chat')
  assert.equal(nounLink.searchParams.get('name'), '我方测算库龄')
  assert.equal(nounLink.searchParams.get('none'), null)
  assert.equal(await links(user).first().locator('strong').textContent(), '我方测算库龄')
  const assistant = page.locator('.message-row.assistant').first()
  await links(assistant).first().waitFor()
  assert.equal(await links(assistant).count(), 2)
  assert.equal(await assistant.locator('code .noun-explanation-link, a a').count(), 0)
  assert.equal(await assistant.locator('a[href="https://existing.example/"]').textContent(), '我方测算库龄')

  // Partial and complete matches open the menu without selecting any option.
  const input = page.locator('.input-row .cm-content')
  const suggestions = page.getByRole('listbox', { name: '名词联想' })
  await input.fill('主体')
  await suggestions.waitFor()
  assert.equal(await suggestions.getByRole('option').textContent(), '主体业务')
  await page.keyboard.insertText('的')
  assert.equal(await input.textContent(), '主体的')
  assert.equal(await suggestions.count(), 0)
  await page.keyboard.press('Backspace')
  await suggestions.waitFor()
  assert.equal(await suggestions.getByRole('option', { selected: true }).count(), 0)
  await input.fill('主体的')
  assert.equal(await suggestions.count(), 0)
  await input.fill('库龄的')
  assert.equal(await suggestions.count(), 0)
  await input.fill('请解释库')
  await suggestions.waitFor()
  assert.equal(await suggestions.getByRole('option').count(), 1)
  assert.equal(await suggestions.getByRole('option', { selected: true }).count(), 0)
  await input.fill('请解释我方测算库')
  await suggestions.waitFor()
  assert.equal(await suggestions.getByRole('option').count(), 1)
  assert.equal(await suggestions.getByRole('option', { selected: true }).count(), 0)
  await input.fill('请解释库')
  await suggestions.waitFor()
  assert.equal(await suggestions.getByRole('option').count(), 1)
  assert.equal(await suggestions.getByRole('option', { selected: true }).count(), 0)
  assert.equal(await suggestions.locator('.active').count(), 0)
  assert.equal(await input.getAttribute('aria-activedescendant'), null)
  await suggestions.getByRole('option', { name: '库龄', exact: true }).click()
  assert.equal(await input.textContent(), '请解释库龄')
  assert.equal(await suggestions.count(), 0)
  assert.equal(await input.evaluate(el => el === document.activeElement), true)
  await input.fill('')
  await input.fill('请解释库')
  await suggestions.waitFor()
  await page.keyboard.press('ArrowDown')
  assert.equal(await suggestions.getByRole('option', { selected: true }).textContent(), '库龄')
  await page.keyboard.press('Enter')
  assert.equal(await input.textContent(), '请解释库龄')
  assert.equal(await suggestions.count(), 0)
  await input.fill('库龄')
  await suggestions.waitFor()
  await page.keyboard.press('ArrowUp')
  assert.equal(await suggestions.getByRole('option', { selected: true }).textContent(), '我方测算库龄')
  await page.keyboard.press('Tab')
  assert.equal(await input.textContent(), '我方测算库龄')
  assert.equal(await suggestions.count(), 0)
  await input.fill('库')
  await suggestions.waitFor()
  assert.equal(await suggestions.getByRole('option', { selected: true }).count(), 0)
  await page.keyboard.press('Tab')
  assert.equal(await input.textContent(), '库')
  assert.equal(await suggestions.count(), 0)
  assert.equal(await input.evaluate(el => el === document.activeElement), false)
  await input.fill('库龄')
  await suggestions.waitFor()
  await page.keyboard.press('Escape')
  assert.equal(await suggestions.count(), 0)
  await input.fill('没有匹配xyz')
  assert.equal(await suggestions.count(), 0)
  await input.fill('')
  assert.equal(await suggestions.count(), 0)
  await input.fill('@库')
  assert.equal(await suggestions.count(), 0)
  await page.getByRole('dialog', { name: '输入引用菜单' }).waitFor()
  await input.fill('/库')
  assert.equal(await suggestions.count(), 0)
  await input.fill('库龄')
  await suggestions.waitFor()
  await input.evaluate(el => el.dispatchEvent(new CompositionEvent('compositionstart', { bubbles: true })))
  assert.equal(await suggestions.count(), 0)
  assert.equal(await input.textContent(), '库龄')
  await input.evaluate(el => el.dispatchEvent(new CompositionEvent('compositionend', { bubbles: true, data: '库龄' })))
  await suggestions.waitFor()
  const cdp = await page.context().newCDPSession(page)
  await input.fill('')
  await cdp.send('Input.imeSetComposition', { text: '库', selectionStart: 1, selectionEnd: 1 })
  assert.equal(await suggestions.count(), 0)
  await cdp.send('Input.insertText', { text: '库' })
  await suggestions.waitFor()
  assert.equal(await input.textContent(), '库')
  assert.equal(await suggestions.getByRole('option', { selected: true }).count(), 0)
  await cdp.detach()
  // Completing a fragment at the caret preserves the rest of the message.
  await input.fill('请解释库，其他内容保留')
  await page.keyboard.press('Home')
  for (let i = 0; i < 4; i++) await page.keyboard.press('ArrowRight')
  await suggestions.getByRole('option', { name: '库龄', exact: true }).click()
  assert.equal(await input.textContent(), '请解释库龄，其他内容保留')
  await page.setViewportSize({ width: 390, height: 844 })
  await input.fill('库龄')
  await suggestions.waitFor()
  const menuBounds = await suggestions.boundingBox()
  assert(menuBounds.x >= 0 && menuBounds.x + menuBounds.width <= 390)
  await page.screenshot({ path: 'node_modules/.cache/noun-highlight/suggestions-mobile.png' })
  await page.setViewportSize({ width: 1440, height: 1080 })
  await page.screenshot({ path: 'node_modules/.cache/noun-highlight/suggestions-desktop.png' })
  assert.equal(nounRequests, 1)
  await input.fill(sentQuestion)
  await suggestions.waitFor()
  assert.equal(await suggestions.getByRole('option', { selected: true }).count(), 0)
  // An unselected menu must leave Enter's normal send behavior intact.
  await page.keyboard.press('Enter')
  const streaming = page.locator('.message-row.assistant').last()
  await streaming.getByText('请看我方测算', { exact: true }).waitFor()
  assert.equal(await links(streaming).count(), 0)
  await page.evaluate(() => window.appendNounStream([{ type: 'text', content: '库龄' }]))
  await links(streaming).first().waitFor()
  assert.equal(await links(streaming).first().textContent(), '我方测算库龄')
  await page.evaluate(() => window.appendNounStream([{ type: 'done' }], true))
  await page.getByRole('button', { name: '发送', exact: true }).waitFor()
  await page.locator('.messages').screenshot({ path: 'node_modules/.cache/noun-highlight/chat.png' })
  assert.equal(nounRequests, 1)

  await page.goto(`${base}/admin/agents/9`)
  const form = page.locator('.config-form')
  await switchControl(form).waitFor()
  assert.equal(await switchControl(form).locator('input').getAttribute('aria-checked'), 'true')
  await linkInput(form).fill('https://expert.example/glossary?mode=full&term=')
  await switchControl(form).click()
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await page.getByText('已保存', { exact: true }).waitFor()
  assert.equal(agent.noun_highlight_enabled, false)
  const beforeDisabled = nounRequests
  await navigate('/admin/agents/9/chat?session=3')
  await page.locator('.message-row.user').first().waitFor()
  assert.equal(await links(page.locator('.messages')).count(), 0)
  assert.equal(await page.locator('.message-row.user').first().innerText(), question)
  assert.equal(nounRequests, beforeDisabled)
  await page.locator('.input-row .cm-content').fill('库龄')
  assert.equal(await suggestions.count(), 0)
  await navigate('/admin/agents/9')
  await switchControl(form).click()
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await page.getByText('已保存', { exact: true }).waitFor()
  await navigate('/admin/agents/9/chat?session=3')
  await links(page.locator('.message-row.user').first()).first().waitFor()
  const expertLink = new URL(await links(page.locator('.message-row.user').first()).first().getAttribute('href'))
  assert.equal(expertLink.origin, 'https://expert.example')
  assert.equal(expertLink.searchParams.get('mode'), 'full')
  assert.equal(expertLink.href, agent.noun_explanation_url + encodeURIComponent('我方测算库龄'))
  assert.equal(expertLink.searchParams.get('term'), '我方测算库龄')
  assert.equal(expertLink.searchParams.get('none'), null)
  assert.equal(nounRequests, beforeDisabled)

  // Browser DOM checks cover escaping, idempotence and both Markdown renderers.
  const dom = await page.evaluate(async () => {
    const { createNounMatcher, highlightNouns } = await import('/src/utils/noun-highlight.js')
    const { renderMarkdown, renderStreamingMarkdown } = await import('/src/utils/markdown.js')
    const matcher = createNounMatcher(['<img onerror=alert(1)>', '我方测算库龄'])
    const html = highlightNouns(renderMarkdown('&lt;img onerror=alert(1)&gt; **我方测算库龄** `我方测算库龄`'), matcher)
    const host = document.createElement('div')
    host.innerHTML = html
    return { count: host.querySelectorAll('.noun-explanation-link').length,
      unsafe: host.querySelectorAll('img, [onerror], code a').length,
      stable: highlightNouns(html, matcher) === html,
      streaming: highlightNouns(renderStreamingMarkdown('我方测算库龄'), matcher).includes('noun-explanation-link') }
  })
  assert.deepEqual(dom, { count: 2, unsafe: 0, stable: true, streaming: true })
  failNouns = true
  agent.noun_highlight_enabled = true
  const failure = page.waitForResponse(response => response.url().endsWith('/noun-explanations/names') && response.status() === 503)
  await page.reload()
  await failure
  await page.locator('.message-row.user').first().waitFor()
  assert.equal(await links(page.locator('.messages')).count(), 0)
  assert.equal(await page.locator('.message-row.user').first().innerText(), question)
  await page.locator('.input-row .cm-content').fill('库龄')
  assert.equal(await suggestions.count(), 0)
  assert.deepEqual(errors, [])
  console.log('Passed: partial and complete noun matches, no default selection, explicit mouse/keyboard selection, normal Enter/Tab without selection, IME, reference menus, mobile layout, cache reuse, highlighting, disable switch and API failure.')
} finally {
  await browser.close()
}

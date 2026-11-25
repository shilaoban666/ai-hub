import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const baseURL = process.env.CHAT_TEST_URL || 'http://127.0.0.1:15173'
const output = path.resolve('../output/playwright/skill-conversation-examples')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
await context.addInitScript(() => localStorage.setItem('access_token', 'skill-examples-test-only'))
const page = await context.newPage()
const resourceLink = name => page.getByRole('navigation', { name: '资源与工具', exact: true }).getByRole('link', { name, exact: true })
const chooseResource = async name => {
  await resourceLink(name).click()
}
page.setDefaultTimeout(12000)
const errors = [], installs = [], updates = []
let failInstall = false, blockInstall = false, finishInstall
let messages = 0
const examples = ['xxx品销量怎么样？', '帮我查看本周任务']
const skill = {
  id: 20, user_id: 7, name: '业务查询技能', version: '1.0.0', author: '测试作者',
  description: '查询商品销量和本周任务。', is_public: true, conversation_examples: [],
  files: JSON.stringify({ tree: [{ id: 1, label: 'SKILL.md', path: 'SKILL.md', type: 'file', content: '# 业务查询' }] }),
}
const release = { id: 200, version: '1.0.0', installable: true, status: 'published' }
const installed = new Map()
const assistant = { id: 1, name: '默认助手', kind: 'personal_default', icon: 'H',
  runtime_type: 'claude_code', default_model_id: 1, models: [{ id: 1, name: '测试模型' }], skills: [] }
const expert = { ...assistant, id: 9, name: '业务智能体', kind: 'custom', can_edit: true }
page.on('pageerror', error => errors.push(error.message))
await page.route('**/*', async route => {
  const request = route.request(), url = new URL(request.url())
  if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
  let body = { items: [], total: 0 }
  if (url.pathname === '/iam/api/me') body = { id: 7, username: '测试用户', permissions: [] }
  else if (url.pathname.endsWith('/bootstrap')) body = { assistant_id: 1, assistant }
  else if (url.pathname.endsWith('/credits/me')) body = { claimed_today: true, available_balance: 100 }
  else if (url.pathname === '/aihub/api/agents/1') body = assistant
  else if (url.pathname === '/aihub/api/agents/9') body = { ...expert, skills: installed.has(9) ? [{ id: skill.id, name: skill.name }] : [] }
  else if (url.pathname === '/aihub/api/agents') body = { items: [expert], total: 1 }
  else if (url.pathname === '/aihub/api/skills/20') {
    if (request.method() === 'PUT') {
      updates.push(request.postDataJSON())
      Object.assign(skill, request.postDataJSON())
    }
    body = skill
  } else if (url.pathname === '/aihub/api/skills/20/releases') body = []
  else if (url.pathname.endsWith('/git/20/status')) body = { is_bound: false }
  else if (url.pathname === '/aihub/api/assets/skills/available') {
    body = { items: installed.has(0) ? [{ skill_id: skill.id, name: skill.name }] : [] }
  }
  else if (url.pathname === '/aihub/api/assets/skills/catalog') {
    const scope = Number(url.searchParams.get('agent_id') || 0)
    const installation = installed.get(scope) || null
    body = { total: 1, items: [{
      ...skill, skill_id: skill.id, latest_release: release, releases: [release],
      user_installation: installation, effective_release_id: installation?.release_id,
      is_mine: true, source: 'mine',
    }] }
  } else if (url.pathname === '/aihub/api/assets/skills/install') {
    installs.push(request.postDataJSON())
    if (blockInstall) await new Promise(resolve => { finishInstall = resolve })
    if (failInstall) return route.fulfill({ status: 422, json: { detail: '模拟安装失败' } })
    body = { id: 80, release_id: 200 }
    installed.set(Number(request.postDataJSON().agent_id || 0), body)
  } else if (/\/agents\/\d+\/messages$/.test(url.pathname)) {
    messages++
    return route.fulfill({ contentType: 'text/event-stream', body: 'data: {"type":"stream_end","status":"succeeded"}\n\n' })
  }
  return route.fulfill({ json: body })
})

const detail = page.getByRole('dialog', { name: '技能详情', exact: true })
const composer = page.locator('.workspace-chat .inline-composer .cm-content')
const openMarketDetail = async (agentId = 0) => {
  await page.goto(`${baseURL}/workspace/skills${agentId ? `?agent=${agentId}` : ''}`)
  await page.locator('.skill-card').first().click()
  await detail.waitFor()
}
const waitExample = async text => {
  await page.waitForURL(url => url.pathname === '/workspace/chat' && !url.searchParams.has('skillExample') && !url.searchParams.has('skillExampleId'))
  await page.waitForFunction(expected => {
    const element = document.querySelector('.workspace-chat .inline-composer .cm-content')?.cloneNode(true)
    element?.querySelectorAll('.composer-reference-prefix').forEach(item => item.remove())
    return element?.textContent === expected
  }, text)
  await composer.locator('.context-chip.skill .chip-label').getByText(skill.name, { exact: true }).waitFor()
}

try {
  // A skill with no configured examples adds no market module.
  await openMarketDetail()
  assert.equal(await detail.locator('.skill-examples').count(), 0)

  // Configure, cancel, save, reload, and remove examples through the actual editor.
  await page.goto(`${baseURL}/admin/skills/20`)
  const info = page.locator('.conversation-examples-info')
  await info.getByText('无', { exact: true }).waitFor()
  await info.getByRole('button', { name: '编辑', exact: true }).click()
  let editor = page.getByRole('dialog', { name: '编辑对话示例', exact: true })
  await editor.getByRole('textbox', { name: '对话示例 1', exact: true }).fill('不保存的示例')
  await editor.getByRole('button', { name: '取消', exact: true }).click()
  assert.equal(updates.length, 0)
  await info.getByRole('button', { name: '编辑', exact: true }).click()
  editor = page.getByRole('dialog', { name: '编辑对话示例', exact: true })
  await editor.getByRole('textbox', { name: '对话示例 1', exact: true }).fill(`  ${examples[0]}  `)
  await editor.getByRole('button', { name: '添加示例', exact: true }).click()
  await editor.getByRole('textbox', { name: '对话示例 2', exact: true }).fill(examples[1])
  await editor.getByRole('button', { name: '添加示例', exact: true }).click()
  await editor.getByRole('textbox', { name: '对话示例 3', exact: true }).fill('删除这一条')
  await editor.getByRole('button', { name: '删除对话示例 3', exact: true }).click()
  await editor.getByRole('button', { name: '保存', exact: true }).click()
  await editor.waitFor({ state: 'hidden' })
  assert.deepEqual(updates, [{ conversation_examples: examples }])
  await page.reload()
  await info.getByText(examples[0], { exact: true }).waitFor()

  await openMarketDetail()
  assert.deepEqual(await detail.locator('.skill-example span').allTextContents(), examples)
  assert.equal(await detail.locator('.skill-examples').evaluate(element =>
    element.getBoundingClientRect().bottom <= element.parentElement.querySelector('.detail-actions').getBoundingClientRect().top), true,
  'Examples appear above the version log and install actions')
  await page.screenshot({ path: path.join(output, 'market-examples.png'), animations: 'disabled' })
  blockInstall = true
  await detail.getByRole('button', { name: examples[0], exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.skill-example')?.disabled)
  assert.equal(new URL(page.url()).pathname, '/workspace/skills', 'Navigation waits for installation')
  assert.equal(installs.length, 1)
  finishInstall()
  blockInstall = false
  await waitExample(examples[0])
  assert.deepEqual(installs, [{ release_id: 200 }])
  assert.equal(messages, 0, 'Examples fill the composer without sending')
  await page.screenshot({ path: path.join(output, 'prefilled-chat.png'), animations: 'disabled' })

  // SPA navigation returns to the existing chat component and consumes each example once.
  await chooseResource('技能市场')
  await page.locator('.skill-card').first().click()
  await detail.getByRole('button', { name: examples[1], exact: true }).click()
  await waitExample(examples[1])
  assert.equal(installs.length, 1, 'An installed skill is reused')
  assert.equal(messages, 0, 'Returning from an example still waits for an explicit send')
  const personalRequest = page.waitForRequest(request => request.url().endsWith('/agents/1/messages') && request.method() === 'POST')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  const personalPayload = (await personalRequest).postDataJSON()
  assert.equal(personalPayload.skill_id, skill.id, 'The default assistant sends the selected skill reference')
  assert.equal(personalPayload.content, examples[1])
  await page.getByRole('button', { name: '发送', exact: true }).waitFor()
  await composer.fill('用户编辑后的草稿')
  await chooseResource('技能市场')
  await page.getByRole('button', { name: '新建对话', exact: true }).click()
  await page.waitForURL(url => url.pathname === '/workspace/chat')
  assert.notEqual(await composer.textContent(), examples[1], 'Returning cannot reapply the consumed example')

  // Failed installations stay in the market; agent installs keep their target scope.
  await openMarketDetail(9)
  failInstall = true
  await detail.getByRole('button', { name: examples[0], exact: true }).click()
  await page.getByText('模拟安装失败', { exact: true }).waitFor()
  assert.equal(new URL(page.url()).pathname, '/workspace/skills')
  await detail.waitFor()
  failInstall = false
  await detail.getByRole('button', { name: examples[1], exact: true }).click()
  await waitExample(examples[1])
  assert.equal(new URL(page.url()).searchParams.get('agent'), '9')
  assert.deepEqual(installs.at(-1), { release_id: 200, agent_id: 9 })
  assert.equal(messages, 1, 'The expert example also waits for an explicit send')
  const sentRequest = page.waitForRequest(request => request.url().endsWith('/agents/9/messages') && request.method() === 'POST')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  const payload = (await sentRequest).postDataJSON()
  assert.equal(payload.skill_id, skill.id, 'The actual message request uses the selected skill')
  assert.equal(payload.content, examples[1])

  await page.goto(`${baseURL}/admin/skills/20`)
  await info.getByRole('button', { name: '编辑', exact: true }).click()
  editor = page.getByRole('dialog', { name: '编辑对话示例', exact: true })
  await editor.getByRole('button', { name: '删除对话示例 2', exact: true }).click()
  await editor.getByRole('button', { name: '删除对话示例 1', exact: true }).click()
  await editor.getByRole('button', { name: '保存', exact: true }).click()
  await editor.waitFor({ state: 'hidden' })
  await info.getByText('无', { exact: true }).waitFor()
  await openMarketDetail()
  assert.equal(await detail.locator('.skill-examples').count(), 0)
  assert.deepEqual(errors, [])
  console.log('PASS: example editing, module order, install-before-navigation, skill reference chip, explicit send with skill_id, reuse, failure, agent scope, and clearing')
} finally {
  await browser.close()
}

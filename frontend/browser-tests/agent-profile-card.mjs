import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.AGENT_PROFILE_TEST_URL || 'http://localhost:15173'
const output = path.resolve('node_modules/.cache/agent-profile-card')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
page.setDefaultTimeout(10000)
const errors = [], mutations = []
const author = '负责企业业务与主体对象分析的智能体作者'.repeat(4)
const longName = '主体对象看板与业务数据分析智能体'.repeat(8)
const description = `完整业务说明：${'支持业务看板、数据分析和趋势解读，保留全部描述。'.repeat(24)}\n\nEnglishIdentifier${'UnbrokenName'.repeat(40)}\n说明结束。`
const skills = Array.from({ length: 18 }, (_, i) => ({ id: i + 1, name: i === 3 ? `跨系统长名称技能${'LongSkillIdentifier'.repeat(18)}` : `完整技能 ${i + 1}：主体对象数据分析及业务看板` }))
const model = { id: 1, name: '测试模型', api_protocol: 'anthropic-messages', scope: 'platform' }
const common = { kind: 'expert', runtime_type: 'claude_code', models: [model], default_model_id: 1, prompt_templates: [], mcp_connections: [] }
const mine = { ...common, id: 99, user_id: 7, name: longName, description, icon: '@cow', skills, is_public: true }
const shared = { ...common, id: 100, user_id: 8, name: '公开智能体', description: ' ', icon: '🚀', skills: [] }
const assistant = { ...common, id: 1, user_id: 7, kind: 'personal_default', name: '默认助手', description: '', icon: 'H', skills: [] }
await page.addInitScript(() => localStorage.setItem('access_token', 'agent-profile-test-only'))
page.on('pageerror', error => errors.push(error.message))
await page.route('**/*', async route => {
  const req = route.request(), url = new URL(req.url()), pathname = url.pathname
  if (!/^\/(aihub|iam)\/api\//.test(pathname)) return route.continue()
  if (req.method() !== 'GET' && !pathname.endsWith('/bootstrap') && !pathname.endsWith('/skills/sync')) mutations.push(pathname)
  let body = { items: [], total: 0 }
  if (pathname === '/iam/api/me') body = { id: 7, username: 'tester', first_name: author, permissions: [] }
  else if (pathname === '/iam/api/users/') body = { items: [{ id: 8, first_name: '公开作者完整名称' }], total: 1 }
  else if (pathname.endsWith('/bootstrap')) body = { assistant_id: 1, assistant }
  else if (pathname.endsWith('/credits/me')) body = { claimed_today: true, available_balance: 100, display_name: '积分' }
  else if (pathname === '/aihub/api/agents') body = { items: [mine], total: 1 }
  else if (pathname === '/aihub/api/public/agents') body = { items: [shared], total: 1 }
  else if (/\/agents\/\d+$/.test(pathname)) body = [mine, shared, assistant].find(agent => agent.id === Number(pathname.split('/').at(-1)))
  else if (pathname.endsWith('/models')) body = { items: [model], total: 1 }
  else if (pathname.endsWith('/runtime-status')) body = { status: 'ready', runtime_type: 'claude_code' }
  else if (pathname.endsWith('/skills/sync')) body = { status: 'synced' }
  else if (pathname.endsWith('/files')) body = { files: [] }
  await route.fulfill({ json: body })
})
const heading = page.locator('.workspace-heading')
const trigger = heading.locator('.agent-switcher-row')
const popover = page.locator('.agent-profile-popover:visible')
const card = popover.getByRole('article', { name: '智能体名片' })
const closeProfile = async () => {
  await page.mouse.move(1400, 900)
  await page.locator('.workspace-content').click({ position: { x: 600, y: 20 } })
  await popover.waitFor({ state: 'hidden' })
}
const noClipping = async () => {
  assert(await card.evaluate(el => el.scrollWidth <= el.clientWidth), 'The profile must wrap long text without horizontal overflow')
  assert(await popover.evaluate(el => {
    const rect = el.getBoundingClientRect()
    return rect.left >= 0 && rect.right <= innerWidth && rect.top >= 0 && rect.bottom <= innerHeight
  }), 'The profile must fit the viewport')
  for (const selector of ['.profile-name', '.profile-author', '.profile-description', '.profile-skill']) {
    assert(await card.locator(selector).evaluateAll(elements => elements.every(el => {
      const style = getComputedStyle(el)
      return style.webkitLineClamp === 'none' && style.textOverflow !== 'ellipsis' && el.scrollHeight <= el.clientHeight + 1 && el.scrollWidth <= el.clientWidth + 1
    })), `${selector} must display its complete content`)
  }
}
try {
  await page.goto(`${base}/workspace/chat?agent=99`)
  await trigger.waitFor()
  assert.equal(await heading.locator('.agent-switcher-name').textContent(), longName)
  assert.equal(await heading.locator('.agent-switcher-name').evaluate(el => getComputedStyle(el).textOverflow), 'ellipsis')
  const summon = heading.getByRole('button', { name: '召唤智能体', exact: true })
  const summonBounds = await summon.boundingBox()
  await trigger.hover()
  await card.waitFor()
  assert.equal(await card.locator('.profile-name').textContent(), longName)
  assert.equal(await card.locator('.profile-author').textContent(), author)
  assert.equal(await card.locator('.profile-description').textContent(), description)
  assert.deepEqual(await card.locator('.profile-skill').allTextContents(), skills.map(skill => skill.name))
  assert.deepEqual(await card.locator('.profile-origin').allTextContents(), ['我的', '公开'])
  await noClipping()
  assert.deepEqual(await summon.boundingBox(), summonBounds)
  await card.hover({ position: { x: 50, y: 50 } })
  await page.waitForTimeout(400)
  assert(await card.isVisible(), 'Moving into the card must keep it open')
  await card.locator('.profile-description').evaluate(el => getSelection().selectAllChildren(el))
  assert.equal(await page.evaluate(() => getSelection().toString()), description)
  await page.evaluate(() => getSelection().removeAllRanges())
  await popover.screenshot({ path: path.join(output, 'long-profile-top.png'), animations: 'disabled' })
  await card.evaluate(el => { el.scrollTop = el.scrollHeight })
  assert(await card.evaluate(el => el.scrollTop > 0), 'Long profiles must scroll to all skills')
  await popover.screenshot({ path: path.join(output, 'long-profile-skills.png'), animations: 'disabled' })
  await closeProfile()
  await trigger.focus()
  await page.keyboard.press('Enter')
  await page.getByRole('listbox', { name: '选择智能体' }).waitFor()
  await page.getByRole('button', { name: '查看当前智能体名片' }).click()
  await card.waitFor()
  await card.focus()
  await page.waitForTimeout(300)
  assert(await card.isVisible(), 'Moving keyboard focus into the card must keep it open')
  await page.keyboard.press('Escape')
  await popover.waitFor({ state: 'hidden' })
  await trigger.click()
  await popover.waitFor({ state: 'hidden' })
  await page.locator('.agent-switcher-popover:visible').getByRole('option', { name: '公开智能体', exact: true }).click()
  await page.waitForURL(`${base}/workspace/chat?agent=100`)
  await trigger.hover()
  await card.waitFor()
  assert.equal(await card.locator('.profile-author').textContent(), '公开作者完整名称')
  assert.equal(await card.locator('.profile-description').textContent(), '无')
  assert.equal(await card.locator('.profile-skills').textContent(), '无')
  assert.deepEqual(await card.locator('.profile-origin').allTextContents(), ['公开'])
  await closeProfile()
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: '打开工作台导航', exact: true }).click()
  await trigger.click()
  await page.getByRole('button', { name: '查看当前智能体名片' }).click()
  await card.waitFor()
  await noClipping()
  await popover.screenshot({ path: path.join(output, 'mobile-profile.png'), animations: 'disabled' })
  await page.keyboard.press('Escape')
  await popover.waitFor({ state: 'hidden' })
  await page.setViewportSize({ width: 1440, height: 960 })
  await page.goto(`${base}/workspace/chat`)
  await trigger.hover()
  await card.waitFor()
  assert.equal(await card.locator('.profile-author').textContent(), '平台')
  assert.deepEqual(await card.locator('.profile-origin').allTextContents(), ['默认'])
  assert.deepEqual(mutations, [], 'Inspecting profiles must not mutate an agent')
  assert.deepEqual(errors, [])
  console.log('Passed: compact heading; full-row switch; complete long profiles; wrapping and scrolling; hover, keyboard and mobile profile access; public and default metadata; no mutations or browser errors.')
  console.log(output)
} finally { await browser.close() }

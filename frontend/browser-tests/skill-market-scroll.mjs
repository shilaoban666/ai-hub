import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const baseURL = process.env.CHAT_TEST_URL || 'http://127.0.0.1:15173'
const output = path.resolve('output/playwright/skill-market-scroll')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
await context.addInitScript(() => localStorage.setItem('access_token', 'skill-market-test-only'))
const page = await context.newPage()
page.setDefaultTimeout(12000)
const errors = [], requests = []
let failNext = false, holdNext = false, pendingBatch = null
const skills = Array.from({ length: 38 }, (_, index) => {
  const id = index + 1
  const release = { id: id * 10, version: '1.0.0', installable: true, status: 'published' }
  return {
    skill_id: id, name: id === 38 ? '检索技能' : `测试技能 ${id}`, author: '测试作者',
    description: '用于验证技能市场滚动加载和筛选的技能。',
    module: id % 2 ? '订单' : '物流', roles: id % 2 ? '采购' : '运营',
    is_mine: id <= 22, is_public: true, latest_release: release, releases: [release],
    user_installation: id <= 2 ? { id, release_id: release.id } : null,
  }
})
const assistant = { id: 1, name: '默认助手', kind: 'personal_default', icon: 'H',
  runtime_type: 'claude_code', models: [], skills: [], prompt_templates: [], mcps: [] }
page.on('pageerror', error => errors.push(error.message))
await page.route('**/*', async route => {
  const request = route.request(), url = new URL(request.url())
  if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
  let body = { items: [], total: 0 }
  if (url.pathname === '/iam/api/me') body = { id: 7, username: '测试用户', permissions: [] }
  else if (url.pathname.endsWith('/bootstrap')) body = { assistant_id: 1, assistant }
  else if (url.pathname.endsWith('/credits/me')) body = { claimed_today: true, available_balance: 100 }
  else if (url.pathname === '/aihub/api/agents/1') body = assistant
  else if (url.pathname.endsWith('/metadata-options')) body = { modules: ['订单', '物流'], roles: ['采购', '运营'] }
  else if (url.pathname.match(/\/assets\/skills\/releases\/\d+\/files$/)) {
    body = { files: [{ id: 'skill-md', label: 'SKILL.md', path: 'SKILL.md', type: 'file', content: '# 测试技能' }] }
  }
  else if (url.pathname === '/aihub/api/assets/skills/catalog') {
    const params = Object.fromEntries(url.searchParams)
    requests.push(params)
    if (failNext) {
      failNext = false
      return route.fulfill({ status: 503, json: { detail: '模拟加载失败' } })
    }
    let items = skills.filter(skill => (!params.q || skill.name.includes(params.q))
      && (params.source !== 'mine' || skill.is_mine)
      && (params.source !== 'collaboration')
      && (!params.module || skill.module === params.module)
      && (!params.role || skill.roles === params.role)
      && (params.installed_only !== 'true' || skill.user_installation))
    body = structuredClone({ total: items.length, items: items.slice(Number(params.skip), Number(params.skip) + Number(params.limit)) })
    if (holdNext) {
      holdNext = false
      await new Promise(resolve => { pendingBatch = resolve })
      pendingBatch = null
    }
  } else if (url.pathname === '/aihub/api/assets/skills/install') {
    const skill = skills.find(item => item.latest_release.id === request.postDataJSON().release_id)
    skill.user_installation = { id: skill.skill_id, release_id: skill.latest_release.id }
    body = skill.user_installation
  } else if (/\/assets\/skills\/installations\/\d+$/.test(url.pathname) && request.method() === 'DELETE') {
    skills.find(item => item.skill_id === Number(url.pathname.split('/').at(-1))).user_installation = null
  }
  await route.fulfill({ json: body })
})

const waitCount = count => page.waitForFunction(expected =>
  document.querySelectorAll('.skill-library .skill-card').length === expected, count)
const waitIdle = () => page.locator('.library-load-more[aria-busy="false"]').waitFor()
const bottom = () => page.locator('.workspace-resource').evaluate(element => { element.scrollTop = element.scrollHeight })
const search = async value => {
  const input = page.getByPlaceholder('搜索技能、作者或说明')
  await input.fill(value)
  await input.press('Enter')
}
const sourceGroup = page.getByRole('group', { name: '技能来源', exact: true })
const viewGroup = page.getByRole('group', { name: '技能范围', exact: true })

try {
  await page.goto(`${baseURL}/admin/workspace/skills`)
  await waitCount(16)
  await waitIdle()
  assert.equal(await page.locator('.skill-library .el-pagination').count(), 0)
  assert.equal(await page.getByText('业务模块', { exact: true }).count(), 0)
  assert.equal(await page.getByText('适用角色', { exact: true }).count(), 0)
  await page.locator('.skill-card').first().click()
  const detailDialog = page.getByRole('dialog', { name: '技能详情', exact: true })
  await detailDialog.waitFor()
  await detailDialog.getByText('测试技能 1', { exact: true }).waitFor()
  await detailDialog.getByText('测试作者 · 1.0.0', { exact: true }).waitFor()
  await detailDialog.getByRole('button', { name: '查看版本日志', exact: true }).waitFor()
  await detailDialog.getByRole('button', { name: '卸载', exact: true }).waitFor()
  assert.equal(await detailDialog.locator('h2').evaluate(element => getComputedStyle(element).fontSize), '18px')
  await detailDialog.getByRole('button', { name: '查看版本日志', exact: true }).click()
  const notesDialog = page.getByRole('dialog', { name: '版本日志', exact: true })
  await notesDialog.waitFor()
  await notesDialog.getByRole('button', { name: '下载', exact: true }).waitFor()
  await notesDialog.getByRole('button', { name: '文件', exact: true }).click()
  await page.locator('.skill-files-dialog').getByLabel('文件列表').getByText('SKILL.md', { exact: true }).waitFor()
  assert.equal(await page.locator('.el-popover:visible').count(), 0, 'Closing detail clears its popovers')
  await page.locator('.skill-files-dialog .el-dialog__headerbtn').click()
  await notesDialog.locator('.el-dialog__headerbtn').click()
  await detailDialog.locator('.el-dialog__headerbtn').click()
  assert.deepEqual(requests.map(item => [item.skip, item.limit]), [['0', '16']])
  failNext = true
  await bottom()
  await page.getByText('加载更多失败', { exact: true }).waitFor()
  await waitCount(16)
  const failedRequests = requests.length
  await page.waitForTimeout(250)
  assert.equal(requests.length, failedRequests, 'Failed batches wait for a deliberate retry')

  holdNext = true
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await page.waitForFunction(() => document.querySelector('.library-load-more')?.getAttribute('aria-busy') === 'true')
  assert(pendingBatch, 'The retry request is pending')
  await bottom()
  await page.waitForTimeout(150)
  assert.equal(requests.length, failedRequests + 1, 'Only one request runs while appending')
  pendingBatch()
  await waitCount(32)
  await waitIdle()
  assert.equal(await page.locator('.skill-card h3').first().innerText(), '测试技能 1')
  await bottom()
  await waitCount(38)
  await waitIdle()
  await bottom()
  await page.waitForTimeout(150)
  assert.deepEqual(requests.map(item => item.skip), ['0', '16', '16', '32'])
  assert.equal(new Set(await page.locator('.skill-card h3').allTextContents()).size, 38)
  await page.screenshot({ path: path.join(output, 'all-loaded.png'), animations: 'disabled' })

  await page.locator('.skill-card').last().getByRole('button', { name: '安装', exact: true }).click()
  await page.locator('.skill-card').last().getByRole('button', { name: '卸载', exact: true }).waitFor()
  await waitIdle()
  await waitCount(38)
  assert.equal(requests.at(-1).skip, '0')
  assert.equal(requests.at(-1).limit, '38', 'Installing refreshes the already loaded range')
  await viewGroup.getByRole('button', { name: '已安装', exact: true }).click()
  await waitCount(3)
  assert.equal(requests.at(-1).skip, '0')
  const installedLast = page.locator('.skill-card').last()
  await installedLast.getByRole('button', { name: '卸载', exact: true }).click()
  await page.getByRole('dialog', { name: '卸载技能', exact: true }).getByRole('button', { name: '卸载', exact: true }).click()
  await waitCount(2)
  await waitIdle()
  await viewGroup.getByRole('button', { name: '全部', exact: true }).click()
  await waitCount(16)
  await sourceGroup.getByRole('button', { name: '我的', exact: true }).click()
  await waitCount(16)
  await waitIdle()
  assert.equal(requests.at(-1).source, 'mine')
  assert.equal(requests.at(-1).skip, '0')
  await sourceGroup.getByRole('button', { name: '协作', exact: true }).click()
  await page.getByText('没有符合条件的技能', { exact: true }).waitFor()
  await waitCount(0)
  await page.waitForTimeout(150)
  assert.equal(requests.at(-1).skip, '0')

  await page.reload()
  await waitCount(16)
  await waitIdle()
  holdNext = true
  await bottom()
  await page.waitForFunction(() => document.querySelector('.library-load-more')?.getAttribute('aria-busy') === 'true')
  assert(pendingBatch)
  const releaseOldBatch = pendingBatch
  await search('检索')
  await waitCount(1)
  releaseOldBatch()
  await page.waitForTimeout(200)
  await waitCount(1)
  assert.equal(await page.locator('.skill-card h3').innerText(), '检索技能', 'Old batches must not enter new search results')
  assert.equal(requests.at(-1).q, '检索')
  assert.equal(requests.at(-1).skip, '0')

  failNext = true
  await search('测试')
  await page.getByText('技能目录加载失败', { exact: true }).waitFor()
  await waitCount(0)
  assert.equal(await page.getByText('没有符合条件的技能', { exact: true }).count(), 0)
  await page.getByRole('button', { name: '重试', exact: true }).click()
  await waitCount(16)
  assert.equal(requests.at(-1).q, '测试')
  assert.equal(requests.at(-1).skip, '0')

  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await waitCount(16)
  await waitIdle()
  await bottom()
  await waitCount(32)
  await waitIdle()
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)
  await page.screenshot({ path: path.join(output, 'mobile-append.png'), animations: 'disabled' })

  await page.setViewportSize({ width: 2400, height: 4200 })
  await page.reload()
  await waitCount(38)
  await waitIdle()
  assert.deepEqual(errors, [])
  console.log('PASS: append, duplicate request guard, exhaustion, retry, detail/files dialogs, stale responses, install/uninstall refresh, mobile and tall viewport')
} finally {
  pendingBatch?.()
  await browser.close()
}

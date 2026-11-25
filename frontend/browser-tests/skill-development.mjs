import assert from 'node:assert/strict'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
await context.addInitScript(() => localStorage.setItem('access_token', 'skill-development-test-only'))
const page = await context.newPage()
page.setDefaultTimeout(10000)
const errors = [], updates = [], previews = [], catalogScopes = []
let enabled = false, isOwner = true, failUpdate = false, unpublished = false, workspaceInstalled = false, installs = []
const release = { id: 200, version: '1.0.0', installable: true, status: 'published' }
const workspaceRelease = { id: 201, version: 'latest', installable: true, status: 'workspace' }
const assistant = { id: 1, name: '默认助手', kind: 'personal_default', models: [], skills: [] }
page.on('pageerror', error => errors.push(error.message))
await page.route('**/*', async route => {
  const request = route.request(), url = new URL(request.url())
  if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
  let body = { items: [], total: 0 }
  if (url.pathname === '/iam/api/me') body = { id: 7, username: '测试作者', permissions: [] }
  else if (url.pathname.endsWith('/bootstrap')) body = { assistant_id: 1, assistant }
  else if (url.pathname === '/aihub/api/agents/1') body = assistant
  else if (url.pathname === '/aihub/api/agents/99') body = { ...assistant, id: 99, name: '自定义智能体', kind: 'expert', user_id: 7, can_edit: true }
  else if (url.pathname.endsWith('/credits/me')) body = { claimed_today: true, available_balance: 100 }
  else if (url.pathname === '/aihub/api/assets/skills/catalog') {
    catalogScopes.push(url.searchParams.get('agent_id'))
    const installedReleaseId = enabled ? workspaceRelease.id : (unpublished ? null : release.id)
    const catalogReleases = [...(unpublished ? [] : [release]), ...(workspaceInstalled ? [workspaceRelease] : [])]
    body = { total: 1, items: [{
      skill_id: 20, name: '开发验证技能', author: '测试作者', description: '检查工作区最新文件。',
      is_mine: isOwner, source: isOwner ? 'mine' : 'enterprise',
      ...(isOwner ? { development_mode: enabled } : {}),
      latest_release: unpublished ? null : release, releases: catalogReleases,
      latest_workspace: isOwner ? { id: workspaceInstalled ? 201 : null, version: 'latest', installable: true, status: 'workspace' } : null,
      user_installation: installedReleaseId ? { id: 80, release_id: installedReleaseId } : null,
      effective_release_id: installedReleaseId,
    }] }
  } else if (url.pathname === '/aihub/api/assets/skills/20/development') {
    updates.push(request.postDataJSON())
    if (failUpdate) return route.fulfill({ status: 409, json: { detail: '技能工作区文件不可用' } })
    enabled = request.postDataJSON().enabled
    workspaceInstalled ||= enabled
    body = { skill_id: 20, development_mode: enabled }
  } else if (url.pathname === '/aihub/api/assets/skills/install') {
    const payload = request.postDataJSON()
    installs.push(payload)
    workspaceInstalled = true
    enabled = true
    body = { id: 81, skill_id: 20, release_id: 201, version: 'latest', status: 'active' }
  } else if (url.pathname.endsWith('/development/files') || url.pathname.endsWith('/releases/200/files')) {
    previews.push(url.pathname)
    body = { files: [{ id: 1, label: 'SKILL.md', path: 'SKILL.md', type: 'file',
      content: url.pathname.endsWith('/development/files') ? '# 工作区最新内容' : '# 已发布内容' }] }
  }
  return route.fulfill({ json: body })
})

const openCatalog = async (agentId = null) => {
  await page.goto(`${process.env.CHAT_TEST_URL || 'http://127.0.0.1:15173'}/admin/workspace/skills${agentId ? `?agent=${agentId}` : ''}`)
  await page.locator('.skill-card').first().waitFor()
}
const detail = page.getByRole('dialog', { name: '技能详情', exact: true })
const card = page.locator('.skill-card').first()
const toggle = card.getByRole('switch', { name: '调试模式', exact: true })
const toggleControl = card.locator('.skill-card__development .el-switch')
try {
  await openCatalog()
  await toggleControl.waitFor()
  assert.equal(await toggle.getAttribute('aria-checked'), 'false')
  await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === '/aihub/api/assets/skills/catalog'),
    toggleControl.click(),
  ])
  await page.waitForFunction(() => document.querySelector('.skill-card [role="switch"]')?.getAttribute('aria-checked') === 'true')
  assert.equal(await detail.count(), 0, 'Toggling on the card must not open details')
  assert.deepEqual(updates, [{ enabled: true }])
  await openCatalog()
  assert.equal(await toggle.getAttribute('aria-checked'), 'true')
  await card.click()
  assert.equal(await detail.getByRole('switch', { name: '调试模式', exact: true }).count(), 1)
  assert.equal(await detail.getByRole('switch', { name: '调试模式', exact: true }).getAttribute('aria-checked'), 'true')
  assert.equal((await detail.locator('.detail-author').textContent()).trim(), '测试作者 · 1.0.0')
  await detail.getByRole('button', { name: '技能文件', exact: true }).click()
  await page.getByText('工作区最新内容', { exact: true }).waitFor()
  assert.equal(previews.at(-1), '/aihub/api/assets/skills/20/development/files')
  await openCatalog()
  await card.click()
  await Promise.all([
    page.waitForResponse(response => new URL(response.url()).pathname === '/aihub/api/assets/skills/catalog'),
    detail.locator('.skill-development-detail .el-switch').click(),
  ])
  await page.waitForFunction(() => document.querySelector('.skill-card [role="switch"]')?.getAttribute('aria-checked') === 'false')
  assert.equal(enabled, false)
  assert.equal(await card.getByRole('button', { name: '升级', exact: true }).count(), 0, 'Disabling debug must refresh the installed version')
  assert.equal(await detail.getByRole('button', { name: '升级', exact: true }).count(), 0)
  assert.equal(await detail.getByRole('switch', { name: '调试模式', exact: true }).getAttribute('aria-checked'), 'false')
  await openCatalog()
  failUpdate = true
  await toggleControl.click()
  await page.getByText('技能工作区文件不可用', { exact: true }).waitFor()
  assert.equal(await toggle.getAttribute('aria-checked'), 'false')
  failUpdate = false
  unpublished = true
  workspaceInstalled = false
  await openCatalog()
  assert.match(await card.textContent(), /无/)
  assert.equal(await card.getByRole('button', { name: '安装', exact: true }).count(), 1)
  await card.getByRole('button', { name: '安装', exact: true }).click()
  await page.getByRole('button', { name: '卸载', exact: true }).waitFor()
  assert.match(await card.textContent(), /无/)
  assert.deepEqual(installs.at(-1), { skill_id: 20 })
  await toggleControl.click()
  await page.waitForFunction(() => document.querySelector('.skill-card [role="switch"]')?.getAttribute('aria-checked') === 'true')
  isOwner = false
  await openCatalog()
  assert.equal(await toggle.count(), 0)
  await card.click()
  assert.equal(await detail.locator('.skill-development-detail').count(), 0)
  isOwner = true
  enabled = false
  workspaceInstalled = false
  await openCatalog(99)
  assert.equal(catalogScopes.at(-1), '99')
  await card.getByRole('button', { name: '安装', exact: true }).click()
  await card.getByRole('button', { name: '卸载', exact: true }).waitFor()
  assert.deepEqual(installs.at(-1), { skill_id: 20, agent_id: 99 })
  assert.equal(await toggle.getAttribute('aria-checked'), 'true')
  assert.equal(await toggle.isDisabled(), true, 'Unreleased skills must keep debug mode enabled')
  await openCatalog(99)
  await card.getByRole('button', { name: '卸载', exact: true }).waitFor()
  await card.getByRole('button', { name: '技能文件', exact: true }).click()
  await page.getByText('工作区最新内容', { exact: true }).waitFor()
  assert.equal(previews.at(-1), '/aihub/api/assets/skills/20/development/files')
  assert.deepEqual(errors, [])
  console.log('PASS: card/detail switches, owner-only controls, unpublished skills in default/custom agents, workspace preview, and failed update rollback')
} finally {
  await browser.close()
}

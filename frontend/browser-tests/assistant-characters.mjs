import assert from 'node:assert/strict'
import { readFile, mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.EMBED_TEST_URL || 'http://localhost:15176'
const source = await readFile('public/embed/assistant.js', 'utf8')
const cow = await readFile('public/characters/cow-v1.svg', 'utf8')
const sprout = await readFile('public/characters/sprout-v1.svg', 'utf8')
const browser = await chromium.launch({ channel: 'msedge', headless: true })
try {
  const page = await browser.newPage({ viewport: { width: 1300, height: 1050 } })
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  let published = { version: 7, assistant_name: '小趣', assistant_icon: 'H', assistant_mascot: '@cow', default_model_id: 1, initial_claim_amount: 10, daily_claim_amount: 10, per_run_limit: 5 }
  let uploadCount = 0
  let appearanceCalls = 0
  let appearanceFailure = false
  await page.addInitScript(() => localStorage.setItem('access_token', 'browser-test-only'))
  await page.route('**/*', route => {
    const url = new URL(route.request().url())
    if (url.pathname === '/embed/assistant.js') return route.fulfill({ contentType: 'text/javascript; charset=utf-8', body: source })
    if (url.pathname === '/character-host') return route.fulfill({ contentType: 'text/html; charset=utf-8', body: '<!doctype html><body style="background:white"><script src="/embed/assistant.js"></script></body>' })
    if (url.pathname.startsWith('/uploads/images/')) return route.fulfill({ contentType: 'image/svg+xml', body: cow })
    if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
    let body = { items: [], total: 0 }
    if (url.pathname === '/iam/api/me') body = { id: 7, username: 'test', is_superuser: true, permissions: [] }
    if (url.pathname.endsWith('/admin/platform-models')) body = { items: [{ id: 1, name: '测试模型', is_enabled: true, has_api_key: true, api_protocol: 'anthropic-messages' }] }
    if (url.pathname.endsWith('/admin/workbench-settings/publish')) {
      published = { ...route.request().postDataJSON(), version: published.version + 1 }
      body = published
    }
    if (url.pathname.endsWith('/admin/workbench-settings')) body = { published, draft: null }
    if (url.pathname.endsWith('/upload/image')) {
      assert.equal(url.searchParams.get('purpose'), 'assistant')
      uploadCount++; body = { url: `/uploads/images/upload_${uploadCount}.svg` }
    }
    if (url.pathname.endsWith('/public/assistant-appearance')) {
      appearanceCalls++
      assert.equal(route.request().headers().authorization, undefined)
      if (appearanceFailure) return route.fulfill({ status: 503, body: '{}' })
      // Exercise the real gateway envelope as well as direct backend JSON.
      body = { mascot: published.assistant_mascot }
      if (published.assistant_mascot !== '@cow') body = { code: 200, message: 'ok', data: body }
    }
    return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
  })
  await page.goto(`${base}/admin/workbench-settings`)
  await page.getByRole('button', { name: '更换头像', exact: true }).click()
  const picker = page.locator('.character-picker')
  const chatPicker = picker.nth(0)
  const mascotPicker = picker.nth(1)
  await chatPicker.getByRole('button', { name: '小牛', exact: true }).click()
  await mascotPicker.getByRole('button', { name: '小树苗', exact: true }).click()
  assert.equal(await chatPicker.getByRole('button', { name: '小牛', exact: true }).getAttribute('aria-pressed'), 'true')
  assert.equal(await mascotPicker.getByRole('button', { name: '文字 / Emoji' }).count(), 0)
  await picker.locator('img').evaluateAll(images => Promise.all(images.map(image => image.decode())))
  const publish = async () => {
    await page.getByRole('button', { name: '保存并发布', exact: true }).click()
    await page.getByRole('button', { name: '确定', exact: true }).click()
    await page.getByText('默认助手设置已发布', { exact: true }).waitFor()
    await page.reload()
    await page.getByRole('button', { name: '更换头像', exact: true }).click()
    await picker.first().waitFor()
  }
  await publish()
  assert.equal(published.assistant_icon, '@cow')
  assert.equal(published.assistant_mascot, '@sprout')
  await mkdir('node_modules/.cache/assistant-characters', { recursive: true })
  await page.locator('.settings-form .settings-section').first().screenshot({ path: 'node_modules/.cache/assistant-characters/settings.png' })
  await chatPicker.locator('input[type=file]').setInputFiles({ name: 'avatar.svg', mimeType: 'image/svg+xml', buffer: Buffer.from(cow) })
  await chatPicker.getByRole('button', { name: '上传图片' }).locator('img').waitFor()
  await mascotPicker.locator('input[type=file]').setInputFiles({ name: 'mascot.svg', mimeType: 'image/svg+xml', buffer: Buffer.from(sprout) })
  await mascotPicker.getByRole('button', { name: '上传图片' }).locator('img').waitFor()
  await publish()
  assert.equal(published.assistant_icon, '/uploads/images/upload_1.svg')
  assert.equal(published.assistant_mascot, '/uploads/images/upload_2.svg')
  assert.equal(await picker.locator('button.selected img').count(), 2)
  await chatPicker.locator('input[type=file]').setInputFiles({ name: 'large.png', mimeType: 'image/png', buffer: Buffer.alloc(200 * 1024 + 1) })
  await page.getByText('图片不能超过 200KB，请压缩后再上传', { exact: true }).waitFor()
  assert.equal(uploadCount, 2)
  await chatPicker.getByRole('button', { name: '文字 / Emoji' }).click()
  await chatPicker.getByPlaceholder('输入字母、文字或 emoji').fill('趣')
  await publish()
  assert.equal(published.assistant_icon, '趣')
  assert.equal(published.assistant_mascot, '/uploads/images/upload_2.svg')
  for (const value of ['@sprout', '@cow', '/uploads/images/upload_2.svg']) {
    published.assistant_mascot = value
    const before = appearanceCalls
    await page.goto(`${base}/character-host`)
    const launcher = page.getByRole('button', { name: '打开 AI 助手', exact: true })
    if (value === '@sprout') await launcher.locator('.antenna').waitFor()
    else if (value === '@cow') await launcher.locator('.head').waitFor()
    else await launcher.locator('img').evaluate(el => el.decode())
    await launcher.hover()
    if (value === '@sprout') assert.notEqual(await launcher.locator('.hand').evaluate(el => getComputedStyle(el).animationName), 'none')
    await page.waitForTimeout(100)
    assert.equal(appearanceCalls, before + 1)
    assert.deepEqual(await launcher.evaluate(el => [el.offsetWidth, el.offsetHeight]), [60, 60])
  }
  appearanceFailure = true
  await page.goto(`${base}/character-host`)
  await page.getByRole('button', { name: '打开 AI 助手', exact: true }).locator('.head').waitFor()
  assert.deepEqual(errors, [])
  console.log('Passed: independent characters, uploads, persistence, legacy text, oversize validation, both animated mascots, uploaded mascot and service fallback.')
} finally { await browser.close() }

import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.USAGE_TEST_URL || 'http://localhost:15173'
const output = path.resolve('node_modules/.cache/user-management-browser')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'msedge', headless: true })
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } })
await context.addInitScript(() => localStorage.setItem('access_token', 'browser-test-only'))
const page = await context.newPage()
const errors = []
const requests = []
let failUsers = false
page.on('pageerror', error => errors.push(error.message))
const users = Array.from({ length: 25 }, (_, index) => ({
  id: index + 1, username: `user${index + 1}`, email: index ? '' : '   ',
  first_name: `Employee ${index + 1}`, is_superuser: index % 2 === 0,
  departments: index === 0 ? [] : index % 2 === 0 ? ['Sales', 'Support'] : ['Sales'],
  roles: index ? [] : ['Administrator'],
}))
users.at(-1).username = 'long-account-'.repeat(20)
await page.route('**/*', async route => {
  const url = new URL(route.request().url())
  if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) {
    return route.fulfill({ response: await route.fetch() })
  }
  let body = { items: [], total: 0 }
  if (url.pathname === '/iam/api/me') body = { id: 7, username: 'admin', is_superuser: true, permissions: [] }
  if (url.pathname === '/aihub/api/admin/user-management/') {
    requests.push(url)
    if (failUsers) return route.fulfill({ status: 400, json: { detail: 'User directory unavailable' } })
    const selected = users.filter(user =>
      (!url.searchParams.has('department') || user.departments.includes(url.searchParams.get('department'))) &&
      (!url.searchParams.has('is_superuser') || user.is_superuser === (url.searchParams.get('is_superuser') === 'true')) &&
      (!url.searchParams.has('user_id') || user.id === Number(url.searchParams.get('user_id'))))
    const skip = Number(url.searchParams.get('skip') || 0)
    body = { total: selected.length, items: selected.slice(skip, skip + 20),
      department_options: ['Sales', 'Support'],
      user_options: users.map(({ id, username, first_name }) => ({ id, username, first_name })) }
  }
  return route.fulfill({ json: body })
})

try {
  await page.goto(`${base}/admin/users`)
  await page.getByRole('heading', { name: '用户管理', exact: true }).waitFor()
  await page.locator('.el-table').getByText('Employee 1', { exact: true }).waitFor()
  assert.equal(await page.locator('.el-table__row').first().getByText('无', { exact: true }).count(), 2)
  await page.locator('.el-pager').getByText('2', { exact: true }).click()
  await page.locator('.el-table').getByText('Employee 21', { exact: true }).waitFor()
  await page.locator('.department-filter .el-select__wrapper').click()
  await page.getByRole('option', { name: 'Support', exact: true }).click()
  await page.locator('.el-table').getByText('Employee 3', { exact: true }).waitFor()
  assert.equal(requests.at(-1).searchParams.get('skip'), '0')
  assert.equal(requests.at(-1).searchParams.get('department'), 'Support')
  await page.locator('.superuser-filter .el-select__wrapper').click()
  await page.getByRole('option', { name: '超级用户：否', exact: true }).click()
  await page.locator('.el-table__empty-text').getByText('无', { exact: true }).waitFor()
  assert.equal(requests.at(-1).searchParams.get('is_superuser'), 'false')
  await page.locator('.department-filter').hover()
  await page.locator('.department-filter .el-select__clear').click()
  await page.locator('.el-table').getByText('Employee 2', { exact: true }).waitFor()
  assert.equal(requests.at(-1).searchParams.has('department'), false)
  await page.locator('.superuser-filter .el-select__wrapper').click()
  await page.getByRole('option', { name: '超级用户：是', exact: true }).click()
  await page.locator('.el-table').getByText('Employee 1', { exact: true }).waitFor()
  assert.equal(requests.at(-1).searchParams.get('is_superuser'), 'true')
  await page.locator('.superuser-filter').hover()
  await page.locator('.superuser-filter .el-select__clear').click()
  await page.locator('.el-table').getByText('Employee 2', { exact: true }).waitFor()
  assert.equal(requests.at(-1).searchParams.has('is_superuser'), false)
  await page.locator('.username-filter .el-select__wrapper').click()
  const assertDropdownWidth = async () => {
    const input = await page.locator('.username-filter').boundingBox()
    await page.locator('.el-select__popper.user-management-user-options').waitFor({ state: 'visible' })
    const menu = await page.locator('.el-select__popper.user-management-user-options').boundingBox()
    assert(Math.abs(input.width - menu.width) <= 2, `Dropdown ${menu.width}, input ${input.width}`)
    assert(menu.x >= 0 && menu.x + menu.width <= (await page.viewportSize()).width)
  }
  await assertDropdownWidth()
  await page.screenshot({ path: path.join(output, 'desktop-dropdown.png') })
  await page.getByRole('combobox', { name: '用户名筛选' }).fill('user2')
  const userOption = page.getByRole('option').filter({ has: page.getByText('user2', { exact: true }) })
  await userOption.waitFor()
  assert.equal(await userOption.locator('.user-account').textContent(), 'user2')
  await page.getByRole('combobox', { name: '用户名筛选' }).fill('Employee 2')
  await userOption.click()
  await page.locator('.el-table').getByText('Employee 2', { exact: true }).waitFor()
  assert.equal(await page.locator('.username-filter .el-select__selected-item').filter({ hasText: 'Employee 2' }).count(), 1)
  assert.equal(requests.at(-1).searchParams.get('user_id'), '2')
  assert.equal(await page.locator('.el-table__row').count(), 1)
  await page.locator('.department-filter .el-select__wrapper').click()
  await page.getByRole('option', { name: 'Support', exact: true }).click()
  await page.locator('.el-table__empty-text').waitFor()
  await page.locator('.username-filter').hover()
  await page.locator('.username-filter .el-select__clear').click()
  await page.locator('.el-table').getByText('Employee 3', { exact: true }).waitFor()
  assert.equal(requests.at(-1).searchParams.has('user_id'), false)
  await page.screenshot({ path: path.join(output, 'desktop.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: path.join(output, 'mobile.png') })
  assert(await page.locator('body').evaluate(element => element.scrollWidth <= innerWidth))
  for (const selector of ['.department-filter', '.superuser-filter', '.username-filter']) {
    assert(await page.locator(selector).evaluate(element => {
      const bounds = element.getBoundingClientRect()
      return bounds.left >= 0 && bounds.right <= innerWidth
    }), selector)
  }
  await page.screenshot({ path: path.join(output, 'mobile.png') })
  await page.locator('.username-filter .el-select__wrapper').click()
  await assertDropdownWidth()
  await page.screenshot({ path: path.join(output, 'mobile-dropdown.png') })
  await page.getByRole('combobox', { name: '用户名筛选' }).press('Escape')
  failUsers = true
  await page.getByRole('button', { name: '搜索', exact: true }).click()
  await page.getByText('User directory unavailable', { exact: true }).waitFor()
  await page.locator('.el-table__empty-text').getByText('无', { exact: true }).waitFor()
  assert.deepEqual(errors, [])
  process.stdout.write('Passed: department column, combined filters, boolean false, username dropdown search, exact selection and clear, pagination reset, failure feedback and desktop/mobile layout.\n')
} finally {
  await browser.close()
}

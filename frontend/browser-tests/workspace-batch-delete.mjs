import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.CHAT_TEST_URL || 'http://127.0.0.1:15177'
const output = path.resolve('node_modules/.cache/workspace-batch-delete')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: 'msedge', headless: true })

try {
  for (const width of [1440, 390]) {
    const page = await browser.newPage({ viewport: { width, height: 960 } })
    const errors = []
    const deleted = []
    let failPath = 'retry.txt'
    let previewRequests = 0
    let releaseDelete
    let deleteGate = null
    let files = [
      { name: 'reports', path: 'reports', type: 'dir' },
      { name: 'draft.txt', path: 'draft.txt', type: 'file', size: 321, is_previewable: true },
      { name: 'retry.txt', path: 'retry.txt', type: 'file', size: 54 },
      { name: '这是一个很长的工作区文件名称用于检查窄屏显示.xlsx', path: '这是一个很长的工作区文件名称用于检查窄屏显示.xlsx', type: 'file', size: 9876 },
      { name: '.claude', path: '.claude', type: 'dir', is_managed: true },
      { name: 'CLAUDE.md', path: 'CLAUDE.md', type: 'file', size: 20, is_managed: true },
      { name: 'child.txt', path: 'reports/child.txt', type: 'file', size: 111 },
    ]
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => localStorage.setItem('access_token', 'workspace-test'))
    await page.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
      let body = { items: [], total: 0 }
      if (url.pathname === '/iam/api/me') body = { id: 7, username: 'workspace-test', permissions: [] }
      if (url.pathname.endsWith('/bootstrap')) body = { assistant_id: 1 }
      if (url.pathname.endsWith('/credits/me')) body = { claimed_today: true, available_balance: 100 }
      if (url.pathname === '/aihub/api/agents/1') body = { id: 1, name: 'AI 助手', icon: 'H', kind: 'personal_default', runtime_type: 'claude_code', models: [], skills: [] }
      if (url.pathname.endsWith('/files/preview')) previewRequests += 1
      if (url.pathname === '/aihub/api/agents/1/files') {
        const filePath = url.searchParams.get('path') || ''
        if (route.request().method() === 'DELETE') {
          assert.equal(route.request().headers().authorization, 'Bearer workspace-test')
          assert(files.some(item => item.path === filePath && !item.is_managed), 'Only deletable items may be sent')
          deleted.push(filePath)
          if (deleteGate) await deleteGate
          if (filePath === failPath) return route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ detail: '文件正在使用中' }) })
          files = files.filter(item => item.path !== filePath && !item.path.startsWith(`${filePath}/`))
          body = { message: '工作区内容已删除' }
        } else {
          body = { type: 'dir', items: files.filter(item => item.path.split('/').slice(0, -1).join('/') === filePath) }
        }
      }
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    })

    await page.goto(`${base}/embed/chat`)
    await page.getByRole('button', { name: '工作区文件', exact: true }).click()
    const panel = page.locator('.workspace-tree')
    const row = name => panel.locator('.tree-row').filter({ has: page.locator('.tree-name', { hasText: name }) })
    const select = name => panel.getByRole('checkbox', { name: `选择 ${name}`, exact: true })
    const all = panel.getByRole('checkbox', { name: '全选', exact: true })
    const remove = panel.getByRole('button', { name: '删除所选', exact: true })
    const setChecked = async (checkbox, checked = true) => {
      if (await checkbox.isChecked() !== checked) await checkbox.locator('xpath=ancestor::label').click()
    }
    await row('reports').waitFor()
    await row('reports').click()
    await row('child.txt').waitFor()
    await panel.getByRole('button', { name: '批量选择', exact: true }).click()
    await setChecked(select('child.txt'))
    await panel.getByRole('button', { name: '全部文件', exact: true }).click()
    await row('draft.txt').waitFor()
    assert.equal(await panel.locator('.tree-row-checkbox.is-checked').count(), 0, 'Navigating clears selection')
    assert(await remove.isDisabled(), 'Empty selections cannot be deleted')
    assert(await select('.claude').isDisabled())
    assert(await select('CLAUDE.md').isDisabled())
    await setChecked(all)
    assert.equal(await panel.locator('.tree-row-checkbox.is-checked').count(), 4, 'Select all excludes managed files and directories')
    await setChecked(all, false)
    await row('draft.txt').click()
    assert(await select('draft.txt').isChecked(), 'Clicking a row toggles selection once')
    await row('draft.txt').dblclick()
    assert.equal(previewRequests, 0, 'Batch selection must not open previews')
    await setChecked(select('draft.txt'))
    await setChecked(select('retry.txt'))
    await setChecked(select('reports'))
    assert.equal(await panel.locator('.tree-batch-toolbar .is-indeterminate').count(), 1)
    await remove.click()
    const dialog = page.getByRole('dialog', { name: '批量删除', exact: true })
    await dialog.waitFor()
    assert.match(await dialog.textContent(), /选中的 3 项/)
    assert.match(await dialog.textContent(), /目录及其中全部内容/)
    assert.deepEqual(await dialog.locator('li').allTextContents(), ['reports/', 'draft.txt', 'retry.txt'])
    await page.screenshot({ path: path.join(output, `confirmation-${width}.png`), animations: 'disabled' })
    await dialog.getByRole('button', { name: '取消', exact: true }).click()
    await dialog.waitFor({ state: 'hidden' })
    assert.deepEqual(deleted, [], 'Cancel must not delete anything')
    assert.equal(await panel.locator('.tree-row-checkbox.is-checked').count(), 3)
    await page.screenshot({ path: path.join(output, `selection-${width}.png`), animations: 'disabled' })

    deleteGate = new Promise(resolve => { releaseDelete = resolve })
    await remove.click()
    const firstDelete = page.waitForRequest(request => request.method() === 'DELETE')
    await dialog.getByRole('button', { name: '删除', exact: true }).click()
    await firstDelete
    assert(await remove.isDisabled(), 'In-flight batches cannot be submitted twice')
    assert(await select('retry.txt').isDisabled(), 'In-flight selection is frozen')
    assert(await panel.getByRole('button', { name: '刷新工作区文件', exact: true }).isDisabled())
    assert(await panel.getByRole('button', { name: '退出批量选择', exact: true }).isDisabled())
    releaseDelete()
    await page.getByText('已删除 2 项，1 项失败：retry.txt（文件正在使用中）', { exact: true }).waitFor()
    await page.waitForFunction(() => !document.querySelector('.tree-batch-delete').disabled)
    assert.deepEqual(deleted, ['reports', 'draft.txt', 'retry.txt'])
    assert.equal(await row('draft.txt').count(), 0)
    assert.equal(await row('reports').count(), 0)
    assert(await select('retry.txt').isChecked(), 'Failed items remain selected for retry')
    assert.equal(await panel.locator('.tree-row-checkbox.is-checked').count(), 1)
    await page.screenshot({ path: path.join(output, `partial-failure-${width}.png`), animations: 'disabled' })

    failPath = ''
    await remove.click()
    await dialog.getByRole('button', { name: '删除', exact: true }).click()
    await panel.getByRole('button', { name: '批量选择', exact: true }).waitFor()
    assert.equal(deleted.at(-1), 'retry.txt')
    assert.equal(await row('retry.txt').count(), 0)
    assert.equal(await panel.locator('.tree-row').count(), 3, 'Unselected and managed items remain')

    await panel.getByRole('button', { name: '批量选择', exact: true }).click()
    await setChecked(all)
    assert.equal(await panel.locator('.tree-row-checkbox.is-checked').count(), 1)
    const bounds = await panel.locator('.tree-row, .tree-batch-toolbar, .tree-toolbar').evaluateAll(elements => elements.map(element => {
      const box = element.getBoundingClientRect()
      return box.left >= 0 && box.right <= innerWidth && element.scrollWidth <= element.clientWidth
    }))
    assert(bounds.every(Boolean), 'Batch controls and long file names fit desktop and mobile')
    await remove.click()
    assert(await dialog.evaluate(element => {
      const box = element.getBoundingClientRect()
      return box.left >= 0 && box.right <= innerWidth && element.scrollWidth <= element.clientWidth
    }), 'Confirmation must fit the viewport even with long file names')
    await dialog.getByRole('button', { name: '删除', exact: true }).click()
    await panel.getByRole('button', { name: '批量选择', exact: true }).waitFor()
    assert.equal(await panel.locator('.tree-row').count(), 2)
    assert(files.some(item => item.path === '.claude'))
    assert(files.some(item => item.path === 'CLAUDE.md'))
    assert(!files.some(item => item.path === 'reports/child.txt'), 'Selected directories delete their descendants')
    await panel.getByRole('button', { name: '批量选择', exact: true }).click()
    assert(await all.isDisabled(), 'Managed-only directories cannot be selected')
    assert(await remove.isDisabled())
    assert.deepEqual(errors, [])
    await page.close()
  }
  console.log('Workspace batch deletion passed: desktop/mobile, selection, directory scope, confirmation, cancellation, managed content, partial failure and retry.')
} finally {
  await browser.close()
}

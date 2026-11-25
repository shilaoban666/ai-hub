import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.CHAT_TEST_URL || 'http://127.0.0.1:15173'
const output = path.resolve('../output/playwright/chat-skill-suggestions')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })
const model = { id: 1, name: 'deepseek-flash', api_protocol: 'anthropic-messages', scope: 'platform' }
const personalSkills = [
  { id: 11, name: '文档助手', conversation_examples: ['把这份会议纪要整理成行动清单', '帮我把项目资料整理成一份汇报文档'] },
  { id: 12, name: '数据分析', conversation_examples: ['分析这张表格，找出值得关注的变化', '对比两份报表，归纳主要差异'] },
  { id: 13, name: '项目助手', conversation_examples: ['梳理本周项目进展和下一步计划', '根据需求文档，拆解可执行的任务'] },
  { id: 14, name: '写作助手', conversation_examples: ['把这段说明改得更简洁、易懂', '帮我起草一封清楚得体的工作邮件'] },
  { id: 15, name: '阅读助手', conversation_examples: ['提炼这篇长文的核心观点', '把这份会议纪要整理成行动清单', '  ', null] },
  { id: 16, name: '代码助手', conversation_examples: ['解释这段代码的执行过程', '检查这段代码可能遗漏的边界情况'] },
  { id: 17, name: '无示例技能', conversation_examples: [] },
]
const longPrompt = `请根据以下要求整理完整报告：\n${'保留材料中的事实与出处，并明确区分结论和待确认事项。'.repeat(20)}`
const expertSkills = [{ id: 91, name: '专家报告', conversation_examples: [longPrompt] }]
const assistant = { id: 1, name: '小趣', icon: 'AI', kind: 'personal_default', runtime_type: 'claude_code', default_model_id: 1, models: [model], skills: [] }
const expert = { ...assistant, id: 9, name: '报告专家', kind: 'expert', skills: expertSkills }
const errors = []

async function setup(routePath, { skills = personalSkills, fail = false, delayed = false, delayFiles = false } = {}) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
  page.setDefaultTimeout(10000)
  page.on('pageerror', error => errors.push(error.message))
  const sent = []
  let releaseSkills
  const gate = delayed ? new Promise(resolve => { releaseSkills = resolve }) : Promise.resolve()
  let releaseFiles
  const filesGate = delayFiles ? new Promise(resolve => { releaseFiles = resolve }) : Promise.resolve()
  await page.addInitScript(() => localStorage.setItem('access_token', 'skill-suggestions-browser-only'))
  await page.route('**/*', async route => {
    const request = route.request(), pathname = new URL(request.url()).pathname
    if (!/^\/(aihub|iam)\/api\//.test(pathname)) return route.continue()
    let body = { items: [], total: 0 }
    if (pathname === '/iam/api/me') body = { id: 7, username: '测试用户', permissions: [] }
    else if (pathname.endsWith('/bootstrap')) body = { assistant_id: 1, assistant }
    else if (pathname.endsWith('/credits/me')) body = { claimed_today: true, available_balance: 100, display_name: '趣点' }
    else if (pathname === '/aihub/api/agents/1') body = assistant
    else if (pathname === '/aihub/api/agents/9') body = expert
    else if (pathname === '/aihub/api/agents') body = { items: [expert], total: 1 }
    else if (pathname.endsWith('/assets/skills/available')) {
      await gate
      if (fail) return route.fulfill({ status: 500, json: { detail: '模拟技能读取失败' } })
      body = { items: skills.map(skill => ({ ...skill, skill_id: skill.id })) }
    } else if (pathname.endsWith('/models')) body = { items: [model], total: 1 }
    else if (pathname.endsWith('/runtime-status')) body = { status: 'ready', runtime_type: 'claude_code' }
    else if (pathname.endsWith('/files')) {
      await filesGate
      body = { items: [{ name: 'brief.md', path: 'brief.md', type: 'file' }] }
    }
    else if (/\/agents\/\d+\/messages$/.test(pathname) && request.method() === 'POST') {
      sent.push(request.postDataJSON())
      return route.fulfill({ contentType: 'text/event-stream', body: [
        { type: 'run_start', run_id: 'suggestions-test', session_id: 3 },
        { type: 'text', content: '已收到任务与技能引用。' },
        { type: 'done' }, { type: 'stream_end', status: 'succeeded' },
      ].map(event => `data: ${JSON.stringify(event)}\n\n`).join('') })
    }
    return route.fulfill({ json: body })
  })
  await page.goto(base + routePath)
  await page.locator('.composer-surface').waitFor()
  return { page, sent, releaseSkills, releaseFiles }
}
const prompts = page => page.locator('.suggestion-text').allTextContents()
const draftText = page => page.locator('.cm-content').evaluate(element => {
  const clone = element.cloneNode(true)
  clone.querySelectorAll('.composer-reference-prefix').forEach(node => node.remove())
  return [...clone.querySelectorAll('.cm-line')].map(line => line.textContent).join('\n')
})

try {
  const { page, sent, releaseSkills, releaseFiles } = await setup('/workspace/chat', { delayed: true, delayFiles: true })
  assert.equal(await page.locator('.welcome-suggestions').count(), 0, 'Wait for the skill list before showing defaults')
  const initialComposer = await page.locator('.composer-surface').boundingBox()
  const composer = page.locator('.cm-content[contenteditable="true"]')
  const referenceMenu = page.getByRole('dialog', { name: '输入引用菜单' })
  await composer.fill('/文档')
  await referenceMenu.getByText('正在加载技能…').waitFor()
  assert.equal(await referenceMenu.getByText('没有匹配的技能').count(), 0)
  releaseSkills()
  await referenceMenu.getByRole('button', { name: '文档助手' }).waitFor()
  assert.equal(await referenceMenu.getByText('正在加载技能…').count(), 0)
  await page.locator('.suggestion-item').nth(3).waitFor()
  assert.equal((await page.locator('.composer-surface').boundingBox()).y, initialComposer.y, 'Loading recommendations must not move the composer')
  assert.match(await page.locator('.suggestions-list').evaluate(element => getComputedStyle(element).animationName), /^suggestions-fade-in(?:-|$)/)
  await page.locator('.suggestions-list').evaluate(element => Promise.all(element.getAnimations().map(animation => animation.finished)))
  assert.equal((await page.locator('.composer-surface').boundingBox()).y, initialComposer.y, 'Fading recommendations must not move the composer')
  const before = await prompts(page)
  assert.equal(new Set(before).size, 4)
  const titles = await page.locator('.suggestion-item').evaluateAll(items => items.map(item => item.title.split('\n')[0]))
  assert.equal(new Set(titles).size, 4, 'At most one recommendation per skill')
  await composer.fill('已有草稿 @')
  await referenceMenu.getByText('正在加载文件…').waitFor()
  assert.ok(await referenceMenu.getByRole('button', { name: /添加文件/ }).isEnabled())
  releaseFiles()
  await page.getByRole('button', { name: 'brief.md', exact: true }).click()
  await composer.locator('.composer-reference.file').waitFor()
  const draft = await draftText(page)
  await page.getByRole('button', { name: '更多操作', exact: true }).click()
  await page.getByRole('button', { name: '更多操作', exact: true }).click()
  assert.deepEqual(await prompts(page), before, 'Typing, attachment selection, and menus must not reshuffle suggestions')
  const composerBeforeRefresh = await page.locator('.composer-surface').boundingBox()
  await page.getByRole('button', { name: '换一批', exact: true }).click()
  assert.equal((await page.locator('.composer-surface').boundingBox()).y, composerBeforeRefresh.y, 'Refreshing recommendations must not move the composer')
  const after = await prompts(page)
  assert.ok(after.some(prompt => !before.includes(prompt)))
  assert.equal(await draftText(page), draft)
  const selected = after[0]
  await page.locator('.suggestion-item').first().press('Enter')
  assert.equal(await composer.locator('.composer-reference.skill').count(), 0, 'Suggestions only insert text without selecting a skill')
  assert.equal(await draftText(page), `${draft}\n\n${selected}`)
  assert.ok(await composer.evaluate(element => element === document.activeElement))
  assert.equal(sent.length, 0, 'Clicking a suggestion fills the draft without submitting')
  await composer.locator('.composer-reference.file').waitFor()
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await page.getByText('已收到任务与技能引用。', { exact: true }).waitFor()
  assert.ok(sent[0].skill_id == null, 'Suggestions must not attach a skill to the request')
  assert.equal(sent[0].content, `${draft}\n\n${selected}`.trim())
  assert.deepEqual(sent[0].attached_files, ['brief.md'])
  assert.equal(await page.locator('.welcome-suggestions').count(), 0)
  await page.getByRole('button', { name: '新建对话', exact: true }).click()
  await page.locator('.suggestion-item').nth(3).waitFor()
  assert.ok((await prompts(page)).some(prompt => !after.includes(prompt)))
  await page.locator('.compact-actions-trigger.is-open').waitFor({ state: 'hidden' })
  await page.getByRole('button', { name: '添加文件', exact: true }).waitFor({ state: 'hidden' })
  await composer.evaluate(element => element.blur())
  await page.screenshot({ path: path.join(output, 'desktop.png'), animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.screenshot({ path: path.join(output, 'mobile.png'), animations: 'disabled' })
  await page.setViewportSize({ width: 320, height: 480 })
  await page.locator('.suggestion-item').last().scrollIntoViewIfNeeded()
  const lastSuggestion = await page.locator('.suggestion-item').last().boundingBox()
  assert.ok(lastSuggestion.y >= 0 && lastSuggestion.y + lastSuggestion.height <= 481)
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
  await page.close()
  console.log('Passed: delayed load, diverse suggestions, stable drafts, refresh, attachments, keyboard selection, send payload, new conversation.')

  for (const routePath of ['/workspace/chat?agent=9', '/admin/agents/9/chat']) {
    const { page, sent } = await setup(routePath)
    await page.locator('.suggestion-item').waitFor()
    if (routePath.startsWith('/workspace/')) {
      assert.equal((await page.locator('.composer-surface').boundingBox()).y, initialComposer.y, 'One or four recommendations must use the same composer position')
      await page.emulateMedia({ reducedMotion: 'reduce' })
      assert.equal(await page.locator('.suggestions-list').evaluate(element => getComputedStyle(element).animationName), 'none')
    }
    assert.deepEqual(await prompts(page), [longPrompt])
    assert.equal(await page.getByRole('button', { name: '换一批', exact: true }).count(), 0)
    const item = page.locator('.suggestion-item')
    assert.ok((await item.getAttribute('title')).includes(longPrompt))
    await item.click()
    assert.equal(await draftText(page), longPrompt)
    assert.equal(await page.locator('.composer-reference.skill').count(), 0, 'Expert suggestions also insert only text')
    assert.equal(sent.length, 0)
    if (routePath.startsWith('/workspace/')) {
      for (const [width, height] of [[390, 844], [320, 640], [390, 480]]) {
        await page.setViewportSize({ width, height })
        await item.scrollIntoViewIfNeeded()
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
        const bounds = await item.boundingBox()
        assert.ok(bounds.x >= 0 && bounds.x + bounds.width <= width + 1)
        assert.ok(bounds.y >= 0 && bounds.y + bounds.height <= height + 1)
      }
      await page.setViewportSize({ width: 390, height: 844 })
      await page.screenshot({ path: path.join(output, 'mobile-long-example.png'), animations: 'disabled' })
    }
    await page.close()
    console.log(`Passed: ${routePath}: scoped examples, full prompt preservation, no redundant refresh, responsive overflow.`)
  }
  for (const options of [{ skills: [] }, { skills: [personalSkills.at(-1)] }, { fail: true }]) {
    const { page, sent } = await setup('/workspace/chat', options)
    await page.getByRole('button', { name: '切换模型', exact: true }).filter({ hasText: 'deepseek-flash' }).waitFor()
    const suggestions = page.locator('.suggestion-item')
    await suggestions.nth(1).waitFor()
    assert.deepEqual(await prompts(page), ['给我一份简洁的工作周报模板', '帮我写一封项目进度跟进邮件'])
    assert.equal(await page.getByRole('button', { name: '换一批', exact: true }).count(), 0)
    const prompt = await suggestions.first().locator('.suggestion-text').textContent()
    assert.equal(await suggestions.first().getAttribute('title'), prompt)
    await page.locator('.cm-content').fill('已有草稿')
    await suggestions.first().click()
    assert.equal(await draftText(page), `已有草稿\n\n${prompt}`)
    assert.equal(await page.locator('.cm-content .composer-reference.skill').count(), 0)
    assert.equal(sent.length, 0)
    assert.equal(await page.getByRole('button', { name: '发送', exact: true }).isEnabled(), true)
    await page.close()
  }
  assert.deepEqual(errors, [])
  console.log('Passed: no skills, no examples, and failed skill loading show usable default prompts; no browser errors.')
} finally {
  await browser.close()
}

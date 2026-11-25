import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
import { createRequire } from 'node:module'
import path from 'node:path'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright')
const base = process.env.CHAT_TEST_URL || 'http://localhost:15176'
const output = path.resolve('node_modules/.cache/chat-image-paste')
await mkdir(output, { recursive: true })
const browser = await chromium.launch({ channel: process.env.PLAYWRIGHT_CHANNEL || 'chrome', headless: true })

try {
  for (const viewport of [{ width: 1440, height: 960 }, { width: 390, height: 844 }]) {
    const context = await browser.newContext({ viewport, permissions: ['clipboard-read', 'clipboard-write'] })
    const page = await context.newPage()
    const sent = []
    const uploads = []
    const errors = []
    let releaseUploads
    let uploadGate = new Promise(resolve => { releaseUploads = resolve })
    let failUpload = false
    let imageFixture
    let imageDownloads = 0
    let failSend = false
    let responseGate = null
    page.on('pageerror', error => errors.push(error.message))
    await page.addInitScript(() => localStorage.setItem('access_token', 'image-paste-test'))
    await page.addInitScript(() => {
      const originalFetch = window.fetch
      window.fetch = async (...args) => {
        const response = await originalFetch(...args)
        if (!window.holdChatStream || !String(args[0]).endsWith('/agents/1/messages') || !response.ok) return response
        const body = await response.text()
        const boundary = body.indexOf('\n\n') + 2
        const encoder = new TextEncoder()
        return new Response(new ReadableStream({
          start(controller) {
            controller.enqueue(encoder.encode(body.slice(0, boundary)))
            window.finishChatStream = () => {
              controller.enqueue(encoder.encode(body.slice(boundary)))
              controller.close()
              window.holdChatStream = false
            }
          },
        }), { status: response.status, headers: response.headers })
      }
    })
    await page.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (url.host === 'fancyqube-aihub.oss-cn-shanghai.aliyuncs.com') {
        assert.equal(route.request().headers().authorization, undefined, 'Public image requests must not include app credentials')
        return route.fulfill({ contentType: 'image/png', body: imageFixture })
      }
      if (url.pathname === '/chat-image-test-host') return route.fulfill({ contentType: 'text/html', body: `<!doctype html><html><body style="margin:0"><script>
        addEventListener('message', event => {
          if (event.origin !== location.origin || event.data?.type !== 'auth-request') return
          event.source.postMessage({ protocol: 'aihub-embed-v1', type: 'auth-result', request_id: event.data.request_id, ok: true,
            result: { user_id: 7, session_id: 'a'.repeat(64), access_token: 'image-paste-test', token_type: 'bearer', expires_in: 900 } }, event.origin)
        })
        </script><iframe title="Image test chat" src="/embed/chat${url.search}" style="border:0;width:100%;height:100dvh;display:block"></iframe></body></html>` })
      if (!/^\/(aihub|iam)\/api\//.test(url.pathname)) return route.continue()
      let body = { items: [], total: 0 }
      if (url.pathname === '/iam/api/me') body = { id: 7, username: 'image-test', permissions: [] }
      if (url.pathname.endsWith('/bootstrap')) body = { assistant_id: 1 }
      if (url.pathname.endsWith('/credits/me')) body = { claimed_today: true, display_name: '算点', available_balance: 100 }
      if (url.pathname.endsWith('/assets/skills/available')) body = { items: [
        { skill_id: 11, name: '本轮技能', user_installation: {} },
        { skill_id: 12, name: '下轮技能', user_installation: {} },
      ] }
      if (url.pathname === '/aihub/api/agents/1') body = { id: 1, name: 'AI 助手', icon: 'H', kind: 'personal_default', runtime_type: 'claude_code', default_model_id: 1, models: [{ id: 1, name: '测试模型' }], skills: [] }
      if (url.pathname.endsWith('/sessions/3/messages')) body = {
        session: { id: 3, source: 'web' },
        items: sent.map((message, index) => ({ id: index + 1, role: 'user', content: message.content, attached_files: message.attached_files,
          skill: message.skill_id ? { id: message.skill_id, name: message.skill_id === 11 ? '本轮技能' : '下轮技能' } : null })),
      }
      if (url.pathname === '/aihub/api/agents/1/files') body = { type: 'dir', items: [
        { name: 'workspace.txt', path: 'workspace.txt', type: 'file', size: 123 },
      ] }
      if (url.pathname.endsWith('/files/download')) {
        assert.equal(route.request().headers().authorization, 'Bearer image-paste-test')
        assert(uploads.includes(url.searchParams.get('path')))
        imageDownloads += 1
        return route.fulfill({ contentType: 'application/octet-stream', body: imageFixture })
      }
      if (url.pathname.endsWith('/files/upload') || url.pathname.endsWith('/images/upload')) {
        const name = /filename="([^"]+)"/.exec(route.request().postDataBuffer().toString())[1]
        const isImage = url.pathname.endsWith('/images/upload')
        const imageUrl = `https://fancyqube-aihub.oss-cn-shanghai.aliyuncs.com/tmp/chat-images/7/20261111/${name}`
        uploads.push(isImage ? imageUrl : name)
        await uploadGate
        if (failUpload) return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'test upload failure' }) })
        body = isImage ? { name, url: imageUrl } : { uploaded: [{ name, path: name }] }
      }
      if (url.pathname === '/aihub/api/agents/1/messages' && route.request().method() === 'POST') {
        sent.push(route.request().postDataJSON())
        if (responseGate) await responseGate
        if (failSend) return route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'test send failure' }) })
        return route.fulfill({ contentType: 'text/event-stream', body: [
          { type: 'run_queued', run_id: 'image-test', session_id: 3 },
          { type: 'run_start', run_id: 'image-test', session_id: 3 },
          { type: 'text', content: '已收到图片。' }, { type: 'done' },
        ].map(event => `data: ${JSON.stringify(event)}\n\n`).join('') })
      }
      return route.fulfill({ contentType: 'application/json', body: JSON.stringify(body) })
    })

    let chatFrame
    const openChat = async (query = '') => {
      if (chatFrame) { await chatFrame.goto(`${base}/embed/chat${query}`, { referer: `${base}/chat-image-test-host` }); return }
      await page.goto(`${base}/chat-image-test-host${query}`)
      await page.locator('iframe').waitFor()
      chatFrame = await (await page.locator('iframe').elementHandle()).contentFrame()
    }
    await openChat()
    const input = chatFrame.locator('.cm-content[contenteditable="true"]')
    const draftText = () => input.evaluate(editor => [...editor.querySelectorAll('.cm-line')].map(line => {
      const copy = line.cloneNode(true)
      copy.querySelectorAll('.composer-reference-prefix, .cm-widgetBuffer, .cm-placeholder').forEach(node => node.remove())
      return copy.textContent
    }).join('\n'))
    const send = chatFrame.getByRole('button', { name: '发送', exact: true })
    const waitForComposerFocus = () => chatFrame.waitForFunction(() => document.activeElement?.matches('.cm-content[contenteditable="true"]'))
    await input.waitFor()
    await input.focus()
    await chatFrame.evaluate(() => navigator.clipboard.writeText('normal text paste'))
    await input.press(process.platform === 'darwin' ? 'Meta+V' : 'Control+V')
    await chatFrame.waitForFunction(() => document.querySelector('.cm-content')?.textContent.includes('normal text paste'))
    assert.equal(await draftText(), 'normal text paste')
    assert.equal(uploads.length, 0)
    await input.fill('')

    const pasteImages = async (count = 1, oversized = false) => {
      const result = await input.evaluate((element, options) => {
      const canvas = document.createElement('canvas')
      canvas.width = 640
      canvas.height = 360
      const ctx = canvas.getContext('2d')
      ctx.fillStyle = '#f7f8fa'
      ctx.fillRect(0, 0, 640, 360)
      ctx.fillStyle = '#27352e'
      ctx.font = '28px Arial'
      ctx.fillText('Quarterly revenue', 32, 50)
      for (let i = 0; i < 4; i++) {
        ctx.fillStyle = ['#3a8060', '#d9a33b', '#538bc4', '#c67869'][i]
        ctx.fillRect(40 + i * 145, 300 - (i + 1) * 50, 90, (i + 1) * 50)
      }
      const bytes = Uint8Array.from(atob(canvas.toDataURL().split(',')[1]), char => char.charCodeAt(0))
      const clipboardData = new DataTransfer()
      for (let i = 0; i < options.count; i++) {
        clipboardData.items.add(new File([options.oversized ? new Uint8Array(5 * 1024 * 1024 + 1) : bytes], 'image.png', { type: 'image/png' }))
      }
      const event = new ClipboardEvent('paste', { clipboardData, bubbles: true, cancelable: true })
      element.dispatchEvent(event)
      return { prevented: event.defaultPrevented, png: canvas.toDataURL().split(',')[1] }
    }, { count, oversized })
      imageFixture = Buffer.from(result.png, 'base64')
      return result.prevented
    }

    const composer = chatFrame.locator('.composer-surface')
    const beforeUpload = await composer.boundingBox()
    assert.equal(await pasteImages(2), true)
    await chatFrame.getByRole('status').filter({ hasText: '正在上传附件' }).waitFor()
    assert.deepEqual(await composer.boundingBox(), beforeUpload, 'Starting an upload must not move or resize the composer')
    const uploadStatus = await chatFrame.locator('.upload-status').boundingBox()
    assert(uploadStatus.y + uploadStatus.height <= beforeUpload.y, 'Upload progress belongs above the composer')
    await page.screenshot({ path: path.join(output, `uploading-${viewport.width}.png`) })
    assert(await send.isDisabled(), 'Upload in progress must block sending')
    await input.press('Enter')
    assert.equal(sent.length, 0)
    releaseUploads()
    await chatFrame.locator('.chip-image img').nth(1).waitFor()
    await chatFrame.locator('.chip-image img').evaluateAll(images => Promise.all(images.map(image => image.decode())))
    const previewBorder = await chatFrame.locator('.chip-image').first().evaluate(element => {
      const style = getComputedStyle(element)
      return { width: style.borderTopWidth, style: style.borderTopStyle, color: style.borderTopColor }
    })
    assert.deepEqual(previewBorder, { width: '1px', style: 'solid', color: 'rgb(228, 231, 237)' })
    assert.deepEqual(await chatFrame.locator('.chip-close').first().evaluate(el => {
      const style = getComputedStyle(el)
      return { background: style.backgroundColor, color: style.color }
    }), { background: 'rgb(96, 98, 102)', color: 'rgb(255, 255, 255)' })
    assert.equal(new Set(uploads).size, 2, 'Every paste image needs a unique filename')
    assert.equal(await send.isEnabled(), true, 'Image-only messages can be sent')
    const chips = await chatFrame.locator('.context-chip').evaluateAll(elements => elements.map(element => {
      const chip = element.getBoundingClientRect()
      const image = element.querySelector('img').getBoundingClientRect()
      const composer = element.closest('.composer-surface')?.getBoundingClientRect()
      const input = element.closest('.composer-surface')?.querySelector('.input-row').getBoundingClientRect()
      return { contains: image.top >= chip.top && image.bottom <= chip.bottom, right: chip.right,
        inside: composer && chip.top >= composer.top && chip.left >= composer.left && chip.right <= composer.right && chip.bottom <= input.top }
    }))
    assert(chips.every(chip => chip.contains && chip.right <= viewport.width), 'Image previews must fit their chips and viewport')
    assert(chips.every(chip => chip.inside), 'Image previews must be inside the composer and above the draft')
    await page.screenshot({ path: path.join(output, `paste-${viewport.width}.png`) })
    await chatFrame.locator('.chip-image').first().click()
    await chatFrame.locator('.el-image-viewer__wrapper').waitFor()
    await page.keyboard.press('Escape')
    await chatFrame.locator('.chip-close').first().click()
    assert.equal(await chatFrame.locator('.chip-image').count(), 1)
    await chatFrame.evaluate(() => { window.holdChatStream = true })
    await send.click()
    await chatFrame.locator('.context-chip').waitFor({ state: 'hidden' })
    assert.equal(await send.count(), 0, 'Attachments must clear while the response is still pending')
    await chatFrame.locator('.user-message-image img').evaluate(image => image.decode())
    await chatFrame.locator('.user-message-image').click()
    await chatFrame.locator('.el-image-viewer__wrapper').waitFor()
    await page.keyboard.press('Escape')
    await page.screenshot({ path: path.join(output, `queued-${viewport.width}.png`) })
    await chatFrame.evaluate(() => window.finishChatStream())
    await chatFrame.getByRole('button', { name: '发送', exact: true }).waitFor()
    assert.equal(sent.length, 1)
    assert.equal(sent[0].attached_files.length, 1)
    assert(uploads.includes(sent[0].attached_files[0]))
    assert(sent[0].attached_files[0].startsWith('https://fancyqube-aihub.oss-cn-shanghai.aliyuncs.com/'))
    const copyImageLink = chatFrame.getByRole('button', { name: '复制图片链接', exact: true })
    await chatFrame.locator('.user-bubble').hover()
    assert.equal(await copyImageLink.evaluate(element => getComputedStyle(element).opacity), '0', 'Copy icon stays hidden until hover or keyboard focus')
    const imageBounds = await chatFrame.locator('.user-image-attachment').boundingBox()
    await chatFrame.locator('.user-image-attachment').hover()
    assert.equal(await copyImageLink.evaluate(element => getComputedStyle(element).opacity), '1')
    assert.deepEqual(await chatFrame.locator('.user-image-attachment').boundingBox(), imageBounds, 'Hover must not change the image layout')
    await copyImageLink.click()
    assert.equal(await chatFrame.evaluate(() => navigator.clipboard.readText()), sent[0].attached_files[0])
    assert.equal(await chatFrame.locator('.el-image-viewer__wrapper').count(), 0, 'Copying must not open the image preview')
    assert.equal(await chatFrame.getByText('图片公网链接', { exact: true }).count(), 0, 'No link text appears below the image')
    assert.equal(sent[0].content, '请分析所附文件。')
    await chatFrame.locator('.user-message-image img').evaluate(image => image.decode())
    assert.equal(await chatFrame.locator('.context-chip').count(), 0, 'Sent attachments must clear automatically')
    await chatFrame.locator('.user-message-image img').evaluate(image => image.decode())
    await chatFrame.locator('.user-message-image').click()
    await chatFrame.locator('.el-image-viewer__wrapper').waitFor()
    await page.keyboard.press('Escape')

    await pasteImages(3)
    await chatFrame.locator('.chip-image img').nth(2).waitFor()
    await input.fill('请看这些图片，按图片上方、文字下方的样式显示。')
    await send.click()
    await chatFrame.getByRole('button', { name: '发送', exact: true }).waitFor()
    assert.equal(sent.length, 2)

    await chatFrame.getByRole('button', { name: '新对话', exact: true }).click()
    await pasteImages(1, true)
    await chatFrame.getByText('单张图片不能超过 5 MB').waitFor()
    assert.equal(uploads.length, 5)
    assert.equal(await chatFrame.locator('.chip-image').count(), 0)

    failUpload = true
    await pasteImages()
    await chatFrame.getByText('图片上传失败，请重试').waitFor()
    assert.equal(await chatFrame.locator('.chip-image').count(), 0)
    assert(await send.isDisabled())
    failUpload = false

    uploadGate = new Promise(resolve => { releaseUploads = resolve })
    await pasteImages()
    await chatFrame.getByRole('status').filter({ hasText: '正在上传附件' }).waitFor()
    await chatFrame.getByRole('button', { name: '新对话', exact: true }).click()
    releaseUploads()
    await chatFrame.getByRole('status').filter({ hasText: '正在上传附件' }).waitFor({ state: 'hidden' })
    assert.equal(await chatFrame.locator('.chip-image').count(), 0, 'Late uploads must not attach to another conversation')

    await openChat('?session=3')
    await chatFrame.locator('.user-message-image img').nth(3).waitFor()
    await chatFrame.locator('.user-message-image img').evaluateAll(images => Promise.all(images.map(image => image.decode())))
    assert.equal(imageDownloads, 0, 'OSS history images must load directly from their public URLs')
    assert.equal(await chatFrame.locator('.image-copy-link').count(), 4, 'History images must retain the copy action')
    assert.deepEqual(await chatFrame.locator('.user-message-image').first().evaluate(element => {
      const style = getComputedStyle(element)
      return { width: style.borderTopWidth, style: style.borderTopStyle, color: style.borderTopColor }
    }), previewBorder, 'History and composer thumbnails must share the same thin border')
    const layouts = await chatFrame.locator('.user-message-stack').evaluateAll(stacks => stacks.map(stack => {
      const images = stack.querySelector('.user-message-images').getBoundingClientRect()
      const bubble = stack.querySelector('.user-bubble').getBoundingClientRect()
      const bounds = stack.getBoundingClientRect()
      return { above: images.bottom <= bubble.top, aligned: Math.abs(images.right - bubble.right) < 1, left: bounds.left, right: bounds.right }
    }))
    assert(layouts.every(layout => layout.above && layout.aligned && layout.left >= 0 && layout.right <= viewport.width))
    assert.equal(await chatFrame.locator('.user-message-stack .chip-label').count(), 0)
    await page.screenshot({ path: path.join(output, `messages-${viewport.width}.png`) })
    await chatFrame.locator('.user-message-image').last().click()
    await chatFrame.locator('.el-image-viewer__wrapper').waitFor()
    await page.keyboard.press('Escape')

    if (process.env.CHAT_IMAGES_ONLY === '1') {
      assert.deepEqual(errors, [])
      await context.close()
      continue
    }

    const selectSkill = async name => {
      await chatFrame.getByRole('button', { name: '更多操作', exact: true }).click()
      await chatFrame.getByRole('button', { name: '技能', exact: true }).click()
      await chatFrame.getByRole('button', { name, exact: true }).click()
      await chatFrame.locator('.context-chip.skill').filter({ hasText: name }).waitFor()
      assert.equal(await chatFrame.locator('.composer-surface .context-chip.skill').count(), 1, 'Skill references belong inside the composer')
      await waitForComposerFocus()
    }
    const attachDocument = async name => {
      await chatFrame.getByRole('button', { name: '更多操作', exact: true }).focus()
      await chatFrame.locator('.chat-main input[type="file"]').setInputFiles({ name, mimeType: 'text/plain', buffer: Buffer.from('Reference document') })
      await chatFrame.locator('.context-chip.file').filter({ hasText: name }).waitFor()
      assert.equal(await chatFrame.locator('.composer-surface .context-chip.file').filter({ hasText: name }).count(), 1, 'Document references belong inside the composer')
      await waitForComposerFocus()
    }
    await chatFrame.getByRole('button', { name: '工作区文件', exact: true }).click()
    const workspaceRow = chatFrame.locator('.workspace-tree .tree-row').filter({ hasText: 'workspace.txt' })
    for (const interaction of ['mouse', 'contextmenu', 'keyboard']) {
      await workspaceRow.hover()
      if (interaction === 'contextmenu') await workspaceRow.click({ button: 'right' })
      else await workspaceRow.getByRole('button', { name: '文件操作', exact: true }).click()
      const menuItem = chatFrame.getByRole('menuitem', { name: '添加到上下文', exact: true })
      await menuItem.waitFor()
      // Let the real menu focus trap activate before choosing the command.
      await page.waitForTimeout(350)
      if (interaction === 'keyboard') {
        await menuItem.focus()
        await page.keyboard.press('Enter')
      } else await menuItem.click()
      await menuItem.waitFor({ state: 'hidden' })
      await page.waitForTimeout(350)
      assert.equal(await input.evaluate(el => el === document.activeElement), true, `${interaction}: focus must remain in the composer after menu dismissal`)
      await page.keyboard.insertText(interaction)
      assert.equal(await draftText(), interaction)
      await input.fill('')
    }
    await chatFrame.getByRole('button', { name: '收起工作区文件', exact: true }).click()
    await chatFrame.getByRole('button', { name: '移除workspace.txt', exact: true }).click()
    await selectSkill('本轮技能')
    const checkEmptyCaretSpacing = async () => {
      assert.equal(await draftText(), '', 'The spacing must not add characters to the draft')
      const spacing = await input.evaluate(editor => {
        const tags = editor.querySelectorAll('.composer-reference')
        const tag = tags[tags.length - 1].getBoundingClientRect()
        const spacer = editor.querySelector('.composer-reference-spacer').getBoundingClientRect()
        const selection = window.getSelection()
        const anchor = selection.anchorNode
        const preceding = anchor.nodeType === Node.ELEMENT_NODE ? anchor.childNodes[selection.anchorOffset - 1] : null
        return { gap: spacer.right - tag.right, afterWidget: preceding?.classList?.contains('composer-reference-prefix') }
      })
      assert(spacing.gap >= 11, 'Empty drafts must retain a real gap after the last reference')
      assert.equal(spacing.afterWidget, true, 'The native caret must be placed after the widget including its spacer')
    }
    await checkEmptyCaretSpacing()
    await attachDocument('caret.txt')
    await checkEmptyCaretSpacing()
    await page.screenshot({ path: path.join(output, `empty-reference-caret-${viewport.width}.png`), animations: 'disabled', caret: 'initial' })
    await chatFrame.getByRole('button', { name: '移除caret.txt', exact: true }).click()
    await page.keyboard.insertText('After skill')
    const caretGap = await input.evaluate(editor => {
      const tag = editor.querySelector('.composer-reference').getBoundingClientRect()
      const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT)
      while (walker.nextNode()) {
        if (walker.currentNode.textContent !== 'After skill') continue
        const range = document.createRange()
        range.setStart(walker.currentNode, 0)
        range.setEnd(walker.currentNode, 1)
        return range.getBoundingClientRect().left - tag.right
      }
    })
    assert(caretGap >= 11, 'Text and caret need visible space after the skill tag')
    await attachDocument('notes.txt')
    await input.fill('这个规范说的什么内容'.repeat(18))
    const wrapping = await input.evaluate(editor => {
      const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT)
      const rectangles = []
      while (walker.nextNode()) {
        const node = walker.currentNode
        if (node.parentElement.closest('.composer-reference-prefix, .cm-widgetBuffer')) continue
        for (let offset = 0; offset < node.length; offset++) {
          const range = document.createRange()
          range.setStart(node, offset)
          range.setEnd(node, offset + 1)
          rectangles.push(range.getBoundingClientRect())
        }
      }
      const row = editor.querySelector('.cm-line')
      const style = getComputedStyle(row)
      return { first: rectangles[0].left, second: rectangles.find(rect => rect.top > rectangles[0].top + 5)?.left,
        start: row.getBoundingClientRect().left + parseFloat(style.paddingLeft) }
    })
    assert(wrapping.first > wrapping.start + 50, 'First line must follow the reference tags')
    assert(Math.abs(wrapping.second - wrapping.start) < 2, 'Wrapped text must reclaim the full width below references')
    await input.evaluate(editor => { editor.closest('.cm-scroller').scrollTop = 0 })
    await page.screenshot({ path: path.join(output, `reference-wrapping-${viewport.width}.png`) })
    await input.fill('First line')
    await input.press('Control+End')
    await input.press('Shift+Enter')
    await input.pressSequentially('Second line')
    assert.equal(await draftText(), 'First line\nSecond line', 'Manual newlines must remain part of the draft')
    await input.press(process.platform === 'darwin' ? 'Meta+z' : 'Control+z')
    assert.notEqual(await draftText(), 'First line\nSecond line', 'Typing must be undoable')
    await input.press(process.platform === 'darwin' ? 'Meta+Shift+z' : 'Control+y')
    assert.equal(await draftText(), 'First line\nSecond line', 'Redo must restore the draft')
    const beforeComposition = sent.length
    await input.dispatchEvent('compositionstart')
    await input.dispatchEvent('keydown', { key: 'Enter', code: 'Enter', isComposing: true, keyCode: 229 })
    await input.dispatchEvent('compositionend')
    assert.equal(sent.length, beforeComposition, 'Confirming Chinese composition must not submit')
    await input.fill('Use these references for this turn')
    await input.press('Control+Home')
    await input.press('Backspace')
    assert.equal(await draftText(), 'Use these references for this turn', 'Removing a reference must preserve the draft')
    assert.equal(await chatFrame.locator('.composer-surface .context-chip.file').count(), 0)
    assert.equal(await chatFrame.locator('.composer-surface .context-chip.skill').count(), 1)
    await attachDocument('notes.txt')
    const inlineBounds = await chatFrame.locator('.composer-reference').evaluateAll(chips => chips.map(chip => {
      const bounds = chip.getBoundingClientRect()
      const composer = chip.closest('.composer-surface').getBoundingClientRect()
      return bounds.left >= composer.left && bounds.right <= composer.right && bounds.top >= composer.top
    }))
    assert(inlineBounds.every(Boolean), 'Inline references must fit within the composer')
    await page.screenshot({ path: path.join(output, `inline-references-${viewport.width}.png`) })
    await chatFrame.evaluate(() => { window.holdChatStream = true })
    await send.click()
    await chatFrame.waitForFunction(() => document.querySelectorAll('.context-chip').length === 0)
    assert.equal(await send.count(), 0, 'Skills and documents must clear as soon as the message is queued')
    assert.equal(sent.at(-1).skill_id, 11)
    assert.deepEqual(sent.at(-1).attached_files, ['notes.txt'])
    assert.equal(await chatFrame.locator('.user-bubble').last().locator('.message-reference.skill').textContent(), '本轮技能')
    assert.equal(await chatFrame.locator('.user-bubble').last().locator('.message-reference.file').textContent(), 'notes.txt')
    await chatFrame.evaluate(() => window.finishChatStream())
    await send.waitFor()
    assert.equal(sent.at(-1).skill_id, 11)
    assert.deepEqual(sent.at(-1).attached_files, ['notes.txt'])
    assert.equal(await chatFrame.locator('.context-chip').count(), 0)

    await input.fill('Next turn without references')
    await send.click()
    await send.waitFor()
    assert.equal(sent.at(-1).skill_id, null)
    assert.deepEqual(sent.at(-1).attached_files, [])

    failSend = true
    await selectSkill('本轮技能')
    await attachDocument('retry.txt')
    await input.fill('Retryable request')
    await send.click()
    await send.waitFor()
    assert.equal(await chatFrame.locator('.context-chip').count(), 2, 'Failed requests retain references for retry')
    failSend = false
    await send.click()
    await send.waitFor()
    assert.equal(sent.at(-1).skill_id, 11)
    assert.deepEqual(sent.at(-1).attached_files, ['retry.txt'])
    assert.equal(await chatFrame.locator('.context-chip').count(), 0)

    let releaseResponse
    responseGate = new Promise(resolve => { releaseResponse = resolve })
    await selectSkill('本轮技能')
    await attachDocument('previous.txt')
    await input.fill('Finish after switching conversations')
    const pendingRequest = page.waitForRequest(request => request.url().endsWith('/agents/1/messages') && request.method() === 'POST')
    await send.click()
    await pendingRequest
    await chatFrame.getByRole('button', { name: '新对话', exact: true }).click()
    await selectSkill('下轮技能')
    await input.press(process.platform === 'darwin' ? 'Meta+z' : 'Control+z')
    assert.equal(await draftText(), '', 'A new conversation must not undo into a previous draft')
    await attachDocument('next.txt')
    const finishedResponse = page.waitForResponse(response => response.url().endsWith('/agents/1/messages'))
    releaseResponse()
    await finishedResponse
    responseGate = null
    await input.fill('New conversation retains its own references')
    await chatFrame.waitForFunction(() => !document.querySelector('button[aria-label="发送"]').disabled)
    assert.equal(await chatFrame.locator('.context-chip').count(), 2, 'Old runs must not clear the new conversation references')
    await send.click()
    await send.waitFor()
    assert.equal(sent.at(-1).skill_id, 12)
    assert.deepEqual(sent.at(-1).attached_files, ['next.txt'])
    assert.equal(await chatFrame.locator('.context-chip').count(), 0)
    assert.deepEqual(errors, [])
    await openChat('?session=3')
    await chatFrame.locator('.message-reference.skill').last().waitFor()
    assert.equal(await chatFrame.locator('.user-bubble').last().locator('.message-reference.skill').textContent(), '下轮技能')
    assert.equal(await chatFrame.locator('.user-bubble').last().locator('.message-reference.file').textContent(), 'next.txt')
    await page.screenshot({ path: path.join(output, `reference-history-${viewport.width}.png`) })
    await context.close()
  }
  console.log('Image paste browser checks passed at desktop and mobile sizes')
} finally {
  await browser.close()
}

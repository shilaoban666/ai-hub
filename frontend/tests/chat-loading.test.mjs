import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'

const { descriptor } = parse(readFileSync(
  new URL('../src/views/admin/components/ChatMain.vue', import.meta.url), 'utf8',
))
const { scriptSetupAst } = compileScript(descriptor, { id: 'chat-loading' })
const declaration = scriptSetupAst.filter(node => node.type === 'VariableDeclaration')
  .flatMap(node => node.declarations).find(node => node.id.name === 'handleComposerEnter')
const source = descriptor.scriptSetup.content.slice(declaration.init.start, declaration.init.end)

function composer(props) {
  const emitted = []
  const input = { value: 'Draft for the selected conversation' }
  const uploading = { value: 0 }
  const hasContent = { value: true }
  const onEnter = new Function('props', 'inputText', 'emit', 'uploadingFiles', 'hasSendContent', 'referenceMenuVisible', `return (${source})`)(
    props, input, (...args) => emitted.push(args), uploading, hasContent, { value: false },
  )
  return { onEnter, emitted, input, uploading, hasContent }
}

test('loading history blocks Enter without discarding the draft', () => {
  const { onEnter, emitted, input } = composer({ historyLoading: true, sendLocked: false, streaming: false })
  onEnter({ preventDefault() {} })
  assert.deepEqual(emitted, [])
  assert.equal(input.value, 'Draft for the selected conversation')
})

test('sending resumes when history loading finishes', () => {
  const props = { historyLoading: true, sendLocked: false, streaming: false }
  const { onEnter, emitted } = composer(props)
  onEnter({ preventDefault() {} })
  props.historyLoading = false
  onEnter({ preventDefault() {} })
  assert.deepEqual(emitted, [['send']])
})

test('confirming IME composition still does not send a message', () => {
  const { onEnter, emitted } = composer({ historyLoading: false, sendLocked: false, streaming: false })
  onEnter({ isComposing: true, preventDefault() { assert.fail('Do not interrupt IME') } })
  assert.deepEqual(emitted, [])
})

test('pending uploads block Enter until image content is ready', () => {
  const { onEnter, emitted, input, uploading } = composer({ historyLoading: false, sendLocked: false, streaming: false })
  input.value = ''
  uploading.value = 2
  onEnter({ preventDefault() {} })
  assert.deepEqual(emitted, [])
  uploading.value = 0
  onEnter({ preventDefault() {} })
  assert.deepEqual(emitted, [['send']])
})

test('empty input without attachments cannot send', () => {
  const { onEnter, emitted, hasContent } = composer({ historyLoading: false, sendLocked: false, streaming: false })
  hasContent.value = false
  onEnter({ preventDefault() {} })
  assert.deepEqual(emitted, [])
})

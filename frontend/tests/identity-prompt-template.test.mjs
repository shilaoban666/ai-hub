import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import { computed, reactive, ref } from 'vue'

const { descriptor } = parse(readFileSync(new URL('../src/components/IdentityPromptTemplatePicker.vue', import.meta.url), 'utf8'))
const { scriptSetupAst } = compileScript(descriptor, { id: 'identity-prompt-template' })
let source = descriptor.scriptSetup.content
for (const node of [...scriptSetupAst].reverse()) {
  if (node.type === 'ImportDeclaration') source = source.slice(0, node.start) + source.slice(node.end)
}

function editor(items = []) {
  const props = reactive({ modelValue: 'Existing system prompt', disabled: false })
  const messages = []
  const writes = []
  const requests = []
  const api = { getUsable: async params => { requests.push(params); return { items } } }
  const scope = {
    computed, ref, defineProps: () => props,
    defineEmits: () => (event, value) => { writes.push(value); props.modelValue = value },
    useAuthStore: () => ({ user: { id: 7 } }),
    onMounted: () => {}, promptTemplatesApi: api,
    ElMessage: Object.fromEntries(['info', 'warning'].map(kind => [kind, value => messages.push([kind, value])])),
  }
  const state = new Function(...Object.keys(scope), `${source}\nreturn { loadTemplates, usableTemplates, appliedTemplateId, handleApplyTemplate, varDialogVisible, varForm, confirmVariables, cancelVariables, loadError, loading, templateSourceLabel }`)(...Object.values(scope))
  return { ...state, props, messages, writes, requests, api }
}

test('identity editor lists personal and public templates, with consistent source labels', async () => {
  const state = editor([{ id: 1, user_id: '7', is_public: false }, { id: 2, user_id: 8, is_public: true }, { id: 3, is_system: true }])
  await state.loadTemplates()
  assert.deepEqual(state.requests, [{ limit: 200, include_system: false }])
  assert.deepEqual(state.usableTemplates.value.map(t => t.id), [1, 2])
  assert.deepEqual(state.usableTemplates.value.map(state.templateSourceLabel), ['我的', '公开'])
})

test('selecting a plain identity template replaces the prompt; clearing keeps it intact', async () => {
  const state = editor([{ id: 1, content: 'New identity', variables: null }])
  await state.loadTemplates()
  state.handleApplyTemplate(1)
  assert.deepEqual(state.writes, ['New identity'])
  assert.equal(state.varDialogVisible.value, false)
  state.handleApplyTemplate(null)
  assert.equal(state.props.modelValue, 'New identity')
  assert.equal(state.writes.length, 1)
})

test('variable templates wait for confirmation and preserve zero and false defaults', async () => {
  const state = editor([{ id: 1, content: 'Help {{topic}}; limit {{limit}}; enabled {{enabled}}', variables: JSON.stringify([{ name: 'topic', required: true }, { name: 'limit', default: 0 }, { name: 'enabled', default: false }]) }])
  await state.loadTemplates()
  state.handleApplyTemplate(1)
  assert.equal(state.varDialogVisible.value, true)
  assert.equal(state.writes.length, 0)
  state.varForm.value.topic = '  '
  state.confirmVariables()
  assert.deepEqual(state.messages, [['warning', '请填写变量：topic']])
  assert.equal(state.writes.length, 0)
  state.varForm.value.topic = 'inventory'
  state.confirmVariables()
  assert.deepEqual(state.writes, ['Help inventory; limit 0; enabled false'])
  assert.equal(state.varDialogVisible.value, false)
})

test('canceling variables preserves the edited prompt and resets the selector', async () => {
  const state = editor([{ id: 1, content: '{{topic}}', variables: '[{"name":"topic"}]' }])
  await state.loadTemplates()
  state.appliedTemplateId.value = 1
  state.handleApplyTemplate(1)
  state.varForm.value.topic = 'discarded'
  state.cancelVariables()
  assert.equal(state.props.modelValue, 'Existing system prompt')
  assert.equal(state.appliedTemplateId.value, null)
  assert.equal(state.varDialogVisible.value, false)
  assert.equal(state.writes.length, 0)
})

test('read-only identity settings cannot apply or confirm a template', async () => {
  const state = editor([{ id: 1, content: '{{topic}}', variables: '[{"name":"topic"}]' }])
  await state.loadTemplates()
  state.props.disabled = true
  state.handleApplyTemplate(1)
  assert.equal(state.varDialogVisible.value, false)
  state.props.disabled = false
  state.handleApplyTemplate(1)
  state.props.disabled = true
  state.confirmVariables()
  assert.equal(state.writes.length, 0)
})

test('optional template loading failures leave the prompt intact and allow retry', async () => {
  const state = editor([{ id: 1, content: 'Retry' }])
  const getUsable = state.api.getUsable
  state.api.getUsable = async () => { throw new Error('offline') }
  await state.loadTemplates()
  assert.equal(state.loadError.value, true)
  assert.equal(state.loading.value, false)
  assert.equal(state.props.modelValue, 'Existing system prompt')
  assert.deepEqual(state.writes, [])
  state.api.getUsable = getUsable
  await state.loadTemplates()
  assert.equal(state.loadError.value, false)
  assert.equal(state.usableTemplates.value.length, 1)
})

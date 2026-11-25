import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import { computed, effectScope, nextTick, reactive, ref, watch } from 'vue'
import * as modelConfig from '../src/config/models.js'
import { DEFAULT_NOUN_EXPLANATION_URL, nounExplanationLink } from '../src/utils/noun-highlight.js'

const { descriptor } = parse(readFileSync(
  new URL('../src/views/admin/AgentDetail.vue', import.meta.url), 'utf8',
))
const { scriptSetupAst } = compileScript(descriptor, { id: 'agent-detail-models-test' })
let source = descriptor.scriptSetup.content
for (const node of [...scriptSetupAst].reverse()) {
  if (node.type === 'ImportDeclaration') source = source.slice(0, node.start) + source.slice(node.end)
}

const models = [
  { id: 1, name: 'Anthropic', api_protocol: 'anthropic-messages', scope: 'platform' },
  { id: 2, name: 'OpenAI', api_protocol: 'openai-completions', scope: 'user' },
]

function editor(runtime, isEdit, catalog = models, options = {}) {
  const effects = effectScope()
  const messages = []
  const writes = []
  const confirmations = []
  const agent = { id: 9, name: 'Demo', runtime_type: runtime, default_model_id: 1, models: catalog }
  const scope = {
    ref, reactive, computed,
    // Drive loading explicitly while retaining the component's reactive watchers.
    watch: (input, callback, options) => watch(input, callback, { ...options, immediate: false }),
    inject: () => null, useRoute: () => ({ params: isEdit ? { id: 9 } : {}, query: {} }),
    useRouter: () => ({ replace() {} }), useAuthStore: () => ({ user: { id: 7 } }),
    ElMessage: Object.fromEntries(['warning', 'error', 'success'].map(kind => [kind, text => messages.push([kind, text])])),
    ElMessageBox: { confirm: async message => {
      confirmations.push(message)
      if (options.cancel) throw 'cancel'
    } },
    promptTemplatesApi: { getUsable: async () => ({ items: [] }) },
    enterpriseApi: { getAgentRuntimeSettings: async () => ({ runtime_type: runtime }) },
    api: {
      get: async path => path === '/models' ? { items: catalog } : agent,
      put: async (path, payload) => {
        writes.push(payload)
        if (writes.length === 1 && options.error) throw options.error
        return { ...agent, ...payload }
      },
      post: async (path, payload) => { writes.push(payload); return { ...agent, ...payload } },
    },
    ...modelConfig,
    DEFAULT_NOUN_EXPLANATION_URL, nounExplanationLink,
  }
  const state = effects.run(() => new Function(...Object.keys(scope),
    `${source}\nreturn { form, fetchData, handleSave, compatibleModels }`)(...Object.values(scope)))
  assert.equal(state.form.noun_explanation_url, DEFAULT_NOUN_EXPLANATION_URL)
  return { ...state, messages, writes, confirmations, stop: () => effects.stop() }
}

for (const runtime of ['claude_code']) {
  for (const isEdit of [true, false]) {
    test(`${isEdit ? 'existing' : 'new'} ${runtime} agent loads mixed catalog without removal warnings`, async () => {
      const state = editor(runtime, isEdit)
      try {
        for (let i = 0; i < 2; i++) {
          await state.fetchData()
          await nextTick()
          assert.equal(state.form.default_model_id, 1)
          assert.deepEqual(state.compatibleModels.value.map(model => model.id), [1])
          assert.deepEqual(state.messages, [])
        }
        state.form.name = 'Updated'
        state.form.default_model_id = 1
        await state.handleSave()
        assert.equal(state.writes.length, 1)
        assert.equal(state.writes[0].default_model_id, state.form.default_model_id)
        assert.equal(Object.hasOwn(state.writes[0], 'model_ids'), false)
      } finally { state.stop() }
    })
  }
}

test('creating an agent without compatible models leaves the default empty without warnings', async () => {
  const state = editor('claude_code', false, [models[1]])
  try {
    await state.fetchData()
    await nextTick()
    assert.equal(state.form.default_model_id, null)
    assert.deepEqual(state.compatibleModels.value, [])
    assert.deepEqual(state.messages, [])
  } finally { state.stop() }
})

for (const standardEnvelope of [true, false]) {
  test(`runtime switch confirms and retries with the target (${standardEnvelope ? 'standard' : 'FastAPI'} error)`, async () => {
    const data = { code: 'RUNTIME_CHANGE_CONFIRMATION_REQUIRED', target_runtime: 'claude_code' }
    const state = editor('claude_code', true, models, { error: {
      response: { status: 409, data: standardEnvelope ? { data } : { detail: { data } } },
    } })
    try {
      await state.fetchData()
      state.form.name = 'Updated'
      await state.handleSave()
      assert.equal(state.confirmations.length, 1)
      assert.match(state.confirmations[0], /强制终止.*其他用户.*清空工作区文件.*未完成的输出将丢失/)
      assert.equal(state.writes.length, 2)
      assert.equal(state.writes[0].confirm_runtime_change, undefined)
      assert.equal(state.writes[1].confirm_runtime_change, 'claude_code')
      assert.equal(state.writes[1].name, 'Updated')
      assert.deepEqual(state.messages, [['success', '已保存']])
    } finally { state.stop() }
  })
}

test('cancelling a runtime switch sends no confirmed update and displays no save error', async () => {
  const state = editor('claude_code', true, models, { cancel: true, error: {
    response: { status: 409, data: { data: {
      code: 'RUNTIME_CHANGE_CONFIRMATION_REQUIRED', target_runtime: 'claude_code',
    } } },
  } })
  try {
    await state.fetchData()
    await state.handleSave()
    assert.equal(state.confirmations.length, 1)
    assert.equal(state.writes.length, 1)
    assert.deepEqual(state.messages, [])
  } finally { state.stop() }
})

test('unrelated save conflicts show their message without requesting runtime confirmation', async () => {
  const state = editor('claude_code', true, models, { error: {
    response: { status: 409, data: { detail: { message: '工作区正在使用中' } } },
  } })
  try {
    await state.fetchData()
    await state.handleSave()
    assert.deepEqual(state.confirmations, [])
    assert.equal(state.writes.length, 1)
    assert.deepEqual(state.messages, [['error', '保存失败：工作区正在使用中']])
  } finally { state.stop() }
})

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import { ref } from 'vue'

const { descriptor } = parse(readFileSync(
  new URL('../src/views/admin/McpDetail.vue', import.meta.url), 'utf8',
))
const { scriptSetupAst } = compileScript(descriptor, { id: 'mcp-detail-config-test' })
const declarations = scriptSetupAst.filter(node => node.type === 'VariableDeclaration')
  .flatMap(node => node.declarations)

function handler(name, state) {
  const declaration = declarations.find(node => node.id.name === name)
  const source = descriptor.scriptSetup.content.slice(declaration.init.start, declaration.init.end)
  return new Function(...Object.keys(state), `return (${source})`)(...Object.values(state))
}

function setup(headers = { 'X-Example': 'saved-value' }) {
  const record = {
    id: 1, type: 'streamable_http', name: 'example',
    config: JSON.stringify({ url: 'https://example.com/mcp', headers }),
  }
  const updates = []
  const state = {
    configForm: ref({ type: '', command: '', args: [], env: [], url: '', headers: [], jsonText: '' }),
    savedConfigForm: ref(null), revealedHeaderKeys: ref([]), mcp: ref({}),
    isEditingConfig: ref(false), savingConfig: ref(false), loading: ref(false), editInstructions: ref(''),
    route: { params: { id: 1 } }, ElMessage: { success() {}, error() {} },
    mcpsApi: {
      async getDetail() { return structuredClone(record) },
      async update(id, data) {
        updates.push(data)
        Object.assign(record, data)
        return structuredClone(record)
      },
    },
  }
  for (const name of ['parseConfig', 'cloneConfigForm', 'restoreConfigForm', 'serializeConfig',
    'fetchDetail', 'toggleEditConfig', 'handleCancelConfig', 'handleSaveConfig']) {
    state[name] = handler(name, state)
  }
  return { state, updates }
}

test('saved headers are available immediately after loading, before opening edit', async () => {
  const { state, updates } = setup()
  await state.fetchDetail()
  assert.equal(state.isEditingConfig.value, false)
  assert.deepEqual(state.savedConfigForm.value.headers, [{ key: 'X-Example', value: 'saved-value' }])
  state.toggleEditConfig()
  assert.deepEqual(state.configForm.value.headers, state.savedConfigForm.value.headers)
  assert.equal(updates.length, 0)
})

test('editing or autofilling an empty header cannot change the saved display; cancel discards it', async () => {
  const { state, updates } = setup({})
  await state.fetchDetail()
  state.toggleEditConfig()
  state.configForm.value.headers[0] = { key: 'Authorization', value: 'draft-only' }
  assert.equal(state.savedConfigForm.value.headers.filter(item => item.key).length, 0)
  state.handleCancelConfig()
  state.toggleEditConfig()
  assert.deepEqual(state.configForm.value.headers, [{ key: '', value: '' }])
  assert.equal(updates.length, 0)
})

test('successful save updates the display and survives a fresh load', async () => {
  const { state } = setup()
  await state.fetchDetail()
  state.toggleEditConfig()
  state.configForm.value.headers.push({ key: 'X-New', value: 'new-value' })
  await state.handleSaveConfig()
  assert.equal(state.isEditingConfig.value, false)
  assert.deepEqual(state.savedConfigForm.value.headers.map(item => item.key), ['X-Example', 'X-New'])
  await state.fetchDetail()
  assert.deepEqual(state.savedConfigForm.value.headers.map(item => item.key), ['X-Example', 'X-New'])
})

test('failed save preserves the draft without changing the saved display', async () => {
  const { state } = setup()
  await state.fetchDetail()
  state.mcpsApi.update = async () => { throw new Error('test failure') }
  state.toggleEditConfig()
  state.configForm.value.headers[0].value = 'draft-only'
  await state.handleSaveConfig()
  assert.equal(state.isEditingConfig.value, true)
  assert.equal(state.savingConfig.value, false)
  assert.equal(state.configForm.value.headers[0].value, 'draft-only')
  assert.equal(state.savedConfigForm.value.headers[0].value, 'saved-value')
})

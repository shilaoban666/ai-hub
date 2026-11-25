import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'

const { descriptor } = parse(readFileSync(
  new URL('../src/views/admin/AssetCenter.vue', import.meta.url), 'utf8',
))
const { scriptSetupAst } = compileScript(descriptor, { id: 'system-resource-picker' })
const pickerFunction = (name, dependencies = {}) => {
  const node = scriptSetupAst.filter(node => node.type === 'VariableDeclaration')
    .flatMap(node => node.declarations).find(node => node.id.name === name)
  const code = descriptor.scriptSetup.content.slice(node.init.start, node.init.end)
  return new Function(...Object.keys(dependencies), `return (${code})`)(...Object.values(dependencies))
}
const objectKeys = pickerFunction('objectKeys')
const normalizedMcpPickerConfig = pickerFunction('normalizedMcpPickerConfig', { objectKeys })
const secretFields = pickerFunction('mcpSecretFields', { objectKeys, normalizedMcpPickerConfig })

for (const [config, expected] of [
  [{ type: 'streamable-http', url: 'https://example.com/mcp', headers: { Authorization: 'source-secret' } },
    [{ kind: 'headers', kindLabel: '请求头', name: 'Authorization' }]],
  [{ command: 'node', env: { API_KEY: 'source-key' } },
    [{ kind: 'env', kindLabel: '环境变量', name: 'API_KEY' }]],
]) {
  for (const wrapped of [false, true]) {
    test(`JSON connector discovers ${expected[0].kind} in ${wrapped ? 'wrapped' : 'direct'} config`, () => {
      assert.deepEqual(secretFields(wrapped ? { mcpServers: { example: config } } : config, 'json'), expected)
    })
  }
}

test('JSON connector refuses ambiguous or invalid server wrappers', () => {
  for (const servers of [{}, { one: {}, two: {} }, { one: null }, []]) {
    assert.throws(() => secretFields({ mcpServers: servers }, 'json'), /JSON MCP/)
  }
})

test('connection authentication defaults to manual and marks only owned saved headers as configured', async () => {
  const dialog = {}
  const request = pickerFunction('requestImportHeaders', { importHeaderDialog: dialog })
  const fields = [{ kind: 'headers', name: 'Authorization' }, { kind: 'headers', name: 'X-Tenant' }]
  const pending = request('Example', fields, { Authorization: 'owner-secret' })
  assert.equal(dialog.authMode, 'manual')
  assert.equal(dialog.kind, 'headers')
  assert.deepEqual(dialog.rows.map(row => [row.name, row.value, row.configured]), [
    ['Authorization', '', true], ['X-Tenant', '', false],
  ])
  dialog.resolve(null)
  await pending
  const publicPending = request('Public', fields)
  assert(dialog.rows.every(row => !row.configured && row.value === ''))
  dialog.resolve(null)
  await publicPending
})

test('connection authentication preserves owned headers, applies edits, and clears temporary values', () => {
  for (const replacement of ['', 'replacement']) {
    const result = []
    const dialog = {
      open: true, kind: 'headers', authMode: 'manual', savedHeaders: { Authorization: 'owner-secret' },
      rows: [{ name: 'Authorization', value: replacement, configured: true }],
      authorizationRows: [], resolve: value => result.push(value),
    }
    const finish = pickerFunction('finishImportHeaders', { importHeaderDialog: dialog })
    const save = pickerFunction('saveImportHeaders', {
      importHeaderDialog: dialog, finishImportHeaders: finish,
      headerPayload: pickerFunction('headerPayload'), ElMessage: { warning: message => assert.fail(message) },
    })
    save()
    assert.deepEqual(result, [{ secrets: { headers: { Authorization: replacement || 'owner-secret' } }, authMode: 'manual' }])
    assert.equal(dialog.open, false)
    assert.deepEqual(dialog.savedHeaders, {})
    assert.deepEqual(dialog.rows, [])
  }
})

test('switching authentication hides Authorization, restores it on manual, and retains other headers', () => {
  const auth = { name: 'Authorization', value: 'Bearer own' }
  const tenant = { name: 'X-Tenant', value: 'tenant' }
  const dialog = { rows: [auth, tenant], authorizationRows: [] }
  const change = pickerFunction('handleImportAuthModeChange', { importHeaderDialog: dialog })
  change('none')
  assert.deepEqual(dialog.rows, [tenant])
  change('current_user')
  assert.deepEqual(dialog.rows, [tenant])
  change('manual')
  assert.deepEqual(dialog.rows, [tenant, auth])
  assert.deepEqual(dialog.authorizationRows, [])
})

for (const selectedSource of ['mine', 'public']) {
  test(`adding ${selectedSource} connector from all resources reads details through the correct API`, async () => {
    const importDeclaration = scriptSetupAst.filter(node => node.type === 'VariableDeclaration')
      .flatMap(node => node.declarations).find(node => node.id.name === 'importSelectedMcp')
    const importSource = descriptor.scriptSetup.content.slice(importDeclaration.init.start, importDeclaration.init.end)
    const calls = []
    const selected = { id: 7, name: 'Example', type: 'http', picker_source: selectedSource }
    const api = origin => ({ getDetail: async id => {
      calls.push(['detail', origin, id])
      return { id, config: '{}' }
    } })
    const picker = { source: 'all', selected }
    const state = {
      props: { readOnly: false }, systemMode: { value: false }, agentId: { value: null },
      mcpPicker: picker, mcpsApi: api('mine'), publicMcpsApi: api('public'),
      parseMcpConfig: JSON.parse, mcpSecretFields: () => [],
      assetsApi: { installMcp: async (...args) => calls.push(['install', ...args]) },
      ElMessage: { success() {}, error: message => assert.fail(message) },
      requestErrorMessage: error => error.message,
      loadAll: async () => calls.push(['reload']),
    }
    const add = new Function(...Object.keys(state), `return (${importSource})`)(...Object.values(state))
    await add()
    assert.deepEqual(calls, [['detail', selectedSource, 7], ['install', 7, undefined, {}, 'manual'], ['reload']])
    assert.equal(picker.importing, false)
  })
}

test('adding a wrapped JSON connector asks for destination headers before installing', async () => {
  const selected = { id: 7, name: 'Example', type: 'json', picker_source: 'mine' }
  const picker = { source: 'all', selected }
  const calls = []
  const destination = { headers: { Authorization: 'Bearer destination-secret' } }
  const add = pickerFunction('importSelectedMcp', {
    props: { readOnly: false }, systemMode: { value: false }, agentId: { value: null },
    mcpPicker: picker,
    mcpsApi: { getDetail: async () => ({ config: JSON.stringify({ mcpServers: { example: {
      url: 'https://example.com/mcp', headers: { Authorization: 'Bearer source-secret' },
    } } }) }) },
    publicMcpsApi: {}, parseMcpConfig: JSON.parse, mcpSecretFields: secretFields, normalizedMcpPickerConfig,
    requestImportHeaders: async (name, fields) => {
      calls.push(['authenticate', name, fields])
      return { secrets: destination, authMode: 'manual' }
    },
    assetsApi: { installMcp: async (...args) => calls.push(['install', ...args]) },
    ElMessage: { success() {}, error: message => assert.fail(message) },
    requestErrorMessage: error => error.message,
    loadAll: async () => calls.push(['reload']),
  })
  await add()
  assert.deepEqual(calls, [
    ['authenticate', 'Example', [{ kind: 'headers', kindLabel: '请求头', name: 'Authorization' }]],
    ['install', 7, undefined, destination, 'manual'], ['reload'],
  ])
  assert.equal(picker.importing, false)
})

test('system connector import sends the source ID without copying public display config', async () => {
  const selected = { id: 7, name: '合趣知识库', type: 'streamable_http' }
  const picker = { source: 'public', selected }
  const calls = []
  const add = pickerFunction('importSelectedMcp', {
    props: { readOnly: false }, systemMode: { value: true }, mcpPicker: picker,
    publicMcpsApi: { getDetail: async () => ({ config: JSON.stringify({ url: 'https://example.com/REDACTED' }) }) },
    parseMcpConfig: JSON.parse, mcpSecretFields: secretFields,
    assetsApi: { createSystemMcpDefinition: async data => calls.push(data) },
    ElMessage: { success() {}, error: message => assert.fail(message) },
    requestErrorMessage: error => error.message, loadAll: async () => {},
  })
  await add()
  assert.deepEqual(calls, [{
    source_mcp_service_id: 7, name: '合趣知识库', description: null,
    transport_type: 'streamable_http', config: {}, auth_mode: 'manual',
  }])
  assert.equal(picker.importing, false)
})

for (const values of [{ headers: { Authorization: '123123' } }, null]) {
  test(`system connector import ${values ? 'saves entered authentication with the source ID' : 'cancels without creating a connector'}`, async () => {
    const selected = { id: 7, name: '合趣知识库', type: 'json' }
    const picker = { source: 'public', selected }
    const calls = []
    const add = pickerFunction('importSelectedMcp', {
      props: { readOnly: false }, systemMode: { value: true }, mcpPicker: picker,
      publicMcpsApi: { getDetail: async () => ({ config: JSON.stringify({ mcpServers: { example: {
        type: 'streamable-http', url: 'https://example.com/REDACTED', headers: { Authorization: '隐藏' },
      } } }) }) },
      parseMcpConfig: JSON.parse, mcpSecretFields: secretFields,
      requestImportHeaders: async (name, fields) => {
        assert.equal(name, '合趣知识库')
        assert.deepEqual(fields, [{ kind: 'headers', kindLabel: '请求头', name: 'Authorization' }])
        return values === null ? null : { secrets: values, authMode: 'manual' }
      },
      assetsApi: { createSystemMcpDefinition: async data => calls.push(data) },
      ElMessage: { success() {}, error: message => assert.fail(message) },
      requestErrorMessage: error => error.message, loadAll: async () => {},
    })
    await add()
    assert.deepEqual(calls, values ? [{
      source_mcp_service_id: 7, name: '合趣知识库', description: null,
      transport_type: 'json', config: {}, ...values, auth_mode: 'manual',
    }] : [])
    assert.equal(picker.importing, false)
  })
}

test('switching agents while connector details load never connects to the new agent', async () => {
  const agentId = { value: 99 }
  const picker = { selected: { id: 7, name: 'Knowledge', type: 'http', picker_source: 'mine' } }
  const add = pickerFunction('importSelectedMcp', {
    props: { readOnly: false }, systemMode: { value: false }, agentId, mcpPicker: picker,
    mcpsApi: { getDetail: async () => {
      agentId.value = 100
      return { config: '{}' }
    } },
    publicMcpsApi: {}, parseMcpConfig: JSON.parse, mcpSecretFields: () => [],
    assetsApi: { installMcp: () => assert.fail('The original agent scope has changed') },
    ElMessage: { error: message => assert.fail(message) }, requestErrorMessage: error => error.message,
  })
  await add()
  assert.equal(picker.importing, false)
})

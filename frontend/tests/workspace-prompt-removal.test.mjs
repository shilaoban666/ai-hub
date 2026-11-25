import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'

const { descriptor } = parse(readFileSync(
  new URL('../src/views/admin/components/PromptCatalogPanel.vue', import.meta.url), 'utf8',
))
const { scriptSetupAst } = compileScript(descriptor, { id: 'workspace-prompt-removal' })
const declaration = scriptSetupAst.filter(node => node.type === 'VariableDeclaration')
  .flatMap(node => node.declarations).find(node => node.id.name === 'changeInstallation')
const source = descriptor.scriptSetup.content.slice(declaration.init.start, declaration.init.end)

function installationAction(props, assetsApi, refresh, confirm = async () => {}) {
  const state = {
    props,
    assetsApi,
    refresh,
    actionId: { value: null },
    disposed: false,
    isInherited: row => row.is_system && !props.agentId && !props.systemMode,
    textOrNone: value => value,
    ElMessageBox: { confirm },
    ElMessage: { success() {}, error: message => assert.fail(message) },
    errorMessage: error => error.message,
  }
  return new Function(...Object.keys(state), `return (${source})`)(...Object.values(state))
}

for (const scope of ['workspace', 'system', 'agent']) {
  test(`${scope} prompt uninstall uses its own endpoint`, async () => {
    const calls = []
    const change = installationAction({ systemMode: scope === 'system', agentId: scope === 'agent' ? 99 : null }, {
      deleteSystemPrompt: async id => calls.push(['system', id]),
      removeWorkspacePrompt: async id => calls.push(['workspace', id]),
      unbindPrompt: async (id, agentId) => calls.push(['agent', id, agentId]),
    }, async () => calls.push(['reload']))
    await change({ id: 42, name: 'Example', installed: true })
    assert.deepEqual(calls, [scope === 'agent' ? ['agent', 42, 99] : [scope, 42], ['reload']])
  })
}

test('cancelling uninstall sends no deletion request', async () => {
  const change = installationAction({}, {
    removeWorkspacePrompt: async () => assert.fail('Cancelled'),
  }, async () => assert.fail('Cancelled'), async () => { throw 'cancel' })
  await change({ id: 42, name: 'Example', installed: true })
})

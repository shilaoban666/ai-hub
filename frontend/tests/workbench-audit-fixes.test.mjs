import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import { ref } from 'vue'

function expression(file, name) {
  const { descriptor } = parse(readFileSync(new URL(`../src/views/admin/${file}.vue`, import.meta.url), 'utf8'))
  const { scriptSetupAst } = compileScript(descriptor, { id: 'audit-fixes' })
  const declaration = scriptSetupAst.filter(node => node.type === 'VariableDeclaration')
    .flatMap(node => node.declarations).find(node => node.id.name === name)
  return descriptor.scriptSetup.content.slice(declaration.init.start, declaration.init.end)
}

function catalogLoader(getSkillCatalog) {
  const state = {
    assetsApi: { getSkillCatalog }, query: ref(' test '), source: ref('mine'),
    systemMode: ref(false), agentId: ref(9), moduleFilter: ref('订单'), roleFilter: ref('运营'),
    view: ref('installed'), currentPage: ref(2), pageSize: 16, totalSkills: ref(0),
    catalog: ref([]), selectedSkill: ref(null), drawerOpen: ref(false),
  }
  const load = new Function(...Object.keys(state), `let catalogRequestId = 0;
    const loadCatalog = ${expression('components/SkillCatalogPanel', 'loadCatalog')}; return loadCatalog;`)(...Object.values(state))
  return { state, load }
}

test('catalog sends scope and filters before server pagination and uses its total', async () => {
  let params
  const { state, load } = catalogLoader(async value => {
    params = value
    return { total: 40, items: [{ skill_id: 17, user_installation: { id: 4 } }] }
  })
  await load()
  assert.deepEqual(params, { q: 'test', source: 'mine', system_mode: false, agent_id: 9,
    module: '订单', role: '运营', installed_only: true, skip: 16, limit: 16 })
  assert.equal(state.totalSkills.value, 40)
  assert.deepEqual(state.catalog.value.map(item => item.skill_id), [17])
})

test('older catalog response cannot overwrite the latest page or total', async () => {
  const resolve = []
  const { state, load } = catalogLoader(() => new Promise(done => resolve.push(done)))
  const first = load()
  state.currentPage.value = 3
  const second = load()
  resolve[1]({ total: 40, items: [{ skill_id: 33 }] })
  await second
  resolve[0]({ total: 80, items: [{ skill_id: 17 }] })
  await first
  assert.equal(state.totalSkills.value, 40)
  assert.equal(state.catalog.value[0].skill_id, 33)
})

test('removing the last item on a page reloads the new last page', async () => {
  const skips = []
  const { state, load } = catalogLoader(async params => {
    skips.push(params.skip)
    return { total: 16, items: params.skip ? [] : [{ skill_id: 1 }] }
  })
  await load()
  assert.deepEqual(skips, [16, 0])
  assert.equal(state.currentPage.value, 1)
  assert.equal(state.catalog.value[0].skill_id, 1)
})

test('workspace download shows the API size limit from a JSON blob error', async () => {
  const errors = []
  const state = {
    props: { agentId: 7 },
    WORKSPACE_DOWNLOAD_TIMEOUT_MS: 120000,
    api: { get: async () => { throw { response: { status: 413, data: new Blob([
      JSON.stringify({ code: 413, message: '工作区文件下载最大支持 20 MiB' }),
    ]) } } } },
    ElMessage: { error: message => errors.push(message), warning: message => errors.push(message) },
  }
  const download = new Function(...Object.keys(state), `return ${expression('components/WorkspaceTree', 'downloadFile')}`)(...Object.values(state))
  await download({ name: 'test.bin', path: 'test.bin' })
  assert.deepEqual(errors, ['工作区文件下载最大支持 20 MiB'])
  state.api.get = async () => assert.fail('Known oversized files need no request')
  await download({ name: 'large.bin', path: 'large.bin', size: 20 * 1024 * 1024 + 1 })
  assert.equal(errors.length, 2)
})

test('workspace download uses a long timeout and releases the blob URL after navigation starts', async () => {
  let requestConfig
  let revokeCallback
  let revokeDelay
  let revokedUrl
  const link = { click() {}, remove() {} }
  const oldDocument = globalThis.document
  const oldCreateObjectURL = URL.createObjectURL
  const oldRevokeObjectURL = URL.revokeObjectURL
  const oldSetTimeout = globalThis.setTimeout
  globalThis.document = {
    createElement: () => link,
    body: { appendChild() {}, removeChild() {} },
  }
  URL.createObjectURL = () => 'blob:workspace-download'
  URL.revokeObjectURL = value => { revokedUrl = value }
  globalThis.setTimeout = (callback, delay) => {
    revokeCallback = callback
    revokeDelay = delay
    return 1
  }

  try {
    const state = {
      props: { agentId: 7 },
      WORKSPACE_DOWNLOAD_TIMEOUT_MS: 120000,
      api: { get: async (_url, config) => {
        requestConfig = config
        return new Blob(['workbook'])
      } },
      ElMessage: { error: assert.fail, warning: assert.fail },
    }
    const download = new Function(...Object.keys(state), `return ${expression('components/WorkspaceTree', 'downloadFile')}`)(...Object.values(state))
    await download({ name: '采购合同.xlsx', path: '采购合同.xlsx', size: 4_674_554 })

    assert.equal(requestConfig.timeout, 120000)
    assert.equal(revokedUrl, undefined)
    assert.equal(revokeDelay, 1000)
    revokeCallback()
    assert.equal(revokedUrl, 'blob:workspace-download')
  } finally {
    globalThis.document = oldDocument
    URL.createObjectURL = oldCreateObjectURL
    URL.revokeObjectURL = oldRevokeObjectURL
    globalThis.setTimeout = oldSetTimeout
  }
})

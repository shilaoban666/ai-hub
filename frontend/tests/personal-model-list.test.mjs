import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import { ref } from 'vue'

const { descriptor } = parse(readFileSync(
  new URL('../src/views/admin/ModelList.vue', import.meta.url), 'utf8',
))
const { scriptSetupAst } = compileScript(descriptor, { id: 'personal-model-list-test' })
const fetchDeclaration = scriptSetupAst
  .filter(node => node.type === 'VariableDeclaration')
  .flatMap(node => node.declarations)
  .find(node => node.id.name === 'fetchModels')
const source = descriptor.scriptSetup.content.slice(fetchDeclaration.init.start, fetchDeclaration.init.end)

test('custom model management requests only personal models with server pagination and search', async () => {
  const state = {
    loading: ref(false), models: ref([]), total: ref(0),
    currentPage: ref(2), pageSize: ref(20), searchKeyword: ref(' custom '),
    modelsApi: {
      async getList(params) {
        assert.deepEqual(params, { skip: 20, limit: 20, scope: 'user', search: 'custom' })
        return { total: 21, items: [{ id: 21, scope: 'user' }] }
      },
    },
    showError(error) { throw error },
  }
  const fetchModels = new Function(...Object.keys(state), `return (${source})`)(...Object.values(state))
  await fetchModels()
  assert.equal(state.total.value, 21)
  assert.deepEqual(state.models.value, [{ id: 21, scope: 'user' }])
  assert.equal(state.loading.value, false)
})

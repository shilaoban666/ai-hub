import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { DEFAULT_NOUN_EXPLANATION_URL, nounExplanationLink } from '../src/utils/noun-highlight.js'
import { compileScript, parse } from '@vue/compiler-sfc'
import { computed, reactive, ref } from 'vue'
import { getCompatibleModelsForRuntime } from '../src/config/models.js'

function expressions(view) {
  const { descriptor } = parse(readFileSync(new URL(`../src/views/admin/${view}.vue`, import.meta.url), 'utf8'))
  const { scriptSetupAst } = compileScript(descriptor, { id: `settings-${view}` })
  const declarations = scriptSetupAst.filter(node => node.type === 'VariableDeclaration')
    .flatMap(node => node.declarations)
  return (name, scope) => {
    const declaration = declarations.find(node => node.id.name === name)
    assert.ok(declaration, `${view}: missing ${name}`)
    const source = descriptor.scriptSetup.content.slice(declaration.init.start, declaration.init.end)
    return new Function(...Object.keys(scope), `return (${source})`)(...Object.values(scope))
  }
}

function settingsEditor(view) {
  const evaluate = expressions(view)
  const calls = []
  const scope = {
    computed, reactive, ref, getCompatibleModelsForRuntime, DEFAULT_NOUN_EXPLANATION_URL, nounExplanationLink,
    loading: ref(false), settingsLoaded: ref(false), loadError: ref(''),
    saving: ref(false), publishing: ref(false), modelSaving: ref(false),
    iconUploading: ref(false), mascotUploading: ref(false),
    draft: ref(null), published: ref(null), models: ref([]),
    savedPayloadSignature: ref(''), activeTab: ref('runtime'),
    creditSettingKeys: ['initial_claim_amount', 'daily_claim_amount', 'per_run_limit', 'low_balance_threshold'],
    DEFAULT_CREDIT_DISPLAY_NAME: '积分',
    ElMessage: Object.fromEntries(['success', 'warning', 'error'].map(name => [name, text => calls.push([name, text])])),
    ElMessageBox: { confirm: async () => {} }, enterpriseApi: {},
  }
  scope.defaults = evaluate('defaults', scope)
  if (view === 'WorkbenchSettings') assert.equal(scope.defaults.noun_explanation_url, DEFAULT_NOUN_EXPLANATION_URL)
  scope.form = reactive({ ...scope.defaults })
  for (const name of ['settingsPayload', view === 'AssistantSettings' ? 'payloadSignature' : 'signature',
    'isDirty', 'canPublish', 'errorText', 'applySettings', 'load', 'saveDraft', 'publish']) {
    scope[name] = evaluate(name, scope)
  }
  if (view === 'WorkbenchSettings') scope.enabledModels = evaluate('enabledModels', scope)
  // Rebind handlers after their computed model catalog is available.
  scope.publish = evaluate('publish', scope)
  return { scope, calls, evaluate }
}

for (const view of ['AssistantSettings', 'WorkbenchSettings']) {
  const kind = view === 'AssistantSettings' ? 'Agent' : 'Workbench'

  test(`${view}: failed initial load blocks writes and a retry restores the editor`, async () => {
    const { scope } = settingsEditor(view)
    scope.enterpriseApi[`get${kind}Settings`] = async () => { throw new Error('offline') }
    scope.enterpriseApi.getPlatformModels = async () => ({ items: [] })
    scope.enterpriseApi[`save${kind}Settings`] = async () => assert.fail('unloaded settings must not be saved')
    scope.enterpriseApi[`publish${kind}Settings`] = async () => assert.fail('unloaded settings must not be published')
    await scope.load()
    assert.equal(scope.loading.value, false)
    assert.ok(scope.loadError.value)
    assert.equal(scope.isDirty.value, false)
    assert.equal(scope.canPublish.value, false)
    await scope.saveDraft()
    await scope.publish()
    const published = { ...scope.defaults, version: 3 }
    scope.enterpriseApi[`get${kind}Settings`] = async () => ({ draft: null, published })
    await scope.load()
    assert.equal(scope.settingsLoaded.value, true)
    assert.equal(scope.loadError.value, '')
    assert.equal(scope.published.value.version, 3)
    scope.form[view === 'AssistantSettings' ? 'max_turns' : 'assistant_name'] = view === 'AssistantSettings' ? 80 : 'Changed'
    scope.enterpriseApi[`get${kind}Settings`] = async () => { throw new Error('refresh offline') }
    await scope.load()
    assert.equal(scope.settingsLoaded.value, false)
    assert.equal(scope.isDirty.value, false)
    assert.equal(scope.canPublish.value, false)
  })

  test(`${view}: saved drafts and publications use server values without another load`, async () => {
    const { scope } = settingsEditor(view)
    const initial = { ...scope.defaults, initial_claim_amount: 10, daily_claim_amount: 2,
      per_run_limit: 1, default_model_id: 1, version: 3 }
    scope.applySettings({ draft: null, published: initial })
    if (view === 'AssistantSettings') scope.form.max_turns = 80
    else scope.form.assistant_name = '  Team  '
    scope.models.value = [{ id: 1, is_enabled: true, has_api_key: true, api_protocol: 'anthropic-messages' }]
    scope.enterpriseApi[`save${kind}Settings`] = async payload => ({ ...payload, assistant_name: 'Team', version: 4 })
    scope.enterpriseApi[`publish${kind}Settings`] = async payload => ({ ...payload, version: 4 })
    scope.enterpriseApi[`get${kind}Settings`] = async () => assert.fail('writes should not refetch settings')
    await scope.saveDraft()
    assert.equal(scope.draft.value.version, 4)
    assert.equal(scope.published.value.version, 3)
    assert.equal(scope.isDirty.value, false)
    if (view === 'WorkbenchSettings') assert.equal(scope.form.assistant_name, 'Team')
    await scope.publish()
    assert.equal(scope.draft.value, null)
    assert.equal(scope.published.value.version, 4)
    assert.equal(scope.canPublish.value, false)
  })

  test(`${view}: canceling publication preserves edits and causes no write`, async () => {
    const { scope } = settingsEditor(view)
    scope.applySettings({ draft: null, published: { ...scope.defaults, initial_claim_amount: 10,
      daily_claim_amount: 2, per_run_limit: 1, default_model_id: 1, version: 3 } })
    if (view === 'AssistantSettings') scope.form.max_turns = 80
    else scope.form.assistant_name = 'Team'
    scope.models.value = [{ id: 1, is_enabled: true, has_api_key: true, api_protocol: 'anthropic-messages' }]
    scope.ElMessageBox.confirm = async () => { throw 'cancel' }
    scope.enterpriseApi[`publish${kind}Settings`] = async () => assert.fail('canceled publication must not write')
    await scope.publish()
    assert.equal(scope.publishing.value, false)
    assert.equal(scope.published.value.version, 3)
    assert.equal(scope.isDirty.value, true)
  })

  test(`${view}: a failed write preserves edits and the user can retry`, async () => {
    const { scope, calls } = settingsEditor(view)
    scope.applySettings({ draft: null, published: { ...scope.defaults, version: 3 } })
    if (view === 'AssistantSettings') scope.form.max_turns = 80
    else scope.form.assistant_name = 'Team'
    scope.enterpriseApi[`save${kind}Settings`] = async () => {
      throw { response: { data: { detail: { message: '保存失败，请重试' } } } }
    }
    await scope.saveDraft()
    assert.equal(scope.saving.value, false)
    assert.equal(scope.isDirty.value, true)
    assert.equal(scope.published.value.version, 3)
    assert.equal(scope.draft.value, null)
    assert.deepEqual(calls.at(-1), ['error', '保存失败，请重试'])
    scope.enterpriseApi[`save${kind}Settings`] = async payload => ({ ...payload, version: 4 })
    await scope.saveDraft()
    assert.equal(scope.draft.value.version, 4)
    assert.equal(scope.isDirty.value, false)
  })

  test(`${view}: repeated clicks during confirmation produce only one publication`, async () => {
    const { scope } = settingsEditor(view)
    scope.applySettings({ draft: { ...scope.defaults, initial_claim_amount: 10,
      daily_claim_amount: 2, per_run_limit: 1, default_model_id: 1, version: 4 }, published: null })
    scope.models.value = [{ id: 1, is_enabled: true, has_api_key: true, api_protocol: 'anthropic-messages' }]
    let confirm
    let writes = 0
    scope.ElMessageBox.confirm = () => new Promise(resolve => { confirm = resolve })
    scope.enterpriseApi[`publish${kind}Settings`] = async payload => {
      writes += 1
      return { ...payload, version: 4 }
    }
    const publishing = scope.publish()
    assert.equal(scope.publishing.value, true)
    await scope.publish()
    confirm()
    await publishing
    assert.equal(writes, 1)
    assert.equal(scope.publishing.value, false)
  })
}

test('platform model saves preserve pending Runtime and credit edits', async () => {
  const { scope, evaluate } = settingsEditor('AssistantSettings')
  scope.applySettings({ draft: null, published: { ...scope.defaults, version: 3 } })
  scope.form.max_turns = 80
  scope.form.per_run_limit = 5
  scope.models.value = [{ id: 1, name: 'Old model' }]
  scope.modelForm = { id: 1, name: 'New model', api_key: '' }
  scope.modelDialogVisible = ref(true)
  scope.enterpriseApi.updatePlatformModel = async () => ({ id: 1, name: 'New model', pricing_version: 2 })
  scope.enterpriseApi.getAgentSettings = async () => assert.fail('model edits must not reload policy')
  await evaluate('saveModel', scope)()
  assert.equal(scope.form.max_turns, 80)
  assert.equal(scope.form.per_run_limit, 5)
  assert.equal(scope.isDirty.value, true)
  assert.equal(scope.models.value[0].name, 'New model')
  assert.equal(scope.modelSaving.value, false)
})

test('workbench model choices exclude disabled, unconfigured, and incompatible models', () => {
  const { scope } = settingsEditor('WorkbenchSettings')
  const model = { is_enabled: true, has_api_key: true, api_protocol: 'anthropic-messages' }
  scope.models.value = [{ id: 1, ...model }, { id: 2, ...model, is_enabled: false },
    { id: 3, ...model, has_api_key: false }, { id: 4, ...model, api_protocol: 'openai-completions' }]
  assert.deepEqual(scope.enabledModels.value.map(item => item.id), [1])
})

test('editing an existing agent uses its effective Runtime without a second settings request', async () => {
  const evaluate = expressions('AgentDetail')
  const scope = {
    loading: ref(false), loadError: ref(''), basicLoaded: ref(false), isEdit: ref(true),
    DEFAULT_NOUN_EXPLANATION_URL,
    publicAgent: ref(null), expertWorkspace: null,
    allModels: ref([]), usableTemplates: ref([]), form: reactive({}), route: { params: { id: 9 } },
    api: { async get(path) {
      if (path === '/models') return { items: [{ id: 1 }] }
      assert.equal(path, '/agents/9')
      return { id: 9, name: 'Existing', runtime_type: 'claude_code', default_model_id: 1, models: [{ id: 1 }] }
    } },
    promptTemplatesApi: { getUsable: async () => { throw new Error('optional templates offline') } },
    enterpriseApi: { getAgentRuntimeSettings: async () => assert.fail('extra Runtime request is unnecessary') },
  }
  await evaluate('fetchData', scope)()
  assert.equal(scope.basicLoaded.value, true)
  assert.equal(scope.form.name, 'Existing')
  assert.equal(scope.form.runtime_type, 'claude_code')
  assert.equal(scope.loadError.value, '')
  assert.equal(scope.loading.value, false)
})

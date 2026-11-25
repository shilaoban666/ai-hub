import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import { ref } from 'vue'
import { parseBackendDateTime } from '../src/utils/date-time.js'

const { descriptor } = parse(readFileSync(
  new URL('../src/views/admin/AgentChat.vue', import.meta.url), 'utf8',
))
const { scriptSetupAst } = compileScript(descriptor, { id: 'session-model-test' })
const declarations = scriptSetupAst
  .filter(node => node.type === 'VariableDeclaration')
  .flatMap(node => node.declarations)

// Execute the component's actual handlers with controlled network and view state.
function handler(name, state) {
  const declaration = declarations.find(node => node.id.name === name)
  assert.ok(declaration?.init, `Missing component handler: ${name}`)
  const source = descriptor.scriptSetup.content.slice(declaration.init.start, declaration.init.end)
  return new Function(...Object.keys(state), `return (${source})`)(...Object.values(state))
}

function setup() {
  const state = {
    parseBackendDateTime,
    agent: ref({ default_model_id: 20 }), agentId: 1,
    agentModels: ref([]), agentSkills: ref([]), selectedSkillId: ref(null),
    agentLoadSequence: 0, personalSkillsLoadSequence: 0,
    selectedModelId: ref(null), currentSessionId: ref(null), currentSessionMetadata: ref(null),
    currentSessionReadOnly: ref(false), sessionViewKey: ref(0), sessions: ref([]),
    currentBlocks: ref([]), selectedFiles: ref([]), inputText: ref(''),
    olderMessagesLoading: ref(false), historyMessagesLoading: ref(false),
    historyMessagesHasMore: ref(false), displayMessages: ref([]),
    sessionsLoading: ref(false), sessionsLoadedCount: ref(0), sessionsTotal: ref(0),
    sessionsRequestPending: false, SESSION_PAGE_SIZE: 20,
    activeStreamState: ref(null), streamStates: ref([]), streamingSessionId: ref(null),
    streamingViewKey: ref(0), currentRunId: ref(null), currentRunPhase: ref('idle'),
    permissionQueue: ref([]), chatMainRef: ref(null),
    streaming: ref(false), handleSend() {}, chatDisposed: false, sessionStatusTimer: null,
    window: { clearTimeout() {}, setTimeout() {} },
    sessionDrafts: new Map(), messageLoadSequence: 0,
    props: { personalChat: true }, route: { query: {} },
    expertWorkspace: null, chatRouteActive: ref(true),
    initialBootstrap: null,
    router: { replace() {} }, api: { async get() { throw new Error('Unexpected request') } },
    assetsApi: { async getWorkspacePrompts() { throw new Error('Unexpected request') } },
    ElMessage: { error(message) { throw new Error(message) } },
    nextTick: async (callback) => callback?.(), saveSessionDraft() {}, resetTokenStats() {},
    isChannelSession: () => false, fetchMessages: async () => true,
    syncStreamStateToView() {},
    buildTurnMetrics: (usage, durationMs, chargedPoints) => ({ usage, durationMs, chargedPoints }),
    recomputeHistoryTokens() {},
    findStreamForView: () => null,
    isStreamVisibleInCurrentView: () => true,
    activateStreamForCurrentView() {
      state.activeStreamState.value = null
      state.streaming.value = false
      state.streamingSessionId.value = null
      return null
    },
  }
  state.sameSessionId = handler('sameSessionId', state)
  state.sameIdentifier = handler('sameIdentifier', state)
  state.getMessageResponseSession = handler('getMessageResponseSession', state)
  return state
}

test('opening the model menu refreshes custom models while preserving the conversation selection', async () => {
  const state = setup()
  Object.assign(state, { isValidId: true, chatDisposed: false, modelsLoading: ref(false) })
  state.selectedModelId.value = 20
  state.agentModels.value = [{ id: 20 }]
  let resolveRequest
  let requests = 0
  state.api.get = (url) => {
    assert.equal(url, '/agents/1/models')
    requests++
    return new Promise(resolve => { resolveRequest = resolve })
  }
  const refresh = handler('refreshModels', state)
  const pending = refresh()
  assert.equal(state.modelsLoading.value, true)
  await refresh()
  assert.equal(requests, 1)
  resolveRequest({ items: [{ id: 20 }, { id: 21, scope: 'user' }] })
  await pending
  assert.deepEqual(state.agentModels.value.map(model => model.id), [20, 21])
  assert.equal(state.selectedModelId.value, 20)
  assert.equal(state.modelsLoading.value, false)
})

test('failed model refresh retains current options and unlocks the selector', async () => {
  const state = setup()
  Object.assign(state, { isValidId: true, chatDisposed: false, modelsLoading: ref(false) })
  state.agentModels.value = [{ id: 20 }]
  const errors = []
  state.ElMessage.error = message => errors.push(message)
  await handler('refreshModels', state)()
  assert.deepEqual(state.agentModels.value, [{ id: 20 }])
  assert.equal(state.modelsLoading.value, false)
  assert.equal(errors.length, 1)
})

test('selecting history keeps its model and a new conversation resets to the default', async () => {
  const state = setup()
  state.sessions.value = [{ id: 1, model_id: 10 }]
  await handler('handleSelectSession', state)(1)
  assert.equal(state.selectedModelId.value, 10)
  handler('handleNewSession', state)()
  assert.equal(state.selectedModelId.value, 20)
  assert.equal(state.currentSessionId.value, null)
})

test('stream completion replaces the historical assistant message instead of appending a duplicate', () => {
  const state = setup()
  state.displayMessages.value = [
    { id: 'u-1', role: 'user', content: 'hello' },
    { id: 'a-2', messageId: 2, runId: 'run-1', role: 'assistant', blocks: [{ type: 'text', content: 'old' }] },
  ]
  const upsert = handler('upsertStreamAssistantMessage', state)

  upsert({
    runId: 'run-1',
    assistantMessageId: null,
    blocks: [{ type: 'text', content: 'new' }],
    usage: null,
    durationMs: 12,
    chargedPoints: null,
    startedAt: Date.now(),
  })

  assert.equal(state.displayMessages.value.filter(message => message.role === 'assistant').length, 1)
  assert.equal(state.displayMessages.value[1].id, 'a-2')
  assert.equal(state.displayMessages.value[1].blocks[0].content, 'new')
})

for (const metadataFirst of [true, false]) {
  test(`deep-linked history retains its model when metadata arrives ${metadataFirst ? 'before' : 'after'} the agent`, async () => {
    const state = setup()
    state.currentSessionId.value = 100
    let resolveAgent
    state.api.get = () => new Promise(resolve => { resolveAgent = resolve })
    const fetch = handler('fetchAgent', state)()
    const merge = () => handler('mergeCurrentSessionMetadata', state)(
      { session: { id: 100, model_id: 10 } }, 100,
    )
    if (metadataFirst) merge()
    resolveAgent({ default_model_id: 20, models: [{ id: 10 }, { id: 20 }] })
    await fetch
    if (!metadataFirst) merge()
    assert.equal(state.selectedModelId.value, 10)
    assert.equal(state.currentSessionMetadata.value.model_id, 10)
  })
}

test('the sessions response restores the fixed model for a selected conversation', async () => {
  const state = setup()
  state.currentSessionId.value = 1
  state.selectedModelId.value = 20
  state.api.get = async () => ({ total: 1, items: [{ id: 1, model_id: 10 }] })
  await handler('fetchSessions', state)()
  assert.equal(state.selectedModelId.value, 10)
})

test('agent loading preserves an explicit model selection in a new conversation', async () => {
  const state = setup()
  state.selectedModelId.value = 30
  state.api.get = async () => ({ default_model_id: 20 })
  await handler('fetchAgent', state)()
  assert.equal(state.selectedModelId.value, 30)
})

test('bootstrap model list is reused without another assistant request', async () => {
  const state = setup()
  state.initialBootstrap = { assistant: { id: 1, default_model_id: 20, models: [{ id: 10 }, { id: 20 }] } }
  await handler('fetchAgent', state)()
  assert.equal(state.selectedModelId.value, 20)
  assert.deepEqual(state.agentModels.value, [{ id: 10 }, { id: 20 }])
})

for (const metadataFirst of [true, false]) {
  test(`bootstrap preserves the history model with metadata ${metadataFirst ? 'before' : 'after'} initialization`, async () => {
    const state = setup()
    state.currentSessionId.value = 100
    state.initialBootstrap = { assistant: { id: 1, default_model_id: 20, models: [{ id: 10 }, { id: 20 }] } }
    const merge = () => handler('mergeCurrentSessionMetadata', state)({ session: { id: 100, model_id: 10 } }, 100)
    if (metadataFirst) merge()
    await handler('fetchAgent', state)()
    if (!metadataFirst) merge()
    assert.equal(state.selectedModelId.value, 10)
  })
}

test('bootstrap for another assistant falls back to the authorized assistant request', async () => {
  const state = setup()
  state.initialBootstrap = { assistant: { id: 99, default_model_id: 99 } }
  const requests = []
  state.api.get = async path => { requests.push(path); return { id: 1, default_model_id: 20 } }
  await handler('fetchAgent', state)()
  assert.deepEqual(requests, ['/agents/1'])
  assert.equal(state.selectedModelId.value, 20)
})

test('personal skill picker uses the available list without requesting the catalog', async () => {
  const state = setup()
  state.assetsApi = {
    getAvailableSkills: async () => ({ items: [{ skill_id: 1, name: 'Global skill' }, { skill_id: 2, name: 'Personal skill' }] }),
    getSkillCatalog: () => assert.fail('Chat must not scan the catalog'),
  }
  await handler('fetchPersonalSkills', state)()
  assert.deepEqual(state.agentSkills.value, [{ id: 1, name: 'Global skill' }, { id: 2, name: 'Personal skill' }])
})

for (const personalChat of [true, false]) {
  test(`${personalChat ? 'personal skill' : 'agent'} stale loading cannot erase the example skill selection`, async () => {
    const state = setup()
    state.props.personalChat = personalChat
    const pending = []
    if (personalChat) state.assetsApi.getAvailableSkills = () => new Promise(resolve => pending.push(resolve))
    else state.api.get = () => new Promise(resolve => pending.push(resolve))
    const load = handler(personalChat ? 'fetchPersonalSkills' : 'fetchAgent', state)
    const old = load()
    const current = load()
    pending[1](personalChat ? { items: [{ skill_id: 20, name: 'Example skill' }] } : { skills: [{ id: 20, name: 'Example skill' }] })
    await current
    state.selectedSkillId.value = 20
    pending[0](personalChat ? { items: [] } : { skills: [] })
    await old
    assert.equal(state.selectedSkillId.value, 20)
    assert.deepEqual(state.agentSkills.value, [{ id: 20, name: 'Example skill' }])
  })

  for (const abandon of [true, false]) {
    test(`${personalChat ? 'personal' : 'expert'} example ${abandon ? 'does not overwrite a newer conversation' : 'fills input with the installed skill selected'}`, async () => {
      const state = setup()
      state.props.personalChat = personalChat
      state.route.query = { skillExample: '本周销量怎么样？', skillExampleId: '20', agent: '9' }
      state.router.replace = async ({ query }) => { state.route.query = query }
      state.handleNewSession = handler('handleNewSession', state)
      state.syncInstalledSkills = () => {}
      let releaseLoad
      state.fetchAgent = () => new Promise(resolve => { releaseLoad = () => {
        if (!personalChat) state.agentSkills.value = [{ id: 20, name: 'Example skill' }]
        resolve()
      } })
      state.fetchPersonalSkills = async () => {
        if (personalChat) state.agentSkills.value = [{ id: 20, name: 'Example skill' }]
      }
      const applied = handler('applySkillExample', state)()
      await Promise.resolve()
      assert.equal(state.inputText.value, '', 'Wait for the skill selection before making the example sendable')
      if (abandon) {
        state.sessionViewKey.value++
        state.inputText.value = '新的草稿'
      }
      releaseLoad()
      assert.equal(await applied, true)
      assert.deepEqual(state.route.query, { agent: '9' })
      assert.equal(state.selectedSkillId.value, abandon ? null : 20)
      assert.equal(state.inputText.value, abandon ? '新的草稿' : '本周销量怎么样？')
    })
  }
}

test('an unavailable example skill does not create an unscoped sendable draft', async () => {
  const state = setup()
  state.route.query = { skillExample: '本周销量怎么样？', skillExampleId: '20' }
  state.router.replace = async ({ query }) => { state.route.query = query }
  state.handleNewSession = handler('handleNewSession', state)
  state.syncInstalledSkills = () => {}
  state.fetchAgent = async () => {}
  state.fetchPersonalSkills = async () => {}
  const warnings = []
  state.ElMessage.warning = text => warnings.push(text)
  assert.equal(await handler('applySkillExample', state)(), true)
  assert.equal(state.selectedSkillId.value, null)
  assert.equal(state.inputText.value, '')
  assert.equal(warnings.length, 1)
})

for (const hasBootstrapCredit of [true, false]) {
  test(`mount ${hasBootstrapCredit ? 'reuses bootstrap balance' : 'fetches balance for older bootstrap responses'}`, async () => {
    const callback = scriptSetupAst.find(node => node.type === 'ExpressionStatement'
      && node.expression.callee?.name === 'onMounted').expression.arguments[0]
    const source = descriptor.scriptSetup.content.slice(callback.start, callback.end)
    let credits = 0
    let focus = 0
    const state = {
      window: { addEventListener() {} }, handleCreditAccountUpdated() {},
      workspaceSidebar: null, isValidId: true, props: { personalChat: true },
      chatRouteActive: ref(true),
      initialBootstrap: hasBootstrapCredit ? { credit: { available_balance: 0 } } : null,
      fetchCredits() { credits += 1 }, fetchRuntimes() {}, fetchUsableTemplates() {},
      route: { query: {} }, fetchPersonalSkills() {}, fetchIdentityMcpStatus() {}, fetchSessions() {}, syncInstalledSkills() {},
      fetchAgent: async () => {}, nextTick: async () => {},
      applySkillExample: async () => false,
      chatMainRef: ref({ focusInput() { focus += 1 } }),
    }
    await new Function(...Object.keys(state), `return (${source})`)(...Object.values(state))()
    assert.equal(credits, hasBootstrapCredit ? 0 : 1)
    assert.equal(focus, 1)
  })
}

for (const [personalChat, workbenchChat] of [
  [true, false],
  [true, true],
  [false, true],
  [false, false],
]) {
  test(`chat prompt selection uses ${personalChat ? 'the workbench prompt list' : 'the expert binding'} scope`, async () => {
    const state = setup()
    state.props.personalChat = personalChat
    state.props.workbenchChat = workbenchChat
    state.usableTemplates = ref([])
    const requests = []
    state.assetsApi = { getWorkspacePrompts: async params => {
      requests.push(['workbench-prompts', params])
      return { items: [
        { id: 10, is_system: false, is_public: false },
        { id: 11, is_system: false, is_public: true },
      ] }
    } }
    state.api.get = async url => {
      requests.push(url)
      return { prompt_templates: [{ id: 20, name: 'Selected module' }] }
    }
    await handler('fetchUsableTemplates', state)()
    assert.deepEqual(requests, personalChat ? [['workbench-prompts', { skip: 0, limit: 200 }]] : ['/agents/1'])
    assert.deepEqual(state.usableTemplates.value.map(item => item.id), personalChat ? [10, 11] : [20])
    if (!personalChat) {
      state.api.get = async () => ({ prompt_templates: [] })
      await handler('fetchUsableTemplates', state)()
      assert.deepEqual(state.usableTemplates.value, [])
    }
  })
}

test('selected identity in the AI workbench uses its bound prompt list', async () => {
  const state = setup()
  state.props.personalChat = false
  state.props.workbenchChat = true
  state.usableTemplates = ref([])
  state.api.get = async () => ({ prompt_templates: [{ id: 30, name: '已绑定模板' }, { id: 31, name: '另一个已绑定模板' }] })
  await handler('fetchUsableTemplates', state)()
  assert.deepEqual(state.usableTemplates.value.map(item => item.id), [30, 31])
})

test('expert menu navigation keeps the selected conversation and does not load messages', async () => {
  const state = setup()
  Object.assign(state, {
    expertWorkspace: {}, chatRouteActive: ref(false),
    shareDialogVisible: ref(true), workspaceOpen: ref(true),
    handleNewSession: () => assert.fail('Menu navigation must not reset the conversation'),
    handleSelectSession: () => assert.fail('Menu navigation must not reload messages'),
  })
  state.currentSessionId.value = 123
  state.inputText.value = 'unsent draft'
  const watcher = scriptSetupAst.find(node => node.type === 'ExpressionStatement'
    && node.expression.callee?.name === 'watch'
    && descriptor.scriptSetup.content.slice(node.expression.arguments[0].start, node.expression.arguments[0].end)
      .includes('[route.name, route.query.session, route.query.agent')).expression.arguments[1]
  const source = descriptor.scriptSetup.content.slice(watcher.start, watcher.end)
  const navigate = new Function(...Object.keys(state), `return (${source})`)(...Object.values(state))
  for (const name of ['AdminAgentDetail', 'AdminAgentChannels', 'AdminAgentStatistics']) {
    await navigate([name, undefined], ['AdminAgentChat'])
    assert.equal(state.currentSessionId.value, 123)
    assert.equal(state.inputText.value, 'unsent draft')
  }
})

test('expert history selected on a resource page navigates to chat with its session', async () => {
  const state = setup()
  const destinations = []
  Object.assign(state, {
    expertWorkspace: {}, chatRouteActive: ref(false), mobileSidebarOpen: ref(false),
    router: { push: async destination => destinations.push(destination) },
    handleSelectSession: () => assert.fail('Let the chat route watcher load messages once'),
  })
  await handler('handleSidebarSelectSession', state)(123)
  assert.deepEqual(destinations, [{ path: '/admin/agents/1/chat', query: { session: 123 } }])
})

test('run start keeps elapsed preparation time when entering the running phase', () => {
  const state = setup()
  Object.assign(state, { scheduleStreamStateSync() {}, touchStreamingSessionInList() {} })
  const startedAt = Date.parse('2026-11-05T01:00:00Z')
  const stream = { startedAt, phase: 'queued', requestedSessionId: 123 }
  const onEvent = handler('handleSseEvent', state)

  onEvent({ type: 'run_start', run_id: 'r1', session_id: 123, started_at: '2026-11-05T01:00:03Z' }, stream)
  assert.equal(stream.phase, 'running')
  assert.equal(stream.startedAt, startedAt)

  // Replaying the start frame during reconnect must keep the same clock origin.
  onEvent({ type: 'snapshot_reset' }, stream)
  onEvent({ type: 'run_start', run_id: 'r1', session_id: 123, started_at: '2026-11-05T01:00:03Z' }, stream)
  assert.equal(stream.startedAt, startedAt)
})

test('resuming a run restores earlier server timing without moving an established start forward', () => {
  const state = setup()
  Object.assign(state, { scheduleStreamStateSync() {}, touchStreamingSessionInList() {} })
  const stream = { startedAt: Date.parse('2026-11-05T01:01:00Z'), phase: 'connecting', requestedSessionId: 123 }
  const onEvent = handler('handleSseEvent', state)
  onEvent({ type: 'run_start', run_id: 'r1', session_id: 123, started_at: '2026-11-05T01:00:00Z' }, stream)
  assert.equal(stream.startedAt, Date.parse('2026-11-05T01:00:00Z'))
  onEvent({ type: 'run_start', run_id: 'r1', session_id: 123, started_at: '2026-11-05T01:00:03Z' }, stream)
  assert.equal(stream.startedAt, Date.parse('2026-11-05T01:00:00Z'))
})

test('a background expert run attaches its new session without changing the resource URL', () => {
  const state = setup()
  state.sessionViewKey.value = 7
  Object.assign(state, {
    chatRouteActive: ref(false), streamingSessionId: ref(null),
    isActiveStreamState: () => true, touchStreamingSessionInList() {}, scheduleStreamStateSync() {},
    router: { replace: () => assert.fail('Background stream must not change resource query parameters') },
  })
  handler('handleSseEvent', state)({ type: 'run_start', run_id: 'r1', session_id: 123 }, {
    requestedSessionId: null, viewKey: 7,
  })
  assert.equal(state.currentSessionId.value, 123)
  assert.equal(state.streamingSessionId.value, 123)
})

for (const personalChat of [true, false]) {
  test(`${personalChat ? 'workbench' : 'expert'} chat loads identity MCP status`, async () => {
    const state = setup()
    state.props.personalChat = personalChat
    const connections = [
      { name: 'Online MCP', status: 'active', auth_mode: 'current_user' },
      { name: 'Manual MCP', status: 'active', auth_mode: 'manual' },
      { name: 'Disabled MCP', status: 'disabled', auth_mode: 'current_user' },
    ]
    state.assetsApi = {
      getMcpConnections: async params => {
        assert.equal(personalChat, true, 'Experts must load their scoped configuration')
        state.identityRequestParams = params
        return { items: connections }
      },
    }
    state.api = { get: async path => {
      assert.equal(personalChat, false)
      state.identityRequestParams = path
      return { mcp_connections: connections }
    } }
    state.identityMcpNames = ref([])
    await handler('fetchIdentityMcpStatus', state)()
    assert.deepEqual(state.identityRequestParams, personalChat ? undefined : '/agents/1')
    assert.deepEqual(state.identityMcpNames.value, ['Online MCP'])
  })
}

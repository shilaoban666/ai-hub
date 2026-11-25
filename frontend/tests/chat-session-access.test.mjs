import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import { ref } from 'vue'

const { descriptor } = parse(readFileSync(new URL('../src/views/admin/AgentChat.vue', import.meta.url), 'utf8'))
const { scriptSetupAst } = compileScript(descriptor, { id: 'session-access' })
function expression(name) {
  const declaration = scriptSetupAst.filter(node => node.type === 'VariableDeclaration')
    .flatMap(node => node.declarations).find(node => node.id.name === name)
  return descriptor.scriptSetup.content.slice(declaration.init.start, declaration.init.end)
}

function loader(get) {
  const replacedQueries = []
  const notices = []
  const state = {
    api: { get }, agentId: 1, MESSAGE_PAGE_SIZE: 50,
    currentSessionId: ref(909), currentSessionReadOnly: ref(false),
    currentSessionMetadata: ref(null), selectedModelId: ref(null),
    agent: ref({ default_model_id: 1 }), sessionViewKey: ref(0),
    historyMessagesLoading: ref(false), historyMessagesLoadFailed: ref(false),
    historyMessagesHasMore: ref(false), olderMessagesLoading: ref(false),
    displayMessages: ref([]), currentBlocks: ref([]), selectedFiles: ref([]),
    selectedSkillId: ref(null), inputText: ref('unsent message'), chatMainRef: ref(null),
    chatRouteActive: ref(true), route: { query: { session: '909', agent: '1' } },
    router: { replace: value => replacedQueries.push(value.query) },
    sameSessionId: (left, right) => String(left) === String(right),
    saveSessionDraft() {}, activateStreamForCurrentView() {}, resetTokenStats() {},
    mergeCurrentSessionMetadata() {}, recomputeHistoryTokens() {},
    mapHistoryMessages: items => items, nextTick: () => {},
    ElMessage: { warning: value => notices.push(value), error: value => notices.push(value) },
  }
  const load = new Function(...Object.keys(state), `
    let messageLoadSequence = 0;
    const handleNewSession = ${expression('handleNewSession')};
    return ${expression('fetchMessages')};
  `)(...Object.values(state))
  return { state, load, replacedQueries, notices }
}

for (const status of [403, 404]) {
  test(`inaccessible session (${status}) clears the target and URL but preserves unsent text`, async () => {
    const { state, load, replacedQueries, notices } = loader(async () => {
      throw { response: { status } }
    })
    assert.equal(await load(909), false)
    assert.equal(state.currentSessionId.value, null)
    assert.equal(state.inputText.value, 'unsent message')
    assert.equal(state.historyMessagesLoading.value, false)
    assert.equal(state.historyMessagesLoadFailed.value, false)
    assert.deepEqual(replacedQueries, [{ agent: '1' }])
    assert.equal(notices.length, 1)
  })
}

test('temporary loading errors block sending without changing the selected session', async () => {
  const { state, load, replacedQueries } = loader(async () => { throw new Error('network unavailable') })
  assert.equal(await load(909), false)
  assert.equal(state.currentSessionId.value, 909)
  assert.equal(state.historyMessagesLoadFailed.value, true)
  assert.equal(state.historyMessagesLoading.value, false)
  assert.deepEqual(replacedQueries, [])
})

test('a stale access error cannot reset a newly selected session', async () => {
  let reject
  const { state, load, replacedQueries } = loader(() => new Promise((resolve, fail) => { reject = fail }))
  const pending = load(909)
  state.currentSessionId.value = 12
  reject({ response: { status: 404 } })
  await pending
  assert.equal(state.currentSessionId.value, 12)
  assert.deepEqual(replacedQueries, [])
})

test('successfully loading an owned session clears the failure lock', async () => {
  const { state, load } = loader(async () => ({ items: [{ id: 1, content: 'owned message' }] }))
  state.historyMessagesLoadFailed.value = true
  assert.equal(await load(909), true)
  assert.equal(state.currentSessionId.value, 909)
  assert.equal(state.historyMessagesLoadFailed.value, false)
  assert.deepEqual(state.displayMessages.value, [{ id: 1, content: 'owned message' }])
})

test('send handler returns before attempting a request while session history is unverified', async () => {
  for (const [loading, failed] of [[true, false], [false, true]]) {
    const send = new Function('historyMessagesLoading', 'historyMessagesLoadFailed',
      `return ${expression('handleSend')}`)(ref(loading), ref(failed))
    // No request or stream dependencies are provided: reaching them would throw.
    await send()
  }
})

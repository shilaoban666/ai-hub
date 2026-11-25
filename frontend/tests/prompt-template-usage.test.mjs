import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import { ref } from 'vue'

const { descriptor } = parse(readFileSync(
  new URL('../src/views/admin/components/ChatMain.vue', import.meta.url), 'utf8',
))
const { scriptSetupAst } = compileScript(descriptor, { id: 'prompt-template-usage' })
const declarations = scriptSetupAst.filter(node => node.type === 'VariableDeclaration')
  .flatMap(node => node.declarations)

function setup() {
  const state = {
    inputText: ref('Existing draft'), varDialogVisible: ref(false),
    currentTemplate: ref(null), currentVariables: ref([]), varForm: ref({}), warnings: [],
    ElMessage: { warning: message => state.warnings.push(message) },
    emit: () => assert.fail('Selecting a template must not send a message'),
  }
  for (const name of ['parseVariables', 'renderTemplate', 'appendToInput', 'handleUseTemplate', 'confirmVariables']) {
    const { init } = declarations.find(node => node.id.name === name)
    const source = descriptor.scriptSetup.content.slice(init.start, init.end)
    state[name] = new Function(...Object.keys(state), `return (${source})`)(...Object.values(state))
  }
  return state
}

test('selecting a template without variables appends it once without sending', () => {
  const state = setup()
  state.handleUseTemplate({ content: 'Summarize inventory', variables: null })
  assert.equal(state.inputText.value, 'Existing draft\nSummarize inventory')
  assert.equal(state.varDialogVisible.value, false)
})

test('templates with variables wait for confirmation, then append substituted content once', () => {
  const state = setup()
  state.handleUseTemplate({
    content: 'Summarize {{topic}}, limit {{limit}}',
    variables: JSON.stringify([{ name: 'topic', required: true }, { name: 'limit', default: 0 }]),
  })
  assert.equal(state.varDialogVisible.value, true)
  assert.equal(state.inputText.value, 'Existing draft')
  state.confirmVariables()
  assert.equal(state.warnings.length, 1)
  assert.equal(state.inputText.value, 'Existing draft')
  assert.equal(state.varDialogVisible.value, true)
  state.varForm.value.topic = 'inventory'
  state.confirmVariables()
  assert.equal(state.inputText.value, 'Existing draft\nSummarize inventory, limit 0')
  assert.equal(state.varDialogVisible.value, false)
  assert.equal(state.inputText.value.includes('{{'), false)
})

test('cancelling variable entry leaves the draft intact', () => {
  const state = setup()
  state.handleUseTemplate({ content: '{{topic}}', variables: '[{"name":"topic"}]' })
  state.varDialogVisible.value = false
  assert.equal(state.inputText.value, 'Existing draft')
})

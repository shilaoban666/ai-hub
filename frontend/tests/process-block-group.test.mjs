import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { compileScript, parse } from '@vue/compiler-sfc'
import { computed, effectScope, nextTick, reactive, ref, watch } from 'vue'
import { getToolResultHtml, getToolResultSeverity } from '../src/utils/agent-chat-blocks.js'

const { descriptor } = parse(readFileSync(new URL('../src/views/admin/components/ProcessBlockGroup.vue', import.meta.url), 'utf8'))
const { scriptSetupAst } = compileScript(descriptor, { id: 'process-block-group' })
const source = scriptSetupAst.filter(node => node.type !== 'ImportDeclaration')
  .map(node => descriptor.scriptSetup.content.slice(node.start, node.end)).join('\n')

function setup(t, overrides = {}) {
  const props = reactive({ streaming: false, running: false, blocks: [], ...overrides })
  const scope = effectScope()
  t.after(() => scope.stop())
  const state = scope.run(() => new Function(
    'computed', 'ref', 'watch', 'defineProps', 'getToolResultHtml', 'getToolResultSeverity',
    `${source}\nreturn { expanded, toggle, hasError, processTitle }`,
  )(computed, ref, watch, () => props, getToolResultHtml, getToolResultSeverity))
  return { props, ...state }
}

const failedTool = () => ({ type: 'tool_use', name: 'MCP', is_error: true, result: 'Connection refused', endTime: 10 })

test('completed historical errors start collapsed while keeping the error indicator', t => {
  const state = setup(t, { blocks: [failedTool()] })
  assert.equal(state.expanded.value, false)
  assert.equal(state.hasError.value, true)
  assert.equal(state.processTitle.value, '执行异常')
  state.toggle()
  assert.equal(state.expanded.value, true)
})

test('tool errors stay collapsed while the current activity card is shown', async t => {
  const state = setup(t, { streaming: true, running: true })
  state.props.blocks.push(failedTool())
  state.props.running = false
  await nextTick()
  assert.equal(state.expanded.value, false)
  state.props.streaming = false
  await nextTick()
  assert.equal(state.expanded.value, false)
  assert.equal(state.hasError.value, true)
})

test('later tool errors do not override a manual expansion state', async t => {
  const state = setup(t, { streaming: true, running: true })
  state.toggle()
  state.toggle()
  state.props.blocks.push(failedTool())
  state.props.running = false
  await nextTick()
  assert.equal(state.expanded.value, false)
  state.props.streaming = false
  await nextTick()
  assert.equal(state.expanded.value, false)
})

test('manual expansion remains open when streaming finishes', async t => {
  const state = setup(t, { streaming: true })
  state.toggle()
  state.props.streaming = false
  await nextTick()
  assert.equal(state.expanded.value, true)
})

test('streaming completed segments do not show a second completed status', t => {
  const state = setup(t, {
    streaming: true,
    blocks: [{ type: 'thinking', content: 'done', endTime: 10 }],
  })
  assert.equal(state.processTitle.value, '')
})

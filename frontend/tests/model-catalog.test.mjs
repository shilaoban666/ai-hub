import assert from 'node:assert/strict'
import test from 'node:test'
import { getModelGroupsForRuntime } from '../src/config/models.js'

const models = [
  { id: 1, scope: 'platform', api_protocol: 'anthropic-messages' },
  { id: 2, scope: 'user', api_protocol: 'openai-completions' },
  { id: 3, scope: 'user', api_protocol: 'anthropic-messages' },
  { id: 4, scope: 'user', api_protocol: null },
]

test('Claude groups platform and custom models with compatible protocols only', () => {
  const groups = getModelGroupsForRuntime(models, 'claude_code')
  assert.deepEqual(groups.map(group => [group.label, group.models.map(model => model.id)]), [
    ['平台模型', [1]], ['自定义模型', [3]],
  ])
})

test('empty or incompatible catalogs have no empty groups', () => {
  assert.deepEqual(getModelGroupsForRuntime([], 'claude_code'), [])
  assert.deepEqual(getModelGroupsForRuntime([models[1]], 'claude_code'), [])
  assert.deepEqual(getModelGroupsForRuntime([models[2]], 'claude_code').map(group => group.key), ['user'])
})

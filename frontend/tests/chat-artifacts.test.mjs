import test from 'node:test'
import assert from 'node:assert/strict'
import { getChatArtifacts } from '../src/utils/chat-artifacts.js'
import { mergeToolBlocks } from '../src/utils/agent-chat-blocks.js'

test('artifact lists come from explicit artifact blocks, not tool mentions or attachments', () => {
  const blocks = [
    { type: 'text', content: 'uploaded.csv' },
    { type: 'tool_use', input: { file_path: 'temporary.txt' } },
    { type: 'artifacts', files: [{ path: 'output/report.csv', size: 0, is_previewable: true }] },
  ]
  assert.deepEqual(getChatArtifacts(mergeToolBlocks(blocks)), [
    { path: 'output/report.csv', name: 'report.csv', size: 0, is_previewable: true },
  ])
})

test('artifact paths remain relative, deduplicate and preserve full names', () => {
  assert.deepEqual(getChatArtifacts([
    { type: 'artifacts', files: [{ path: 'out\\report.txt', size: 1 }, { path: '../secret' }, { path: '/etc/passwd' }, { path: 'C:\\secret' }, {}] },
    { type: 'artifacts', files: [{ path: 'out/report.txt', size: 2 }] },
  ]), [{ path: 'out/report.txt', name: 'report.txt', size: 2 }])
  assert.deepEqual(getChatArtifacts([]), [])
})

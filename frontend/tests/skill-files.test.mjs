import test from 'node:test'
import assert from 'node:assert/strict'
import { formatSkillFileSize, syncSkillFilePaths } from '../src/utils/skill-files.js'

test('binary size comes from stored bytes and edited text uses its current UTF-8 size', () => {
  assert.equal(formatSkillFileSize({ is_binary: true, size: 9 * 1024 * 1024, content: '' }), '9 MB')
  assert.equal(formatSkillFileSize({ content: '中文', size: 999 }), '6 B')
  assert.equal(formatSkillFileSize({ is_binary: true, size: 0 }), '0 B')
  assert.equal(formatSkillFileSize({ content: '' }), '0 B')
})

test('successful renames update references for the next save without changing resource data', () => {
  const font = { label: 'renamed.ttf', path: 'assets/font.ttf', original_path: 'assets/font.ttf', is_binary: true, content: '', size: 4096 }
  const tree = [{ label: 'renamed-assets', type: 'folder', children: [font] }]
  syncSkillFilePaths(tree)
  assert.equal(font.path, 'renamed-assets/renamed.ttf')
  assert.equal(font.original_path, font.path)
  assert.equal(font.content, '')
  assert.equal(font.size, 4096)
  font.label = 'next.ttf'
  syncSkillFilePaths(tree)
  assert.equal(font.original_path, 'renamed-assets/next.ttf')
})

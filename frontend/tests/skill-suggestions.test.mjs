import test from 'node:test'
import assert from 'node:assert/strict'
import { buildSkillSuggestions, pickSkillSuggestions } from '../src/utils/skill-suggestions.js'

test('uses only supplied examples, removes blanks and duplicates, and preserves full multiline prompts', () => {
  const prompt = `整理以下材料：\n${'详细内容。'.repeat(100)}`
  const pool = buildSkillSuggestions([
    { id: 1, name: '文档', conversation_examples: [' ', null, 42, ` ${prompt} `, 'Weekly report'] },
    { id: 2, name: '周报', conversation_examples: ['weekly  report', '整理本周进度'] },
    { id: 0, name: '无效', conversation_examples: ['不应出现'] },
    { id: 3, name: '无示例' },
  ])
  assert.equal(pool.length, 3)
  assert.equal(pool[0].prompt, prompt)
  assert.equal(pool[0].skillId, 1)
  assert.equal(pool[0].skillName, '文档')
  assert.equal(pool[2].prompt, '整理本周进度')
})

test('selects at most four different skills and refresh prefers previously unseen examples', () => {
  const pool = buildSkillSuggestions(Array.from({ length: 6 }, (_, index) => ({
    id: index + 1, name: `Skill ${index}`, conversation_examples: [`问题 ${index} A`, `问题 ${index} B`],
  })))
  const original = structuredClone(pool)
  const first = pickSkillSuggestions(pool, [], () => .5)
  const second = pickSkillSuggestions(pool, first, () => .5)
  assert.equal(first.length, 4)
  assert.equal(second.length, 4)
  assert.equal(new Set(first.map(item => item.skillId)).size, 4)
  assert.equal(new Set(second.map(item => item.skillId)).size, 4)
  assert.ok(second.every(item => !first.some(previous => previous.key === item.key)))
  assert.deepEqual(pool, original)
})

test('fills a batch from remaining examples after taking one from each available skill', () => {
  const pool = buildSkillSuggestions([
    { id: 7, name: '文档助手', conversation_examples: ['文档问题一', '文档问题二', '文档问题三', '文档问题四'] },
    { id: 8, name: '周报助手', conversation_examples: ['周报问题'] },
  ])
  const result = pickSkillSuggestions(pool, [], () => 0)
  assert.equal(result.length, 4)
  assert.equal(new Set(result.slice(0, 2).map(item => item.skillId)).size, 2)
  assert.equal(new Set(result.map(item => item.key)).size, 4)
})

test('single-skill recommendations fill four slots and rotate examples when possible', () => {
  const pool = buildSkillSuggestions([
    { id: 7, name: '助手', conversation_examples: ['问题一', '问题二', '问题三', '问题四', '问题五'] },
  ])
  const first = pickSkillSuggestions(pool, [], () => 0)
  const second = pickSkillSuggestions(pool, first, () => 0)
  assert.equal(first.length, 4)
  assert.equal(second.length, 4)
  assert.ok(second.some(item => !first.some(previous => previous.key === item.key)))
  assert.equal(pickSkillSuggestions(pool.slice(0, 2)).length, 2)
})

test('refresh still includes a new example when fewer than four alternatives exist', () => {
  const pool = buildSkillSuggestions(Array.from({ length: 5 }, (_, i) => ({
    id: i + 1, name: `${i}`, conversation_examples: [`问题 ${i}`],
  })))
  const first = pickSkillSuggestions(pool, [], () => 0)
  const second = pickSkillSuggestions(pool, first, () => 0)
  assert.equal(second.length, 4)
  assert.ok(second.some(item => !first.some(previous => previous.key === item.key)))
})

test('no skills or no configured examples produce no invented fallback tasks', () => {
  assert.deepEqual(pickSkillSuggestions(buildSkillSuggestions()), [])
  assert.deepEqual(pickSkillSuggestions(buildSkillSuggestions([{ id: 1, name: '技能', conversation_examples: [] }])), [])
})

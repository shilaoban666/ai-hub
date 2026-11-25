import assert from 'node:assert/strict'
import test from 'node:test'
import { createNounSuggester } from '../src/utils/noun-suggestions.js'

test('matches partial and complete names in a sentence at the caret', () => {
  const suggest = createNounSuggester(['我方测算库龄', '库龄', 'SKU'])
  assert.deepEqual(suggest('请解释库龄，以及其他指标', 5), {
    from: 3, to: 5, query: '库龄', options: ['库龄', '我方测算库龄'],
  })
  assert.deepEqual(suggest('请解释我方测算库龄'), {
    from: 3, to: 9, query: '我方测算库龄', options: ['我方测算库龄'],
  })
  assert.deepEqual(suggest('请解释我方测算库'), {
    from: 3, to: 8, query: '我方测算库', options: ['我方测算库龄'],
  })
  assert.deepEqual(suggest('库').options, ['库龄'])
})

test('hides empty and unmatched input and leaves file/skill triggers alone', () => {
  const suggest = createNounSuggester(['库龄', 'SKU'])
  for (const text of ['', ' ', '库龄 ', '库龄。', '没有匹配', 'sku', '@库龄', '请看 @库龄', '/库龄']) {
    assert.equal(suggest(text), null, text)
  }
  assert.equal(createNounSuggester([])('库'), null)
})

test('does not fall back to unrelated trailing characters when a phrase stops matching', () => {
  const suggest = createNounSuggester([
    '主体业务', '审核通过的FN头程费', '组合SKU的可用数量', '函数管理中的接口函数id',
    '通过数据渲染后的模板字符串', 'ASIN的BSRid', 'ASIN的BSR排名', 'ASIN的月销量增长率',
    '我方测算库龄', '库龄', 'Key',
  ])
  assert.deepEqual(suggest('主体').options, ['主体业务'])
  for (const text of ['主体的', '主体的内容', '库龄的', '请解释库龄的', 'MASK']) {
    assert.equal(suggest(text), null, text)
  }
  assert.deepEqual(suggest('库').options, ['库龄'])
  assert.deepEqual(suggest('请解释库').options, ['库龄'])
  assert.deepEqual(suggest('请解释库龄').options, ['库龄', '我方测算库龄'])
  assert.deepEqual(suggest('BSR').options, ['ASIN的BSRid', 'ASIN的BSR排名'])
  assert.deepEqual(suggest('请解释ASIN的').options, ['ASIN的BSRid', 'ASIN的BSR排名', 'ASIN的月销量增长率'])
})

test('treats punctuation literally, deduplicates names, and handles large dictionaries', () => {
  const suggest = createNounSuggester(['a+b[0]', 'a+b[0]', null, ' ', '📦库龄'])
  assert.deepEqual(suggest('请看a+b['), { from: 2, to: 6, query: 'a+b[', options: ['a+b[0]'] })
  assert.deepEqual(suggest('请看a+b[0]'), { from: 2, to: 8, query: 'a+b[0]', options: ['a+b[0]'] })
  assert.deepEqual(suggest('📦库'), { from: 0, to: 3, query: '📦库', options: ['📦库龄'] })
  assert.deepEqual(suggest('📦库龄'), { from: 0, to: 4, query: '📦库龄', options: ['📦库龄'] })
  const large = createNounSuggester(Array.from({ length: 20000 }, (_, i) => `指标${i}`))
  assert.equal(large('指标').options.length, 8)
  assert.deepEqual(large('指标19999').options, ['指标19999'])
})

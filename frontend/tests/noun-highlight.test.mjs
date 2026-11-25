import assert from 'node:assert/strict'
import test from 'node:test'
import { createNounMatcher, nounExplanationLink, DEFAULT_NOUN_EXPLANATION_URL } from '../src/utils/noun-highlight.js'

test('matches complete literal names, case sensitively, repeatedly and longest first', () => {
  const matcher = createNounMatcher(['库龄', '我方测算库龄', 'SKU', 'a+b[0]', '', ' ', null])
  assert.deepEqual(matcher.find('我方测算库龄、库龄、sku、SKU、a+b[0]、我方测算库龄'), [
    { start: 0, end: 6, noun: '我方测算库龄' },
    { start: 7, end: 9, noun: '库龄' },
    { start: 14, end: 17, noun: 'SKU' },
    { start: 18, end: 24, noun: 'a+b[0]' },
    { start: 25, end: 31, noun: '我方测算库龄' },
  ])
  assert.deepEqual(matcher.find('我方测算库'), [])
})

test('appends the encoded noun to the configured link without inserting a parameter name', () => {
  assert.equal(DEFAULT_NOUN_EXPLANATION_URL, 'https://online.fancyqube.net/Project/admin/skuapp/t_noun_explanation/?exact=1&noun_name=')
  const defaultLink = new URL(createNounMatcher(['库龄']).link('库龄'))
  assert.equal(defaultLink.searchParams.get('exact'), '1')
  assert.equal(defaultLink.searchParams.get('noun_name'), '库龄')
  assert.equal(defaultLink.searchParams.get('none'), null)
  const destination = 'https://example.com/info?source=chat&name='
  assert.equal(nounExplanationLink(destination), destination)
  const matcher = createNounMatcher(['库龄', 'SKU'], destination)
  assert.equal(matcher.link('库龄'), destination + encodeURIComponent('库龄'))
  assert.equal(matcher.link('SKU'), destination + 'SKU')
  assert.equal(new URL(matcher.link('库龄')).searchParams.get('none'), null)
  const noun = '我方 & 库龄#?'
  assert.equal(new URL(nounExplanationLink(destination, noun)).searchParams.get('name'), noun)
  for (const prefix of ['https://example.com/nouns/', 'https://example.com/#/noun?name=', 'https://example.com/?']) {
    assert.equal(nounExplanationLink(prefix, '库龄'), prefix + encodeURIComponent('库龄'))
  }
  assert.equal(nounExplanationLink('https://example.com', 'SKU'), 'https://example.com/SKU')
})

test('rejects unsafe and invalid destinations and empty lists', () => {
  for (const url of ['javascript:alert(1)', 'data:text/html,test', '//example.com', 'https://user:pass@example.com', '']) {
    assert.equal(nounExplanationLink(url), null)
    assert.equal(createNounMatcher(['test'], url), null)
  }
  assert.equal(createNounMatcher([]), null)
})

test('supports emoji names and large dictionaries without a regex limit', () => {
  const matcher = createNounMatcher([...Array.from({ length: 20000 }, (_, i) => `指标${i}`), '📦库龄'])
  assert.deepEqual(matcher.find('指标19999 📦库龄'), [
    { start: 0, end: 7, noun: '指标19999' },
    { start: 8, end: 12, noun: '📦库龄' },
  ])
})

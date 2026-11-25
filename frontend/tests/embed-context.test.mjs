import test from 'node:test'
import assert from 'node:assert/strict'
import { normalizePageContext, trustedParentOrigin } from '../src/utils/embed-context.js'

test('only same-origin or explicitly configured hosts can supply context', () => {
  assert.equal(trustedParentOrigin('https://online.example/orders/', 'https://ai.example', 'https://online.example'), 'https://online.example')
  assert.equal(trustedParentOrigin('https://online.example.attacker.test', 'https://ai.example', 'https://online.example'), '')
  assert.equal(trustedParentOrigin('', 'https://ai.example'), '')
  assert.equal(trustedParentOrigin('https://ai.example/preview', 'https://ai.example'), 'https://ai.example')
})

test('page context retains routing identifiers and strips secrets and arbitrary data', () => {
  assert.deepEqual(normalizePageContext({ url: 'https://online.example/orders/?id=12&token=secret&email=secret#/detail?session=secret', title: 'Orders' }, 'https://online.example'), {
    url: 'https://online.example/orders/?id=12#/detail', title: 'Orders',
  })
  assert.equal(normalizePageContext({ url: 'javascript:alert(1)' }, 'https://online.example'), null)
  assert.equal(normalizePageContext({ url: 'https://other.example/' }, 'https://online.example'), null)
  assert.equal(normalizePageContext({ url: 'https://online.example/' + 'a'.repeat(4096) }, 'https://online.example'), null)
})

import assert from 'node:assert/strict'
import test from 'node:test'
import { consumeLogoutCallback, createLogoutUrl } from '../src/utils/logout.js'

function storage(state = 'test-state', partial = '0') {
  const values = new Map([['oauth_logout_state', state], ['oauth_logout_partial', partial]])
  return { getItem: key => values.get(key) ?? null, removeItem: key => values.delete(key) }
}

test('logout visits IAM with an encoded registered callback and no credentials in URL', () => {
  const url = new URL(createLogoutUrl('http://172.26.36.234:9001', 'client', 'http://localhost:15173/oauth/callback', 'test-state'))
  assert.equal(url.origin, 'http://172.26.36.234:9001')
  assert.equal(url.pathname, '/logout/')
  assert.equal(url.searchParams.get('post_logout_redirect_uri'), 'http://localhost:15173/oauth/callback')
  assert.deepEqual([...url.searchParams.keys()], ['client_id', 'post_logout_redirect_uri', 'state'])
})

test('a logout callback must match the pending request and can only complete once', () => {
  const pending = storage()
  assert.throws(() => consumeLogoutCallback(pending, 'wrong-state'))
  assert.deepEqual(consumeLogoutCallback(pending, 'test-state'), { tokenRevocationFailed: false })
  assert.throws(() => consumeLogoutCallback(pending, 'test-state'))
})

test('partial token revocation remains visible after IAM clears the browser session', () => {
  assert.deepEqual(consumeLogoutCallback(storage('test-state', '1'), 'test-state'), { tokenRevocationFailed: true })
})

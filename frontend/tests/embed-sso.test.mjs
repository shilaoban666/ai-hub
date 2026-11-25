import assert from 'node:assert/strict'
import test from 'node:test'
import { createEmbedSso } from '../src/utils/embed-sso.js'
import { embeddedAccessToken } from '../src/utils/embedded-session.js'

function harness() {
  let listener
  const state = { user_id: 7, session_id: 'a'.repeat(64), status: 200, exchanges: 0, grants: [], ended: [], checks: 0, time: 100000 }
  const target = {
    location: { origin: 'https://ai.test' }, setTimeout, clearTimeout,
    addEventListener: (_type, fn) => { listener = fn }, removeEventListener: () => {},
    parent: { postMessage(data, origin) {
      assert.equal(origin, 'https://host.test')
      assert.deepEqual(Object.keys(data).sort(), (data.action === 'authorize' ? ['protocol', 'type', 'request_id', 'action', 'session_id'] : ['protocol', 'type', 'request_id', 'action']).sort())
      if (data.action === 'status') state.checks += 1
      if (data.action === 'authorize') state.grants.push(data)
      const grant = { access_token: `token-${state.user_id}-${state.grants.length}`, token_type: 'bearer', expires_in: 900, ...state.badToken }
      if (state.spoof) {
        const forged = { protocol: data.protocol, type: 'auth-result', request_id: data.request_id, ok: true, result: { user_id: 999, session_id: 'f'.repeat(64) } }
        listener({ source: target.parent, origin: 'https://evil.test', data: forged })
        listener({ source: {}, origin, data: forged })
      }
      queueMicrotask(() => { listener({ source: target.parent, origin, data: {
        protocol: data.protocol, type: 'auth-result', request_id: data.request_id,
        ok: state.status === 200, status: state.status, message: '会话已结束',
        result: { user_id: state.user_id, session_id: state.session_id,
          ...(data.action === 'authorize' ? grant : {}),
        },
      } }); if (data.action === 'authorize' && state.logoutDuringGrant) state.status = 401 })
    } },
  }
  const oldFetch = globalThis.fetch
  globalThis.fetch = async () => { state.exchanges += 1; throw new Error('The iframe must not exchange tokens directly') }
  const sso = createEmbedSso({ parentOrigin: 'https://host.test', target, now: () => state.time, onEnded: error => state.ended.push(error) })
  return { state, sso, close() { sso.dispose(); globalThis.fetch = oldFetch } }
}

test('silent login deduplicates concurrent requests and only keeps an in-memory access token', async () => {
  const h = harness()
  try {
    const tokens = await Promise.all([h.sso.ensure(), h.sso.ensure(), h.sso.ensure()])
    assert.deepEqual(tokens, ['token-7-1', 'token-7-1', 'token-7-1'])
    assert.equal(h.state.grants.length, 1)
    assert.equal(embeddedAccessToken(), 'token-7-1')
    assert.equal(await h.sso.ensure(), 'token-7-1')
    assert.equal(h.state.grants.length, 1)
  } finally { h.close() }
})

test('registered host client delivers its user token without browser-side IAM exchange', async () => {
  const h = harness()
  try {
    assert.equal(await h.sso.ensure(), 'token-7-1')
    assert.equal(h.state.exchanges, 0)
    assert.equal(await h.sso.ensure(true), 'token-7-2')
    h.state.user_id = 8
    h.state.session_id = 'b'.repeat(64)
    h.sso.invalidate()
    await assert.rejects(h.sso.ensure(), error => error.status === 409)
    assert.equal(embeddedAccessToken(), '')
    assert.equal(await h.sso.ensure(), 'token-8-3')
    h.state.status = 401
    await h.sso.monitor()
    assert.equal(embeddedAccessToken(), '')
    assert.equal(h.state.exchanges, 0)
  } finally { h.close() }
})

test('malformed token is rejected without browser-side token exchange', async () => {
  for (const badToken of [{ access_token: '' }, { expires_in: '900' }, { expires_in: Infinity }, { token_type: 'other' }, { user_id: 99 }]) {
    const h = harness()
    try {
      h.state.badToken = badToken
      await assert.rejects(h.sso.ensure())
      assert.equal(embeddedAccessToken(), '')
      assert.equal(h.state.exchanges, 0)
    } finally { h.close() }
  }
})

test('renewal rechecks the host session and logout clears credentials instead of refreshing', async () => {
  const h = harness()
  try {
    await h.sso.ensure()
    assert.equal(await h.sso.ensure(true), 'token-7-2')
    h.state.status = 401
    await assert.rejects(h.sso.ensure(true))
    assert.equal(embeddedAccessToken(), '')
    assert.equal(h.state.grants.length, 2)
    assert.equal(h.state.ended.length, 1)
  } finally { h.close() }
})

test('account changes fail the old request and allow a fresh isolated login', async () => {
  const h = harness()
  try {
    await h.sso.ensure()
    h.state.user_id = 8
    h.state.session_id = 'b'.repeat(64)
    h.sso.invalidate()
    await assert.rejects(h.sso.ensure(), error => error.status === 409)
    assert.equal(h.state.grants.length, 1)
    assert.equal(embeddedAccessToken(), '')
    assert.equal(await h.sso.ensure(), 'token-8-2')
  } finally { h.close() }
})

test('background checks discard credentials when the host session expires', async () => {
  const h = harness()
  try {
    await h.sso.ensure()
    h.state.status = 403
    await h.sso.monitor()
    assert.equal(embeddedAccessToken(), '')
    assert.equal(h.state.ended.length, 1)
  } finally { h.close() }
})

test('a logout during token delivery cannot install the old token', async () => {
  const h = harness()
  try {
    h.state.logoutDuringGrant = true
    await assert.rejects(h.sso.ensure())
    assert.equal(embeddedAccessToken(), '')
  } finally { h.close() }
})

test('other origins and other windows cannot inject login responses', async () => {
  const h = harness()
  try {
    h.state.spoof = true
    assert.equal(await h.sso.ensure(), 'token-7-1')
    assert.equal(h.sso.userId, 7)
  } finally { h.close() }
})


test('sequential API requests reuse a fresh identity check; expiry checks status without issuing a token', async () => {
  const h = harness()
  try {
    await h.sso.ensure()
    assert.equal(h.state.checks, 2)
    for (let i = 0; i < 10; i++) await h.sso.ensure()
    await h.sso.monitor(false)
    assert.equal(h.state.checks, 2)
    h.state.time += 15000
    await Promise.all([h.sso.ensure(), h.sso.ensure(), h.sso.monitor(false)])
    assert.equal(h.state.checks, 3)
    assert.equal(h.state.grants.length, 1)
    h.sso.invalidate()
    await h.sso.monitor(false)
    assert.equal(h.state.checks, 4)
    h.state.time += 870000
    await h.sso.ensure()
    assert.equal(h.state.grants.length, 2)
    assert.equal(h.state.checks, 6)
  } finally { h.close() }
})

test('expired cache detects logout before sending the next API request', async () => {
  const h = harness()
  try {
    await h.sso.ensure()
    h.state.status = 401
    h.state.time += 15000
    await assert.rejects(h.sso.ensure())
    assert.equal(embeddedAccessToken(), '')
    assert.equal(h.state.grants.length, 1)
  } finally { h.close() }
})

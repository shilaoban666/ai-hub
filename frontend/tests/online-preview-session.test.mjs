import assert from 'node:assert/strict'
import test from 'node:test'

import {
  ensureOnlinePreviewSession,
  resetOnlinePreviewSessionForTests,
} from '../src/utils/online-preview-session.js'

function installBrowserGlobals(token = '') {
  globalThis.localStorage = {
    getItem: key => key === 'access_token' ? token : null,
  }
  globalThis.window = {
    setTimeout,
    clearTimeout,
  }
}

test.beforeEach(() => {
  resetOnlinePreviewSessionForTests()
  installBrowserGlobals()
  globalThis.fetch = undefined
})

test('skips the exchange when AI Hub has no access token', async () => {
  let calls = 0
  globalThis.fetch = async () => {
    calls += 1
    return { ok: true }
  }

  assert.equal(await ensureOnlinePreviewSession(), false)
  assert.equal(calls, 0)
})

test('merges concurrent exchanges and caches a successful session', async () => {
  installBrowserGlobals('access-token')
  let calls = 0
  globalThis.fetch = async (url, options) => {
    calls += 1
    assert.equal(url, '/func_process_app/iam_sso_session/')
    assert.equal(options.headers.Authorization, 'Bearer access-token')
    return {
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      json: async () => ({ code: 0, msg: '', data: { user_id: 7 } }),
    }
  }

  const [first, second] = await Promise.all([
    ensureOnlinePreviewSession(),
    ensureOnlinePreviewSession(),
  ])

  assert.equal(first, true)
  assert.equal(second, true)
  assert.equal(await ensureOnlinePreviewSession(), true)
  assert.equal(calls, 1)
})

test('allows preview fallback and temporarily caches a failed exchange', async () => {
  installBrowserGlobals('access-token')
  let calls = 0
  globalThis.fetch = async () => {
    calls += 1
    return { ok: false, status: 401 }
  }

  assert.equal(await ensureOnlinePreviewSession(), false)
  assert.equal(await ensureOnlinePreviewSession(), false)
  assert.equal(calls, 1)
})

test('uses the Pinia access token even when local storage is unavailable', async () => {
  installBrowserGlobals('')
  let authorization = ''
  globalThis.fetch = async (_url, options) => {
    authorization = options.headers.Authorization
    return {
      ok: true,
      status: 200,
      headers: { get: () => 'application/json' },
      json: async () => ({ code: 0, data: { user_id: 7 } }),
    }
  }

  assert.equal(await ensureOnlinePreviewSession('pinia-token'), true)
  assert.equal(authorization, 'Bearer pinia-token')
})

test('does not treat a redirected login page as a successful exchange', async () => {
  installBrowserGlobals('access-token')
  globalThis.fetch = async () => ({
    ok: true,
    status: 200,
    headers: { get: () => 'text/html; charset=utf-8' },
  })

  assert.equal(await ensureOnlinePreviewSession(), false)
})

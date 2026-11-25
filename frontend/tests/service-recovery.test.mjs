import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { canRecoverRequest, createServiceRecovery, isServiceUnavailable } from '../src/utils/service-recovery.js'

function outage(method = 'get', status = 503) {
  return { config: { method }, response: { status, data: { code: status, message: 'Service temporarily unavailable', timestamp: '2026-11-03', data: null } } }
}
function harness(options = {}) {
  let clock = 0
  const states = [], delays = []
  const recovery = createServiceRecovery({
    now: () => clock, onChange: state => states.push(state),
    setTimer: (fn, ms) => { delays.push(ms); return setImmediate(() => { clock += ms; fn() }) },
    clearTimer: clearImmediate, ...options,
  })
  return { recovery, states, delays }
}

test('gateway standard JSON 503s, 502/504 and network failures can recover', () => {
  for (const status of [502, 503, 504]) assert.equal(canRecoverRequest(outage('get', status)), true)
  assert.equal(canRecoverRequest({ config: { method: 'head' }, code: 'ERR_NETWORK' }), true)
  for (const status of [400, 401, 403, 404, 422, 500]) assert.equal(canRecoverRequest(outage('get', status)), false)
  const business = outage()
  business.response.headers = { 'x-aihub-error': 'business' }
  assert.equal(isServiceUnavailable(business), false)
})

test('writes, cancellation, opted-out calls and internal retry attempts never replay', () => {
  for (const method of ['post', 'patch', 'put', 'delete']) assert.equal(canRecoverRequest(outage(method)), false)
  for (const overrides of [{ skipServiceRecovery: true }, { _serviceRecoveryAttempt: true }]) {
    const error = outage(); Object.assign(error.config, overrides)
    assert.equal(canRecoverRequest(error), false)
  }
  assert.equal(canRecoverRequest({ ...outage(), code: 'ERR_CANCELED' }), false)
})

test('reads return their actual result after temporary failure and clear the notice', async () => {
  const h = harness()
  let calls = 0
  const result = await h.recovery.recover(outage(), async () => {
    if (++calls < 3) throw outage()
    return { items: [{ id: 7 }] }
  })
  assert.deepEqual(result, { items: [{ id: 7 }] })
  assert.deepEqual(h.delays, [1000, 2000, 4000])
  assert.deepEqual(h.states.at(-1), { active: 0, unavailable: false })
})

test('long outages stop at the deadline and offer a persistent unavailable state', async () => {
  const h = harness({ maxWait: 7000 })
  let calls = 0
  await assert.rejects(h.recovery.recover(outage(), async () => { calls++; throw outage() }))
  assert.equal(calls, 2)
  assert.deepEqual(h.delays, [1000, 2000, 4000])
  assert.deepEqual(h.states.at(-1), { active: 0, unavailable: true })
  h.recovery.noteSuccess()
  assert.deepEqual(h.states.at(-1), { active: 0, unavailable: false })
})

test('concurrent requests keep one notice until all waiting reads complete', async () => {
  const h = harness()
  let finishSecond
  const secondResponse = new Promise(resolve => { finishSecond = resolve })
  const first = h.recovery.recover(outage(), async () => 'one')
  const second = h.recovery.recover(outage(), () => secondResponse)
  assert.equal(await first, 'one')
  assert.equal(h.states.at(-1).active, 1)
  finishSecond('two')
  assert.equal(await second, 'two')
  assert.equal(h.states.at(-1).active, 0)
})

test('abort releases timers and waiting state without retrying', async () => {
  const controller = new AbortController()
  const h = harness({ setTimer: () => 1, clearTimer: () => {} })
  let calls = 0
  const result = h.recovery.recover(outage(), () => { calls++ }, { signal: controller.signal })
  controller.abort()
  await assert.rejects(result, error => error.code === 'ERR_CANCELED')
  assert.equal(calls, 0)
  assert.deepEqual(h.states.at(-1), { active: 0, unavailable: false })
})

test('manual retry wakes waiting reads without reloading the page', async () => {
  const h = harness({ setTimer: () => 1, clearTimer: () => {} })
  const result = h.recovery.recover(outage(), async () => 'restored')
  h.recovery.retryNow()
  assert.equal(await result, 'restored')
})

test('application errors after reconnect are returned directly', async () => {
  const h = harness()
  const forbidden = outage('get', 403)
  await assert.rejects(h.recovery.recover(outage(), async () => { throw forbidden }), error => error === forbidden)
  assert.equal(h.delays.length, 1)
  assert.deepEqual(h.states.at(-1), { active: 0, unavailable: false })
})

// Exercise the real Axios interceptors with adapters, without a running backend.
async function requestModule() {
  const inline = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
  let source = await readFile(new URL('../src/api/request.js', import.meta.url), 'utf8')
  const imports = {
    axios: import.meta.resolve('axios'),
    '@/config': inline('export const config = { apiTimeout: 5000, authBase: "https://auth.test", oauth2ClientId: "test" }'),
    '@/utils/embedded-session': inline('export const isEmbeddedPage = () => false; export const embeddedGeneration = () => 0; export const requestEmbeddedToken = () => ""; export const clearEmbeddedSession = () => {}'),
    '@/utils/service-recovery': new URL('../src/utils/service-recovery.js', import.meta.url).href,
    '@/utils/service-availability': new URL('../src/utils/service-availability.js', import.meta.url).href,
  }
  for (const [name, url] of Object.entries(imports)) source = source.replace(`from '${name}'`, `from '${url}'`)
  return import(inline(source))
}

function storage() {
  const values = new Map([['access_token', 'original-token'], ['refresh_token', 'refresh-token']])
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
}

test('real request interceptor recovers reads, unwraps data once, and never repeats writes', async () => {
  globalThis.localStorage = storage()
  globalThis.window = { location: { pathname: '/admin/chat', href: '/admin/chat' } }
  const { default: request } = await requestModule()
  const { serviceRecoveryFor } = await import('../src/utils/service-availability.js')
  const { AxiosError } = await import('axios')
  let reads = 0, writes = 0
  request.defaults.adapter = async cfg => {
    if (cfg.method === 'post') writes++
    else reads++
    if (cfg.method === 'post' || reads === 1) {
      throw new AxiosError('503', 'ERR_BAD_RESPONSE', cfg, {}, { status: 503, headers: {}, data: outage().response.data })
    }
    return { config: cfg, status: 200, headers: {}, data: { code: 200, data: { code: 'business-code', data: 'keep-this-envelope' } } }
  }
  const response = request.get('/skills')
  await new Promise(resolve => setImmediate(resolve))
  serviceRecoveryFor('/aihub/api').retryNow()
  assert.deepEqual(await response, { code: 'business-code', data: 'keep-this-envelope' })
  assert.equal(reads, 2)
  await assert.rejects(request.post('/skills', { name: 'test' }), error => error.response.data.detail.includes('核实结果'))
  assert.equal(writes, 1)
})

test('requests waiting through an account change cannot replay for the new user', async () => {
  globalThis.localStorage = storage()
  const { default: request } = await requestModule()
  const { serviceRecoveryFor } = await import('../src/utils/service-availability.js')
  const { AxiosError } = await import('axios')
  let calls = 0
  request.defaults.adapter = async cfg => {
    calls++
    throw new AxiosError('503', 'ERR_BAD_RESPONSE', cfg, {}, { status: 503, headers: {}, data: 'unavailable' })
  }
  const response = request.get('/skills')
  await new Promise(resolve => setImmediate(resolve))
  localStorage.setItem('access_token', 'new-user-token')
  serviceRecoveryFor('/aihub/api').retryNow()
  await assert.rejects(response, error => error.code === 'ERR_CANCELED')
  assert.equal(calls, 1)
})

test('an IAM outage during refresh preserves tokens and the current page', async () => {
  globalThis.localStorage = storage()
  const { refreshAccessToken } = await requestModule()
  const { default: axios, AxiosError } = await import('axios')
  const previous = axios.defaults.adapter
  axios.defaults.adapter = async cfg => { throw new AxiosError('503', 'ERR_BAD_RESPONSE', cfg, {}, { status: 503, headers: {}, data: 'unavailable' }) }
  try {
    await assert.rejects(refreshAccessToken())
    assert.equal(localStorage.getItem('access_token'), 'original-token')
    assert.equal(localStorage.getItem('refresh_token'), 'refresh-token')
    assert.equal(window.location.href, '/admin/chat')
  } finally { axios.defaults.adapter = previous }
})

test('an account change before the first failed response also prevents replay', async () => {
  globalThis.localStorage = storage()
  const { default: request } = await requestModule()
  const { serviceRecoveryFor } = await import('../src/utils/service-availability.js')
  const { AxiosError } = await import('axios')
  let calls = 0
  request.defaults.adapter = async cfg => {
    calls++
    assert.equal(cfg.headers.Authorization, 'Bearer original-token')
    localStorage.setItem('access_token', 'new-user-token')
    throw new AxiosError('503', 'ERR_BAD_RESPONSE', cfg, {}, { status: 503, headers: {}, data: 'unavailable' })
  }
  const response = request.get('/skills')
  await new Promise(resolve => setImmediate(resolve))
  serviceRecoveryFor('/aihub/api').retryNow()
  await assert.rejects(response, error => error.code === 'ERR_CANCELED')
  assert.equal(calls, 1)
})

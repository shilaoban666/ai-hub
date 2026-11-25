import assert from 'node:assert/strict'
import test from 'node:test'
import configure from '../vite.config.js'

test('local launcher uses gateway API proxies and browser-visible IAM URL without changing builds', () => {
  const ports = process.env.AIHUB_LOCAL_PORTS
  const host = process.env.AIHUB_PUBLIC_HOST
  try {
    delete process.env.AIHUB_LOCAL_PORTS
    const build = configure({ command: 'build' })
    const normalDev = configure({ command: 'serve' })
    process.env.AIHUB_LOCAL_PORTS = JSON.stringify({ frontend: 25173, backend: 25174, gateway: 28080, iam: 29001 })
    process.env.AIHUB_PUBLIC_HOST = 'localhost'
    const local = configure({ command: 'serve' })
    assert.equal(local.server.port, 25173)
    assert.equal(local.server.strictPort, true)
    assert.equal(local.server.proxy['/aihub/api'].target, 'http://127.0.0.1:28080')
    assert.equal(local.server.proxy['/iam/api'].target, 'http://127.0.0.1:28080')
    assert.equal(local.server.proxy['/uploads'].target, 'http://127.0.0.1:25174')
    assert.equal(local.server.proxy['/releases'].target, 'http://127.0.0.1:25174')
    assert.equal(local.define['import.meta.env.VITE_AUTH_BASE'], '"http://localhost:29001"')
    assert.deepEqual(configure({ command: 'build' }).define, build.define)
    delete process.env.AIHUB_LOCAL_PORTS
    assert.deepEqual(configure({ command: 'serve' }).define, normalDev.define)
  } finally {
    if (ports === undefined) delete process.env.AIHUB_LOCAL_PORTS
    else process.env.AIHUB_LOCAL_PORTS = ports
    if (host === undefined) delete process.env.AIHUB_PUBLIC_HOST
    else process.env.AIHUB_PUBLIC_HOST = host
  }
})

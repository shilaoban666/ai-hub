import assert from 'node:assert/strict'
import test from 'node:test'
import { createPinia } from 'pinia'
import { useAppStore } from '../src/stores/app.js'

function storage(t, initial) {
  const data = new Map(initial === undefined ? [] : [['aihub:sidebar-collapsed', String(initial)]])
  const writes = []
  const old = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
    getItem: key => data.get(key) ?? null,
    setItem: (key, value) => { writes.push([key, value]); data.set(key, value) },
  } })
  t.after(() => {
    if (old) Object.defineProperty(globalThis, 'localStorage', old)
    else delete globalThis.localStorage
  })
  return { data, writes }
}

test('manual changes are restored by a fresh app store without an initial write', t => {
  const { writes } = storage(t)
  const appStore = useAppStore(createPinia())
  assert.equal(appStore.collapsed, false)
  assert.deepEqual(writes, [])
  appStore.toggleSidebar()
  assert.equal(useAppStore(createPinia()).collapsed, true)
  appStore.toggleSidebar()
  assert.equal(useAppStore(createPinia()).collapsed, false)
})

test('unavailable storage does not break sidebar interaction', t => {
  storage(t)
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, get() { throw new Error('Storage unavailable') } })
  const appStore = useAppStore(createPinia())
  assert.equal(appStore.collapsed, false)
  assert.doesNotThrow(() => appStore.toggleSidebar())
  assert.equal(appStore.collapsed, true)
})

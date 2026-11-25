import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import {
  mergeVisibleResourceOrder,
  sortByResourceOrder,
  useTagReorder,
} from '../src/composables/useTagReorder.js'

test('sortByResourceOrder keeps untracked items in source order at the end', () => {
  const items = [{ id: 1 }, { id: 2 }, { id: 3 }, { id: 4 }]
  assert.deepEqual(
    sortByResourceOrder(items, ['3', '1']).map(item => item.id),
    [3, 1, 2, 4],
  )
})

test('mergeVisibleResourceOrder preserves hidden slots', () => {
  assert.deepEqual(
    mergeVisibleResourceOrder(['1', '2', '3', '4', '5'], ['4', '2']),
    ['1', '4', '3', '2', '5'],
  )
})

test('useTagReorder shows the insertion side and moves only on drop', async () => {
  const items = ref([{ id: 1 }, { id: 2 }, { id: 3 }])
  let savedIds = []
  const reorder = useTagReorder(items, {
    save: async ids => { savedIds = ids },
  })
  const listeners = new Map()
  const previousWindow = globalThis.window
  globalThis.window = {
    addEventListener: (type, listener) => listeners.set(type, listener),
    removeEventListener: (type, listener) => {
      if (listeners.get(type) === listener) listeners.delete(type)
    },
  }
  const elements = [
    { dataset: { tagSortId: '1' }, getBoundingClientRect: () => ({ left: 0, right: 60, top: 0, bottom: 40, width: 60, height: 40 }) },
    { dataset: { tagSortId: '2' }, getBoundingClientRect: () => ({ left: 70, right: 130, top: 0, bottom: 40, width: 60, height: 40 }) },
    { dataset: { tagSortId: '3' }, getBoundingClientRect: () => ({ left: 140, right: 200, top: 0, bottom: 40, width: 60, height: 40 }) },
  ]
  const container = { querySelectorAll: () => elements }
  elements.forEach(element => { element.parentElement = container })

  try {
    reorder.pointerDown({
      button: 0,
      clientX: 20,
      clientY: 20,
      currentTarget: elements[0],
      isPrimary: true,
      pointerId: 9,
    }, items.value[0])
    const pointerMove = listeners.get('pointermove')
    const pointerUp = listeners.get('pointerup')
    pointerMove({ clientX: 120, clientY: 20, pointerId: 9, preventDefault() {} })

    assert.deepEqual(items.value.map(item => item.id), [1, 2, 3])
    assert.equal(reorder.dropTargetId.value, '2')
    assert.equal(reorder.dropSide.value, 'after')
    pointerUp({ pointerId: 9, preventDefault() {} })
    await reorder.whenIdle()
    assert.deepEqual(items.value.map(item => item.id), [2, 1, 3])
    assert.deepEqual(savedIds, ['2', '1', '3'])
  } finally {
    reorder.dispose()
    globalThis.window = previousWindow
  }
})

test('useTagReorder accepts another drag while the previous save is pending', async () => {
  const items = ref([{ id: 1 }, { id: 2 }, { id: 3 }])
  const saves = []
  let releaseFirstSave
  const firstSaveGate = new Promise(resolve => { releaseFirstSave = resolve })
  const reorder = useTagReorder(items, {
    save: async ids => {
      saves.push(ids)
      if (saves.length === 1) await firstSaveGate
    },
  })
  const listeners = new Map()
  const previousWindow = globalThis.window
  globalThis.window = {
    addEventListener: (type, listener) => listeners.set(type, listener),
    removeEventListener: (type, listener) => {
      if (listeners.get(type) === listener) listeners.delete(type)
    },
  }
  const elements = [
    { dataset: { tagSortId: '1' }, getBoundingClientRect: () => ({ left: 0, right: 60, top: 0, bottom: 40, width: 60, height: 40 }) },
    { dataset: { tagSortId: '2' }, getBoundingClientRect: () => ({ left: 70, right: 130, top: 0, bottom: 40, width: 60, height: 40 }) },
    { dataset: { tagSortId: '3' }, getBoundingClientRect: () => ({ left: 140, right: 200, top: 0, bottom: 40, width: 60, height: 40 }) },
  ]
  const container = { querySelectorAll: () => elements }
  elements.forEach(element => { element.parentElement = container })

  function drag(itemId, elementIndex, pointerId, clientX) {
    const item = items.value.find(entry => entry.id === itemId)
    reorder.pointerDown({
      button: 0,
      clientX: elementIndex === 2 ? 170 : 20,
      clientY: 20,
      currentTarget: elements[elementIndex],
      isPrimary: true,
      pointerId,
    }, item)
    const pointerMove = listeners.get('pointermove')
    const pointerUp = listeners.get('pointerup')
    pointerMove({ clientX, clientY: 20, pointerId, preventDefault() {} })
    pointerUp({ pointerId, preventDefault() {} })
  }

  try {
    drag(1, 0, 10, 120)
    assert.deepEqual(items.value.map(item => item.id), [2, 1, 3])
    assert.equal(saves.length, 1)

    drag(3, 2, 11, 10)
    assert.deepEqual(items.value.map(item => item.id), [2, 3, 1])
    assert.equal(saves.length, 1)

    releaseFirstSave()
    await reorder.whenIdle()
    assert.deepEqual(saves, [['2', '1', '3'], ['2', '3', '1']])
  } finally {
    reorder.dispose()
    globalThis.window = previousWindow
  }
})

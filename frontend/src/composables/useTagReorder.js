import { computed, ref } from 'vue'

export function sortByResourceOrder(items, resourceIds, getId = item => item.id) {
  const positions = new Map((resourceIds || []).map((id, index) => [String(id), index]))
  return [...(items || [])].sort((left, right) => {
    const leftPosition = positions.get(String(getId(left)))
    const rightPosition = positions.get(String(getId(right)))
    if (leftPosition === undefined && rightPosition === undefined) return 0
    if (leftPosition === undefined) return 1
    if (rightPosition === undefined) return -1
    return leftPosition - rightPosition
  })
}

export function mergeVisibleResourceOrder(resourceIds, visibleResourceIds) {
  const visibleIds = visibleResourceIds.map(String)
  const visibleSet = new Set(visibleIds)
  const knownIds = new Set()
  const mergedIds = resourceIds.map(String).filter(id => {
    if (knownIds.has(id)) return false
    knownIds.add(id)
    return true
  })
  visibleIds.forEach(id => {
    if (!knownIds.has(id)) {
      knownIds.add(id)
      mergedIds.push(id)
    }
  })
  const visibleSlots = mergedIds
    .map((id, index) => visibleSet.has(id) ? index : -1)
    .filter(index => index >= 0)
  visibleSlots.forEach((slot, index) => {
    mergedIds[slot] = visibleIds[index]
  })
  return mergedIds
}

export function useTagReorder(items, { getId = item => item.id, save, onError }) {
  const draggedId = ref(null)
  const dropTargetId = ref(null)
  const dropSide = ref(null)
  const saving = ref(false)
  const isDragging = computed(() => draggedId.value !== null)
  let originalItems = []
  let changed = false
  let pendingInsertionIndex = null
  let suppressClickUntil = 0
  let pointer = null
  let pendingSave = null
  let saveLoop = null
  let confirmedItems = []

  function clearDropTarget() {
    dropTargetId.value = null
    dropSide.value = null
    pendingInsertionIndex = null
    changed = false
  }

  function updateDropTarget(clientX, clientY, item, targetElement) {
    if (!isDragging.value) return
    const sourceIndex = items.value.findIndex(entry => String(getId(entry)) === draggedId.value)
    const targetIndex = items.value.findIndex(entry => String(getId(entry)) === String(getId(item)))
    if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) {
      clearDropTarget()
      return
    }

    const rect = targetElement?.getBoundingClientRect?.()
    let insertAfter = sourceIndex < targetIndex
    if (rect) {
      const verticalEdge = Math.min(12, rect.height * 0.3)
      if (clientY <= rect.top + verticalEdge) insertAfter = false
      else if (clientY >= rect.bottom - verticalEdge) insertAfter = true
      else insertAfter = clientX >= rect.left + rect.width / 2
    }
    dropTargetId.value = String(getId(item))
    dropSide.value = insertAfter ? 'after' : 'before'

    let insertionIndex = targetIndex + (insertAfter ? 1 : 0)
    if (sourceIndex < insertionIndex) insertionIndex -= 1
    pendingInsertionIndex = insertionIndex
    changed = sourceIndex !== insertionIndex
  }

  function updateDropTargetFromPoint(clientX, clientY) {
    const elements = [...pointer.container.querySelectorAll(':scope > [data-tag-sort-id]')]
    if (!elements.length) return
    const nearest = elements.reduce((best, element) => {
      const rect = element.getBoundingClientRect()
      const dx = clientX < rect.left
        ? rect.left - clientX
        : clientX > rect.right ? clientX - rect.right : 0
      const dy = clientY < rect.top
        ? rect.top - clientY
        : clientY > rect.bottom ? clientY - rect.bottom : 0
      const distance = dx * dx + dy * dy
      return !best || distance < best.distance ? { element, distance } : best
    }, null)
    const item = items.value.find(entry => String(getId(entry)) === nearest.element.dataset.tagSortId)
    if (item) updateDropTarget(clientX, clientY, item, nearest.element)
  }

  function removePointerListeners() {
    if (typeof window === 'undefined') return
    window.removeEventListener('pointermove', pointerMove)
    window.removeEventListener('pointerup', pointerUp)
    window.removeEventListener('pointercancel', pointerCancel)
  }

  function pointerDown(event, item) {
    if (event.button !== 0 || event.isPrimary === false) return
    removePointerListeners()
    pointer = {
      id: event.pointerId,
      item,
      container: event.currentTarget.parentElement,
      startX: event.clientX,
      startY: event.clientY,
      active: false,
    }
    window.addEventListener('pointermove', pointerMove, { passive: false })
    window.addEventListener('pointerup', pointerUp)
    window.addEventListener('pointercancel', pointerCancel)
  }

  function pointerMove(event) {
    if (!pointer || event.pointerId !== pointer.id) return
    if (!pointer.active) {
      const distance = Math.hypot(event.clientX - pointer.startX, event.clientY - pointer.startY)
      if (distance < 3) return
      pointer.active = true
      originalItems = [...items.value]
      if (!saving.value) confirmedItems = [...originalItems]
      pendingInsertionIndex = null
      changed = false
      draggedId.value = String(getId(pointer.item))
    }
    event.preventDefault()
    updateDropTargetFromPoint(event.clientX, event.clientY)
  }

  function pointerUp(event) {
    if (!pointer || event.pointerId !== pointer.id) return
    const wasActive = pointer.active
    pointer = null
    removePointerListeners()
    if (!wasActive) return
    event.preventDefault()
    suppressClickUntil = Date.now() + 300
    return end()
  }

  function pointerCancel(event) {
    if (!pointer || event.pointerId !== pointer.id) return
    pointer = null
    removePointerListeners()
    draggedId.value = null
    clearDropTarget()
    originalItems = []
  }

  function handleClick(event, handler) {
    if (Date.now() <= suppressClickUntil) {
      event.preventDefault()
      event.stopPropagation()
      return
    }
    handler()
  }

  function end() {
    if (!isDragging.value) return
    const activeDraggedId = draggedId.value
    const insertionIndex = pendingInsertionIndex
    draggedId.value = null
    dropTargetId.value = null
    dropSide.value = null
    if (!changed || insertionIndex === null) {
      originalItems = []
      pendingInsertionIndex = null
      return
    }
    const sourceIndex = items.value.findIndex(entry => String(getId(entry)) === activeDraggedId)
    if (sourceIndex < 0) return
    const nextItems = [...items.value]
    const [draggedItem] = nextItems.splice(sourceIndex, 1)
    nextItems.splice(insertionIndex, 0, draggedItem)
    items.value = nextItems
    const request = {
      items: nextItems,
      resourceIds: nextItems.map(item => String(getId(item))),
      rollbackItems: originalItems,
    }
    originalItems = []
    changed = false
    pendingInsertionIndex = null
    queueSave(request)
  }

  function queueSave(request) {
    pendingSave = request
    if (saveLoop) return
    saving.value = true
    saveLoop = flushSaves().finally(() => {
      saveLoop = null
      saving.value = false
      if (pendingSave) queueSave(pendingSave)
    })
  }

  async function flushSaves() {
    while (pendingSave) {
      const request = pendingSave
      pendingSave = null
      try {
        await save(request.resourceIds)
        confirmedItems = request.items
      } catch (error) {
        if (pendingSave || isDragging.value) continue
        items.value = confirmedItems.length ? confirmedItems : request.rollbackItems
        onError?.(error)
      }
    }
  }

  async function whenIdle() {
    while (saveLoop) await saveLoop
  }

  function dispose() {
    pointer = null
    removePointerListeners()
  }

  return {
    draggedId,
    dropTargetId,
    dropSide,
    isDragging,
    saving,
    pointerDown,
    handleClick,
    end,
    whenIdle,
    dispose,
  }
}

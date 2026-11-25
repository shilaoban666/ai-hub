// Call from a user gesture so browsers can authorize clipboard writes.
export async function copyToClipboard(text) {
  const value = String(text)
  if (window.isSecureContext && navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value)
      return
    } catch {
      // Embedded pages can be denied access by an ancestor's permissions policy.
    }
  }

  const activeElement = document.activeElement
  const selection = window.getSelection()
  const ranges = selection
    ? Array.from({ length: selection.rangeCount }, (_, index) => selection.getRangeAt(index).cloneRange())
    : []
  const inputSelection = activeElement instanceof HTMLInputElement || activeElement instanceof HTMLTextAreaElement
    ? { start: activeElement.selectionStart, end: activeElement.selectionEnd, direction: activeElement.selectionDirection }
    : null
  const textarea = document.createElement('textarea')
  textarea.value = value
  textarea.readOnly = true
  textarea.style.position = 'fixed'
  textarea.style.inset = '0 auto auto 0'
  textarea.style.opacity = '0'
  textarea.style.pointerEvents = 'none'
  // Keep focus inside a modal's focus trap while selecting the temporary text.
  const container = activeElement?.closest('[role="dialog"], dialog') || document.body
  container.appendChild(textarea)
  try {
    textarea.focus({ preventScroll: true })
    textarea.select()
    if (!document.execCommand('copy')) throw new Error('Clipboard copy was rejected')
  } finally {
    textarea.remove()
    activeElement?.focus({ preventScroll: true })
    if (inputSelection?.start != null && inputSelection.end != null) {
      activeElement.setSelectionRange(inputSelection.start, inputSelection.end, inputSelection.direction)
    } else if (selection) {
      selection.removeAllRanges()
      ranges.forEach(range => selection.addRange(range))
    }
  }
}

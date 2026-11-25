import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useAppStore = defineStore('app', () => {
  const storageKey = 'aihub:sidebar-collapsed'
  let savedCollapsed = false
  try {
    savedCollapsed = localStorage.getItem(storageKey) === 'true'
  } catch { /* Keep the default when browser storage is unavailable. */ }
  const collapsed = ref(savedCollapsed)

  const toggleSidebar = () => {
    collapsed.value = !collapsed.value
    try {
      localStorage.setItem(storageKey, String(collapsed.value))
    } catch { /* The in-memory preference still applies for this visit. */ }
  }

  return {
    collapsed,
    toggleSidebar
  }
})

<template>
  <ServiceAvailabilityNotice />
  <router-view />
</template>

<script setup>
import { onBeforeUnmount, onMounted } from 'vue'
import ServiceAvailabilityNotice from '@/components/ServiceAvailabilityNotice.vue'

let autocompleteObserver

const disableAutocomplete = (root) => {
  if (root.nodeType !== Node.ELEMENT_NODE) return

  if (root.matches('form, input, textarea')) {
    root.setAttribute('autocomplete', 'off')
  }
  root.querySelectorAll('form, input, textarea').forEach((element) => {
    element.setAttribute('autocomplete', 'off')
  })
}

onMounted(() => {
  disableAutocomplete(document.body)
  autocompleteObserver = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      mutation.addedNodes.forEach(disableAutocomplete)
    })
  })
  autocompleteObserver.observe(document.body, { childList: true, subtree: true })
})

onBeforeUnmount(() => autocompleteObserver?.disconnect())
</script>

<template>
  <div class="chat-error-details">
    <span>错误来源：{{ details.source }}</span>
    <details>
      <summary>错误详情</summary>
      <div>错误码：{{ details.code }}</div>
      <pre>{{ details.detail }}</pre>
    </details>
  </div>
</template>

<script setup>
defineProps({ details: { type: Object, required: true } })
</script>

<style scoped>
.chat-error-details { font-size: calc(12px + var(--workspace-font-size-offset, 0px)); line-height: 1.6; overflow-wrap: anywhere; min-width: 0; }
details { margin-top: 4px; }
summary { cursor: pointer; width: fit-content; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 260px; overflow: auto; margin: 6px 0 0; font: inherit; }
</style>

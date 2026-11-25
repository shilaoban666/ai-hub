<template>
  <img v-if="image" class="character-image" :src="image" alt="" aria-hidden="true" />
  <span v-else>{{ icon?.trim() || 'H' }}</span>
</template>

<script setup>
import { computed } from 'vue'
import { getAssistantImage } from '@/config/assistant-characters'
const props = defineProps({ icon: { type: String, default: 'H' } })
const image = computed(() => getAssistantImage(props.icon))
</script>

<style scoped>
.character-image { display: block; width: 100%; height: 100%; object-fit: contain; }
</style>

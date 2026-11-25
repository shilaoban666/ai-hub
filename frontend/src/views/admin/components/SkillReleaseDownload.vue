<template>
  <section v-if="selectedRelease" class="release-panel" :class="{ 'is-compact': compact }" aria-label="版本说明" @click.stop @keyup.stop>
    <div class="release-panel__header">
      <h3>版本说明</h3>
      <el-select v-model="selectedReleaseId" class="release-select" aria-label="选择版本" :teleported="false">
        <el-option v-for="release in releases" :key="release.id" :value="release.id" :label="releaseLabel(release)" />
      </el-select>
    </div>
    <p class="release-panel__description" :class="{ 'is-empty': !selectedRelease.description?.trim() }">{{ selectedRelease.description?.trim() || '无' }}</p>
    <div class="release-panel__footer">
      <slot name="actions">
      <el-button type="primary" plain :icon="Download" :loading="downloading" :disabled="!selectedRelease.installable" :title="`下载 ${selectedRelease.version}`" @click="$emit('download', selectedRelease)">下载</el-button>
      <span class="release-download-hint">{{ selectedRelease.installable ? 'ZIP 技能包' : selectedRelease.unavailable_reason || '此版本暂不可下载' }}</span>
      </slot>
    </div>
  </section>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { Download } from '@element-plus/icons-vue'

const props = defineProps({
  skill: { type: Object, required: true },
  currentReleaseId: { type: [Number, String], default: null },
  downloading: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
})
defineEmits(['download'])
const selectedReleaseId = ref(null)
const releases = computed(() => (props.skill.releases || []).filter(release => release.status !== 'workspace'))
watch(() => props.skill.skill_id, () => {
  selectedReleaseId.value = props.skill.latest_release?.id ?? null
}, { immediate: true })
const selectedRelease = computed(() => releases.value.find(
  release => release.id === selectedReleaseId.value,
) || props.skill.latest_release || null)
watch(selectedRelease, release => { selectedReleaseId.value = release?.id ?? null })
const releaseLabel = release => {
  const labels = [release.version]
  if (release.id === props.skill.latest_release?.id) labels.push('最新')
  if (release.id === props.currentReleaseId) labels.push('当前使用')
  return labels.join(' · ')
}
</script>

<style scoped>
.release-panel { margin: 6px 0 20px; padding: 16px; border: 1px solid #e3eaf3; border-radius: 10px; background: #f7f9fc; }
.release-panel.is-compact { margin: 0; border: 0; border-radius: 4px; }
.release-panel__header { display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px; }
.release-panel__header h3 { margin: 0; color: #273445; font-size: 15px; font-weight: 650; }
.release-select { width: 200px; max-width: 100%; }
.release-panel__description { margin: 12px 0 16px; color: #404e60; font-size: 14px; line-height: 1.8; white-space: pre-wrap; overflow-wrap: anywhere; }
.is-compact .release-panel__description { max-height: 220px; overflow-y: auto; }
.release-panel__description.is-empty { color: #8a94a2; }
.release-panel__footer { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; border-top: 1px solid #e5ebf3; padding-top: 10px; }
.release-download-hint { margin-left: auto; color: #8993a1; font-size: 12px; overflow-wrap: anywhere; }
</style>

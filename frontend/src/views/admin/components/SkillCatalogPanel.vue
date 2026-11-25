<template>
  <section class="skill-library">
    <div class="library-toolbar">
      <el-input
        v-model="query"
        class="workspace-search"
        :prefix-icon="Search"
        clearable
        placeholder="搜索技能、作者或说明"
        @keyup.enter="searchCatalog"
        @clear="searchCatalog"
      />
      <div class="view-switch" role="group" aria-label="技能范围">
        <button
          v-for="option in viewOptions"
          :key="option.value"
          type="button"
          :class="{ active: view === option.value }"
          :aria-pressed="view === option.value"
          @click="selectView(option.value)"
        >{{ option.label }}</button>
      </div>
      <ResourceCenterCreateButton v-if="!readOnly" class="library-create" resource="skills" />
    </div>

    <div class="library-summary">
      <div class="source-tabs" role="group" aria-label="技能来源">
        <span class="source-label">技能来源</span>
        <button
          v-for="option in sourceOptions"
          :key="option.value"
          type="button"
          :class="{ active: source === option.value }"
          :aria-pressed="source === option.value"
          @click="selectSource(option.value)"
        >{{ option.label }}</button>
      </div>
    </div>

    <div v-loading="loading" class="skill-grid">
      <article
        v-for="skill in catalog"
        :key="skill.skill_id"
        class="skill-card"
        tabindex="0"
        @click="openDetail(skill)"
        @keyup.enter.self="openDetail(skill)"
      >
        <span
          v-if="skill.is_mine || skill.is_collaborator"
          class="skill-source-badge"
          :class="`skill-source-badge--${skill.is_mine ? 'mine' : 'collaboration'}`"
          :title="skill.is_mine ? '我的技能' : '协作技能'"
        >{{ skill.is_mine ? '我的' : '协作' }}</span>
        <div class="skill-card__top">
          <div class="skill-mark">
            <img v-if="skill.cover" :src="skill.cover" :alt="skill.name" />
            <el-icon v-else><SkillIcon /></el-icon>
          </div>
          <div class="skill-card__identity">
            <div class="skill-card__title">
              <h3 :title="skill.name">{{ skill.name }}</h3>
            </div>
            <div class="skill-card__byline">
              <span class="skill-version-line">
                <span class="skill-card__author" :title="`${skill.author?.trim() || '无'} · ${versionLabel(skill)}`">{{ skill.author?.trim() || '无' }} · {{ versionLabel(skill) }}</span>
                <el-popover
                  v-if="hasUpdate(skill)"
                  trigger="click"
                  placement="bottom-start"
                  :width="320"
                  :persistent="false"
                  popper-class="skill-update-popover"
                >
                  <template #reference>
                    <button
                      type="button"
                      class="skill-update-badge"
                      :aria-label="`查看最新版本 ${latestVersionLabel(skill)} 的版本描述`"
                      @click.stop
                      @keyup.stop
                    ><el-icon><Bell /></el-icon>最新版本 {{ latestVersionLabel(skill) }}</button>
                  </template>
                  <div class="skill-update-popover__title">最新版本 {{ latestVersionLabel(skill) }}</div>
                  <div class="skill-update-popover__description">{{ skill.latest_release?.description?.trim() || '无' }}</div>
                </el-popover>
              </span>
              <span class="skill-stats" @click.stop.prevent>
                <span title="下载次数" :aria-label="`下载次数：${formatCount(skill.download_count)}`"><el-icon><Download /></el-icon><strong>{{ formatCount(skill.download_count) }}</strong></span>
                <span title="安装人数" :aria-label="`安装人数：${formatCount(skill.installed_user_count)}`"><el-icon><User /></el-icon><strong>{{ formatCount(skill.installed_user_count) }}</strong></span>
              </span>
            </div>
          </div>
        </div>
        <p class="skill-description">{{ skill.description?.trim() || '无' }}</p>
        <div v-if="canDevelop(skill)" class="skill-card__development" :class="{ 'is-enabled': skill.development_mode }" @click.stop @keyup.stop @keydown.stop>
          <span class="skill-card__development-copy">
            <span class="skill-card__development-dot" aria-hidden="true" />
            <span class="skill-card__development-label">调试模式</span>
            <el-popover
              trigger="hover"
              placement="top-start"
              :width="360"
              :show-after="150"
              :hide-after="100"
              popper-class="skill-development-popover"
            >
              <template #reference>
                <el-icon class="skill-card__development-info" aria-label="调试模式说明" @click.stop><InfoFilled /></el-icon>
              </template>
              <div class="skill-development-popover__content">
                <strong>技能文件</strong>
                <p>{{ developmentHint(skill) }}</p>
              </div>
            </el-popover>
            <button
              type="button"
              class="skill-card__development-state"
              @click.stop="openFiles(skill, 'workspace')"
            >技能文件</button>
          </span>
          <el-switch
            :model-value="Boolean(skill.development_mode)"
            :loading="actionSkillId === skill.skill_id && actionType === 'development'"
            :disabled="actionSkillId !== null || !hasPublishedRelease(skill)"
            aria-label="调试模式"
            @change="enabled => toggleDevelopment(skill, enabled)"
          />
        </div>
        <div class="skill-card__actions" @click.stop @keyup.stop>
          <div class="card-download">
            <el-button
              class="release-notes-action"
              text
              :icon="Document"
              title="查看版本日志"
              aria-label="查看版本日志"
              @click="openReleaseNotes(skill)"
            >版本日志</el-button>
          </div>
          <el-button
            v-if="canInstall(skill)"
            type="primary"
            plain
            :loading="actionSkillId === skill.skill_id && actionType === 'install'"
            :disabled="readOnly || (skill.latest_release && !skill.latest_release.installable && !skill.latest_workspace?.installable)"
            @click="installSkill(skill)"
          >{{ systemMode ? '安装到默认助手' : '安装' }}</el-button>
          <template v-else-if="canManage(skill)">
            <el-button
              type="danger"
              plain
              :loading="actionSkillId === skill.skill_id && actionType === 'uninstall'"
              :disabled="readOnly || actionSkillId === skill.skill_id && actionType !== 'uninstall'"
              @click="uninstallSkill(skill)"
            >卸载</el-button>
            <el-popover
              v-if="hasUpdate(skill)"
              :visible="upgradePopoverId === skill.skill_id"
              trigger="click"
              placement="bottom-end"
              :persistent="false"
              :popper-style="{ width: 'min(400px, calc(100vw - 48px))', padding: '0', boxSizing: 'border-box' }"
              @update:visible="setUpgradePopover(skill.skill_id, $event)"
            >
              <template #reference>
                <el-button
                  type="success"
                  plain
                  :loading="actionSkillId === skill.skill_id && actionType === 'upgrade'"
                  :disabled="readOnly || !skill.latest_release?.installable || (actionSkillId === skill.skill_id && actionType !== 'upgrade')"
                >升级</el-button>
              </template>
              <SkillReleaseDownload
                v-if="upgradePopoverId === skill.skill_id"
                :skill="skill"
                :current-release-id="effectiveReleaseId(skill)"
                compact
              >
                <template #actions>
                  <span class="upgrade-current">当前使用 {{ installedVersion(skill) }}</span>
                  <el-button
                    type="success"
                    plain
                    :loading="actionSkillId === skill.skill_id && actionType === 'upgrade'"
                    :disabled="readOnly || !skill.latest_release?.installable || (actionSkillId === skill.skill_id && actionType !== 'upgrade')"
                    @click="upgradeSkill(skill)"
            >升级至 {{ skill.latest_release?.version }}</el-button>
                </template>
              </SkillReleaseDownload>
            </el-popover>
          </template>
          <span v-else class="managed-note">系统默认</span>
        </div>
      </article>

      <el-empty v-if="!loading && !loadError && catalog.length === 0" class="empty-state" description="没有符合条件的技能" />
    </div>

    <div ref="loadMoreTrigger" class="library-load-more" role="status" aria-live="polite" :aria-busy="loading || loadingMore">
      <template v-if="loadError">
        <span>{{ loadError }}</span>
        <el-button link type="primary" @click="retryLoad">重试</el-button>
      </template>
      <span v-else-if="catalog.length && hasMore">继续向下滚动加载更多</span>
    </div>

    <el-dialog
      v-model="infoDialogOpen"
      class="skill-info-dialog"
      width="min(760px, calc(100vw - 32px))"
      title="技能详情"
      destroy-on-close
      @close="closePopovers"
    >
      <div v-if="selectedSkill" class="skill-detail">
        <div class="detail-header">
          <div class="skill-mark skill-mark--large">
            <img v-if="selectedSkill.cover" :src="selectedSkill.cover" :alt="selectedSkill.name" />
            <el-icon v-else><SkillIcon /></el-icon>
          </div>
          <div class="detail-identity">
            <h2 :title="selectedSkill.name">{{ selectedSkill.name }}</h2>
            <div class="detail-byline">
              <span class="skill-version-line">
                <span
                  class="detail-author"
                  :title="selectedSkill.author?.trim() || '无'"
                >{{ selectedSkill.author?.trim() || '无' }}<template v-if="hasPublishedRelease(selectedSkill)"> · {{ latestVersionLabel(selectedSkill) }}</template></span>
                <el-popover
                  v-if="hasUpdate(selectedSkill)"
                  trigger="click"
                  placement="bottom-start"
                  :width="320"
                  :persistent="false"
                  popper-class="skill-update-popover"
                >
                  <template #reference>
                    <button
                      type="button"
                      class="skill-update-badge"
                      :aria-label="`查看最新版本 ${latestVersionLabel(selectedSkill)} 的版本描述`"
                      @click.stop
                      @keyup.stop
                    ><el-icon><Bell /></el-icon>最新版本 {{ latestVersionLabel(selectedSkill) }}</button>
                  </template>
                  <div class="skill-update-popover__title">最新版本 {{ latestVersionLabel(selectedSkill) }}</div>
                  <div class="skill-update-popover__description">{{ selectedSkill.latest_release?.description?.trim() || '无' }}</div>
                </el-popover>
              </span>
              <span class="detail-stats">
                <span title="下载次数" :aria-label="`下载次数：${formatCount(selectedSkill.download_count)}`"><el-icon><Download /></el-icon><strong>{{ formatCount(selectedSkill.download_count) }}</strong></span>
                <span title="安装人数" :aria-label="`安装人数：${formatCount(selectedSkill.installed_user_count)}`"><el-icon><User /></el-icon><strong>{{ formatCount(selectedSkill.installed_user_count) }}</strong></span>
              </span>
            </div>
          </div>
        </div>
        <p class="detail-description">{{ selectedSkill.description?.trim() || '无' }}</p>
        <div
          v-if="canDevelop(selectedSkill)"
          class="skill-card__development skill-development-detail"
          :class="{ 'is-enabled': selectedSkill.development_mode }"
          @click.stop
          @keyup.stop
          @keydown.stop
        >
          <span class="skill-card__development-copy">
            <span class="skill-card__development-dot" aria-hidden="true" />
            <span class="skill-card__development-label">调试模式</span>
            <el-popover
              trigger="hover"
              placement="top-start"
              :width="360"
              :show-after="150"
              :hide-after="100"
              popper-class="skill-development-popover"
            >
              <template #reference>
                <el-icon class="skill-card__development-info" aria-label="调试模式说明" @click.stop><InfoFilled /></el-icon>
              </template>
              <div class="skill-development-popover__content">
                <strong>技能文件</strong>
                <p>{{ developmentHint(selectedSkill) }}</p>
              </div>
            </el-popover>
            <button
              type="button"
              class="skill-card__development-state"
              @click.stop="openFiles(selectedSkill, 'workspace')"
            >技能文件</button>
          </span>
          <el-switch
            :model-value="Boolean(selectedSkill.development_mode)"
            :loading="actionSkillId === selectedSkill.skill_id && actionType === 'development'"
            :disabled="actionSkillId !== null || !hasPublishedRelease(selectedSkill)"
            aria-label="调试模式"
            @change="enabled => toggleDevelopment(selectedSkill, enabled)"
          />
        </div>
        <section v-if="!systemMode && selectedSkill.conversation_examples?.length" class="skill-examples" aria-label="试试这样用">
          <h3><el-icon><Opportunity /></el-icon>试试这样用</h3>
          <button
            v-for="(example, index) in selectedSkill.conversation_examples"
            :key="index"
            type="button"
            class="skill-example"
            :disabled="readOnly || tryingExample || actionSkillId !== null"
            @click="tryExample(selectedSkill, example)"
          >
            <span>{{ example }}</span>
            <el-icon><ChatDotRound /></el-icon>
          </button>
        </section>
        <div class="detail-actions" @click.stop @keyup.stop>
            <div class="detail-download">
              <el-button
                class="release-notes-action"
                text
                :icon="Document"
                title="查看版本日志"
                aria-label="查看版本日志"
                @click="openReleaseNotes(selectedSkill)"
              >版本日志</el-button>
            </div>
            <el-button
              v-if="canInstall(selectedSkill)"
              type="primary"
              plain
              :loading="actionSkillId === selectedSkill.skill_id && actionType === 'install'"
              :disabled="readOnly || (selectedSkill.latest_release && !selectedSkill.latest_release.installable && !selectedSkill.latest_workspace?.installable)"
              @click="installSkill(selectedSkill)"
            >{{ systemMode ? '安装到默认助手' : '安装' }}</el-button>
            <template v-else-if="canManage(selectedSkill)">
              <el-button
                type="danger"
                plain
                :loading="actionSkillId === selectedSkill.skill_id && actionType === 'uninstall'"
                :disabled="readOnly || actionSkillId === selectedSkill.skill_id && actionType !== 'uninstall'"
                @click="uninstallSkill(selectedSkill)"
              >卸载</el-button>
              <el-popover
                v-if="hasUpdate(selectedSkill)"
                :visible="upgradePopoverId === detailPopoverId"
                trigger="click"
                placement="bottom-end"
                :persistent="false"
                :popper-style="{ width: 'min(400px, calc(100vw - 48px))', padding: '0', boxSizing: 'border-box' }"
                @update:visible="setUpgradePopover(detailPopoverId, $event)"
              >
                <template #reference>
                  <el-button
                    type="success"
                    plain
                    :loading="actionSkillId === selectedSkill.skill_id && actionType === 'upgrade'"
                    :disabled="readOnly || !selectedSkill.latest_release?.installable || (actionSkillId === selectedSkill.skill_id && actionType !== 'upgrade')"
                  >升级</el-button>
                </template>
                <SkillReleaseDownload
                  v-if="upgradePopoverId === detailPopoverId"
                  :skill="selectedSkill"
                  :current-release-id="effectiveReleaseId(selectedSkill)"
                  compact
                >
                  <template #actions>
                    <span class="upgrade-current">当前使用 {{ installedVersion(selectedSkill) }}</span>
                    <el-button
                      type="success"
                      plain
                      :loading="actionSkillId === selectedSkill.skill_id && actionType === 'upgrade'"
                      :disabled="readOnly || !selectedSkill.latest_release?.installable || (actionSkillId === selectedSkill.skill_id && actionType !== 'upgrade')"
                      @click="upgradeSkill(selectedSkill)"
                      >升级至 {{ selectedSkill.latest_release?.version }}</el-button>
                  </template>
                </SkillReleaseDownload>
              </el-popover>
            </template>
            <span v-else class="managed-note">系统默认</span>
          </div>
      </div>
    </el-dialog>

    <el-dialog
      v-model="releaseNotesDialogOpen"
      class="release-notes-dialog"
      width="min(860px, calc(100vw - 32px))"
      title="版本日志"
      destroy-on-close
      @closed="releaseNotesSkill = null"
    >
      <div v-if="releaseNotesSkill" class="release-notes-list">
        <article v-for="release in releaseNotes" :key="release.id" class="release-notes-item">
          <div class="release-notes-item__header">
            <span class="release-notes-version">版本 {{ release.version || '无' }}</span>
            <span class="release-notes-date">{{ formatReleaseDate(release.created_at) }}</span>
          </div>
          <div class="release-notes-item__body">{{ release.description?.trim() || '无' }}</div>
          <div class="release-notes-item__actions">
            <el-button
              link
              size="small"
              :icon="Download"
              :loading="downloadingSkills.has(releaseNotesSkill.skill_id)"
              :disabled="!release.installable"
              :title="release.installable ? `下载 ${release.version || '无'}` : (release.unavailable_reason || '此版本暂不可下载')"
              @click="downloadSkill(releaseNotesSkill, release)"
            >下载</el-button>
            <el-button
              link
              size="small"
              :icon="Document"
              title="查看文件"
              @click="openFiles(releaseNotesSkill, release.id)"
            >文件</el-button>
          </div>
        </article>
        <el-empty v-if="!releaseNotes.length" description="暂无版本日志" :image-size="64" />
      </div>
    </el-dialog>

    <el-dialog
      v-model="filesDialogOpen"
      class="skill-files-dialog"
      width="min(1180px, calc(100vw - 32px))"
      top="5vh"
      :title="selectedSkill?.name || '技能'"
      destroy-on-close
    >
      <SkillReleaseFiles
        v-if="filesDialogOpen && selectedSkill"
        :key="`${selectedSkill.skill_id}:${selectedFileReleaseId || 'latest'}`"
        :skill="selectedSkill"
        :current-release-id="selectedFileReleaseId || effectiveReleaseId(selectedSkill)"
      />
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  Bell, ChatDotRound, Document, Download, InfoFilled, Opportunity, Search, User,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { assetsApi } from '@/api/assets'
import SkillIcon from '@/components/icons/SkillIcon.vue'
import ResourceCenterCreateButton from './ResourceCenterCreateButton.vue'
import SkillReleaseDownload from './SkillReleaseDownload.vue'
import SkillReleaseFiles from './SkillReleaseFiles.vue'
import '@/assets/styles/workspace-search.css'
import { formatBeijingDateTime } from '@/utils/date-time'

const props = defineProps({
  readOnly: { type: Boolean, default: false },
  systemMode: { type: Boolean, default: false },
  agentId: { type: [Number, String], default: null },
})
const systemMode = computed(() => props.systemMode)
const router = useRouter()
const tryingExample = ref(false)
const agentId = computed(() => Number(props.agentId) > 0 ? Number(props.agentId) : null)
const agentMode = computed(() => Boolean(agentId.value) && !systemMode.value)

const query = ref('')
const source = ref('all')
const view = ref('catalog')
const loading = ref(false)
const loadingMore = ref(false)
const loadError = ref('')
const loadMoreTrigger = ref(null)
const actionSkillId = ref(null)
const actionType = ref('')
const catalog = ref([])
const totalSkills = ref(0)
const pageSize = 16
const nextOffset = ref(0)
const exhausted = ref(false)
const hasMore = computed(() => !exhausted.value && nextOffset.value < totalSkills.value)
const activeQuery = ref('')
const infoDialogOpen = ref(false)
const filesDialogOpen = ref(false)
const releaseNotesDialogOpen = ref(false)
const selectedSkill = ref(null)
const releaseNotesSkill = ref(null)
const releaseNotes = computed(() => (releaseNotesSkill.value?.releases || [])
  .filter(release => release.status !== 'workspace'))
const selectedFileReleaseId = ref(null)
const detailPopoverId = computed(() => `detail:${selectedSkill.value?.skill_id}`)
const upgradePopoverId = ref(null)
const closePopovers = () => {
  upgradePopoverId.value = null
}
const setUpgradePopover = (id, visible) => {
  if (visible) {
    upgradePopoverId.value = id
  } else if (upgradePopoverId.value === id) upgradePopoverId.value = null
}
const downloadingSkills = ref(new Set())
const formatCount = value => Number(value || 0).toLocaleString('zh-CN')
const viewOptions = [
  { label: '全部', value: 'catalog' },
  { label: '已安装', value: 'installed' },
]
const sourceOptions = computed(() => [
  { label: '全部', value: 'all' },
  { label: '我的', value: 'mine' },
  { label: '协作', value: 'collaboration' },
  { label: '公开', value: 'public' },
  ...(!agentMode.value ? [{ label: '系统默认', value: 'system_default' }] : []),
])
const effectiveReleaseId = skill => systemMode.value
  ? skill.system_installation?.release_id
  : agentMode.value ? (isAgentBound(skill) ? skill.user_installation?.release_id : null)
    : (skill.system_installation?.release_id || skill.effective_release_id)
const effectiveVersion = skill => skill.releases?.find(item => item.id === effectiveReleaseId(skill))?.version
  || skill.latest_release?.version
  || '无'
const hasPublishedRelease = skill => Boolean(skill.latest_release?.status === 'published')
const developmentHint = skill => {
  if (!hasPublishedRelease(skill)) {
    return '当前技能还没有发布版本。安装后会自动开启调试模式，运行时使用工作区当前文件；发布版本前不能关闭调试模式。仅技能作者可操作。'
  }
  if (skill.development_mode) {
    return '每次运行都会使用当前技能工作区已保存的最新文件；关闭调试模式后恢复已安装的发布版本。仅技能作者可操作。'
  }
  return '调试模式未开启。开启后每次运行都会使用当前工作区已保存的最新文件；关闭时使用已安装的发布版本。仅技能作者可操作。'
}
const canDevelop = skill => !props.readOnly && !systemMode.value && skill.is_mine
  && typeof skill.development_mode === 'boolean' && Boolean(skill.user_installation)
const versionLabel = skill => hasPublishedRelease(skill) ? latestVersionLabel(skill) : '无版本'
const latestVersionLabel = skill => skill.latest_release?.version?.trim() || '无版本'
const installedVersion = skill => !hasPublishedRelease(skill)
  ? '无'
  : (skill.development_mode ? latestVersionLabel(skill) : effectiveVersion(skill))
const isAgentBound = skill => agentMode.value && Boolean(skill.user_installation)
const canInstall = skill => systemMode.value
  ? !skill.system_installation
  : agentMode.value
    ? !isAgentBound(skill)
    : !skill.user_installation && !skill.system_installation
const canManage = skill => systemMode.value
  ? Boolean(skill.system_installation)
  : agentMode.value
    ? isAgentBound(skill)
    : Boolean(skill.user_installation && !skill.system_installation)
const hasUpdate = skill => !skill.development_mode && Boolean(effectiveReleaseId(skill) && skill.latest_release
  && skill.latest_release.id !== effectiveReleaseId(skill))

let catalogRequestId = 0
let catalogObserver
let retryAppend = false
const observeLoadMore = () => {
  if (!catalogObserver || !loadMoreTrigger.value) return
  // Recheck after each batch, including when the list still does not fill its scroll container.
  catalogObserver.unobserve(loadMoreTrigger.value)
  catalogObserver.observe(loadMoreTrigger.value)
}
const loadCatalog = async ({ append = false, reset = false } = {}) => {
  if (append && (loading.value || loadingMore.value || !hasMore.value)) return
  const requestId = ++catalogRequestId
  if (reset) {
    activeQuery.value = query.value.trim()
    catalog.value = []
    totalSkills.value = 0
    nextOffset.value = 0
    exhausted.value = false
    selectedSkill.value = null
    infoDialogOpen.value = false
    filesDialogOpen.value = false
    upgradePopoverId.value = null
  }
  loading.value = !append
  loadingMore.value = append
  loadError.value = ''
  retryAppend = append
  const params = {
    q: activeQuery.value, source: source.value, system_mode: systemMode.value,
    agent_id: agentId.value || undefined,
    installed_only: view.value === 'installed',
    sort_by: 'created_at',
  }
  // Refresh the loaded range after installation changes so later cards and scroll position survive.
  const targetCount = append ? nextOffset.value + pageSize : Math.max(pageSize, nextOffset.value)
  let offset = append ? nextOffset.value : 0
  let items = append ? [...catalog.value] : []
  let total = 0
  let reachedEnd = false
  try {
    do {
      const result = await assetsApi.getSkillCatalog({ ...params, skip: offset, limit: Math.min(100, targetCount - offset) })
      if (requestId !== catalogRequestId) return
      const batch = result?.items || []
      total = result?.total || 0
      items.push(...batch)
      offset += batch.length
      reachedEnd = batch.length === 0 || offset >= total
    } while (offset < targetCount && !reachedEnd)
    catalog.value = [...new Map(items.map(item => [item.skill_id, item])).values()]
    totalSkills.value = total
    nextOffset.value = offset
    exhausted.value = reachedEnd
    if (selectedSkill.value) {
      selectedSkill.value = catalog.value.find(item => item.skill_id === selectedSkill.value.skill_id) || null
      if (!selectedSkill.value) {
        infoDialogOpen.value = false
        filesDialogOpen.value = false
      }
    }
  } catch (error) {
    if (requestId !== catalogRequestId) return
    loadError.value = append ? '加载更多失败' : '技能目录加载失败'
    ElMessage.error(error.response?.data?.detail || loadError.value)
  } finally {
    if (requestId === catalogRequestId) {
      loading.value = false
      loadingMore.value = false
      await nextTick()
      observeLoadMore()
    }
  }
}
const loadAll = () => loadCatalog()
const loadMore = () => loadCatalog({ append: true })
const retryLoad = () => loadCatalog({ append: retryAppend })
const searchCatalog = () => loadCatalog({ reset: true })
const selectSource = value => {
  if (source.value === value) return
  source.value = value
  searchCatalog()
}
const selectView = value => {
  if (view.value === value) return
  view.value = value
  searchCatalog()
}
const openDetail = skill => {
  selectedSkill.value = skill
  closePopovers()
  infoDialogOpen.value = true
}
const openFiles = (skill, releaseId = null) => {
  selectedSkill.value = skill
  const requestedRelease = skill.releases?.find(release => release.id === releaseId)
  selectedFileReleaseId.value = requestedRelease?.status === 'workspace'
    ? 'workspace'
    : releaseId || (skill.development_mode ? 'workspace' : null)
    || effectiveReleaseId(skill) || skill.latest_release?.id || null
  filesDialogOpen.value = true
}
const openReleaseNotes = skill => {
  releaseNotesSkill.value = skill
  releaseNotesDialogOpen.value = true
}
const formatReleaseDate = value => formatBeijingDateTime(value, {
  fallback: '无',
  second: undefined,
})
const downloadSkill = async (skill, release = skill.latest_release) => {
  if (!release?.installable || downloadingSkills.value.has(skill.skill_id)) return
  downloadingSkills.value.add(skill.skill_id)
  try {
    const blob = await assetsApi.downloadSkillRelease(release.id)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${skill.name}-${release.version}.zip`.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_')
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 60000)
    // Refresh the visible count even if the catalog was replaced during the download.
    const current = catalog.value.find(item => item.skill_id === skill.skill_id)
    if (current) current.download_count = Number(current.download_count || 0) + 1
    ElMessage.success('下载已开始')
  } catch (error) {
    let detail = error.response?.data?.detail
    if (error.response?.data instanceof Blob) {
      try {
        const body = JSON.parse(await error.response.data.text())
        detail = body.detail || body.message
      } catch { /* Use the download error below when the response is not JSON. */ }
    }
    ElMessage.error(typeof detail === 'string' ? detail : detail?.message || '技能下载失败，请重试')
  } finally {
    downloadingSkills.value.delete(skill.skill_id)
  }
}
const toggleDevelopment = async (skill, enabled) => {
  if (!canDevelop(skill) || actionSkillId.value !== null) return
  actionSkillId.value = skill.skill_id
  actionType.value = 'development'
  try {
    const result = await assetsApi.setSkillDevelopmentMode(skill.skill_id, enabled, agentId.value || undefined)
    skill.development_mode = result.development_mode
    await loadAll()
    ElMessage.success(enabled ? '调试模式已开启，运行时读取工作区当前文件' : '调试模式已关闭，可升级到最新发布版本')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '调试模式设置失败')
  } finally {
    actionSkillId.value = null
    actionType.value = ''
  }
}
const installSkill = async skill => {
  if (props.readOnly || actionSkillId.value !== null) return false
  const release = skill.latest_release
  if (release && !release.installable && !skill.latest_workspace?.installable) {
    ElMessage.warning(release?.unavailable_reason || '当前没有可安装版本')
    return false
  }
  actionSkillId.value = skill.skill_id
  actionType.value = 'install'
  try {
    if (!release || (release && !release.installable && skill.latest_workspace?.installable)) {
      await assetsApi.installSkill({ skill_id: skill.skill_id, ...(agentMode.value ? { agent_id: agentId.value } : {}) })
    } else if (systemMode.value) await assetsApi.installSystemSkill({ release_id: release.id })
    else if (agentMode.value && skill.user_installation) await assetsApi.bindSkill(skill.user_installation.id, agentId.value)
    else if (agentMode.value) await assetsApi.installSkill({ release_id: release.id, agent_id: agentId.value })
    else await assetsApi.installSkill({ release_id: release.id })
    ElMessage.success(systemMode.value ? '技能已安装到默认助手' : '技能已安装')
    await loadAll()
    return true
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '技能安装失败')
    return false
  } finally {
    actionSkillId.value = null
    actionType.value = ''
  }
}
const tryExample = async (skill, example) => {
  if (props.readOnly || systemMode.value || tryingExample.value || actionSkillId.value !== null) return
  tryingExample.value = true
  try {
    if (canInstall(skill) && !await installSkill(skill)) return
    await router.push({
      path: '/workspace/chat',
      query: { ...(agentMode.value ? { agent: agentId.value } : {}), skillExample: example, skillExampleId: skill.skill_id },
    })
    infoDialogOpen.value = false
  } catch {
    ElMessage.error('进入对话失败，请重试')
  } finally {
    tryingExample.value = false
  }
}
const upgradeSkill = async skill => {
  if (props.readOnly) return
  const release = skill.latest_release
  const installation = systemMode.value ? skill.system_installation : skill.user_installation
  if (!release?.installable || !installation || actionSkillId.value === skill.skill_id) return
  actionSkillId.value = skill.skill_id
  actionType.value = 'upgrade'
  try {
    if (systemMode.value) await assetsApi.changeSystemSkillRelease(installation.id, release.id)
    else await assetsApi.changeSkillRelease(installation.id, release.id, agentId.value || undefined)
    upgradePopoverId.value = null
    ElMessage.success(`${systemMode.value ? '默认助手技能已升级到' : '已升级到'} ${release.version}`)
    await loadAll()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || (systemMode.value ? '默认助手技能升级失败' : '技能升级失败'))
  } finally {
    actionSkillId.value = null
    actionType.value = ''
  }
}
const uninstallSkill = async skill => {
  if (props.readOnly) return
  const actionLabel = '卸载'
  try {
    await ElMessageBox.confirm(systemMode.value ? `从默认助手卸载 ${skill.name}？自定义 Agent 的安装不受影响。` : `${actionLabel} ${skill.name}？`, `${actionLabel}技能`, {
      type: 'warning',
      confirmButtonText: actionLabel,
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  actionSkillId.value = skill.skill_id
  actionType.value = 'uninstall'
  try {
    const installation = systemMode.value ? skill.system_installation : skill.user_installation
    if (systemMode.value) await assetsApi.uninstallSystemSkill(installation.id)
    else if (agentMode.value) await assetsApi.unbindSkill(installation.id, agentId.value)
    else await assetsApi.uninstallSkill(installation.id)
    ElMessage.success(systemMode.value ? '已从默认助手卸载技能' : '技能已卸载')
    await loadAll()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || (systemMode.value ? '默认助手技能卸载失败' : '技能卸载失败'))
  } finally {
    actionSkillId.value = null
    actionType.value = ''
  }
}

watch([systemMode, agentId], searchCatalog)
onMounted(() => {
  catalogObserver = new IntersectionObserver(entries => {
    if (entries.some(entry => entry.isIntersecting) && !loadError.value) loadMore()
  })
  observeLoadMore()
  searchCatalog()
})
onBeforeUnmount(() => {
  catalogRequestId += 1
  catalogObserver?.disconnect()
})
defineExpose({ refresh: loadAll })
</script>

<style scoped>
.workspace-search.el-input { --el-input-text-color: #303133; --el-input-placeholder-color: #303133; }
.skill-library { min-width: 0; --skill-filter-row-gap: 8px; }
.library-toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; min-height: 40px; }
.library-create { flex-shrink: 0; }
.view-switch { height: 32px; display: inline-flex; flex: 0 0 auto; align-items: center; gap: 2px; padding: 3px; border-radius: 7px; background: #f0f1f3; box-sizing: border-box; }
.view-switch button { min-width: 58px; height: 26px; padding: 0 10px; border: 0; border-radius: 5px; color: #303133; background: transparent; cursor: pointer; font: inherit; font-size: 13px; line-height: 26px; }
.view-switch button:hover { color: #2c3036; }
.view-switch button.active { color: #202328; background: #fff; box-shadow: 0 1px 2px rgba(20, 24, 32, .08); font-weight: 600; }
.view-switch button:focus-visible { outline: 2px solid #8a9098; outline-offset: 1px; }
.source-tabs { min-width: 0; display: flex; align-items: center; gap: 6px; overflow-x: auto; scrollbar-width: none; }
.source-tabs::-webkit-scrollbar { display: none; }
.source-label { flex-shrink: 0; margin-right: 8px; color: #303133; font-size: 13px; line-height: 30px; }
.source-tabs button { box-sizing: border-box; height: 30px; flex: 0 0 auto; padding: 4px 13px; border: 1px solid transparent; border-radius: 16px; color: #303133; background: transparent; cursor: pointer; font: inherit; font-size: 13px; line-height: 20px; white-space: nowrap; }
.source-tabs button:hover { color: #24272c; background: #f3f4f5; }
.source-tabs button.active { color: #2c5f95; background: #eef5fc; border-color: #d7e7f7; font-weight: 600; }
.source-tabs button:focus-visible { outline: 2px solid #8a9098; outline-offset: 1px; }
.library-summary { display: flex; align-items: center; gap: 24px; margin: 22px 0 24px; }
.skill-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; min-height: 240px; align-items: stretch; }
.skill-card { --skill-card-text: #24272d; --skill-card-muted: #737d8b; position: relative; color: var(--skill-card-text); display: flex; min-width: 0; min-height: 220px; flex-direction: column; padding: 18px; border: 1px solid #e4e8ee; border-radius: 12px; background: #fff; cursor: pointer; transition: border-color .15s, box-shadow .15s; box-sizing: border-box; }
.skill-card:hover { border-color: #c5d6e8; box-shadow: 0 4px 16px #1834520a; }
.skill-card:focus-visible { outline: 2px solid #83b3e4; outline-offset: 2px; }
.skill-source-badge { position: absolute; top: 12px; right: 12px; padding: 1px 7px; border-radius: 5px; color: #667180; background: #f0f2f5; font-size: 11px; line-height: 18px; white-space: nowrap; }
.skill-source-badge--mine { color: #285886; background: #eaf2fa; }
.skill-source-badge--collaboration { color: #6c4b86; background: #f3ecf8; }
.skill-card__top { display: flex; min-width: 0; align-items: center; gap: 12px; }
.skill-source-badge + .skill-card__top .skill-card__title { padding-right: 48px; }
.skill-mark { width: 40px; height: 40px; display: grid; flex: 0 0 40px; place-items: center; overflow: hidden; border-radius: 10px; color: #4c7198; background: #f0f5fb; font-size: 19px; }
.skill-mark img { width: 100%; height: 100%; object-fit: cover; }
.skill-mark--large { width: 50px; height: 50px; flex-basis: 50px; }
.skill-card .skill-mark { color: var(--skill-card-muted); }
.skill-card :deep(.empty-tags) { color: var(--skill-card-muted); }
.skill-card__identity { min-width: 0; flex: 1; }
.skill-card__byline { display: flex; align-items: center; gap: 8px; margin-top: 4px; min-width: 0; color: var(--skill-card-muted); font-size: 12px; }
.skill-version-line { display: flex; flex: 1 1 auto; min-width: 0; align-items: center; gap: 6px; }
.skill-card__author { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.skill-update-badge { height: 20px; display: inline-flex; flex: 0 0 auto; align-items: center; gap: 3px; padding: 0 6px; border: 1px solid #b9ddc8; border-radius: 4px; color: #287849; background: #eef8f2; box-sizing: border-box; cursor: pointer; font: inherit; font-size: 11px; line-height: 18px; white-space: nowrap; }
.skill-update-badge:hover { border-color: #87c5a0; color: #1e633b; background: #e3f4e9; }
.skill-update-badge:focus-visible { outline: 2px solid #79b994; outline-offset: 2px; }
.skill-update-badge .el-icon { font-size: 12px; }
:global(.skill-update-popover) { max-width: calc(100vw - 32px); box-sizing: border-box; }
:global(.skill-update-popover .skill-update-popover__title) { margin-bottom: 8px; color: #273445; font-size: 13px; font-weight: 600; }
:global(.skill-update-popover .skill-update-popover__description) { max-height: 220px; overflow-y: auto; color: #536174; font-size: 13px; line-height: 1.7; white-space: pre-wrap; overflow-wrap: anywhere; }
.skill-card__title { display: flex; min-width: 0; align-items: center; gap: 7px; }
.skill-card h3 { display: -webkit-box; min-width: 0; margin: 0; overflow: hidden; color: var(--skill-card-text); font-size: 14px; line-height: 21px; font-weight: 650; overflow-wrap: anywhere; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.skill-description { display: -webkit-box; flex: 1 1 auto; min-height: 42px; margin: 16px 0 0; overflow: hidden; color: #303133; font-size: 13px; line-height: 21px; -webkit-box-orient: vertical; -webkit-line-clamp: 5; }
.skill-stats { display: flex; flex-shrink: 0; align-items: center; gap: 8px; color: var(--skill-card-muted); font-size: 12px; cursor: default; }
.skill-stats > span { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
.skill-stats strong { color: inherit; font-weight: inherit; font-variant-numeric: tabular-nums; }
.skill-card__development { display: flex; align-items: center; justify-content: space-between; gap: 12px; min-height: 38px; margin-top: 14px; padding: 6px 10px 6px 12px; border: 1px solid #e4eaf2; border-radius: 9px; background: #f8fafc; color: #596678; box-sizing: border-box; transition: border-color .15s, background .15s, color .15s; }
.skill-development-detail { margin-top: 0; }
.skill-card__development.is-enabled { border-color: #b9d8f5; background: #f1f7fd; color: #285b8d; }
.skill-card__development-copy { display: inline-flex; min-width: 0; align-items: center; gap: 7px; }
.skill-card__development-dot { width: 7px; height: 7px; flex: 0 0 7px; border-radius: 50%; background: #aeb9c6; box-shadow: 0 0 0 3px #edf0f4; }
.skill-card__development.is-enabled .skill-card__development-dot { background: #409eff; box-shadow: 0 0 0 3px #dcecff; }
.skill-card__development-label { font-size: 12px; font-weight: 400; }
.skill-card__development-info { flex: 0 0 auto; color: #8a96a5; font-size: 14px; cursor: help; }
.skill-card__development-info:hover { color: #409eff; }
:global(.skill-development-popover) { padding: 0 !important; border: 1px solid #d7e7f7 !important; border-radius: 10px !important; background: #f7faff !important; box-shadow: 0 8px 24px #1834521c !important; }
:global(.skill-development-popover__content) { padding: 14px 16px; color: #697382; font-size: 13px; line-height: 1.7; }
:global(.skill-development-popover__content strong) { display: block; margin-bottom: 5px; color: #4f5d6d; font-size: 14px; }
:global(.skill-development-popover__content p) { margin: 0; white-space: normal; }
.skill-card__development-state { padding: 0; border: 0; color: #8a96a5; background: transparent; cursor: pointer; font: inherit; font-size: 11px; }
.skill-card__development-state:hover { color: #409eff; text-decoration: underline; }
.skill-card__development.is-enabled .skill-card__development-state { color: #4d83b5; }
.skill-card__development :deep(.el-switch) { --el-switch-on-color: #409eff; --el-switch-off-color: #c5ced9; transform: scale(.9); transform-origin: right center; }
.skill-card__actions { min-height: 32px; display: flex; align-items: center; justify-content: flex-end; gap: 6px; margin-top: auto; padding-top: 18px; }
.skill-card__actions :deep(.el-button) { min-width: 60px; margin-left: 0; padding-left: 12px; padding-right: 12px; }
.card-download { display: inline-flex; align-items: center; gap: 2px; margin-right: auto; }
.release-notes-action { height: 32px; margin: 0; padding: 0 4px 0 0; color: var(--skill-card-muted); }
.release-notes-action:hover { color: #2c5f95; background: #eef5fc; }
.managed-note { color: var(--skill-card-muted); font-size: 14px; line-height: 32px; }
.upgrade-current { margin-right: auto; color: #8993a1; font-size: 12px; }
.empty-state { grid-column: 1 / -1; }
.library-load-more { display: flex; align-items: center; justify-content: center; gap: 10px; min-height: 48px; margin-top: 16px; color: #737d8b; font-size: 13px; }
:deep(.skill-info-dialog .el-dialog__body) { padding-top: 4px; }
:deep(.skill-files-dialog .el-dialog__body) { height: min(76vh, 760px); min-height: 0; padding-top: 4px; box-sizing: border-box; display: flex; flex-direction: column; overflow: hidden; }
.skill-detail { display: flex; flex-direction: column; gap: 20px; padding: 4px 2px 2px; box-sizing: border-box; }
.detail-header { display: flex; flex-shrink: 0; align-items: flex-start; gap: 14px; }
.detail-identity { min-width: 0; flex: 1; }
.detail-header h2 { margin: 2px 0 4px; color: #171a20; font-size: 18px; overflow-wrap: anywhere; }
.detail-byline { display: flex; align-items: center; gap: 8px; min-width: 0; color: #737d8b; font-size: 12px; }
.detail-author { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.detail-stats { display: flex; flex-shrink: 0; align-items: center; gap: 8px; color: #737d8b; font-size: 12px; }
.detail-stats > span { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
.detail-stats strong { color: inherit; font-weight: inherit; font-variant-numeric: tabular-nums; }
.skill-development { padding: 14px 16px; border: 1px solid #d7e7f7; border-radius: 8px; background: #f7faff; }
.skill-development__heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-size: 14px; }
.skill-development p { margin: 6px 0 0; color: #697382; font-size: 13px; line-height: 1.7; }
.detail-description { margin: 6px 0 0; color: #303133; font-size: 13px; line-height: 21px; white-space: pre-line; overflow-wrap: anywhere; }
.detail-actions { display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
.detail-actions :deep(.el-button) { min-width: 60px; margin-left: 0; padding-left: 12px; padding-right: 12px; }
.skill-examples { display: grid; gap: 12px; border-top: 1px solid #ebeef2; padding-top: 20px; }
.skill-examples h3 { display: flex; align-items: center; gap: 8px; margin: 0 0 4px; color: #24272c; font-size: 16px; font-weight: 600; }
.skill-examples h3 .el-icon { font-size: 20px; }
.skill-example { display: flex; align-items: center; justify-content: space-between; gap: 16px; width: 100%; padding: 16px 20px; border: 0; border-radius: 16px; background: #f6f6f7; color: #555b63; font: inherit; font-size: 14px; line-height: 1.6; text-align: left; cursor: pointer; }
.skill-example span { min-width: 0; white-space: pre-wrap; overflow-wrap: anywhere; }
.skill-example > .el-icon { flex-shrink: 0; color: #8b9098; font-size: 20px; }
.skill-example:hover:not(:disabled) { background: #eff1f4; color: #24272c; }
.skill-example:focus-visible { outline: 2px solid #409eff; outline-offset: 2px; }
.skill-example:disabled { cursor: not-allowed; opacity: .55; }
.detail-download { display: inline-flex; align-items: center; gap: 2px; margin-right: auto; }
:deep(.el-dialog.release-notes-dialog) { height: auto; max-height: 700px; display: flex; flex-direction: column; overflow: hidden; box-sizing: border-box; }
.release-notes-dialog :deep(.el-dialog__body) { overflow: hidden; padding-top: 4px; }
.release-notes-list { display: flex; flex-direction: column; gap: 12px; max-height: min(628px, calc(100vh - 180px)); overflow-y: auto; padding-right: 8px; }
.release-notes-item { padding: 14px 16px; border: 1px solid #e6ebf2; border-radius: 8px; background: #fafbfd; }
.release-notes-item__header { display: flex; align-items: center; justify-content: space-between; gap: 12px; color: #273445; font-size: 13px; }
.release-notes-version { color: #273445; font-weight: 400; }
.release-notes-date { color: #8a94a2; font-size: 12px; white-space: nowrap; }
.release-notes-item__body { margin-top: 10px; color: #536174; font-size: 13px; line-height: 1.8; white-space: pre-wrap; overflow-wrap: anywhere; }
.release-notes-item__actions { display: flex; align-items: center; justify-content: flex-end; gap: 4px; margin-top: 10px; padding-top: 8px; }
@media (max-width: 760px) {
  .library-toolbar { align-items: stretch; flex-wrap: wrap; }
  .source-tabs { width: 100%; }
  .library-summary { flex-wrap: wrap; gap: 8px; margin-top: 18px; }
  .skill-grid { grid-template-columns: 1fr; }
  .detail-actions { flex-wrap: wrap; justify-content: flex-start; }
  :deep(.skill-files-dialog .el-dialog__body) { height: min(78vh, 680px); }
}
</style>

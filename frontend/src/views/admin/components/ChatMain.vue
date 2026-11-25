<template>
  <!-- 中央对话区：消息列表 + 流式消息 + 输入区 -->
  <div
    class="chat-main"
    :aria-busy="historyLoading"
    :class="{
      'view-only': viewOnly,
      'is-empty-conversation': isEmptyConversation,
    }"
  >
    <!-- 消息列表 -->
    <div class="messages-shell">
      <div
        ref="messagesRef"
        id="chat-messages"
        class="messages"
        @scroll.passive="handleMessagesScroll"
      >
      <div ref="messagesContentRef" class="messages-content">
      <ChatHistorySkeleton v-if="historyLoading" />
      <template v-else>
      <div v-if="historyHasMore" class="older-messages-loader">
        <el-button
          size="small"
          text
          :loading="olderHistoryLoading"
          @click="$emit('load-older')"
        >
          加载更早消息
        </el-button>
      </div>
      <template v-for="msg in displayMessages" :key="msg.id">
        <!-- 用户消息 -->
        <div v-if="msg.role === 'user'" class="message-row user">
          <div class="user-message-stack">
            <div v-if="msg.images?.length" class="user-message-images">
              <UserMessageImage
                v-for="image in msg.images"
                :key="image.path"
                :agent-id="agentId"
                :path="image.path"
                :preview-url="image.previewUrl"
              />
            </div>
            <div class="message-bubble user-bubble" :class="{ 'has-references': msg.skill || messageFileReferences(msg).length }">
              <span v-if="msg.skill" class="message-reference skill" :title="msg.skill.name"><el-icon><SkillIcon /></el-icon><span>{{ msg.skill.name }}</span></span>
              <span v-for="file in messageFileReferences(msg)" :key="file" class="message-reference file" :title="file"><el-icon><Document /></el-icon><span>{{ referenceFileName(file) }}</span></span>
              <div class="markdown-body" v-html="userMessageHtml.get(msg.id)"></div>
            </div>
            <div class="user-message-actions">
              <time :datetime="msg.created_at || undefined">{{ formatBeijingDateTime(msg.created_at, { fallback: '无' }) }}</time>
              <el-button link :icon="CopyDocument" aria-label="复制消息" title="复制消息"
                :disabled="copyingMessage" @click="copyMessageText(msg.content)" />
            </div>
          </div>
        </div>

        <!-- 助手消息 -->
        <div v-else-if="msg.role === 'assistant'" class="message-row assistant" :class="{ 'feedback-target': highlightedMessageId != null && msg.messageId === highlightedMessageId }">
          <div class="message-content">
            <div class="assistant-identity">
              <el-tag v-if="highlightedMessageId != null && msg.messageId === highlightedMessageId" size="small" effect="plain">被反馈回复</el-tag>
              <span class="assistant-avatar" :class="{ 'image-avatar': getAssistantImage(assistantDisplayIcon) }" aria-hidden="true"><AssistantIcon :icon="assistantDisplayIcon" /></span>
              <strong>{{ assistantDisplayName }}</strong>
            </div>
            <div class="completed-run-elapsed">
              <el-icon aria-hidden="true"><WarningFilled v-if="messageFailed(msg)" /><CircleCheck v-else /></el-icon>
              <span>{{ messageFailed(msg) ? '本轮未完成' : '已完成' }} {{ formatCompletedDuration(msg.metrics?.durationMs) }}</span>
            </div>
            <template v-for="segment in groupProcessBlocks(msg.blocks)" :key="segment.key">
              <!-- 文本 -->
              <div v-if="segment.type === 'block' && segment.block.type === 'text'" class="text-block">
                <MessageContent
                  :content="segment.block.content || ''"
                  :noun-matcher="nounMatcher"
                  :view-only="viewOnly"
                />
              </div>
              <ProcessBlockGroup
                v-else-if="segment.type === 'process_group'"
                :blocks="segment.blocks"
                :show-duration="false"
                :view-only="viewOnly"
              />
            </template>
            <ChatArtifacts :files="getChatArtifacts(msg.blocks)" :agent-id="agentId" :view-only="viewOnly" />
            <ChatErrorDetails
              v-if="!viewOnly && savedErrorDetails(msg)"
              :details="savedErrorDetails(msg)"
            />
            <div v-if="hasTurnMetrics(msg.metrics) || !viewOnly || allowReplyCopy" class="assistant-footer">
              <div
                v-if="hasTurnMetrics(msg.metrics)"
                class="turn-metrics"
                :class="{ 'is-fresh': !msg._saved }"
                :title="turnMetricsTitle(msg.metrics)"
              >
              <template v-if="showCreditUsage && creditUnitLabel && Number.isFinite(msg.metrics?.chargedPoints)">
                <span class="turn-metric">
                  <span class="turn-metric-label">共消耗</span>
                  <span class="turn-metric-value">{{ formatCreditPoints(msg.metrics.chargedPoints) }}</span>
                  <span class="turn-metric-label">{{ creditUnitLabel }}</span>
                </span>
              </template>
              <span
                v-if="showCreditUsage && creditUnitLabel && Number.isFinite(msg.metrics?.chargedPoints)"
                class="turn-metrics-separator"
              >·</span>
              <span class="turn-metric">
                <span class="turn-metric-label">Token</span>
                <span :class="{ 'turn-metric-value': hasTokenCount(msg.metrics?.totalTokens) }">
                  {{ formatTurnTokenCount(msg.metrics?.totalTokens) }}
                </span>
              </span>
              <template v-if="msg.metrics?.cacheTokens !== null && msg.metrics?.cacheTokens !== undefined">
                <span class="turn-metrics-separator">·</span>
                <span class="turn-metric turn-metric-detail">
                  输入 <span class="turn-metric-value">{{ formatTokenCount(msg.metrics.totalInputTokens) }}</span>
                  <span class="input-breakdown">
                    (缓存 {{ formatTokenCount(msg.metrics.cacheTokens) }} / 非缓存 {{ formatTokenCount(msg.metrics.nonCacheInputTokens) }})
                  </span>
                </span>
                <span class="turn-metrics-separator">·</span>
                <span class="turn-metric turn-metric-detail">
                  输出 <span class="turn-metric-value">{{ formatTokenCount(msg.metrics.outputTokens) }}</span>
                </span>
                <span
                  class="cache-status"
                  :class="{ hit: msg.metrics.cacheHit, miss: msg.metrics.cacheHit === false }"
                  :title="msg.metrics.cacheHit ? '本轮读取了缓存 Token' : '本轮未读取缓存 Token'"
                >
                  <span class="cache-status-indicator" aria-hidden="true"></span>
                  <span>{{ msg.metrics.cacheHit ? '缓存命中' : '缓存未命中' }}</span>
                </span>
              </template>
              </div>
              <div v-if="!viewOnly || allowReplyCopy" class="msg-actions assistant-actions">
                <el-tooltip content="复制回复" placement="bottom">
                  <el-button
                    class="msg-action-btn"
                    :icon="CopyDocument"
                    text
                    circle
                    aria-label="复制这条回复"
                    :disabled="copyingMessage"
                    @click="copyReply(msg)"
                  />
                </el-tooltip>
                <MessageFeedback v-if="!viewOnly" :message-id="msg.messageId" :feedback="msg.feedback"
                  @change="$emit('feedback-change', { messageId: msg.messageId, feedback: $event })" />
                <el-tooltip v-if="!viewOnly" content="重新提问" placement="bottom">
                  <el-button
                    class="msg-action-btn"
                    :icon="RefreshRight"
                    text
                    circle
                    aria-label="将对应问题重新放入输入框"
                    :disabled="sendLocked || streaming"
                    @click="$emit('regenerate', msg)"
                  />
                </el-tooltip>
              </div>
            </div>
          </div>
        </div>
      </template>

      <!-- 流式消息 -->
      <div v-if="streaming" class="message-row assistant">
        <div class="message-content">
          <div class="assistant-identity">
            <span class="assistant-avatar" :class="{ 'image-avatar': getAssistantImage(assistantDisplayIcon) }" aria-hidden="true"><AssistantIcon :icon="assistantDisplayIcon" /></span>
            <strong>{{ assistantDisplayName }}</strong>
          </div>
          <div class="stream-run-elapsed" role="status" aria-live="polite">
            已处理 {{ streamElapsedText }}
          </div>
          <div v-if="contextNotice" class="context-notice" role="status">
            <el-icon><InfoFilled /></el-icon>
            <span>{{ contextNotice }}</span>
          </div>
          <div
            v-if="streamProcessStatusLabel"
            class="stream-process-status"
            role="status"
            aria-live="polite"
          >
            <span class="chat-activity-text">{{ streamProcessStatusLabel }}</span>
          </div>
          <template v-for="segment in currentSegments" :key="segment.key">
            <div v-if="segment.type === 'block' && segment.block.type === 'text'" class="text-block">
              <MessageContent :content="segment.block.content || ''" :noun-matcher="nounMatcher" :view-only="viewOnly" streaming />
            </div>
            <ProcessBlockGroup
              v-else-if="segment.type === 'process_group'"
              :blocks="segment.blocks"
              :activity="getRunActivity(segment.blocks, runStatus?.phase)"
              :view-only="viewOnly"
              :running="hasRunningProcessBlocks(segment.blocks)"
              streaming
            />
          </template>
          <ChatArtifacts :files="getChatArtifacts(currentBlocks)" :agent-id="agentId" :view-only="viewOnly" />
          <div
            v-if="streamGenerating || hasStreamCreditUsage || runTokenCount != null"
            class="stream-run-meta"
            role="status"
            aria-live="polite"
          >
            <span v-if="streamGenerating" class="stream-run-meta-item stream-run-meta-status chat-activity-text">
              生成回复中
            </span>
            <span v-if="hasStreamCreditUsage" class="stream-run-meta-item">
              <span v-if="streamGenerating" class="stream-run-meta-separator">|</span>
              已消耗 <strong>{{ streamChargedPointsText }}</strong> {{ creditUnitLabel }}
            </span>
            <span v-if="runTokenCount != null" class="stream-run-meta-item">
              <span v-if="hasStreamCreditUsage || streamGenerating" class="stream-run-meta-separator">|</span>
              {{ runTokenCount.toLocaleString('zh-CN') }} Token
            </span>
          </div>
        </div>
      </div>

      <div
        v-if="!viewOnly && !streaming && runFailure"
        class="message-row assistant run-failure-row"
        role="alert"
      >
        <div class="run-failure-inline">
          <el-icon class="run-failure-icon"><WarningFilled /></el-icon>
          <div class="run-failure-copy">
            <strong>{{ runFailure.title || '本次运行未完成' }}</strong>
            <span class="run-failure-message">{{ runFailure.message }}</span>
            <ChatErrorDetails v-if="runFailure.details" :details="runFailure.details" />
          </div>
          <div class="run-failure-actions">
            <el-button type="danger" link :icon="RefreshRight" @click="$emit('retry-run')">
              {{ runFailure.retryLabel || '重新发送' }}
            </el-button>
            <el-button
              v-if="runFailure.suggestNarrow"
              type="warning"
              link
              :icon="Operation"
              @click="$emit('retry-narrow-run')"
            >
              缩小范围重试
            </el-button>
            <el-button
              v-if="runFailure.canContinue"
              type="primary"
              link
              :icon="ArrowRight"
              @click="$emit('continue-run')"
            >
              继续执行
            </el-button>
          </div>
          <el-button
            class="run-failure-close"
            text
            circle
            :icon="Close"
            aria-label="关闭运行错误"
            @click="$emit('dismiss-run-failure')"
          />
        </div>
      </div>

      <!-- 空白欢迎页 -->
      <div
        v-if="!historyLoading && !streaming && !runFailure && displayMessages.length === 0"
        class="welcome"
      >
        <h2 class="welcome-title">{{ viewOnly ? '暂无对话内容' : '今天，想一起做点什么？' }}</h2>
        <p v-if="viewOnly" class="welcome-desc">该分享中暂无对话内容</p>
        <p v-else class="welcome-subtitle">从一个问题、一个想法，或一份文件开始</p>
      </div>
      </template>
      </div>
      </div>
      <div
        v-if="!historyLoading && messagesHasOverflow"
        class="messages-scroll-indicator"
        :class="{ visible: messagesScrolling || scrollDragging }"
        :style="{ right: `${scrollbarRightOffset}px` }"
        role="scrollbar"
        tabindex="0"
        aria-label="对话滚动条"
        aria-controls="chat-messages"
        aria-orientation="vertical"
        :aria-valuemin="0"
        :aria-valuemax="100"
        :aria-valuenow="messagesScrollPercent"
        @pointerdown="startScrollDrag"
        @pointermove="moveScrollDrag"
        @pointerup="endScrollDrag"
        @pointercancel="endScrollDrag"
        @lostpointercapture="endScrollDrag"
        @keydown.up.prevent="scrollMessagesBy(-80)"
        @keydown.down.prevent="scrollMessagesBy(80)"
        @keydown.page-up.prevent="scrollMessagesBy(-480)"
        @keydown.page-down.prevent="scrollMessagesBy(480)"
        @keydown.home.prevent="scrollMessagesTo(0)"
        @keydown.end.prevent="scrollMessagesToEnd"
      >
        <span :style="messagesScrollThumbStyle"></span>
      </div>
      <div
        v-if="!historyLoading && !viewOnly && messagesHasOverflow"
        class="scroll-navigation-control"
        :style="{ right: `${scrollbarRightOffset + 16}px` }"
      >
        <span v-if="unseenStreamContent && !messagesNearBottom" class="new-content-label">有新内容</span>
        <div class="scroll-navigation-buttons">
          <el-tooltip v-if="!messagesNearTop" content="跳到顶部" placement="left">
            <el-button
              class="scroll-navigation-button"
              :icon="Top"
              circle
              aria-label="跳到顶部"
              @click="scrollToTop(false)"
            />
          </el-tooltip>
          <el-tooltip v-if="!messagesNearBottom" content="回到底部" placement="left">
            <el-button
              class="scroll-navigation-button"
              :icon="Bottom"
              circle
              aria-label="回到底部"
              @click="scrollToBottom(false)"
            />
          </el-tooltip>
        </div>
      </div>
    </div>

    <!-- 授权弹窗 -->
    <PermissionBar
      v-if="!viewOnly"
      :permissions="pendingPermissions"
      :submitting-ids="permissionSubmittingIds"
      @decide="(p, decision, remember) => $emit('permission-decide', p, decision, remember)"
    />

    <div
      v-if="!viewOnly && runtimeNotice"
      class="runtime-notice"
      :class="{ pending: runtimePending }"
      role="status"
    >
      <el-icon :class="{ 'is-loading': runtimePending }">
        <Loading v-if="runtimePending" />
        <WarningFilled v-else />
      </el-icon>
      <span>{{ runtimeNotice }}</span>
    </div>

    <!-- 输入区 -->
    <div
      v-if="!viewOnly"
      ref="inputAreaRef"
      class="input-area"
      :inert="historyLoading"
      :class="{
        'is-narrow': narrowInputArea,
        'is-very-narrow': veryNarrowInputArea,
      }"
    >
      <div class="composer-surface">
      <div class="composer-status" role="status" aria-live="polite">
        <span v-if="uploadingFiles > 0" class="upload-status"><el-icon class="is-loading"><Loading /></el-icon>正在上传附件</span>
      </div>
      <div v-if="imageChips.length" class="context-chips-bar">
        <span v-for="chip in imageChips" :key="chip.id" class="context-chip file has-preview">
          <el-image class="chip-image" :src="chip.previewUrl" :preview-src-list="[chip.previewUrl]" preview-teleported fit="contain" :alt="chip.label" />
          <el-icon
            class="chip-close"
            role="button"
            tabindex="0"
            :aria-label="`移除${chip.label}`"
            @click="$emit('remove-chip', chip)"
            @keydown.enter="$emit('remove-chip', chip)"
            @keydown.space.prevent="$emit('remove-chip', chip)"
          ><Close /></el-icon>
        </span>
        <el-button size="small" text class="clear-chips-btn" :disabled="uploadingFiles > 0" @click="$emit('clear-chips')">清空</el-button>
      </div>
      <InlineComposerInput
        ref="messageInputRef"
        v-model="inputText"
        class="input-row"
        :references="inlineChips"
        :noun-names="nounHighlightEnabled ? nounNames : []"
        :noun-suggestions-disabled="referenceMenuVisible"
        :rows="isEmptyConversation || veryNarrowInputArea ? 3 : 4"
        :placeholder="composerPlaceholder"
        :disabled="historyLoading || streaming || !!runtimeNotice"
        @keydown.enter.exact="handleComposerEnter"
        @keydown="handleComposerKeydown"
        @blur="handleComposerBlur"
        @backspace-start="handleReferenceBackspace"
        @remove-reference="$emit('remove-chip', $event)"
        @paste="handleComposerPaste"
      />
      <div
        v-if="referenceMenuVisible"
        ref="referenceMenuRef"
        class="composer-reference-menu"
        role="dialog"
        aria-label="输入引用菜单"
        @mousedown.prevent
      >
        <button
          v-if="referenceTrigger === '@'"
          type="button"
          class="composer-reference-action"
          :class="{ active: referenceActiveIndex === 0 }"
          @click="openReferenceFileUpload"
        >
          <el-icon><Paperclip /></el-icon>
          <span>添加文件</span>
          <small>上传本地文件</small>
        </button>
        <div class="composer-reference-heading">{{ referenceTrigger === '@' ? '工作区文件' : '调用技能' }}</div>
        <div class="composer-reference-list">
          <div v-if="referenceOptionsLoading" class="composer-reference-status" role="status">
            <el-icon class="is-loading" aria-hidden="true"><Loading /></el-icon>
            {{ referenceTrigger === '@' ? '正在加载文件…' : '正在加载技能…' }}
          </div>
          <template v-else-if="referenceTrigger === '@'">
            <button
              v-for="file in filteredWorkspaceFiles"
              :key="file.path"
              type="button"
              class="composer-reference-option"
              :class="{
                selected: props.contextChips.some(chip => chip.path === file.path),
                active: referenceActiveIndex === filteredWorkspaceFiles.indexOf(file) + 1,
              }"
              @click="selectWorkspaceReference(file)"
            >
              <el-icon><Document /></el-icon>
              <span>{{ file.path }}</span>
              <el-icon v-if="props.contextChips.some(chip => chip.path === file.path)" class="composer-reference-check"><Check /></el-icon>
            </button>
            <div v-if="filteredWorkspaceFiles.length === 0" class="composer-reference-status">
              {{ workspaceFileQuery ? '没有匹配的工作区文件' : '无' }}
            </div>
          </template>
          <template v-else>
            <button
              v-for="skill in filteredReferenceSkills"
              :key="skill.id"
              type="button"
              class="composer-reference-option"
              :class="{
                selected: Number(skill.id) === Number(props.selectedSkillId),
                active: referenceActiveIndex === filteredReferenceSkills.indexOf(skill),
              }"
              @click="selectSkillReference(skill)"
            >
              <el-icon><SkillIcon /></el-icon>
              <span>{{ skill.name }}</span>
              <el-icon v-if="Number(skill.id) === Number(props.selectedSkillId)" class="composer-reference-check"><Check /></el-icon>
            </button>
            <div v-if="filteredReferenceSkills.length === 0" class="composer-reference-status">
              {{ referenceQuery ? '没有匹配的技能' : '无' }}
            </div>
          </template>
        </div>
      </div>
      <div class="input-actions">
        <div class="input-left">
          <input
            ref="fileInputRef"
            type="file"
            style="display:none"
            @change="handleFileChange"
            multiple
            accept="*/*"
          />
          <el-popover
            v-model:visible="compactActionsVisible"
            placement="top-start"
            trigger="click"
            :width="240"
            popper-class="composer-tools-popper"
            :popper-style="{ maxWidth: 'calc(100vw - 24px)' }"
          >
            <template #reference>
              <el-button
                class="compact-actions-trigger"
                :class="{ 'is-open': compactActionsVisible }"
                size="small"
                title="更多操作"
                aria-label="更多操作"
              >
                <el-icon><Close v-if="compactActionsVisible" /><Plus v-else /></el-icon>
                <span>工具</span>
              </el-button>
            </template>
            <div class="compact-actions-menu" @keydown.esc.stop="compactActionsVisible = false">
              <button type="button" class="compact-menu-item" @click="openCompactFileUpload">
                <el-icon><Paperclip /></el-icon>
                <span>添加文件</span>
              </button>
              <el-popover
                v-model:visible="workspaceMenuVisible"
                placement="right-start"
                trigger="click"
                :width="240"
                popper-class="composer-tools-popper composer-submenu-popper"
                :popper-style="{ maxWidth: 'calc(100vw - 24px)' }"
                @show="openCompactSubmenu('workspace')"
              >
                <template #reference>
                  <button type="button" class="compact-menu-item">
                    <el-icon><Files /></el-icon>
                    <span>工作区文件</span>
                    <el-icon class="compact-menu-arrow"><ArrowRight /></el-icon>
                  </button>
                </template>
                <div class="compact-actions-menu compact-submenu-menu">
                  <div class="compact-submenu-title">工作区文件</div>
                  <div class="compact-menu-divider" role="separator"></div>
                  <div v-loading="workspaceFilesLoading" class="workspace-file-options-list">
                    <button
                      v-for="file in workspaceFiles"
                      :key="file.path"
                      type="button"
                      class="compact-menu-item compact-menu-option"
                      :class="{ selected: props.contextChips.some(chip => chip.path === file.path) }"
                      @click="handleCompactWorkspaceSelect(file)"
                    >
                      <el-icon><Document /></el-icon>
                      <span class="compact-option-copy"><span>{{ file.path }}</span></span>
                      <el-icon v-if="props.contextChips.some(chip => chip.path === file.path)" class="compact-option-check"><Check /></el-icon>
                    </button>
                    <div v-if="!workspaceFilesLoading && workspaceFiles.length === 0" class="compact-menu-empty">
                      暂无数据
                    </div>
                  </div>
                </div>
              </el-popover>
              <div class="compact-menu-divider" role="separator"></div>

              <el-popover
                v-model:visible="skillMenuVisible"
                placement="right-start"
                trigger="click"
                :width="240"
                popper-class="composer-tools-popper composer-submenu-popper"
                :popper-style="{ maxWidth: 'calc(100vw - 24px)' }"
                @show="openCompactSubmenu('skills')"
              >
                <template #reference>
                  <button type="button" class="compact-menu-item">
                    <el-icon><SkillIcon /></el-icon>
                    <span>技能</span>
                    <el-icon class="compact-menu-arrow"><ArrowRight /></el-icon>
                  </button>
                </template>
                <div class="compact-actions-menu compact-submenu-menu">
                  <div class="compact-submenu-title">选择技能</div>
                  <div class="compact-menu-divider" role="separator"></div>
                  <button
                    v-for="skill in agentSkills"
                    :key="skill.id"
                    type="button"
                    class="compact-menu-item compact-menu-option"
                    :class="{ selected: skill.id === selectedSkillId }"
                    @click="handleCompactSkillSelect(skill.id)"
                  >
                    <span class="compact-option-dot skill"></span>
                    <span class="compact-option-copy"><span>{{ skill.name }}</span></span>
                    <el-icon v-if="skill.id === selectedSkillId" class="compact-option-check"><Check /></el-icon>
                  </button>
                  <div v-if="agentSkills.length === 0" class="compact-menu-empty">
                    暂无数据
                  </div>
                </div>
              </el-popover>

              <el-popover
                v-model:visible="templateMenuVisible"
                placement="right-start"
                trigger="click"
                :width="240"
                popper-class="composer-tools-popper composer-submenu-popper"
                :popper-style="{ maxWidth: 'calc(100vw - 24px)' }"
                @show="openCompactSubmenu('templates')"
              >
                <template #reference>
                  <button type="button" class="compact-menu-item">
                    <el-icon><ChatDotSquare /></el-icon>
                    <span>提示词</span>
                    <el-icon class="compact-menu-arrow"><ArrowRight /></el-icon>
                  </button>
                </template>
                <div class="compact-actions-menu compact-submenu-menu">
                  <div class="compact-submenu-title">选择提示词</div>
                  <div class="compact-menu-divider" role="separator"></div>
                  <button
                    v-for="template in usableTemplates"
                    :key="template.id"
                    type="button"
                    class="compact-menu-item compact-menu-option"
                    @click="handleCompactTemplateSelect(template)"
                  >
                    <span class="compact-option-dot template"></span>
                    <span class="compact-option-copy">
                      <span>{{ template.name }}</span>
                    </span>
                  </button>
                  <div v-if="usableTemplates.length === 0" class="compact-menu-empty">
                    暂无数据
                  </div>
                </div>
              </el-popover>
              <template v-if="identityMcpNames.length">
                <div class="compact-menu-divider" role="separator"></div>
                <div class="identity-mcp-status" role="status">
                  <el-icon><UserFilled /></el-icon>
                  <div>
                    <span>当前身份用于 {{ identityMcpNames.length }} 个 MCP 的认证</span>
                    <small>{{ identityMcpNames.join('、') }}</small>
                  </div>
                </div>
              </template>
            </div>
          </el-popover>
          <el-dropdown trigger="click" placement="top-start" @command="handlePermissionModeSelect">
            <button type="button" class="permission-mode-trigger" aria-label="选择权限模式" :title="permissionModeLabel">
              <el-icon><Lock v-if="permissionMode === 'default'" /><CircleCheck v-else /></el-icon>
              <span>{{ permissionModeLabel }}</span>
              <el-icon class="permission-mode-arrow"><ArrowDown /></el-icon>
            </button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="acceptEdits">
                  <div class="permission-mode-option">
                    <el-icon><CircleCheck /></el-icon>
                    <span><strong>默认权限</strong><small>自动接受工作区内的文件编辑</small></span>
                    <el-icon v-if="permissionMode === 'acceptEdits'" class="permission-option-check"><Check /></el-icon>
                  </div>
                </el-dropdown-item>
                <el-dropdown-item command="default">
                  <div class="permission-mode-option">
                    <el-icon><Lock /></el-icon>
                    <span><strong>逐次确认</strong><small>文件修改、命令和 MCP 调用前请求确认</small></span>
                    <el-icon v-if="permissionMode === 'default'" class="permission-option-check"><Check /></el-icon>
                  </div>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
        <div class="input-right">
          <TokenUsage
            v-if="tokenHasReplies || tokenAvailable"
            :used="tokenUsed"
            :input-tokens="inputTokens"
            :output-tokens="outputTokens"
            :cache-tokens="cacheTokens"
            :available="tokenAvailable"
            :complete="tokenComplete"
            :has-replies="tokenHasReplies"
            compact
          />
          <el-popover
            v-model:visible="modelMenuVisible"
            placement="top-end"
            trigger="click"
            :width="280"
            popper-class="composer-tools-popper model-switch-popper"
            :popper-style="{ maxWidth: 'calc(100vw - 24px)' }"
            @show="$emit('refresh-models')"
          >
            <template #reference>
              <button
                type="button"
                class="model-switch-trigger"
                :class="{ 'is-open': modelMenuVisible }"
                :title="`当前模型：${selectedModelName}`"
                aria-label="切换模型"
              >
                <span>{{ selectedModelName }}</span>
                <el-icon class="model-switch-arrow">
                  <ArrowDown />
                </el-icon>
              </button>
            </template>
            <div class="compact-actions-menu compact-submenu-menu model-switch-menu">
              <div class="compact-submenu-title">选择模型</div>
              <div class="compact-menu-divider" role="separator"></div>
              <div v-loading="modelsLoading && agentModels.length === 0" class="model-options-list">
                <section v-for="group in modelGroups" :key="group.key" :aria-label="group.label">
                  <div class="compact-submenu-title model-group-title">{{ group.label }}</div>
                  <button
                    v-for="model in group.models"
                    :key="model.id"
                    type="button"
                    class="compact-menu-item compact-menu-option"
                    :class="{ selected: model.id === selectedModelId }"
                    @click="handleModelSelect(model.id)"
                  >
                    <span class="compact-option-dot model"></span>
                    <span class="compact-option-copy">
                      <span>{{ model.name }}</span>
                      <small v-if="model.remarks">{{ model.remarks }}</small>
                    </span>
                    <el-icon v-if="model.id === selectedModelId" class="compact-option-check"><Check /></el-icon>
                  </button>
                </section>
                <div v-if="!modelsLoading && visibleAgentModels.length === 0" class="compact-menu-empty">暂无与当前运行方式兼容的模型</div>
              </div>
              <template v-if="allowCustomModels">
                <div class="compact-menu-divider" role="separator"></div>
                <router-link class="compact-menu-item model-config-link" to="/admin/models" target="_blank" rel="noopener noreferrer" @click="modelMenuVisible = false">
                  <el-icon><Edit /></el-icon><span>配置自定义模型</span>
                </router-link>
              </template>
            </div>
          </el-popover>
          <span class="btn-group">
            <el-tooltip v-if="streaming" content="停止生成" placement="top">
              <el-button
                class="composer-action-button"
                type="danger"
                circle
                :disabled="runStatus?.phase === 'stopping'"
                :aria-label="runStatus?.phase === 'stopping' ? '正在停止' : '停止生成'"
                @click="$emit('stop')"
              >
                <span class="stop-square" aria-hidden="true"></span>
              </el-button>
            </el-tooltip>
            <el-tooltip v-else content="发送" placement="top">
              <el-button
                class="composer-action-button"
                type="primary"
                circle
                aria-label="发送"
                :disabled="historyLoading || !hasSendContent || sendLocked || uploadingFiles > 0"
                @click="$emit('send')"
              >
                <el-icon><Top /></el-icon>
              </el-button>
            </el-tooltip>
          </span>
        </div>
      </div>
      </div>
      <section v-if="isEmptyConversation && welcomeSuggestions.length" class="welcome-suggestions" aria-label="任务灵感">
        <div class="suggestions-heading">
          <span>试试这样问</span>
          <button v-if="canRefreshSuggestions" type="button" class="suggestions-refresh" @click="refreshSuggestions">
            <el-icon><RefreshRight /></el-icon><span>换一批</span>
          </button>
        </div>
        <div :key="suggestionsRevision" class="suggestions-list">
          <button
            v-for="suggestion in welcomeSuggestions"
            :key="suggestion.key"
            type="button"
            class="suggestion-item"
            :title="suggestion.skillName ? `来自 ${suggestion.skillName}\n${suggestion.prompt}` : suggestion.prompt"
            :disabled="sendLocked || !!runtimeNotice || uploadingFiles > 0"
            @click="useWelcomeSuggestion(suggestion)"
          >
            <span class="suggestion-text">{{ suggestion.prompt }}</span>
            <el-icon aria-hidden="true"><TopRight /></el-icon>
          </button>
        </div>
      </section>
    </div>

    <!-- 提示词模板变量填写弹窗 -->
    <el-dialog
      v-if="!viewOnly"
      v-model="varDialogVisible"
      title="填写模板变量"
      width="480px"
      :close-on-click-modal="false"
    >
      <el-form label-width="120px" v-if="currentTemplate">
        <el-form-item
          v-for="v in currentVariables"
          :key="v.name"
          :label="v.name"
          :required="v.required"
        >
          <el-input
            v-model="varForm[v.name]"
            :placeholder="v.description || ('请输入 ' + v.name)"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="varDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmVariables">填入输入框</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import '@/assets/styles/chat-activity.css'
import AssistantIcon from '@/components/AssistantIcon.vue'
import SkillIcon from '@/components/icons/SkillIcon.vue'
import { getAssistantImage } from '@/config/assistant-characters'
import { ref, computed, nextTick, onMounted, onBeforeUnmount, watch } from 'vue'
import {
  Top, Bottom, Close, Loading, WarningFilled, Plus, Paperclip, Files,
  Operation, ArrowRight, ArrowDown, Check, CircleCheck, Lock, Edit,
  CopyDocument, RefreshRight, InfoFilled, Document, UserFilled, ChatDotSquare, TopRight,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { formatBeijingDateTime } from '@/utils/date-time'
import MessageContent from './MessageContent.vue'
import MessageFeedback from './MessageFeedback.vue'
import ChatArtifacts from './ChatArtifacts.vue'
import ChatErrorDetails from './ChatErrorDetails.vue'
import { getAgentRunErrorDetails } from '@/utils/agent-run-state'
import { getChatArtifacts } from '@/utils/chat-artifacts'
import UserMessageImage from './UserMessageImage.vue'
import InlineComposerInput from './InlineComposerInput.vue'
import ChatHistorySkeleton from './ChatHistorySkeleton.vue'
import ProcessBlockGroup from './ProcessBlockGroup.vue'
import PermissionBar from './PermissionBar.vue'
import TokenUsage from './TokenUsage.vue'
import api from '@/api/request'
import { getCompatibleModelsForRuntime, getModelGroupsForRuntime } from '@/config/models'
import { formatCreditPoints } from '@/utils/credit-points'
import { copyToClipboard } from '@/utils/clipboard'
import { buildSkillSuggestions, pickSkillSuggestions } from '@/utils/skill-suggestions'
import {
  groupProcessBlocks,
  hasRunningProcessBlocks,
  getRunActivity,
} from '@/utils/agent-chat-blocks'

const props = defineProps({
  agentId: { type: [Number, String], default: '' },
  displayMessages: { type: Array, default: () => [] },
  historyLoading: { type: Boolean, default: false },
  historyHasMore: { type: Boolean, default: false },
  olderHistoryLoading: { type: Boolean, default: false },
  currentBlocks: { type: Array, default: () => [] },
  streaming: { type: Boolean, default: false },
  sendLocked: { type: Boolean, default: false },
  pendingPermissions: { type: Array, default: () => [] },
  permissionSubmittingIds: { type: Array, default: () => [] },
  runtimeType: { type: String, default: 'claude_code' },
  runtimeNotice: { type: String, default: '' },
  runtimePending: { type: Boolean, default: false },
  runStatus: { type: Object, default: null },
  runStartedAt: { type: Number, default: null },
  runChargedPoints: { type: Number, default: null },
  runTokenCount: { type: Number, default: null },
  runFailure: { type: Object, default: null },
  contextNotice: { type: String, default: '' },
  agentModels: { type: Array, default: () => [] },
  modelsLoading: { type: Boolean, default: false },
  allowCustomModels: { type: Boolean, default: false },
  selectedModelId: { type: Number, default: null },
  agentSkills: { type: Array, default: () => [] },
  agentSkillsLoading: { type: Boolean, default: false },
  showDefaultSuggestions: { type: Boolean, default: false },
  suggestionKey: { type: Number, default: 0 },
  selectedSkillId: { type: Number, default: null },
  usableTemplates: { type: Array, default: () => [] },
  tokenUsed: { type: Number, default: null },
  inputTokens: { type: Number, default: 0 },
  outputTokens: { type: Number, default: 0 },
  cacheTokens: { type: Number, default: 0 },
  tokenAvailable: { type: Boolean, default: false },
  tokenComplete: { type: Boolean, default: false },
  tokenHasReplies: { type: Boolean, default: false },
  agentName: { type: String, default: '' },
  agentIcon: { type: String, default: 'H' },
  creditDisplayName: { type: String, default: '' },
  showCreditUsage: { type: Boolean, default: false },
  identityMcpNames: { type: Array, default: () => [] },
  scrollbarRightOffset: { type: Number, default: 3 },
  uploadFile: { type: Function, default: null },
  contextChips: { type: Array, default: () => [] },
  permissionMode: { type: String, default: 'acceptEdits' },
  viewOnly: { type: Boolean, default: false },
  allowReplyCopy: { type: Boolean, default: false },
  highlightedMessageId: { type: Number, default: null },
})

const emit = defineEmits([
  'send', 'stop', 'permission-decide', 'fill-input',
  'switch-model', 'switch-skill', 'refresh-models', 'use-welcome-suggestion',
  'regenerate', 'remove-chip', 'clear-chips',
  'load-older', 'retry-run', 'retry-narrow-run', 'continue-run', 'dismiss-run-failure',
  'add-workspace-file',
  'update:permission-mode',
  'feedback-change',
])

const formatCompletedDuration = durationMs => Number.isFinite(durationMs)
  ? `${Math.round(Math.max(0, durationMs) / 1000)}s`
  : '无'
const currentSegments = computed(() => groupProcessBlocks(props.currentBlocks))
const hasCurrentProcessSegment = computed(() => currentSegments.value.some(segment => segment.type === 'process_group'))
const streamGenerating = computed(() => {
  const latest = props.currentBlocks
    .filter(block => ['thinking', 'tool_use', 'text'].includes(block?.type))
    .at(-1)
  return latest?.type === 'text' && Boolean(String(latest.content || '').trim())
})
const streamProcessStatusLabel = computed(() => {
  const phase = props.runStatus?.phase
  if (hasCurrentProcessSegment.value) return ''
  if (phase === 'connecting') return '准备中'
  if (phase === 'queued') return '排队中'
  if (phase === 'waiting_permission') return '等待确认'
  if (phase === 'stopping') return '正在停止'
  const latest = props.currentBlocks
    .filter(block => ['thinking', 'tool_use', 'text'].includes(block?.type))
    .at(-1)
  if (!latest && phase === 'running') return '正在等待模型响应'
  return ''
})
const streamClockNow = ref(Date.now())
let streamClockTimer = null
const streamElapsedText = computed(() => {
  const startedAt = Number(props.runStartedAt)
  const elapsedMs = Number.isFinite(startedAt) && startedAt > 0
    ? Math.max(0, streamClockNow.value - startedAt)
    : 0
  return `${Math.floor(elapsedMs / 1000)}s`
})
const animatedChargedPoints = ref(null)
let chargedPointsAnimationFrame = null
const stopChargedPointsAnimation = () => {
  if (chargedPointsAnimationFrame !== null) cancelAnimationFrame(chargedPointsAnimationFrame)
  chargedPointsAnimationFrame = null
}
const animateChargedPoints = value => {
  stopChargedPointsAnimation()
  const target = Number(value)
  if (!Number.isFinite(target)) {
    animatedChargedPoints.value = null
    return
  }

  const start = Number.isFinite(animatedChargedPoints.value)
    ? animatedChargedPoints.value
    : 0
  if (Math.abs(target - start) < 0.0001) {
    animatedChargedPoints.value = target
    return
  }

  let startedAt = null
  const duration = Math.min(600, Math.max(220, Math.abs(target - start) * 260))
  const tick = timestamp => {
    if (startedAt === null) startedAt = timestamp
    const progress = Math.min(1, (timestamp - startedAt) / duration)
    const eased = 1 - ((1 - progress) ** 3)
    const next = start + ((target - start) * eased)
    animatedChargedPoints.value = Math.round(next * 100) / 100
    if (progress < 1) chargedPointsAnimationFrame = requestAnimationFrame(tick)
    else {
      animatedChargedPoints.value = target
      chargedPointsAnimationFrame = null
    }
  }
  chargedPointsAnimationFrame = requestAnimationFrame(tick)
}
watch(() => props.runChargedPoints, animateChargedPoints, { immediate: true })
const streamChargedPointsText = computed(() => formatCreditPoints(
  animatedChargedPoints.value ?? props.runChargedPoints,
))
watch(
  [() => props.streaming, () => props.runStartedAt],
  ([streaming]) => {
    if (streamClockTimer) clearInterval(streamClockTimer)
    streamClockTimer = null
    streamClockNow.value = Date.now()
    if (streaming) streamClockTimer = setInterval(() => { streamClockNow.value = Date.now() }, 1000)
  },
  { immediate: true },
)
onBeforeUnmount(() => {
  stopChargedPointsAnimation()
  if (streamClockTimer) clearInterval(streamClockTimer)
  streamClockTimer = null
})
const assistantDisplayName = computed(() => props.agentName?.trim() || 'AI Hub')
const nounNames = ref([])
const nounMatcher = computed(() => null)
const copyingMessage = ref(false)
async function copyMessageText(text) {
  if (copyingMessage.value) return
  if (!text?.trim()) { ElMessage.warning('无文本内容可复制'); return }
  copyingMessage.value = true
  try {
    await copyToClipboard(text)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.error('复制失败，请手动选择文本复制')
  } finally {
    copyingMessage.value = false
  }
}
function copyReply(message) {
  return copyMessageText((message.blocks || [])
    .filter(block => block.type === 'text')
    .map(block => block.content)
    .join('\n\n'))
}

const userMessageHtml = computed(() => new Map(props.displayMessages
  .filter(message => message.role === 'user')
  .map(message => [message.id, message._html])))
const assistantDisplayIcon = computed(() => props.agentIcon?.trim() || 'H')
// 单位尚未加载时暂缓展示消耗文案，不猜测平台配置的名称。
const creditUnitLabel = computed(() => props.creditDisplayName.trim())
const hasStreamCreditUsage = computed(() => props.runChargedPoints != null && !!creditUnitLabel.value)
const isEmptyConversation = computed(() => (
  !props.viewOnly
  && !props.historyLoading
  && !props.streaming
  && !props.runFailure
  && props.displayMessages.length === 0
))

const handleComposerEnter = (event) => {
  if (event.isComposing || event.keyCode === 229) return
  if (referenceMenuVisible.value) {
    event.preventDefault()
    if (referenceTrigger.value === '@') {
      if (referenceActiveIndex.value === 0) openReferenceFileUpload()
      else if (filteredWorkspaceFiles.value[referenceActiveIndex.value - 1]) {
        selectWorkspaceReference(filteredWorkspaceFiles.value[referenceActiveIndex.value - 1])
      }
    } else if (referenceTrigger.value === '/' && filteredReferenceSkills.value.length) {
      const skill = filteredReferenceSkills.value[referenceActiveIndex.value]
      if (skill) selectSkillReference(skill)
    }
    return
  }
  event.preventDefault()
  if (!props.historyLoading && !props.sendLocked && !props.streaming && !uploadingFiles.value && hasSendContent.value) emit('send')
}

const handleComposerKeydown = (event) => {
  if (event.key === 'Escape' && referenceMenuVisible.value) {
    event.preventDefault()
    dismissReferenceMenu()
    return
  }
  if (!referenceMenuVisible.value) return
  const optionCount = referenceTrigger.value === '@'
    ? filteredWorkspaceFiles.value.length + 1
    : filteredReferenceSkills.value.length
  if (!optionCount) return
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    const direction = event.key === 'ArrowDown' ? 1 : -1
    referenceActiveIndex.value = (referenceActiveIndex.value + direction + optionCount) % optionCount
  }
}

const handleComposerBlur = () => {
  if (referenceMenuVisible.value) dismissReferenceMenu()
}

const uploadingFiles = ref(0)
const imageChips = computed(() => props.contextChips.filter(chip => chip.previewUrl))
const inlineChips = computed(() => props.contextChips.filter(chip => !chip.previewUrl))
const referenceFileName = path => path.split(/[/\\]/).pop() || path
const messageFileReferences = message => (message.attachedFiles || []).filter(path => !/\.(png|jpe?g|gif|webp)$/i.test(path))
const handleReferenceBackspace = event => {
  if (event.isComposing || props.historyLoading || props.streaming || props.runtimeNotice) return
  if (!inlineChips.value.length) return
  event.preventDefault()
  emit('remove-chip', inlineChips.value.at(-1))
}
const hasSendContent = computed(() => inputText.value.trim() || props.contextChips.some(chip => chip.type === 'file'))
const composerPlaceholder = computed(() => {
  if (props.runtimeNotice) return props.runtimeNotice
  if (inputText.value.length > 0 || props.contextChips.length > 0) return ''
  return '输入问题或任务，@ 添加文件，/ 调用技能'
})

const hasTokenCount = tokens => Number.isFinite(tokens)
const messageFailed = message => message.failed || message.blocks?.some(block => block.type === 'error')
const savedErrorDetails = message => {
  if (!message._saved && props.runFailure) return null
  const error = message.blocks?.findLast(block => block.type === 'error')
  return error ? getAgentRunErrorDetails(error.content, error.error_code, error.metadata) : null
}

const formatTokenCount = tokens => (
  hasTokenCount(tokens) ? Math.round(tokens).toLocaleString() : '--'
)

const formatTurnTokenCount = tokens => (
  hasTokenCount(tokens)
    ? formatTokenCount(tokens)
    : '不可用'
)

const hasTurnMetrics = (metrics) => (
  Number.isFinite(metrics?.totalTokens)
  || (props.showCreditUsage && creditUnitLabel.value && Number.isFinite(metrics?.chargedPoints))
)

const turnMetricsTitle = (metrics) => {
  if (!metrics) return ''
  const parts = []
  if (Number.isFinite(metrics.cacheTokens)) {
    parts.push(`缓存输入 ${formatTokenCount(metrics.cacheTokens)}`)
  }
  if (Number.isFinite(metrics.nonCacheInputTokens)) {
    parts.push(`非缓存输入 ${formatTokenCount(metrics.nonCacheInputTokens)}`)
  }
  if (Number.isFinite(metrics.outputTokens)) parts.push(`输出 ${formatTokenCount(metrics.outputTokens)}`)
  if (props.showCreditUsage && creditUnitLabel.value && Number.isFinite(metrics.chargedPoints)) {
    parts.push(`${creditUnitLabel.value} ${formatCreditPoints(metrics.chargedPoints)}`)
  }
  if (Number.isFinite(metrics.cacheReadTokens)) {
    parts.push(`缓存读取 ${formatTokenCount(metrics.cacheReadTokens)}`)
  }
  if (Number.isFinite(metrics.cacheCreationTokens)) {
    parts.push(`缓存创建 ${formatTokenCount(metrics.cacheCreationTokens)}`)
  }
  return parts.join(' · ')
}

const inputText = defineModel('inputText', { type: String, default: '' })
const messagesRef = ref(null)
const messagesContentRef = ref(null)
const messagesScrolling = ref(false)
const messagesHasOverflow = ref(false)
const messagesNearTop = ref(true)
const messagesNearBottom = ref(true)
const messagesScrollPercent = ref(0)
const scrollDragging = ref(false)
const unseenStreamContent = ref(false)
const messagesScrollThumbStyle = ref({ height: '0px', transform: 'translateY(0px)' })
const messageInputRef = ref(null)
const defaultWelcomeSuggestions = [
  '给我一份简洁的工作周报模板',
  '帮我写一封项目进度跟进邮件',
].map(prompt => ({ key: prompt, prompt }))
const suggestionPool = computed(() => buildSkillSuggestions(props.agentSkills))
const suggestionSignature = computed(() => JSON.stringify(suggestionPool.value))
const skillSuggestions = ref([])
const welcomeSuggestions = computed(() =>
  props.showDefaultSuggestions && !skillSuggestions.value.length ? defaultWelcomeSuggestions : skillSuggestions.value,
)
const suggestionsRevision = ref(0)
const canRefreshSuggestions = computed(() => suggestionPool.value.some(
  candidate => !skillSuggestions.value.some(item => item.key === candidate.key),
))
const refreshSuggestions = () => {
  skillSuggestions.value = pickSkillSuggestions(suggestionPool.value, skillSuggestions.value)
  suggestionsRevision.value += 1
}
watch([suggestionSignature, () => props.suggestionKey], refreshSuggestions, { immediate: true })
const useWelcomeSuggestion = suggestion => {
  if (props.sendLocked || props.runtimeNotice || uploadingFiles.value > 0) return
  emit('use-welcome-suggestion', suggestion)
}
const referenceMenuRef = ref(null)
const fileInputRef = ref(null)
const inputAreaRef = ref(null)
const inputAreaWidth = ref(0)
const compactActionsVisible = ref(false)
const modelMenuVisible = ref(false)
const skillMenuVisible = ref(false)
const templateMenuVisible = ref(false)
const workspaceMenuVisible = ref(false)
const referenceMenuVisible = ref(false)
const referenceTrigger = ref('')
const referenceQuery = ref('')
const referenceActiveIndex = ref(0)
const workspaceFiles = ref([])
const workspaceFilesLoading = ref(false)
const referenceOptionsLoading = computed(() => referenceTrigger.value === '@'
  ? workspaceFilesLoading.value
  : props.agentSkillsLoading && props.agentSkills.length === 0,
)
let workspaceFilesRequest = 0
let referenceTriggerDismissed = false
const narrowInputArea = computed(() => inputAreaWidth.value < 520)
const veryNarrowInputArea = computed(() => inputAreaWidth.value < 400)
const visibleAgentModels = computed(() => getCompatibleModelsForRuntime(
  props.agentModels,
  props.runtimeType,
))
const selectedAgentModel = computed(() => visibleAgentModels.value.find(
  model => Number(model.id) === Number(props.selectedModelId),
))
const modelGroups = computed(() => getModelGroupsForRuntime(props.agentModels, props.runtimeType))
const selectedModelName = computed(() => selectedAgentModel.value?.name || '选择模型')
const permissionModeLabel = computed(() => (
  props.permissionMode === 'default' ? '逐次确认' : '默认权限'
))
const workspaceFileQuery = computed(() => referenceTrigger.value === '@' ? referenceQuery.value.trim().toLowerCase() : '')
const filteredWorkspaceFiles = computed(() => {
  const query = workspaceFileQuery.value
  if (!query) return workspaceFiles.value
  return workspaceFiles.value.filter(file => String(file.path || file.name || '').toLowerCase().includes(query))
})
const filteredReferenceSkills = computed(() => {
  const query = referenceTrigger.value === '/' ? referenceQuery.value.trim().toLowerCase() : ''
  if (!query) return props.agentSkills
  return props.agentSkills.filter(skill => String(skill.name || '').toLowerCase().includes(query))
})
let inputAreaObserver = null
let messagesContentObserver = null
let messagesScrollTimer = null
let previousMessagesScrollTop = 0
let historyAutoLoadSuppressed = false
let historyAutoLoadReleaseFrame = null

const updateMessagesScrollIndicator = () => {
  const el = messagesRef.value
  if (!el) return
  const trackHeight = Math.max(0, el.clientHeight - 8)
  const scrollRange = el.scrollHeight - el.clientHeight
  messagesHasOverflow.value = scrollRange > 0
  messagesNearTop.value = scrollRange <= 0 || el.scrollTop <= 80
  messagesNearBottom.value = scrollRange <= 0 || scrollRange - el.scrollTop <= 80
  if (scrollRange <= 0 || trackHeight <= 0) return

  const thumbHeight = Math.min(trackHeight, Math.max(36, trackHeight * el.clientHeight / el.scrollHeight))
  const scrollProgress = Math.min(1, Math.max(0, el.scrollTop / scrollRange))
  messagesScrollPercent.value = Math.round(scrollProgress * 100)
  const thumbOffset = (trackHeight - thumbHeight) * scrollProgress
  messagesScrollThumbStyle.value = {
    height: `${thumbHeight}px`,
    transform: `translateY(${thumbOffset}px)`,
  }
}

const handleMessagesScroll = () => {
  const el = messagesRef.value
  const currentScrollTop = el?.scrollTop || 0
  const scrollingUp = currentScrollTop < previousMessagesScrollTop - 1
  previousMessagesScrollTop = currentScrollTop
  updateMessagesScrollIndicator()
  if (messagesNearBottom.value) unseenStreamContent.value = false
  messagesScrolling.value = true
  window.clearTimeout(messagesScrollTimer)
  messagesScrollTimer = window.setTimeout(() => {
    messagesScrolling.value = false
  }, 500)
  if (
    el
    && scrollingUp
    && currentScrollTop <= 48
    && props.historyHasMore
    && !props.historyLoading
    && !props.olderHistoryLoading
    && !props.viewOnly
    && !historyAutoLoadSuppressed
  ) {
    emit('load-older')
  }
}

const setScrollFromPointer = (event) => {
  const track = event.currentTarget
  const el = messagesRef.value
  if (!track || !el) return
  const rect = track.getBoundingClientRect()
  const trackHeight = rect.height
  const thumbHeight = Math.min(trackHeight, Math.max(36, trackHeight * el.clientHeight / el.scrollHeight))
  const availableTrack = Math.max(1, trackHeight - thumbHeight)
  const progress = Math.min(1, Math.max(0, (event.clientY - rect.top - thumbHeight / 2) / availableTrack))
  el.scrollTop = progress * Math.max(0, el.scrollHeight - el.clientHeight)
}

const scrollMessagesBy = (delta) => {
  messagesRef.value?.scrollBy({ top: delta, behavior: 'auto' })
}

const scrollMessagesTo = (top) => {
  messagesRef.value?.scrollTo({ top, behavior: 'auto' })
}

const scrollMessagesToEnd = () => {
  const el = messagesRef.value
  if (el) scrollMessagesTo(el.scrollHeight)
}

const startScrollDrag = (event) => {
  scrollDragging.value = true
  messagesScrolling.value = true
  event.currentTarget.setPointerCapture(event.pointerId)
  setScrollFromPointer(event)
}

const moveScrollDrag = (event) => {
  if (!scrollDragging.value) return
  setScrollFromPointer(event)
}

const endScrollDrag = (event) => {
  if (!scrollDragging.value) return
  scrollDragging.value = false
  if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
    event.currentTarget.releasePointerCapture(event.pointerId)
  }
  handleMessagesScroll()
}

const updateInputAreaWidth = () => {
  if (inputAreaRef.value) {
    inputAreaWidth.value = inputAreaRef.value.getBoundingClientRect().width
  }
}

onMounted(() => {
  document.addEventListener('pointerdown', handleReferenceOutsidePointerDown, true)
  updateInputAreaWidth()
  nextTick(updateMessagesScrollIndicator)
  if (typeof ResizeObserver !== 'undefined') {
    if (inputAreaRef.value) {
      inputAreaObserver = new ResizeObserver(updateInputAreaWidth)
      inputAreaObserver.observe(inputAreaRef.value)
    }
    if (messagesContentRef.value) {
      messagesContentObserver = new ResizeObserver(updateMessagesScrollIndicator)
      messagesContentObserver.observe(messagesContentRef.value)
    }
  } else {
    window.addEventListener('resize', updateInputAreaWidth)
  }
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', handleReferenceOutsidePointerDown, true)
  inputAreaObserver?.disconnect()
  messagesContentObserver?.disconnect()
  window.removeEventListener('resize', updateInputAreaWidth)
  window.clearTimeout(messagesScrollTimer)
  window.cancelAnimationFrame(historyAutoLoadReleaseFrame)
})

// 文件上传
const openFileUpload = () => {
  fileInputRef.value?.click()
}

const removeReferenceTrigger = () => {
  inputText.value = inputText.value.replace(/(^|\s)[@/]\S*$/, '$1')
}

const closeReferenceMenu = () => {
  referenceMenuVisible.value = false
  referenceTrigger.value = ''
  referenceQuery.value = ''
  referenceActiveIndex.value = 0
}

const dismissReferenceMenu = () => {
  if (!referenceMenuVisible.value) return
  referenceTriggerDismissed = true
  closeReferenceMenu()
}

function handleReferenceOutsidePointerDown(event) {
  if (!referenceMenuVisible.value) return
  const target = event.target
  if (referenceMenuRef.value?.contains(target) || messageInputRef.value?.containsTarget?.(target)) return
  dismissReferenceMenu()
}

const selectWorkspaceReference = (file) => {
  referenceTriggerDismissed = false
  removeReferenceTrigger()
  closeReferenceMenu()
  emit('add-workspace-file', file)
  nextTick(() => messageInputRef.value?.focus())
}

const selectSkillReference = (skill) => {
  referenceTriggerDismissed = false
  removeReferenceTrigger()
  closeReferenceMenu()
  emit('switch-skill', skill.id)
  nextTick(() => messageInputRef.value?.focus())
}

const openReferenceFileUpload = () => {
  referenceTriggerDismissed = false
  removeReferenceTrigger()
  closeReferenceMenu()
  openFileUpload()
}

const loadWorkspaceFiles = async () => {
  const requestId = ++workspaceFilesRequest
  if (!props.agentId) {
    workspaceFiles.value = []
    workspaceFilesLoading.value = false
    return
  }
  workspaceFilesLoading.value = true
  try {
    const files = []
    const pending = ['']
    const visited = new Set()
    while (pending.length && files.length < 300) {
      const path = pending.shift()
      if (visited.has(path)) continue
      visited.add(path)
      const response = await api.get(`/agents/${props.agentId}/files`, {
        params: path ? { path } : {},
      })
      for (const item of response?.items || []) {
        if (item.type === 'file') files.push({ name: item.name, path: item.path, size: item.size })
        else if (item.type === 'dir' && pending.length + files.length < 300) pending.push(item.path)
      }
    }
    if (requestId !== workspaceFilesRequest) return
    workspaceFiles.value = files
  } catch {
    if (requestId === workspaceFilesRequest) workspaceFiles.value = []
  } finally {
    if (requestId === workspaceFilesRequest) workspaceFilesLoading.value = false
  }
}

const openCompactFileUpload = () => {
  compactActionsVisible.value = false
  openFileUpload()
}

watch(inputText, value => {
  if (props.viewOnly || props.historyLoading || props.streaming || props.runtimeNotice) {
    closeReferenceMenu()
    return
  }
  const match = String(value || '').match(/(?:^|\s)([@/])([^\s]*)$/)
  if (!match) {
    referenceTriggerDismissed = false
    closeReferenceMenu()
    return
  }
  if (referenceTriggerDismissed) {
    closeReferenceMenu()
    return
  }
  const wasVisible = referenceMenuVisible.value && referenceTrigger.value === match[1]
  referenceTrigger.value = match[1]
  referenceQuery.value = match[2] || ''
  if (!wasVisible) referenceActiveIndex.value = 0
  referenceMenuVisible.value = true
  if (!wasVisible && match[1] === '@' && workspaceFiles.value.length === 0 && !workspaceFilesLoading.value) {
    void loadWorkspaceFiles()
  }
})

watch(
  () => [props.historyLoading, props.streaming, props.runtimeNotice, props.viewOnly],
  ([historyLoading, streaming, runtimeNotice, viewOnly]) => {
    if (historyLoading || streaming || runtimeNotice || viewOnly) closeReferenceMenu()
  },
)

watch(() => props.agentId, () => {
  workspaceFilesRequest += 1
  workspaceFiles.value = []
  workspaceFilesLoading.value = false
  if (referenceTrigger.value === '@' && referenceMenuVisible.value) void loadWorkspaceFiles()
})

const closeCompactSubmenus = () => {
  skillMenuVisible.value = false
  templateMenuVisible.value = false
  workspaceMenuVisible.value = false
}

watch(() => props.suggestionKey, () => {
  compactActionsVisible.value = false
  modelMenuVisible.value = false
  closeCompactSubmenus()
})

const openCompactSubmenu = (submenu) => {
  if (submenu !== 'skills') skillMenuVisible.value = false
  if (submenu !== 'templates') templateMenuVisible.value = false
  if (submenu !== 'workspace') workspaceMenuVisible.value = false
  if (submenu === 'workspace' && workspaceFiles.value.length === 0 && !workspaceFilesLoading.value) {
    void loadWorkspaceFiles()
  }
}

const handlePermissionModeSelect = (mode) => {
  emit('update:permission-mode', mode)
}

const handleModelSelect = (id) => {
  emit('switch-model', id)
  modelMenuVisible.value = false
}

const handleCompactSkillSelect = (id) => {
  emit('switch-skill', id)
  compactActionsVisible.value = false
}

const handleCompactWorkspaceSelect = (file) => {
  selectWorkspaceReference(file)
  compactActionsVisible.value = false
}

const handleCompactTemplateSelect = (template) => {
  handleUseTemplate(template)
  compactActionsVisible.value = false
}

watch(compactActionsVisible, (visible) => {
  if (visible) closeReferenceMenu()
  if (visible) modelMenuVisible.value = false
  else closeCompactSubmenus()
})

watch(modelMenuVisible, (visible) => {
  if (visible) compactActionsVisible.value = false
})

const handleFileChange = async (e) => {
  const files = Array.from(e.target.files || [])
  e.target.value = ''
  await uploadFiles(files)
}

const uploadFiles = async (files) => {
  if (!props.uploadFile || props.viewOnly || props.historyLoading || props.streaming || props.runtimeNotice) return
  uploadingFiles.value += files.length
  await Promise.all(files.map(async file => {
    try {
      await props.uploadFile(file)
    } catch {
      ElMessage.error(`上传失败: ${file.name}`)
    } finally {
      uploadingFiles.value -= 1
    }
  }))
}

const handleComposerPaste = (event) => {
  const images = Array.from(event.clipboardData?.items || [])
    .filter(item => item.kind === 'file' && item.type.startsWith('image/'))
    .map(item => item.getAsFile())
    .filter(Boolean)
  if (!images.length || !props.uploadFile) return
  // Text-only paste retains the browser's native caret and selection behavior.
  event.preventDefault()
  const files = images.map(file => {
    const extension = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/webp': 'webp', 'image/gif': 'gif' }[file.type]
    const id = Array.from(crypto.getRandomValues(new Uint8Array(12)), byte => byte.toString(16).padStart(2, '0')).join('')
    return new File([file], `screenshot-${Date.now()}-${id}.${extension || 'img'}`, { type: file.type })
  })
  void uploadFiles(files)
}

// ---- 提示词模板：选模板 -> 有变量弹窗收集 -> 渲染后填入输入框（不自动发送） ----
const varDialogVisible = ref(false)
const currentTemplate = ref(null)
const currentVariables = ref([])
const varForm = ref({})

const parseVariables = (str) => {
  if (!str) return []
  try {
    return JSON.parse(str)
  } catch {
    return []
  }
}

const renderTemplate = (template, values) => {
  const content = template.content || ''
  return content.replace(/\{\{(\w+)\}\}/g, (_, name) => {
    const val = values?.[name]
    return val !== undefined && val !== '' ? String(val) : ''
  })
}

const appendToInput = (text) => {
  inputText.value = inputText.value ? inputText.value + '\n' + text : text
}

const handleUseTemplate = (template) => {
  const vars = parseVariables(template.variables)
  if (vars.length === 0) {
    // 无变量：直接填入输入框（不自动发送）
    appendToInput(template.content)
    return
  }
  // 有变量：弹窗收集
  currentTemplate.value = template
  currentVariables.value = vars
  varForm.value = {}
  vars.forEach(v => {
    varForm.value[v.name] = v.default ?? ''
  })
  varDialogVisible.value = true
}

const confirmVariables = () => {
  for (const v of currentVariables.value) {
    if (v.required && !String(varForm.value[v.name] ?? '').trim()) {
      ElMessage.warning(`请填写变量：${v.name}`)
      return
    }
  }
  const rendered = renderTemplate(currentTemplate.value, varForm.value)
  appendToInput(rendered)
  varDialogVisible.value = false
}

const scrollToBottom = (smooth = true) => {
  messagesNearBottom.value = true
  unseenStreamContent.value = false
  historyAutoLoadSuppressed = true
  window.cancelAnimationFrame(historyAutoLoadReleaseFrame)
  nextTick(() => {
    const el = messagesRef.value
    if (!el) {
      historyAutoLoadSuppressed = false
      return
    }
    el.scrollTo({
      top: el.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto',
    })
    previousMessagesScrollTop = el.scrollTop
    historyAutoLoadReleaseFrame = window.requestAnimationFrame(() => {
      previousMessagesScrollTop = el.scrollTop
      historyAutoLoadSuppressed = false
    })
    // 平滑滚动期间由 scroll 事件持续更新，避免动画刚开始就误判为离开底部。
    if (!smooth) updateMessagesScrollIndicator()
  })
}

const scrollToTop = (smooth = true) => {
  historyAutoLoadSuppressed = true
  window.cancelAnimationFrame(historyAutoLoadReleaseFrame)
  nextTick(() => {
    const el = messagesRef.value
    if (!el) {
      historyAutoLoadSuppressed = false
      return
    }
    el.scrollTo({
      top: 0,
      behavior: smooth ? 'smooth' : 'auto',
    })
    previousMessagesScrollTop = el.scrollTop
    historyAutoLoadReleaseFrame = window.requestAnimationFrame(() => {
      previousMessagesScrollTop = el.scrollTop
      historyAutoLoadSuppressed = false
    })
    if (!smooth) updateMessagesScrollIndicator()
  })
}

const followStream = () => {
  if (!messagesNearBottom.value) {
    nextTick(updateMessagesScrollIndicator)
    return
  }
  scrollToBottom(false)
}

watch(() => props.currentBlocks, () => {
  if (props.streaming && !messagesNearBottom.value) unseenStreamContent.value = true
})

// 暴露给父组件：流式内容只在用户仍停留在底部时自动跟随。
defineExpose({
  focusInput: () => {
    nextTick(() => messageInputRef.value?.focus())
  },
  scrollToBottom,
  scrollToTop,
  followStream,
  getScrollSnapshot: () => ({
    height: messagesRef.value?.scrollHeight || 0,
    top: messagesRef.value?.scrollTop || 0,
  }),
  restoreAfterPrepend: (snapshot) => {
    nextTick(() => {
      const el = messagesRef.value
      if (!el) return
      const addedHeight = Math.max(0, el.scrollHeight - (snapshot?.height || 0))
      el.scrollTop = (snapshot?.top || 0) + addedHeight
      updateMessagesScrollIndicator()
    })
  },
})
</script>

<style scoped>
.chip-image { width: 64px; height: 48px; flex: 0 0 64px; box-sizing: border-box; border: 1px solid var(--chat-image-border); background: #fff; border-radius: 4px; }
.composer-status { position: absolute; bottom: calc(100% + 6px); left: 0; display: flex; max-width: 100%; align-items: center; gap: 10px; pointer-events: none; }
.upload-status { display: flex; align-items: center; gap: 6px; color: #606266; font-size: calc(12px + var(--workspace-font-size-offset, 0px)); line-height: 18px; }
.identity-mcp-status { display: flex; align-items: flex-start; gap: 9px; padding: 10px 12px; color: #737373; font-size: 12px; line-height: 20px; }
.identity-mcp-status > .el-icon { flex-shrink: 0; margin-top: 3px; font-size: 15px; }
.identity-mcp-status > div { min-width: 0; }
.identity-mcp-status small { display: block; margin-top: 2px; color: #858585; font-size: 11px; overflow-wrap: anywhere; }
.chat-main {
  --chat-image-border: #e4e7ed;
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #fff;
  min-width: 0;
  min-height: 0;
}

.chat-main.is-empty-conversation {
  justify-content: flex-start;
  overflow-y: auto;
  /* Anchor the composer independently of asynchronously loaded suggestions. */
  padding-top: calc(clamp(32px, 12vh, 120px) + 100px);
  padding-bottom: 32px;
  box-sizing: border-box;
}

.chat-main.is-empty-conversation .messages-shell {
  width: 100%;
  min-height: 0;
  flex: 0 0 auto;
}

.chat-main.is-empty-conversation .messages {
  width: 100%;
  min-height: 0;
  flex: 0 1 auto;
  overflow: visible;
  padding-top: 0;
  padding-bottom: 0;
  box-sizing: border-box;
}

.chat-main.is-empty-conversation .messages-content {
  min-height: 0;
}

.messages-shell {
  position: relative;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex: 1;
}

.messages {
  flex: 1;
  overflow-y: auto;
  padding: 28px max(24px, calc((100% - 840px) / 2)) 36px;
  scrollbar-width: none;
}
.messages-content {
  width: 100%;
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

.older-messages-loader {
  display: flex;
  justify-content: center;
  min-height: 30px;
  margin: -10px 0 12px;
}
.messages::-webkit-scrollbar {
  width: 0;
  height: 0;
}

.messages-scroll-indicator {
  position: absolute;
  z-index: 4;
  top: 4px;
  right: 3px;
  bottom: 4px;
  width: 6px;
  border-radius: 3px;
  background: rgba(225, 229, 234, 0.72);
  opacity: 0;
  cursor: pointer;
  touch-action: none;
  transition: opacity 0.15s ease;
}
.messages-scroll-indicator.visible {
  opacity: 1;
}
.messages-scroll-indicator:hover {
  opacity: 1;
}
.messages-scroll-indicator span {
  width: 6px;
  display: block;
  border-radius: 3px;
  background: #7d8792;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, 0.65);
  will-change: transform;
  pointer-events: none;
}

.scroll-navigation-control {
  position: absolute;
  z-index: 5;
  bottom: 16px;
  display: flex;
  align-items: center;
  gap: 7px;
}

.scroll-navigation-buttons {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.new-content-label {
  padding: 4px 8px;
  border: 1px solid #d8dee4;
  border-radius: 4px;
  color: #52606d;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 2px 8px rgba(31, 45, 61, 0.12);
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
  line-height: 18px;
}

.scroll-navigation-button.el-button {
  width: 34px;
  height: 34px;
  margin-left: 0;
  padding: 0;
  border-color: #d8dee4;
  color: #52606d;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 3px 10px rgba(31, 45, 61, 0.16);
}

.scroll-navigation-button.el-button:hover {
  color: #1f5f99;
  border-color: #a9bfd2;
  background: #fff;
}

/* 欢迎页 */
.welcome {
  width: min(620px, 100%);
  min-height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  margin: auto;
  padding: 56px 20px 48px;
  text-align: center;
  box-sizing: border-box;
}
.is-empty-conversation .welcome {
  width: 100%;
  min-height: 0;
  padding-top: 0;
  padding-bottom: 24px;
}
.is-empty-conversation .welcome-title {
  margin-bottom: 0;
}
.welcome-title {
  margin: 0 0 22px;
  color: #181818;
  font-size: calc(27px + var(--workspace-font-size-offset, 0px));
  font-weight: 500;
  letter-spacing: .3px;
  line-height: 1.5;
}
.welcome-subtitle { margin: 10px 0 0; color: #888; font-size: calc(13px + var(--workspace-font-size-offset, 0px)); line-height: 1.6; }
.welcome-suggestions { margin-top: 28px; }
.suggestions-heading { display: flex; align-items: center; justify-content: space-between; min-height: 28px; margin-bottom: 10px; color: #888; font-size: calc(11px + var(--workspace-font-size-offset, 0px)); }
.suggestions-refresh { display: inline-flex; align-items: center; gap: 5px; min-height: 28px; padding: 0 6px; border: 0; border-radius: 6px; background: transparent; color: #888; font: inherit; cursor: pointer; }
.suggestions-refresh:hover { color: #181818; background: #f5f5f5; }
.suggestions-list { display: flex; flex-direction: column; align-items: flex-start; gap: 10px; animation: suggestions-fade-in .35s ease-out both; }
@keyframes suggestions-fade-in {
  from { opacity: 0; }
  to { opacity: 1; }
}
.suggestion-item { display: inline-flex; align-items: center; gap: 12px; max-width: 100%; min-height: 38px; padding: 8px 15px; border: 1px solid #e8e8e8; border-radius: 20px; box-sizing: border-box; background: #fff; color: #262626; box-shadow: 0 2px 4px rgba(0, 0, 0, .025); font: inherit; font-size: calc(12px + var(--workspace-font-size-offset, 0px)); text-align: left; line-height: 20px; cursor: pointer; transition: background .15s, border-color .15s; }
.suggestion-text { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.suggestion-item > .el-icon { flex-shrink: 0; font-size: 14px; color: #555; }
.suggestion-item:hover:not(:disabled) { background: #f7f7f7; border-color: #d9d9d9; }
.suggestion-item:disabled { opacity: .5; cursor: not-allowed; }
.welcome-suggestions button:focus-visible { outline: 2px solid #858585; outline-offset: 3px; }
.welcome-desc {
  margin: 0 0 28px;
  font-size: calc(14px + var(--workspace-font-size-offset, 0px));
  color: #909399;
  max-width: 400px;
  line-height: 1.6;
}
.message-row {
  margin-bottom: 28px;
  display: flex;
}
.message-row.user {
  justify-content: flex-end;
  margin-bottom: 24px;
}
.message-row.assistant {
  justify-content: flex-start;
}

.user-bubble {
  background: #f1f2f3;
  color: #1f2330;
  padding: 10px 15px;
  border-radius: 20px;
  max-width: min(76%, 680px);
  font-size: calc(14px + var(--workspace-font-size-offset, 0px));
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.user-message-stack {
  position: relative;
  min-width: 0;
  max-width: min(76%, 680px);
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 12px;
}
.user-message-actions { position: absolute; top: 100%; right: 0; display: flex; align-items: center; gap: 8px; height: 24px; white-space: nowrap; color: #909399; font-size: calc(12px + var(--workspace-font-size-offset, 0px)); opacity: 0; pointer-events: none; }
.user-message-stack:hover .user-message-actions, .user-message-stack:focus-within .user-message-actions { opacity: 1; pointer-events: auto; }
@media (hover: none) { .user-message-actions { opacity: 1; pointer-events: auto; } }
.user-message-images {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  max-width: 100%;
}
.user-message-stack .user-bubble {
  max-width: 100%;
}
.message-reference { display: inline-flex; align-items: center; gap: 4px; max-width: 100%; margin: 0 6px 3px 0; padding: 1px 7px; border-radius: 6px; background: #e1e6e9; color: #38454f; font-size: calc(13px + var(--workspace-font-size-offset, 0px)); vertical-align: middle; box-sizing: border-box; }
.message-reference > span { min-width: 0; overflow-wrap: anywhere; }
.message-reference .el-icon { flex-shrink: 0; }
.user-bubble.has-references .markdown-body { display: inline; }
.user-bubble.has-references :deep(.markdown-body > p:first-child) { display: inline; }
/* 气泡内链接:靛蓝 + 下划线,浅底上清晰可辨,覆盖浏览器默认蓝/紫 */
.user-bubble :deep(a),
.user-bubble :deep(a:visited) {
  color: #4d5bf5;
  font-weight: 500;
  text-decoration: underline;
  text-decoration-color: rgba(77, 91, 245, 0.45);
  text-underline-offset: 2px;
  transition: color 0.15s, text-decoration-color 0.15s;
}
.user-bubble :deep(a:hover) {
  color: #3a47d6;
  text-decoration-color: #3a47d6;
}
.user-bubble :deep(a.noun-explanation-link),
.user-bubble :deep(a.noun-explanation-link:visited),
.user-bubble :deep(a.noun-explanation-link:hover),
.user-bubble :deep(a.noun-explanation-link:active) {
  color: #0969da;
  text-decoration: none;
  background: rgba(9, 105, 218, 0.07);
  border-radius: 3px;
  display: inline-block;
  margin: 0 0.12em;
  padding: 0.06em 0.12em;
}
.user-bubble :deep(a.noun-explanation-link:hover) { text-decoration: underline; }
.user-bubble :deep(.noun-explanation-link strong) { font-weight: 600; }

.message-content {
  width: 100%;
}
.assistant-identity {
  min-height: 28px;
  display: flex;
  align-items: center;
  gap: 9px;
  margin-bottom: 12px;
  color: #2d3137;
}
.assistant-avatar.image-avatar { background: transparent; }
.assistant-avatar {
  width: 22px;
  height: 22px;
  display: grid;
  flex: 0 0 22px;
  place-items: center;
  border-radius: 50%;
  color: #fff;
  background: #30343a;
  overflow: hidden;
  font-size: calc(11px + var(--workspace-font-size-offset, 0px));
  font-weight: 700;
  line-height: 1;
  white-space: nowrap;
}
.assistant-identity strong {
  min-width: 0;
  overflow: hidden;
  font-size: calc(14px + var(--workspace-font-size-offset, 0px));
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.stream-run-elapsed,
.completed-run-elapsed {
  min-height: 22px;
  margin: -2px 0 8px;
  color: #858b93;
  font-size: calc(14px + var(--workspace-font-size-offset, 0px));
  font-weight: 400;
  line-height: 22px;
  font-variant-numeric: tabular-nums;
}
.completed-run-elapsed {
  display: flex;
  align-items: center;
  gap: 6px;
}
.completed-run-elapsed .el-icon { font-size: 14px; }
.stream-process-status {
  height: 22px;
  box-sizing: border-box;
  margin: 8px 0;
  color: #a0a5ac;
  font-size: calc(14px + var(--workspace-font-size-offset, 0px));
  font-weight: 400;
  line-height: 22px;
}
.assistant-footer {
  container: turn-footer / inline-size;
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
  min-height: 26px;
  margin-top: 5px;
}
.context-notice {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  margin: 0 0 8px;
  color: #667085;
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
  line-height: 18px;
}
.context-notice .el-icon {
  flex: 0 0 auto;
  color: #7a8594;
}
.context-notice span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.turn-metrics {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
  min-height: 20px;
  margin-top: 0;
  color: #969ba3;
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
  line-height: 20px;
  font-variant-numeric: tabular-nums;
}
.turn-metrics.is-fresh {
  transform-origin: left center;
  animation: turn-metrics-enter 420ms cubic-bezier(0.22, 1, 0.36, 1) both;
}
.turn-metric {
  display: inline-flex;
  align-items: baseline;
  gap: 3px;
  white-space: nowrap;
}
.turn-metric-label,
.turn-metric-detail {
  color: inherit;
}
.turn-metric-value {
  color: inherit;
}
.turn-metrics-separator {
  color: inherit;
}
.input-breakdown {
  color: inherit;
}
@container turn-footer (max-width: 720px) {
  .input-breakdown { display: none; }
}
.cache-status {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 4px;
  color: inherit;
  font-weight: 400;
  white-space: nowrap;
}
.cache-status-indicator {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: #b4b9c0;
  flex: 0 0 auto;
}
.cache-status.hit .cache-status-indicator {
  background: #82aa8b;
}
.turn-metrics-pending {
  opacity: 0.7;
}
.inline-run-status {
  min-height: 22px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 2px;
  color: #667085;
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
  line-height: 18px;
}
.inline-run-status .el-icon {
  flex: 0 0 auto;
  font-size: 13px;
}
.stream-run-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  min-height: 22px;
  margin-top: 8px;
  color: #969ba3;
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
  line-height: 22px;
  font-variant-numeric: tabular-nums;
}
.stream-run-meta-item { display: inline-flex; align-items: center; gap: 6px; }
.stream-run-meta-separator { color: #c5c9ce; }
.stream-run-meta-status { color: #a0a5ac; }
.stream-run-meta strong { color: #6f747b; font-weight: 500; }
.run-failure-row {
  margin-top: 2px;
}
.run-failure-inline {
  width: min(100%, 760px);
  min-height: 56px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid #f1b8b4;
  border-radius: 6px;
  background: #fff6f5;
  color: #b42318;
  font-size: calc(13px + var(--workspace-font-size-offset, 0px));
  line-height: 20px;
}
.run-failure-icon {
  flex: 0 0 auto;
  align-self: flex-start;
  margin-top: 2px;
  font-size: 17px;
}
.run-failure-copy {
  min-width: 0;
  display: flex;
  flex: 1 1 260px;
  flex-direction: column;
  gap: 2px;
}
.run-failure-copy strong {
  color: #912018;
  font-size: calc(14px + var(--workspace-font-size-offset, 0px));
  font-weight: 600;
}
.run-failure-message {
  min-width: 0;
  color: #69413e;
  overflow-wrap: anywhere;
}
.run-failure-actions {
  display: flex;
  flex: 0 1 auto;
  align-items: center;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 2px;
}
.run-failure-close.el-button {
  width: 24px;
  height: 24px;
  padding: 0;
  align-self: flex-start;
}
@media (max-width: 720px) {
  .run-failure-inline { align-items: flex-start; flex-wrap: wrap; }
  .run-failure-actions { width: 100%; justify-content: flex-start; padding-left: 27px; }
}
.metrics-skeleton {
  display: inline-block;
  height: 7px;
  border-radius: 2px;
  background: linear-gradient(90deg, #eceef1 25%, #f6f7f8 50%, #eceef1 75%);
  background-size: 200% 100%;
  animation: metrics-skeleton-shimmer 1.4s ease-in-out infinite;
}
.metrics-skeleton-short { width: 52px; }
.metrics-skeleton-long { width: 68px; }

@keyframes turn-metrics-enter {
  from {
    opacity: 0;
    transform: translateY(4px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
@keyframes metrics-skeleton-shimmer {
  from { background-position: 100% 0; }
  to { background-position: -100% 0; }
}

@media (prefers-reduced-motion: reduce) {
  .turn-metrics.is-fresh,
  .metrics-skeleton {
    animation: none;
  }
}

.text-block {
  min-width: 0;
  margin-bottom: 8px;
}

/* 等待首块响应 */
.thinking-indicator {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 28px;
  padding: 0;
  color: #777d85;
  font-size: calc(13px + var(--workspace-font-size-offset, 0px));
  font-weight: 500;
}
.thinking-dots {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.thinking-dots .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #858b93;
  animation: dot-wave 1.2s ease-in-out infinite;
}
.thinking-dots .dot:nth-child(2) { animation-delay: 0.18s; }
.thinking-dots .dot:nth-child(3) { animation-delay: 0.36s; }
.thinking-indicator-text { letter-spacing: 0; }
.thinking-status-icon {
  width: 21px;
  flex: 0 0 21px;
  font-size: 15px;
}
@keyframes dot-wave {
  0%, 60%, 100% { transform: translateY(0) scale(0.8); opacity: 0.45; }
  30% { transform: translateY(-5px) scale(1); opacity: 1; }
}
.runtime-notice {
  width: min(840px, calc(100% - 40px));
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 4px auto 0;
  padding: 8px 12px;
  border: 1px solid #eee3cf;
  border-radius: 8px;
  background: #fffaf2;
  color: #7c6846;
  font-size: calc(13px + var(--workspace-font-size-offset, 0px));
  line-height: 20px;
  flex-shrink: 0;
  box-sizing: border-box;
}
.is-empty-conversation .runtime-notice {
  width: min(720px, calc(100% - 40px));
  margin-bottom: 8px;
}
.runtime-notice.pending {
  border-color: #dfe7ef;
  background: #f6f8fb;
  color: #64768a;
}
.runtime-notice span {
  min-width: 0;
  overflow-wrap: anywhere;
}

.input-area {
  padding: 12px max(20px, calc((100% - 840px) / 2)) 18px;
  background: linear-gradient(to bottom, rgba(255, 255, 255, 0), #fff 18px);
  flex-shrink: 0;
}
.is-empty-conversation .input-area {
  width: 100%;
  padding: 0 max(20px, calc((100% - 840px) / 2));
  background: #fff;
  box-sizing: border-box;
}
.is-empty-conversation .composer-surface {
  border-radius: 20px;
}
.composer-surface {
  position: relative;
  padding: 12px 14px 12px;
  border: 1px solid #e6e6e6;
  border-radius: 18px;
  background: #fff;
  box-shadow: 0 6px 24px rgba(0, 0, 0, .04), 0 1px 3px rgba(0, 0, 0, .02);
  transition: border-color .15s, box-shadow .15s;
}
.composer-surface:focus-within { border-color: #bdbdbd; box-shadow: 0 6px 24px rgba(0, 0, 0, .055), 0 0 0 3px rgba(0, 0, 0, .045); }

.composer-reference-menu {
  position: absolute;
  z-index: 20;
  left: 10px;
  bottom: calc(100% - 4px);
  width: min(360px, calc(100% - 20px));
  max-height: min(360px, 52vh);
  overflow: hidden;
  border: 1px solid #d8dade;
  border-radius: 10px;
  background: #fff;
  box-shadow: 0 10px 28px rgba(31, 35, 41, .16);
}
.composer-reference-action,
.composer-reference-option {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 36px;
  padding: 8px 12px;
  border: 0;
  color: #30343a;
  background: transparent;
  text-align: left;
  cursor: pointer;
  box-sizing: border-box;
}
.composer-reference-action:hover,
.composer-reference-option:hover,
.composer-reference-action.active,
.composer-reference-option.active,
.composer-reference-option.selected { background: #f3f5f7; }
.composer-reference-action .el-icon,
.composer-reference-option .el-icon { flex: 0 0 auto; color: #5b6875; }
.composer-reference-action span,
.composer-reference-option span { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.composer-reference-action small { margin-left: auto; color: #98a0a8; font-size: calc(11px + var(--workspace-font-size-offset, 0px)); white-space: nowrap; }
.composer-reference-heading {
  padding: 7px 12px 5px;
  border-top: 1px solid #eef0f2;
  color: #8b929a;
  font-size: calc(11px + var(--workspace-font-size-offset, 0px));
  line-height: 16px;
}
.composer-reference-list { max-height: 260px; overflow-y: auto; }
.composer-reference-check { margin-left: auto; color: #409eff !important; }
.composer-reference-status {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-height: 36px;
  padding: 8px 12px;
  box-sizing: border-box;
  color: #737b84;
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
}

.input-row {
  margin-bottom: 8px;
}
.input-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.input-left {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  flex-shrink: 0;
}
.compact-actions-trigger.el-button {
  gap: 5px;
  height: 32px;
  padding: 0 9px;
  border-color: transparent;
  border-radius: 8px;
  color: #666666;
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
  background: transparent;
  flex-shrink: 0;
}
.compact-actions-trigger :deep(.el-icon) { font-size: 16px; }
.compact-actions-trigger :deep(.el-icon + span) { margin-left: 5px; }
.compact-actions-trigger.el-button:hover,
.compact-actions-trigger.el-button.is-open {
  border-color: transparent;
  background: #f2f3f5;
}
.compact-actions-menu {
  display: flex;
  flex-direction: column;
  max-height: min(440px, calc(100vh - 120px));
  overflow-y: auto;
  padding: 4px;
}
.compact-menu-item {
  width: 100%;
  min-height: 44px;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 0 10px;
  border: 0;
  border-radius: 7px;
  color: #303133;
  background: transparent;
  font: inherit;
  font-size: calc(14px + var(--workspace-font-size-offset, 0px));
  text-align: left;
  cursor: pointer;
  outline: none;
}
.compact-menu-item:hover,
.compact-menu-option.selected {
  background: #f4f5f6;
}
.compact-menu-item:focus-visible {
  background: #f4f5f6;
  box-shadow: inset 0 0 0 1px #c8ccd1;
}
.compact-menu-item > .el-icon {
  width: 20px;
  flex: 0 0 20px;
  color: #555b63;
  font-size: 19px;
}
.compact-menu-item > span:nth-child(2) {
  min-width: 0;
  white-space: nowrap;
}
.compact-menu-arrow.el-icon {
  width: 16px;
  margin-left: auto;
  flex: 0 0 16px;
  color: #8b9097;
  font-size: 14px;
}
.compact-menu-divider {
  height: 1px;
  margin: 5px 10px;
  background: #e5e7eb;
}
.compact-submenu-menu {
  min-height: 0;
}
.compact-submenu-title {
  min-height: 40px;
  display: flex;
  align-items: center;
  padding: 0 10px;
  color: #303133;
  font-size: calc(14px + var(--workspace-font-size-offset, 0px));
  font-weight: 600;
}
.compact-menu-option {
  min-height: 48px;
}
.compact-option-dot {
  width: 8px;
  height: 8px;
  margin-left: 6px;
  flex: 0 0 8px;
  border-radius: 50%;
}
.compact-option-dot.model { background: #409eff; }
.compact-option-dot.skill { background: #67c23a; }
.compact-option-dot.template { background: #b37feb; }
.compact-option-copy {
  min-width: 0;
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}
.compact-option-copy > span,
.compact-option-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.compact-option-copy small {
  color: #909399;
  font-size: calc(11px + var(--workspace-font-size-offset, 0px));
  font-weight: 400;
}
.compact-option-check.el-icon {
  width: 16px;
  flex: 0 0 16px;
  color: #303133;
  font-size: 14px;
}
.compact-menu-empty {
  min-height: 64px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 10px;
  color: #a0a5ac;
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
  text-align: center;
}
.permission-mode-trigger {
  height: 32px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 8px;
  border: 0;
  border-radius: 8px;
  color: #808080;
  background: transparent;
  font: inherit;
  font-size: calc(11px + var(--workspace-font-size-offset, 0px));
  white-space: nowrap;
  cursor: pointer;
}
.permission-mode-trigger:hover,
.permission-mode-trigger:focus-visible {
  outline: none;
  background: #f2f3f5;
}
.permission-mode-trigger > .el-icon:first-child {
  font-size: 15px;
}
.permission-mode-arrow.el-icon {
  color: #6f757d;
  font-size: 12px;
}
.permission-mode-option {
  min-width: 248px;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 3px 0;
}
.permission-mode-option > .el-icon:first-child {
  flex: 0 0 auto;
  color: #5c626a;
  font-size: 17px;
}
.permission-mode-option > span {
  min-width: 0;
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}
.permission-mode-option strong {
  color: #303133;
  font-size: calc(13px + var(--workspace-font-size-offset, 0px));
  font-weight: 500;
}
.permission-mode-option small {
  color: #909399;
  font-size: calc(11px + var(--workspace-font-size-offset, 0px));
}
.permission-option-check.el-icon {
  color: #303133;
  font-size: 14px;
}
.input-right {
  display: flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
  flex-shrink: 1;
}
.model-switch-trigger {
  min-width: 0;
  max-width: 180px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 0 9px;
  border: 0;
  border-radius: 8px;
  color: #666666;
  background: transparent;
  font: inherit;
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
  white-space: nowrap;
  cursor: pointer;
  outline: none;
}
.model-switch-trigger:hover,
.model-switch-trigger:focus-visible,
.model-switch-trigger.is-open {
  background: #f2f3f5;
}
.model-switch-trigger > span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
.model-switch-arrow.el-icon {
  flex: 0 0 auto;
  color: #777d85;
  font-size: 11px;
  transition: transform 0.16s ease;
}
.model-switch-trigger.is-open .model-switch-arrow {
  transform: rotate(180deg);
}
.model-switch-menu {
  max-height: min(360px, calc(100vh - 120px));
  overflow: hidden;
}
.model-switch-menu > :not(.model-options-list) {
  flex-shrink: 0;
}
.model-options-list {
  min-height: 48px;
  overflow-y: auto;
}
.workspace-file-options-list {
  min-height: 48px;
  max-height: min(320px, calc(100vh - 180px));
  overflow-y: auto;
}
.model-group-title {
  min-height: 28px;
  color: #909399;
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
  font-weight: 400;
}
.model-config-link {
  box-sizing: border-box;
  text-decoration: none;
}
.btn-group {
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 32px;
  margin-left: 8px;
}
.composer-action-button.el-button {
  width: 32px;
  min-width: 32px;
  height: 32px;
  min-height: 32px;
  flex: 0 0 32px;
  padding: 0;
  border-radius: 50%;
  font-size: 15px;
}
.composer-action-button :deep(.el-icon) {
  font-size: 15px;
}
.composer-action-button.el-button--primary {
  --el-button-hover-text-color: #fff;
  --el-button-hover-bg-color: #202329;
  --el-button-hover-border-color: #202329;
  --el-button-active-bg-color: #202329;
  --el-button-active-border-color: #202329;
  --el-button-disabled-text-color: #fff;
  --el-button-disabled-bg-color: #202329;
  --el-button-disabled-border-color: #202329;
  color: #fff;
  background: #202329;
  border-color: #202329;
  box-shadow: none;
}
.composer-action-button.el-button--primary.is-disabled {
  color: #a3a3a3;
  background: #f0f0f0;
  border-color: #f0f0f0;
  opacity: 1;
}
.composer-action-button.el-button--danger {
  color: #fff;
  background: #e64b4b;
  border-color: #e64b4b;
  box-shadow: 0 2px 6px rgba(230, 75, 75, 0.24);
}
.stop-square {
  width: 8px;
  height: 8px;
  display: block;
  border-radius: 1px;
  background: currentColor;
}
.input-area.is-narrow .input-right :deep(.token-usage.compact .usage-bar) {
  display: none;
}
.input-area.is-very-narrow .input-right :deep(.token-usage.compact) {
  display: none;
}
.input-area.is-very-narrow .permission-mode-trigger {
  width: 36px;
  padding: 0;
  justify-content: center;
}
.input-area.is-very-narrow .permission-mode-trigger > span,
.input-area.is-very-narrow .permission-mode-arrow {
  display: none;
}
.input-area.is-narrow .model-switch-trigger {
  max-width: 128px;
}
.input-area.is-very-narrow .model-switch-trigger {
  max-width: 112px;
}

:global(.composer-tools-popper.el-popover.el-popper) {
  padding: 6px;
  border-color: #dfe2e6;
  border-radius: 12px;
  box-shadow: 0 10px 30px rgba(28, 32, 39, 0.14);
}
:global(.model-switch-popper.el-popover.el-popper) {
  padding: 6px;
}

.user-bubble :deep(pre) {
  background: #1e2333;
  padding: 8px 10px;
  border-radius: 4px;
  color: #e6edf3;
}
.user-bubble :deep(code) {
  background: rgba(77, 91, 245, 0.1);
  color: #2f3550;
}
.user-bubble :deep(pre code) {
  background: transparent;
  color: #e6edf3;
}

/* 消息操作按钮 */
.msg-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  padding: 0;
  opacity: 0.58;
  transition: opacity 0.15s;
}
.msg-actions:has(.feedback-button.selected),
.message-row:hover .msg-actions,
.message-row:focus-within .msg-actions {
  opacity: 1;
}
.assistant-actions { margin: 0 0 0 2px; }
.assistant-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
.assistant-actions :deep(.msg-action-btn.el-button) {
  width: 26px;
  min-width: 26px;
  height: 26px;
  margin: 0;
  font-size: 14px;
  color: #909399;
  padding: 0;
}
.assistant-actions :deep(.msg-action-btn:hover) {
  color: #202329;
  background: #f0f1ef;
}

/* 上下文引用 chip */
.context-chips-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-height: 32px;
  max-height: 144px;
  overflow-y: auto;
  flex-shrink: 0;
  padding: 4px 6px 0;
  margin-bottom: 6px;
  box-sizing: border-box;
}

@media (hover: none) {
  .msg-actions { opacity: 1; }
}

@media (max-width: 560px) {
  .messages {
    padding: 24px 20px 28px;
  }

  .input-area {
    padding: 10px 14px 14px;
  }

  .runtime-notice {
    width: calc(100% - 28px);
  }

}

@media (max-width: 680px) {
  .welcome { padding-right: 14px; padding-left: 14px; }
  .welcome-title { font-size: calc(22px + var(--workspace-font-size-offset, 0px)); }
}
@media (max-width: 380px) {
  .is-empty-conversation .messages { padding-right: 14px; padding-left: 14px; }
  .is-empty-conversation .welcome { padding-right: 0; padding-left: 0; }
  .welcome-title { font-size: 20px; letter-spacing: 0; }
  .welcome-subtitle { font-size: 12px; }
}
@media (max-height: 600px) {
  .chat-main.is-empty-conversation { justify-content: flex-start; overflow-y: auto; padding-top: 20px; padding-bottom: 20px; }
  .chat-main.is-empty-conversation .messages-shell { flex-shrink: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .suggestions-list { animation: none; }
  .suggestion-item, .composer-surface { transition: none; }
  .composer-reference-status .is-loading { animation: none; }
}

.clear-chips-btn.el-button {
  height: 24px;
  margin-left: auto;
  padding: 0 6px;
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
  line-height: 24px;
  flex-shrink: 0;
}
.context-chip {
  height: 24px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0 8px;
  border-radius: 12px;
  box-sizing: border-box;
  font-size: calc(12px + var(--workspace-font-size-offset, 0px));
  line-height: 24px;
  user-select: none;
}
.context-chip.skill {
  background: #ecf5ff;
  color: #409eff;
}
.context-chip.file {
  background: #e8f4e8;
  color: #2e7d32;
}
.context-chip.has-preview {
  position: relative;
  width: 64px;
  height: 48px;
  flex: 0 0 64px;
  padding: 0;
  border-radius: 4px;
  background: transparent;
}
.chip-icon { width: 14px; height: 14px; flex: 0 0 14px; font-size: 13px; }
.chip-label { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chip-close {
  width: 14px;
  height: 14px;
  font-size: 12px;
  cursor: pointer;
  color: #909399;
  flex: 0 0 14px;
}
.chip-close:hover { color: #f56c6c; }
.has-preview .chip-close {
  position: absolute;
  top: 2px;
  right: 2px;
  z-index: 1;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: #606266;
  color: #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.16);
}
.has-preview .chip-close:hover { background: #303133; color: #fff; }
.has-preview .chip-close:focus-visible { outline: 2px solid #409eff; outline-offset: 1px; }
</style>

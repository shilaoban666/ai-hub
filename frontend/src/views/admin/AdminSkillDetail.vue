<template>
  <div class="skill-detail">
    <div class="detail-header">
      <el-button class="back-btn" @click="handleBack" :icon="ArrowLeft">返回</el-button>
      <div class="header-info">
        <h2
          v-if="!isEditingName"
          class="editable-name"
          @click="startEditName"
          :title="'点击编辑技能名称'"
        >
          {{ skill.name }}
        </h2>
        <el-input
          v-else
          v-model="editingName"
          @blur="saveSkillName"
          @keyup.enter="saveSkillName"
          ref="nameInputRef"
          size="large"
          class="name-input"
        />
        <el-tag>版本：{{ skill.version }}</el-tag>
      </div>
      <div class="header-actions">
        <el-button type="primary" :icon="UserFilled" @click="openCollaboratorDialog">
          协作者
        </el-button>
        <el-button
          type="primary"
          :icon="Upload"
          @click="handleImport"
          :loading="importing"
        >
          导入技能
        </el-button>
        <el-button
          type="primary"
          :icon="Download"
          @click="handleExport"
          :loading="exporting"
        >
          导出技能
        </el-button>
        <el-button
          type="primary"
          :icon="Upload"
          @click="handleRelease"
          :loading="releasing"
        >
          发布版本
        </el-button>
        <el-button
          :type="skill.is_public ? 'success' : 'info'"
          :icon="skill.is_public ? Hide : View"
          :loading="visibilitySaving"
          @click="handleToggleVisibility"
        >
          {{ skill.is_public ? '设为私有' : '设为公开' }}
        </el-button>
        <!-- GitLab 同步按钮 -->
        <el-dropdown v-if="isGitBound" @command="handleGitSyncCommand">
          <el-button
            :type="gitSyncStatusType === 'success' ? 'success' : 'warning'"
            :icon="Connection"
            :loading="gitSyncing"
          >
            <span>Git 同步</span>
            <el-icon class="el-icon--right"><ArrowDown /></el-icon>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="push">推送到 {{ gitProviderName }}</el-dropdown-item>
              <el-dropdown-item command="pull">从 {{ gitProviderName }} 拉取</el-dropdown-item>
              <el-dropdown-item command="diff" divided>文件差异</el-dropdown-item>
              <el-dropdown-item command="unbind" divided>解除绑定</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-button v-else type="info" :icon="Connection" @click="handleGitBind">
          绑定 Git 仓库
        </el-button>

      </div>
    </div>

    <div class="detail-body" v-loading="loading">
      <div class="left-sidebar">
        <div class="sidebar-info">
          <div class="info-section">
          <div class="info-header">
            <h3>基本信息</h3>
            <el-button
              type="primary"
              link
              size="small"
              @click="toggleEditInfo"
            >
              编辑
            </el-button>
          </div>
          <div class="info-content">
            <div class="info-item">
              <span class="info-label">描述：</span>
              <span class="info-value">{{ skill.description || '未设置' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">版本：</span>
              <span class="info-value">{{ skill.version }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">作者：</span>
              <span class="info-value">{{ skill.author || '未设置' }}</span>
            </div>
            <div class="info-item">
              <span class="info-label">业务模块：</span>
              <SkillMetadataTags class="info-value" :model-value="skill.module" />
            </div>
            <div class="info-item">
              <span class="info-label">适用角色：</span>
              <SkillMetadataTags class="info-value" :model-value="skill.roles" field="roles" />
            </div>
          </div>
          </div>

          <div class="info-section conversation-examples-info">
            <div class="info-header">
              <h3>对话示例</h3>
              <el-button type="primary" link size="small" @click="editConversationExamples">编辑</el-button>
            </div>
            <ol v-if="skill.conversation_examples?.length" class="conversation-examples-list">
              <li v-for="(example, index) in skill.conversation_examples" :key="index">
                <el-tooltip
                  :content="example"
                  placement="right"
                  :show-after="300"
                  :popper-style="{ maxWidth: 'min(420px, calc(100vw - 32px))', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }"
                >
                  <span class="conversation-example-text">{{ example }}</span>
                </el-tooltip>
              </li>
            </ol>
            <div v-else class="info-content">无</div>
          </div>

          <!-- Git 仓库信息 -->
          <div class="info-section" v-if="isGitBound">
            <div class="info-header">
              <h3>Git 仓库</h3>
              <el-button type="primary" link size="small" @click="handleGitEdit">编辑</el-button>
            </div>
            <div class="info-content">
              <div class="info-item">
                <span class="info-label">服务商：</span>
                <span class="info-value">{{ gitProviderName }}</span>
              </div>
              <div class="info-item">
                <span class="info-label">仓库：</span>
                <span class="info-value"><a :href="gitSyncStatus?.git_repo_url" target="_blank" style="color: #409eff;">{{ gitRepoName }}</a></span>
              </div>
              <div class="info-item">
                <span class="info-label">分支：</span>
                <span class="info-value">{{ gitSyncStatus?.git_branch || 'main' }}</span>
              </div>
              <div class="info-item">
                <span class="info-label">同步状态：</span>
                <span class="info-value">{{ gitSyncStatusText }}</span>
              </div>
              <div class="info-item">
                <span class="info-label">同步方向：</span>
                <span class="info-value">{{ gitSyncDirectionText }}</span>
              </div>
              <div class="info-item" v-if="gitSyncStatus?.git_last_synced_at">
                <span class="info-label">同步时间：</span>
                <span class="info-value">{{ formatTime(gitSyncStatus.git_last_synced_at) }}</span>
              </div>
            </div>
          </div>
        </div>

        <div class="file-tree">
        <div class="tree-header">
          <h3>文件列表</h3>
          <div class="tree-actions">
            <el-dropdown trigger="click" placement="bottom-end" @command="handleFileTreeAction">
              <el-button type="primary" link size="small">
                操作
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="create-file" :icon="DocumentAdd">新建文件</el-dropdown-item>
                  <el-dropdown-item command="create-folder" :icon="FolderAdd">新建文件夹</el-dropdown-item>
                  <el-dropdown-item command="upload" :icon="Upload" divided>上传文件</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>
        <input
          ref="fileUploadInputRef"
          class="hidden-file-input"
          type="file"
          multiple
          @change="handleFileUploadChange"
        />
        <el-tree
          :data="fileTree"
          :props="treeProps"
          @node-click="handleNodeClick"
          :default-expanded-keys="expandedKeys"
          node-key="id"
          :current-node-key="currentFile?.id"
          highlight-current
        >
          <template #default="{ node, data }">
            <span class="tree-node" :class="{ 'is-skill-md': data.label === 'SKILL.md' }">
              <span class="node-label">
                <el-icon v-if="data.type === 'folder'"><Folder /></el-icon>
                <el-icon v-else><Document /></el-icon>
                <span :title="node.label">{{ node.label }}</span>
                <el-tooltip
                  v-if="data.label === 'SKILL.md'"
                  content="核心文件，不可重命名或删除"
                  placement="right"
                >
                  <el-icon class="skill-lock" aria-label="受保护文件"><Lock /></el-icon>
                </el-tooltip>
              </span>

              <span class="node-trailing" @click.stop>
                <span v-if="data.type === 'file'" class="node-size">
                  {{ formatSkillFileSize(data) }}
                </span>
                <span v-if="data.label !== 'SKILL.md'" class="node-control node-actions">
                  <el-dropdown
                    trigger="click"
                    placement="bottom-end"
                    @command="(command) => handleNodeAction(command, data)"
                  >
                    <el-button
                      class="node-more-button"
                      text
                      circle
                      :icon="MoreFilled"
                      aria-label="文件操作"
                    />
                    <template #dropdown>
                      <el-dropdown-menu>
                        <template v-if="data.type === 'folder'">
                          <el-dropdown-item command="create-file" :icon="DocumentAdd">新建文件</el-dropdown-item>
                          <el-dropdown-item command="create-folder" :icon="FolderAdd">新建文件夹</el-dropdown-item>
                          <el-dropdown-item command="upload" :icon="Upload" divided>上传文件</el-dropdown-item>
                          <el-dropdown-item command="rename" :icon="Edit" divided>修改文件夹名称</el-dropdown-item>
                          <el-dropdown-item command="delete" :icon="Delete">删除文件夹</el-dropdown-item>
                        </template>
                        <template v-else>
                          <el-dropdown-item command="rename" :icon="Edit">修改文件名称</el-dropdown-item>
                          <el-dropdown-item command="delete" :icon="Delete" divided>删除文件</el-dropdown-item>
                        </template>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                </span>
              </span>
            </span>
          </template>
        </el-tree>
      </div>

      <!-- 发布历史 -->
      <div class="release-history">
        <div class="release-header">
          <h3>发布历史</h3>
        </div>
        <div class="release-list">
          <div
            v-for="release in displayedReleases"
            :key="release.id"
            class="release-item"
          >
            <div class="release-info">
              <div class="release-title-row">
                <div class="release-version">版本：{{ release.version }}</div>
                <el-dropdown
                  trigger="click"
                  placement="bottom-end"
                  :disabled="restoringReleaseId !== null"
                  @click.stop
                  @command="command => handleReleaseAction(command, release)"
                >
                  <el-button
                    class="release-more-button"
                    text
                    circle
                    :icon="MoreFilled"
                    :loading="restoringReleaseId === release.id"
                    aria-label="版本操作"
                  />
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item
                        v-if="release.description"
                        command="notes"
                        :icon="Document"
                      >
                        版本日志
                      </el-dropdown-item>
                      <el-dropdown-item command="restore" :icon="RefreshLeft">恢复此版本</el-dropdown-item>
                      <el-dropdown-item command="copy" :icon="Link">复制链接</el-dropdown-item>
                      <el-dropdown-item command="download" :icon="Download">导出技能</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
              <button
                v-if="release.description"
                type="button"
                class="release-description"
                title="查看完整版本描述"
                @click="showReleaseNotes(release)"
              >
                {{ release.description }}
              </button>
              <div class="release-time">{{ formatTime(release.created_at) }}</div>
            </div>
          </div>
          <el-empty v-if="releases.length === 0" description="暂无发布记录" :image-size="60" />
          <div v-if="hasMoreReleases" class="load-more">
            <el-button link type="primary" size="small" @click="loadMoreReleases">
              查看更多
            </el-button>
          </div>
        </div>
      </div>
      </div>

      <div class="content-area">
        <div v-if="!currentFile" class="empty-file-placeholder">
          <el-empty description="未选择文件" :image-size="80" />
        </div>
        <template v-else>
          <div class="content-header">
            <span class="current-file">
              <el-icon v-if="currentFile.type === 'folder'"><Folder /></el-icon>
              <el-icon v-else><Document /></el-icon>
              {{ currentFile.label }}
            </span>
            <div class="content-actions" v-if="currentFile.type === 'file' && !currentFile.is_binary">
              <template v-if="isEditing">
                <el-button
                  type="primary"
                  size="small"
                  @click="handleSave"
                  :loading="saving"
                >
                  保存
                </el-button>
                <el-button
                  size="small"
                  @click="handleCancel"
                >
                  取消
                </el-button>
              </template>
              <el-button
                v-else
                type="primary"
                link
                size="small"
                @click="toggleEdit"
              >
                编辑
              </el-button>
            </div>
          </div>

          <div v-if="currentFile.type === 'folder'" class="folder-view">
            <el-icon class="folder-icon"><Folder /></el-icon>
          </div>

          <div v-else-if="currentFile.is_binary" class="folder-view">
            <el-empty description="此文件不支持在线预览" :image-size="80" />
          </div>

          <div v-else-if="!isEditing" class="preview-mode">
            <MdPreview
              v-if="isMarkdownFile"
              class="skill-markdown-preview"
              :modelValue="currentFile?.content || ''"
            />
            <Codemirror
              v-else
              :modelValue="currentFile?.content || ''"
              :style="{ height: '100%', fontSize: '14px' }"
              :extensions="codeExtensions"
              :editable="false"
              :indent-with-tab="true"
              :tab-size="2"
            />
          </div>

          <div v-else class="edit-mode">
            <MarkdownEditor media-tools
              v-if="isMarkdownFile"
              v-model="editContent"
              class="skill-markdown-preview"
              language="zh-CN"
              showCodeRowNumber
              :onUploadImg="onUploadImg"
            />
            <Codemirror
              v-else
              v-model="editContent"
              :style="{ height: '100%', fontSize: '14px' }"
              :extensions="codeExtensions"
              :autofocus="true"
              :indent-with-tab="true"
              :tab-size="2"
            />
          </div>
        </template>
      </div>
    </div>

    <!-- 发布版本对话框 -->
    <el-dialog
      v-model="releaseDialog"
      title="发布版本"
      width="min(680px, 92vw)"
      :close-on-click-modal="false"
    >
      <el-form :model="releaseForm" label-width="80px">
        <el-form-item label="版本号">
          <el-input
            v-model="releaseForm.version"
            placeholder="请输入版本号，如 1.0.0"
          />
        </el-form-item>
        <el-form-item label="版本描述">
          <el-input
            v-model="releaseForm.description"
            type="textarea"
            :rows="8"
            maxlength="1000"
            show-word-limit
            placeholder="请输入本次更新内容"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="releaseDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmRelease" :loading="releasing">
          确定
        </el-button>
      </template>
    </el-dialog>

    <!-- 导入技能对话框 -->
    <el-dialog
      v-model="importDialogVisible"
      title="导入技能"
      width="500px"
      :close-on-click-modal="false"
      @closed="resetImportDialog"
    >
      <el-upload
        ref="importUploadRef"
        class="upload-demo"
        drag
        :auto-upload="false"
        :limit="1"
        :on-change="handleImportFileChange"
        :on-exceed="handleImportFileExceed"
        accept=".md,.zip"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">
          将文件拖到此处，或<em>点击上传</em>
        </div>
        <template #tip>
          <div class="el-upload__tip">
            只能上传 SKILL.md 文件或包含 SKILL.md 的 zip 压缩包
            <br />导入时先清空原工作区，再写入新文件，技能相关信息保持不变
          </div>
        </template>
      </el-upload>
      <template #footer>
        <el-button @click="importDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleConfirmImport" :loading="importing">
          确定导入
        </el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="releaseNotesDialogVisible"
      title="版本描述"
      width="min(520px, 92vw)"
      @closed="activeReleaseNotes = null"
    >
      <template v-if="activeReleaseNotes">
        <div class="release-notes-meta">
          <strong>版本 {{ activeReleaseNotes.version }}</strong>
          <span>{{ formatTime(activeReleaseNotes.created_at) }}</span>
        </div>
        <div class="release-notes-content">{{ activeReleaseNotes.description }}</div>
      </template>
      <template #footer>
        <el-button type="primary" @click="releaseNotesDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 新增文件/目录对话框 -->
    <el-dialog
      v-model="addItemDialog"
      title="新建文件/目录"
      width="400px"
    >
      <el-form :model="addItemForm" label-width="80px">
        <el-form-item label="类型">
          <el-radio-group v-model="addItemForm.type">
            <el-radio value="file">文件</el-radio>
            <el-radio value="folder">文件夹</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="名称">
          <el-input
            v-model="addItemForm.name"
            :placeholder="addItemForm.type === 'file' ? '请输入文件名（自动添加.md后缀）' : '请输入文件夹名'"
            @keyup.enter="confirmAddItem"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addItemDialog = false">取消</el-button>
        <el-button type="primary" @click="confirmAddItem">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="collaboratorDialogVisible"
      title="协作者管理"
      width="560px"
      :close-on-click-modal="false"
    >
      <el-form v-if="isOwner" :model="collaboratorForm" label-width="80px" @submit.prevent>
        <el-form-item label="协作者">
          <el-select
            v-model="collaboratorForm.user_id"
            clearable
            filterable
            remote
            :remote-method="searchCollaboratorUsers"
            :loading="collaboratorUserSearchLoading"
            placeholder="请输入姓名或用户名搜索"
            style="width: 100%"
          >
            <el-option
              v-for="user in availableCollaboratorUsers"
              :key="user.id"
              :label="collaboratorUserLabel(user)"
              :value="user.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            :icon="Plus"
            :loading="addingCollaborator"
            @click="handleAddCollaborator"
          >
            添加协作者
          </el-button>
        </el-form-item>
      </el-form>

      <el-table :data="collaborators" v-loading="collaboratorsLoading" size="small">
        <el-table-column label="姓名" width="211" align="left">
          <template #default="{ row }">
            {{ row.first_name || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="username" label="用户名" width="211" align="left" />
        <el-table-column label="操作" width="106" align="left">
          <template #default="{ row }">
            <el-tooltip v-if="isOwner" content="移除协作者" placement="top">
              <el-button
                type="danger"
                :icon="Delete"
                link
                aria-label="移除协作者"
                @click="handleRemoveCollaborator(row)"
              />
            </el-tooltip>
            <span v-else>无</span>
          </template>
        </el-table-column>
      </el-table>
      <el-empty
        v-if="!collaboratorsLoading && collaborators.length === 0"
        description="暂无协作者"
        :image-size="64"
      />
    </el-dialog>

    <!-- Git 差异确认对话框 -->
    <el-dialog v-model="diffDialogVisible" :title="diffDialogTitle" width="900px">
      <div style="display: flex; gap: 16px; max-height: 350px; overflow: hidden;">
        <div style="flex: 1; overflow-y: auto;">
          <h4 style="margin: 0 0 8px; color: #303133;">本地</h4>
          <el-table :data="diffLocalChanges" max-height="280" size="small" style="width: 100%">
            <el-table-column prop="path" label="文件路径">
              <template #default="{ row }">
                <span :style="{ color: diffRemoteChanges.some(r => r.path === row.path) ? '#e6a23c' : '#303133' }">
                  {{ row.path }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="70">
              <template #default="{ row }">
                <el-tag :type="row.status === 'added' ? 'success' : 'warning'" size="small">
                  {{ row.status === 'added' ? '新增' : '修改' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div style="flex: 1; overflow-y: auto;">
          <h4 style="margin: 0 0 8px; color: #303133;">Git 仓库</h4>
          <el-table :data="diffRemoteChanges" max-height="280" size="small" style="width: 100%">
            <el-table-column prop="path" label="文件路径">
              <template #default="{ row }">
                <span :style="{ color: diffLocalChanges.some(r => r.path === row.path) ? '#e6a23c' : '#303133' }">
                  {{ row.path }}
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="status" label="状态" width="70">
              <template #default="{ row }">
                <el-tag :type="row.status === 'added' ? 'success' : 'warning'" size="small">
                  {{ row.status === 'added' ? '新增' : '修改' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>
      <template #footer>
        <el-button @click="diffDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- Git 绑定对话框 -->
    <el-dialog
      v-model="gitBindDialogVisible"
      :title="gitBindMode === 'edit' ? '修改 Git 仓库配置' : '绑定 Git 仓库'"
      width="min(760px, calc(100vw - 32px))"
      :close-on-click-modal="false"
      @closed="handleGitDialogClosed"
    >
      <el-form
        ref="gitBindFormRef"
        :model="gitBindForm"
        :rules="gitBindRules"
        label-width="80px"
        autocomplete="off"
      >
        <el-form-item label="服务商">
          <el-radio-group v-model="gitBindForm.provider">
            <el-radio-button value="gitlab">GitLab</el-radio-button>
            <el-radio-button value="github">GitHub</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="仓库地址" prop="repo_url">
          <el-input
            v-model="gitBindForm.repo_url"
            :placeholder="gitBindForm.provider === 'github' ? 'https://github.com/user/repo.git' : 'https://gitlab.example.com/user/repo.git'"
            autocomplete="off"
          />
        </el-form-item>
        <el-form-item label="访问令牌">
          <el-input
            v-model="gitBindForm.access_token"
            placeholder="公开仓库可留空，私有仓库需填写"
            show-password
            autocomplete="new-password"
          />
        </el-form-item>
        <el-form-item label="分支">
          <el-radio-group v-model="gitBindForm.branch" style="margin-bottom: 8px;">
            <el-radio value="main">main</el-radio>
            <el-radio value="master">master</el-radio>
            <el-radio value="custom">其他</el-radio>
          </el-radio-group>
          <el-input
            v-if="gitBindForm.branch === 'custom'"
            v-model="gitBindForm.branch_custom"
            placeholder="请输入分支名"
          />
        </el-form-item>
        <el-form-item>
          <el-button @click="handleTestGitConnection" :loading="gitTesting" :type="gitTestResult?.success ? 'success' : 'primary'">
            {{ gitTestResult?.success ? '连接成功' : '测试连接' }}
          </el-button>
          <span v-if="gitTestResult && !gitTestResult.success" style="margin-left: 8px; color: #f56c6c; font-size: 13px;">
            {{ gitTestResult.message }}
          </span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="gitBindDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleConfirmGitBind" :loading="gitSyncing">
          {{ gitBindMode === 'edit' ? '保存' : '绑定' }}
        </el-button>
      </template>
    </el-dialog>

    <ResourceEditDialog
      v-model="examplesDialogVisible"
      title="编辑对话示例"
      :saving="savingExamples"
      @cancel="examplesDialogVisible = false"
      @save="saveConversationExamples"
    >
      <p class="examples-editor-hint">在技能市场展示，点击后自动安装技能并填入对话输入框。最多配置 10 条。</p>
      <div v-for="(_, index) in examplesForm" :key="index" class="example-editor-row">
        <el-input
          v-model="examplesForm[index]"
          type="textarea"
          :rows="2"
          :maxlength="1000"
          show-word-limit
          :aria-label="`对话示例 ${index + 1}`"
          :placeholder="index === 0 ? '例如：xxx品销量怎么样？' : '例如：帮我查看本周任务'"
          :disabled="savingExamples"
        />
        <el-button :icon="Delete" :aria-label="`删除对话示例 ${index + 1}`" :disabled="savingExamples" @click="examplesForm.splice(index, 1)" />
      </div>
      <el-button :icon="Plus" :disabled="savingExamples || examplesForm.length >= 10" @click="examplesForm.push('')">添加示例</el-button>
    </ResourceEditDialog>

    <ResourceEditDialog
      v-model="isEditingInfo"
      title="编辑技能基本信息"
      :saving="savingInfo"
      @cancel="handleCancelInfo"
      @save="handleSaveInfo"
    >
      <el-form :disabled="savingInfo" :model="infoForm" label-position="top">
        <el-form-item label="描述">
          <el-input
            v-model="infoForm.description"
            type="textarea"
            :rows="5"
            placeholder="请输入描述"
          />
        </el-form-item>
        <el-form-item label="版本">
          <el-input v-model="infoForm.version" placeholder="请输入版本号" />
        </el-form-item>
        <el-form-item label="作者">
          <el-input v-model="infoForm.author" placeholder="请输入作者" disabled />
        </el-form-item>
        <el-form-item label="业务模块">
          <SkillMetadataTags v-model="infoForm.module" editable :disabled="savingInfo" />
        </el-form-item>
        <el-form-item label="适用角色">
          <SkillMetadataTags v-model="infoForm.roles" field="roles" editable :disabled="savingInfo" />
        </el-form-item>
      </el-form>
    </ResourceEditDialog>
  </div>
</template>

<script setup>
import MarkdownEditor from '@/components/MarkdownEditor.vue'
import ResourceEditDialog from '@/components/ResourceEditDialog.vue'
import SkillMetadataTags from '@/components/SkillMetadataTags.vue'
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { skillsApi } from '@/api/skills'
import { assetsApi } from '@/api/assets'
import { adminApi } from '@/api/admin'
import { gitApi } from '@/api/git'
import { useAuthStore } from '@/stores/auth'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowDown, Plus, Edit, Delete, Folder, Document, DocumentAdd, FolderAdd, Download, CopyDocument, Upload, UploadFilled, Link, Lock, Connection, UserFilled, RefreshLeft, MoreFilled, View, Hide } from '@element-plus/icons-vue'
import { MdPreview } from 'md-editor-v3'
import 'md-editor-v3/lib/style.css'
import { Codemirror } from 'vue-codemirror'
import { javascript } from '@codemirror/lang-javascript'
import { python } from '@codemirror/lang-python'
import { html } from '@codemirror/lang-html'
import { css } from '@codemirror/lang-css'
import { json } from '@codemirror/lang-json'
import { vue } from '@codemirror/lang-vue'
import { oneDark } from '@codemirror/theme-one-dark'
import { formatSkillFileSize, syncSkillFilePaths } from '@/utils/skill-files'
import { uploadImage } from '@/api/upload'
import { formatBeijingDateTime } from '@/utils/date-time'
import JSZip from 'jszip'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()

const loading = ref(false)
const saving = ref(false)
const exporting = ref(false)
const importing = ref(false)
const importDialogVisible = ref(false)
const importUploadRef = ref(null)
const selectedImportFile = ref(null)
const releasing = ref(false)
const visibilitySaving = ref(false)
const isEditing = ref(false)
const isEditingInfo = ref(false)
const savingInfo = ref(false)

// GitLab 同步状态
const gitSyncing = ref(false)
const gitSyncStatus = ref(null)
const gitBindDialogVisible = ref(false)
const gitBindMode = ref('bind') // 'bind' | 'edit'
const gitBindForm = ref({ provider: 'gitlab', repo_url: '', branch: 'main', branch_custom: '', access_token: '' })
const gitBindFormRef = ref(null)
const gitTestResult = ref(null)
const gitTesting = ref(false)
const gitBindRules = {
  repo_url: [{ required: true, message: '请输入仓库地址', trigger: 'blur' }]
}
const isEditingName = ref(false)
const editingName = ref('')
const nameInputRef = ref(null)
const skill = ref({})
const examplesDialogVisible = ref(false)
const savingExamples = ref(false)
const examplesForm = ref([])
const editConversationExamples = () => {
  examplesForm.value = skill.value.conversation_examples?.length ? [...skill.value.conversation_examples] : ['']
  examplesDialogVisible.value = true
}
const saveConversationExamples = async () => {
  if (savingExamples.value) return
  savingExamples.value = true
  try {
    const conversation_examples = examplesForm.value.map(text => text.trim()).filter(Boolean)
    const updated = await skillsApi.update(route.params.id, { conversation_examples })
    skill.value.conversation_examples = updated.conversation_examples || []
    examplesDialogVisible.value = false
    ElMessage.success('对话示例已保存')
  } catch {
    ElMessage.error('对话示例保存失败，请重试')
  } finally {
    savingExamples.value = false
  }
}
const editContent = ref('')
const originalContent = ref('') // 保存编辑前的原始内容
const currentFile = ref(null)
const selectedNode = ref(null)
const releases = ref([])
const restoringReleaseId = ref(null)
const releaseNotesDialogVisible = ref(false)
const activeReleaseNotes = ref(null)
const releaseDialog = ref(false)
const releaseForm = ref({
  version: '',
  description: '',
})
const releaseDisplayCount = ref(5) // 当前显示的发布记录数量
const releasePageSize = 5 // 每次加载的数量

// 计算属性：当前显示的发布记录
const displayedReleases = computed(() => {
  return releases.value.slice(0, releaseDisplayCount.value)
})

// 计算属性：是否还有更多发布记录
const hasMoreReleases = computed(() => {
  return releases.value.length > releaseDisplayCount.value
})

// 基本信息表单
const infoForm = ref({
  version: '',
  author: '',
  description: '',
  module: '',
  roles: ''
})
const originalInfo = ref({}) // 保存编辑前的原始信息

// Markdown 编辑器工具栏配置
const onUploadImg = async (files, callback) => {
  const urls = []
  for (const file of files) {
    try {
      const res = await uploadImage(file)
      urls.push(res.url)
    } catch (e) {
      ElMessage.error('图片上传失败')
    }
  }
  callback(urls)
}

// 判断是否为 Markdown 文件
const isMarkdownFile = computed(() => {
  if (!currentFile.value) return false
  const ext = currentFile.value.label.split('.').pop().toLowerCase()
  return ['md', 'markdown'].includes(ext)
})

// 获取代码编辑器的语言扩展
const codeExtensions = computed(() => {
  if (!currentFile.value) return [oneDark]

  const ext = currentFile.value.label.split('.').pop().toLowerCase()
  const langMap = {
    'js': javascript({ jsx: false }),
    'jsx': javascript({ jsx: true }),
    'ts': javascript({ typescript: true }),
    'tsx': javascript({ jsx: true, typescript: true }),
    'py': python(),
    'html': html(),
    'css': css(),
    'scss': css(),
    'less': css(),
    'json': json(),
    'vue': vue(),
  }

  const lang = langMap[ext]
  return lang ? [lang, oneDark] : [oneDark]
})

// 新增项目对话框
const addItemDialog = ref(false)
const addItemForm = ref({
  type: 'file',
  name: ''
})
const addItemParent = ref(null)
const fileUploadInputRef = ref(null)
const pendingUploadParent = ref(null)
const MAX_SKILL_FILE_BYTES = 1024 * 1024
const MAX_SKILL_UPLOAD_FILES = 20

const collaboratorDialogVisible = ref(false)
const collaborators = ref([])
const collaboratorsLoading = ref(false)
const addingCollaborator = ref(false)
const collaboratorUsers = ref([])
const collaboratorUserSearchLoading = ref(false)
const collaboratorForm = ref({ user_id: null })

const currentUserId = computed(() => Number(authStore.user?.id ?? authStore.user?.user_id))
const isOwner = computed(() => Number(skill.value.user_id) === currentUserId.value)
const availableCollaboratorUsers = computed(() => {
  const unavailableIds = new Set([
    Number(skill.value.user_id),
    ...collaborators.value.map(item => Number(item.user_id))
  ])
  return collaboratorUsers.value.filter(user => !unavailableIds.has(Number(user.id)))
})

const expandedKeys = ref([])

const treeProps = {
  children: 'children',
  label: 'label'
}

const fileTree = ref([
  {
    id: 1,
    label: 'SKILL.md',
    type: 'file',
    path: 'SKILL.md',
    content: ''
  }
])

let nextId = 2

// 查找目标节点到根路径上所有祖先文件夹的 ID
const findAncestorIds = (nodes, targetId, ancestors = []) => {
  for (const node of nodes) {
    if (node.id === targetId) return ancestors
    if (node.children?.length) {
      const result = findAncestorIds(node.children, targetId, [...ancestors, node.id])
      if (result) return result
    }
  }
  return null
}

const fetchSkillDetail = async () => {
  loading.value = true
  try {
    const data = await skillsApi.getDetail(route.params.id)
    skill.value = data

    // 解析文件树
    let hasValidFiles = false
    if (data.files) {
      try {
        const parsedFiles = JSON.parse(data.files)
        if (parsedFiles.tree && Array.isArray(parsedFiles.tree)) {
          const sortTree = (nodes) => {
            nodes.sort((a, b) => {
              if (a.type !== b.type) return a.type === 'folder' ? -1 : 1
              return a.label.localeCompare(b.label)
            })
            nodes.filter(n => n.type === 'folder').forEach(n => {
              if (n.children) sortTree(n.children)
            })
          }
          sortTree(parsedFiles.tree)
          fileTree.value = parsedFiles.tree
          hasValidFiles = true
          // 找到最大ID
          const findMaxId = (nodes) => {
            let maxId = 0
            nodes.forEach(node => {
              if (node.id > maxId) maxId = node.id
              if (node.children) {
                const childMaxId = findMaxId(node.children)
                if (childMaxId > maxId) maxId = childMaxId
              }
            })
            return maxId
          }
          nextId = findMaxId(fileTree.value) + 1
        }
      } catch (e) {
        console.error('解析文件树失败:', e)
      }
    }

    // 如果没有有效的文件树，初始化默认文件
    if (!hasValidFiles) {
      fileTree.value = [
        {
          id: 1,
          label: 'SKILL.md',
          type: 'file',
          path: 'SKILL.md',
          content: data.content || '# 技能说明\n\n请在此编写技能说明文档。'
        }
      ]
      nextId = 2

      // 保存初始文件树
      try {
        const filesData = JSON.stringify({
          tree: fileTree.value
        })
        await skillsApi.update(route.params.id, {
          files: filesData
        })
        syncSkillFilePaths(fileTree.value)
        skill.value.files = JSON.stringify({ tree: fileTree.value })
      } catch (e) {
        console.error('保存初始文件树失败:', e)
      }
    }

    // 优先展示根目录 README.md，没有则 SKILL.md，再没有则第一个文件（BFS）
    const findFileBFS = (nodes, matchName = null) => {
      const queue = [...nodes]
      while (queue.length > 0) {
        const node = queue.shift()
        if (node.type === 'file') {
          if (matchName) {
            if (node.label.toLowerCase() === matchName.toLowerCase()) {
              return node
            }
          } else {
            return node
          }
        }
        if (node.children) {
          queue.push(...node.children)
        }
      }
      return null
    }

    const defaultFile = findFileBFS(fileTree.value, 'README.md')
      || findFileBFS(fileTree.value, 'SKILL.md')
      || findFileBFS(fileTree.value)
    if (defaultFile) {
      currentFile.value = defaultFile
      selectedNode.value = defaultFile
      editContent.value = defaultFile.content || ''
      const ancestorIds = findAncestorIds(fileTree.value, defaultFile.id)
      if (ancestorIds) expandedKeys.value = ancestorIds
    }
  } catch (error) {
    ElMessage.error('获取详情失败')
  } finally {
    loading.value = false
  }
}

const handleBack = () => {
  router.back()
}

const toggleEdit = () => {
  isEditing.value = !isEditing.value
  if (isEditing.value && currentFile.value) {
    originalContent.value = currentFile.value.content || ''
    editContent.value = originalContent.value
  }
}

const handleCancel = () => {
  editContent.value = originalContent.value
  isEditing.value = false
}

const handleSave = async () => {
  saving.value = true
  try {
    // 保存当前文件内容
    if (currentFile.value && currentFile.value.type === 'file') {
      currentFile.value.content = editContent.value
    }

    // 序列化文件树
    const filesData = JSON.stringify({
      tree: fileTree.value
    })

    await skillsApi.update(route.params.id, {
      files: filesData
    })

    syncSkillFilePaths(fileTree.value)
    skill.value.files = JSON.stringify({ tree: fileTree.value })
    isEditing.value = false
    ElMessage.success('保存成功')
  } catch (error) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const handleNodeClick = (data) => {
  // 设置选中的节点（用于显示操作按钮）
  selectedNode.value = data

  // 如果是文件，则加载文件内容
  if (data.type === 'file') {
    // 如果正在编辑，先保存当前文件内容
    if (isEditing.value && currentFile.value && currentFile.value.type === 'file') {
      currentFile.value.content = editContent.value
    }

    // 切换到新文件
    currentFile.value = data
    editContent.value = data.content || ''

    // 退出编辑模式
    isEditing.value = false
  } else if (data.type === 'folder') {
    // 如果是文件夹，也更新 currentFile 以显示文件夹信息
    // 如果正在编辑文件，先保存
    if (isEditing.value && currentFile.value && currentFile.value.type === 'file') {
      currentFile.value.content = editContent.value
    }

    currentFile.value = data
    editContent.value = ''
    isEditing.value = false
  }
}

const handleAddItem = async (command) => {
  const itemType = command === 'folder' ? '文件夹' : '文件'
  const defaultName = command === 'folder' ? '新建文件夹' : '新建文件.md'

  try {
    const { value: name } = await ElMessageBox.prompt(`请输入${itemType}名称`, `新建${itemType}`, {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputValue: defaultName,
      inputPattern: /\S+/,
      inputErrorMessage: '名称不能为空'
    })

    const newItem = {
      id: nextId++,
      label: name,
      type: command,
      path: name,
      content: command === 'file' ? '' : undefined,
      children: command === 'folder' ? [] : undefined
    }

    fileTree.value.push(newItem)

    // 立即保存到数据库
    try {
      const filesData = JSON.stringify({
        tree: fileTree.value
      })

      await skillsApi.update(route.params.id, {
        files: filesData
      })

      syncSkillFilePaths(fileTree.value)
      skill.value.files = JSON.stringify({ tree: fileTree.value })
      ElMessage.success(`${itemType}创建成功`)

      // 如果是文件，自动选中并进入编辑模式
      if (command === 'file') {
        currentFile.value = newItem
        editContent.value = ''
        isEditing.value = true
      }
    } catch (error) {
      // 保存失败，回滚
      fileTree.value.pop()
      ElMessage.error(`${itemType}创建失败，请重试`)
    }
  } catch (error) {
    // 用户取消操作
  }
}

const handleAddItemToRoot = (type = 'file') => {
  addItemParent.value = null
  addItemForm.value = {
    type,
    name: ''
  }
  addItemDialog.value = true
}

const handleFileTreeAction = (command) => {
  if (command === 'create-file') return handleAddItemToRoot('file')
  if (command === 'create-folder') return handleAddItemToRoot('folder')
  if (command === 'upload') return handleUploadFiles()
}

const handleAddItemToFolder = (folder, type = 'file') => {
  addItemParent.value = folder
  addItemForm.value = {
    type,
    name: ''
  }
  addItemDialog.value = true
}

const handleNodeAction = (command, item) => {
  if (command === 'create-file') return handleAddItemToFolder(item, 'file')
  if (command === 'create-folder') return handleAddItemToFolder(item, 'folder')
  if (command === 'upload') return handleUploadFiles(item)
  if (command === 'rename') return handleRenameItem(item)
  if (command === 'delete') return handleDeleteItem(item)
}

const handleUploadFiles = (folder = null) => {
  pendingUploadParent.value = folder
  if (fileUploadInputRef.value) {
    fileUploadInputRef.value.value = ''
    fileUploadInputRef.value.click()
  }
}

const readUtf8File = async (file) => {
  if (file.size > MAX_SKILL_FILE_BYTES) {
    throw new Error(`${file.name} 超过 1 MiB`)
  }
  const buffer = await file.arrayBuffer()
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(buffer)
  } catch {
    throw new Error(`${file.name} 不是 UTF-8 文本文件`)
  }
}

const handleFileUploadChange = async (event) => {
  const selectedFiles = Array.from(event.target.files || [])
  if (!selectedFiles.length) return
  if (selectedFiles.length > MAX_SKILL_UPLOAD_FILES) {
    ElMessage.warning(`一次最多上传 ${MAX_SKILL_UPLOAD_FILES} 个文件`)
    return
  }

  const parent = pendingUploadParent.value
  const targetList = parent ? (parent.children || (parent.children = [])) : fileTree.value

  try {
    const candidates = []
    for (const file of selectedFiles) {
      if (!file.name || ['.', '..'].includes(file.name) || file.name.includes('/') || file.name.includes('\\')) {
        throw new Error('文件名不合法')
      }
      const existing = targetList.find(item => item.label === file.name)
      if (existing?.type === 'folder') {
        throw new Error(`${file.name} 与现有文件夹重名`)
      }
      candidates.push({ file, existing, content: await readUtf8File(file) })
    }

    const overwriteNames = candidates.filter(item => item.existing).map(item => item.file.name)
    if (overwriteNames.length) {
      await ElMessageBox.confirm(
        `以下文件已存在：${overwriteNames.join('、')}。是否覆盖？`,
        '覆盖文件',
        {
          confirmButtonText: '确定',
          cancelButtonText: '取消',
          type: 'warning'
        }
      )
    }

    const previousTree = JSON.parse(JSON.stringify(fileTree.value))
    let lastUploaded = null
    try {
      for (const item of candidates) {
        if (item.existing) {
          item.existing.content = item.content
          lastUploaded = item.existing
          continue
        }
        const uploaded = {
          id: nextId++,
          label: item.file.name,
          type: 'file',
          path: parent ? `${parent.path}/${item.file.name}` : item.file.name,
          content: item.content
        }
        targetList.push(uploaded)
        lastUploaded = uploaded
      }
      await saveFileTree()
    } catch (error) {
      fileTree.value = previousTree
      throw error
    }

    if (parent && !expandedKeys.value.includes(parent.id)) {
      expandedKeys.value = [...expandedKeys.value, parent.id]
    }
    if (lastUploaded) {
      currentFile.value = lastUploaded
      selectedNode.value = lastUploaded
      editContent.value = lastUploaded.content
      originalContent.value = lastUploaded.content
      isEditing.value = false
    }
    ElMessage.success(`已上传 ${candidates.length} 个文件`)
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error?.message || '文件上传失败')
    }
  } finally {
    pendingUploadParent.value = null
    event.target.value = ''
  }
}

const fetchCollaborators = async () => {
  collaboratorsLoading.value = true
  try {
    const collaboratorRows = await skillsApi.getCollaborators(route.params.id)
    const userIds = collaboratorRows.map(item => item.user_id)
    let userMap = new Map()

    if (userIds.length) {
      try {
        const response = await adminApi.getUsers({
          ids: userIds.join(','),
          limit: userIds.length
        })
        const users = response.items || response
        userMap = new Map(users.map(user => [Number(user.id), user]))
      } catch {
        userMap = new Map()
      }
    }

    collaborators.value = collaboratorRows.map(item => ({
      ...item,
      first_name: (userMap.get(Number(item.user_id))?.first_name || '').trim()
    }))
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '获取协作者失败')
  } finally {
    collaboratorsLoading.value = false
  }
}

const loadCollaboratorUsers = async () => {
  collaboratorUserSearchLoading.value = true
  try {
    const response = await adminApi.getUsers({ limit: 100 })
    collaboratorUsers.value = response.items || response
  } catch {
    collaboratorUsers.value = []
  } finally {
    collaboratorUserSearchLoading.value = false
  }
}

const searchCollaboratorUsers = async (query) => {
  if (!query) {
    await loadCollaboratorUsers()
    return
  }
  collaboratorUserSearchLoading.value = true
  try {
    const response = await adminApi.getUsers({ search: query, limit: 50 })
    collaboratorUsers.value = response.items || response
  } catch {
    collaboratorUsers.value = []
  } finally {
    collaboratorUserSearchLoading.value = false
  }
}

const collaboratorUserLabel = (user) => {
  const name = (user.first_name || '').trim()
  return name ? `${name} (${user.username})` : user.username
}

const openCollaboratorDialog = () => {
  collaboratorForm.value = { user_id: null }
  collaboratorDialogVisible.value = true
  fetchCollaborators()
  if (isOwner.value) loadCollaboratorUsers()
}

const handleAddCollaborator = async () => {
  const userId = Number(collaboratorForm.value.user_id)
  const selectedUser = collaboratorUsers.value.find(user => Number(user.id) === userId)
  if (!Number.isInteger(userId) || userId <= 0 || !selectedUser?.username) {
    ElMessage.warning('请选择协作者')
    return
  }

  addingCollaborator.value = true
  try {
    await skillsApi.addCollaborator(route.params.id, {
      user_id: userId,
      username: selectedUser.username
    })
    collaboratorForm.value = { user_id: null }
    await fetchCollaborators()
    ElMessage.success('协作者已添加')
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '添加协作者失败')
  } finally {
    addingCollaborator.value = false
  }
}

const handleRemoveCollaborator = async (collaborator) => {
  try {
    await ElMessageBox.confirm(
      `确定移除协作者“${collaborator.username}”吗？`,
      '移除协作者',
      {
        confirmButtonText: '移除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
    await skillsApi.removeCollaborator(route.params.id, collaborator.user_id)
    ElMessage.success('协作者已移除')
    if (!isOwner.value && Number(collaborator.user_id) === currentUserId.value) {
      collaboratorDialogVisible.value = false
      router.push('/admin/skills')
      return
    }
    await fetchCollaborators()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error?.response?.data?.detail || '移除协作者失败')
    }
  }
}

const confirmAddItem = async () => {
  if (!addItemForm.value.name.trim()) {
    ElMessage.warning('请输入名称')
    return
  }

  const itemType = addItemForm.value.type === 'folder' ? '文件夹' : '文件'
  const defaultExt = addItemForm.value.type === 'file' && !addItemForm.value.name.includes('.') ? '.md' : ''
  const finalName = addItemForm.value.name.trim() + defaultExt

  // 检查是否重名
  const targetList = addItemParent.value ? addItemParent.value.children : fileTree.value
  if (targetList && targetList.some(item => item.label === finalName)) {
    ElMessage.warning(`${itemType}名称已存在，请使用其他名称`)
    return
  }

  try {
    const newItem = {
      id: nextId++,
      label: finalName,
      type: addItemForm.value.type,
      path: addItemParent.value ? `${addItemParent.value.path}/${finalName}` : finalName,
      content: addItemForm.value.type === 'file' ? '' : undefined,
      children: addItemForm.value.type === 'folder' ? [] : undefined
    }

    // 如果有父节点，添加到父节点的 children；否则添加到根目录
    if (addItemParent.value) {
      if (!addItemParent.value.children) {
        addItemParent.value.children = []
      }
      addItemParent.value.children.push(newItem)
    } else {
      fileTree.value.push(newItem)
    }

    await saveFileTree()
    ElMessage.success(`${itemType}创建成功`)

    if (addItemForm.value.type === 'file') {
      currentFile.value = newItem
      editContent.value = ''
      isEditing.value = true
    }

    addItemDialog.value = false
  } catch (error) {
    ElMessage.error('创建失败')
  }
}

const handleRenameItem = async (item) => {
  try {
    const { value: newName } = await ElMessageBox.prompt('请输入新名称', '重命名', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputValue: item.label,
      inputPattern: /\S+/,
      inputErrorMessage: '名称不能为空'
    })

    // 如果名称没有改变，直接返回
    if (newName === item.label) {
      return
    }

    // 查找同级目录，检查是否重名
    const findParentAndSiblings = (nodes, targetId, parent = null) => {
      for (const node of nodes) {
        if (node.id === targetId) {
          return { parent, siblings: parent ? parent.children : fileTree.value }
        }
        if (node.children) {
          const result = findParentAndSiblings(node.children, targetId, node)
          if (result) return result
        }
      }
      return null
    }

    const result = findParentAndSiblings(fileTree.value, item.id)
    if (result && result.siblings) {
      const hasDuplicate = result.siblings.some(
        sibling => sibling.id !== item.id && sibling.label === newName
      )
      if (hasDuplicate) {
        ElMessage.warning('名称已存在，请使用其他名称')
        return
      }
    }

    item.label = newName
    await saveFileTree()
    ElMessage.success('重命名成功')
  } catch (error) {
    // 用户取消操作
  }
}

const handleDeleteItem = async (item) => {
  try {
    await ElMessageBox.confirm(
      `确定要删除"${item.label}"吗？此操作不可恢复。`,
      '删除确认',
      {
        confirmButtonText: '确定',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )

    // 递归删除节点
    const deleteNode = (nodes, targetId) => {
      for (let i = 0; i < nodes.length; i++) {
        if (nodes[i].id === targetId) {
          nodes.splice(i, 1)
          return true
        }
        if (nodes[i].children) {
          if (deleteNode(nodes[i].children, targetId)) {
            return true
          }
        }
      }
      return false
    }

    deleteNode(fileTree.value, item.id)

    // 如果删除的是当前文件，重定位到SKILL.md
    if (currentFile.value?.id === item.id) {
      // 查找SKILL.md文件
      const findSkillMd = (nodes) => {
        for (const node of nodes) {
          if (node.label === 'SKILL.md' && node.type === 'file') {
            return node
          }
          if (node.children) {
            const found = findSkillMd(node.children)
            if (found) return found
          }
        }
        return null
      }

      const skillMdFile = findSkillMd(fileTree.value)
      if (skillMdFile) {
        currentFile.value = skillMdFile
        selectedNode.value = skillMdFile
        editContent.value = skillMdFile.content || ''
        isEditing.value = false
      } else {
        currentFile.value = null
        editContent.value = ''
      }
    }

    // 如果删除的是选中的节点，重定位到SKILL.md
    if (selectedNode.value?.id === item.id) {
      const findSkillMd = (nodes) => {
        for (const node of nodes) {
          if (node.label === 'SKILL.md' && node.type === 'file') {
            return node
          }
          if (node.children) {
            const found = findSkillMd(node.children)
            if (found) return found
          }
        }
        return null
      }

      const skillMdFile = findSkillMd(fileTree.value)
      selectedNode.value = skillMdFile || null
    }

    await saveFileTree()
    ElMessage.success('删除成功')
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

const saveFileTree = async () => {
  try {
    const filesData = JSON.stringify({
      tree: fileTree.value
    })

    await skillsApi.update(route.params.id, {
      files: filesData
    })

    syncSkillFilePaths(fileTree.value)
    skill.value.files = JSON.stringify({ tree: fileTree.value })
  } catch (error) {
    ElMessage.error('保存失败')
    throw error
  }
}

const handleExport = async () => {
  exporting.value = true
  try {
    const content = await skillsApi.export(route.params.id)
    const rootFolderName = `${skill.value.name}-${skill.value.version}`

    // 创建下载链接
    const url = URL.createObjectURL(content)
    const link = document.createElement('a')
    link.href = url
    link.download = `${rootFolderName}.zip`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)

    ElMessage.success('导出成功')
  } catch (error) {
    console.error('导出失败:', error)
    ElMessage.error('导出失败')
  } finally {
    exporting.value = false
  }
}

const handleImport = async () => {
  try {
    await ElMessageBox.confirm(
      '导入将先清空原技能工作区，再写入安装包文件；技能名称、版本及其他相关信息保持不变。是否确认？',
      '导入技能',
      {
        confirmButtonText: '确认',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )
    selectedImportFile.value = null
    importDialogVisible.value = true
  } catch (error) {
    if (error !== 'cancel') ElMessage.error(error?.message || '无法打开导入弹窗')
  }
}

const handleImportFileChange = (file) => {
  selectedImportFile.value = file.raw
}

const handleImportFileExceed = () => {
  ElMessage.warning('只能上传一个文件')
}

const validateImportFile = async (file) => {
  const fileName = file.name.toLowerCase()
  if (fileName === 'skill.md') return true

  if (fileName.endsWith('.zip')) {
    try {
      const zip = new JSZip()
      const zipContent = await zip.loadAsync(file)
      const hasSkillMd = Object.keys(zipContent.files).some(
        filename => filename.toLowerCase() === 'skill.md' || filename.toLowerCase().endsWith('/skill.md')
      )
      if (!hasSkillMd) ElMessage.error('zip 压缩包中必须包含 SKILL.md 文件')
      return hasSkillMd
    } catch (error) {
      ElMessage.error('无法解析 zip 文件')
      return false
    }
  }

  ElMessage.error('文件格式不正确，请上传 SKILL.md 文件或包含 SKILL.md 的 zip 压缩包')
  return false
}

const resetImportDialog = () => {
  selectedImportFile.value = null
  importUploadRef.value?.clearFiles()
}

const handleConfirmImport = async () => {
  if (!selectedImportFile.value) {
    ElMessage.warning('请先选择要导入的文件')
    return
  }

  if (!(await validateImportFile(selectedImportFile.value))) return

  importing.value = true
  try {
    await skillsApi.importInto(route.params.id, selectedImportFile.value)
    isEditing.value = false
    currentFile.value = null
    selectedNode.value = null
    importDialogVisible.value = false
    await fetchSkillDetail()
    ElMessage.success('导入成功，工作区已替换，技能信息保持不变')
  } catch (error) {
    const isTimeout = error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT'
    const errorMsg = isTimeout
      ? '导入请求超时，请刷新详情确认是否已完成，再决定是否重试'
      : error.response?.data?.detail || error.response?.data?.message || error.message || '导入失败'
    ElMessage.error(errorMsg)
  } finally {
    importing.value = false
  }
}

// 发布版本
const handleRelease = () => {
  releaseForm.value.version = skill.value.version
  releaseForm.value.description = ''
  releaseDialog.value = true
}

const handleToggleVisibility = async () => {
  if (visibilitySaving.value) return
  visibilitySaving.value = true
  try {
    const result = await skillsApi.toggleVisibility(route.params.id)
    skill.value.is_public = Boolean(result.is_public)
    ElMessage.success(`技能已设为${skill.value.is_public ? '公开' : '私有'}`)
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '切换技能可见性失败')
  } finally {
    visibilitySaving.value = false
  }
}

const confirmRelease = async () => {
  if (!releaseForm.value.version.trim()) {
    ElMessage.warning('请输入版本号')
    return
  }

  releasing.value = true
  try {
    await skillsApi.release(route.params.id, {
      version: releaseForm.value.version,
      description: releaseForm.value.description.trim() || null,
    })

    // 更新页面上的版本号
    skill.value.version = releaseForm.value.version
    infoForm.value.version = releaseForm.value.version

    ElMessage.success('发布成功')
    releaseDialog.value = false

    // 刷新发布历史
    await fetchReleases()
  } catch (error) {
    const errorMsg = error.response?.data?.detail || '发布失败'
    ElMessage.error(errorMsg)
  } finally {
    releasing.value = false
  }
}

// 获取发布历史
const fetchReleases = async () => {
  try {
    releases.value = await skillsApi.getReleases(route.params.id)
    // 重置显示数量
    releaseDisplayCount.value = releasePageSize
  } catch (error) {
    console.error('获取发布历史失败:', error)
  }
}

// 加载更多发布记录
const loadMoreReleases = () => {
  releaseDisplayCount.value += releasePageSize
}

const handleReleaseAction = (command, release) => {
  if (command === 'notes') return showReleaseNotes(release)
  if (command === 'restore') return restoreRelease(release)
  if (command === 'copy') return copyReleaseUrl(release)
  if (command === 'download') return downloadRelease(release)
}

const showReleaseNotes = (release) => {
  activeReleaseNotes.value = release
  releaseNotesDialogVisible.value = true
}

const restoreRelease = async (release) => {
  try {
    await ElMessageBox.confirm(
      `恢复版本 ${release.version} 后，当前技能的全部文件内容将被覆盖。是否继续？`,
      '恢复发布版本',
      {
        confirmButtonText: '恢复',
        cancelButtonText: '取消',
        type: 'warning',
      }
    )

    restoringReleaseId.value = release.id
    await skillsApi.restoreRelease(route.params.id, release.id)
    isEditing.value = false
    currentFile.value = null
    selectedNode.value = null
    await fetchSkillDetail()
    ElMessage.success(`已恢复到版本 ${release.version}`)
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error(error.response?.data?.detail || '恢复失败')
    }
  } finally {
    restoringReleaseId.value = null
  }
}

// 复制发布链接
const copyReleaseUrl = async (release) => {
  const url = `${window.location.origin}${release.file_url}`
  try {
    await navigator.clipboard.writeText(url)
    ElMessage.success('链接已复制到剪贴板')
  } catch (error) {
    ElMessage.error('复制失败')
  }
}

// 下载发布文件
const downloadRelease = async (release) => {
  try {
    const blob = await assetsApi.downloadSkillRelease(release.id)
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `${skill.value.name}-${release.version}.zip`.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_')
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 60000)
  } catch (error) {
    let detail = error.response?.data?.detail
    if (error.response?.data instanceof Blob) {
      try {
        const body = JSON.parse(await error.response.data.text())
        detail = body.detail || body.message
      } catch { /* fallback below */ }
    }
    ElMessage.error(typeof detail === 'string' ? detail : '版本下载失败，请检查访问权限和发布状态')
  }
}

// 格式化时间
const formatTime = (time) => {
  return formatBeijingDateTime(time, { second: undefined })
}

// 基本信息编辑相关方法
const toggleEditInfo = () => {
  isEditingInfo.value = true
  originalInfo.value = {
    version: skill.value.version,
    // 作者属于技能自身的发布信息，编辑者不能被写入作者字段。
    author: skill.value.author,
    description: skill.value.description,
    module: skill.value.module,
    roles: skill.value.roles
  }
  infoForm.value = { ...originalInfo.value }
}

const handleCancelInfo = () => {
  infoForm.value = { ...originalInfo.value }
  isEditingInfo.value = false
}

const handleSaveInfo = async () => {
  savingInfo.value = true
  try {
    await skillsApi.update(route.params.id, {
      version: infoForm.value.version,
      description: infoForm.value.description,
      module: infoForm.value.module,
      roles: infoForm.value.roles
    })

    // 更新本地数据
    skill.value.version = infoForm.value.version
    skill.value.description = infoForm.value.description
    skill.value.module = infoForm.value.module
    skill.value.roles = infoForm.value.roles

    isEditingInfo.value = false
    ElMessage.success('保存成功')
  } catch (error) {
    ElMessage.error('保存失败')
  } finally {
    savingInfo.value = false
  }
}

// 技能名称编辑相关方法
const startEditName = () => {
  isEditingName.value = true
  editingName.value = skill.value.name
  // 使用 nextTick 确保 input 已渲染
  nextTick(() => {
    if (nameInputRef.value) {
      nameInputRef.value.focus()
      nameInputRef.value.select()
    }
  })
}

const saveSkillName = async () => {
  if (!editingName.value.trim()) {
    ElMessage.warning('技能名称不能为空')
    editingName.value = skill.value.name
    isEditingName.value = false
    return
  }

  if (editingName.value === skill.value.name) {
    isEditingName.value = false
    return
  }

  try {
    await skillsApi.update(route.params.id, {
      name: editingName.value
    })

    skill.value.name = editingName.value
    isEditingName.value = false
    ElMessage.success('技能名称已更新')
  } catch (error) {
    ElMessage.error('更新失败')
    editingName.value = skill.value.name
    isEditingName.value = false
  }
}

// GitLab 同步相关方法
const isGitBound = computed(() => !!gitSyncStatus.value?.git_repo_url)

const gitRepoName = computed(() => {
  const url = gitSyncStatus.value?.git_repo_url || ''
  try {
    const pathname = new URL(url).pathname.replace(/\.git$/, '')
    return pathname.replace(/^\//, '')
  } catch {
    return url
  }
})

const gitProviderName = computed(() => {
  const p = gitSyncStatus.value?.git_provider
  if (p === 'github') return 'GitHub'
  return 'GitLab'
})

const gitSyncStatusType = computed(() => {
  const map = { synced: 'success', syncing: '', error: 'danger' }
  return map[gitSyncStatus.value?.git_sync_status] || 'info'
})

const gitSyncStatusText = computed(() => {
  const map = { synced: '已同步', syncing: '同步中', error: '同步错误' }
  return map[gitSyncStatus.value?.git_sync_status] || '未同步'
})

const gitSyncDirectionText = computed(() => {
  const map = { 0: '未同步', 1: 'Git → 本地', 2: '本地 → Git' }
  return map[gitSyncStatus.value?.git_sync_direction] || '未同步'
})

const fetchGitSyncStatus = async () => {
  try {
    gitSyncStatus.value = await gitApi.getSyncStatus(route.params.id)
  } catch (e) {
    gitSyncStatus.value = null
  }
}

const handleGitDialogClosed = () => {
  gitBindForm.value = { provider: 'gitlab', repo_url: '', branch: 'main', branch_custom: '', access_token: '' }
  gitTestResult.value = null
}

const handleGitBind = () => {
  gitBindMode.value = 'bind'
  gitBindForm.value = { provider: 'gitlab', repo_url: '', branch: 'main', branch_custom: '', access_token: '' }
  gitTestResult.value = null
  gitBindDialogVisible.value = true
}

const handleGitEdit = () => {
  gitBindMode.value = 'edit'
  const s = gitSyncStatus.value
  // 判断分支是预设选项还是自定义
  const presetBranches = ['main', 'master']
  const currentBranch = s?.git_branch || 'main'
  gitBindForm.value = {
    provider: s?.git_provider || 'gitlab',
    repo_url: s?.git_repo_url || '',
    branch: presetBranches.includes(currentBranch) ? currentBranch : 'custom',
    branch_custom: presetBranches.includes(currentBranch) ? '' : currentBranch,
    access_token: s?.git_access_token || ''
  }
  gitTestResult.value = null
  gitBindDialogVisible.value = true
}

const handleTestGitConnection = async () => {
  if (!gitBindForm.value.repo_url) {
    ElMessage.warning('请先输入仓库地址')
    return
  }
  gitTesting.value = true
  gitTestResult.value = null
  try {
    const result = await gitApi.testConnection({
      provider: gitBindForm.value.provider,
      repo_url: gitBindForm.value.repo_url,
      access_token: gitBindForm.value.access_token || undefined,
      branch: gitBindForm.value.branch === 'custom' ? gitBindForm.value.branch_custom : gitBindForm.value.branch
    })
    gitTestResult.value = { success: true, ...result }
  } catch (e) {
    gitTestResult.value = { success: false, message: e.response?.data?.detail || '连接失败' }
  } finally {
    gitTesting.value = false
  }
}

const handleConfirmGitBind = async () => {
  if (!gitBindFormRef.value) return
  try {
    await gitBindFormRef.value.validate()
  } catch (e) {
    return
  }
  const branch = gitBindForm.value.branch === 'custom' ? gitBindForm.value.branch_custom : gitBindForm.value.branch
  if (gitBindForm.value.branch === 'custom' && !branch) {
    ElMessage.warning('请输入自定义分支名')
    return
  }
  gitSyncing.value = true
  try {
    await gitApi.bind(route.params.id, {
      provider: gitBindForm.value.provider,
      repo_url: gitBindForm.value.repo_url,
      branch: branch,
      access_token: gitBindForm.value.access_token || undefined,
    })
    ElMessage.success(gitBindMode.value === 'bind' ? '仓库绑定成功' : '仓库配置已更新')
    gitBindDialogVisible.value = false
    fetchGitSyncStatus()
    fetchSkillDetail()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '绑定失败')
  } finally {
    gitSyncing.value = false
  }
}

const handleGitUnbind = async () => {
  try {
    await ElMessageBox.confirm(`确定解除 ${gitProviderName.value} 仓库绑定吗？本地文件不会被删除。`, '解除绑定', { type: 'warning' })
    await gitApi.unbind(route.params.id)
    ElMessage.success('已解除绑定')
    gitSyncStatus.value = null
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('解除绑定失败')
  }
}

const diffDialogVisible = ref(false)
const diffDialogTitle = ref('')
const diffLocalChanges = ref([])
const diffRemoteChanges = ref([])
const handleGitSyncCommand = async (command) => {
  if (command === 'unbind') {
    await handleGitUnbind()
    return
  }

  // 查看文件差异
  if (command === 'diff') {
    try {
      const diff = await gitApi.getDiff(route.params.id)
      diffLocalChanges.value = diff.local_changes || []
      diffRemoteChanges.value = diff.remote_changes || []

      if (diffLocalChanges.value.length === 0 && diffRemoteChanges.value.length === 0) {
        ElMessage.info('本地与远程完全一致，无差异')
        return
      }

      diffDialogTitle.value = '文件差异对比'
      diffDialogVisible.value = true
    } catch (e) {
      ElMessage.error(e.response?.data?.detail || '获取差异失败')
    }
    return
  }

  // 推送/拉取：仅二次确认
  if (command === 'push' || command === 'pull') {
    const actionName = command === 'push' ? '推送' : '拉取'
    const direction = command === 'push'
      ? `将本地文件推送到 ${gitProviderName.value} 仓库`
      : `将从 ${gitProviderName.value} 仓库拉取文件覆盖本地`
    try {
      await ElMessageBox.confirm(
        `${direction}，确认继续？`,
        `确认${actionName}`,
        { confirmButtonText: actionName, cancelButtonText: '取消', type: 'warning' }
      )
      await doGitSync(command)
    } catch (e) {
      if (e !== 'cancel') ElMessage.error(e.response?.data?.detail || '操作失败')
    }
    return
  }
}

const doGitSync = async (command) => {
  gitSyncing.value = true
  try {
    let result
    if (command === 'push') {
      result = await gitApi.push(route.params.id, { commit_message: `Update skill: ${skill.value.name}` })
      ElMessage.success(result.message || '推送成功')
    } else if (command === 'pull') {
      result = await gitApi.pull(route.params.id, {})
      ElMessage.success(result.message || '拉取成功')
      fetchSkillDetail()
    }
    fetchGitSyncStatus()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  } finally {
    gitSyncing.value = false
  }
}


onMounted(() => {
  fetchSkillDetail()
  fetchReleases()
  fetchGitSyncStatus()
})
</script>

<style scoped>
.conversation-examples-list { margin: 0; padding: 12px 16px 12px 36px; color: #606266; font-size: 13px; line-height: 1.7; }
.conversation-examples-list li + li { margin-top: 8px; }
.conversation-example-text { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.examples-editor-hint { margin: 0 0 16px; color: #909399; font-size: 13px; line-height: 1.6; }
.example-editor-row { display: flex; align-items: flex-start; gap: 8px; margin-bottom: 12px; }
.example-editor-row .el-textarea { flex: 1; min-width: 0; }
.skill-detail {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: white;
  border-radius: 4px;
}

.detail-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px 12px 12px;
  border-bottom: 1px solid #e8e8e8;
}

.back-btn {
  margin-right: 8px;
  flex-shrink: 0;
  border: none;
  color: #606266;
  padding: 5px 8px 5px 0;
}

.back-btn:hover {
  color: #409eff;
  background: transparent;
}

.header-info {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.header-actions > .el-button {
  margin-left: 0;
}

.header-info h2 {
  margin: 0;
  font-size: 20px;
}

.editable-name {
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  transition: all 0.2s;
}

.editable-name:hover {
  background-color: #f5f5f5;
  color: #409eff;
}

.name-input {
  width: 80%;
}

.name-input :deep(.el-input__wrapper) {
  font-size: 20px;
  font-weight: 600;
}

.detail-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.left-sidebar {
  width: 300px;
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid #e8e8e8;
  overflow-x: hidden;
  overflow-y: auto;
  scrollbar-width: none;
  scrollbar-color: transparent transparent;
}

.left-sidebar:hover {
  scrollbar-width: thin;
  scrollbar-color: #c1c1c1 transparent;
}

.sidebar-info {
  width: 299px;
  flex: 0 0 auto;
}

.info-section {
  border-bottom: 1px solid #e8e8e8;
  background: white;
}

.info-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #e8e8e8;
  background: white;
}

.info-header h3 {
  margin: 0;
  font-size: 14px;
}

.info-actions {
  display: flex;
  gap: 5px;
}

.info-content {
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  font-size: 13px;
}

.info-item {
  display: flex;
  gap: 8px;
  align-items: flex-start;
}

.info-item-full {
  grid-column: auto;
}

.info-label {
  font-weight: 500;
  color: #606266;
  font-size: 12px;
  white-space: nowrap;
  flex-shrink: 0;
}

.info-value {
  color: #303133;
  word-break: break-word;
  flex: 1;
}

.info-edit {
  padding: 12px 16px;
}

.file-section {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.file-tree {
  width: 299px;
  flex: none;
}

.file-tree :deep(.el-tree) {
  padding: 8px 12px;
}

.file-tree :deep(.el-tree-node__content) {
  height: auto;
  padding: 4px 0;
}

.tree-header {
  padding: 12px 16px;
  border-bottom: 1px solid #e8e8e8;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.tree-header h3 {
  margin: 0;
  font-size: 14px;
}

.tree-actions {
  display: flex;
  gap: 10px;
}

.tree-actions .el-button + .el-button {
  margin-left: 0;
}

.hidden-file-input {
  display: none;
}

.skill-detail :deep(.md-editor-code-head) {
  z-index: 2 !important;
}

.tree-node {
  display: flex;
  align-items: center;
  width: 100%;
  justify-content: space-between;
  overflow: hidden;
  padding: 2px 0;
}

.tree-node:hover {
  background-color: transparent;
}

.node-label {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.node-label span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.release-history {
  width: 299px;
  border-top: 1px solid #e8e8e8;
  background: white;
  flex: none;
}

.release-header {
  padding: 12px 16px;
  border-bottom: 1px solid #e8e8e8;
}

.release-header h3 {
  margin: 0;
  font-size: 14px;
}

.release-list {
  overflow: visible;
}

.left-sidebar::-webkit-scrollbar {
  width: 0;
}

.left-sidebar:hover::-webkit-scrollbar {
  width: 4px;
}

.left-sidebar::-webkit-scrollbar-track {
  background: transparent;
}

.left-sidebar::-webkit-scrollbar-thumb {
  background: transparent;
  border-radius: 3px;
}

.left-sidebar:hover::-webkit-scrollbar-thumb {
  background: #c1c1c1;
}

.left-sidebar::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}

.release-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #f0f0f0;
  transition: background-color 0.2s;
}

.release-item:hover {
  background-color: #f5f7fa;
}

.load-more {
  text-align: center;
  padding: 12px 16px;
  border-top: 1px solid #f0f0f0;
}

.release-info {
  flex: 1;
  min-width: 0;
}

.release-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.release-version {
  font-size: 13px;
  font-weight: normal;
  color: #303133;
}

.release-more-button.el-button {
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  padding: 0;
}

.release-description {
  display: block;
  width: 100%;
  margin: 3px 0 4px;
  padding: 0;
  border: 0;
  color: #606266;
  background: transparent;
  font-size: 12px;
  line-height: 18px;
  text-align: left;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  cursor: pointer;
}

.release-description:hover {
  color: #409eff;
}

.release-description:focus-visible {
  outline: 2px solid #409eff;
  outline-offset: 2px;
}

.release-notes-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding-bottom: 12px;
  color: #303133;
}

.release-notes-meta span {
  flex-shrink: 0;
  color: #909399;
  font-size: 12px;
}

.release-notes-content {
  max-height: 50vh;
  overflow-y: auto;
  padding-top: 12px;
  border-top: 1px solid #ebeef5;
  color: #606266;
  line-height: 1.7;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.release-time {
  font-size: 12px;
  color: #909399;
}

.node-trailing {
  display: grid;
  place-items: center end;
  width: 56px;
  height: 24px;
  flex: 0 0 56px;
  margin-left: 4px;
  margin-right: 8px;
}

.node-size,
.node-control {
  grid-area: 1 / 1;
  transition: opacity 0.15s ease;
}

.node-size {
  color: #a8abb2;
  font-size: 11px;
  line-height: 24px;
  white-space: nowrap;
}

.node-control {
  visibility: hidden;
  opacity: 0;
  pointer-events: none;
}

.node-actions {
  display: flex;
}

.tree-node:not(.is-skill-md):hover .node-size,
.node-trailing:focus-within .node-size {
  visibility: hidden;
  opacity: 0;
}

.tree-node:hover .node-control,
.node-trailing:focus-within .node-control {
  visibility: visible;
  opacity: 1;
  pointer-events: auto;
}

.skill-lock {
  flex: 0 0 auto;
  color: #909399;
}

.node-more-button.el-button {
  width: 24px;
  height: 24px;
  padding: 0;
  color: #606266;
}

.content-area {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.empty-file-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.content-header {
  padding: 12px 24px;
  border-bottom: 1px solid #e8e8e8;
  background: #fafafa;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.current-file {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: #606266;
}

.content-actions {
  display: flex;
  gap: 8px;
}

.folder-view {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #fafafa;
}

.folder-icon {
  font-size: 120px;
  color: #dcdfe6;
}

.preview-mode {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
}

.preview-mode::-webkit-scrollbar {
  width: 4px;
}

.preview-mode::-webkit-scrollbar-track {
  background: #f1f1f1;
  border-radius: 3px;
}

.preview-mode::-webkit-scrollbar-thumb {
  background: #c1c1c1;
  border-radius: 3px;
}

.preview-mode::-webkit-scrollbar-thumb:hover {
  background: #a8a8a8;
}

.preview-mode :deep(.cm-editor) {
  height: 100%;
}

.edit-mode {
  flex: 1;
  overflow: hidden;
}

.edit-mode :deep(.md-editor) {
  height: 100%;
}

.edit-mode :deep(.cm-editor) {
  height: 100%;
}
</style>


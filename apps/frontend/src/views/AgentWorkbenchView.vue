<template>
  <div class="flex flex-col h-[calc(100vh-120px)] min-h-[560px] -mt-2">
    <div class="electron-drag h-5 shrink-0" aria-hidden="true" />
    <div class="flex items-center justify-between gap-3 px-1 pb-3 workbench-head">
      <div class="min-w-0">
        <h1 class="text-[20px] font-semibold tracking-[-0.02em] text-ink truncate">智能体工作台</h1>
        <p class="text-[11px] tracking-wide text-muted">规划 · 转录 · 洞察 · trace 可追溯 · SSE 9事件+审批</p>
      </div>
      <div class="flex items-center gap-2 shrink-0">
        <n-tag v-if="wb.status === 'running'" type="warning" size="small">运行中</n-tag>
        <n-tag v-else-if="wb.status === 'completed'" type="success" size="small">已完成</n-tag>
        <n-tag v-else-if="wb.status === 'failed'" type="error" size="small">失败</n-tag>
        <n-tag v-else size="small">空闲</n-tag>
        <span class="hidden sm:inline text-[11px] tracking-wide px-2 py-1 rounded-full bg-surface text-muted font-mono" aria-label="当前 trace">trace_id: {{ wb.traceId ? wb.traceId.slice(0, 8) : '—' }}</span>
        <div v-if="wb.transcript.length" class="relative">
          <div class="flex items-center gap-1">
            <button
              class="px-3 py-1.5 text-[11px] font-medium rounded-full bg-surface text-muted hover:text-ink border border-hairline transition-colors"
              aria-label="复制全文"
              @click="copyFullTranscript"
            >复制全文</button>
            <button
              class="px-2 py-1.5 text-[11px] rounded-full bg-surface text-muted hover:text-ink border border-hairline transition-colors"
              aria-label="导出菜单"
              :aria-expanded="exportOpen"
              @click="exportOpen = !exportOpen"
            >更多</button>
          </div>
          <div v-if="exportOpen" class="absolute right-0 top-full mt-1 z-20 w-[160px] rounded-[12px] border border-hairline bg-[var(--c-bg)] shadow-lg p-1" @click.stop>
            <button class="w-full text-left px-2.5 py-1.5 text-[12px] rounded-[8px] text-ink hover:bg-[var(--c-surface)]" @click="onExportMarkdown">复制 Markdown</button>
            <button class="w-full text-left px-2.5 py-1.5 text-[12px] rounded-[8px] text-ink hover:bg-[var(--c-surface)]" @click="onDownloadMarkdown">下载 .md 文件</button>
            <button class="w-full text-left px-2.5 py-1.5 text-[12px] rounded-[8px] text-ink hover:bg-[var(--c-surface)]" @click="onCopyTraceId">复制 trace_id</button>
          </div>
        </div>
        <button class="px-3.5 py-1.5 text-[12px] font-medium rounded-full bg-ink text-white hover:bg-[var(--c-ink-hover)] transition-colors" aria-label="新会话" @click="newSession">＋ 新会话</button>
      </div>
    </div>

    <div class="flex-1 min-h-0 flex gap-4 workbench-cols">
      <!-- 移动端三 Tab：会话/对话/监控，仅布局显隐，复用现有三栏组件 -->
      <div class="md:hidden flex items-center gap-1 p-1 rounded-full bg-surface border border-hairline mb-2" role="tablist" aria-label="工作台视图切换">
        <button
          role="tab"
          :aria-selected="mobileTab === 'session'"
          aria-label="会话列表"
          :class="['flex-1 px-3 py-1.5 text-[12px] rounded-full transition-colors', mobileTab === 'session' ? 'bg-ink text-white font-medium' : 'text-muted']"
          @click="mobileTab = 'session'"
        >会话</button>
        <button
          role="tab"
          :aria-selected="mobileTab === 'chat'"
          aria-label="对话"
          :class="['flex-1 px-3 py-1.5 text-[12px] rounded-full transition-colors', mobileTab === 'chat' ? 'bg-ink text-white font-medium' : 'text-muted']"
          @click="mobileTab = 'chat'"
        >对话</button>
        <button
          role="tab"
          :aria-selected="mobileTab === 'monitor'"
          aria-label="监控"
          :class="['flex-1 px-3 py-1.5 text-[12px] rounded-full transition-colors', mobileTab === 'monitor' ? 'bg-ink text-white font-medium' : 'text-muted']"
          @click="mobileTab = 'monitor'"
        >监控</button>
      </div>
      <aside v-if="!leftCollapsed" aria-label="会话列表" :data-active="mobileTab === 'session'" class="workbench-pane workbench-pane-session hidden md:flex w-[280px] shrink-0 flex-col rounded-[16px] bg-surface/60 border border-hairline p-3">
        <button
          class="w-full px-3.5 py-2 text-[13px] font-medium rounded-[12px] bg-ink text-white hover:bg-[var(--c-ink-hover)] transition-colors"
          style="letter-spacing:-0.011em"
          aria-label="新任务"
          @click="newSession"
        >＋ 新任务</button>
        <div class="mt-2">
          <input
            v-model="searchQuery"
            type="text"
            maxlength="100"
            placeholder="搜索任务标题或会话内容..."
            aria-label="搜索任务"
            class="w-full rounded-[12px] border border-hairline bg-[var(--c-bg)] px-3 py-2 text-[12px] text-ink placeholder:text-muted focus:outline-none focus:border-[#0071e3]/40"
          />
        </div>
        <div class="mt-2 flex items-center gap-1 p-0.5 rounded-full bg-[var(--c-bg)] border border-hairline" role="tablist" aria-label="会话视图切换">
          <button
            role="tab"
            :aria-selected="viewMode === 'list'"
            aria-label="列表视图"
            :class="['flex-1 px-2 py-1 text-[11px] rounded-full transition-colors', viewMode === 'list' ? 'bg-ink text-white font-medium' : 'text-muted hover:text-ink']"
            @click="viewMode = 'list'"
          >列表</button>
          <button
            role="tab"
            :aria-selected="viewMode === 'kanban'"
            aria-label="看板视图"
            :class="['flex-1 px-2 py-1 text-[11px] rounded-full transition-colors', viewMode === 'kanban' ? 'bg-ink text-white font-medium' : 'text-muted hover:text-ink']"
            @click="viewMode = 'kanban'"
          >看板</button>
        </div>
        <div class="mt-2 flex items-center justify-between px-2 py-1">
          <span class="text-[11px] tracking-widest font-medium text-muted">会话</span>
          <div class="flex items-center gap-2">
            <span class="text-[11px] text-muted">{{ sessionsStore.total }}</span>
            <button class="text-[11px] text-muted hover:text-ink" aria-label="收起会话栏" @click="leftCollapsed = true">«</button>
          </div>
        </div>
        <div class="mt-1 flex-1 min-h-0 overflow-auto space-y-3 pr-1" role="listbox" aria-label="历史会话">
          <template v-if="viewMode === 'list'">
            <template v-if="groupedSessions.length">
              <div v-for="g in groupedSessions" :key="g.key">
                <div class="px-2 py-1 text-[11px] text-muted" style="letter-spacing:-0.011em">{{ g.key }}</div>
                <div class="space-y-1">
                  <div
                    v-for="s in g.items"
                    :key="s.trace_id"
                    role="option"
                    :aria-selected="wb.traceId === s.trace_id"
                    :class="['group relative w-full text-left px-3 py-2.5 rounded-[12px] transition-colors cursor-pointer', wb.traceId === s.trace_id ? 'bg-ink text-white' : 'hover:bg-[var(--c-bg)] text-ink']"
                    @click="replaySession(s)"
                  >
                    <div class="flex items-center justify-between gap-2">
                      <span class="text-[13px] font-medium truncate" style="letter-spacing:-0.011em">
                        <span v-if="sessionsStore.isPinned(s.trace_id)" class="mr-1 text-[11px] px-1 py-px rounded-full bg-[#eff6ff] text-[#1e40af] border border-[#bfdbfe] align-middle">置顶</span>{{ sessionDisplay(s) }}
                      </span>
                      <span :class="['text-[11px] px-1.5 py-0.5 rounded-full border shrink-0', pillClass(sessionState(s))]">{{ pillLabel(sessionState(s)) }}</span>
                    </div>
                    <div class="mt-1 flex items-center gap-2">
                      <span :class="['text-[11px] px-1.5 py-0.5 rounded-full border', modeClass(s.mode)]">{{ s.mode }}</span>
                      <span :class="['text-[11px]', wb.traceId === s.trace_id ? 'text-white/60' : 'text-muted']">{{ relativeTime(s.last_event_at) }}</span>
                      <span :class="['text-[11px] font-mono', wb.traceId === s.trace_id ? 'text-white/60' : 'text-muted']">{{ s.event_count }} 事件</span>
                      <span class="ml-auto opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                        <button
                          class="text-[11px] px-1.5 py-0.5 rounded-full border border-hairline bg-[var(--c-bg)] text-muted hover:text-ink"
                          aria-label="会话操作菜单"
                          @click.stop="toggleMenu(s.trace_id)"
                        >···</button>
                      </span>
                    </div>
                    <div
                      v-if="openMenuId === s.trace_id"
                      class="absolute right-2 top-full mt-1 z-20 w-[132px] rounded-[12px] border border-hairline bg-[var(--c-bg)] shadow-lg p-1"
                      @click.stop
                    >
                      <button class="w-full text-left px-2.5 py-1.5 text-[12px] rounded-[8px] text-ink hover:bg-[var(--c-surface)]" @click="pinSession(s)">{{ sessionsStore.isPinned(s.trace_id) ? '取消置顶' : '置顶' }}</button>
                      <button class="w-full text-left px-2.5 py-1.5 text-[12px] rounded-[8px] text-ink hover:bg-[var(--c-surface)]" @click="renameSession(s)">重命名</button>
                      <button class="w-full text-left px-2.5 py-1.5 text-[12px] rounded-[8px] text-[#991b1b] hover:bg-[#fef2f2]" @click="deleteSession(s)">删除</button>
                    </div>
                  </div>
                </div>
              </div>
            </template>
            <div v-if="!groupedSessions.length && !sessionsStore.loading" class="py-8 text-center">
              <div class="mx-auto w-9 h-9 rounded-[12px] bg-[var(--c-bg)] border border-hairline flex items-center justify-center text-[13px] font-medium text-muted">空</div>
              <div class="mt-2 text-[12px] text-muted">{{ searchQuery.trim() ? '无匹配任务' : '暂无历史会话' }}</div>
              <div class="mt-1 text-[11px] text-muted/70">{{ searchQuery.trim() ? '换个关键词试试' : '创建目标并生成计划后展示' }}</div>
            </div>
          </template>
          <template v-else>
            <div v-for="g in kanbanGroups" :key="g.key" class="rounded-[12px] border border-hairline bg-[var(--c-bg)] p-2">
              <div class="px-1 py-1 text-[11px] font-medium text-muted">{{ g.key }} · {{ g.items.length }}</div>
              <div class="space-y-1">
                <div
                  v-for="s in g.items"
                  :key="s.trace_id"
                  role="option"
                  :aria-selected="wb.traceId === s.trace_id"
                  :class="['group relative w-full text-left px-3 py-2 rounded-[10px] transition-colors cursor-pointer border border-transparent', wb.traceId === s.trace_id ? 'bg-ink text-white' : 'bg-[var(--c-surface)] hover:bg-white text-ink border-hairline']"
                  @click="replaySession(s)"
                >
                  <div class="flex items-center justify-between gap-2">
                    <span class="text-[12px] font-medium truncate">{{ sessionDisplay(s) }}</span>
                    <span :class="['text-[10px] px-1.5 py-0.5 rounded-full border shrink-0', pillClass(sessionState(s))]">{{ pillLabel(sessionState(s)) }}</span>
                  </div>
                  <div class="mt-1 flex items-center gap-2">
                    <span :class="['text-[10px]', wb.traceId === s.trace_id ? 'text-white/60' : 'text-muted']">{{ relativeTime(s.last_event_at) }}</span>
                    <span class="ml-auto opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity">
                      <button
                        class="text-[10px] px-1.5 py-0.5 rounded-full border border-hairline bg-[var(--c-bg)] text-muted hover:text-ink"
                        aria-label="会话操作菜单"
                        @click.stop="toggleMenu(s.trace_id)"
                      >···</button>
                    </span>
                  </div>
                  <div
                    v-if="openMenuId === s.trace_id"
                    class="absolute right-2 top-full mt-1 z-20 w-[132px] rounded-[12px] border border-hairline bg-[var(--c-bg)] shadow-lg p-1"
                    @click.stop
                  >
                    <button class="w-full text-left px-2.5 py-1.5 text-[12px] rounded-[8px] text-ink hover:bg-[var(--c-surface)]" @click="pinSession(s)">{{ sessionsStore.isPinned(s.trace_id) ? '取消置顶' : '置顶' }}</button>
                    <button class="w-full text-left px-2.5 py-1.5 text-[12px] rounded-[8px] text-ink hover:bg-[var(--c-surface)]" @click="renameSession(s)">重命名</button>
                    <button class="w-full text-left px-2.5 py-1.5 text-[12px] rounded-[8px] text-[#991b1b] hover:bg-[#fef2f2]" @click="deleteSession(s)">删除</button>
                  </div>
                </div>
                <div v-if="!g.items.length" class="py-2 text-center text-[11px] text-muted">暂无</div>
              </div>
            </div>
          </template>
        </div>
        <div class="mt-2 pt-2 border-t border-hairline flex items-center justify-between">
          <button class="text-[11px] text-muted hover:text-ink disabled:opacity-40" :disabled="sessionsStore.page <= 1 || sessionsStore.loading" @click="prevPage">上一页</button>
          <span class="text-[11px] text-muted font-mono">{{ sessionsStore.page }}/{{ Math.max(1, Math.ceil(sessionsStore.total / sessionsStore.size)) }}</span>
          <button class="text-[11px] text-muted hover:text-ink disabled:opacity-40" :disabled="!sessionsStore.hasMore || sessionsStore.loading" @click="loadMore">下一页</button>
        </div>
        <div class="relative mt-2 pt-2 border-t border-hairline">
          <button
            class="w-full flex items-center gap-2 px-2 py-1.5 rounded-[12px] hover:bg-[var(--c-bg)] transition-colors"
            aria-label="用户菜单"
            :aria-expanded="showUserMenu"
            @click="showUserMenu = !showUserMenu"
          >
            <span class="w-7 h-7 rounded-full bg-ink text-white text-[12px] font-semibold flex items-center justify-center shrink-0">{{ userIdLabel }}</span>
            <span class="text-[12px] text-ink truncate" style="letter-spacing:-0.011em">我的工作台</span>
            <span class="ml-auto text-[11px] text-muted">{{ showUserMenu ? '收起' : '展开' }}</span>
          </button>
          <div v-if="showUserMenu" class="absolute left-0 right-0 bottom-full mb-1 z-20 rounded-[12px] border border-hairline bg-[var(--c-bg)] shadow-lg p-1">
            <button class="w-full text-left px-2.5 py-1.5 text-[12px] rounded-[8px] text-ink hover:bg-[var(--c-surface)]" @click="goSettings">设置</button>
            <button class="w-full text-left px-2.5 py-1.5 text-[12px] rounded-[8px] text-ink hover:bg-[var(--c-surface)]" @click="handleToggleTheme">{{ themeLabel }}</button>
            <button class="w-full text-left px-2.5 py-1.5 text-[12px] rounded-[8px] text-ink hover:bg-[var(--c-surface)]" @click="handleLogout">退出登录</button>
          </div>
        </div>
      </aside>
      <div v-else class="hidden md:flex w-[36px] shrink-0 flex-col items-center rounded-[16px] bg-surface/60 border border-hairline py-2 gap-2">
        <button class="text-[11px] text-muted hover:text-ink" aria-label="展开会话栏" @click="leftCollapsed = false">»</button>
        <div class="text-[11px] tracking-widest text-muted" style="writing-mode: vertical-rl">会话</div>
      </div>

      <main :data-active="mobileTab === 'chat'" class="workbench-pane workbench-pane-chat flex-1 min-w-0 flex flex-col rounded-[16px] bg-[var(--c-bg)] border border-hairline overflow-hidden">
        <TranscriptView
          v-if="wb.transcript.length || wb.status === 'running'"
          :items="wb.transcript"
          :reconnecting="wb.reconnecting"
          :selected-node-id="wb.selectedNodeId"
          :last-event-id="wb.lastEventId"
          :status="wb.status"
          :trace-id="wb.traceId"
          @select="onTranscriptSelect"
          @resend="onResend"
        />
        <div v-else class="flex-1 overflow-auto p-6 flex items-center justify-center" aria-label="空态">
          <div class="text-center max-w-[480px]">
            <div class="mx-auto w-10 h-10 rounded-[12px] bg-ink text-white flex items-center justify-center text-[14px] font-semibold">AI</div>
            <div v-if="wb.status === 'failed'" class="mt-3">
              <div class="text-[15px] font-semibold tracking-[-0.01em] text-ink">规划中断，已停止重连</div>
              <p class="mt-1 text-[13px] leading-5 text-muted">{{ wb.failMessage || '会话不存在或网络中断，可点击下方重试' }}</p>
              <button class="mt-3 px-4 py-2 rounded-full bg-ink text-white text-[13px] hover:bg-[var(--c-ink-hover)] transition-colors" aria-label="重试连接" @click="handleRetry">重试</button>
            </div>
            <template v-else>
              <div class="mt-4 text-[28px] leading-9 font-semibold text-ink" style="letter-spacing:-0.011em">不止规划，搞定学习</div>
              <p class="mt-2 text-[14px] leading-6 text-muted" style="letter-spacing:-0.011em">描述目标，AI 自主拆解、执行并接受你的审批</p>
              <div class="mt-5 flex flex-wrap justify-center gap-2">
                <button
                  v-for="ex in examplePrompts"
                  :key="ex"
                  class="px-3.5 py-2 text-[12px] rounded-full bg-[var(--c-bg)] border border-hairline text-ink hover:bg-[var(--c-surface)] transition-colors"
                  style="letter-spacing:-0.011em"
                  :aria-label="`填入示例：${ex}`"
                  @click="fillExample(ex)"
                >{{ ex }}</button>
              </div>
            </template>
          </div>
        </div>

        <div class="border-t border-hairline p-4">
          <div v-if="attachedFiles.length" class="mb-2 flex flex-wrap gap-1.5" aria-label="已关联知识">
            <span
              v-for="(f, i) in attachedFiles"
              :key="`${f}-${i}`"
              class="inline-flex items-center gap-1.5 text-[11px] px-2.5 py-1 rounded-full bg-[var(--c-surface)] border border-hairline text-ink"
            >已关联知识：{{ f }}
              <button class="text-muted hover:text-ink" :aria-label="`移除附件 ${f}`" @click="removeAttach(i)">×</button>
            </span>
          </div>
          <div class="relative">
            <div
              v-if="showMention"
              class="absolute left-0 right-0 bottom-full mb-1 z-20 rounded-[12px] border border-hairline bg-[var(--c-bg)] shadow-lg p-1 max-h-[220px] overflow-auto"
              role="listbox"
              aria-label="提及目标"
            >
              <div class="px-2.5 py-1 text-[11px] text-muted">选择目标插入（@ 触发）</div>
              <button
                v-for="o in filteredGoalOpts"
                :key="o.value"
                role="option"
                :aria-selected="selectedGoal === o.value"
                class="w-full text-left px-2.5 py-1.5 text-[12px] rounded-[8px] text-ink hover:bg-[var(--c-surface)] truncate"
                @mousedown.prevent="selectMention(o)"
              >{{ o.label }}</button>
              <div v-if="!filteredGoalOpts.length" class="px-2.5 py-2 text-[12px] text-muted">无匹配目标，直接输入将自动建目标</div>
            </div>
            <div
              v-if="showSlashMenu"
              class="absolute left-0 right-0 bottom-full mb-1 z-20 rounded-[12px] border border-hairline bg-white shadow-lg p-1 max-h-[280px] overflow-auto"
              aria-label="斜杠菜单"
            >
              <div class="px-2.5 pt-1 text-[11px] text-muted">斜杠命令（/ 触发）</div>
              <ComposerMenu :items="slashItems" @select="onComposerMenuSelect" />
              <div class="px-2.5 pt-1 text-[11px] text-muted border-t border-hairline mt-1">技能模板（填入不发送）</div>
              <ComposerMenu :items="skillItems" @select="onComposerMenuSelect" />
            </div>
            <textarea
              ref="inputRef"
              v-model="composer"
              rows="1"
              maxlength="2000"
              class="w-full resize-none rounded-[12px] border border-hairline bg-surface/50 px-3 py-2.5 text-[13px] text-ink placeholder:text-muted focus:outline-none focus:border-[#0071e3]/40 disabled:opacity-50"
              style="letter-spacing:-0.011em"
              placeholder="描述目标… @提及目标 /快捷命令，如：30天过六级，每天2小时"
              aria-label="目标输入"
              :disabled="wb.status === 'running'"
              @input="onComposerInput"
              @keydown.enter.exact.prevent="send"
              @keydown.escape="onComposerEscape"
            />
          </div>
          <div class="mt-2 flex items-center gap-2 flex-wrap composer-bar composer-controls">
            <input ref="fileInputRef" type="file" class="hidden" aria-label="选择附件" @change="onFileChange" />
            <button
              class="w-8 h-8 rounded-full border border-hairline bg-[var(--c-bg)] text-[15px] text-muted hover:text-ink flex items-center justify-center shrink-0 disabled:opacity-40"
              aria-label="添加附件并上传知识库"
              title="附件上传知识库"
              :disabled="uploading"
              @click="pickFile"
            >＋</button>
            <n-select
              v-model:value="selectedGoal"
              :options="goalOpts"
              placeholder="目标（或 @ 提及）"
              clearable
              size="small"
              class="w-[190px]"
              aria-label="选择目标"
            />
            <div class="flex rounded-full border border-hairline bg-surface/50 p-0.5" role="radiogroup" aria-label="规划模式">
              <button
                :class="['px-3 py-1 text-[11px] rounded-full transition-colors', mode === 'single' ? 'bg-ink text-white' : 'text-muted hover:text-ink']"
                role="radio"
                :aria-checked="mode === 'single'"
                @click="mode = 'single'"
              >单智能体</button>
              <button
                :class="['px-3 py-1 text-[11px] rounded-full transition-colors', mode === 'multi' ? 'bg-ink text-white' : 'text-muted hover:text-ink']"
                role="radio"
                :aria-checked="mode === 'multi'"
                @click="mode = 'multi'"
              >多智能体</button>
            </div>
            <n-select
              v-model:value="selectedModel"
              :options="modelOpts"
              placeholder="模型"
              size="small"
              class="w-[140px]"
              aria-label="选择模型"
            />
            <button
              :class="['px-3 py-1 text-[11px] rounded-full border transition-colors shrink-0', needApproval ? 'bg-[#fffbeb] border-[#fde68a] text-[#92400e]' : 'border-hairline text-muted hover:text-ink']"
              :disabled="mode !== 'multi'"
              :aria-pressed="needApproval"
              aria-label="写库审批开关（仅多智能体）"
              @click="needApproval = !needApproval"
            >{{ needApproval ? '审批开' : '审批关' }}</button>
            <label class="flex items-center gap-1 text-[11px] text-muted shrink-0" aria-label="每日时长">
              <span>每天</span>
              <input
                v-model.number="hours"
                type="number"
                min="1"
                max="8"
                class="w-[52px] rounded-[8px] border border-hairline bg-surface/50 px-2 py-1 text-[12px] text-ink focus:outline-none"
                aria-label="每天小时数"
              />
              <span>小时</span>
            </label>
            <div class="ml-auto flex items-center gap-2 shrink-0">
              <button
                v-if="wb.status === 'running'"
                class="px-4 py-2 rounded-full bg-[var(--c-bg)] border border-hairline text-[13px] text-ink hover:bg-[var(--c-surface)] transition-colors"
                aria-label="停止"
                @click="handleStop"
              >停止</button>
              <button
                v-else-if="wb.status === 'failed'"
                class="px-4 py-2 rounded-full bg-[var(--c-bg)] border border-hairline text-[13px] text-ink hover:bg-[var(--c-surface)] transition-colors"
                aria-label="重试"
                @click="handleRetry"
              >重试</button>
              <button
                class="px-4 py-2 rounded-full bg-ink text-white text-[13px] hover:bg-[var(--c-ink-hover)] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                :disabled="creating || wb.status === 'running' || !composer.trim() || composer.trim().length > 2000"
                aria-label="发送"
                @click="send"
              >{{ creating ? '生成中…' : '发送' }}</button>
            </div>
          </div>
          <div class="mt-2 flex items-center justify-between text-[11px] tracking-wide text-muted">
            <span>Enter 发送 · Shift+Enter 换行 · @提及目标 · /命令 · ＋附件<span v-if="uploading">上传中…</span> · 模式 {{ mode }} · 模型 {{ selectedModel }}<span v-if="needApproval && mode === 'multi'"> · 审批开</span> · {{ composer.trim().length }}/2000 字<span v-if="wb.status === 'running'"> · 运行中已锁定输入</span></span>
            <span v-if="wb.traceId" class="font-mono">trace {{ wb.traceId.slice(0, 8) }} · 续传 last_event_id={{ wb.lastEventId || '0' }}</span>
            <span v-else>转录流 · 工具折叠块 · 任务卡</span>
          </div>
          <div v-if="lastUsageText" class="mt-1 text-[11px] tracking-wide text-muted">上次完成 · {{ lastUsageText }}</div>
          <div v-if="wb.status === 'failed'" class="mt-2 flex items-center gap-2 text-[11px] text-[#991b1b]" role="alert">
            <span>{{ wb.failMessage || '连接失败，已停止重连' }}</span>
            <button class="px-2.5 py-1 rounded-full bg-[#fef2f2] border border-[#fecaca] hover:bg-[#fee2e2]" aria-label="失败重试" @click="handleRetry">重试</button>
          </div>
        </div>
      </main>

      <aside v-if="!rightCollapsed" aria-label="Inspector" :data-active="mobileTab === 'monitor'" class="workbench-pane workbench-pane-monitor hidden xl:flex w-[300px] shrink-0 flex-col rounded-[16px] bg-surface/60 border border-hairline p-3">
        <div class="flex items-center justify-between px-2 py-1">
          <span class="text-[11px] tracking-widest font-medium text-muted">INSPECTOR</span>
          <button class="text-[11px] text-muted hover:text-ink" aria-label="收起 Inspector" @click="rightCollapsed = true">»</button>
        </div>
        <!-- MonitorPanel 由另一人并行新建：import.meta.glob 缺失时返回空，不打包不报错，懒加载失败走空白占位 -->
        <div v-if="showMonitor" class="mb-2 rounded-[12px] border border-hairline bg-[var(--c-bg)] overflow-hidden">
          <MonitorPanel
            :status="wb.status"
            :tasks-preview="monitorTasksPreview"
            :approve-token="monitorApproveToken"
            :trace-id="wb.traceId ?? ''"
            :expires-in="monitorExpiresIn"
            :nodes="monitorNodes"
            :citations="monitorCitations"
            :counts="monitorCounts"
            @resolved="onMonitorResolved"
            @approve="onMonitorResolved"
            @reject="onMonitorResolved"
          />
        </div>
        <div class="mt-2 flex-1 min-h-0 flex flex-col bg-[var(--c-bg)] rounded-[12px] border border-hairline overflow-hidden">
          <n-tabs type="line" animated style="--n-tab-padding: 10px;" class="flex-1 min-h-0 flex flex-col">
            <n-tab-pane name="dag" tab="DAG" class="h-full">
              <div class="p-2 overflow-auto h-full">
                <GraphCanvas
                  v-if="wb.graph.nodes.length"
                  :nodes="wb.graph.nodes"
                  :edges="wb.graph.edges"
                  :status="wb.graph.status"
                  :selected-id="wb.selectedNodeId"
                  @select="onSelectNode"
                />
                <div v-else class="text-[12px] text-muted text-center py-10">无运行中的智能体<br /><span class="text-[11px]">生成计划后展示 6节点 DAG</span></div>
                <div v-if="wb.graph.nodes.length" class="mt-2 flex flex-wrap gap-1.5">
                  <span v-for="n in wb.graph.nodes" :key="n.id" :class="['text-[11px] px-2 py-0.5 rounded-full border', nodeClass(n.status)]">{{ n.name }}:{{ n.status }}</span>
                </div>
                <div v-if="wb.manifest" class="mt-3 rounded-[10px] bg-[var(--c-surface)] p-2">
                  <div class="text-[11px] tracking-widest text-muted">小工具清单 · {{ wb.manifest.tools.length }} 个</div>
                  <div class="mt-1 flex flex-wrap gap-1">
                    <span v-for="t in wb.manifest.tools.slice(0, 12)" :key="t.name" class="text-[11px] px-1.5 py-0.5 rounded-full bg-[var(--c-bg)] border border-hairline text-ink" :title="t.description || t.name">{{ t.label || t.name }}</span>
                  </div>
                  <div v-if="wb.manifest.tools.length > 12" class="mt-1 text-[11px] text-muted">…等 {{ wb.manifest.tools.length }} 个，详见工具 Tab</div>
                </div>
              </div>
            </n-tab-pane>
            <n-tab-pane name="state" tab="State">
              <div class="p-3 space-y-2">
                <div class="flex items-center justify-between">
                  <span class="text-[11px] text-muted">state 快照</span>
                  <button class="text-[11px] text-muted hover:text-ink" @click="copyJson(wb.inspector.state)">复制</button>
                </div>
                <n-code :code="pretty(wb.inspector.state)" language="json" class="text-[11px]" />
              </div>
            </n-tab-pane>
            <n-tab-pane name="logs" tab="Logs">
              <div class="p-3 space-y-2">
                <div class="flex items-center justify-between gap-2">
                  <span class="text-[11px] text-muted">agent_run_log ({{ wb.filteredLogs.length }}/{{ wb.inspector.logs.length }})</span>
                  <div class="flex items-center gap-1">
                    <button class="text-[11px] text-muted hover:text-ink" @click="copyAllLogs">复制全部</button>
                    <button class="text-[11px] text-muted hover:text-ink" @click="copyJson(wb.filteredLogs)">复制JSON</button>
                  </div>
                </div>
                <n-select
                  v-model:value="wb.logAgentFilter"
                  :options="agentFilterOpts"
                  placeholder="按 agent_name 过滤"
                  clearable
                  size="small"
                  aria-label="按智能体过滤日志"
                />
                <div v-for="lg in wb.filteredLogs" :key="String(lg.id ?? `${lg.agent_name}-${lg.created_at}`)" :class="['rounded-[10px] p-2', lg.agent_name === wb.selectedNodeId ? 'bg-[#eff6ff] border border-[#bfdbfe]' : 'bg-[#f5f5f7]']">
                  <div class="flex items-center justify-between gap-2">
                    <div class="text-[11px] font-medium text-ink truncate">{{ lg.agent_name }} <span class="text-muted font-normal">{{ String(lg.created_at ?? '').slice(11, 19) }}</span></div>
                    <button class="text-[11px] text-muted hover:text-ink shrink-0" @click="copyJson(lg)">复制</button>
                  </div>
                  <div class="text-[11px] text-muted mt-1 break-all">input: {{ jsonStr(lg.input) }}</div>
                  <div class="text-[11px] text-muted break-all">output: {{ jsonStr(lg.output) }}</div>
                  <div v-if="lg.tool_calls?.length" class="mt-1">
                    <button class="text-[11px] text-[#1e40af] hover:underline" :aria-expanded="isLogExpanded(logKey(lg))" @click="toggleLog(logKey(lg))">
                      {{ isLogExpanded(logKey(lg)) ? '收起' : '展开' }} tool_calls ({{ lg.tool_calls.length }})
                    </button>
                    <div v-if="isLogExpanded(logKey(lg))" class="mt-1 space-y-1">
                      <div v-for="(tc, ti) in lg.tool_calls" :key="ti" class="rounded-[8px] bg-[var(--c-bg)] border border-hairline p-1.5">
                        <div class="text-[11px] font-medium text-ink">{{ String((tc as Record<string, unknown>).tool ?? (tc as Record<string, unknown>).name ?? `工具${ti + 1}`) }}</div>
                        <n-code :code="pretty(tc)" language="json" class="text-[11px] mt-1" />
                      </div>
                    </div>
                  </div>
                  <div v-if="hasCitations(lg)" class="mt-1 rounded-[8px] bg-[var(--c-bg)] border border-hairline p-1.5">
                    <div class="text-[11px] tracking-widest text-muted">引用证据</div>
                    <div class="mt-1 text-[11px] text-muted break-all">{{ jsonStr(lg.citations) }}</div>
                  </div>
                </div>
                <div v-if="!wb.filteredLogs.length" class="text-[12px] text-muted text-center py-6">暂无日志，选择会话后加载</div>
              </div>
            </n-tab-pane>
            <n-tab-pane name="patch" tab="Patch">
              <div class="p-3 space-y-2">
                <div class="flex items-center justify-between">
                  <span class="text-[11px] text-muted">reflector patch</span>
                  <button class="text-[11px] text-muted hover:text-ink" @click="copyJson(wb.inspector.patch)">复制</button>
                </div>
                <n-code :code="pretty(wb.inspector.patch)" language="json" class="text-[11px]" />
                <div v-if="wb.weekLoadEntries.length" class="flex flex-wrap gap-1.5">
                  <span class="text-[11px] text-muted w-full">周负荷</span>
                  <span v-for="[k, v] in wb.weekLoadEntries" :key="k" class="text-[11px] px-2 py-0.5 rounded-full bg-[#ecfdf5] text-[#065f46] border border-[#a7f3d0]">{{ k }}: {{ v }}h</span>
                </div>
                <div v-if="wb.dailyLoadEntries.length" class="flex flex-wrap gap-1.5">
                  <span class="text-[11px] text-muted w-full">日负荷</span>
                  <span v-for="[k, v] in wb.dailyLoadEntries" :key="k" class="text-[11px] px-2 py-0.5 rounded-full bg-[#eff6ff] text-[#1e40af] border border-[#bfdbfe]">{{ k }}: {{ v }}h</span>
                </div>
                <div v-if="wb.reallocateInfo" class="text-[11px] text-muted">重分配：{{ wb.reallocateInfo }}</div>
                <div v-if="!Object.keys(wb.inspector.patch || {}).length" class="text-[11px] text-muted">暂无 patch（critic 通过）</div>
              </div>
            </n-tab-pane>
            <n-tab-pane name="tools" tab="工具">
              <div class="p-3 space-y-2">
                <div class="flex items-center justify-between">
                  <span class="text-[11px] text-muted">智能体工具清单{{ wb.manifest ? ` · ${wb.manifest.tools.length} 个 · v${wb.manifest.version}` : '' }}</span>
                  <button class="text-[11px] text-muted hover:text-ink" @click="copyJson(wb.manifest?.tools ?? [])">复制</button>
                </div>
                <div v-if="wb.manifest?.tools.length" class="space-y-1.5">
                  <div v-for="t in wb.manifest.tools" :key="t.name" class="rounded-[10px] bg-[var(--c-surface)] p-2">
                    <div class="text-[11px] font-medium text-ink">{{ t.label || t.name }}</div>
                    <div class="text-[11px] text-muted font-mono">{{ t.name }}</div>
                    <div v-if="t.description" class="mt-0.5 text-[11px] text-muted leading-4">{{ t.description }}</div>
                  </div>
                </div>
                <div v-else class="text-[12px] text-muted text-center py-6">暂无工具清单，正在加载…</div>
              </div>
            </n-tab-pane>
          </n-tabs>
        </div>
      </aside>
      <div v-else class="hidden xl:flex w-[36px] shrink-0 flex-col items-center rounded-[16px] bg-surface/60 border border-hairline py-2 gap-2">
        <button class="text-[11px] text-muted hover:text-ink" aria-label="展开 Inspector" @click="rightCollapsed = false">«</button>
        <div class="text-[11px] tracking-widest text-muted" style="writing-mode: vertical-rl">INSPECTOR</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount, watch, defineAsyncComponent } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NSelect, NTag, NTabs, NTabPane, NCode, useMessage } from 'naive-ui'
import { useWorkbenchStore } from '@/stores/workbench'
import { useSessionsStore, getSessionPill } from '@/stores/sessions'
import type { SessionPill } from '@/stores/sessions'
import { useAppStore } from '@/stores/app'
import { createPlan, waitForPendingApproval } from '@/api/plans'
import { listGoals, createGoal } from '@/api/goals'
import { extractErrorMessage } from '@/api/client'
import { fetchLlmModelOptions, getStoredModel, setStoredModel, FALLBACK_MODEL_OPTIONS } from '@/api/llm'
import { ingestRag } from '@/api/rag'
import GraphCanvas from '@/components/GraphCanvas.vue'
import TranscriptView from '@/components/TranscriptView.vue'
import ComposerMenu from '@/components/ComposerMenu.vue'
import type { WorkbenchGraphNode } from '@/api/plans'
import type { PlanSessionItem } from '@/api/plans'
import type { PlanLogItem } from '@/types'

defineOptions({ name: 'AgentWorkbenchView' })

const route = useRoute()
const router = useRouter()
const message = useMessage()
const wb = useWorkbenchStore()
const sessionsStore = useSessionsStore()
const appStore = useAppStore()

// MonitorPanel 由另一人并行新建：glob 缺失时返回空记录，不打包不报错，懒加载失败走空白占位
declare global {
  interface ImportMeta {
    glob: (pattern: string) => Record<string, () => Promise<any>>
  }
}
const MONITOR_GLOB_KEY = '../components/MonitorPanel.vue'
const monitorModules = import.meta.glob('../components/MonitorPanel.vue')
async function loadMonitorPanel(): Promise<any> {
  const loader = monitorModules[MONITOR_GLOB_KEY]
  if (!loader) return { template: '<div style="display:none"></div>' }
  try {
    const m = await loader()
    return (m as { default?: unknown }).default ?? m
  } catch {
    return { template: '<div style="display:none"></div>' }
  }
}
const MonitorPanel = defineAsyncComponent(loadMonitorPanel)

const rightCollapsed = ref(false)
const leftCollapsed = ref(false)
// 移动端三 Tab（会话/对话/监控）：纯布局显隐状态，不改业务逻辑，默认对话
const mobileTab = ref<'session' | 'chat' | 'monitor'>('chat')
const composer = ref('')
const selectedGoal = ref<number | null>(null)
const creating = ref(false)
const mode = ref<'single' | 'multi'>('multi')
// 模型选择：选项取 GET /llm/models 模型名，失败/空回退两档（自动/默认），持久化 workbench:model
const modelOpts = ref<Array<{ label: string; value: string }>>([...FALLBACK_MODEL_OPTIONS])
const selectedModel = ref<string>(getStoredModel())
// 写库审批：仅 multi 有效，开启后 POST 后台等待，需经待审批发现+流内审批卡批准
const needApproval = ref<boolean>( (() => { try { return localStorage.getItem('settings:require-approval') === '1' } catch { return false } })() )
// 每日时长偏好：优先读本地偏好，默认 2（保留原写死2的回退逻辑，见 resolveHours 注释）
const hours = ref(2)
const goalOpts = ref<Array<{ label: string; value: number }>>([])
const inputRef = ref<HTMLTextAreaElement | null>(null)
const expandedLogs = ref<Set<string>>(new Set())

// 左栏：搜索 / 分组 / 菜单 / 用户区
const searchQuery = ref('')
const openMenuId = ref<string | null>(null)
const showUserMenu = ref(false)
const userIdLabel = ref('U')
const viewMode = ref<'list' | 'kanban'>('list')
const exportOpen = ref(false)
const groupedSessions = computed(() => sessionsStore.groupSessions(searchQuery.value))
const kanbanGroups = computed(() => sessionsStore.kanbanGroups(searchQuery.value, sessionState))
const themeLabel = computed(() => appStore.theme === 'dark' ? '切换到浅色' : '切换到深色')

// B-Composer：斜杠命令 + 技能模板（纯前端常量）+ 附件
const attachedFiles = ref<string[]>([])
const uploading = ref(false)
const fileInputRef = ref<HTMLInputElement | null>(null)
const slashItems = [
  { key: 'cmd-plan', label: '/规划', desc: '发送当前输入走规划流程' },
  { key: 'cmd-review', label: '/复盘', desc: '跳反思页' },
  { key: 'cmd-pomo', label: '/番茄', desc: '跳日历' },
]
const skillItems = [
  { key: 'tpl-exam', label: '考试冲刺', desc: '填入冲刺模板' },
  { key: 'tpl-semester', label: '学期规划', desc: '填入学期模板' },
  { key: 'tpl-thesis', label: '论文写作', desc: '填入论文模板' },
]
const SKILL_TEXT: Record<string, string> = {
  'tpl-exam': '考试冲刺：目标【XX考试】，剩余【X天】，每天可学【X小时】，请拆解冲刺计划并安排每日任务',
  'tpl-semester': '学期规划：本学期目标【XX】，共【X周】，每周可学【X小时】，请生成阶段计划与周任务',
  'tpl-thesis': '论文写作：题目【XX】，要求【X字/查重】，截止【X天后】，请拆解写作大纲与每日进度',
}
const showSlashMenu = computed(() => composer.value.trimStart().startsWith('/'))

// 中央空态示例
const examplePrompts = [
  '30天过六级，每天2小时',
  '7天拿下数据结构链表与树，每天3小时',
  '14天完成毕业开题，每天2小时',
]

// Composer：@ 提及目标
const showMention = ref(false)
const mentionKeyword = ref('')
const filteredGoalOpts = computed(() => {
  const k = mentionKeyword.value.trim().toLowerCase()
  if (!k) return goalOpts.value.slice(0, 8)
  return goalOpts.value.filter((o) => o.label.toLowerCase().includes(k)).slice(0, 8)
})

// 右栏 MonitorPanel 接线：运行时或有待审批优先渲染
const pendingApprovalItem = computed(() =>
  wb.transcript.find((it) => it.kind === 'approval' && it.approval?.status === 'pending') ?? null,
)
const showMonitor = computed(() => wb.status === 'running' || wb.hasPendingApproval)
const monitorTasksPreview = computed(() =>
  pendingApprovalItem.value?.approval?.tasksPreview ?? pendingApprovalItem.value?.tasks ?? [],
)
const monitorApproveToken = computed(() => pendingApprovalItem.value?.approval?.approveToken ?? '')
const monitorExpiresIn = computed(() => pendingApprovalItem.value?.approval?.expiresIn ?? 0)
const monitorNodes = computed(() => wb.graph.nodes)
const monitorCitations = computed<unknown[]>(() => {
  const out: unknown[] = []
  for (const l of wb.inspector.logs) {
    const c = (l as unknown as { citations?: unknown }).citations
    if (!c) continue
    if (Array.isArray(c)) out.push(...c)
    else out.push(c)
  }
  return out.slice(0, 50)
})
const monitorCounts = computed(() => ({
  transcript: wb.transcript.length,
  logs: wb.inspector.logs.length,
  tasks: monitorTasksPreview.value.length,
  events: wb.lastEventId || '0',
}))

const agentFilterOpts = computed(() => [
  { label: '全部智能体', value: '' },
  ...wb.agentNameOptions.map((n) => ({ label: n, value: n })),
])

// 用量显示：取最后一条 done，不动 TranscriptView.vue，仅在本视图 footer 展示 + 复制全文携带
const lastDoneItem = computed(() => {
  for (let i = wb.transcript.length - 1; i >= 0; i--) {
    const it = wb.transcript[i]
    if (it && it.kind === 'done') return it
  }
  return null
})
const lastUsageText = computed(() => {
  const d = lastDoneItem.value
  if (!d) return ''
  if (d.text && d.text.includes('估算')) return d.text
  const hasElapsed = typeof d.elapsedMs === 'number'
  const hasTokens = typeof d.tokensEstimate === 'number'
  if (hasElapsed && hasTokens) return `耗时 ${((d.elapsedMs as number) / 1000).toFixed(1)} 秒 · 约 ${d.tokensEstimate} tokens（估算）`
  if (hasElapsed) return `耗时 ${((d.elapsedMs as number) / 1000).toFixed(1)} 秒`
  return ''
})

async function loadModelOpts() {
  try {
    const opts = await fetchLlmModelOptions()
    if (opts.length) {
      modelOpts.value = opts
      if (!opts.some((o) => o.value === selectedModel.value)) {
        selectedModel.value = opts[0]?.value ?? 'auto'
        setStoredModel(selectedModel.value)
      }
    }
  } catch {}
}

function resolveHours(): number {
  // 自由文本启发式 hours：原写死2保留为回退，优先读本地偏好 workbench:hours_per_day（1-8）
  try {
    const raw = localStorage.getItem('workbench:hours_per_day')
    if (raw) {
      const n = Number(raw)
      if (Number.isFinite(n) && n >= 1 && n <= 8) return Math.floor(n)
    }
  } catch {}
  const h = Math.floor(Number(hours.value) || 2)
  if (Number.isFinite(h) && h >= 1 && h <= 8) return h
  return 2
}

function sessionState(s: PlanSessionItem): SessionPill {
  return getSessionPill(s, { traceId: wb.traceId, hasPendingApproval: wb.hasPendingApproval })
}

function pillLabel(p: SessionPill): string {
  if (p === 'pending') return '待审批'
  if (p === 'completed') return '已完成'
  if (p === 'failed') return '失败'
  return '进行中'
}

function pillClass(p: SessionPill): string {
  if (p === 'pending') return 'bg-[#fffbeb] text-[#92400e] border-[#fde68a]'
  if (p === 'completed') return 'bg-[#ecfdf5] text-[#065f46] border-[#a7f3d0]'
  if (p === 'failed') return 'bg-[#fef2f2] text-[#991b1b] border-[#fecaca]'
  return 'bg-[#eff6ff] text-[#1e40af] border-[#bfdbfe]'
}

function sessionDisplay(s: PlanSessionItem): string {
  return sessionsStore.displayName(s.trace_id, s.goal_title)
}

function toggleMenu(id: string) {
  openMenuId.value = openMenuId.value === id ? null : id
}

function pinSession(s: PlanSessionItem) {
  sessionsStore.togglePin(s.trace_id)
  openMenuId.value = null
}

function renameSession(s: PlanSessionItem) {
  openMenuId.value = null
  const cur = sessionsStore.displayName(s.trace_id, s.goal_title)
  const v = window.prompt('重命名任务', cur)
  if (v == null) return
  const name = v.trim().slice(0, 60)
  if (!name) return
  sessionsStore.setName(s.trace_id, name)
}

function deleteSession(s: PlanSessionItem) {
  openMenuId.value = null
  const isCurrent = wb.traceId === s.trace_id
  // 仅清本地 pin/name 记录与本地展示，不删后端数据
  sessionsStore.removeTrace(s.trace_id)
  if (isCurrent) newSession()
}

function refreshUser(): void {
  try {
    const uid = localStorage.getItem('user_id') ?? ''
    userIdLabel.value = uid ? uid.slice(0, 1).toUpperCase() : 'U'
  } catch {}
}

function handleLogout(): void {
  try { localStorage.removeItem('token'); localStorage.removeItem('user_id') } catch {}
  showUserMenu.value = false
  refreshUser()
  void router.push('/login')
}

function handleToggleTheme(): void {
  appStore.toggleTheme()
  showUserMenu.value = false
}

function goSettings(): void {
  showUserMenu.value = false
  void router.push('/settings')
}

function fillExample(p: string) {
  composer.value = p
  try { inputRef.value?.focus() } catch {}
}

function onComposerInput() {
  const m = composer.value.match(/@([^\s@#]*)$/)
  if (m) {
    showMention.value = true
    mentionKeyword.value = m[1] ?? ''
  } else {
    showMention.value = false
  }
}

function selectMention(opt: { label: string; value: number }) {
  const title = opt.label.replace(/^#\d+\s*/, '')
  composer.value = composer.value.replace(/@([^\s@#]*)$/, `#${opt.value} ${title} `)
  selectedGoal.value = opt.value
  showMention.value = false
  requestAnimationFrame(() => { try { inputRef.value?.focus() } catch {} })
}

function stripSlashPrefix(v: string): string {
  return v.replace(/^\s*\/\S*\s*/, '')
}

async function onComposerMenuSelect(key: string): Promise<void> {
  if (key === 'cmd-plan') {
    const rest = stripSlashPrefix(composer.value)
    composer.value = rest
    if (!rest.trim()) {
      try { inputRef.value?.focus() } catch {}
      return
    }
    await send()
    return
  }
  if (key === 'cmd-review') {
    composer.value = stripSlashPrefix(composer.value)
    void router.push('/reflection')
    return
  }
  if (key === 'cmd-pomo') {
    composer.value = stripSlashPrefix(composer.value)
    void router.push('/calendar')
    return
  }
  const tpl = SKILL_TEXT[key]
  if (tpl) {
    composer.value = tpl
    try { inputRef.value?.focus() } catch {}
  }
}

function onComposerEscape(): void {
  showMention.value = false
  exportOpen.value = false
}

function pickFile(): void {
  try { fileInputRef.value?.click() } catch {}
}

function removeAttach(idx: number): void {
  attachedFiles.value = attachedFiles.value.filter((_, i) => i !== idx)
}

async function onFileChange(e: Event): Promise<void> {
  const input = e.target as HTMLInputElement | null
  const file = input?.files?.[0]
  if (input) input.value = ''
  if (!file) return
  uploading.value = true
  try {
    await ingestRag(file)
    if (!attachedFiles.value.includes(file.name)) attachedFiles.value = [...attachedFiles.value, file.name].slice(0, 5)
    message.success(`已关联知识：${file.name}`)
    try { inputRef.value?.focus() } catch {}
  } catch (err: unknown) {
    message.error(extractErrorMessage(err))
  } finally {
    uploading.value = false
  }
}

function onMonitorResolved(): void {
  try { wb.resyncDelayed(4000) } catch {}
}

function modeClass(m: PlanSessionItem['mode']): string {
  return m === 'multi' ? 'bg-[var(--c-bg)] text-ink border-hairline' : 'bg-[var(--c-surface)] text-muted border-hairline'
}

function nodeClass(status: string): string {
  if (status === 'success') return 'bg-[#ecfdf5] text-[#065f46] border-[#a7f3d0]'
  if (status === 'running') return 'bg-[#fffbeb] text-[#92400e] border-[#fde68a]'
  if (status === 'error') return 'bg-[#fef2f2] text-[#991b1b] border-[#fecaca]'
  return 'bg-[#f5f5f7] text-muted border-[#e8e8ed]'
}

function relativeTime(v: string | null): string {
  if (!v) return '—'
  try {
    const t = new Date(v).getTime()
    if (Number.isNaN(t)) return v.slice(0, 10)
    const diff = Date.now() - t
    const m = Math.floor(diff / 60000)
    if (m < 1) return '刚刚'
    if (m < 60) return `${m} 分钟前`
    const h = Math.floor(m / 60)
    if (h < 24) return `${h} 小时前`
    const d = Math.floor(h / 24)
    if (d < 30) return `${d} 天前`
    return new Date(t).toLocaleDateString()
  } catch { return v.slice(0, 10) }
}

function pretty(v: unknown) {
  try { return JSON.stringify(v, null, 2) } catch { return String(v) }
}

function jsonStr(v: unknown) {
  try {
    const s = JSON.stringify(v)
    if (s == null) return '—'
    return s.length > 160 ? s.slice(0, 160) + '…' : s
  } catch { return String(v) }
}

function hasCitations(lg: PlanLogItem): boolean {
  const c = lg.citations
  if (!c) return false
  if (Array.isArray(c)) return c.length > 0
  return Object.keys(c).length > 0
}

function logKey(lg: PlanLogItem): string {
  return String(lg.id ?? `${lg.agent_name}-${lg.created_at}`)
}

function isLogExpanded(k: string): boolean {
  return expandedLogs.value.has(k)
}

function toggleLog(k: string) {
  const next = new Set(expandedLogs.value)
  if (next.has(k)) next.delete(k)
  else next.add(k)
  expandedLogs.value = next
}

function copyJson(v: unknown) {
  try { navigator.clipboard.writeText(JSON.stringify(v, null, 2)); message.success('已复制') } catch { message.warning('复制失败') }
}

function copyAllLogs() {
  try {
    navigator.clipboard.writeText(JSON.stringify(wb.filteredLogs, null, 2))
    message.success(`已复制 ${wb.filteredLogs.length} 条日志`)
  } catch { message.warning('复制失败') }
}

function buildTranscriptMarkdown(): string {
  const lines = wb.transcript.map((it) => {
    if (it.kind === 'user') return `[用户] ${it.text ?? ''}`
    if (it.kind === 'thought') return `[${it.agent ?? '思考'}] ${it.text ?? ''}`
    if (it.kind === 'tool') return `[工具] ${(it.tools ?? []).map((t) => t.tool).join(',')}`
    if (it.kind === 'plan') return `[计划] ${(it.tasks ?? []).map((t) => t.title).join('；')}`
    if (it.kind === 'critic') return `[Critic] ${it.feedback ?? ''}`
    if (it.kind === 'mentor') return `[Mentor] ${it.text ?? ''}`
    if (it.kind === 'reflector') return `[Reflector] ${JSON.stringify(it.patch ?? {})}`
    if (it.kind === 'approval') return `[审批] ${(it.approval?.tasksPreview ?? []).map((t) => t.title).join('；')}`
    if (it.kind === 'done') {
      if (it.text && it.text.includes('估算')) return `[完成] ${it.count ?? 0} 任务 · ${it.text}`
      const sec = typeof it.elapsedMs === 'number' ? `耗时 ${((it.elapsedMs as number) / 1000).toFixed(1)} 秒` : ''
      const tok = typeof it.tokensEstimate === 'number' ? `约 ${it.tokensEstimate} tokens（估算）` : ''
      const extra = [sec, tok].filter(Boolean).join(' · ')
      return extra ? `[完成] ${it.count ?? 0} 任务 · ${extra}` : `[完成] ${it.count ?? 0} 任务`
    }
    if (it.kind === 'compact') return `[压缩] ${it.count ?? 0} 条`
    return `[${it.kind}] ${it.text ?? ''}`
  })
  return lines.join('\n')
}

function copyFullTranscript() {
  try {
    void navigator.clipboard.writeText(buildTranscriptMarkdown())
    message.success('已复制全文')
  } catch { message.warning('复制失败') }
}

function onExportMarkdown(): void {
  exportOpen.value = false
  copyFullTranscript()
}

function onDownloadMarkdown(): void {
  exportOpen.value = false
  try {
    const blob = new Blob([buildTranscriptMarkdown()], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const d = new Date()
    const pad = (n: number) => String(n).padStart(2, '0')
    const stamp = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`
    const short = wb.traceId ? wb.traceId.slice(0, 8) : 'new'
    const a = document.createElement('a')
    a.href = url
    a.download = `workbench-${short}-${stamp}.md`
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    message.success('已导出 .md')
  } catch { message.warning('导出失败') }
}

function onCopyTraceId(): void {
  exportOpen.value = false
  try {
    if (!wb.traceId) {
      message.warning('暂无 trace_id')
      return
    }
    void navigator.clipboard.writeText(wb.traceId)
    message.success('已复制 trace_id')
  } catch { message.warning('复制失败') }
}

async function onResend(text: string): Promise<void> {
  const t = (text ?? '').trim()
  if (!t) return
  if (wb.status === 'running' || creating.value) {
    message.warning('运行中，稍后再试')
    return
  }
  wb.setTraceId('')
  composer.value = t.slice(0, 2000)
  selectedGoal.value = null
  showMention.value = false
  await send()
}

function onSelectNode(node: WorkbenchGraphNode) {
  wb.selectNode(node)
}

function onTranscriptSelect(agentId: string) {
  wb.selectNodeById(agentId)
}

function handleStop() {
  wb.unsubscribe()
  message.info('已停止')
}

function handleRetry() {
  if (!wb.traceId) {
    message.warning('暂无会话可重试')
    return
  }
  wb.subscribe()
  void wb.fetchGraph()
  void wb.fetchInspector()
}

function newSession() {
  wb.setTraceId('')
  composer.value = ''
  selectedGoal.value = null
  showMention.value = false
  openMenuId.value = null
  exportOpen.value = false
  attachedFiles.value = []
  inputRef.value?.focus()
}

// 桌面端命令（App.vue 经 window 转交 electronBridge.onAgentCommand）
function onAgentCommand(e: Event): void {
  const cmd = (e as CustomEvent<string>).detail
  if (cmd === 'agent:new-session') newSession()
  else if (cmd === 'agent:focus-composer') {
    if (route.path !== '/agent') void router.push('/agent')
    requestAnimationFrame(() => { try { inputRef.value?.focus() } catch {} })
  } else if (cmd === 'agent:toggle-inspector') rightCollapsed.value = !rightCollapsed.value
  else if (cmd === 'show-shortcuts') showShortcutsHint()
}
function showShortcutsHint(): void {
  try { window.dispatchEvent(new KeyboardEvent('keydown', { key: '?' })) } catch {}
}

function replayTrace(trace: string) {
  wb.setTraceId(trace)
  wb.subscribe()
  void wb.fetchGraph()
  void wb.fetchInspector()
}

function replaySession(s: PlanSessionItem) {
  if (!s.trace_id) return
  openMenuId.value = null
  replayTrace(s.trace_id)
}

// key=r.path 后同页切 ?trace= 不重挂，监听补回放（与 onMounted 初次逻辑一致）
watch(() => route.query.trace, (v) => {
  if (typeof v === 'string' && v && v !== wb.traceId) replayTrace(v)
})

function prevPage() {
  if (sessionsStore.page > 1) void sessionsStore.fetchPage(sessionsStore.page - 1)
}

function loadMore() {
  void sessionsStore.loadMore()
}

async function loadGoalOpts() {
  try {
    const res = await listGoals({ page: 1, size: 20 })
    goalOpts.value = res.data.items.map((g) => ({ label: `#${g.id} ${g.title}`, value: g.id }))
  } catch {}
}

async function send() {
  const text = composer.value.trim()
  if (!text || creating.value) return
  if (wb.status === 'running') return
  if (text.length > 2000) {
    message.warning('输入需 1-2000 字')
    return
  }
  const attached = [...attachedFiles.value]
  const attachSuffix = attached.length ? `\n【关联知识：${attached.join('、')}】` : ''
  const sendText = text + attachSuffix
  creating.value = true
  try {
    let gid = selectedGoal.value
    // @提及解析：#id 优先为 selectedGoal，自由文本建 Goal 保留为回退
    if (gid == null) {
      const m = text.match(/#(\d+)/)
      if (m) {
        const id = Number(m[1])
        if (Number.isFinite(id) && id > 0) {
          gid = id
          selectedGoal.value = id
        }
      }
    }
    const display = goalOpts.value.find((o) => o.value === gid)?.label?.replace(/^#\d+\s*/, '') || sendText.slice(0, 30)
    if (gid == null) {
      const daysMatch = text.match(/(\d+)\s*天/)
      const days = daysMatch ? Number(daysMatch[1]) : 7
      const subject = text.includes('英语') ? '英语' : text.includes('数据结构') ? '数据结构' : undefined
      const deadline = new Date(Date.now() + days * 86400000).toISOString()
      const g = await createGoal({ title: text.slice(0, 30), description: sendText, deadline, subject, status: 'active' })
      gid = g.data.id
    }
    wb.pushUser(display)
    composer.value = ''
    showMention.value = false
    attachedFiles.value = []
    // 模型透传：并入 preferences（后端忽略未知字段无风险），与 createPlan 现有签名自洽
    const prefsWithModel = { hours_per_day: resolveHours(), model: selectedModel.value } as unknown as { hours_per_day: number }
    // 审批流：POST 会阻塞等审批，后台 fire 后经待审批发现拿 trace 再订阅流
    if (needApproval.value && mode.value === 'multi') {
      const bg = createPlan(gid, prefsWithModel, 'multi', true)
      bg.then(() => {
        void wb.fetchGraph()
        void wb.fetchInspector()
        void sessionsStore.refresh()
      }).catch((e: unknown) => {
        message.error(extractErrorMessage(e))
      }).finally(() => {
        creating.value = false
      })
      message.info('审批模式：等待任务生成，稍后在审批卡确认')
      const tid = await waitForPendingApproval(gid, 120000)
      if (!tid) {
        message.warning('未发现待审批会话，请稍后在会话列表重放')
        return
      }
      wb.setTraceId(tid)
      wb.subscribe()
      void wb.fetchGraph()
      void loadGoalOpts()
      return
    }
    const plan = await createPlan(gid, prefsWithModel, mode.value)
    wb.setTraceId(plan.data.trace_id)
    wb.subscribe()
    void wb.fetchGraph()
    void loadGoalOpts()
  } catch (e: unknown) {
    message.error(extractErrorMessage(e))
  } finally {
    creating.value = false
  }
}

watch(() => wb.status, (s) => {
  if (s === 'completed' || s === 'failed') void sessionsStore.refresh()
})

onBeforeUnmount(() => {
  try { window.removeEventListener('agent:command', onAgentCommand) } catch {}
})

watch(hours, (h) => {
  try {
    if (Number.isFinite(h) && h >= 1 && h <= 8) localStorage.setItem('workbench:hours_per_day', String(Math.floor(h)))
  } catch {}
})

watch(selectedModel, (v) => {
  setStoredModel(v)
})

onMounted(() => {
  try {
    selectedModel.value = getStoredModel()
  } catch {}
  void loadModelOpts()
  try {
    const raw = localStorage.getItem('workbench:hours_per_day')
    if (raw) {
      const n = Number(raw)
      if (Number.isFinite(n) && n >= 1 && n <= 8) hours.value = Math.floor(n)
    }
  } catch {}
  refreshUser()
  void sessionsStore.fetchPage(1)
  void loadGoalOpts()
  // 桌面端命令监听（App.vue 转交）
  window.addEventListener('agent:command', onAgentCommand)
  // 接线死代码：manifest 小工具清单需数据，挂载即拉取
  void wb.fetchManifest()
  const qTrace = route.query.trace
  if (typeof qTrace === 'string' && qTrace) replayTrace(qTrace)
  try {
    const raw = sessionStorage.getItem('agent:prefill')
    if (raw) {
      const p = JSON.parse(raw) as { text?: unknown; goal_id?: unknown; source?: unknown; mode?: unknown; hours?: unknown }
      // 仅接受 dashboard 来源，校验 mode/hours 合法性
      if (p.source !== 'dashboard') {
        sessionStorage.removeItem('agent:prefill')
      } else {
        if (typeof p.text === 'string' && p.text) composer.value = p.text.slice(0, 2000)
        if (typeof p.goal_id === 'number' && Number.isFinite(p.goal_id)) selectedGoal.value = p.goal_id
        if (p.mode === 'single' || p.mode === 'multi') mode.value = p.mode
        if (typeof p.hours === 'number' && Number.isFinite(p.hours) && p.hours >= 1 && p.hours <= 8) hours.value = Math.floor(p.hours)
        sessionStorage.removeItem('agent:prefill')
      }
    }
  } catch {}
})
</script>

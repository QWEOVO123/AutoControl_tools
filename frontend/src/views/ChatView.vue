<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Send,
  Square,
  PanelRight,
  X,
  Terminal,
  FolderSearch,
  FileCode2,
  Sparkles,
  Wrench,
  CircleHelp,
  LoaderCircle,
  Paperclip,
  FileText,
  Globe,
  Braces,
} from '@lucide/vue'
import { useChat } from '../stores/chat'
import { useAuth } from '../stores/auth'
import ChatMessage from '../components/ChatMessage.vue'
import ToolCard from '../components/ToolCard.vue'
import type { OutputMode, ReasoningEffort } from '../types'

const chat = useChat(),
  auth = useAuth(),
  route = useRoute(),
  router = useRouter()
const id = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const messages = computed(() => chat.messages[id.value] ?? [])
const conversation = computed(() => chat.conversations.find((item) => item.id === id.value))
const traces = computed(() => messages.value.flatMap((message) => message.tool_events))
const running = computed(() => chat.streamingId === id.value || chat.remoteRunning[id.value])
const reasoningEffort = ref<ReasoningEffort>('none')
const outputMode = ref<OutputMode>('text')
const draft = ref(''),
  error = ref(''),
  loading = ref(false),
  inspector = ref(window.matchMedia('(min-width: 1180px)').matches),
  help = ref(false)
const scrolling = ref<HTMLElement>(),
  composer = ref<HTMLTextAreaElement>(),
  follow = ref(true)
const selectedFiles = ref<File[]>([])
const fileInput = ref<HTMLInputElement>()
const richLayout = ref(false)
const uploading = ref(false)
const supportedFiles =
  '.png,.jpg,.jpeg,.gif,.webp,.pdf,.doc,.docx,.ppt,.pptx,.txt,.md,.log,.csv,.json,.yaml,.yml,.xls,.xlsx'
const showLayoutOption = computed(() =>
  selectedFiles.value.some((file) => /\.(pdf|docx?|pptx?)$/i.test(file.name)),
)
const attachmentsAvailable = computed(() => !chat.system || chat.system.model === 'deepseek-flash')
const workspaceName = computed(
  () => chat.system?.workspace.split(/[\\/]/).filter(Boolean).pop() ?? '本地工作区',
)
const canSend = computed(
  () =>
    Boolean(draft.value.trim() || selectedFiles.value.length) &&
    !running.value &&
    !chat.streamingId &&
    !loading.value &&
    !uploading.value,
)
const suggestions = [
  {
    icon: FolderSearch,
    title: '探索项目',
    subtitle: '快速找到关键文件与调用关系',
    text: '查看当前项目的目录结构，找出程序入口并说明主要调用流程。',
  },
  {
    icon: FileCode2,
    title: '审查代码',
    subtitle: '定位问题，给出具体改进建议',
    text: '检查当前项目的代码和依赖，找出最值得优先修复的问题。先分析，不修改。',
  },
  {
    icon: Terminal,
    title: '执行检查',
    subtitle: '运行命令，验证项目状态',
    text: '在当前项目目录运行 uv pip check，并解释检查结果。',
  },
  {
    icon: Globe,
    title: '查官方文档',
    subtitle: '搜索上游资料并附来源链接',
    text: '查阅当前项目主要依赖的官方文档，核对当前用法并给出来源链接。',
  },
]
watch(
  id,
  async (value) => {
    error.value = ''
    draft.value = ''
    selectedFiles.value = []
    richLayout.value = false
    follow.value = true
    if (!value) return
    loading.value = true
    try {
      await chat.load(value)
    } catch (e) {
      error.value = e instanceof Error ? e.message : '读取会话失败'
    } finally {
      loading.value = false
    }
  },
  { immediate: true },
)
watch(
  () =>
    messages.value
      .map(
        (message) =>
          `${message.content.length}:${message.reasoning?.length ?? 0}:${message.status}:${message.tool_events.length}`,
      )
      .join(''),
  async () => {
    if (follow.value) {
      await nextTick()
      scrolling.value?.scrollTo({ top: scrolling.value.scrollHeight, behavior: 'instant' })
    }
  },
)
function trackScroll() {
  const el = scrolling.value
  if (el) follow.value = el.scrollHeight - el.scrollTop - el.clientHeight < 90
}
function suggest(text: string) {
  draft.value = text
  composer.value?.focus()
}
function addFiles(files: File[]) {
  if (!attachmentsAvailable.value || uploading.value) return
  error.value = ''
  for (const file of files) {
    if (selectedFiles.value.length >= 4) {
      error.value = '每条消息最多添加 4 个附件。'
      break
    }
    const extension = file.name.slice(file.name.lastIndexOf('.')).toLowerCase()
    if (
      !supportedFiles.split(',').includes(extension) ||
      !file.size ||
      file.size > 12 * 1024 * 1024
    ) {
      error.value = `无法添加 ${file.name}。请选择支持的格式，单个文件最多 12 MiB。`
    } else {
      selectedFiles.value.push(file)
    }
  }
}
function chooseFiles(event: Event) {
  const input = event.target as HTMLInputElement
  addFiles(Array.from(input.files ?? []))
  input.value = ''
}
function pasteFiles(event: ClipboardEvent) {
  const files = Array.from(event.clipboardData?.files ?? [])
  if (files.length && attachmentsAvailable.value && !uploading.value) {
    event.preventDefault()
    addFiles(files)
  }
}
async function submit() {
  const text = draft.value.trim()
  const effort = reasoningEffort.value
  const format = outputMode.value
  const files = [...selectedFiles.value]
  const rich = richLayout.value
  if (!canSend.value) return
  error.value = ''
  follow.value = true
  uploading.value = true
  let target = id.value
  try {
    if (!target) {
      const item = await chat.create()
      target = item.id
      await router.replace(`/chat/${target}`)
    }
    const attachments = files.length ? await chat.uploadAttachments(target, files, rich) : []
    if (id.value !== target) {
      await chat.discardAttachments(target, attachments)
      return
    }
    draft.value = ''
    selectedFiles.value = []
    uploading.value = false
    await chat.send(target, text, effort, attachments, format)
  } catch (e) {
    if (id.value === target) {
      if (!draft.value) draft.value = text
      if (!selectedFiles.value.length) selectedFiles.value = files
      richLayout.value = rich
      error.value = e instanceof Error ? e.message : '执行失败'
    }
  } finally {
    uploading.value = false
  }
}
async function stop() {
  try {
    await chat.stop(id.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '停止失败'
  }
}
function keydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault()
    void submit()
  }
}
</script>

<template>
  <div class="chat-page">
    <header class="page-header">
      <div class="header-breadcrumb">
        <span>工作空间</span><span class="breadcrumb-slash">/</span
        ><strong>{{ conversation?.title ?? '新会话' }}</strong>
      </div>
      <div class="header-actions">
        <span class="model-pill"><Sparkles :size="14" />{{ chat.system?.model ?? 'Agent' }}</span
        ><button
          class="icon-button"
          :class="{ pressed: inspector }"
          aria-label="切换工具执行面板"
          @click="inspector = !inspector"
        >
          <PanelRight :size="19" />
        </button>
      </div>
    </header>
    <div class="chat-workspace">
      <section class="chat-column">
        <div ref="scrolling" class="message-scroll" @scroll="trackScroll">
          <div v-if="!messages.length && !loading" class="welcome">
            <div class="workspace-path">
              <Terminal :size="16" /> <span>~ / {{ workspaceName }}</span>
            </div>
            <h1>Agent 工作台</h1>
            <p>检查项目、排查故障，或添加截图和日志一起分析。</p>
            <div class="suggestion-grid">
              <button
                v-for="item in suggestions"
                :key="item.title"
                class="suggestion-card"
                @click="suggest(item.text)"
              >
                <component :is="item.icon" :size="21" /><strong>{{ item.title }}</strong
                ><span>{{ item.subtitle }}</span>
              </button>
            </div>
          </div>
          <div v-else-if="loading" class="page-loading">
            <LoaderCircle class="spin" :size="22" />正在读取会话…
          </div>
          <div v-else class="message-list">
            <ChatMessage
              v-for="message in messages"
              :key="message.id"
              :message="message"
              :conversation-id="id"
              :username="auth.user?.username ?? 'U'"
              @inspect="inspector = true"
            />
          </div>
        </div>
        <div class="composer-area">
          <div v-if="error" class="error-banner" role="alert">
            {{ error
            }}<button class="icon-button" aria-label="关闭错误" @click="error = ''">
              <X :size="15" />
            </button>
          </div>
          <div v-if="chat.remoteRunning[id] && chat.streamingId !== id" class="info-banner">
            此会话有任务正在执行。<button @click="stop">停止生成</button>
          </div>
          <div v-if="chat.system && !chat.system.model_configured" class="info-banner">
            模型尚未配置，请在后端环境中设置 DEEPSEEK_API_KEY 后重启。
          </div>
          <form class="composer" @submit.prevent="submit">
            <div v-if="selectedFiles.length" class="composer-attachments">
              <div
                v-for="(file, index) in selectedFiles"
                :key="`${file.name}-${index}`"
                class="attachment-chip"
              >
                <FileText :size="15" /><span>{{ file.name }}</span>
                <button
                  type="button"
                  :aria-label="`移除 ${file.name}`"
                  :disabled="uploading"
                  @click="selectedFiles.splice(index, 1)"
                >
                  <X :size="14" />
                </button>
              </div>
              <label v-if="showLayoutOption" class="layout-option">
                <input v-model="richLayout" type="checkbox" :disabled="uploading" />
                解析文档中的图表
              </label>
              <span class="upload-status">发送后由 DeepSeek 处理</span>
            </div>
            <textarea
              ref="composer"
              v-model="draft"
              aria-label="发送给 Agent 的消息"
              placeholder="描述你想完成的事，或问一个关于项目的问题…"
              rows="3"
              maxlength="8000"
              @keydown="keydown"
              @paste="pasteFiles"
            />
            <div class="composer-footer">
              <div class="composer-left">
                <input
                  ref="fileInput"
                  type="file"
                  multiple
                  hidden
                  :accept="supportedFiles"
                  @change="chooseFiles"
                />
                <button
                  type="button"
                  class="icon-button attachment-button"
                  aria-label="添加图片或文件"
                  title="添加图片或文件，也可以粘贴截图"
                  :disabled="!attachmentsAvailable || uploading"
                  @click="fileInput?.click()"
                >
                  <Paperclip :size="17" />
                </button>
                <button
                  type="button"
                  class="icon-button format-button"
                  :class="{ pressed: outputMode === 'json' }"
                  :aria-pressed="outputMode === 'json'"
                  aria-label="JSON 输出"
                  title="JSON 输出"
                  @click="outputMode = outputMode === 'text' ? 'json' : 'text'"
                >
                  <Braces :size="17" />
                </button>
                <span class="composer-context"
                  ><Terminal :size="14" /><span>{{ workspaceName }}</span></span
                >
                <span v-if="uploading" class="upload-status" role="status">正在上传…</span>
              </div>
              <div class="composer-controls">
                <label class="effort-picker">
                  <span>思考强度</span>
                  <select v-model="reasoningEffort">
                    <option value="none">关闭</option>
                    <option value="low">低</option>
                    <option value="high">高</option>
                    <option value="max">最高</option>
                  </select>
                </label>
                <span class="keyboard-hint">Enter 发送 · Shift + Enter 换行</span
                ><button
                  v-if="running"
                  type="button"
                  class="send-button stop-button"
                  aria-label="停止生成"
                  @click="stop"
                >
                  <Square :size="15" fill="currentColor" /></button
                ><button
                  v-else
                  type="submit"
                  class="send-button"
                  aria-label="发送消息"
                  :disabled="!canSend"
                >
                  <Send :size="19" />
                </button>
              </div>
            </div>
          </form>
          <div class="composer-disclaimer">
            <span>Agent 可以操作本机文件和命令，请明确任务范围。</span
            ><button class="subtle-button" aria-label="查看使用说明" @click="help = !help">
              <CircleHelp :size="14" />
            </button>
          </div>
          <p v-if="help" class="help-note">
            工具记录可在右侧面板查看。停止生成会取消 Agent
            后续步骤，已启动的同步工具可能运行到自身超时。当前未启用管理员提权。
          </p>
        </div>
      </section>
      <aside v-if="inspector" class="inspector">
        <div class="inspector-heading">
          <div>
            <Wrench :size="17" /><strong>执行记录</strong><span>{{ traces.length }}</span>
          </div>
          <button class="icon-button" aria-label="关闭执行面板" @click="inspector = false">
            <X :size="18" />
          </button>
        </div>
        <div v-if="!traces.length" class="inspector-empty">
          <Terminal :size="25" /><strong>等待工具调用</strong>
          <p>这里显示命令输出、任务状态和网页来源。</p>
        </div>
        <div v-else class="tool-list">
          <ToolCard v-for="tool in traces" :key="tool.id" :tool="tool" />
        </div>
      </aside>
    </div>
  </div>
</template>

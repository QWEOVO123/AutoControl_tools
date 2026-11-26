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
  Cpu,
  CircleHelp,
  LoaderCircle,
} from '@lucide/vue'
import { useChat } from '../stores/chat'
import { useAuth } from '../stores/auth'
import ChatMessage from '../components/ChatMessage.vue'
import ToolCard from '../components/ToolCard.vue'

const chat = useChat(),
  auth = useAuth(),
  route = useRoute(),
  router = useRouter()
const id = computed(() => (typeof route.params.id === 'string' ? route.params.id : ''))
const messages = computed(() => chat.messages[id.value] ?? [])
const conversation = computed(() => chat.conversations.find((item) => item.id === id.value))
const traces = computed(() => messages.value.flatMap((message) => message.tool_events))
const running = computed(() => chat.streamingId === id.value || chat.remoteRunning[id.value])
const draft = ref(''),
  error = ref(''),
  loading = ref(false),
  inspector = ref(false),
  help = ref(false)
const scrolling = ref<HTMLElement>(),
  composer = ref<HTMLTextAreaElement>(),
  follow = ref(true)
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
    icon: Cpu,
    title: '了解环境',
    subtitle: '查看系统、解释器与当前目录',
    text: '查看当前运行环境，包括操作系统、Python 解释器和工作目录。',
  },
]
watch(
  id,
  async (value) => {
    error.value = ''
    draft.value = ''
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
      .map((message) => `${message.content}:${message.status}:${message.tool_events.length}`)
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
async function submit() {
  const text = draft.value.trim()
  if (!text || chat.streamingId || loading.value) return
  error.value = ''
  follow.value = true
  try {
    let target = id.value
    if (!target) {
      const item = await chat.create()
      target = item.id
      await router.replace(`/chat/${target}`)
    }
    draft.value = ''
    await chat.send(target, text)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '执行失败'
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
            <div class="welcome-symbol"><Sparkles :size="29" /></div>
            <div class="eyebrow">A LITTLE CONTEXT. A LOT OF POSSIBILITY.</div>
            <h1>让想法落到代码里。</h1>
            <p>读懂文件，调用工具，推进你的下一步。<br />从一个问题，或一件想完成的事开始。</p>
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
            <div class="welcome-capabilities">
              <span><Wrench :size="14" />{{ chat.system?.tools.length ?? '—' }} 个本地工具</span
              ><span><Terminal :size="14" />本地执行</span><span>HTTP · SSE</span>
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
            <textarea
              ref="composer"
              v-model="draft"
              aria-label="发送给 Agent 的消息"
              placeholder="描述你想完成的事，或问一个关于项目的问题…"
              rows="3"
              maxlength="8000"
              @keydown="keydown"
            />
            <div class="composer-footer">
              <span class="composer-context"
                ><Terminal :size="14" /><span>{{
                  chat.system?.workspace.split(/[\\/]/).filter(Boolean).pop() ?? '本地工作区'
                }}</span></span
              >
              <div class="composer-controls">
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
                  :disabled="!draft.trim() || !!chat.streamingId || loading"
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
        <p class="inspector-description">跟随 Agent 的每一次工具调用。</p>
        <div v-if="!traces.length" class="inspector-empty">
          <Terminal :size="30" /><strong>执行过程会出现在这里</strong>
          <p>发送任务后，查看工具参数、运行状态和返回结果。</p>
        </div>
        <div v-else class="tool-list">
          <ToolCard v-for="tool in traces" :key="tool.id" :tool="tool" />
        </div>
        <div class="inspector-footer"><span class="tiny-square" />工具输出与模型回答分开展示</div>
      </aside>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { AudioLines, Copy, FileText, LoaderCircle, ScanText } from '@lucide/vue'
import { api } from '../api/client'
import { useAuth } from '../stores/auth'

interface Page {
  index: number
  text: string
  truncated: boolean
}
const auth = useAuth()
const mode = ref<'ocr' | 'transcribe'>('ocr')
const file = ref<File>()
const picker = ref<HTMLInputElement>()
const layout = ref(false)
const busy = ref(false)
const error = ref('')
const copyStatus = ref('')
const pages = ref<Page[]>([])
const transcript = ref<string>()
let controller: AbortController | undefined
const result = computed(() => transcript.value ?? pages.value.map((page) => page.text).join('\n\n'))
const accept = computed(() =>
  mode.value === 'ocr'
    ? '.png,.jpg,.jpeg,.gif,.webp,.pdf,.doc,.docx,.ppt,.pptx'
    : '.wav,.ogg,.opus',
)

function reset(next: 'ocr' | 'transcribe') {
  mode.value = next
  file.value = undefined
  if (picker.value) picker.value.value = ''
  pages.value = []
  transcript.value = undefined
  error.value = ''
  copyStatus.value = ''
}

function choose(event: Event) {
  const target = event.target as HTMLInputElement
  file.value = target.files?.[0]
  error.value = ''
}

async function run() {
  if (!file.value || busy.value) return
  const limit = mode.value === 'ocr' ? 12 : 8
  if (!file.value.size || file.value.size > limit * 1024 * 1024) {
    error.value = `请选择大于 0 且不超过 ${limit} MiB 的文件。`
    return
  }
  const body = new FormData()
  body.set('file', file.value)
  if (mode.value === 'ocr') body.set('layout', String(layout.value))
  controller = new AbortController()
  const signal = controller.signal
  error.value = ''
  copyStatus.value = ''
  pages.value = []
  transcript.value = undefined
  busy.value = true
  try {
    const options = { method: 'POST', body, signal }
    if (mode.value === 'ocr') {
      pages.value = (
        await api<{ pages: Page[] }>('/media/ocr', options, auth.user?.csrf_token)
      ).pages
    } else {
      transcript.value = (
        await api<{ text: string }>('/media/transcribe', options, auth.user?.csrf_token)
      ).text
    }
  } catch (e) {
    if (!signal.aborted) error.value = e instanceof Error ? e.message : '处理失败。'
  } finally {
    busy.value = false
    controller = undefined
  }
}

async function copy() {
  try {
    await navigator.clipboard.writeText(result.value)
    copyStatus.value = '已复制'
  } catch {
    copyStatus.value = '无法访问剪贴板，请手动复制。'
  }
}

onBeforeUnmount(() => controller?.abort())
</script>

<template>
  <div class="settings-page">
    <header class="page-header">
      <div class="header-breadcrumb">
        <span>工作空间</span><span class="breadcrumb-slash">/</span><strong>识别工具</strong>
      </div>
    </header>
    <div class="settings-scroll">
      <div class="settings-content">
        <h1>文字与语音识别</h1>
        <p class="settings-intro">从截图、扫描件或音频中提取可复制的文字。</p>
        <section class="settings-section media-panel">
          <div class="media-modes" aria-label="识别类型">
            <button
              class="secondary-button"
              :class="{ active: mode === 'ocr' }"
              :aria-pressed="mode === 'ocr'"
              :disabled="busy"
              @click="reset('ocr')"
            >
              <ScanText :size="17" /> 文字识别
            </button>
            <button
              class="secondary-button"
              :class="{ active: mode === 'transcribe' }"
              :aria-pressed="mode === 'transcribe'"
              :disabled="busy"
              @click="reset('transcribe')"
            >
              <AudioLines :size="17" /> 语音转写
            </button>
          </div>
          <form class="media-form" @submit.prevent="run">
            <label for="media-file">{{ mode === 'ocr' ? '图片或文档' : '音频文件' }}</label>
            <input
              id="media-file"
              ref="picker"
              class="text-input"
              type="file"
              :accept="accept"
              :disabled="busy"
              @change="choose"
            />
            <p>
              {{
                mode === 'ocr'
                  ? '支持图片、PDF、Word 和 PPT，最大 12 MiB。'
                  : '支持 16 位 PCM WAV 或 Ogg Opus，最大 8 MiB、120 秒。'
              }}
            </p>
            <label v-if="mode === 'ocr'" class="layout-option">
              <input v-model="layout" type="checkbox" :disabled="busy" /> 按页识别版面与文字
            </label>
            <div class="media-actions">
              <button class="primary-button" :disabled="!file || busy">
                <LoaderCircle v-if="busy" class="spin" :size="17" />
                <FileText v-else :size="17" />
                {{ busy ? '正在处理…' : mode === 'ocr' ? '提取文字' : '开始转写' }}
              </button>
              <button
                v-if="busy"
                type="button"
                class="secondary-button"
                @click="controller?.abort()"
              >
                取消等待
              </button>
            </div>
            <p>所选文件将发送给 DeepSeek 处理。</p>
          </form>
          <div v-if="error" class="error-banner" role="alert">{{ error }}</div>
        </section>
        <section
          v-if="pages.length || transcript !== undefined"
          class="settings-section media-result"
        >
          <div class="media-result-heading">
            <h2>识别结果</h2>
            <button class="secondary-button" :disabled="!result" @click="copy">
              <Copy :size="15" /> 复制结果
            </button>
          </div>
          <p v-if="copyStatus" role="status">{{ copyStatus }}</p>
          <div v-for="page in pages" :key="page.index" class="media-page">
            <h3>第 {{ page.index + 1 }} 页 <span v-if="page.truncated">· 本页输出已截断</span></h3>
            <pre>{{ page.text || '本页没有识别到文字。' }}</pre>
          </div>
          <pre v-if="transcript !== undefined">{{ transcript || '没有识别到语音。' }}</pre>
        </section>
      </div>
    </div>
  </div>
</template>

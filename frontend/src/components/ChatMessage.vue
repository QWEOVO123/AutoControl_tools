<script setup lang="ts">
import { computed, ref } from 'vue'
import {
  Copy,
  Check,
  Wrench,
  LoaderCircle,
  ChevronRight,
  FileText,
  Image,
  Database,
} from '@lucide/vue'
import type { Message } from '../types'
import MarkdownContent from './MarkdownContent.vue'
import SpeakButton from './SpeakButton.vue'
const props = defineProps<{ message: Message; username: string; conversationId: string }>()
defineEmits<{ inspect: [] }>()
const copied = ref(false)
const isJson = computed(() => {
  const value = props.message.content.trim()
  if (!value.startsWith('{') || !value.endsWith('}')) return false
  try {
    JSON.parse(value)
    return true
  } catch {
    return false
  }
})
async function copy(content: string) {
  try {
    await navigator.clipboard.writeText(content)
    copied.value = true
    setTimeout(() => {
      copied.value = false
    }, 1800)
  } catch {
    copied.value = false
  }
}
const statusLabel: Record<string, string> = {
  failed: '执行失败',
  cancelled: '已停止生成',
  interrupted: '任务已中断',
}
</script>

<template>
  <article :class="['chat-message', message.role]">
    <span :class="['avatar', message.role === 'assistant' ? 'agent-avatar' : 'user-avatar']">{{
      message.role === 'assistant' ? 'A' : username.slice(0, 1).toUpperCase()
    }}</span>
    <div class="message-body">
      <div class="message-author">
        {{ message.role === 'assistant' ? 'Agent' : '你'
        }}<span v-if="message.role === 'assistant'" class="agent-tag">LOCAL</span>
      </div>
      <details v-if="message.reasoning" class="reasoning-disclosure">
        <summary>
          <ChevronRight class="reasoning-chevron" :size="15" aria-hidden="true" />
          <span>{{
            message.status === 'running' && message.thinking ? '正在思考' : '思考过程'
          }}</span>
        </summary>
        <div class="reasoning-text">{{ message.reasoning }}</div>
      </details>
      <div v-if="message.tool_events.length" class="tool-summary">
        <Wrench :size="14" /><button @click="$emit('inspect')">
          {{ message.tool_events.length }} 次工具调用<span>查看执行记录</span>
        </button>
      </div>
      <div v-if="message.role === 'assistant' && isJson" class="markdown-content structured-output">
        <span>JSON</span>
        <pre>{{ message.content }}</pre>
      </div>
      <MarkdownContent
        v-else-if="message.role === 'assistant' && message.content"
        :content="message.content"
      />
      <div v-else-if="message.role === 'user'" class="user-content">{{ message.content }}</div>
      <div v-if="message.attachments?.length" class="message-attachments">
        <a
          v-for="file in message.attachments"
          :key="file.id"
          class="attachment-chip"
          :href="`/api/conversations/${conversationId}/attachments/${file.id}`"
          download
        >
          <Image v-if="file.media_type.startsWith('image/')" :size="16" />
          <FileText v-else :size="16" />
          <span>{{ file.name }}</span>
        </a>
      </div>
      <div
        v-if="
          message.status === 'running' &&
          !message.content &&
          !(message.reasoning && message.thinking)
        "
        class="thinking"
        role="status"
      >
        <LoaderCircle class="spin" :size="15" />{{
          message.preparing
            ? '正在解析附件…'
            : message.thinking
              ? '正在思考'
              : message.tool_events.length
                ? '正在处理工具结果…'
                : '正在生成…'
        }}
      </div>
      <div
        v-if="statusLabel[message.status]"
        class="message-state"
        :class="{ 'danger-text': message.status === 'failed' }"
      >
        {{ message.error || statusLabel[message.status] }}
      </div>
      <div
        v-if="message.role === 'assistant' && message.content && message.status !== 'running'"
        class="message-actions"
      >
        <button
          class="icon-button"
          :aria-label="copied ? '已复制' : '复制回答'"
          @click="copy(message.content)"
        >
          <Check v-if="copied" :size="15" /><Copy v-else :size="15" />
        </button>
        <span v-if="message.usage" class="message-usage">
          <Database :size="14" aria-hidden="true" />
          输入 {{ message.usage.input_tokens.toLocaleString() }} · 输出
          {{ message.usage.output_tokens.toLocaleString() }}
          <template v-if="message.usage.cache_read_tokens !== null">
            · 缓存命中 {{ message.usage.cache_read_tokens.toLocaleString() }}
          </template>
        </span>
        <SpeakButton v-if="message.status === 'completed' && !isJson" :text="message.content" />
      </div>
    </div>
  </article>
</template>

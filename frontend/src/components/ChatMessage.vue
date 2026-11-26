<script setup lang="ts">
import { ref } from 'vue'
import { Copy, Check, Wrench, LoaderCircle } from '@lucide/vue'
import type { Message } from '../types'
import MarkdownContent from './MarkdownContent.vue'
defineProps<{ message: Message; username: string }>()
defineEmits<{ inspect: [] }>()
const copied = ref(false)
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
      <div v-if="message.tool_events.length" class="tool-summary">
        <Wrench :size="14" /><button @click="$emit('inspect')">
          {{ message.tool_events.length }} 次工具调用<span>查看执行记录</span>
        </button>
      </div>
      <MarkdownContent
        v-if="message.role === 'assistant' && message.content"
        :content="message.content"
      />
      <div v-else-if="message.role === 'user'" class="user-content">{{ message.content }}</div>
      <div v-if="message.status === 'running' && !message.content" class="thinking">
        <LoaderCircle class="spin" :size="15" />{{
          message.tool_events.length ? '正在处理工具结果…' : '正在思考…'
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
      </div>
    </div>
  </article>
</template>

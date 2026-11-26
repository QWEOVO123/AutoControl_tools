<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { Conversation } from '../types'
const props = defineProps<{
  item: Conversation
  action: 'rename' | 'delete'
  pending: boolean
  error: string
}>()
const emit = defineEmits<{ close: []; confirm: [value: string] }>()
const modal = ref<HTMLDialogElement>(),
  title = ref(props.item.title)
onMounted(() => modal.value?.showModal())
</script>

<template>
  <dialog ref="modal" class="app-dialog" @cancel.prevent="!pending && emit('close')">
    <form @submit.prevent="emit('confirm', title.trim())">
      <h2>{{ action === 'rename' ? '重命名会话' : '删除这段会话？' }}</h2>
      <p>
        {{
          action === 'rename'
            ? '给这段工作一个容易找到的名字。'
            : '会话记录和对应的 Agent 记忆将被永久删除。'
        }}
      </p>
      <input
        v-if="action === 'rename'"
        v-model="title"
        class="text-input"
        aria-label="会话标题"
        maxlength="80"
        required
        autofocus
      />
      <div v-if="error" class="error-banner" role="alert">{{ error }}</div>
      <div class="dialog-actions">
        <button type="button" class="secondary-button" :disabled="pending" @click="emit('close')">
          取消</button
        ><button
          :class="action === 'delete' ? 'danger-button' : 'primary-button'"
          :disabled="pending || !title.trim()"
        >
          {{ pending ? '处理中…' : action === 'rename' ? '保存' : '确认删除' }}
        </button>
      </div>
    </form>
  </dialog>
</template>

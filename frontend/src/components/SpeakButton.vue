<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import { LoaderCircle, Volume2, X } from '@lucide/vue'
import { apiResponse } from '../api/client'
import { useAuth } from '../stores/auth'

const props = defineProps<{ text: string }>()
const auth = useAuth()
const busy = ref(false)
const error = ref('')
const audioUrl = ref('')
let controller: AbortController | undefined

function close() {
  controller?.abort()
  controller = undefined
  busy.value = false
  if (audioUrl.value) URL.revokeObjectURL(audioUrl.value)
  audioUrl.value = ''
}

async function synthesize() {
  if (busy.value || audioUrl.value) {
    close()
    return
  }
  error.value = ''
  const request = new AbortController()
  controller = request
  busy.value = true
  try {
    const response = await apiResponse(
      '/media/speech',
      {
        method: 'POST',
        body: JSON.stringify({ text: props.text }),
        signal: request.signal,
      },
      auth.user?.csrf_token,
    )
    const audio = await response.blob()
    if (!request.signal.aborted) audioUrl.value = URL.createObjectURL(audio)
  } catch (e) {
    if (!request.signal.aborted) error.value = e instanceof Error ? e.message : '朗读请求失败。'
  } finally {
    if (controller === request) {
      controller = undefined
      busy.value = false
    }
  }
}

onBeforeUnmount(close)
</script>

<template>
  <div class="speak-control">
    <button
      class="icon-button"
      type="button"
      :aria-label="busy || audioUrl ? '关闭朗读' : '朗读回答'"
      :disabled="text.length > 10000"
      :title="text.length > 10000 ? '朗读最多支持 10000 字符' : undefined"
      @click="synthesize"
    >
      <LoaderCircle v-if="busy" class="spin" :size="16" />
      <X v-else-if="audioUrl" :size="16" />
      <Volume2 v-else :size="16" />
    </button>
    <audio v-if="audioUrl" :src="audioUrl" controls autoplay @error="error = '音频无法播放。'" />
    <span v-if="error" class="danger-text" role="alert">{{ error }}</span>
  </div>
</template>

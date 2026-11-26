<script setup lang="ts">
import { ref } from 'vue'
import { Image, RotateCcw } from '@lucide/vue'
import { useAppearance } from '../stores/appearance'

const appearance = useAppearance()
const picker = ref<HTMLInputElement>()
const busy = ref(false)
const error = ref('')

async function choose(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (!file) return
  error.value = ''
  busy.value = true
  try {
    await appearance.setBackground(file)
  } catch (e) {
    error.value = e instanceof Error ? e.message : '无法加载图片。'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="settings-section">
    <div class="section-heading">
      <Image :size="20" />
      <div>
        <h2>背景与外观</h2>
        <p>背景图仅保存在当前浏览器。</p>
      </div>
    </div>
    <div class="appearance-control">
      <div class="wallpaper-preview">
        <img v-if="appearance.background" :src="appearance.background" alt="当前背景预览" />
        <span v-else>默认网格背景</span>
      </div>
      <div class="appearance-actions">
        <input
          ref="picker"
          hidden
          type="file"
          accept="image/jpeg,image/png,image/webp"
          @change="choose"
        />
        <button type="button" class="primary-button" :disabled="busy" @click="picker?.click()">
          {{ busy ? '处理中…' : '选择背景图片' }}
        </button>
        <button
          v-if="appearance.background"
          type="button"
          class="secondary-button"
          @click="appearance.reset()"
        >
          <RotateCcw :size="15" /> 恢复默认
        </button>
      </div>
    </div>
    <p v-if="error" class="error-banner" role="alert">{{ error }}</p>
  </section>
</template>

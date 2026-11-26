<script setup lang="ts">
import { Check, LoaderCircle, Terminal, X } from '@lucide/vue'
import type { ToolTrace } from '../types'
defineProps<{ tool: ToolTrace }>()
function format(value: unknown) {
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}
</script>

<template>
  <details :class="['tool-card', tool.status]">
    <summary>
      <span class="tool-icon"><Terminal :size="15" /></span
      ><span class="tool-card-name">{{ tool.name }}</span
      ><LoaderCircle v-if="tool.status === 'running'" class="spin" :size="15" /><Check
        v-else-if="tool.status === 'completed'"
        class="success-text"
        :size="15"
      /><X v-else class="danger-text" :size="15" />
    </summary>
    <div class="tool-detail">
      <span class="field-label">调用参数</span>
      <pre>{{ format(tool.input) }}</pre>
      <template v-if="tool.output !== undefined"
        ><span class="field-label">执行结果</span>
        <pre>{{ format(tool.output) }}</pre></template
      ><span v-if="tool.started_at && tool.finished_at" class="muted"
        >耗时 {{ ((tool.finished_at - tool.started_at) * 1000).toFixed(0) }} ms</span
      >
    </div>
  </details>
</template>

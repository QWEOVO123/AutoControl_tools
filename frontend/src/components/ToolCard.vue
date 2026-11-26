<script setup lang="ts">
import { computed } from 'vue'
import { Check, ExternalLink, Globe, LoaderCircle, Terminal, X } from '@lucide/vue'
import type { ToolTrace } from '../types'
const props = defineProps<{ tool: ToolTrace }>()
function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : undefined
}
function publicLink(value: unknown) {
  if (typeof value !== 'string') return undefined
  try {
    const url = new URL(value)
    return ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password
      ? url.href
      : undefined
  } catch {
    return undefined
  }
}
const output = computed(() => record(props.tool.output))
const web = computed(() => props.tool.name === 'web_search' || props.tool.name === 'web_fetch')
const sources = computed(() => {
  const rows = output.value?.results
  return (Array.isArray(rows) ? rows : [output.value]).flatMap((value) => {
    const row = record(value)
    const href = publicLink(row?.url)
    return href
      ? [
          {
            href,
            title: String(row?.title || href),
            summary: typeof row?.summary === 'string' ? row.summary : '',
            site: typeof row?.site === 'string' ? row.site : new URL(href).hostname,
          },
        ]
      : []
  })
})
const terminal = computed(() => {
  const data = output.value
  if (!data || !('stdout' in data || 'stderr' in data)) return undefined
  const text = (value: unknown) => (typeof value === 'string' ? value : record(value)?.text)
  return {
    stdout: text(data.stdout),
    stderr: text(data.stderr),
    exit: data.exit_code,
    status: data.status,
    truncated:
      data.truncated ||
      data.output_incomplete ||
      record(data.stdout)?.has_more ||
      record(data.stderr)?.has_more ||
      record(data.stdout)?.dropped_chars ||
      record(data.stderr)?.dropped_chars,
  }
})
function format(value: unknown) {
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}
</script>

<template>
  <details :class="['tool-card', tool.status]">
    <summary>
      <span class="tool-icon"><Globe v-if="web" :size="15" /><Terminal v-else :size="15" /></span
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
      <div v-if="web && sources.length" class="source-list">
        <a
          v-for="(source, index) in sources"
          :key="`${source.href}-${index}`"
          :href="source.href"
          target="_blank"
          rel="noopener noreferrer"
        >
          <strong>{{ source.title }} <ExternalLink :size="12" /></strong>
          <span>{{ source.site }}</span>
          <p v-if="source.summary">{{ source.summary }}</p>
        </a>
        <details v-if="tool.name === 'web_fetch' && output?.content" class="raw-output">
          <summary>网页正文</summary>
          <pre>{{ output.content }}</pre>
        </details>
      </div>
      <div v-else-if="terminal" class="terminal-output">
        <span class="field-label">{{
          terminal.exit == null ? terminal.status || '运行中' : `退出码 ${terminal.exit}`
        }}</span>
        <template v-if="terminal.stdout"
          ><span class="field-label">stdout</span>
          <pre>{{ terminal.stdout }}</pre>
        </template>
        <template v-if="terminal.stderr"
          ><span class="field-label">stderr</span>
          <pre>{{ terminal.stderr }}</pre>
        </template>
        <p v-if="terminal.truncated" class="field-label">当前仅显示部分输出</p>
      </div>
      <template v-else-if="tool.output !== undefined">
        <span class="field-label">执行结果</span>
        <pre>{{ format(tool.output) }}</pre>
      </template>
      <span v-if="tool.started_at && tool.finished_at" class="muted"
        >耗时 {{ ((tool.finished_at - tool.started_at) * 1000).toFixed(0) }} ms</span
      >
    </div>
  </details>
</template>

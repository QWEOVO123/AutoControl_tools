<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
const props = defineProps<{ content: string }>()
const html = computed(() =>
  DOMPurify.sanitize(marked.parse(props.content, { async: false, breaks: true }), {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style', 'form', 'input'],
  }),
)
</script>

<template><div class="markdown-content" v-html="html" /></template>

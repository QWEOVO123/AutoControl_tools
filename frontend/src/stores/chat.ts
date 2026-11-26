import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, streamRequest } from '../api/client'
import { readSSE } from '../api/sse'
import { useAuth } from './auth'
import type {
  Attachment,
  Conversation,
  ConversationDetail,
  Message,
  OutputMode,
  ReasoningEffort,
  RunEvent,
  SystemInfo,
} from '../types'

export const useChat = defineStore('chat', () => {
  const conversations = ref<Conversation[]>([])
  const messages = ref<Record<string, Message[]>>({})
  const system = ref<SystemInfo | null>(null)
  const streamingId = ref<string | null>(null)
  const remoteRunning = ref<Record<string, boolean>>({})
  let controller: AbortController | null = null
  let generation = 0
  const csrf = () => useAuth().user?.csrf_token

  async function initialize() {
    const currentGeneration = generation
    const [items, info] = await Promise.all([
      api<Conversation[]>('/conversations'),
      api<SystemInfo>('/system'),
    ])
    if (generation !== currentGeneration) return
    conversations.value = items
    system.value = info
  }
  async function create() {
    const currentGeneration = generation
    const item = await api<Conversation>('/conversations', { method: 'POST' }, csrf())
    if (generation !== currentGeneration) throw new Error('登录状态已变化，请重试。')
    conversations.value.unshift(item)
    messages.value[item.id] = []
    return item
  }
  async function load(id: string) {
    const currentGeneration = generation
    if (streamingId.value === id) return
    const detail = await api<ConversationDetail>(`/conversations/${id}`)
    if (streamingId.value === id || generation !== currentGeneration) return
    messages.value[id] = detail.messages
    remoteRunning.value[id] = detail.running
  }
  async function rename(id: string, title: string) {
    const item = await api<Conversation>(
      `/conversations/${id}`,
      { method: 'PATCH', body: JSON.stringify({ title }) },
      csrf(),
    )
    const index = conversations.value.findIndex((row) => row.id === id)
    if (index >= 0) conversations.value[index] = item
  }
  async function remove(id: string) {
    await api(`/conversations/${id}`, { method: 'DELETE' }, csrf())
    conversations.value = conversations.value.filter((item) => item.id !== id)
    delete messages.value[id]
  }
  async function stop(id: string) {
    await api(`/conversations/${id}/stop`, { method: 'POST' }, csrf())
    if (streamingId.value !== id) {
      await load(id)
      remoteRunning.value[id] = false
    }
  }
  async function uploadAttachments(id: string, files: File[], rich: boolean) {
    const body = new FormData()
    body.set('rich', String(rich))
    for (const file of files) body.append('files', file)
    return api<Attachment[]>(`/conversations/${id}/attachments`, { method: 'POST', body }, csrf())
  }
  async function discardAttachments(id: string, attachments: Attachment[]) {
    await Promise.allSettled(
      attachments.map((file) =>
        api(`/conversations/${id}/attachments/${file.id}`, { method: 'DELETE' }, csrf()),
      ),
    )
  }
  async function send(
    id: string,
    content: string,
    reasoningEffort: ReasoningEffort = 'none',
    attachments: Attachment[] = [],
    outputMode: OutputMode = 'text',
  ) {
    if (streamingId.value) throw new Error('请等待当前任务完成，或先停止生成。')
    controller = new AbortController()
    const currentGeneration = generation
    streamingId.value = id
    const rows = messages.value[id] ?? (messages.value[id] = [])
    const userId = crypto.randomUUID()
    const reply: Message = {
      id: crypto.randomUUID(),
      role: 'assistant',
      content: '',
      thinking: reasoningEffort !== 'none',
      status: 'running',
      created_at: Date.now() / 1000,
      tool_events: [],
    }
    rows.push(
      {
        id: userId,
        role: 'user',
        content,
        attachments,
        status: 'completed',
        created_at: Date.now() / 1000,
        tool_events: [],
      },
      reply,
    )
    let finished = false
    let accepted = false
    const onEvent = (event: RunEvent) => {
      if (generation !== currentGeneration) return
      const item = messages.value[id]!.find((row) => row === reply || row.id === reply.id)!
      if (event.type === 'run.started') {
        accepted = true
        item.id = event.message_id
        reply.id = event.message_id
      } else if (event.type === 'attachment.preparing' || event.type === 'attachment.ready') {
        item.preparing = event.type === 'attachment.preparing'
      } else if (event.type === 'usage.completed') {
        item.usage = event.usage
      } else if (event.type === 'reasoning.delta') {
        item.reasoning = (item.reasoning ?? '') + event.text
        item.thinking = true
      } else if (event.type === 'message.delta') {
        item.content += event.text
        item.thinking = false
      } else if (event.type === 'tool.started' || event.type === 'tool.completed') {
        item.thinking = false
        const index = item.tool_events.findIndex((tool) => tool.id === event.tool.id)
        if (index >= 0) item.tool_events[index] = event.tool
        else item.tool_events.push(event.tool)
      } else if (event.type.startsWith('run.')) {
        item.status = event.type.slice(4)
        if ('error' in event) item.error = event.error
        finished = true
      }
    }
    try {
      const response = await streamRequest(
        `/conversations/${id}/runs`,
        {
          content,
          reasoning_effort: reasoningEffort,
          attachment_ids: attachments.map((file) => file.id),
          output_mode: outputMode,
        },
        csrf()!,
        controller.signal,
      )
      await readSSE(response, onEvent)
      if (!finished) throw new Error('连接中断，执行状态请刷新后确认。')
    } catch (error) {
      if (generation !== currentGeneration) return
      const item = rows.find((row) => row.id === reply.id)!
      item.status =
        error instanceof DOMException && error.name === 'AbortError' ? 'cancelled' : 'failed'
      item.error = error instanceof Error ? error.message : '请求失败'
      if (!accepted) {
        messages.value[id] = rows.filter((row) => row.id !== userId && row.id !== reply.id)
        await discardAttachments(id, attachments)
      }
      throw error
    } finally {
      if (generation === currentGeneration) {
        streamingId.value = null
        remoteRunning.value[id] = false
        controller = null
        const items = await api<Conversation[]>('/conversations').catch(() => conversations.value)
        if (generation === currentGeneration) conversations.value = items
      }
    }
  }
  function clear() {
    generation += 1
    controller?.abort()
    controller = null
    conversations.value = []
    messages.value = {}
    system.value = null
    remoteRunning.value = {}
    streamingId.value = null
  }
  return {
    conversations,
    messages,
    system,
    streamingId,
    remoteRunning,
    initialize,
    create,
    load,
    rename,
    remove,
    send,
    uploadAttachments,
    discardAttachments,
    stop,
    clear,
  }
})

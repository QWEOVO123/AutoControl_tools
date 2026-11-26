import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { api, streamRequest } from '../api/client'
import { useChat } from './chat'
import { useAuth } from './auth'
import type { ConversationDetail, SystemInfo } from '../types'

vi.mock('../api/client', () => ({ api: vi.fn(), streamRequest: vi.fn() }))
vi.mock('../api/sse', () => ({ readSSE: vi.fn().mockResolvedValue(undefined) }))

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('conversation state isolation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    setActivePinia(createPinia())
    useAuth().user = { id: 'first-user', username: 'tester', csrf_token: 'csrf' }
  })

  it('does not restore a previous account after a delayed initialization', async () => {
    const system = deferred<SystemInfo>()
    vi.mocked(api)
      .mockResolvedValueOnce([{ id: 'private-conversation' }])
      .mockReturnValueOnce(system.promise)
    const chat = useChat()
    const pending = chat.initialize()
    chat.clear()
    system.resolve({ model: 'offline-test' } as SystemInfo)
    await pending
    expect(chat.conversations).toEqual([])
    expect(chat.system).toBeNull()
  })

  it('does not overwrite a new stream with an older history response', async () => {
    const history = deferred<ConversationDetail>()
    vi.mocked(api).mockReturnValueOnce(history.promise)
    const chat = useChat()
    const pending = chat.load('conversation')
    chat.streamingId = 'conversation'
    chat.messages.conversation = [
      {
        id: 'new',
        role: 'assistant',
        content: 'live reply',
        status: 'running',
        created_at: 0,
        tool_events: [],
      },
    ]
    history.resolve({
      messages: [],
      running: false,
      conversation: { id: 'conversation', title: 'History', created_at: 0, updated_at: 0 },
    } as ConversationDetail)
    await pending
    expect(chat.messages.conversation[0]?.content).toBe('live reply')
  })

  it('does not revive messages when an old send finishes after logout', async () => {
    const transport = deferred<Response>()
    vi.mocked(streamRequest).mockReturnValueOnce(transport.promise)
    const chat = useChat()
    const pending = chat.send('private-conversation', 'private message')
    chat.clear()
    transport.resolve(new Response(''))
    await pending
    expect(chat.messages).toEqual({})
    expect(chat.streamingId).toBeNull()
    expect(api).not.toHaveBeenCalled()
  })
})

import { describe, expect, it } from 'vitest'
import { readSSE } from './sse'
import type { RunEvent } from '../types'

function response(text: string, size = 1) {
  const bytes = new TextEncoder().encode(text)
  return new Response(
    new ReadableStream({
      start(controller) {
        for (let index = 0; index < bytes.length; index += size)
          controller.enqueue(bytes.slice(index, index + size))
        controller.close()
      },
    }),
  )
}

describe('HTTP SSE reader', () => {
  it('preserves UTF-8 and JSON across arbitrary network chunk boundaries', async () => {
    const events: RunEvent[] = []
    await readSSE(
      response(
        ': keepalive\n\nevent: message.delta\ndata: {"type":"message.delta","text":"你好中文"}\n\ndata: {"type":"run.completed","run_id":"1"}\n\n',
      ),
      (event) => events.push(event),
    )
    expect(events).toEqual([
      { type: 'message.delta', text: '你好中文' },
      { type: 'run.completed', run_id: '1' },
    ])
  })
  it('handles CRLF, multiple data lines and an unterminated final frame', async () => {
    const events: RunEvent[] = []
    await readSSE(
      response(
        'data: {"type":"message.delta",\r\ndata: "text":"hello"}\r\n\r\ndata: {"type":"run.completed","run_id":"1"}',
        7,
      ),
      (event) => events.push(event),
    )
    expect(events).toHaveLength(2)
    expect(events[0]).toEqual({ type: 'message.delta', text: 'hello' })
  })
  it('fails visibly for missing response bodies or invalid JSON', async () => {
    await expect(readSSE(new Response(null), () => {})).rejects.toThrow('数据流')
    await expect(readSSE(response('data: broken\n\n'), () => {})).rejects.toThrow()
  })
})

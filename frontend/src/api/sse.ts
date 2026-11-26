import type { RunEvent } from '../types'

export async function readSSE(response: Response, onEvent: (event: RunEvent) => void) {
  if (!response.body) throw new Error('浏览器未收到可读取的数据流。')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let data: string[] = []
  function line(value: string) {
    value = value.replace(/\r$/, '')
    if (!value) {
      if (data.length) onEvent(JSON.parse(data.join('\n')) as RunEvent)
      data = []
    } else if (value.startsWith('data:')) data.push(value.slice(5).replace(/^ /, ''))
  }
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      let end: number
      while ((end = buffer.indexOf('\n')) >= 0) {
        line(buffer.slice(0, end))
        buffer = buffer.slice(end + 1)
      }
      if (done) {
        if (buffer) line(buffer)
        line('')
        break
      }
    }
  } finally {
    reader.releaseLock()
  }
}

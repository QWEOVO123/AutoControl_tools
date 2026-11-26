export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message)
  }
}

async function responseError(response: Response): Promise<never> {
  let message = `请求失败（${response.status}）`
  try {
    const body = await response.json()
    if (typeof body.detail === 'string') message = body.detail
    else if (Array.isArray(body.detail)) message = '输入格式不正确，请检查后重试。'
  } catch {
    /* Use the status when the server did not return JSON. */
  }
  throw new ApiError(response.status, message)
}

export async function api<T>(path: string, options: RequestInit = {}, csrf?: string): Promise<T> {
  const headers = new Headers(options.headers)
  if (options.body) headers.set('Content-Type', 'application/json')
  if (csrf) headers.set('X-CSRF-Token', csrf)
  const response = await fetch(`/api${path}`, { ...options, headers, credentials: 'same-origin' })
  if (!response.ok) return responseError(response)
  return response.json()
}

export async function streamRequest(
  path: string,
  body: unknown,
  csrf: string,
  signal: AbortSignal,
): Promise<Response> {
  const response = await fetch(`/api${path}`, {
    method: 'POST',
    credentials: 'same-origin',
    signal,
    headers: {
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrf,
      Accept: 'text/event-stream',
    },
    body: JSON.stringify(body),
  })
  if (!response.ok) return responseError(response)
  return response
}

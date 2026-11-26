export interface User {
  id: string
  username: string
  csrf_token: string
}
export interface Conversation {
  id: string
  title: string
  created_at: number
  updated_at: number
}
export interface ToolTrace {
  id: string
  name: string
  input: unknown
  output?: unknown
  status: 'running' | 'completed' | 'failed' | 'interrupted'
  started_at?: number
  finished_at?: number
}
export type ReasoningEffort = 'none' | 'low' | 'high' | 'max'
export type OutputMode = 'text' | 'json'

export interface Attachment {
  id: string
  name: string
  size: number
  media_type: string
}
export interface TokenUsage {
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number | null
}

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  reasoning?: string | null
  thinking?: boolean
  preparing?: boolean
  attachments?: Attachment[]
  usage?: TokenUsage | null
  status: string
  created_at: number
  tool_events: ToolTrace[]
  error?: string | null
}
export interface ConversationDetail {
  conversation: Conversation
  messages: Message[]
  running: boolean
}
export interface SystemInfo {
  platform: string
  python: string
  workspace: string
  model: string
  model_configured: boolean
  transport: string
  elevation_enabled: boolean
  tools: { name: string; description: string }[]
}
export type RunEvent =
  | { type: 'run.started'; run_id: string; message_id: string }
  | { type: 'message.delta'; text: string }
  | { type: 'reasoning.delta'; text: string }
  | { type: 'attachment.preparing' }
  | { type: 'attachment.ready' }
  | { type: 'usage.completed'; usage: TokenUsage }
  | { type: 'tool.started' | 'tool.completed'; tool: ToolTrace }
  | {
      type: 'run.completed' | 'run.cancelled' | 'run.failed'
      run_id: string
      error?: string | null
    }

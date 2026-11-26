<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ShieldCheck, Wrench, Server, KeyRound } from '@lucide/vue'
import { useChat } from '../stores/chat'
import { useAuth } from '../stores/auth'
import { api } from '../api/client'
import AppearanceSettings from '../components/AppearanceSettings.vue'
const chat = useChat(),
  auth = useAuth(),
  router = useRouter()
const current = ref(''),
  replacement = ref(''),
  confirmation = ref(''),
  error = ref(''),
  busy = ref(false)
onMounted(async () => {
  if (!chat.system)
    try {
      await chat.initialize()
    } catch (e) {
      error.value = e instanceof Error ? e.message : '读取设置失败'
    }
})
async function changePassword() {
  error.value = ''
  if (replacement.value !== confirmation.value) {
    error.value = '两次新密码不一致。'
    return
  }
  busy.value = true
  try {
    await api(
      '/auth/password',
      {
        method: 'POST',
        body: JSON.stringify({ current_password: current.value, new_password: replacement.value }),
      },
      auth.user?.csrf_token,
    )
    current.value = ''
    replacement.value = ''
    confirmation.value = ''
    chat.clear()
    auth.user = null
    auth.ready = false
    await router.replace('/login')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '修改失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="settings-page">
    <header class="page-header">
      <div class="header-breadcrumb">
        <span>工作空间</span><span class="breadcrumb-slash">/</span><strong>设置与工具</strong>
      </div>
    </header>
    <div class="settings-scroll">
      <div class="settings-content">
        <h1>工作台设置</h1>
        <p class="settings-intro">运行环境、界面外观和账户。</p>
        <div v-if="error" class="error-banner" role="alert">{{ error }}</div>
        <AppearanceSettings />
        <section class="settings-section">
          <div class="section-heading">
            <Server :size="20" />
            <div>
              <h2>运行环境</h2>
              <p>当前连接的后端与工作目录</p>
            </div>
          </div>
          <dl class="environment-grid">
            <div>
              <dt>操作系统</dt>
              <dd>{{ chat.system?.platform ?? '—' }}</dd>
            </div>
            <div>
              <dt>Python</dt>
              <dd>{{ chat.system?.python ?? '—' }}</dd>
            </div>
            <div>
              <dt>模型</dt>
              <dd>{{ chat.system?.model ?? '—' }}</dd>
            </div>
            <div>
              <dt>通信方式</dt>
              <dd>{{ chat.system?.transport ?? '—' }}</dd>
            </div>
            <div class="wide">
              <dt>工作目录</dt>
              <dd class="mono">{{ chat.system?.workspace ?? '—' }}</dd>
            </div>
          </dl>
        </section>
        <section class="settings-section">
          <div class="section-heading">
            <Wrench :size="20" />
            <div>
              <h2>
                可用工具 <span class="count-badge">{{ chat.system?.tools.length ?? 0 }}</span>
              </h2>
              <p>按需调用，执行记录会显示在对话侧栏</p>
            </div>
          </div>
          <div class="tool-catalog">
            <div v-for="tool in chat.system?.tools" :key="tool.name">
              <code>{{ tool.name }}</code>
              <p>{{ tool.description }}</p>
            </div>
          </div>
          <div class="permission-note">
            <ShieldCheck :size="17" />
            <p>工具以当前后端用户的权限运行。管理员提权尚未启用。</p>
          </div>
        </section>
        <section class="settings-section">
          <div class="section-heading">
            <KeyRound :size="20" />
            <div>
              <h2>账户安全</h2>
              <p>修改密码后，所有登录会话都会失效</p>
            </div>
          </div>
          <form class="password-form" @submit.prevent="changePassword">
            <label for="current-password">当前密码</label
            ><input
              id="current-password"
              v-model="current"
              type="password"
              class="text-input"
              autocomplete="current-password"
              maxlength="128"
              required
            /><label for="new-password">新密码</label
            ><input
              id="new-password"
              v-model="replacement"
              type="password"
              class="text-input"
              autocomplete="new-password"
              minlength="12"
              maxlength="128"
              placeholder="至少 12 个字符"
              required
            /><label for="confirm-password">确认新密码</label
            ><input
              id="confirm-password"
              v-model="confirmation"
              type="password"
              class="text-input"
              autocomplete="new-password"
              minlength="12"
              maxlength="128"
              required
            /><button class="primary-button" :disabled="busy || !!chat.streamingId">
              {{ busy ? '正在更新…' : '更新密码并重新登录' }}
            </button>
          </form>
        </section>
      </div>
    </div>
  </div>
</template>

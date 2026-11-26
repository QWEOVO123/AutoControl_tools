<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { LockKeyhole, TerminalSquare, FolderSearch, ShieldCheck, Eye, EyeOff } from '@lucide/vue'
import { useAuth } from '../stores/auth'
const auth = useAuth(),
  router = useRouter()
const username = ref(''),
  password = ref(''),
  visible = ref(false),
  busy = ref(false),
  error = ref('')
async function submit() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  try {
    await auth.login(username.value.trim(), password.value)
    password.value = ''
    await router.replace('/chat')
  } catch (e) {
    error.value = e instanceof Error ? e.message : '暂时无法登录'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <section class="login-story">
      <div class="brand">
        <span class="brand-mark"><i /><i /><i /><i /></span
        ><span>Agent Studio<small>LOCAL WORKSPACE</small></span>
      </div>
      <div class="login-story-content">
        <span class="eyebrow light">YOUR MACHINE. YOUR WORKSPACE.</span>
        <h1>让想法，<br />在本地发生。</h1>
        <p>从一次对话开始，把检索、编码与执行<br class="desktop-only" />串成清晰可追踪的工作流。</p>
        <div class="login-feature">
          <FolderSearch :size="19" /><span>读懂项目，找到关键上下文</span>
        </div>
        <div class="login-feature">
          <TerminalSquare :size="19" /><span>调用工具，让下一步真正执行</span>
        </div>
        <div class="login-feature">
          <ShieldCheck :size="19" /><span>账户保护，掌握工作台访问权</span>
        </div>
      </div>
      <div class="login-story-footer"><span class="tiny-square" /> BUILT FOR FOCUSED WORK</div>
      <div class="login-grid" aria-hidden="true">
        <div />
        <div />
        <div />
      </div>
    </section>
    <section class="login-form-side">
      <div class="login-form-wrap">
        <span class="login-lock"><LockKeyhole :size="22" /></span
        ><span class="eyebrow">WELCOME BACK</span>
        <h2>登录你的工作台</h2>
        <p class="login-description">输入账户信息，继续你的本地工作。</p>
        <form @submit.prevent="submit">
          <label for="username">账户</label
          ><input
            id="username"
            v-model="username"
            class="text-input"
            autocomplete="username"
            placeholder="输入账户名称"
            maxlength="32"
            required
            autofocus
          /><label for="password">密码</label>
          <div class="password-input">
            <input
              id="password"
              v-model="password"
              :type="visible ? 'text' : 'password'"
              class="text-input"
              autocomplete="current-password"
              placeholder="输入登录密码"
              maxlength="128"
              required
            /><button
              type="button"
              class="icon-button"
              :aria-label="visible ? '隐藏密码' : '显示密码'"
              @click="visible = !visible"
            >
              <EyeOff v-if="visible" :size="18" /><Eye v-else :size="18" />
            </button>
          </div>
          <div v-if="error" class="error-banner" role="alert">{{ error }}</div>
          <button type="submit" class="primary-button login-submit" :disabled="busy">
            {{ busy ? '正在验证…' : '进入工作台' }}
          </button>
        </form>
        <div class="login-note">
          <ShieldCheck :size="16" /><span>此工作台仅向已创建的账户开放。</span>
        </div>
      </div>
      <footer>Agent Studio <span>本地 Agent 工作空间</span></footer>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Plus,
  MessageSquare,
  Settings2,
  LogOut,
  MoreHorizontal,
  Pencil,
  Trash2,
  PanelLeftClose,
  Menu,
} from '@lucide/vue'
import { useChat } from '../stores/chat'
import { useAuth } from '../stores/auth'
import type { Conversation } from '../types'
import ConversationDialog from './ConversationDialog.vue'

const chat = useChat(),
  auth = useAuth(),
  route = useRoute(),
  router = useRouter()
const mobileOpen = ref(false),
  menu = ref<string | null>(null),
  error = ref('')
const dialog = ref<{ item: Conversation; action: 'rename' | 'delete' } | null>(null)
const pending = ref(false)
function newChat() {
  void router.push('/chat')
  mobileOpen.value = false
}
function selectConversation() {
  mobileOpen.value = false
  menu.value = null
}
function manageConversation(item: Conversation, action: 'rename' | 'delete') {
  dialog.value = { item, action }
  menu.value = null
}
onMounted(async () => {
  try {
    await chat.initialize()
  } catch (e) {
    error.value = String(e instanceof Error ? e.message : e)
  }
})
async function logout() {
  if (chat.streamingId) await chat.stop(chat.streamingId).catch(() => {})
  chat.clear()
  await auth.logout().catch(() => {})
  await router.push('/login')
}
async function confirm(value: string) {
  if (!dialog.value) return
  pending.value = true
  error.value = ''
  try {
    const { item, action } = dialog.value
    if (action === 'rename') await chat.rename(item.id, value)
    else {
      await chat.remove(item.id)
      if (route.params.id === item.id) await router.push('/chat')
    }
    dialog.value = null
  } catch (e) {
    error.value = e instanceof Error ? e.message : '操作失败'
  } finally {
    pending.value = false
  }
}
</script>

<template>
  <button class="mobile-menu icon-button" aria-label="打开导航" @click="mobileOpen = !mobileOpen">
    <Menu :size="22" />
  </button>
  <div v-if="mobileOpen" class="sidebar-shade" @click="mobileOpen = false" />
  <aside :class="['sidebar', { 'mobile-open': mobileOpen }]">
    <RouterLink to="/chat" class="brand" @click="mobileOpen = false"
      ><span class="brand-mark"><i /><i /><i /><i /></span
      ><span>Agent Studio<small>LOCAL WORKSPACE</small></span></RouterLink
    >
    <button class="new-chat" @click="newChat"><Plus :size="18" /> 新建会话 <kbd>NEW</kbd></button>
    <div class="sidebar-section-label">工作空间</div>
    <RouterLink
      to="/chat"
      :class="['nav-item', { active: route.path.startsWith('/chat') }]"
      @click="mobileOpen = false"
      ><MessageSquare :size="18" />Agent 对话<span class="nav-count">{{
        chat.conversations.length
      }}</span></RouterLink
    >
    <div class="sidebar-section-label recent-label">最近会话</div>
    <nav class="conversation-list" aria-label="历史会话">
      <p v-if="!chat.conversations.length" class="sidebar-empty">
        开始一次对话，<br />让工作留有轨迹。
      </p>
      <div
        v-for="item in chat.conversations"
        :key="item.id"
        :class="['conversation-row', { selected: route.params.id === item.id }]"
      >
        <RouterLink :to="`/chat/${item.id}`" @click="selectConversation"
          ><MessageSquare :size="15" /><span>{{ item.title }}</span></RouterLink
        >
        <button
          class="conversation-more icon-button"
          :aria-label="`管理会话 ${item.title}`"
          @click="menu = menu === item.id ? null : item.id"
        >
          <MoreHorizontal :size="16" />
        </button>
        <div v-if="menu === item.id" class="conversation-menu">
          <button @click="manageConversation(item, 'rename')"><Pencil :size="14" />重命名</button>
          <button class="danger-text" @click="manageConversation(item, 'delete')">
            <Trash2 :size="14" />删除会话
          </button>
        </div>
      </div>
    </nav>
    <div class="sidebar-bottom">
      <div class="workspace-card">
        <span class="workspace-symbol">⌘</span>
        <div>
          <strong>本地执行环境</strong><small>{{ chat.system?.platform ?? '正在连接后端…' }}</small>
        </div>
      </div>
      <RouterLink
        to="/settings"
        :class="['nav-item', { active: route.path === '/settings' }]"
        @click="mobileOpen = false"
        ><Settings2 :size="18" />设置与工具</RouterLink
      >
      <div class="account-row">
        <span class="avatar account-avatar">{{
          auth.user?.username.slice(0, 1).toUpperCase()
        }}</span>
        <div>
          <strong>{{ auth.user?.username }}</strong><small>已登录</small>
        </div>
        <button class="icon-button" aria-label="退出登录" @click="logout">
          <LogOut :size="17" />
        </button>
      </div>
    </div>
  </aside>
  <ConversationDialog
    v-if="dialog"
    :item="dialog.item"
    :action="dialog.action"
    :pending="pending"
    :error="error"
    @close="dialog = null"
    @confirm="confirm"
  />
  <div v-else-if="error" class="global-notice" role="alert">
    {{ error
    }}<button class="icon-button" aria-label="关闭提示" @click="error = ''">
      <PanelLeftClose :size="16" />
    </button>
  </div>
</template>

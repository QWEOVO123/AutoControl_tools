import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, ApiError } from '../api/client'
import type { User } from '../types'

export const useAuth = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const ready = ref(false)
  let loading: Promise<void> | null = null
  async function restore() {
    if (ready.value) return
    if (loading) return loading
    loading = (async () => {
      try {
        user.value = await api<User>('/auth/me')
        ready.value = true
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          user.value = null
          ready.value = true
        } else throw error
      } finally {
        loading = null
      }
    })()
    return loading
  }
  async function login(username: string, password: string) {
    user.value = await api<User>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    })
    ready.value = true
  }
  async function logout() {
    try {
      await api('/auth/logout', { method: 'POST' }, user.value?.csrf_token)
    } finally {
      user.value = null
      ready.value = false
    }
  }
  return { user, ready, restore, login, logout }
})

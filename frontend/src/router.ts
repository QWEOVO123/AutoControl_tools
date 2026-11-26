import { createRouter, createWebHistory } from 'vue-router'
import type { Pinia } from 'pinia'
import { useAuth } from './stores/auth'

export function createAppRouter(pinia: Pinia) {
  const router = createRouter({
    history: createWebHistory(),
    routes: [
      { path: '/login', component: () => import('./views/LoginView.vue') },
      { path: '/', redirect: '/chat' },
      { path: '/chat/:id?', component: () => import('./views/ChatView.vue') },
      { path: '/settings', component: () => import('./views/SettingsView.vue') },
      { path: '/:pathMatch(.*)*', redirect: '/chat' },
    ],
  })
  router.beforeEach(async (to) => {
    const auth = useAuth(pinia)
    try {
      await auth.restore()
    } catch {
      return to.path === '/login' ? true : '/login'
    }
    if (!auth.user && to.path !== '/login') return '/login'
    if (auth.user && to.path === '/login') return '/chat'
  })
  return router
}

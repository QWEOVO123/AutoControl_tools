<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppSidebar from './components/AppSidebar.vue'
import { useAppearance } from './stores/appearance'
const route = useRoute()
const login = computed(() => route.path === '/login')
const appearance = useAppearance()
const wallpaper = computed(() =>
  appearance.background ? { '--workspace-image': `url("${appearance.background}")` } : {},
)
</script>

<template>
  <div
    :class="[
      'app-frame',
      { 'login-frame': login, 'custom-wallpaper': !login && !!appearance.background },
    ]"
    :style="login ? {} : wallpaper"
  >
    <AppSidebar v-if="!login" />
    <main class="main-frame"><RouterView /></main>
  </div>
</template>

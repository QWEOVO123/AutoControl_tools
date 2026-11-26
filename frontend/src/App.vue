<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppSidebar from './components/AppSidebar.vue'
const route = useRoute()
const login = computed(() => route.path === '/login')
</script>

<template>
  <div :class="['app-frame', { 'login-frame': login }]">
    <AppSidebar v-if="!login" />
    <main class="main-frame"><RouterView /></main>
  </div>
</template>

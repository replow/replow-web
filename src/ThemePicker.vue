<script setup lang="ts">
import { setThemeMode, themeMode, type ThemeMode } from "./theme";
function changeTheme(event: Event) {
  setThemeMode((event.target as HTMLSelectElement).value as ThemeMode);
}
</script>

<template>
  <select class="theme-picker" aria-label="外观模式" :value="themeMode" @change="changeTheme">
    <option value="system">跟随系统</option>
    <option value="light">浅色模式</option>
    <option value="dark">深色模式</option>
  </select>
</template>

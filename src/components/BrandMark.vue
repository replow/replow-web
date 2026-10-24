<script setup lang="ts">
import { MIRO_AVATAR } from "@/utils/miro-brand";
</script>

<template>
  <img class="miro-brand-mark" :src="MIRO_AVATAR" alt="Silune · Silver Wolf" />
</template>

<style scoped>
.miro-brand-mark {
  display: block;
  flex: 0 0 auto;
  width: 34px;
  height: 34px;
  object-fit: cover;
  border: 2px solid var(--miro-mark-border, #d4c8ef);
  border-radius: 11px;
}
</style>

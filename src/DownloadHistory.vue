<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue';
import { mountFanqie } from './fanqie';
const root = ref<HTMLElement | null>(null);
let stop: (() => void) | undefined;
onMounted(() => { if (root.value) stop = mountFanqie(root.value, 'history'); });
onBeforeUnmount(() => stop?.());
</script>
<template>
  <div class="page-heading"><div><h1>历史下载</h1><p>你的小说书架。有效期内直接下载原文件，也可以检查新章节并增量更新。</p></div></div>
  <div ref="root" class="card fq-app fq-account" aria-label="历史下载记录"></div>
</template>
<style scoped>
.fq-account{padding:24px;min-width:0}
@media(max-width:600px){.fq-account{padding:14px}}
</style>

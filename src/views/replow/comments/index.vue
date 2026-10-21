<script setup lang="ts">
import { onMounted, ref } from "vue";
import { getAdminComments, updateCommentStatus } from "@/api/replow";
import { message } from "@/utils/message";

defineOptions({ name: "ReplowComments" });
const loading = ref(false);
const rows = ref<any[]>([]);
const total = ref(0);

async function load() {
  loading.value = true;
  try {
    const result = await getAdminComments({ limit: 200 });
    rows.value = result.items || [];
    total.value = result.total || 0;
  } catch {
    message("评论读取失败", { type: "error" });
  } finally {
    loading.value = false;
  }
}

async function toggle(row: any) {
  const next = row.status === "visible" ? "hidden" : "visible";
  try {
    await updateCommentStatus(row.id, next);
    row.status = next;
    message("评论状态已更新", { type: "success" });
  } catch {
    message("评论状态更新失败", { type: "error" });
  }
}

onMounted(load);
</script>

<template>
  <div class="page-wrap"><el-card shadow="never">
    <template #header><div class="toolbar"><div><strong>评论管理</strong><span class="muted">共 {{ total }} 条</span></div><el-button :loading="loading" @click="load">刷新</el-button></div></template>
    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column prop="article_title" label="文章" min-width="180" show-overflow-tooltip />
      <el-table-column prop="user_name" label="用户" width="150" />
      <el-table-column prop="body_markdown" label="内容" min-width="280" show-overflow-tooltip />
      <el-table-column prop="created_at" label="时间" width="190" />
      <el-table-column label="状态" width="130"><template #default="scope"><el-button text :type="scope.row.status === 'visible' ? 'success' : 'danger'" @click="toggle(scope.row)">{{ scope.row.status === "visible" ? "可见" : "已隐藏" }}</el-button></template></el-table-column>
    </el-table>
  </el-card></div>
</template>

<style scoped>
.page-wrap { padding: 2px; }.toolbar { display: flex; align-items: center; justify-content: space-between; }.toolbar > div { display: flex; align-items: baseline; gap: 12px; }.muted { color: var(--el-text-color-secondary); font-size: 12px; }
</style>

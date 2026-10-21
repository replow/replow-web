<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  getAdminMedia,
  uploadAdminMedia,
  type MediaItem
} from "@/api/replow";
import { message } from "@/utils/message";

const props = withDefaults(
  defineProps<{
    modelValue: string;
    category?: string;
    placeholder?: string;
    accept?: string;
  }>(),
  {
    category: "general",
    placeholder: "可填写外部图片地址，或从媒体库上传",
    accept: "image/jpeg,image/png,image/gif,image/webp,image/avif,image/heic,image/heif,image/bmp"
  }
);

const emit = defineEmits<{
  "update:modelValue": [value: string];
}>();

const dialogVisible = ref(false);
const loading = ref(false);
const uploading = ref(false);
const rows = ref<MediaItem[]>([]);
const fileInput = ref<HTMLInputElement>();

const preview = computed(() => props.modelValue || "");

async function load() {
  loading.value = true;
  try {
    const result = await getAdminMedia({ limit: 200 });
    rows.value = result.items || [];
  } catch {
    message("媒体库读取失败", { type: "error" });
  } finally {
    loading.value = false;
  }
}

function openDialog() {
  dialogVisible.value = true;
  void load();
}

function choose(item: MediaItem) {
  emit("update:modelValue", item.public_url);
  dialogVisible.value = false;
}

function clearValue() {
  emit("update:modelValue", "");
}

function selectFile() {
  fileInput.value?.click();
}

async function upload(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  uploading.value = true;
  try {
    const result = await uploadAdminMedia(file, props.category);
    emit("update:modelValue", result.data.public_url);
    message("图片已上传到媒体库", { type: "success" });
    if (dialogVisible.value) await load();
  } catch (error: any) {
    const detail = error?.response?.data?.detail;
    const labels: Record<string, string> = {
      media_image_type_not_allowed: "支持 JPG、PNG、GIF、WebP、AVIF、HEIC、HEIF 或 BMP 图片",
      media_file_too_large: "图片不能超过 100 MB",
      media_r2_upload_failed: "R2 上传失败，请检查 R2 配置和权限",
      media_r2_sdk_not_installed: "服务器尚未安装 R2 存储依赖"
    };
    message(labels[detail] || detail || "图片上传失败", { type: "error" });
  } finally {
    uploading.value = false;
  }
}

function formatSize(bytes: number) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

onMounted(() => {
  // The picker is intentionally lazy; only the current value is rendered until
  // the user opens the library.
});
</script>

<template>
  <div class="media-picker">
    <div class="media-picker-row">
      <el-input
        :model-value="modelValue"
        :placeholder="placeholder"
        clearable
        @update:model-value="emit('update:modelValue', $event)"
      />
      <el-button :loading="uploading" @click="selectFile">上传</el-button>
      <el-button @click="openDialog">媒体库</el-button>
    </div>
    <div v-if="preview" class="media-picker-preview">
      <el-image :src="preview" fit="cover" lazy />
      <el-button link type="danger" @click="clearValue">清除</el-button>
    </div>
    <input ref="fileInput" class="hidden-file" type="file" :accept="accept" @change="upload" />

    <el-dialog v-model="dialogVisible" title="选择媒体" width="min(94vw, 900px)" destroy-on-close>
      <div v-loading="loading" class="media-grid">
        <button v-for="item in rows" :key="item.id" type="button" class="media-card" @click="choose(item)">
          <el-image :src="item.public_url" fit="cover" lazy />
          <span class="media-name" :title="item.original_name">{{ item.original_name || item.object_key }}</span>
          <small>{{ item.storage_backend.toUpperCase() }} · {{ formatSize(item.byte_size) }}</small>
        </button>
      </div>
      <el-empty v-if="!loading && rows.length === 0" description="媒体库暂无图片" />
      <template #footer>
        <el-button :loading="uploading" @click="selectFile">上传新图片</el-button>
        <el-button @click="dialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.media-picker-row { display: flex; gap: 8px; align-items: center; }
.media-picker-row :deep(.el-input) { flex: 1; min-width: 0; }
.media-picker-preview { display: flex; align-items: center; gap: 10px; margin-top: 8px; }
.media-picker-preview :deep(.el-image) { width: 58px; height: 42px; border-radius: 6px; border: 1px solid var(--el-border-color); }
.hidden-file { display: none; }
.media-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; min-height: 80px; }
.media-card { display: flex; flex-direction: column; gap: 5px; padding: 8px; border: 1px solid var(--el-border-color); border-radius: 8px; background: var(--el-bg-color); text-align: left; cursor: pointer; }
.media-card:hover { border-color: var(--el-color-primary); }
.media-card :deep(.el-image) { width: 100%; height: 105px; border-radius: 5px; background: var(--el-fill-color-light); }
.media-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.media-card small { color: var(--el-text-color-secondary); }
@media (max-width: 600px) { .media-picker-row { flex-wrap: wrap; }.media-picker-row :deep(.el-input) { flex-basis: 100%; } }
</style>

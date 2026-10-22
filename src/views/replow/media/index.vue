<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessageBox } from "element-plus";
import {
  deleteAdminMedia,
  getAdminMedia,
  uploadAdminMedia,
  mediaUploadErrorMessage,
  type MediaItem
} from "@/api/replow";
import { message } from "@/utils/message";

defineOptions({ name: "ReplowMedia" });

const router = useRouter();
const loading = ref(false);
const uploading = ref(false);
const uploadPercent = ref(0);
const uploadStage = ref("");
const rows = ref<MediaItem[]>([]);
const total = ref(0);
const activeCategory = ref("general");
const fileInput = ref<HTMLInputElement>();
const detailsVisible = ref(false);
const selectedItem = ref<MediaItem | null>(null);

const categoryLabels: Record<string, string> = {
  general: "通用", wallpaper: "壁纸", "article-cover": "文章封面",
  avatar: "用户头像", "friend-avatar": "友链头像"
};

async function refreshMedia() {
  loading.value = true;
  try {
    const result = await getAdminMedia({ limit: 200 });
    rows.value = result.items || [];
    total.value = result.total || 0;
    if (selectedItem.value) {
      selectedItem.value = rows.value.find(item => item.id === selectedItem.value?.id) || null;
      if (!selectedItem.value) detailsVisible.value = false;
    }
  } catch {
    message("媒体库读取失败", { type: "error" });
  } finally {
    loading.value = false;
  }
}

function chooseFile() { fileInput.value?.click(); }

async function upload(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  uploading.value = true;
  uploadPercent.value = 0;
  uploadStage.value = "准备上传文件…";
  try {
    await uploadAdminMedia(file, activeCategory.value, progress => {
      uploadPercent.value = Math.min(100, Math.round((progress.loaded / Math.max(1, progress.total)) * 100));
      uploadStage.value = uploadPercent.value >= 100
        ? "文件已发送，正在确认云端存储…"
        : `正在发送 ${uploadPercent.value}%${progress.bytesPerSecond ? ` · ${formatSize(progress.bytesPerSecond)}/s` : ""}`;
    });
    message("文件已上传到媒体库", { type: "success" });
    await refreshMedia();
  } catch (error: unknown) {
    message(mediaUploadErrorMessage(error), { type: "error" });
  } finally {
    uploading.value = false;
    uploadStage.value = "";
  }
}

function openDetails(item: MediaItem) {
  selectedItem.value = item;
  detailsVisible.value = true;
}

async function remove(item: MediaItem) {
  try {
    await ElMessageBox.confirm(
      `确定删除“${item.original_name || item.object_key}”吗？文件和媒体记录都会删除。`,
      "删除媒体", { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }
    );
    await deleteAdminMedia(item.id);
    if (selectedItem.value?.id === item.id) {
      detailsVisible.value = false;
      selectedItem.value = null;
    }
    message("媒体已删除", { type: "success" });
    await refreshMedia();
  } catch (error: any) {
    if (error !== "cancel" && error !== "close") message("媒体删除失败", { type: "error" });
  }
}

async function copyLink(item: MediaItem) {
  try {
    await navigator.clipboard.writeText(item.public_url);
    message("链接已复制", { type: "success" });
  } catch {
    message("复制失败，请手动复制文件地址", { type: "warning" });
  }
}

function formatSize(bytes: number) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}
function fileType(item: MediaItem) {
  const extension = (item.original_name || "").split(".").pop();
  return `${extension && extension !== item.original_name ? extension.toUpperCase() : "文件"} · ${item.mime_type || "未知 MIME"}`;
}
function fileExtension(item: MediaItem) {
  const extension = (item.original_name || "").split(".").pop();
  return extension && extension !== item.original_name ? extension.toUpperCase() : "FILE";
}
function categoryLabel(category: string) { return categoryLabels[category] || category || "未分类"; }
function uploadedAt(value: string) { return value ? value.replace("T", " ").slice(0, 19) : "未记录"; }
function uploadedBy(item: MediaItem) {
  if (item.uploader_id == null) return "历史文件 · 未记录上传用户";
  return `${item.uploader_name || item.uploader_username || "用户"} (UID ${item.uploader_id})`;
}
function isImage(item: MediaItem) { return (item.mime_type || "").startsWith("image/"); }

onMounted(refreshMedia);
</script>

<template>
  <div class="page-wrap">
    <el-card v-loading="loading" shadow="never">
      <template #header>
        <div class="toolbar">
          <div class="heading">
            <strong>媒体库</strong>
            <span class="muted">共 {{ total }} 个文件，点击文件查看详情</span>
          </div>
          <div class="toolbar-actions">
            <el-select v-model="activeCategory" class="category-select" aria-label="上传类别">
              <el-option label="通用" value="general" />
              <el-option label="壁纸" value="wallpaper" />
              <el-option label="文章封面" value="article-cover" />
              <el-option label="用户头像" value="avatar" />
              <el-option label="友链头像" value="friend-avatar" />
            </el-select>
            <el-button :loading="uploading" type="primary" @click="chooseFile">上传文件</el-button>
            <el-button :loading="loading" @click="refreshMedia">刷新</el-button>
            <el-button @click="router.push('/replow/media/storage')">存储设置</el-button>
          </div>
        </div>
      </template>
      <input ref="fileInput" class="hidden-file" type="file"
        accept="image/jpeg,image/png,image/gif,image/webp,image/avif,image/heic,image/heif,image/bmp,.pdf,.txt,.epub,.zip,.mp3,.mp4,.webm,.ogg,.wav,.flac"
        @change="upload" />
      <div v-if="uploading" class="upload-progress">
        <el-progress :percentage="uploadPercent" :stroke-width="5" :show-text="false" />
        <small>{{ uploadStage }}</small>
      </div>
      <div class="media-grid">
        <div v-for="item in rows" :key="item.id" class="media-card">
          <button class="media-open" type="button" :aria-label="`查看 ${item.original_name || item.object_key} 的详情`" @click="openDetails(item)">
            <el-image v-if="isImage(item)" :src="item.public_url" :alt="item.original_name" fit="cover" lazy />
            <div v-else class="file-preview">{{ fileExtension(item) }}</div>
            <div class="media-name" :title="item.original_name">{{ item.original_name || item.object_key }}</div>
          </button>
          <div class="media-meta">
            <span>{{ categoryLabel(item.category) }}</span>
            <span>{{ formatSize(item.byte_size) }}</span>
          </div>
          <div class="media-actions">
            <el-button link type="primary" @click="openDetails(item)">详情</el-button>
            <el-button link type="primary" @click="copyLink(item)">复制链接</el-button>
            <el-button link type="danger" @click="remove(item)">删除</el-button>
          </div>
        </div>
      </div>
      <el-empty v-if="!loading && rows.length === 0" description="媒体库暂无文件，请先上传" />
    </el-card>

    <el-dialog v-model="detailsVisible" title="媒体详情" width="min(760px, 95vw)" destroy-on-close append-to-body>
      <div v-if="selectedItem" class="detail-layout">
        <div class="detail-preview">
          <el-image v-if="isImage(selectedItem)" :src="selectedItem.public_url"
            :alt="selectedItem.original_name" fit="contain" />
          <div v-else class="detail-file">{{ fileExtension(selectedItem) }}</div>
        </div>
        <el-descriptions :column="1" border class="detail-fields">
          <el-descriptions-item label="文件名称"><span class="break-text">{{ selectedItem.original_name || selectedItem.object_key }}</span></el-descriptions-item>
          <el-descriptions-item label="格式">{{ fileType(selectedItem) }}</el-descriptions-item>
          <el-descriptions-item label="大小">{{ formatSize(selectedItem.byte_size) }}（{{ selectedItem.byte_size.toLocaleString() }} 字节）</el-descriptions-item>
          <el-descriptions-item label="链接">
            <a class="break-text detail-link" :href="selectedItem.public_url" target="_blank" rel="noopener noreferrer">{{ selectedItem.public_url }}</a>
            <el-button class="ml-2" link type="primary" @click="copyLink(selectedItem)">复制</el-button>
          </el-descriptions-item>
          <el-descriptions-item label="上传日期">{{ uploadedAt(selectedItem.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="类别">{{ categoryLabel(selectedItem.category) }}</el-descriptions-item>
          <el-descriptions-item label="上传用户">{{ uploadedBy(selectedItem) }}</el-descriptions-item>
          <el-descriptions-item label="存储位置">{{ selectedItem.storage_backend.toUpperCase() }}</el-descriptions-item>
        </el-descriptions>
      </div>
      <template #footer><el-button @click="detailsVisible = false">关闭</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-wrap { padding: 2px; }
.toolbar, .toolbar-actions, .heading, .media-actions, .media-meta { display: flex; align-items: center; gap: 10px; }
.toolbar { justify-content: space-between; flex-wrap: wrap; }
.heading { flex-wrap: wrap; }
.toolbar-actions { flex-wrap: wrap; }
.muted { font-size: 12px; color: var(--el-text-color-secondary); }
.category-select { width: 130px; }
.hidden-file { display: none; }
.upload-progress { margin: 10px 0 18px; }
.upload-progress small { color: var(--el-text-color-secondary); }
.media-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(185px, 1fr)); gap: 16px; }
.media-card { min-width: 0; padding: 10px; border: 1px solid var(--el-border-color); border-radius: 12px; background: var(--el-bg-color); transition: border-color .2s, box-shadow .2s; }
.media-card:hover { border-color: var(--el-color-primary-light-5); box-shadow: 0 4px 12px rgba(0,0,0,.06); }
.media-open { display: block; width: 100%; background: none; border: 0; padding: 0; color: inherit; text-align: left; cursor: pointer; }
.media-open:focus-visible { outline: 2px solid var(--el-color-primary); outline-offset: 3px; border-radius: 6px; }
.media-open :deep(.el-image) { display: block; width: 100%; height: 150px; background: var(--el-fill-color-light); border-radius: 8px; }
.file-preview, .detail-file { display: flex; justify-content: center; align-items: center; color: var(--el-text-color-secondary); background: var(--el-fill-color-light); border-radius: 8px; font-size: 25px; font-weight: 700; }
.file-preview { height: 150px; }
.media-name { margin-top: 9px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.media-meta { justify-content: space-between; color: var(--el-text-color-secondary); margin-top: 6px; font-size: 12px; }
.media-actions { flex-wrap: wrap; justify-content: space-between; gap: 0; margin-top: 5px; }
.media-actions :deep(.el-button) { padding: 0; margin: 0; }
.detail-layout { display: grid; gap: 18px; }
.detail-preview { min-height: 175px; max-height: 340px; display: flex; justify-content: center; align-items: center; border-radius: 10px; background: var(--el-fill-color-light); overflow: hidden; }
.detail-preview :deep(.el-image) { width: 100%; height: 100%; max-height: 340px; text-align: center; }
.detail-file { width: 100%; height: 175px; }
.detail-fields { width: 100%; }
.break-text { overflow-wrap: anywhere; word-break: break-word; }
.detail-link { color: var(--el-color-primary); }
@media (max-width: 760px) { .toolbar { align-items: flex-start; flex-direction: column; } .toolbar-actions { width: 100%; } .category-select { flex: 1; min-width: 110px; } .media-grid { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 10px; } .media-open :deep(.el-image), .file-preview { height: 125px; } }
</style>

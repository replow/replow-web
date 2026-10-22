<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessageBox } from "element-plus";
import {
  deleteAdminMedia,
  getAdminMedia,
  getMediaStorageSettings,
  getMediaStorageStatus,
  updateMediaStorageSettings,
  uploadAdminMedia,
  mediaUploadErrorMessage,
  type MediaItem,
  type MediaStorageSettings,
  type MediaStorageStatus
} from "@/api/replow";
import { message } from "@/utils/message";

defineOptions({ name: "ReplowMedia" });

const NINE_GB = 9_000_000_000;
const loading = ref(false);
const saving = ref(false);
const uploading = ref(false);
const uploadPercent = ref(0);
const uploadStage = ref("");
const rows = ref<MediaItem[]>([]);
const total = ref(0);
const activeCategory = ref("general");
const fileInput = ref<HTMLInputElement>();
const status = ref<MediaStorageStatus>();

const form = reactive({
  storage_mode: "od_first",
  od_weight: 50,
  r2_weight: 50,
  fallback_enabled: true,
  od_enabled: true,
  r2_account_id: "",
  r2_bucket: "",
  r2_access_key_id: "",
  r2_secret_access_key: "",
  r2_public_base_url: "",
  r2_endpoint_url: "",
  local_root: "./data/media",
  local_public_base_url: "https://www.replow.org/v1/public/media",
  clear_r2_credentials: false
});

function applySettings(value: MediaStorageSettings) {
  form.storage_mode = value.storage_mode || "od_first";
  form.od_weight = value.od_weight || 50;
  form.r2_weight = value.r2_weight || 50;
  form.fallback_enabled = value.fallback_enabled ?? true;
  form.od_enabled = value.od_enabled ?? true;
  form.r2_account_id = value.r2_account_id || "";
  form.r2_bucket = value.r2_bucket || "";
  form.r2_access_key_id = "";
  form.r2_secret_access_key = "";
  form.r2_public_base_url = value.r2_public_base_url || "";
  form.r2_endpoint_url = value.r2_endpoint_url || "";
  form.local_root = value.local_root || "./data/media";
  form.local_public_base_url =
    value.local_public_base_url || "https://www.replow.org/v1/public/media";
  form.clear_r2_credentials = false;
}

async function load() {
  loading.value = true;
  try {
    const [mediaResult, storageResult, statusResult] = await Promise.all([
      getAdminMedia({ limit: 200 }),
      getMediaStorageSettings(),
      getMediaStorageStatus()
    ]);
    rows.value = mediaResult.items || [];
    total.value = mediaResult.total || 0;
    applySettings(storageResult.data);
    status.value = statusResult.data;
  } catch {
    message("媒体库或存储配置读取失败", { type: "error" });
  } finally {
    loading.value = false;
  }
}

async function refreshMedia() {
  try {
    const [mediaResult, statusResult] = await Promise.all([
      getAdminMedia({ limit: 200 }),
      getMediaStorageStatus()
    ]);
    rows.value = mediaResult.items || [];
    total.value = mediaResult.total || 0;
    status.value = statusResult.data;
  } catch {
    message("媒体库刷新失败", { type: "error" });
  }
}

async function saveSettings() {
  if (!form.local_root.trim() || !form.local_public_base_url.trim()) {
    message("本地存储路径和本地公开地址不能为空", { type: "warning" });
    return;
  }
  saving.value = true;
  try {
    const result = await updateMediaStorageSettings({
      storage_mode: form.storage_mode,
      od_weight: form.od_weight,
      r2_weight: form.r2_weight,
      fallback_enabled: form.fallback_enabled,
      od_enabled: form.od_enabled,
      r2_account_id: form.r2_account_id.trim(),
      r2_bucket: form.r2_bucket.trim(),
      r2_access_key_id: form.r2_access_key_id.trim(),
      r2_secret_access_key: form.r2_secret_access_key.trim(),
      r2_public_base_url: form.r2_public_base_url.trim(),
      r2_endpoint_url: form.r2_endpoint_url.trim(),
      r2_limit_bytes: NINE_GB,
      local_root: form.local_root.trim(),
      local_public_base_url: form.local_public_base_url.trim(),
      clear_r2_credentials: form.clear_r2_credentials
    });
    applySettings(result.data);
    message("媒体存储设置已保存", { type: "success" });
    await refreshMedia();
  } catch (error: any) {
    const detail = error?.response?.data?.detail;
    const labels: Record<string, string> = {
      media_invalid_r2_account_id: "R2 Account ID 格式不正确",
      media_r2_config_incomplete: "R2 账号、Bucket 和公开地址需要同时填写",
      media_invalid_r2_public_url: "R2 公共访问地址必须是 HTTP 或 HTTPS",
      media_invalid_r2_endpoint: "R2 Endpoint 必须是 HTTP 或 HTTPS",
      media_local_root_required: "本地存储路径不能为空",
      media_invalid_local_public_url: "本地公开地址必须是 HTTP 或 HTTPS",
      media_r2_limit_must_be_9_gb: "R2 阈值固定为 9 GB",
      media_invalid_storage_mode: "请选择有效的上传策略",
      media_invalid_storage_weights: "两端权重需要在 1–100 之间",
      media_invalid_storage_policy: "存储策略设置无效"
    };
    message(labels[detail] || detail || "媒体存储设置保存失败", {
      type: "error"
    });
  } finally {
    saving.value = false;
  }
}

function chooseFile() {
  fileInput.value?.click();
}

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
      uploadPercent.value = Math.min(
        100,
        Math.round((progress.loaded / Math.max(1, progress.total)) * 100)
      );
      uploadStage.value =
        uploadPercent.value >= 100
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

async function remove(item: MediaItem) {
  try {
    await ElMessageBox.confirm(
      `确定删除“${item.original_name || item.object_key}”吗？文件和媒体记录都会删除。`,
      "删除媒体",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }
    );
    await deleteAdminMedia(item.id);
    message("媒体已删除", { type: "success" });
    await refreshMedia();
  } catch (error: any) {
    if (error !== "cancel" && error !== "close")
      message("媒体删除失败", { type: "error" });
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
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1
  );
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function usagePercent() {
  return Math.min(100, Math.max(0, Number(status.value?.r2_used_percent || 0)));
}

onMounted(load);
</script>

<template>
  <div v-loading="loading" class="page-wrap">
    <el-card shadow="never" class="settings-card">
      <template #header>
        <div class="toolbar">
          <div>
            <strong>媒体存储</strong
            ><span class="muted">选择上传位置，文件自动生成长期访问链接</span>
          </div>
          <el-button :loading="saving" type="primary" @click="saveSettings"
            >保存存储设置</el-button
          >
        </div>
      </template>
      <el-alert
        title="R2 和 Cloudflare CDN 是两套独立账号。这里填写 R2 账号自己的 Account ID、Bucket、Access Key 和 Secret Key，不会读取 CDN 配置。"
        type="info"
        :closable="false"
        show-icon
        class="mb-4"
      />
      <el-form label-position="top">
        <el-row :gutter="18">
          <el-col :xs="24" :md="12"
            ><el-form-item label="上传策略"
              ><el-select v-model="form.storage_mode" style="width: 100%"
                ><el-option label="OneDrive 优先" value="od_first" /><el-option
                  label="R2 优先"
                  value="r2_first" /><el-option
                  label="按权重分流"
                  value="balanced" /></el-select></el-form-item
          ></el-col>
          <el-col :xs="24" :md="12"
            ><el-form-item label="OneDrive"
              ><el-switch
                v-model="form.od_enabled"
                active-text="允许新文件上传"
              /><el-tag
                class="ml-3"
                :type="status?.od_configured ? 'success' : 'warning'"
                >{{
                  status?.od_configured ? "已连接" : "未启用或未连接"
                }}</el-tag
              ></el-form-item
            ></el-col
          >
          <template v-if="form.storage_mode === 'balanced'">
            <el-col :xs="24" :md="12"
              ><el-form-item label="OneDrive 权重"
                ><el-input-number
                  v-model="form.od_weight"
                  :min="1"
                  :max="100" /></el-form-item
            ></el-col>
            <el-col :xs="24" :md="12"
              ><el-form-item label="R2 权重"
                ><el-input-number
                  v-model="form.r2_weight"
                  :min="1"
                  :max="100" /></el-form-item
            ></el-col>
          </template>
        </el-row>
        <el-checkbox v-model="form.fallback_enabled"
          >首选存储不可用时，尝试另一云存储</el-checkbox
        >
        <p class="muted">
          OneDrive
          链接：https://drive.4z.ink/文件路径。策略只影响新上传，已有文件保留原地址。分流比例按上传请求数量计算，不复制文件。
        </p>
        <el-row :gutter="18">
          <el-col :xs="24" :md="12"
            ><el-form-item label="R2 Account ID"
              ><el-input
                v-model="form.r2_account_id"
                placeholder="R2 所属账号的 Account ID" /></el-form-item
          ></el-col>
          <el-col :xs="24" :md="12"
            ><el-form-item label="R2 Bucket"
              ><el-input
                v-model="form.r2_bucket"
                placeholder="例如 replow-media" /></el-form-item
          ></el-col>
          <el-col :xs="24" :md="12"
            ><el-form-item label="R2 Access Key ID"
              ><el-input
                v-model="form.r2_access_key_id"
                autocomplete="new-password"
                placeholder="留空表示不修改" /></el-form-item
          ></el-col>
          <el-col :xs="24" :md="12"
            ><el-form-item label="R2 Secret Access Key"
              ><el-input
                v-model="form.r2_secret_access_key"
                type="password"
                show-password
                autocomplete="new-password"
                placeholder="留空表示不修改" /></el-form-item
          ></el-col>
          <el-col :xs="24" :md="12"
            ><el-form-item label="R2 公共访问地址"
              ><el-input
                v-model="form.r2_public_base_url"
                placeholder="https://img.example.com" /></el-form-item
          ></el-col>
          <el-col :xs="24" :md="12"
            ><el-form-item label="R2 Endpoint（可选）"
              ><el-input
                v-model="form.r2_endpoint_url"
                placeholder="留空自动使用 R2 Account ID 生成" /></el-form-item
          ></el-col>
          <el-col :xs="24" :md="12"
            ><el-form-item label="本地存储路径"
              ><el-input
                v-model="form.local_root"
                placeholder="/www/wwwroot/replow-next/media" /></el-form-item
          ></el-col>
          <el-col :xs="24" :md="12"
            ><el-form-item label="本地公开地址"
              ><el-input
                v-model="form.local_public_base_url"
                placeholder="https://www.replow.org/v1/public/media" /></el-form-item
          ></el-col>
        </el-row>
      </el-form>
      <div class="inline-options">
        <el-checkbox v-model="form.clear_r2_credentials"
          >清除已保存的 R2 密钥</el-checkbox
        ><span class="muted"
          >R2 阈值固定为 9 GB，达到阈值后按上传策略选择可用云存储。</span
        >
      </div>
      <div v-if="status" class="usage-box">
        <div class="usage-head">
          <span
            >R2 使用量：{{ formatSize(status.r2_bytes) }} /
            {{ formatSize(status.r2_limit_bytes) }}</span
          ><el-tag
            :type="
              status.od_configured || status.r2_configured
                ? 'success'
                : 'warning'
            "
            >{{
              status.next_backend === "balanced"
                ? "按权重分流"
                : `下一次上传：${status.next_backend.toUpperCase()}`
            }}</el-tag
          >
        </div>
        <el-progress
          :percentage="usagePercent()"
          :status="usagePercent() >= 90 ? 'warning' : undefined"
        />
        <div class="usage-foot">
          <span>OneDrive：{{ formatSize(status.od_bytes) }}</span
          ><span>本地：{{ formatSize(status.local_bytes) }}</span
          ><span>总计：{{ formatSize(status.total_bytes) }}</span>
        </div>
      </div>
    </el-card>

    <el-card shadow="never">
      <template #header
        ><div class="toolbar">
          <div>
            <strong>媒体库</strong
            ><span class="muted">共 {{ total }} 个文件</span>
          </div>
          <div class="toolbar-actions">
            <el-select v-model="activeCategory" class="category-select"
              ><el-option label="通用" value="general" /><el-option
                label="壁纸"
                value="wallpaper" /><el-option
                label="文章封面"
                value="article-cover" /><el-option
                label="用户头像"
                value="avatar" /><el-option
                label="友链头像"
                value="friend-avatar" /></el-select
            ><el-button :loading="uploading" type="primary" @click="chooseFile"
              >上传文件</el-button
            ><el-button :loading="loading" @click="refreshMedia"
              >刷新</el-button
            >
          </div>
        </div></template
      >
      <input
        ref="fileInput"
        class="hidden-file"
        type="file"
        accept="image/jpeg,image/png,image/gif,image/webp,image/avif,image/heic,image/heif,image/bmp,.pdf,.txt,.epub,.zip,.mp3,.mp4,.webm,.ogg,.wav,.flac"
        @change="upload"
      />
      <div v-if="uploading" class="upload-progress">
        <el-progress
          :percentage="uploadPercent"
          :stroke-width="5"
          :show-text="false"
        />
        <small>{{ uploadStage }}</small>
      </div>
      <div class="media-grid">
        <div v-for="item in rows" :key="item.id" class="media-card">
          <el-image
            v-if="item.mime_type.startsWith('image/')"
            :src="item.public_url"
            fit="cover"
            lazy
          />
          <div v-else class="file-preview">
            {{ item.original_name.split(".").pop()?.toUpperCase() || "FILE" }}
          </div>
          <div class="media-name" :title="item.original_name">
            {{ item.original_name || item.object_key }}
          </div>
          <div class="media-meta">
            <span>{{ item.storage_backend.toUpperCase() }}</span
            ><span>{{ formatSize(item.byte_size) }}</span>
          </div>
          <el-button link type="primary" @click="copyLink(item)"
            >复制链接</el-button
          >
          <el-button link type="danger" @click="remove(item)">删除</el-button>
        </div>
      </div>
      <el-empty
        v-if="!loading && rows.length === 0"
        description="媒体库暂无文件，请先上传"
      />
    </el-card>
  </div>
</template>

<style scoped>
.file-preview {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 150px;
  border-radius: 7px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-secondary);
  font-size: 24px;
  font-weight: 600;
}
.upload-progress {
  margin: 10px 0;
}
.upload-progress small {
  color: var(--el-text-color-secondary);
}
.page-wrap {
  display: grid;
  gap: 16px;
  padding: 2px;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.toolbar > div:first-child {
  display: flex;
  gap: 12px;
  align-items: baseline;
}
.toolbar-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.mb-4 {
  margin-bottom: 16px;
}
.inline-options {
  display: flex;
  gap: 18px;
  align-items: center;
  flex-wrap: wrap;
}
.usage-box {
  margin-top: 18px;
  padding: 14px;
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
}
.usage-head,
.usage-foot,
.media-meta {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
}
.usage-foot {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-top: 6px;
}
.category-select {
  width: 120px;
}
.hidden-file {
  display: none;
}
.media-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 16px;
}
.media-card {
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--el-border-color);
  border-radius: 10px;
  background: var(--el-bg-color);
}
.media-card :deep(.el-image) {
  display: block;
  width: 100%;
  height: 150px;
  border-radius: 7px;
  background: var(--el-fill-color-light);
}
.media-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-top: 9px;
}
.media-meta {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-top: 6px;
}
.media-card :deep(.el-button) {
  padding-left: 0;
  margin-top: 3px;
}
@media (max-width: 760px) {
  .toolbar {
    align-items: stretch;
    flex-direction: column;
  }
  .toolbar-actions {
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  .category-select {
    flex: 1;
    min-width: 110px;
  }
}
</style>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import { ElMessageBox } from "element-plus";
import {
  getAlbums,
  getAlbum,
  saveAlbum,
  saveAlbumPhotos,
  deleteAlbum,
  getAdminMedia,
  uploadAdminMedia,
  mediaUploadErrorMessage,
  type AlbumItem,
  type AlbumPhoto,
  type MediaItem
} from "@/api/replow";
import MediaPicker from "@/components/MediaPicker.vue";
import { message } from "@/utils/message";
defineOptions({ name: "ReplowAlbums" });
const albums = ref<AlbumItem[]>([]),
  loading = ref(false),
  saving = ref(false),
  editor = ref(false),
  photoEditor = ref(false),
  libraryOpen = ref(false),
  uploading = ref(false);
const uploadPercent = ref(0);
const uploadStage = ref("");
const editingId = ref<number>(),
  activeAlbum = ref<AlbumItem>(),
  photos = ref<AlbumPhoto[]>([]),
  media = ref<MediaItem[]>([]),
  chosen = ref<number[]>([]);
const fileInput = ref<HTMLInputElement>(),
  base = ref(""),
  photoBase = ref("");
const form = reactive({
  title: "",
  description: "",
  cover_url: "",
  sort_order: 0,
  is_published: false
});
const dirty = computed(
  () => editor.value && JSON.stringify(form) !== base.value
);
const photosDirty = computed(
  () => photoEditor.value && JSON.stringify(photos.value) !== photoBase.value
);
async function load() {
  loading.value = true;
  try {
    albums.value = (await getAlbums()).items;
  } catch {
    message("相册读取失败", { type: "error" });
  } finally {
    loading.value = false;
  }
}
async function confirmDiscard(value: boolean) {
  if (!value) return true;
  try {
    await ElMessageBox.confirm("有尚未保存的修改，确定放弃？", "放弃修改", {
      confirmButtonText: "放弃修改",
      cancelButtonText: "继续编辑",
      type: "warning"
    });
    return true;
  } catch {
    return false;
  }
}
async function closeEditor(done?: () => void) {
  if (!saving.value && (await confirmDiscard(dirty.value))) {
    editor.value = false;
    done?.();
  }
}
async function closePhotos(done?: () => void) {
  if (!saving.value && (await confirmDiscard(photosDirty.value))) {
    photoEditor.value = false;
    done?.();
  }
}
onBeforeRouteLeave(
  async () => await confirmDiscard(dirty.value || photosDirty.value)
);
function edit(row?: AlbumItem) {
  editingId.value = row?.id;
  Object.assign(form, {
    title: row?.title || "",
    description: row?.description || "",
    cover_url: row?.cover_url || "",
    sort_order: row?.sort_order || 0,
    is_published: !!row?.is_published
  });
  base.value = JSON.stringify(form);
  editor.value = true;
}
async function save() {
  if (!form.title.trim()) {
    message("请输入相册名称", { type: "warning" });
    return;
  }
  if (form.is_published) {
    try {
      await ElMessageBox.confirm(
        "保存后，此相册及其中图片将向所有访客公开。",
        "确认发布相册",
        {
          type: "warning",
          confirmButtonText: "保存并发布",
          cancelButtonText: "取消"
        }
      );
    } catch {
      return;
    }
  }
  saving.value = true;
  try {
    await saveAlbum({ ...form, title: form.title.trim() }, editingId.value);
    base.value = JSON.stringify(form);
    editor.value = false;
    await load();
    message("相册已保存", { type: "success" });
  } catch {
    message("保存失败，请检查名称和封面地址", { type: "error" });
  } finally {
    saving.value = false;
  }
}
async function manage(row: AlbumItem) {
  try {
    const result = await getAlbum(row.id);
    activeAlbum.value = result.data;
    photos.value = result.data.photos || [];
    photoBase.value = JSON.stringify(photos.value);
    photoEditor.value = true;
  } catch {
    message("相册图片读取失败", { type: "error" });
  }
}
async function openLibrary() {
  try {
    media.value = (await getAdminMedia({ limit: 500 })).items.filter(
      item =>
        item.mime_type.startsWith("image/") &&
        item.mime_type !== "image/svg+xml"
    );
    chosen.value = [];
    libraryOpen.value = true;
  } catch {
    message("媒体库读取失败", { type: "error" });
  }
}
function toggle(id: number) {
  chosen.value = chosen.value.includes(id)
    ? chosen.value.filter(value => value !== id)
    : [...chosen.value, id];
}
function add() {
  for (const id of chosen.value) {
    const item = media.value.find(item => item.id === id);
    if (item && !photos.value.some(photo => photo.media_id === id))
      photos.value.push({
        media_id: id,
        caption: "",
        public_url: item.public_url,
        original_name: item.original_name
      });
  }
  libraryOpen.value = false;
}
function move(index: number, step: number) {
  const target = index + step;
  if (target < 0 || target >= photos.value.length) return;
  [photos.value[index], photos.value[target]] = [
    photos.value[target],
    photos.value[index]
  ];
}
async function savePhotos() {
  if (!activeAlbum.value) return;
  saving.value = true;
  try {
    const result = await saveAlbumPhotos(activeAlbum.value.id, photos.value);
    photos.value = result.data.photos || [];
    photoBase.value = JSON.stringify(photos.value);
    message("图片顺序与说明已保存", { type: "success" });
    await load();
  } catch {
    message("图片保存失败，请检查媒体是否仍存在", { type: "error" });
  } finally {
    saving.value = false;
  }
}
async function upload(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  uploading.value = true;
  uploadPercent.value = 0;
  uploadStage.value = "准备发送图片…";
  try {
    const item = (await uploadAdminMedia(file, "article", progress => {
      uploadPercent.value = Math.min(100, Math.round(progress.loaded / Math.max(1, progress.total) * 100));
      uploadStage.value = uploadPercent.value >= 100
        ? "文件已发送，正在确认云端存储…"
        : `正在发送 ${uploadPercent.value}%${progress.bytesPerSecond ? ` · ${Math.round(progress.bytesPerSecond / 1024)} KB/s` : ""}`;
    })).data;
    photos.value.push({
      media_id: item.id,
      public_url: item.public_url,
      original_name: item.original_name,
      caption: ""
    });
    message("上传完成，保存图片列表后加入相册", { type: "success" });
  } catch (error: unknown) {
    message(mediaUploadErrorMessage(error), { type: "error" });
  } finally {
    uploading.value = false;
    uploadStage.value = "";
    input.value = "";
  }
}
async function remove(row: AlbumItem) {
  try {
    await ElMessageBox.confirm(
      "删除相册“" + row.title + "”及图集编排，媒体库原图会保留。",
      "删除相册",
      {
        type: "warning",
        confirmButtonText: "删除相册",
        cancelButtonText: "取消"
      }
    );
    await deleteAlbum(row.id);
    await load();
  } catch (e: any) {
    if (e !== "cancel" && e !== "close") message("删除失败", { type: "error" });
  }
}
onMounted(load);
</script>
<template>
  <div class="albums-page">
    <el-card shadow="never"
      ><template #header
        ><div class="toolbar">
          <div>
            <strong>相册管理</strong><small>仅已发布相册向访客展示</small>
          </div>
          <div>
            <el-button @click="load">刷新相册</el-button
            ><el-button type="primary" @click="edit()">新建相册</el-button
            ><el-button
              tag="a"
              href="https://www.preview.replow.org/gallery/"
              target="_blank"
              rel="noopener"
              >查看主站相册</el-button
            >
          </div>
        </div></template
      >
      <div v-loading="loading" class="album-grid">
        <article v-for="row in albums" :key="row.id" class="album-card">
          <el-image
            v-if="row.resolved_cover"
            :src="row.resolved_cover"
            fit="cover"
          />
          <div v-else class="empty-cover">还没有封面</div>
          <div class="album-info">
            <div class="title">
              <strong>{{ row.title }}</strong
              ><el-tag :type="row.is_published ? 'success' : 'info'">{{
                row.is_published ? "已发布" : "草稿"
              }}</el-tag>
            </div>
            <p>{{ row.description || "暂无说明" }}</p>
            <small
              >{{ row.photo_count || 0 }} 张图片 · 排序
              {{ row.sort_order }}</small
            >
            <div class="actions">
              <el-button @click="manage(row)">管理图片</el-button
              ><el-button @click="edit(row)">编辑相册</el-button
              ><el-button type="danger" text @click="remove(row)"
                >删除</el-button
              >
            </div>
          </div>
        </article>
      </div>
      <el-empty
        v-if="!loading && !albums.length"
        description="创建第一本相册，从媒体库挑选要分享的图片"
    /></el-card>
    <el-dialog
      v-model="editor"
      :title="editingId ? '编辑相册' : '新建相册'"
      width="min(94vw,680px)"
      :before-close="closeEditor"
      :close-on-click-modal="false"
      ><el-form label-position="top"
        ><el-form-item label="相册名称"
          ><el-input
            v-model="form.title"
            maxlength="100"
            aria-label="相册名称" /></el-form-item
        ><el-form-item label="相册说明"
          ><el-input
            v-model="form.description"
            type="textarea"
            :rows="3"
            maxlength="1000"
            aria-label="相册说明" /></el-form-item
        ><el-form-item label="封面（留空使用第一张图片）"
          ><MediaPicker
            v-model="form.cover_url"
            category="article" /></el-form-item
        ><el-form-item label="排序（越小越靠前）"
          ><el-input-number
            v-model="form.sort_order"
            :min="-100000"
            :max="100000" /></el-form-item
        ><el-form-item label="向访客公开"
          ><el-switch
            v-model="form.is_published"
            aria-label="向访客公开"
          /><span class="switch-note">{{
            form.is_published ? "保存后公开展示" : "保存为草稿"
          }}</span></el-form-item
        ></el-form
      ><template #footer
        ><el-button @click="closeEditor()">取消</el-button
        ><el-button type="primary" :loading="saving" @click="save"
          >保存相册</el-button
        ></template
      ></el-dialog
    >
    <el-dialog
      v-model="photoEditor"
      :title="'管理图片 · ' + (activeAlbum?.title || '')"
      width="min(96vw,960px)"
      class="photo-editor"
      :before-close="closePhotos"
      :close-on-click-modal="false"
      ><div class="photo-toolbar">
        <el-button type="primary" @click="openLibrary">从媒体库添加</el-button
        ><el-button :loading="uploading" @click="fileInput?.click()"
          >上传图片</el-button
        ><small>拖动替代操作：使用上移／下移按钮调整顺序，保存后生效。</small>
      </div>
      <input
        ref="fileInput"
        type="file"
        accept="image/jpeg,image/png,image/webp,image/gif,image/avif,image/heic,image/heif"
        hidden
        @change="upload"
      />
      <div v-if="uploading" class="upload-progress">
        <el-progress :percentage="uploadPercent" :stroke-width="5" :show-text="false" />
        <small>{{ uploadStage }}</small>
      </div>
      <div class="photo-list">
        <article
          v-for="(photo, index) in photos"
          :key="photo.media_id"
          class="photo-row"
        >
          <el-image :src="photo.public_url" fit="cover" />
          <div>
            <small>{{ index + 1 }} · {{ photo.original_name }}</small
            ><el-input
              v-model="photo.caption"
              placeholder="图片说明 / 替代文本"
              maxlength="500"
              aria-label="图片说明"
            />
            <div class="actions">
              <el-button :disabled="index === 0" @click="move(index, -1)"
                >上移</el-button
              ><el-button
                :disabled="index === photos.length - 1"
                @click="move(index, 1)"
                >下移</el-button
              ><el-button type="danger" text @click="photos.splice(index, 1)"
                >移出相册</el-button
              >
            </div>
          </div>
        </article>
      </div>
      <el-empty v-if="!photos.length" description="还没有图片" /><template
        #footer
        ><span class="muted">{{ photosDirty ? "有未保存修改" : "已保存" }}</span
        ><el-button @click="closePhotos()">关闭</el-button
        ><el-button type="primary" :loading="saving" @click="savePhotos"
          >保存图片列表</el-button
        ></template
      ></el-dialog
    >
    <el-dialog
      v-model="libraryOpen"
      title="从媒体库添加图片"
      class="album-library-dialog"
      width="min(94vw,900px)"
      ><p>已在相册中的图片会自动去重。已选择 {{ chosen.length }} 张。</p>
      <div class="library-grid">
        <button
          v-for="item in media"
          :key="item.id"
          type="button"
          :aria-pressed="chosen.includes(item.id)"
          :class="{ selected: chosen.includes(item.id) }"
          @click="toggle(item.id)"
        >
          <img
            :src="item.public_url"
            :alt="item.original_name"
            loading="lazy"
          /><span>{{ item.original_name }}</span>
        </button>
      </div>
      <el-empty
        v-if="!media.length"
        description="媒体库暂无图片，请先上传"
      /><template #footer
        ><el-button @click="libraryOpen = false">取消</el-button
        ><el-button type="primary" :disabled="!chosen.length" @click="add"
          >添加所选图片</el-button
        ></template
      ></el-dialog
    >
  </div>
</template>
<style scoped>
.upload-progress { margin: 10px 0; }
.upload-progress small { color: var(--el-text-color-secondary); }
.toolbar,
.toolbar > div:last-child,
.title,
.actions,
.photo-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.toolbar {
  justify-content: space-between;
}
.toolbar > div:first-child {
  display: grid;
  gap: 5px;
}
.toolbar small,
.album-info small,
.muted,
.photo-toolbar small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.album-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
  gap: 18px;
}
.album-card {
  border: 1px solid var(--el-border-color-light);
  border-radius: 14px;
  overflow: hidden;
}
.album-card > .el-image,
.empty-cover {
  width: 100%;
  height: 180px;
  background: var(--el-fill-color-light);
}
.empty-cover {
  display: grid;
  place-items: center;
  color: var(--el-text-color-secondary);
}
.album-info {
  padding: 16px;
}
.title {
  justify-content: space-between;
}
.album-info p {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 13px;
}
.actions {
  margin-top: 14px;
}
.actions .el-button + .el-button {
  margin-left: 0;
}
.photo-toolbar {
  margin-bottom: 18px;
}
.photo-list {
  display: grid;
  gap: 14px;
}
.photo-row {
  display: flex;
  gap: 16px;
  padding: 12px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 12px;
}
.photo-row > .el-image {
  width: 100px;
  height: 110px;
  flex-shrink: 0;
}
.photo-row > div:last-child {
  min-width: 0;
  flex: 1;
  display: grid;
  gap: 10px;
}
.photo-row small {
  overflow-wrap: anywhere;
}
.switch-note {
  margin-left: 12px;
}
.library-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
  gap: 10px;
}
.library-grid button {
  border: 2px solid transparent;
  border-radius: 10px;
  padding: 8px;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-primary);
  text-align: left;
  cursor: pointer;
}
.library-grid .selected {
  border-color: var(--el-color-primary);
}
.library-grid img {
  width: 100%;
  height: 110px;
  object-fit: cover;
  border-radius: 6px;
}
.library-grid span {
  display: block;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.muted {
  margin-right: 12px;
}
@media (max-width: 600px) {
  .photo-row {
    flex-direction: column;
  }
  .photo-row > .el-image {
    width: 100%;
    height: 160px;
  }
  .album-grid {
    grid-template-columns: 1fr;
  }
}
</style>
<style>
.album-library-dialog .el-dialog__body {
  max-height: 65dvh;
  overflow: auto;
}
.photo-editor .el-dialog__body {
  max-height: 68dvh;
  overflow: auto;
}
.photo-editor .el-dialog__footer {
  position: sticky;
  bottom: 0;
  background: var(--el-bg-color);
  padding-top: 12px;
  border-top: 1px solid var(--el-border-color-light);
}
</style>

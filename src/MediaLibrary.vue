<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { humanError } from "./api";
import { mediaApi, uploadMedia, type MediaCategory, type MediaItem } from "./media";

const props = withDefaults(defineProps<{
  picker?: boolean;
  imageOnly?: boolean;
  category?: MediaCategory;
}>(), {picker: false, imageOnly: false, category: "site"});
const emit = defineEmits<{
  select: [item: MediaItem];
  close: [];
}>();
const rows = ref<MediaItem[]>([]);
const total = ref(0);
const trash = ref(false);
const references = ref<{type:string;title:string}[]>([]);
async function showReferences(item:MediaItem) {
  try { const r=await mediaApi.references(item.id); references.value=r.data.items; error.value=r.data.total ? `仍有 ${r.data.total} 处引用，请先解除引用后再删除` : "暂无引用"; }
  catch(err) { error.value=humanError(err); }
}
async function restore(item:MediaItem) {
  try { await mediaApi.restore(item.id); await load(); } catch(err) { error.value=humanError(err); }
}
async function purge(item:MediaItem) {
  if (!window.confirm(`彻底删除“${item.original_name}”？原文件无法恢复。`)) return;
  try { await mediaApi.purge(item.id); await load(); } catch(err) { error.value=humanError(err); }
}
const offset = ref(0);
const pageSize = 60;
const loading = ref(false);
const uploading = ref(false);
const progress = ref(0);
const error = ref("");
const category = ref<MediaCategory>(props.category);
const fileInput = ref<HTMLInputElement | null>(null);
const selected = ref<MediaItem | null>(null);
const visible = computed(() => props.imageOnly
  ? rows.value.filter(item => item.mime_type.startsWith("image/"))
  : rows.value);
const fmtSize = (bytes: number) =>
  bytes < 1024 ? `${bytes} B` : bytes < 1048576
    ? `${(bytes / 1024).toFixed(1)} KB`
    : `${(bytes / 1048576).toFixed(1)} MB`;
const fmtDate = (value: string) =>
  value ? new Date(value).toLocaleString("zh-CN", {hour12: false}) : "—";

async function load(reset = false) {
  if (reset) offset.value = 0;
  loading.value = true;
  error.value = "";
  try {
    const result = await mediaApi.list(pageSize, offset.value, trash.value);
    rows.value = result.items || [];
    total.value = result.total || 0;
    if (selected.value)
      selected.value = rows.value.find(row => row.id === selected.value?.id) || null;
  } catch (err) {
    error.value = humanError(err);
  } finally {
    loading.value = false;
  }
}

async function upload(event: Event) {
  const element = event.target as HTMLInputElement;
  const file = element.files?.[0];
  element.value = "";
  if (!file) return;
  if ((props.imageOnly || category.value !== "site") && !file.type.startsWith("image/")) {
    error.value = "请上传图片文件";
    return;
  }
  uploading.value = true;
  progress.value = 0;
  error.value = "";
  try {
    const item = await uploadMedia(file, category.value, value => {progress.value = Math.round(value * 100);});
    await load(true);
    selected.value = item;
    // Uploading from the avatar or article picker means 'upload and use'.
    if (props.picker) emit("select", item);
  } catch (err) {
    error.value = err instanceof Error && /^(文件|暂不|头像|浏览器|云存储)/.test(err.message)
      ? err.message : humanError(err);
  } finally {
    uploading.value = false;
  }
}

async function rename(item: MediaItem) {
  const ext = item.original_name.match(/\.[^.]+$/)?.[0] || "";
  const raw = window.prompt("修改文件名称（保留原扩展名）", item.original_name);
  if (raw === null || raw.trim() === item.original_name) return;
  const name = raw.trim();
  if (ext && !name.toLowerCase().endsWith(ext.toLowerCase())) {
    error.value = "文件扩展名不能修改";
    return;
  }
  try {
    const result = await mediaApi.rename(item.id, name);
    rows.value = rows.value.map(row => row.id === item.id ? result.data : row);
    selected.value = result.data;
    error.value = "";
  } catch (err) { error.value = humanError(err); }
}

async function remove(item: MediaItem) {
  try {
    const refs=await mediaApi.references(item.id);
    if(refs.data.total) { await showReferences(item); return; }
    if (!window.confirm(`将“${item.original_name}”移入回收站？原文件保留，可以恢复。`)) return;
    await mediaApi.delete(item.id);
    selected.value = null;
    await load();
  } catch (err) { error.value = humanError(err); }
}

async function copyLink(item: MediaItem) {
  try { await navigator.clipboard.writeText(item.public_url); error.value = "链接已复制"; }
  catch { error.value = "复制失败，请手动复制链接"; }
}

onMounted(() => void load());
</script>

<template>
  <div class="my-media">
    <div class="my-media-toolbar">
      <div>
        <h2>{{ trash ? "我的回收站" : picker ? "从我的媒体库选择" : "我的媒体库" }}</h2>
        <p>仅显示当前账号上传的文件，共 {{ total }} 个。</p>
      </div>
      <div class="my-media-tools">
        <button v-if="!picker" class="btn btn-soft" @click="trash=!trash;references=[];load(true)">{{ trash ? "返回媒体库" : "回收站" }}</button>
        <select v-model="category" class="select" :disabled="picker || uploading">
          <option value="site">通用文件</option>
          <option value="avatar">用户头像</option>
          <option value="article">文章图片</option>
        </select>
        <input ref="fileInput" hidden type="file"
          :accept="imageOnly || category !== 'site' ? 'image/*,.heic,.heif' : '.jpg,.jpeg,.png,.gif,.webp,.avif,.bmp,.heic,.heif,.pdf,.txt,.epub,.zip,.mp3,.mp4,.webm,.ogg,.wav,.flac'"
          @change="upload"/>
        <button v-if="!trash" class="btn btn-primary" :disabled="uploading" @click="fileInput?.click()">
          {{ uploading ? `上传中 ${progress}%` : "上传文件" }}
        </button>
        <button class="btn btn-soft" :disabled="loading || uploading" @click="load()">刷新</button>
        <button v-if="picker" class="btn btn-ghost" @click="emit('close')">关闭</button>
      </div>
    </div>
    <div v-if="uploading" class="my-media-progress"><div :style="{width: progress+'%'}"></div></div>
    <p v-if="error" class="my-media-feedback" role="status">{{ error }}</p>
    <ul v-if="references.length"><li v-for="(item,index) in references" :key="index">{{ item.type }} · {{ item.title }}</li></ul>
    <p v-if="loading" class="empty">正在加载媒体文件…</p>
    <div v-else-if="!visible.length" class="empty">{{ imageOnly ? "这一页没有可选择的图片" : "还没有上传文件" }}</div>
    <div v-else class="my-media-grid">
      <article v-for="item in visible" :key="item.id"
        class="my-media-item" :class="{active: selected?.id === item.id}"
        @click="selected = item">
        <img v-if="item.mime_type.startsWith('image/')" :src="item.public_url" :alt="item.original_name" loading="lazy"/>
        <div v-else class="my-media-file">{{ item.original_name.split('.').pop()?.toUpperCase() || "FILE" }}</div>
        <div class="my-media-file-name" :title="item.original_name">{{ item.original_name }}</div>
        <div class="my-media-secondary">{{ fmtSize(item.byte_size) }} · {{ item.storage_backend.toUpperCase() }}</div>
        <div class="my-media-actions">
          <button v-if="picker" class="link-button" @click.stop="emit('select', item)">使用</button>
          <button class="link-button" @click.stop="selected=item; rename(item)">改名</button>
          <button class="link-button" @click.stop="selected=item; copyLink(item)">复制</button>
          <template v-if="trash"><button class="link-button" @click.stop="restore(item)">恢复</button><button class="link-button danger" @click.stop="purge(item)">彻底删除</button></template>
          <template v-else><button class="link-button" @click.stop="showReferences(item)">引用</button><button class="link-button danger" @click.stop="remove(item)">移入回收站</button></template>
        </div>
      </article>
    </div>
    <div v-if="selected" class="my-media-details">
      <strong>文件详情</strong>
      <span>{{ selected.original_name }} · {{ selected.mime_type }} · {{ fmtSize(selected.byte_size) }}</span>
      <span>{{ fmtDate(selected.created_at) }} · {{ selected.category }}</span>
      <a :href="selected.public_url" target="_blank" rel="noopener noreferrer">查看文件</a>
    </div>
    <div v-if="total > pageSize" class="my-media-pagination">
      <button class="btn btn-soft" :disabled="loading || offset === 0" @click="offset=Math.max(0,offset-pageSize);load()">上一页</button>
      <span>{{ offset + 1 }}–{{ Math.min(offset+pageSize,total) }} / {{ total }}</span>
      <button class="btn btn-soft" :disabled="loading || offset+pageSize >= total" @click="offset+=pageSize;load()">下一页</button>
    </div>
  </div>
</template>

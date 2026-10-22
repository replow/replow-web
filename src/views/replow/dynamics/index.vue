<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import { ElMessageBox } from "element-plus";
import MediaPicker from "@/components/MediaPicker.vue";
import {
  getDynamics,
  saveDynamic,
  deleteDynamic,
  type DynamicItem,
  type DynamicImage
} from "@/api/dynamics";
import { message } from "@/utils/message";

defineOptions({ name: "ReplowDynamics" });
const rows = ref<DynamicItem[]>([]),
  total = ref(0),
  page = ref(1),
  search = ref(""),
  state = ref("");
const loading = ref(false),
  saving = ref(false),
  editor = ref(false),
  editingId = ref<number>(),
  imageUrl = ref(""),
  baseline = ref("");
const form = reactive({
  content: "",
  images: [] as DynamicImage[],
  location: "",
  pinned: false,
  is_published: false,
  published_at: new Date() as Date | null
});
const dirty = computed(
  () => editor.value && JSON.stringify(form) !== baseline.value
);
function dateLabel(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "Asia/Shanghai"
  }).format(new Date(value));
}
function visibility(item: DynamicItem) {
  return !item.is_published
    ? "草稿"
    : new Date(item.published_at).getTime() > Date.now()
      ? "定时发布"
      : "已发布";
}
async function load() {
  loading.value = true;
  try {
    const result = await getDynamics({
      limit: 20,
      offset: (page.value - 1) * 20,
      search: search.value.trim(),
      state: state.value
    });
    rows.value = result.items;
    total.value = result.total;
  } catch {
    message("动态读取失败", { type: "error" });
  } finally {
    loading.value = false;
  }
}
function filter() {
  page.value = 1;
  void load();
}
function edit(item?: DynamicItem) {
  editingId.value = item?.id;
  imageUrl.value = "";
  Object.assign(form, {
    content: item?.content || "",
    images: item ? item.images.map(i => ({ ...i })) : [],
    location: item?.location || "",
    pinned: item?.pinned || false,
    is_published: item?.is_published || false,
    published_at: item ? new Date(item.published_at) : new Date()
  });
  baseline.value = JSON.stringify(form);
  editor.value = true;
}
async function discard() {
  if (!dirty.value) return true;
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
  if (!saving.value && (await discard())) {
    editor.value = false;
    done?.();
  }
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value) {
    event.preventDefault();
    event.returnValue = "";
  }
}
onBeforeRouteLeave(async () => await discard());
onMounted(() => {
  void load();
  window.addEventListener("beforeunload", beforeUnload);
});
onUnmounted(() => window.removeEventListener("beforeunload", beforeUnload));
function addImage() {
  let url: URL;
  try {
    url = new URL(imageUrl.value.trim());
  } catch {
    message("请先上传、选择或填写图片地址", { type: "warning" });
    return;
  }
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password
  ) {
    message("图片地址必须使用 HTTP 或 HTTPS", { type: "warning" });
    return;
  }
  if (form.images.length >= 9) {
    message("每条动态最多 9 张图片", { type: "warning" });
    return;
  }
  form.images.push({ src: url.href, alt: "" });
  imageUrl.value = "";
}
function move(index: number, delta: number) {
  const target = index + delta;
  if (target < 0 || target >= form.images.length) return;
  [form.images[index], form.images[target]] = [
    form.images[target],
    form.images[index]
  ];
}
async function save() {
  if ((!form.content.trim() && !form.images.length) || !form.published_at) {
    message("请填写正文或添加图片，并选择发布时间", { type: "warning" });
    return;
  }
  saving.value = true;
  try {
    await saveDynamic(
      {
        ...form,
        content: form.content.trim(),
        location: form.location.trim(),
        published_at: form.published_at.toISOString()
      },
      editingId.value
    );
    editor.value = false;
    message("动态已保存", { type: "success" });
    await load();
  } catch {
    message("动态保存失败，请检查正文、图片及发布时间", { type: "error" });
  } finally {
    saving.value = false;
  }
}
async function toggle(item: DynamicItem) {
  try {
    await ElMessageBox.confirm(
      item.is_published
        ? "撤下后，主站将不再显示这条动态。"
        : "发布后，访客即可在主站查看这条动态。",
      "更改可见性",
      {
        confirmButtonText: item.is_published ? "撤为草稿" : "确认发布",
        cancelButtonText: "取消",
        type: "warning"
      }
    );
    await saveDynamic({ is_published: !item.is_published }, item.id);
    message("可见性已更新", { type: "success" });
    await load();
  } catch (error) {
    if (error !== "cancel" && error !== "close")
      message("状态更新失败", { type: "error" });
  }
}
async function pin(item: DynamicItem) {
  try {
    await saveDynamic({ pinned: !item.pinned }, item.id);
    await load();
  } catch {
    message("置顶状态更新失败", { type: "error" });
  }
}
async function remove(item: DynamicItem) {
  try {
    await ElMessageBox.confirm(
      "确定删除这条动态？媒体库中的原图会保留。",
      "删除动态",
      { confirmButtonText: "删除", cancelButtonText: "取消", type: "warning" }
    );
    await deleteDynamic(item.id);
    if (rows.value.length === 1 && page.value > 1) page.value--;
    message("动态已删除", { type: "success" });
    await load();
  } catch (error) {
    if (error !== "cancel" && error !== "close")
      message("动态删除失败", { type: "error" });
  }
}
</script>

<template>
  <div class="dynamics-page">
    <el-card shadow="never">
      <div class="page-heading">
        <div>
          <h2>动态管理</h2>
          <p>记录日常与灵感，发布后会自动显示在主站动态页。</p>
        </div>
        <el-button type="primary" @click="edit()">新建动态</el-button>
      </div>
      <div class="filters">
        <el-input
          v-model="search"
          placeholder="搜索正文或地点"
          clearable
          @keyup.enter="filter"
          @clear="filter"
        />
        <el-select v-model="state" @change="filter"
          ><el-option label="全部状态" value="" /><el-option
            label="已发布 / 定时发布"
            value="published" /><el-option label="草稿" value="draft"
        /></el-select>
        <el-button :loading="loading" @click="filter">搜索</el-button>
        <a
          href="https://www.replow.org/dynamic/"
          target="_blank"
          rel="noopener noreferrer"
          >查看主站动态 ↗</a
        >
      </div>
    </el-card>
    <div v-loading="loading" class="dynamic-list">
      <el-card
        v-for="item in rows"
        :key="item.id"
        shadow="never"
        class="dynamic-card"
        :data-dynamic-id="item.id"
      >
        <div class="card-meta">
          <el-tag :type="item.is_published ? 'success' : 'info'">{{
            visibility(item)
          }}</el-tag
          ><el-tag v-if="item.pinned" type="warning">置顶</el-tag
          ><time>{{ dateLabel(item.published_at) }}</time
          ><span v-if="item.location">{{ item.location }}</span>
        </div>
        <p class="dynamic-content">{{ item.content }}</p>
        <div v-if="item.images.length" class="card-images">
          <el-image
            v-for="image in item.images"
            :key="image.src"
            :src="image.src"
            :alt="image.alt"
            fit="cover"
            lazy
            :preview-src-list="item.images.map(i => i.src)"
            preview-teleported
          />
        </div>
        <div class="card-actions">
          <el-button type="primary" text @click="edit(item)">编辑</el-button
          ><el-button text @click="pin(item)">{{
            item.pinned ? "取消置顶" : "置顶"
          }}</el-button
          ><el-button text @click="toggle(item)">{{
            item.is_published ? "撤为草稿" : "发布"
          }}</el-button
          ><el-button type="danger" text @click="remove(item)">删除</el-button>
        </div>
      </el-card>
      <el-empty
        v-if="!loading && !rows.length"
        description="暂无动态，写下新的灵感吧。"
      />
    </div>
    <el-pagination
      v-if="total > 20"
      v-model:current-page="page"
      :page-size="20"
      :total="total"
      layout="prev, pager, next"
      @current-change="load"
    />
    <el-dialog
      v-model="editor"
      :title="editingId ? '编辑动态' : '新建动态'"
      width="min(94vw, 780px)"
      class="dynamic-editor"
      :before-close="closeEditor"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <el-form label-position="top" :disabled="saving">
        <el-form-item label="动态正文"
          ><el-input
            v-model="form.content"
            type="textarea"
            :rows="6"
            maxlength="20000"
            show-word-limit
            placeholder="记录此刻的想法……支持 Markdown。"
        /></el-form-item>
        <el-form-item label="图片（最多 9 张）">
          <div class="image-controls">
            <MediaPicker v-model="imageUrl" category="article" /><el-button
              :disabled="!imageUrl || form.images.length >= 9"
              @click="addImage"
              >添加到动态</el-button
            >
          </div>
        </el-form-item>
        <div v-if="form.images.length" class="editor-images">
          <div
            v-for="(image, index) in form.images"
            :key="index"
            class="editor-image"
          >
            <el-image :src="image.src" :alt="image.alt" fit="cover" />
            <el-input
              v-model="image.alt"
              maxlength="200"
              placeholder="图片说明（可选）"
            />
            <div>
              <el-button text :disabled="index === 0" @click="move(index, -1)"
                >前移</el-button
              ><el-button
                text
                :disabled="index === form.images.length - 1"
                @click="move(index, 1)"
                >后移</el-button
              ><el-button
                text
                type="danger"
                @click="form.images.splice(index, 1)"
                >移除</el-button
              >
            </div>
          </div>
        </div>
        <div class="editor-options">
          <el-form-item label="地点（可选）"
            ><el-input
              v-model="form.location"
              maxlength="160"
              placeholder="例如：无锡"
          /></el-form-item>
          <el-form-item label="发布时间"
            ><el-date-picker
              v-model="form.published_at"
              type="datetime"
              placeholder="选择时间"
              style="width: 100%"
          /></el-form-item>
          <el-form-item label="可见性"
            ><el-select v-model="form.is_published" style="width: 100%"
              ><el-option label="草稿（仅后台可见）" :value="false" /><el-option
                label="公开发布"
                :value="true" /></el-select
          ></el-form-item>
          <el-form-item label="置顶"
            ><el-switch v-model="form.pinned" active-text="置顶显示"
          /></el-form-item>
        </div>
        <p class="editor-hint">
          选择未来时间并公开发布，可定时展示。图片移除或删除动态不会删除媒体库原图。
        </p>
      </el-form>
      <template #footer
        ><el-button :disabled="saving" @click="closeEditor()">取消</el-button
        ><el-button type="primary" :loading="saving" @click="save"
          >保存动态</el-button
        ></template
      >
    </el-dialog>
  </div>
</template>

<style scoped>
.dynamics-page {
  display: grid;
  gap: 16px;
  min-width: 0;
}
.page-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}
.page-heading h2 {
  font-size: 20px;
  font-weight: 650;
}
.page-heading p,
.editor-hint {
  color: var(--el-text-color-secondary);
  margin-top: 6px;
  font-size: 13px;
}
.filters {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
  margin-top: 20px;
}
.filters > .el-input {
  max-width: 300px;
}
.filters > .el-select {
  width: 180px;
}
.filters > a {
  font-size: 13px;
  color: var(--el-color-primary);
}
.dynamic-list {
  display: grid;
  gap: 16px;
  min-height: 120px;
}
.card-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.dynamic-content {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  line-height: 1.8;
  margin: 18px 0;
  max-height: 260px;
  overflow: auto;
}
.card-images {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(90px, 130px));
  gap: 10px;
}
.card-images .el-image {
  height: 100px;
  border-radius: 10px;
  width: 100%;
}
.card-actions {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  justify-content: flex-end;
  margin-top: 16px;
}
.image-controls {
  width: 100%;
  display: grid;
  gap: 10px;
  justify-items: start;
}
.image-controls > .media-picker {
  width: 100%;
}
.editor-images {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 22px;
}
.editor-image {
  min-width: 0;
  display: grid;
  gap: 6px;
}
.editor-image > .el-image {
  height: 130px;
  width: 100%;
  border-radius: 10px;
}
.editor-image > div {
  display: flex;
  flex-wrap: wrap;
}
.editor-options {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 20px;
}
:global(.dynamic-editor .el-dialog__body) {
  max-height: calc(100dvh - 190px);
  overflow: auto;
}
:global(.dynamic-editor .el-dialog__footer) {
  position: sticky;
  bottom: 0;
  background: var(--el-bg-color);
  padding-top: 14px;
  border-top: 1px solid var(--el-border-color-lighter);
}
@media (max-width: 600px) {
  .page-heading {
    align-items: flex-start;
  }
  .page-heading p {
    max-width: 220px;
  }
  .filters > .el-input,
  .filters > .el-select {
    max-width: none;
    flex: 1;
    min-width: 130px;
  }
  .filters > a {
    width: 100%;
  }
  .editor-images {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .editor-options {
    grid-template-columns: 1fr;
  }
  .card-actions {
    justify-content: flex-start;
  }
  .card-meta {
    gap: 7px;
  }
  .card-images {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .card-images .el-image {
    height: 90px;
  }
}
</style>

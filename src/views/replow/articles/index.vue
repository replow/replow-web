<script setup lang="ts">
import { nextTick, onMounted, reactive, ref } from "vue";
import { ElMessageBox, type FormInstance } from "element-plus";
import {
  createArticle,
  deleteArticle,
  getAdminArticle,
  getAdminArticles,
  updateArticle,
  type ArticleItem,
  type ArticlePayload
} from "@/api/replow";
import { message } from "@/utils/message";
import { useArticleDraft } from "@/composables/useArticleDraft";
import ArticleVersions from "@/components/ArticleVersions.vue";
import { getToken } from "@/utils/auth";
import { contentError } from "@/api/contentTools";
import MediaPicker from "@/components/MediaPicker.vue";

defineOptions({ name: "ReplowArticles" });

type ArticleForm = {
  _base_token: string;
  title: string;
  slug: string;
  excerpt: string;
  body_markdown: string;
  cover_url: string;
  icon_url: string;
  category: string;
  tagsText: string;
  status: ArticlePayload["status"];
  is_pinned: boolean;
};

const loading = ref(false);
const saving = ref(false);
const editingLoading = ref(false);
const search = ref("");
const rows = ref<ArticleItem[]>([]);
const total = ref(0);
const dialogVisible = ref(false);
const editingId = ref<number | null>(null);
const slugTouched = ref(false);
const formRef = ref<FormInstance>();
const fileInput = ref<HTMLInputElement>();

const emptyForm = (): ArticleForm => ({
  _base_token: "",
  title: "",
  slug: "",
  excerpt: "",
  body_markdown: "",
  cover_url: "",
  icon_url: "",
  category: "",
  tagsText: "",
  status: "draft",
  is_pinned: false
});

const form = reactive<ArticleForm>(emptyForm());
const revisionToken = ref("");
const draft = useArticleDraft(form, dialogVisible, editingId, () => {
  try { return JSON.parse(atob(getToken().accessToken.split(".")[1])).sub; } catch { return "unknown"; }
}, async () => {
  try { await ElMessageBox.confirm("发现尚未提交的自动保存草稿，是否恢复到编辑器？", "恢复草稿", {confirmButtonText:"恢复草稿",cancelButtonText:"使用当前文章"}); return true; } catch { return false; }
});
async function restored(article: Record<string,unknown>) {
  applyArticle(article as ArticleItem);
  await draft.clear();
  await load();
  await draft.begin();
}
const rules = {
  title: [{ required: true, message: "请输入文章标题", trigger: "blur" }],
  body_markdown: [{ required: true, message: "请输入 Markdown 正文", trigger: "blur" }]
};

async function load() {
  loading.value = true;
  try {
    const result = await getAdminArticles({ limit: 100, search: search.value || undefined });
    rows.value = result.items || [];
    total.value = result.total || 0;
  } catch {
    message("文章读取失败", { type: "error" });
  } finally {
    loading.value = false;
  }
}

function resetForm() {
  Object.assign(form, emptyForm());
  editingId.value = null;
  slugTouched.value = false;
  nextTick(() => formRef.value?.clearValidate());
}

function applyArticle(article: ArticleItem) {
  revisionToken.value = article.revision_token || "";
  form._base_token = revisionToken.value;
  Object.assign(form, {
    title: article.title || "",
    slug: article.slug || "",
    excerpt: article.excerpt || "",
    body_markdown: article.body_markdown || "",
    cover_url: article.cover_url || "",
    icon_url: article.icon_url || "",
    category: article.category || "",
    tagsText: Array.isArray(article.tags) ? article.tags.join(", ") : "",
    status: article.status || "draft",
    is_pinned: Boolean(article.is_pinned)
  });
}

async function openCreate() {
  resetForm(); revisionToken.value = "";
  dialogVisible.value = true;
  await draft.begin();
}

async function openEdit(row: ArticleItem) {
  editingId.value = row.id;
  slugTouched.value = true;
  applyArticle(row);
  dialogVisible.value = true;
  editingLoading.value = true;
  try {
    const result = await getAdminArticle(row.id);
    if (result.data) applyArticle(result.data);
    await draft.begin();
  } catch {
    message("文章详情读取失败，已显示列表中的内容", { type: "warning" });
  } finally {
    editingLoading.value = false;
  }
}

function slugify(value: string) {
  const slug = value
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/[\s-]+/g, "-");
  return slug || `article-${Date.now()}`;
}

function handleTitleInput() {
  if (!slugTouched.value) form.slug = slugify(form.title);
}

function payload(): ArticlePayload {
  return {
    _base_token: form._base_token || undefined,
    title: form.title.trim(),
    slug: form.slug.trim() || slugify(form.title),
    excerpt: form.excerpt.trim(),
    body_markdown: form.body_markdown,
    cover_url: form.cover_url.trim(),
    icon_url: form.icon_url.trim(),
    category: form.category.trim(),
    tags: form.tagsText
      .replaceAll("，", ",")
      .split(",")
      .map(tag => tag.trim())
      .filter(Boolean),
    status: form.status,
    is_pinned: form.is_pinned
  };
}

function errorText(error: any, fallback: string) {
  const detail = error?.response?.data?.detail;
  const labels: Record<string, string> = {
    article_slug_already_exists: "文章 slug 已存在，请换一个",
    body_markdown_required: "文章正文不能为空",
    invalid_article_status: "文章状态无效",
    title_required: "文章标题不能为空"
  };
  return labels[detail] || contentError(error, fallback);
}

async function save() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return;
  saving.value = true;
  try {
    const data = payload();
    if (editingId.value) {
      await updateArticle(editingId.value, data);
      message("文章已更新", { type: "success" });
    } else {
      await createArticle(data);
      message("文章已创建", { type: "success" });
    }
    await draft.clear();
    dialogVisible.value = false;
    await load();
  } catch (error) {
    message(errorText(error, "文章保存失败"), { type: "error" });
  } finally {
    saving.value = false;
  }
}

async function remove(row: ArticleItem) {
  try {
    await ElMessageBox.confirm(
      `确定删除《${row.title}》吗？文章下的评论也会一并删除，此操作不可撤销。`,
      "删除文章",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }
    );
    await deleteArticle(row.id);
    message("文章已删除", { type: "success" });
    await load();
  } catch (error: any) {
    if (error !== "cancel" && error !== "close") {
      message(errorText(error, "文章删除失败"), { type: "error" });
    }
  }
}

function formatDate(value: string) {
  return value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
}

function statusLabel(status: string) {
  return { published: "已发布", draft: "草稿", pending: "待审核", rejected: "已拒绝" }[status] || status;
}

async function importMarkdown(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  try {
    const raw = await file.text();
    let body = raw;
    const frontMatter = raw.match(/^---\s*\r?\n([\s\S]*?)\r?\n---\s*\r?\n?/);
    if (frontMatter) {
      body = raw.slice(frontMatter[0].length);
      for (const line of frontMatter[1].split(/\r?\n/)) {
        const separator = line.indexOf(":");
        if (separator < 0) continue;
        const key = line.slice(0, separator).trim().toLowerCase();
        let value = line.slice(separator + 1).trim().replace(/^['"]|['"]$/g, "");
        if (key === "tags") value = value.replace(/^\[|\]$/g, "").replaceAll("'", "");
        if (key === "title") form.title = value;
        if (key === "slug") {
          form.slug = value;
          slugTouched.value = Boolean(value);
        }
        if (key === "excerpt" || key === "description") form.excerpt = value;
        if (key === "category") form.category = value;
        if (key === "tags") form.tagsText = value;
        if (key === "cover" || key === "cover_url") form.cover_url = value;
        if (["draft", "pending", "published", "rejected"].includes(value)) {
          if (key === "status") form.status = value as ArticlePayload["status"];
        }
      }
    }
    if (!form.title) form.title = file.name.replace(/\.(md|markdown)$/i, "");
    if (!form.slug) form.slug = slugify(form.title);
    form.body_markdown = body.trim();
    message(`已导入 ${file.name}`, { type: "success" });
  } catch {
    message("Markdown 文件读取失败", { type: "error" });
  } finally {
    input.value = "";
  }
}

onMounted(load);
</script>

<template>
  <div class="page-wrap">
    <el-card shadow="never">
      <template #header>
        <div class="toolbar">
          <div><strong>文章管理</strong><span class="muted">共 {{ total }} 篇</span></div>
          <div class="toolbar-actions">
            <el-input v-model="search" clearable placeholder="搜索标题或 slug" @keyup.enter="load" />
            <el-button :loading="loading" @click="load">刷新</el-button>
            <el-button type="primary" @click="openCreate">新建 / 上传文章</el-button>
          </div>
        </div>
      </template>
      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column prop="title" label="标题" min-width="280" show-overflow-tooltip />
        <el-table-column prop="category" label="分类" width="120" show-overflow-tooltip />
        <el-table-column label="标签" min-width="180">
          <template #default="scope"><el-tag v-for="tag in scope.row.tags" :key="tag" size="small" class="tag">{{ tag }}</el-tag></template>
        </el-table-column>
        <el-table-column label="状态" width="110"><template #default="scope"><el-tag :type="scope.row.status === 'published' ? 'success' : 'warning'">{{ statusLabel(scope.row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="更新时间" width="190"><template #default="scope">{{ formatDate(scope.row.updated_at) }}</template></el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="scope">
            <el-button link type="primary" @click="openEdit(scope.row)">编辑</el-button>
            <el-button link type="danger" @click="remove(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-if="!loading && rows.length === 0" description="暂无文章" />
    </el-card>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑文章' : '新建文章'" width="min(94vw, 920px)" destroy-on-close>
      <el-alert :title="draft.status.value" type="info" :closable="false" style="margin-bottom:14px" />
      <el-form ref="formRef" :disabled="saving || editingLoading" v-loading="editingLoading" :model="form" :rules="rules" label-position="top" class="article-form">
        <el-row :gutter="18">
          <el-col :xs="24" :md="14"><el-form-item label="标题" prop="title"><el-input v-model="form.title" maxlength="200" show-word-limit @input="handleTitleInput" /></el-form-item></el-col>
          <el-col :xs="24" :md="10"><el-form-item label="Slug"><el-input v-model="form.slug" maxlength="220" @input="slugTouched = true"><template #append><el-button @click="form.slug = slugify(form.title); slugTouched = true">生成</el-button></template></el-input></el-form-item></el-col>
          <el-col :span="24"><el-form-item label="摘要"><el-input v-model="form.excerpt" maxlength="500" show-word-limit /></el-form-item></el-col>
          <el-col :xs="24" :md="12"><el-form-item label="分类"><el-input v-model="form.category" maxlength="100" /></el-form-item></el-col>
          <el-col :xs="24" :md="12"><el-form-item label="标签（逗号分隔）"><el-input v-model="form.tagsText" placeholder="例如：Astro, FastAPI" /></el-form-item></el-col>
          <el-col :xs="24" :md="12"><el-form-item label="文章封面"><MediaPicker v-model="form.cover_url" category="article-cover" /></el-form-item></el-col>
          <el-col :xs="24" :md="12"><el-form-item label="图标 URL"><el-input v-model="form.icon_url" placeholder="可选" /></el-form-item></el-col>
          <el-col :xs="24" :md="12"><el-form-item label="发布状态"><el-select v-model="form.status" class="full"><el-option label="草稿" value="draft" /><el-option label="待审核" value="pending" /><el-option label="已发布" value="published" /><el-option label="已拒绝" value="rejected" /></el-select></el-form-item></el-col>
          <el-col :xs="24" :md="12"><el-form-item label="置顶"><el-switch v-model="form.is_pinned" /></el-form-item></el-col>
          <el-col :span="24">
            <div class="import-box"><input ref="fileInput" type="file" accept=".md,.markdown,text/markdown" @change="importMarkdown" /><span>可导入 Markdown 文件；支持简单 YAML front matter。</span></div>
          </el-col>
          <el-col :span="24"><el-form-item label="Markdown 正文" prop="body_markdown"><el-input v-model="form.body_markdown" type="textarea" :rows="18" placeholder="在这里编写文章正文…" /></el-form-item></el-col>
        </el-row>
      </el-form>
      <template #footer><ArticleVersions v-if="editingId" :article-id="editingId" :current="form" :token="form._base_token" @restored="restored"/><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存文章</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-wrap { padding: 2px; }
.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
.toolbar > div:first-child { display: flex; gap: 12px; align-items: baseline; }
.muted { color: var(--el-text-color-secondary); font-size: 12px; }
.toolbar-actions { display: flex; gap: 10px; align-items: center; }
.toolbar-actions :deep(.el-input) { width: 240px; }
.tag { margin: 2px 5px 2px 0; }
.article-form { min-height: 240px; }
.full { width: 100%; }
.import-box { display: flex; align-items: center; gap: 12px; margin: 0 0 18px; padding: 11px 13px; border: 1px dashed var(--el-border-color); border-radius: 8px; color: var(--el-text-color-secondary); font-size: 12px; background: var(--el-fill-color-lighter); }
.import-box input { max-width: 240px; }
@media (max-width: 800px) { .toolbar { align-items: stretch; flex-direction: column; }.toolbar-actions { width: 100%; flex-wrap: wrap; }.toolbar-actions :deep(.el-input) { width: 100%; }.import-box { align-items: flex-start; flex-direction: column; } }
</style>

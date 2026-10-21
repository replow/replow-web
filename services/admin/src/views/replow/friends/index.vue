<script setup lang="ts">
import { computed, nextTick, onMounted, reactive, ref } from "vue";
import { ElMessageBox, type FormInstance, type FormRules } from "element-plus";
import {
  createFriend,
  deleteFriend,
  getAdminFriends,
  updateFriend,
  type FriendItem,
  type FriendPayload
} from "@/api/replow";
import { message } from "@/utils/message";

defineOptions({ name: "ReplowFriends" });

const loading = ref(false);
const saving = ref(false);
const rows = ref<FriendItem[]>([]);
const total = ref(0);
const categoryOptions = computed(() => [...new Set(rows.value.map(item => (item.category || "").trim()).filter(Boolean))]);
const dialogVisible = ref(false);
const editingId = ref<number | null>(null);
const formRef = ref<FormInstance>();
const languageOptions = [
  "WordPress",
  "Typecho",
  "Halo",
  "PHP",
  "Java",
  "HTML",
  "Hexo",
  "Astro",
  "Hugo",
  "Jekyll",
  "Vue",
  "React",
  "Next.js",
  "Nuxt",
  "Svelte",
  "Ghost",
  "Laravel",
  "Django",
  "Spring"
];

const emptyForm = (): FriendPayload => ({
  name: "",
  website_url: "",
  avatar_url: "",
  description: "",
  language: "",
  rss_url: "",
  category: "",
  sort_order: 0,
  is_enabled: true
});
const form = reactive<FriendPayload>(emptyForm());
const rules: FormRules = {
  name: [{ required: true, message: "请输入友链名称", trigger: "blur" }],
  website_url: [
    { required: true, message: "请输入网站地址", trigger: "blur" },
    { type: "url", message: "请输入有效的 HTTP 或 HTTPS 地址", trigger: "blur" }
  ]
};

async function load() {
  loading.value = true;
  try {
    const result = await getAdminFriends();
    rows.value = result.items || [];
    total.value = result.total || 0;
  } catch {
    message("友链读取失败", { type: "error" });
  } finally {
    loading.value = false;
  }
}

function resetForm() {
  Object.assign(form, emptyForm());
  editingId.value = null;
  nextTick(() => formRef.value?.clearValidate());
}

function openCreate() {
  resetForm();
  dialogVisible.value = true;
}

function openEdit(row: FriendItem) {
  editingId.value = row.id;
  Object.assign(form, {
    name: row.name || "",
    website_url: row.website_url || "",
    avatar_url: row.avatar_url || "",
    description: row.description || "",
    language: row.language || "",
    rss_url: row.rss_url || "",
    category: row.category || "",
    sort_order: row.sort_order || 0,
    is_enabled: Boolean(row.is_enabled)
  });
  dialogVisible.value = true;
}

function errorText(error: any, fallback: string) {
  const detail = error?.response?.data?.detail;
  const labels: Record<string, string> = {
    friend_name_required: "友链名称不能为空",
    website_url_required: "网站地址不能为空",
    invalid_website_url: "网站地址必须是 HTTP 或 HTTPS 地址",
    invalid_avatar_url: "头像地址必须是 HTTP 或 HTTPS 地址",
    invalid_rss_url: "RSS 地址必须是 HTTP 或 HTTPS 地址",
    friend_category_too_long: "分类最多 80 个字符"
  };
  return labels[detail] || fallback;
}

async function save() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return;
  saving.value = true;
  try {
    if (editingId.value) {
      await updateFriend(editingId.value, { ...form });
      message("友链已更新", { type: "success" });
    } else {
      await createFriend({ ...form });
      message("友链已创建", { type: "success" });
    }
    dialogVisible.value = false;
    await load();
  } catch (error) {
    message(errorText(error, "友链保存失败"), { type: "error" });
  } finally {
    saving.value = false;
  }
}

async function remove(row: FriendItem) {
  try {
    await ElMessageBox.confirm(
      `确定删除“${row.name}”吗？此操作不可撤销。`,
      "删除友情链接",
      { type: "warning", confirmButtonText: "删除", cancelButtonText: "取消" }
    );
    await deleteFriend(row.id);
    message("友链已删除", { type: "success" });
    await load();
  } catch (error: any) {
    if (error !== "cancel" && error !== "close") message(errorText(error, "友链删除失败"), { type: "error" });
  }
}

onMounted(load);
</script>

<template>
  <div class="page-wrap">
    <el-card shadow="never">
      <template #header><div class="toolbar"><div><strong>友情链接</strong><span class="muted">共 {{ total }} 条</span></div><div class="toolbar-actions"><el-button :loading="loading" @click="load">刷新</el-button><el-button type="primary" @click="openCreate">新增友链</el-button></div></div></template>
      <el-table v-loading="loading" :data="rows" stripe>
        <el-table-column prop="name" label="名称" min-width="190" show-overflow-tooltip />
        <el-table-column prop="website_url" label="网址" min-width="260" show-overflow-tooltip />
        <el-table-column label="分类" min-width="120" show-overflow-tooltip><template #default="scope">{{ scope.row.category || "友情链接" }}</template></el-table-column>
        <el-table-column prop="language" label="语言" width="120" show-overflow-tooltip />
        <el-table-column prop="description" label="描述" min-width="280" show-overflow-tooltip />
        <el-table-column prop="sort_order" label="排序" width="80" />
        <el-table-column label="状态" width="100"><template #default="scope"><el-tag :type="scope.row.is_enabled ? 'success' : 'info'">{{ scope.row.is_enabled ? "启用" : "停用" }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="150" fixed="right"><template #default="scope"><el-button link type="primary" @click="openEdit(scope.row)">编辑</el-button><el-button link type="danger" @click="remove(scope.row)">删除</el-button></template></el-table-column>
      </el-table>
      <el-empty v-if="!loading && rows.length === 0" description="暂无友情链接" />
    </el-card>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑友情链接' : '新增友情链接'" width="min(94vw, 680px)" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-row :gutter="18">
          <el-col :xs="24" :md="12"><el-form-item label="名称" prop="name"><el-input v-model="form.name" maxlength="120" /></el-form-item></el-col>
          <el-col :xs="24" :md="12"><el-form-item label="网站地址" prop="website_url"><el-input v-model="form.website_url" placeholder="https://example.com" /></el-form-item></el-col>
          <el-col :span="24">
            <el-form-item label="友情链接分类">
              <el-select v-model="form.category" filterable allow-create default-first-option clearable class="full" placeholder="选择已有分类，或输入新分类（留空为友情链接）">
                <el-option v-for="item in categoryOptions" :key="item" :label="item" :value="item" />
              </el-select>
              <div class="category-hint">分类名称相同的友链自动归为一组，前台可按类别筛选。</div>
            </el-form-item>
          </el-col>
          <el-col :span="24"><el-form-item label="头像地址"><el-input v-model="form.avatar_url" placeholder="可选，https://..." /></el-form-item></el-col>
          <el-col :xs="24" :md="12">
            <el-form-item label="网站语言 / 技术栈">
              <el-select v-model="form.language" filterable allow-create default-first-option clearable class="full" placeholder="请选择或自定义填写">
                <el-option v-for="item in languageOptions" :key="item" :label="item" :value="item" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="12"><el-form-item label="RSS 地址"><el-input v-model="form.rss_url" placeholder="留空默认使用网站根目录 /rss.xml" /></el-form-item></el-col>
          <el-col :span="24"><el-form-item label="描述"><el-input v-model="form.description" maxlength="500" show-word-limit /></el-form-item></el-col>
          <el-col :xs="24" :md="12"><el-form-item label="排序"><el-input-number v-model="form.sort_order" :min="-1000000" :max="1000000" class="full" /></el-form-item></el-col>
          <el-col :xs="24" :md="12"><el-form-item label="公开显示"><el-switch v-model="form.is_enabled" /></el-form-item></el-col>
        </el-row>
      </el-form>
      <template #footer><el-button @click="dialogVisible = false">取消</el-button><el-button type="primary" :loading="saving" @click="save">保存友链</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page-wrap { padding: 2px; }
.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
.toolbar > div:first-child { display: flex; gap: 12px; align-items: baseline; }
.toolbar-actions { display: flex; gap: 10px; }
.muted { color: var(--el-text-color-secondary); font-size: 12px; }
.full { width: 100%; }
.category-hint { font-size: 12px; color: var(--el-text-color-secondary); line-height: 1.5; margin-top: 4px; }
@media (max-width: 700px) { .toolbar { align-items: stretch; flex-direction: column; }.toolbar-actions { justify-content: flex-end; } }
</style>

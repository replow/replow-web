<script setup lang="ts">
import {
  computed,
  h,
  nextTick,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref
} from "vue";
import { onBeforeRouteLeave } from "vue-router";
import { ElMessageBox, type FormInstance, type FormRules } from "element-plus";
import {
  createUser,
  deleteUser,
  getAdminUsers,
  updateUser,
  type UserItem,
  type UserPayload,
  type UserUpdateResponse
} from "@/api/replow";
import { setToken } from "@/utils/auth";
import { useUserStoreHook } from "@/store/modules/user";
import { message } from "@/utils/message";
import { sensitiveChanges, isOwnSession } from "@/utils/user-edit";
import {
  validNewPassword,
  PASSWORD_POLICY_MESSAGE
} from "@/utils/password-policy";
import MediaPicker from "@/components/MediaPicker.vue";
defineOptions({ name: "ReplowUsers" });
const loading = ref(false),
  saving = ref(false),
  dialogVisible = ref(false),
  advanced = ref(false);
const rows = ref<UserItem[]>([]),
  original = ref<UserItem | null>(null),
  formRef = ref<FormInstance>();
const query = ref(""),
  baseline = ref("");
const userStore = useUserStoreHook();
const empty = (): UserPayload => ({
  uid: "",
  username: "",
  email: "",
  display_name: "",
  avatar_url: "",
  bio: "",
  website_url: "",
  role: "user",
  status: "active",
  password: ""
});
const form = reactive<UserPayload>(empty());
const dirty = computed(
  () => dialogVisible.value && JSON.stringify(form) !== baseline.value
);
const visibleRows = computed(() =>
  rows.value.filter(row =>
    [row.uid, row.username, row.display_name, row.email]
      .join(" ")
      .toLowerCase()
      .includes(query.value.trim().toLowerCase())
  )
);
const rules: FormRules = {
  username: [{ required: true, message: "请输入用户名", trigger: "blur" }],
  email: [
    { required: true, message: "请输入邮箱", trigger: "blur" },
    { type: "email", message: "请输入有效邮箱", trigger: "blur" }
  ],
  uid: [
    {
      pattern: /^\d{1,20}$/,
      message: "UID 必须为 1-20 位数字",
      trigger: "blur"
    }
  ]
};
function isCurrent(row: UserItem) {
  return row.username === userStore.username;
}
async function load() {
  loading.value = true;
  try {
    rows.value = (await getAdminUsers()).items || [];
  } catch {
    message("用户读取失败", { type: "error" });
  } finally {
    loading.value = false;
  }
}
function open(row?: UserItem) {
  original.value = row ? { ...row } : null;
  advanced.value = false;
  Object.assign(
    form,
    empty(),
    row
      ? {
          uid: row.uid,
          username: row.username,
          email: row.email,
          display_name: row.display_name || "",
          avatar_url: row.avatar_url || "",
          bio: row.bio || "",
          website_url: row.website_url || "",
          role: row.role,
          status: row.status
        }
      : {}
  );
  form.password = "";
  baseline.value = JSON.stringify(form);
  dialogVisible.value = true;
  nextTick(() => formRef.value?.clearValidate());
}
async function discard() {
  if (!dirty.value) return true;
  try {
    await ElMessageBox.confirm("尚有未保存的修改，确定放弃？", "放弃修改", {
      confirmButtonText: "放弃修改",
      cancelButtonText: "继续编辑",
      type: "warning"
    });
    return true;
  } catch {
    return false;
  }
}
async function close(done?: () => void) {
  if (saving.value) return;
  if (await discard()) {
    dialogVisible.value = false;
    done?.();
  }
}
function beforeUnload(e: BeforeUnloadEvent) {
  if (dirty.value) {
    e.preventDefault();
    e.returnValue = "";
  }
}
onBeforeRouteLeave(async () => !dirty.value || (await discard()));
async function unlockUid() {
  try {
    if (original.value)
      await ElMessageBox.prompt(
        "修改 UID 会改变账号标识及关联记录。请输入当前 UID " +
          original.value.uid +
          " 解锁。",
        "UID 高级操作",
        {
          inputValidator: value =>
            value === original.value?.uid || "请输入当前 UID",
          confirmButtonText: "解锁修改",
          cancelButtonText: "取消",
          type: "warning"
        }
      );
    else
      await ElMessageBox.confirm(
        "默认按顺序分配 UID。自定义较大的 UID 会提高后续自动分配起点。",
        "自定义 UID",
        {
          type: "warning",
          confirmButtonText: "启用自定义",
          cancelButtonText: "取消"
        }
      );
    advanced.value = true;
  } catch {
    /* cancelled */
  }
}
function generate() {
  const alphabet =
    "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%-_";
  const values = crypto.getRandomValues(new Uint32Array(20));
  form.password =
    "Aa2!" + Array.from(values, v => alphabet[v % alphabet.length]).join("");
  message("已生成随机密码，点击保存后生效", { type: "success" });
}
function applyOwnSession(result: UserUpdateResponse, username: string) {
  if (isOwnSession(result, username, userStore.username) && result.session)
    setToken(result.session);
}
function errorText(error: any) {
  const labels: Record<string, string> = {
    sensitive_confirmation_required: "请确认敏感操作",
    uid_override_confirmation_required: "请先解锁 UID 高级操作",
    uid_already_exists: "UID 已被占用",
    email_already_exists: "邮箱已被占用",
    username_or_email_already_exists: "用户名或邮箱已存在",
    cannot_change_own_admin_access: "不能停用或降级当前管理员",
    last_active_admin_required: "至少保留一名启用的管理员",
    cannot_delete_current_user: "不能删除当前登录账号",
    invalid_password: PASSWORD_POLICY_MESSAGE
  };
  return labels[error?.response?.data?.detail] || "保存失败，请检查输入后重试";
}
async function save() {
  if (!(await formRef.value?.validate().catch(() => false))) return;
  const data: UserPayload = {
    ...form,
    uid: form.uid?.trim() || undefined,
    username: form.username.trim(),
    email: form.email.trim()
  };
  if (!data.password) delete data.password;
  if (data.password && !validNewPassword(data.password)) {
    message(PASSWORD_POLICY_MESSAGE, { type: "warning" });
    return;
  }
  const changes = sensitiveChanges(original.value, data);
  try {
    if (changes.length)
      await ElMessageBox.confirm(
        h("div", { class: "sensitive-summary" }, [
          h(
            "p",
            "目标：" +
              data.username +
              " · UID " +
              (original.value?.uid || "自动分配")
          ),
          h(
            "ul",
            changes.map(text => h("li", text))
          )
        ]),
        "确认敏感修改",
        {
          confirmButtonText: "确认修改",
          cancelButtonText: "取消",
          type: "warning",
          closeOnClickModal: false
        }
      );
  } catch {
    return;
  }
  saving.value = true;
  try {
    data.confirm_sensitive = true;
    data.allow_uid_override = advanced.value;
    if (original.value) {
      const result = await updateUser(original.value.uid, data);
      applyOwnSession(result, data.username);
    } else await createUser(data);
    baseline.value = JSON.stringify(form);
    dialogVisible.value = false;
    message(original.value ? "用户已更新" : "用户已创建", { type: "success" });
    await load();
  } catch (error) {
    message(errorText(error), { type: "error" });
  } finally {
    saving.value = false;
  }
}
async function remove(row: UserItem) {
  if (isCurrent(row)) return;
  try {
    await ElMessageBox.prompt(
      "将删除 " +
        row.username +
        "（UID " +
        row.uid +
        "）及关联申请与令牌。文章评论保留但解除归属。请输入 UID 确认。",
      "删除用户",
      {
        inputValidator: value => value === row.uid || "请输入目标 UID",
        confirmButtonText: "确认删除",
        cancelButtonText: "取消",
        type: "warning"
      }
    );
    await deleteUser(row.uid);
    message("用户已删除", { type: "success" });
    await load();
  } catch (error: any) {
    if (error !== "cancel" && error !== "close")
      message(errorText(error), { type: "error" });
  }
}
onMounted(() => {
  load();
  window.addEventListener("beforeunload", beforeUnload);
});
onBeforeUnmount(() => window.removeEventListener("beforeunload", beforeUnload));
</script>
<template>
  <div class="users-page">
    <el-card shadow="never">
      <template #header
        ><div class="toolbar">
          <div>
            <strong>用户管理</strong
            ><span class="muted">共 {{ rows.length }} 人</span>
          </div>
          <div class="toolbar-actions">
            <el-input
              v-model="query"
              placeholder="搜索 UID、用户名或邮箱"
              clearable
              aria-label="搜索用户"
            /><el-button :loading="loading" @click="load">刷新</el-button
            ><el-button type="primary" @click="open()">新增用户</el-button>
          </div>
        </div></template
      >
      <el-table
        v-loading="loading"
        class="desktop-users"
        :data="visibleRows"
        stripe
      >
        <el-table-column prop="uid" label="UID" width="100" /><el-table-column
          label="账号"
          min-width="200"
          ><template #default="{ row }"
            ><div class="account-cell">
              <el-avatar :size="34" :src="row.avatar_url">{{
                row.username.slice(0, 1)
              }}</el-avatar>
              <div>
                <strong>{{ row.display_name || row.username }}</strong
                ><small
                  >@{{ row.username }}
                  <el-tag v-if="isCurrent(row)" size="small"
                    >当前登录</el-tag
                  ></small
                >
              </div>
            </div></template
          ></el-table-column
        >
        <el-table-column
          prop="email"
          label="邮箱"
          min-width="220"
          show-overflow-tooltip
        />
        <el-table-column label="角色" width="100"
          ><template #default="{ row }"
            ><el-tag :type="row.role === 'admin' ? 'danger' : 'info'">{{
              row.role === "admin" ? "管理员" : "普通用户"
            }}</el-tag></template
          ></el-table-column
        >
        <el-table-column label="状态" width="90"
          ><template #default="{ row }"
            ><el-tag :type="row.status === 'active' ? 'success' : 'warning'">{{
              row.status === "active" ? "启用" : "停用"
            }}</el-tag></template
          ></el-table-column
        >
        <el-table-column label="操作" width="150" fixed="right"
          ><template #default="{ row }"
            ><el-button text type="primary" @click="open(row)">编辑</el-button
            ><el-button
              text
              type="danger"
              :disabled="isCurrent(row)"
              @click="remove(row)"
              >删除</el-button
            ></template
          ></el-table-column
        >
      </el-table>
      <div v-loading="loading" class="mobile-users">
        <article v-for="row in visibleRows" :key="row.uid" class="user-card">
          <div class="account-cell">
            <el-avatar :src="row.avatar_url">{{
              row.username.slice(0, 1)
            }}</el-avatar>
            <div>
              <strong>{{ row.display_name || row.username }}</strong
              ><small>@{{ row.username }}</small>
            </div>
            <el-tag v-if="isCurrent(row)" size="small">当前登录</el-tag>
          </div>
          <div class="card-meta">
            <span>UID {{ row.uid }}</span
            ><span
              >{{ row.role === "admin" ? "管理员" : "普通用户" }} ·
              {{ row.status === "active" ? "启用" : "停用" }}</span
            >
          </div>
          <p>{{ row.email }}</p>
          <div class="card-actions">
            <el-button @click="open(row)">编辑用户</el-button
            ><el-button
              type="danger"
              plain
              :disabled="isCurrent(row)"
              @click="remove(row)"
              >删除</el-button
            >
          </div>
        </article>
      </div>
      <el-empty
        v-if="!loading && !visibleRows.length"
        description="没有匹配的用户"
      />
    </el-card>
    <el-dialog
      v-model="dialogVisible"
      :title="original ? '编辑用户' : '新增用户'"
      width="min(94vw,720px)"
      class="user-edit-dialog"
      :before-close="close"
      :close-on-click-modal="false"
      destroy-on-close
    >
      <div class="edit-target" data-edit-target>
        <el-avatar :size="44" :src="original?.avatar_url">{{
          (original?.username || "新").slice(0, 1)
        }}</el-avatar>
        <div>
          <strong>{{
            original?.display_name || original?.username || "新增用户"
          }}</strong
          ><small>{{
            original
              ? "@" + original.username + " · UID " + original.uid
              : "保存后自动分配 UID"
          }}</small>
        </div>
        <el-tag v-if="original && isCurrent(original)">当前登录账号</el-tag>
      </div>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top">
        <el-row :gutter="18">
          <el-col :xs="24" :md="12"
            ><el-form-item label="UID" prop="uid"
              ><el-input
                v-model="form.uid"
                :readonly="!advanced"
                inputmode="numeric"
                maxlength="20"
                placeholder="保存后自动递增分配"
              /><el-button
                v-if="!advanced"
                link
                type="primary"
                @click="unlockUid"
                >高级操作：{{ original ? "修改" : "自定义" }} UID</el-button
              ><small v-else class="muted"
                >UID 修改将再次确认，并可能提高后续分配起点。</small
              ></el-form-item
            ></el-col
          >
          <el-col :xs="24" :md="12"
            ><el-form-item label="用户名" prop="username"
              ><el-input
                v-model="form.username"
                :disabled="Boolean(original)"
                maxlength="32" /></el-form-item
          ></el-col>
          <el-col :xs="24" :md="12"
            ><el-form-item label="邮箱" prop="email"
              ><el-input v-model="form.email" maxlength="190" /></el-form-item
          ></el-col>
          <el-col :xs="24" :md="12"
            ><el-form-item label="显示名称"
              ><el-input
                v-model="form.display_name"
                maxlength="80" /></el-form-item
          ></el-col>
          <el-col :xs="24" :md="12"
            ><el-form-item label="角色"
              ><el-select
                v-model="form.role"
                :disabled="!!original && isCurrent(original)"
                ><el-option label="普通用户" value="user" /><el-option
                  label="管理员"
                  value="admin" /></el-select></el-form-item
          ></el-col>
          <el-col :xs="24" :md="12"
            ><el-form-item label="状态"
              ><el-select
                v-model="form.status"
                :disabled="!!original && isCurrent(original)"
                ><el-option label="启用" value="active" /><el-option
                  label="停用"
                  value="disabled" /></el-select></el-form-item
          ></el-col>
          <el-col :span="24"
            ><el-form-item label="密码"
              ><el-input
                v-model="form.password"
                type="password"
                show-password
                maxlength="128"
                autocomplete="new-password"
                :placeholder="PASSWORD_POLICY_MESSAGE"
                placeholder="留空则不修改；新用户可使用验证码登录"
              /><el-button link type="primary" @click="generate"
                >生成随机密码（保存后生效）</el-button
              ></el-form-item
            ></el-col
          >
          <el-col :span="24"
            ><el-form-item label="用户头像"
              ><MediaPicker
                v-model="form.avatar_url"
                category="avatar" /></el-form-item
          ></el-col>
          <el-col :span="24"
            ><el-form-item label="个人网站"
              ><el-input
                v-model="form.website_url"
                placeholder="https://..." /></el-form-item
          ></el-col>
          <el-col :span="24"
            ><el-form-item label="个人简介"
              ><el-input
                v-model="form.bio"
                type="textarea"
                :rows="3"
                maxlength="500"
                show-word-limit /></el-form-item
          ></el-col>
        </el-row>
      </el-form>
      <template #footer
        ><el-button :disabled="saving" @click="close()">取消</el-button
        ><el-button type="primary" :loading="saving" @click="save"
          >保存用户</el-button
        ></template
      >
    </el-dialog>
  </div>
</template>
<style scoped>
.toolbar,
.toolbar > div,
.toolbar-actions,
.account-cell,
.card-meta,
.card-actions,
.edit-target {
  display: flex;
  align-items: center;
  gap: 12px;
}
.toolbar {
  justify-content: space-between;
  flex-wrap: wrap;
}
.toolbar-actions {
  flex-wrap: wrap;
}
.toolbar-actions .el-input {
  width: 240px;
}
.muted {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.account-cell > div,
.edit-target > div {
  display: grid;
  gap: 4px;
  min-width: 0;
}
.account-cell small,
.edit-target small {
  color: var(--el-text-color-secondary);
  overflow-wrap: anywhere;
}
.mobile-users {
  display: none;
}
.edit-target {
  position: sticky;
  top: 0;
  z-index: 3;
  background: var(--el-bg-color);
  padding: 12px 0;
  margin-bottom: 14px;
  border-bottom: 1px solid var(--el-border-color-light);
}
.edit-target .el-tag {
  margin-left: auto;
}
.el-select {
  width: 100%;
}
@media (max-width: 767px) {
  .desktop-users {
    display: none;
  }
  .mobile-users {
    display: grid;
    gap: 12px;
  }
  .toolbar-actions {
    width: 100%;
  }
  .toolbar-actions .el-input {
    width: 100%;
    flex-basis: 100%;
  }
  .user-card {
    padding: 16px;
    border: 1px solid var(--el-border-color-light);
    border-radius: 14px;
    background: var(--el-bg-color);
  }
  .card-meta {
    justify-content: space-between;
    font-size: 12px;
    margin-top: 14px;
    color: var(--el-text-color-secondary);
  }
  .user-card p {
    overflow-wrap: anywhere;
    font-size: 13px;
  }
  .card-actions {
    justify-content: flex-end;
    margin-top: 14px;
  }
  .edit-target {
    flex-wrap: wrap;
  }
  .edit-target .el-tag {
    margin-left: 0;
  }
}
</style>
<style>
.user-edit-dialog {
  display: flex;
  flex-direction: column;
  max-height: 92dvh;
  margin-top: 4dvh !important;
  margin-bottom: 4dvh !important;
}
.user-edit-dialog .el-dialog__body {
  min-height: 0;
  flex: 1;
  max-height: 68dvh;
  overflow: auto;
  padding-top: 0;
}
.user-edit-dialog .el-dialog__footer {
  position: sticky;
  bottom: 0;
  background: var(--el-bg-color);
  border-top: 1px solid var(--el-border-color-light);
  padding-top: 14px;
}
.sensitive-summary ul {
  padding-left: 18px;
  line-height: 1.9;
}
.sensitive-summary p {
  overflow-wrap: anywhere;
}
</style>

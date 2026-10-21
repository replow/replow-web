<script setup lang="ts">
import DeviceSessions from "@/components/DeviceSessions.vue";
import { reactive, ref } from "vue";
import type { FormInstance } from "element-plus";
import { changeMyPassword } from "@/api/user";
import { setToken } from "@/utils/auth";
import { useUserStoreHook } from "@/store/modules/user";
import { message } from "@/utils/message";

defineOptions({ name: "ReplowProfile" });

const formRef = ref<FormInstance>();
const saving = ref(false);
const userStore = useUserStoreHook();
const form = reactive({
  oldPassword: "",
  newPassword: "",
  confirmPassword: ""
});

async function savePassword() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return;
  if (form.newPassword !== form.confirmPassword) {
    message("两次输入的密码不一致", { type: "warning" });
    return;
  }
  saving.value = true;
  try {
    const result = await changeMyPassword({
      old_password: form.oldPassword || undefined,
      new_password: form.newPassword
    });
    setToken(result.data);
    form.oldPassword = "";
    form.newPassword = "";
    form.confirmPassword = "";
    message("密码已更新", { type: "success" });
  } catch {
    message("密码更新失败，请检查旧密码", { type: "error" });
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="page-wrap">
    <el-row :gutter="18">
      <el-col :xs="24" :md="9">
        <el-card shadow="never">
          <div class="identity">
            <el-avatar :size="64" :src="userStore.avatar">{{
              userStore.nickname || userStore.username
            }}</el-avatar>
            <div>
              <strong>{{ userStore.nickname || userStore.username }}</strong>
              <span>@{{ userStore.username }}</span>
              <small>SilverCode 账号</small>
            </div>
          </div>
          <el-alert
            title="邮箱验证码登录无需密码；设置密码后可使用账号密码登录。"
            type="info"
            :closable="false"
            show-icon
          />
        </el-card>
      </el-col>
      <el-col :xs="24" :md="15">
        <el-card shadow="never">
          <template #header><strong>修改密码</strong></template>
          <el-form
            ref="formRef"
            :model="form"
            label-position="top"
            class="password-form"
          >
            <el-form-item label="旧密码（未设置过密码可留空）">
              <el-input
                v-model="form.oldPassword"
                type="password"
                show-password
                autocomplete="current-password"
              />
            </el-form-item>
            <el-form-item
              label="新密码"
              prop="newPassword"
              :rules="[
                {
                  required: true,
                  min: 8,
                  max: 128,
                  message: '请输入 8-128 位新密码',
                  trigger: 'blur'
                }
              ]"
            >
              <el-input
                v-model="form.newPassword"
                type="password"
                show-password
                autocomplete="new-password"
              />
            </el-form-item>
            <el-form-item
              label="确认新密码"
              prop="confirmPassword"
              :rules="[
                { required: true, message: '请再次输入新密码', trigger: 'blur' }
              ]"
            >
              <el-input
                v-model="form.confirmPassword"
                type="password"
                show-password
                autocomplete="new-password"
              />
            </el-form-item>
            <el-button type="primary" :loading="saving" @click="savePassword"
              >保存密码</el-button
            >
          </el-form>
        </el-card>
      </el-col>
    </el-row>
    <DeviceSessions />
  </div>
</template>

<style scoped>
.page-wrap {
  padding: 2px;
}
.identity {
  display: flex;
  align-items: center;
  gap: 15px;
  margin-bottom: 20px;
}
.identity > div {
  display: grid;
  gap: 4px;
}
.identity span,
.identity small {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.password-form {
  max-width: 560px;
}
</style>

<script setup lang="ts">
import Motion from "./utils/motion";
import { useRouter } from "vue-router";
import { message } from "@/utils/message";
import { loginRules } from "./utils/rule";
import { ref, reactive } from "vue";
import { debounce } from "@pureadmin/utils";
import { useNav } from "@/layout/hooks/useNav";
import { useEventListener } from "@vueuse/core";
import type { FormInstance } from "element-plus";
import { useLayout } from "@/layout/hooks/useLayout";
import { useUserStoreHook } from "@/store/modules/user";
import { initRouter, getTopMenu } from "@/router/utils";
import BrandMark from "@/components/BrandMark.vue";
import { MIRO_WALLPAPER } from "@/utils/miro-brand";
import FloatingLoginInput from "./components/FloatingLoginInput.vue";
import { useDataThemeChange } from "@/layout/hooks/useDataThemeChange";
import { codeLogin, sendVerificationCode } from "@/api/user";
import { setToken } from "@/utils/auth";

import dayIcon from "@/assets/svg/day.svg?component";
import darkIcon from "@/assets/svg/dark.svg?component";

defineOptions({
  name: "Login"
});

const router = useRouter();
const loading = ref(false);
const restrictionMessage = ref("");
function loginError(error: unknown, fallback: string) {
  const detail = (error as { response?: { data?: { detail?: string } } })
    ?.response?.data?.detail;
  if (typeof detail === "string" && detail.startsWith("账号封禁：")) {
    restrictionMessage.value = detail;
    return detail;
  }
  return detail === "registration_email_not_allowed"
    ? "此邮箱后缀未开放注册，请使用站点允许的邮箱或联系管理员"
    : fallback;
}
const disabled = ref(false);
const ruleFormRef = ref<FormInstance>();
const loginMode = ref<"password" | "code">("password");
const codeSending = ref(false);
const codeCountdown = ref(0);

const { initStorage } = useLayout();
initStorage();

const { dataTheme, overallStyle, dataThemeChange } = useDataThemeChange();
dataThemeChange(overallStyle.value);
const { title } = useNav();

const ruleForm = reactive({
  username: "",
  password: "",
  email: "",
  code: ""
});

async function finishLogin(result: any) {
  if (!result?.success) throw new Error("login_failed");
  if (!result?.data?.roles?.includes("admin")) {
    window.location.href = "https://account.replow.org/";
    return;
  }
  setToken(result.data);
  await initRouter();
  disabled.value = true;
  try {
    await router.push(getTopMenu(true).path);
    message("登录成功", { type: "success" });
  } finally {
    disabled.value = false;
  }
}

const onLogin = async (formEl: FormInstance | undefined) => {
  if (!formEl) return;
  const valid = await formEl.validate().catch(() => false);
  if (!valid) return;
  loading.value = true;
  try {
    if (loginMode.value === "code") {
      await finishLogin(
        await codeLogin({ email: ruleForm.email, code: ruleForm.code })
      );
    } else {
      await finishLogin(
        await useUserStoreHook().loginByUsername({
          username: ruleForm.username,
          password: ruleForm.password
        })
      );
    }
  } catch (error) {
    message(loginError(error, "登录失败，请检查账号、密码或验证码"), {
      type: "error"
    });
  } finally {
    loading.value = false;
  }
};

function startCountdown(target: { value: number }, seconds: number) {
  target.value = seconds;
  const timer = window.setInterval(() => {
    target.value -= 1;
    if (target.value <= 0) window.clearInterval(timer);
  }, 1000);
}

async function sendLoginCode() {
  if (!ruleForm.email) return message("请输入邮箱", { type: "warning" });
  if (codeSending.value || codeCountdown.value > 0) return;
  codeSending.value = true;
  try {
    await sendVerificationCode({ email: ruleForm.email, purpose: "login" });
    startCountdown(codeCountdown, 60);
    message("验证码已发送", { type: "success" });
  } catch (error) {
    message(loginError(error, "验证码发送失败，请检查邮件配置"), {
      type: "error"
    });
  } finally {
    codeSending.value = false;
  }
}

const immediateDebounce: any = debounce(
  formRef => onLogin(formRef),
  1000,
  true
);

useEventListener(document, "keydown", ({ code }) => {
  if (
    ["Enter", "NumpadEnter"].includes(code) &&
    !disabled.value &&
    !loading.value
  )
    immediateDebounce(ruleFormRef.value);
});
</script>

<template>
  <div class="miro-login select-none">
    <div class="flex-c absolute right-5 top-3">
      <!-- 主题 -->
      <el-switch
        v-model="dataTheme"
        inline-prompt
        aria-label="切换明暗主题"
        :active-icon="dayIcon"
        :inactive-icon="darkIcon"
        @change="dataThemeChange"
      />
    </div>
    <div class="login-container">
      <div class="img">
        <img :src="MIRO_WALLPAPER" alt="Silver Wolf 银狼壁纸" />
        <div class="login-art-caption">
          <strong>Silune</strong>
          <span>Silver Wolf · Replow Lv.999</span>
        </div>
      </div>
      <div class="login-box">
        <div class="login-form">
          <BrandMark />
          <Motion>
            <h2 class="outline-hidden">{{ title }}</h2>
            <p class="login-subtitle">欢迎回来，管理你的内容与灵感</p>
          </Motion>

          <el-radio-group v-model="loginMode" class="login-mode" size="small">
            <el-radio-button label="password">密码登录</el-radio-button>
            <el-radio-button label="code">邮箱验证码</el-radio-button>
          </el-radio-group>

          <el-alert
            v-if="restrictionMessage"
            :title="restrictionMessage"
            type="error"
            :closable="false"
            show-icon
            style="margin: 16px 0; overflow-wrap: anywhere"
          />
          <el-form
            ref="ruleFormRef"
            :model="ruleForm"
            :rules="loginRules"
            size="large"
          >
            <Motion v-if="loginMode === 'password'" :delay="100">
              <el-form-item
                :rules="[
                  {
                    required: true,
                    message: '请输入账号',
                    trigger: 'blur'
                  }
                ]"
                prop="username"
              >
                <FloatingLoginInput
                  id="miro-login-username"
                  v-model="ruleForm.username"
                  label="账号"
                  name="username"
                  autocomplete="username"
                  autocapitalize="off"
                  :spellcheck="false"
                />
              </el-form-item>
            </Motion>

            <Motion v-if="loginMode === 'password'" :delay="150">
              <el-form-item prop="password">
                <FloatingLoginInput
                  id="miro-login-password"
                  v-model="ruleForm.password"
                  label="密码"
                  name="password"
                  type="password"
                  autocomplete="current-password"
                  show-password
                />
              </el-form-item>
            </Motion>

            <template v-if="loginMode === 'code'">
              <el-form-item
                prop="email"
                :rules="[
                  { required: true, message: '请输入邮箱', trigger: 'blur' }
                ]"
              >
                <FloatingLoginInput
                  id="miro-login-email"
                  v-model="ruleForm.email"
                  label="邮箱"
                  name="email"
                  type="email"
                  autocomplete="email"
                  inputmode="email"
                  autocapitalize="off"
                  :spellcheck="false"
                />
              </el-form-item>
              <el-form-item
                prop="code"
                :rules="[
                  { required: true, message: '请输入验证码', trigger: 'blur' }
                ]"
              >
                <div class="login-code-row">
                  <FloatingLoginInput
                    id="miro-login-code"
                    v-model="ruleForm.code"
                    label="6 位验证码"
                    name="code"
                    autocomplete="one-time-code"
                    inputmode="numeric"
                    pattern="[0-9]*"
                    :maxlength="6"
                  />
                  <el-button
                    :loading="codeSending"
                    :disabled="codeCountdown > 0"
                    @click="sendLoginCode"
                    >{{
                      codeCountdown > 0 ? codeCountdown + "s" : "获取验证码"
                    }}</el-button
                  >
                </div>
              </el-form-item>
            </template>

            <Motion :delay="250">
              <el-button
                class="w-full mt-4!"
                size="default"
                type="primary"
                :loading="loading"
                :disabled="disabled"
                @click="onLogin(ruleFormRef)"
              >
                登录
              </el-button>
            </Motion>
          </el-form>
          <div class="account-links">
            <span>邮箱验证码登录无需设置密码</span>
          </div>
          <p class="login-owner">Silune · SilverCode Admin</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@import url("@/style/login.css");
</style>

<style lang="scss" scoped>
:deep(.el-input-group__append, .el-input-group__prepend) {
  padding: 0;
}
.login-mode {
  display: flex;
  justify-content: center;
  margin: 18px 0 12px;
}
.account-links {
  display: flex;
  justify-content: center;
  margin-top: 15px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>

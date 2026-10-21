<script setup lang="ts">
import { onMounted, onUnmounted, reactive, ref, watch } from "vue";
import MediaPicker from "@/components/MediaPicker.vue";
import {
  getSiteBuild,
  startSiteBuild,
  updateFireflyConfig,
  type FireflyConfig,
  type SiteBuildStatus
} from "@/api/replow";
import { message } from "@/utils/message";
const props = defineProps<{ config: FireflyConfig }>();
const emit = defineEmits<{ saved: [] }>();
const saving = ref(false);
const building = ref(false);
const statusLabels: Record<string, string> = {
  idle: "待构建",
  queued: "排队中",
  building: "构建中",
  success: "发布成功",
  failed: "构建失败"
};
const status = ref<SiteBuildStatus>({ status: "idle", version: "", error: "" });
let timer: ReturnType<typeof setInterval> | undefined;
const form = reactive({
  heroTitle: "Silver Wolf",
  headerIdleMs: 400,
  postCardImagePosition: "alternating",
  motionLevel: "lively",
  runtimeArticles: true,
  name: "",
  avatar: "",
  bio: "",
  github: "",
  bilibili: "",
  qq: "",
  qqGroup: "",
  email: ""
});
function load(config: FireflyConfig) {
  const koharu = config.koharuConfig || {};
  const profile = config.profileConfig || {};
  form.heroTitle = koharu.heroTitle || "Silver Wolf";
  form.headerIdleMs = Number(koharu.headerIdleMs || 400);
  form.postCardImagePosition = koharu.postCardImagePosition || "alternating";
  form.motionLevel = koharu.motionLevel || "lively";
  form.runtimeArticles = koharu.runtimeArticles !== false;
  form.name = profile.name || "";
  form.avatar = profile.avatar || "";
  form.bio = profile.bio || "";
  const links = Array.isArray(profile.links) ? profile.links : [];
  const url = (name: string) =>
    String(links.find((link: FireflyConfig) => link.name === name)?.url || "");
  form.github = url("GitHub");
  form.bilibili = url("Bilibili");
  form.qq = url("QQ");
  form.qqGroup = url("QQ群");
  form.email = url("邮箱").replace(/^mailto:/, "");
}
watch(() => props.config, load, { immediate: true, deep: true });
async function save() {
  saving.value = true;
  try {
    const config = JSON.parse(JSON.stringify(props.config)) as FireflyConfig;
    config.koharuConfig = {
      ...config.koharuConfig,
      theme: "astro-koharu",
      heroTitle: form.heroTitle.trim(),
      headerIdleMs: form.headerIdleMs,
      postCardImagePosition: form.postCardImagePosition,
      motionLevel: form.motionLevel,
      runtimeArticles: form.runtimeArticles
    };
    config.profileConfig = {
      ...config.profileConfig,
      name: form.name,
      avatar: form.avatar,
      bio: form.bio,
      links: [
        { name: "GitHub", icon: "fa7-brands:github", url: form.github },
        { name: "Bilibili", icon: "fa7-brands:bilibili", url: form.bilibili },
        { name: "QQ", icon: "fa7-brands:qq", url: form.qq },
        { name: "QQ群", icon: "fa7-brands:qq", url: form.qqGroup },
        {
          name: "邮箱",
          icon: "fa7-solid:envelope",
          url: form.email ? "mailto:" + form.email : ""
        }
      ]
        .filter(link => link.url)
        .map(link => ({ ...link, showName: false }))
    };
    config.sidebarLayoutConfig = {
      ...config.sidebarLayoutConfig,
      position: "left",
      showBothSidebarsOnPostPage: false
    };
    config.footerConfig = {
      ...config.footerConfig,
      customHtml: String(config.footerConfig?.customHtml || "").replace(
        /Theme\s+Firefly/gi,
        "Theme astro-koharu"
      )
    };
    await updateFireflyConfig(config);
    emit("saved");
    message(
      "Koharu 设置已保存。名称、背景、公告和底栏会动态同步；卡片布局、动效、搜索与静态页面请构建发布。",
      { type: "success" }
    );
    return true;
  } catch {
    message("Koharu 设置保存失败", { type: "error" });
    return false;
  } finally {
    saving.value = false;
  }
}
async function pollStatus() {
  try {
    const result = await getSiteBuild();
    status.value = result.data;
    building.value = ["building", "queued"].includes(result.data.status);
  } catch {
    /* Keep the last verified build state while the API restarts. */
  }
}
async function build() {
  if (!(await save())) return;
  building.value = true;
  try {
    const result = await startSiteBuild();
    status.value = result.data;
    message("构建任务已提交，通过检查后会自动发布。", { type: "success" });
  } catch {
    building.value = false;
    message("构建任务提交失败", { type: "error" });
  }
}
onMounted(() => {
  void pollStatus();
  timer = setInterval(pollStatus, 5000);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <div class="koharu-settings">
    <el-alert
      title="astro-koharu"
      type="info"
      :closable="false"
      description="后台文章、友链和站点配置会直接写入构建产物；前台继续通过 API 同步内容。构建发布会更新搜索索引、RSS、分类归档及文章静态页。"
      show-icon
    />
    <el-form label-position="top">
      <el-divider content-position="left">主题与交互</el-divider>
      <el-row :gutter="18">
        <el-col :xs="24" :md="12"
          ><el-form-item label="首页主标题"
            ><el-input v-model="form.heroTitle" /></el-form-item
        ></el-col>
        <el-col :xs="24" :md="12"
          ><el-form-item label="停止滚动后显示顶栏（毫秒）"
            ><el-input-number
              v-model="form.headerIdleMs"
              :min="100"
              :max="2000"
              :step="100" /></el-form-item
        ></el-col>
        <el-col :xs="24" :md="12"
          ><el-form-item label="文章封面位置"
            ><el-select v-model="form.postCardImagePosition"
              ><el-option label="左右交替" value="alternating" /><el-option
                label="左侧"
                value="left" /><el-option
                label="右侧"
                value="right" /></el-select></el-form-item
        ></el-col>
        <el-col :xs="24" :md="12"
          ><el-form-item label="动效强度"
            ><el-select v-model="form.motionLevel"
              ><el-option label="灵动" value="lively" /><el-option
                label="克制"
                value="subtle" /><el-option
                label="减弱"
                value="reduced" /></el-select></el-form-item
        ></el-col>
        <el-col :xs="24" :md="12"
          ><el-form-item label="API 动态同步文章"
            ><el-switch v-model="form.runtimeArticles" /></el-form-item
        ></el-col>
      </el-row>
      <el-divider content-position="left">个人信息与联系方式</el-divider>
      <el-row :gutter="18">
        <el-col :xs="24" :md="12"
          ><el-form-item label="个人名称"
            ><el-input v-model="form.name" /></el-form-item
        ></el-col>
        <el-col :xs="24" :md="12"
          ><el-form-item label="头像"
            ><MediaPicker
              v-model="form.avatar"
              category="site-avatar" /></el-form-item
        ></el-col>
      </el-row>
      <el-form-item label="个人简介"
        ><el-input v-model="form.bio" type="textarea" :rows="3"
      /></el-form-item>
      <el-row :gutter="18">
        <el-col :xs="24" :md="12"
          ><el-form-item label="GitHub"
            ><el-input v-model="form.github" /></el-form-item
        ></el-col>
        <el-col :xs="24" :md="12"
          ><el-form-item label="Bilibili"
            ><el-input v-model="form.bilibili" /></el-form-item
        ></el-col>
        <el-col :xs="24" :md="12"
          ><el-form-item label="QQ"><el-input v-model="form.qq" /></el-form-item
        ></el-col>
        <el-col :xs="24" :md="12"
          ><el-form-item label="QQ群"
            ><el-input v-model="form.qqGroup" /></el-form-item
        ></el-col>
      </el-row>
      <el-form-item label="邮箱"
        ><el-input v-model="form.email" type="email"
      /></el-form-item>
      <el-button type="primary" :loading="saving" @click="save"
        >保存 Koharu 设置</el-button
      >
      <el-button type="success" :loading="building" @click="build"
        >构建并发布</el-button
      >
      <p class="build-status" role="status">
        构建状态：{{ statusLabels[status.status] || status.status }}
        {{ status.version }}
      </p>
      <el-alert
        v-if="status.error"
        :title="status.error"
        type="error"
        :closable="false"
      />
    </el-form>
  </div>
</template>
<style scoped>
.koharu-settings {
  max-width: 1000px;
}
.el-form {
  margin-top: 20px;
}
.el-select {
  width: 100%;
}
.build-status {
  margin-top: 16px;
  color: var(--el-text-color-secondary);
}
</style>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessageBox } from "element-plus";
import {
  getAccountSettings,
  getCloudflareSettings,
  getFireflyConfig,
  purgeCloudflareCache,
  sendTestMail,
  updateAccountSettings,
  updateCloudflareSettings,
  updateFireflyConfig,
  type AccountSettings,
  type CloudflareSettings,
  type FireflyConfig
} from "@/api/replow";
import { message } from "@/utils/message";
import MediaPicker from "@/components/MediaPicker.vue";
import KoharuSettings from "@/components/KoharuSettings.vue";

defineOptions({ name: "ReplowSettings" });

const loading = ref(false);
const saving = ref(false);
const accountSaving = ref(false);
const mailTesting = ref(false);
const cloudflareSaving = ref(false);
const cloudflarePurging = ref(false);
const activeTab = ref("koharu");
const jsonText = ref("{}");

const form = reactive({
  site: {
    title: "",
    subtitle: "",
    description: "",
    siteUrl: "",
    keywords: "",
    lang: "zh_CN",
    hue: 270,
    defaultMode: "system",
    pageWidth: 110,
    postsPerPage: 10
  },
  friendSite: {
    name: "",
    description: "",
    url: "",
    avatarUrl: "",
    accountUrl: "https://account.replow.org/"
  },
  wallpaper: {
    mode: "banner",
    switchable: true,
    desktop: "",
    mobile: "",
    lightDesktop: "",
    lightMobile: "",
    overlayOpacity: 0.8,
    overlayBlur: 10,
    waves: true,
    carousel: false,
    carouselInterval: 5000
  },
  features: {
    friends: true,
    sponsor: false,
    guestbook: true,
    bangumi: false,
    gallery: false,
    categoryBar: true,
    footer: true,
    announcement: true,
    comments: "none",
    musicNavbar: true,
    musicSidebar: true,
    sakura: false,
    live2d: false,
    spine: false,
    displaySettings: false,
    coverInPost: true,
    generateOgImages: true,
    showLastModified: true,
    sharePoster: true
  },
  announcement: {
    title: "网站公告",
    content: "",
    closable: true,
    linkText: "",
    linkUrl: "",
    linkEnabled: false
  },
  sidebar: {
    enable: true,
    position: "both",
    tabletSidebar: "left",
    showBothOnPost: true
  },
  footerHtml: "",
  account: {
    registrationEnabled: true,
    emailVerificationEnabled: true
  },
  mail: {
    smtpHost: "",
    smtpPort: 465,
    smtpUsername: "",
    smtpPassword: "",
    fromEmail: "",
    senderName: "SilverCode",
    useTls: true,
    useSsl: true,
    passwordConfigured: false,
    configured: false,
    testRecipient: ""
  },
  cloudflare: {
    authType: "api_token" as "api_token" | "global_key",
    email: "",
    credential: "",
    accountId: "",
    zoneId: "",
    zoneName: "replow.org",
    credentialConfigured: false,
    configured: false,
    clearCredential: false
  }
});

const firefly = ref<FireflyConfig>({});

function firstImage(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value)) return String(value[0] || "");
  return "";
}

function section(config: FireflyConfig, name: string): FireflyConfig {
  return config[name] && typeof config[name] === "object" ? config[name] : {};
}

function loadForm(config: FireflyConfig) {
  const site = section(config, "siteConfig");
  const profile = section(config, "profileConfig");
  const friendSite = section(config, "friendSiteInfo");
  const themeColor = section(site, "themeColor");
  const pages = section(site, "pages");
  const post = section(site, "post");
  const wallpaper = section(config, "backgroundWallpaper");
  const source = section(wallpaper, "src");
  const common = section(wallpaper, "common");
  const homeText = section(common, "homeText");
  const banner = section(wallpaper, "banner");
  const bannerWaves = section(banner, "waves");
  const overlay = section(wallpaper, "overlay");
  const announcement = section(config, "announcementConfig");
  const announcementLink = section(announcement, "link");
  const sidebar = section(config, "sidebarLayoutConfig");
  const footer = section(config, "footerConfig");
  const comments = section(config, "commentConfig");
  const music = section(config, "musicPlayerConfig");
  const displaySettings = section(config, "displaySettingsConfig");
  const cover = section(config, "coverImageConfig");

  form.site.title = String(site.title || "");
  form.site.subtitle = String(site.subtitle || "");
  form.site.description = String(site.description || "");
  form.site.siteUrl = String(site.site_url || "");
  form.site.keywords = Array.isArray(site.keywords)
    ? site.keywords.join(", ")
    : "";
  form.site.lang = String(site.lang || "zh_CN");
  form.site.hue = Number(themeColor.hue ?? 270);
  form.site.defaultMode = String(themeColor.defaultMode || "system");
  form.site.pageWidth = Number(site.pageWidth ?? 110);
  form.site.postsPerPage = Number(
    section(site, "pagination").postsPerPage ?? 10
  );

  form.friendSite.name = String(
    friendSite.name || site.title || "SilverCode Nexus"
  );
  form.friendSite.description = String(
    friendSite.description || site.description || ""
  );
  form.friendSite.url = String(
    friendSite.url || site.site_url || "https://replow.org/"
  );
  form.friendSite.avatarUrl = String(
    friendSite.avatar_url ||
      profile.avatar ||
      "https://cdn.replow.org/replow-org/images/tx.jpg"
  );
  form.friendSite.accountUrl = String(
    friendSite.account_url || "https://account.replow.org/"
  );

  form.wallpaper.mode = String(wallpaper.mode || "banner");
  form.wallpaper.switchable = wallpaper.switchable !== false;
  form.wallpaper.desktop = firstImage(source.desktop);
  form.wallpaper.mobile = firstImage(source.mobile);
  form.wallpaper.lightDesktop = firstImage(wallpaper.desktopLight);
  form.wallpaper.lightMobile = firstImage(wallpaper.mobileLight);
  form.wallpaper.overlayOpacity = Number(overlay.opacity ?? 0.8);
  form.wallpaper.overlayBlur = Number(overlay.blur ?? 10);
  form.wallpaper.waves = bannerWaves.enable !== false;
  form.wallpaper.carousel = Boolean(section(common, "carousel").enable);
  form.wallpaper.carouselInterval = Number(
    section(common, "carousel").interval ?? 5000
  );

  form.features.friends = pages.friends !== false;
  form.features.sponsor = Boolean(pages.sponsor);
  form.features.guestbook = pages.guestbook !== false;
  form.features.bangumi = Boolean(pages.bangumi);
  form.features.gallery = Boolean(pages.gallery);
  form.features.categoryBar = site.categoryBar !== false;
  form.features.footer = footer.enable !== false;
  form.features.announcement =
    announcement.enable !== false && Object.keys(announcement).length > 0;
  form.features.comments = String(comments.type || "none");
  form.features.musicNavbar = music.showInNavbar !== false;
  form.features.musicSidebar = music.showInSidebar !== false;
  form.features.sakura = Boolean(section(config, "sakuraConfig").enable);
  form.features.live2d = Boolean(section(config, "live2dWidgetConfig").enable);
  form.features.spine = Boolean(section(config, "spineModelConfig").enable);
  form.features.displaySettings = Boolean(displaySettings.enable);
  form.features.coverInPost = cover.enableInPost !== false;
  form.features.generateOgImages = post.generateOgImages !== false;
  form.features.showLastModified = post.showLastModified !== false;
  form.features.sharePoster = post.sharePoster !== false;

  form.announcement.title = String(announcement.title || "网站公告");
  form.announcement.content = String(announcement.content || "");
  form.announcement.closable = announcement.closable !== false;
  form.announcement.linkText = String(announcementLink.text || "");
  form.announcement.linkUrl = String(announcementLink.url || "");
  form.announcement.linkEnabled = Boolean(announcementLink.enable);

  form.sidebar.enable = sidebar.enable !== false;
  form.sidebar.position = String(sidebar.position || "both");
  form.sidebar.tabletSidebar = String(sidebar.tabletSidebar || "left");
  form.sidebar.showBothOnPost = sidebar.showBothSidebarsOnPostPage !== false;

  form.footerHtml = String(footer.customHtml || "");
  jsonText.value = JSON.stringify(config, null, 2);
}

function syncFormToConfig(config: FireflyConfig) {
  config.siteConfig = { ...section(config, "siteConfig") };
  config.siteConfig.title = form.site.title;
  config.siteConfig.subtitle = form.site.subtitle;
  config.siteConfig.description = form.site.description;
  config.siteConfig.site_url = form.site.siteUrl;
  config.siteConfig.keywords = form.site.keywords
    .split(",")
    .map(item => item.trim())
    .filter(Boolean);
  config.siteConfig.lang = form.site.lang;
  config.siteConfig.themeColor = {
    ...section(config.siteConfig, "themeColor"),
    hue: form.site.hue,
    defaultMode: form.site.defaultMode
  };
  config.siteConfig.pageWidth = form.site.pageWidth;
  config.siteConfig.categoryBar = form.features.categoryBar;
  config.siteConfig.pagination = {
    ...section(config.siteConfig, "pagination"),
    postsPerPage: form.site.postsPerPage
  };
  config.siteConfig.pages = {
    ...section(config.siteConfig, "pages"),
    friends: form.features.friends,
    sponsor: form.features.sponsor,
    guestbook: form.features.guestbook,
    bangumi: form.features.bangumi,
    gallery: form.features.gallery
  };
  config.siteConfig.post = {
    ...section(config.siteConfig, "post"),
    generateOgImages: form.features.generateOgImages,
    showLastModified: form.features.showLastModified,
    sharePoster: form.features.sharePoster
  };

  config.friendSiteInfo = {
    ...section(config, "friendSiteInfo"),
    name: form.friendSite.name.trim(),
    description: form.friendSite.description.trim(),
    url: form.friendSite.url.trim(),
    avatar_url: form.friendSite.avatarUrl.trim(),
    account_url: form.friendSite.accountUrl.trim()
  };

  config.backgroundWallpaper = { ...section(config, "backgroundWallpaper") };
  config.backgroundWallpaper.mode = form.wallpaper.mode;
  config.backgroundWallpaper.switchable = form.wallpaper.switchable;
  config.backgroundWallpaper.src = {
    desktop: form.wallpaper.desktop ? [form.wallpaper.desktop] : [],
    mobile: form.wallpaper.mobile ? [form.wallpaper.mobile] : []
  };
  config.backgroundWallpaper.desktopLight = form.wallpaper.lightDesktop
    ? [form.wallpaper.lightDesktop]
    : [];
  config.backgroundWallpaper.mobileLight = form.wallpaper.lightMobile
    ? [form.wallpaper.lightMobile]
    : [];
  config.backgroundWallpaper.overlay = {
    ...section(config.backgroundWallpaper, "overlay"),
    opacity: form.wallpaper.overlayOpacity,
    blur: form.wallpaper.overlayBlur
  };
  config.backgroundWallpaper.banner = {
    ...section(config.backgroundWallpaper, "banner"),
    waves: {
      ...section(section(config.backgroundWallpaper, "banner"), "waves"),
      enable: form.wallpaper.waves
    }
  };
  config.backgroundWallpaper.common = {
    ...section(config.backgroundWallpaper, "common"),
    carousel: {
      ...section(section(config.backgroundWallpaper, "common"), "carousel"),
      enable: form.wallpaper.carousel,
      interval: form.wallpaper.carouselInterval
    },
    homeText: {
      ...section(section(config.backgroundWallpaper, "common"), "homeText"),
      enable: form.features.announcement
        ? section(section(config.backgroundWallpaper, "common"), "homeText")
            .enable !== false
        : false
    }
  };

  config.announcementConfig = {
    ...section(config, "announcementConfig"),
    enable: form.features.announcement,
    title: form.announcement.title,
    content: form.announcement.content,
    closable: form.announcement.closable,
    link: {
      ...section(section(config, "announcementConfig"), "link"),
      enable: form.announcement.linkEnabled,
      text: form.announcement.linkText,
      url: form.announcement.linkUrl
    }
  };
  config.footerConfig = {
    ...section(config, "footerConfig"),
    enable: form.features.footer,
    customHtml: form.footerHtml
  };
  config.sidebarLayoutConfig = {
    ...section(config, "sidebarLayoutConfig"),
    enable: form.sidebar.enable,
    position: "left",
    tabletSidebar: form.sidebar.tabletSidebar,
    showBothSidebarsOnPostPage: false
  };
  ["leftComponents", "rightComponents", "mobileBottomComponents"].forEach(
    key => {
      if (!Array.isArray(config.sidebarLayoutConfig[key])) return;
      config.sidebarLayoutConfig[key] = config.sidebarLayoutConfig[key].map(
        (item: FireflyConfig) =>
          item.type === "announcement"
            ? { ...item, enable: form.features.announcement }
            : item
      );
    }
  );
  config.commentConfig = {
    ...section(config, "commentConfig"),
    type: form.features.comments
  };
  config.musicPlayerConfig = {
    ...section(config, "musicPlayerConfig"),
    showInNavbar: form.features.musicNavbar,
    showInSidebar: form.features.musicSidebar
  };
  config.sakuraConfig = {
    ...section(config, "sakuraConfig"),
    enable: form.features.sakura
  };
  config.live2dWidgetConfig = {
    ...section(config, "live2dWidgetConfig"),
    enable: form.features.live2d
  };
  config.spineModelConfig = {
    ...section(config, "spineModelConfig"),
    enable: form.features.spine
  };
  config.displaySettingsConfig = {
    ...section(config, "displaySettingsConfig"),
    enable: form.features.displaySettings
  };
  config.coverImageConfig = {
    ...section(config, "coverImageConfig"),
    enableInPost: form.features.coverInPost
  };
}

async function load() {
  loading.value = true;
  try {
    const [fireflyResult, accountResult, cloudflareResult] = await Promise.all([
      getFireflyConfig(),
      getAccountSettings(),
      getCloudflareSettings()
    ]);
    firefly.value = fireflyResult.data || {};
    loadForm(firefly.value);
    applyAccount(accountResult.data);
    applyCloudflare(cloudflareResult.data);
  } catch {
    message("站点、账号或 Cloudflare 设置读取失败", { type: "error" });
  } finally {
    loading.value = false;
  }
}

function applyAccount(value: AccountSettings) {
  form.account.registrationEnabled = value.registration_enabled;
  form.account.emailVerificationEnabled = value.email_verification_enabled;
  form.mail.smtpHost = value.mail.smtp_host;
  form.mail.smtpPort = value.mail.smtp_port;
  form.mail.smtpUsername = value.mail.smtp_username;
  form.mail.fromEmail = value.mail.from_email;
  form.mail.senderName = value.mail.sender_name;
  form.mail.useTls = value.mail.use_tls;
  form.mail.useSsl = value.mail.use_ssl;
  form.mail.passwordConfigured = value.mail.password_configured;
  form.mail.configured = value.mail.configured;
}

function applyCloudflare(value: CloudflareSettings) {
  form.cloudflare.authType = value.auth_type || "api_token";
  form.cloudflare.email = value.email || "";
  form.cloudflare.credential = "";
  form.cloudflare.accountId = value.account_id || "";
  form.cloudflare.zoneId = value.zone_id || "";
  form.cloudflare.zoneName = value.zone_name || "replow.org";
  form.cloudflare.credentialConfigured = Boolean(value.credential_configured);
  form.cloudflare.configured = Boolean(value.configured);
  form.cloudflare.clearCredential = false;
}

async function saveFirefly() {
  saving.value = true;
  try {
    const parsed = JSON.parse(jsonText.value) as FireflyConfig;
    if (activeTab.value !== "advanced") syncFormToConfig(parsed);
    const result = await updateFireflyConfig(parsed);
    firefly.value = result.data || parsed;
    jsonText.value = JSON.stringify(firefly.value, null, 2);
    message(
      "通用设置已保存，前台动态同步；搜索和静态页面请在 Koharu 页构建发布",
      { type: "success" }
    );
  } catch (error) {
    message(
      error instanceof SyntaxError
        ? "高级 JSON 格式不正确"
        : "站点设置保存失败",
      { type: "error" }
    );
  } finally {
    saving.value = false;
  }
}

async function saveAccount() {
  accountSaving.value = true;
  try {
    const result = await updateAccountSettings({
      registration_enabled: form.account.registrationEnabled,
      email_verification_enabled: form.account.emailVerificationEnabled,
      mail: {
        smtp_host: form.mail.smtpHost,
        smtp_port: form.mail.smtpPort,
        smtp_username: form.mail.smtpUsername,
        smtp_password: form.mail.smtpPassword,
        from_email: form.mail.fromEmail,
        sender_name: form.mail.senderName,
        use_tls: form.mail.useTls,
        use_ssl: form.mail.useSsl
      }
    });
    form.mail.smtpPassword = "";
    applyAccount(result.data);
    message("SilverCode 账号设置已保存", { type: "success" });
  } catch {
    message("账号设置保存失败", { type: "error" });
  } finally {
    accountSaving.value = false;
  }
}

function cloudflareErrorDetail(error: unknown): string {
  const response = (error as any)?.response;
  const detail = response?.data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (response?.status) {
    return `HTTP ${response.status}${response.statusText ? ` ${response.statusText}` : ""}`;
  }
  if (error instanceof Error && error.message) return error.message;
  return "未返回具体错误信息";
}

async function testMail() {
  if (!form.mail.testRecipient) {
    message("请先填写测试收件地址", { type: "warning" });
    return;
  }
  mailTesting.value = true;
  try {
    await sendTestMail(form.mail.testRecipient);
    message("测试邮件已发送", { type: "success" });
  } catch {
    message("测试邮件发送失败，请检查 SMTP 配置", { type: "error" });
  } finally {
    mailTesting.value = false;
  }
}

async function saveCloudflare() {
  if (!form.cloudflare.accountId.trim()) {
    message("请填写 Cloudflare Account ID", { type: "warning" });
    return;
  }
  if (!form.cloudflare.zoneId.trim() && !form.cloudflare.zoneName.trim()) {
    message("请填写 Zone ID 或 Zone 域名", { type: "warning" });
    return;
  }
  if (
    form.cloudflare.authType === "global_key" &&
    !form.cloudflare.email.trim()
  ) {
    message("使用 Global API Key 时必须填写 Cloudflare 账号邮箱", {
      type: "warning"
    });
    return;
  }
  cloudflareSaving.value = true;
  try {
    const result = await updateCloudflareSettings({
      auth_type: form.cloudflare.authType,
      email: form.cloudflare.email.trim(),
      credential: form.cloudflare.credential.trim(),
      account_id: form.cloudflare.accountId.trim(),
      zone_id: form.cloudflare.zoneId.trim(),
      zone_name: form.cloudflare.zoneName.trim(),
      clear_credential: form.cloudflare.clearCredential
    });
    applyCloudflare(result.data);
    message("Cloudflare CDN 设置已保存", { type: "success" });
  } catch (error) {
    message(`Cloudflare CDN 设置保存失败：${cloudflareErrorDetail(error)}`, {
      type: "error",
      duration: 8000,
      showClose: true
    });
  } finally {
    cloudflareSaving.value = false;
  }
}

async function purgeCloudflare() {
  if (!form.cloudflare.configured) {
    message("请先保存可用的 Cloudflare 凭据和 Zone 配置", { type: "warning" });
    return;
  }
  try {
    await ElMessageBox.confirm(
      "这会清空当前 Cloudflare Zone 的全部 CDN 缓存。清理后短时间内资源会重新从源站回源，确定继续吗？",
      "清理全部 CDN 缓存",
      {
        confirmButtonText: "确定清理",
        cancelButtonText: "取消",
        type: "warning"
      }
    );
  } catch {
    return;
  }

  cloudflarePurging.value = true;
  try {
    const result = await purgeCloudflareCache();
    message(
      "Cloudflare 缓存已清理" +
        (result.zone_name ? "：" + result.zone_name : ""),
      { type: "success" }
    );
  } catch (error) {
    message(`Cloudflare 缓存清理失败：${cloudflareErrorDetail(error)}`, {
      type: "error",
      duration: 10000,
      showClose: true
    });
  } finally {
    cloudflarePurging.value = false;
  }
}

onMounted(load);
</script>

<template>
  <div class="page-wrap" v-loading="loading">
    <el-card shadow="never">
      <template #header>
        <div class="toolbar">
          <div>
            <strong>Koharu 与 SilverCode 设置</strong>
            <span class="subtle">站点配置同时用于构建与 API 动态同步</span>
          </div>
          <el-button
            :loading="saving"
            :disabled="activeTab === 'koharu'"
            type="primary"
            @click="saveFirefly"
            >保存通用设置</el-button
          >
        </div>
      </template>

      <el-tabs v-model="activeTab" class="settings-tabs">
        <el-tab-pane label="Koharu 主题" name="koharu"
          ><KoharuSettings :config="firefly" @saved="load"
        /></el-tab-pane>
        <el-tab-pane label="站点基础" name="site">
          <el-form label-position="top" class="settings-form">
            <el-row :gutter="18">
              <el-col :xs="24" :md="12"
                ><el-form-item label="站点标题"
                  ><el-input v-model="form.site.title" /></el-form-item
              ></el-col>
              <el-col :xs="24" :md="12"
                ><el-form-item label="副标题"
                  ><el-input v-model="form.site.subtitle" /></el-form-item
              ></el-col>
              <el-col :xs="24" :md="12"
                ><el-form-item label="站点 URL"
                  ><el-input
                    v-model="form.site.siteUrl"
                    placeholder="https://4z.ink" /></el-form-item
              ></el-col>
              <el-col :xs="24" :md="12"
                ><el-form-item label="语言"
                  ><el-select v-model="form.site.lang" class="full"
                    ><el-option label="简体中文" value="zh_CN" /><el-option
                      label="繁體中文"
                      value="zh_TW" /><el-option
                      label="English"
                      value="en" /></el-select></el-form-item
              ></el-col>
              <el-col :xs="24" :md="12"
                ><el-form-item label="主题色相"
                  ><el-input-number
                    v-model="form.site.hue"
                    :min="0"
                    :max="360"
                    class="full" /></el-form-item
              ></el-col>
              <el-col :xs="24" :md="12"
                ><el-form-item label="默认主题"
                  ><el-select v-model="form.site.defaultMode" class="full"
                    ><el-option label="跟随系统" value="system" /><el-option
                      label="浅色"
                      value="light" /><el-option
                      label="深色"
                      value="dark" /></el-select></el-form-item
              ></el-col>
              <el-col :xs="24" :md="12"
                ><el-form-item label="页面宽度（rem）"
                  ><el-input-number
                    v-model="form.site.pageWidth"
                    :min="60"
                    :max="180"
                    class="full" /></el-form-item
              ></el-col>
              <el-col :xs="24" :md="12"
                ><el-form-item label="每页文章数"
                  ><el-input-number
                    v-model="form.site.postsPerPage"
                    :min="1"
                    :max="100"
                    class="full" /></el-form-item
              ></el-col>
            </el-row>
            <el-form-item label="站点描述"
              ><el-input
                v-model="form.site.description"
                type="textarea"
                :rows="3"
            /></el-form-item>
            <el-form-item label="关键词（逗号分隔）"
              ><el-input v-model="form.site.keywords"
            /></el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="友链本站信息" name="friend-site">
          <el-form label-position="top" class="settings-form">
            <el-alert
              title="这里配置的是友情链接页面左侧展示的“本站信息”。保存后前台刷新即可生效，无需重新构建。"
              type="info"
              :closable="false"
              show-icon
              class="mb-4"
            />
            <el-row :gutter="18">
              <el-col :xs="24" :md="12">
                <el-form-item label="站点名称">
                  <el-input
                    v-model="form.friendSite.name"
                    placeholder="SilverCode Nexus"
                  />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :md="12">
                <el-form-item label="站点网址">
                  <el-input
                    v-model="form.friendSite.url"
                    placeholder="https://replow.org/"
                  />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :md="12">
                <el-form-item label="本站头像">
                  <MediaPicker
                    v-model="form.friendSite.avatarUrl"
                    category="site-avatar"
                  />
                </el-form-item>
              </el-col>
              <el-col :xs="24" :md="12">
                <el-form-item label="Account 申请入口">
                  <el-input
                    v-model="form.friendSite.accountUrl"
                    placeholder="https://account.replow.org/"
                  />
                </el-form-item>
              </el-col>
            </el-row>
            <el-form-item label="站点描述">
              <el-input
                v-model="form.friendSite.description"
                type="textarea"
                :rows="3"
                maxlength="500"
                show-word-limit
              />
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="壁纸与外观" name="appearance">
          <el-form label-position="top" class="settings-form">
            <el-row :gutter="18">
              <el-col :xs="24" :md="12"
                ><el-form-item label="壁纸模式"
                  ><el-select v-model="form.wallpaper.mode" class="full"
                    ><el-option label="横幅 Banner" value="banner" /><el-option
                      label="关闭"
                      value="none" /></el-select></el-form-item
              ></el-col>
              <el-col :xs="24" :md="12"
                ><el-form-item label="桌面壁纸"
                  ><MediaPicker
                    v-model="form.wallpaper.desktop"
                    category="wallpaper" /></el-form-item
              ></el-col>
              <el-col :xs="24" :md="12"
                ><el-form-item label="移动壁纸"
                  ><MediaPicker
                    v-model="form.wallpaper.mobile"
                    category="wallpaper" /></el-form-item
              ></el-col>
              <el-col :xs="24" :md="12"
                ><el-form-item label="覆盖模糊（px）"
                  ><el-input-number
                    v-model="form.wallpaper.overlayBlur"
                    :min="0"
                    :max="60"
                    class="full" /></el-form-item
              ></el-col>
              <el-col :xs="24" :md="8"
                ><el-form-item label="水波纹"
                  ><el-switch v-model="form.wallpaper.waves" /></el-form-item
              ></el-col>
              <el-col :xs="24" :md="8"
                ><el-form-item label="壁纸轮播"
                  ><el-switch v-model="form.wallpaper.carousel" /></el-form-item
              ></el-col>
              <el-col :xs="24" :md="8"
                ><el-form-item label="轮播间隔（ms）"
                  ><el-input-number
                    v-model="form.wallpaper.carouselInterval"
                    :min="3000"
                    :max="120000"
                    class="full" /></el-form-item
              ></el-col>
            </el-row>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="功能开关" name="features">
          <el-form label-position="top" class="settings-form">
            <el-form-item label="友链"
              ><el-switch v-model="form.features.friends"
            /></el-form-item>
            <el-form-item label="底栏"
              ><el-switch v-model="form.features.footer"
            /></el-form-item>
            <el-form-item label="公告"
              ><el-switch v-model="form.features.announcement"
            /></el-form-item>
            <el-form-item label="樱花特效"
              ><el-switch v-model="form.features.sakura"
            /></el-form-item>
            <el-form-item label="评论系统"
              ><el-select v-model="form.features.comments"
                ><el-option label="关闭" value="none" /><el-option
                  label="Twikoo"
                  value="twikoo" /><el-option
                  label="Waline"
                  value="waline" /><el-option
                  label="Giscus"
                  value="giscus" /></el-select
            ></el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="公告 / 侧栏 / 页脚" name="content">
          <el-form label-position="top" class="settings-form">
            <el-divider content-position="left">公告</el-divider>
            <el-form-item label="公告标题"
              ><el-input v-model="form.announcement.title"
            /></el-form-item>
            <el-form-item label="公告内容"
              ><el-input
                v-model="form.announcement.content"
                type="textarea"
                :rows="4"
            /></el-form-item>
            <el-row :gutter="18"
              ><el-col :span="12"
                ><el-form-item label="公告链接文字"
                  ><el-input
                    v-model="
                      form.announcement.linkText
                    " /></el-form-item></el-col
              ><el-col :span="12"
                ><el-form-item label="公告链接 URL"
                  ><el-input
                    v-model="
                      form.announcement.linkUrl
                    " /></el-form-item></el-col
            ></el-row>
            <div class="inline-switches">
              <el-form-item label="允许关闭"
                ><el-switch
                  v-model="form.announcement.closable" /></el-form-item
              ><el-form-item label="启用链接"
                ><el-switch v-model="form.announcement.linkEnabled"
              /></el-form-item>
            </div>
            <el-divider content-position="left">侧栏</el-divider>
            <el-row :gutter="18"
              ><el-col :span="8"
                ><el-form-item label="启用侧栏"
                  ><el-switch
                    v-model="form.sidebar.enable" /></el-form-item></el-col
              ><el-col :span="8"
                ><el-form-item label="位置"
                  ><el-select v-model="form.sidebar.position" class="full"
                    ><el-option
                      label="左侧"
                      value="left" /></el-select></el-form-item></el-col
              ><el-col :span="8"
                ><el-form-item label="平板侧栏"
                  ><el-select v-model="form.sidebar.tabletSidebar" class="full"
                    ><el-option label="左侧" value="left" /><el-option
                      label="右侧"
                      value="right" /></el-select></el-form-item></el-col
            ></el-row>
            <el-alert
              title="Koharu 使用左侧单侧栏，目录与个人信息在同一侧栏切换。"
              type="info"
              :closable="false"
            />
            <el-divider content-position="left">页脚 HTML</el-divider>
            <el-input
              v-model="form.footerHtml"
              type="textarea"
              :rows="8"
              placeholder="可填写备案号、版权信息等 HTML"
            />
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="SilverCode 账号与邮件" name="account">
          <el-form label-position="top" class="settings-form">
            <div class="inline-switches">
              <el-form-item label="允许注册"
                ><el-switch
                  v-model="form.account.registrationEnabled" /></el-form-item
              ><el-form-item label="启用邮箱验证"
                ><el-switch v-model="form.account.emailVerificationEnabled"
              /></el-form-item>
            </div>
            <el-alert
              title="注册流程：用户名 / 显示名称 / 邮箱 → 邮箱验证码 → 可选设置密码；未设置密码的账号只能使用邮箱验证码登录。"
              type="info"
              :closable="false"
              show-icon
            />
            <el-divider content-position="left">SMTP</el-divider>
            <el-row :gutter="18"
              ><el-col :span="16"
                ><el-form-item label="SMTP 主机"
                  ><el-input
                    v-model="form.mail.smtpHost"
                    placeholder="smtp.example.com" /></el-form-item></el-col
              ><el-col :span="8"
                ><el-form-item label="端口"
                  ><el-input-number
                    v-model="form.mail.smtpPort"
                    :min="1"
                    :max="65535"
                    class="full" /></el-form-item></el-col
              ><el-col :span="12"
                ><el-form-item label="SMTP 用户名"
                  ><el-input
                    v-model="form.mail.smtpUsername" /></el-form-item></el-col
              ><el-col :span="12"
                ><el-form-item label="SMTP 密码"
                  ><el-input
                    v-model="form.mail.smtpPassword"
                    type="password"
                    show-password
                    :placeholder="
                      form.mail.passwordConfigured
                        ? '已配置，留空表示不修改'
                        : '请输入密码'
                    " /></el-form-item></el-col
              ><el-col :span="12"
                ><el-form-item label="发件地址"
                  ><el-input
                    v-model="form.mail.fromEmail" /></el-form-item></el-col
              ><el-col :span="12"
                ><el-form-item label="发件人名称"
                  ><el-input
                    v-model="form.mail.senderName" /></el-form-item></el-col
            ></el-row>
            <div class="inline-switches">
              <el-form-item label="STARTTLS"
                ><el-switch v-model="form.mail.useTls" /></el-form-item
              ><el-form-item label="SSL"
                ><el-switch v-model="form.mail.useSsl"
              /></el-form-item>
            </div>
            <div class="account-actions">
              <el-button
                :loading="accountSaving"
                type="primary"
                @click="saveAccount"
                >保存账号设置</el-button
              ><el-input
                v-model="form.mail.testRecipient"
                class="test-email"
                placeholder="测试收件地址"
              /><el-button :loading="mailTesting" @click="testMail"
                >发送测试邮件</el-button
              >
            </div>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="Cloudflare CDN" name="cloudflare">
          <el-form label-position="top" class="settings-form">
            <el-alert
              title="Cloudflare 凭据只保存在服务器端加密存储。Account ID 用于限定 Zone 查询；推荐使用 API Token，并授予 Zone Read + Cache Purge 权限。"
              type="info"
              :closable="false"
              show-icon
              class="mb-4"
            />

            <el-row :gutter="18">
              <el-col :xs="24" :md="12">
                <el-form-item label="鉴权方式">
                  <el-select v-model="form.cloudflare.authType" class="full">
                    <el-option label="API Token（推荐）" value="api_token" />
                    <el-option label="Global API Key" value="global_key" />
                  </el-select>
                </el-form-item>
              </el-col>

              <el-col
                v-if="form.cloudflare.authType === 'global_key'"
                :xs="24"
                :md="12"
              >
                <el-form-item label="Cloudflare 账号邮箱">
                  <el-input
                    v-model="form.cloudflare.email"
                    placeholder="you@example.com"
                  />
                </el-form-item>
              </el-col>

              <el-col :xs="24" :md="12">
                <el-form-item
                  :label="
                    form.cloudflare.authType === 'global_key'
                      ? 'Global API Key'
                      : 'API Token'
                  "
                >
                  <el-input
                    v-model="form.cloudflare.credential"
                    type="password"
                    show-password
                    autocomplete="new-password"
                    :placeholder="
                      form.cloudflare.credentialConfigured
                        ? '已配置，留空表示不修改'
                        : '请输入 Cloudflare 凭据'
                    "
                  />
                </el-form-item>
              </el-col>

              <el-col :xs="24" :md="12">
                <el-form-item label="Account ID">
                  <el-input
                    v-model="form.cloudflare.accountId"
                    placeholder="Cloudflare 控制台中的 Account ID"
                  />
                </el-form-item>
              </el-col>

              <el-col :xs="24" :md="12">
                <el-form-item label="Zone 域名">
                  <el-input
                    v-model="form.cloudflare.zoneName"
                    placeholder="replow.org"
                  />
                </el-form-item>
              </el-col>

              <el-col :xs="24" :md="12">
                <el-form-item label="Zone ID（可选）">
                  <el-input
                    v-model="form.cloudflare.zoneId"
                    placeholder="留空时自动按 Zone 域名查询"
                  />
                </el-form-item>
              </el-col>
            </el-row>

            <div class="inline-switches">
              <el-form-item label="清除已保存凭据">
                <el-switch v-model="form.cloudflare.clearCredential" />
              </el-form-item>
              <span class="subtle"
                >勾选后需要点击“保存 Cloudflare 设置”才会提交清除。</span
              >
            </div>

            <el-alert
              :title="
                form.cloudflare.configured
                  ? 'Cloudflare CDN 已配置，可执行缓存清理。'
                  : 'Cloudflare CDN 尚未完整配置。'
              "
              :type="form.cloudflare.configured ? 'success' : 'warning'"
              :closable="false"
              show-icon
              class="mb-4"
            />

            <div class="account-actions">
              <el-button
                :loading="cloudflareSaving"
                type="primary"
                @click="saveCloudflare"
              >
                保存 Cloudflare 设置
              </el-button>
              <el-button
                :loading="cloudflarePurging"
                type="danger"
                @click="purgeCloudflare"
              >
                清理所有 CDN 缓存
              </el-button>
            </div>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="全部配置 JSON" name="advanced">
          <div class="advanced-tip">
            这里保留 Firefly
            的完整对象，未在上方列出的长尾设置（字体、导航、相册、赞助、广告、动画参数、第三方服务参数等）都可以直接编辑。保存时会保留未知字段。
          </div>
          <el-input
            v-model="jsonText"
            type="textarea"
            :rows="34"
            spellcheck="false"
            class="json-editor"
          />
        </el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>

<style scoped>
.page-wrap {
  padding: 2px;
}
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.subtle {
  display: block;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  margin-top: 5px;
}
.settings-tabs {
  min-height: 620px;
}
.settings-form {
  max-width: 960px;
}
.full {
  width: 100%;
}
.switch-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 4px 24px;
}
.inline-switches {
  display: flex;
  gap: 40px;
  align-items: center;
  flex-wrap: wrap;
}
.account-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-top: 20px;
}
.test-email {
  max-width: 280px;
}
.advanced-tip {
  color: var(--el-text-color-secondary);
  margin-bottom: 12px;
  line-height: 1.7;
}
.json-editor :deep(textarea) {
  font-family: var(--el-font-family-monospace);
  font-size: 12px;
  line-height: 1.5;
}
@media (max-width: 768px) {
  .toolbar {
    align-items: flex-start;
    flex-direction: column;
  }
  .switch-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>

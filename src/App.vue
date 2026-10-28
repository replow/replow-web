<script setup lang="ts">
import DownloadHistory from "./DownloadHistory.vue";
import ThemePicker from "./ThemePicker.vue";
import MediaLibrary from "./MediaLibrary.vue";
import type { MediaItem } from "./media";
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from "vue";
import {
  ApiError,
  authApi,
  clearSession,
  getSession,
  humanError,
  request,
  saveSession,
  type Article,
  type CommentItem,
  type FriendApplication,
  type NotificationItem,
  type Profile,
  type Restriction,
  type SessionData
} from "./api";

type Section = "downloads" | "overview" | "profile" | "security" | "articles" | "media" | "comments" | "notifications" | "friends";
// There is no sign-up page any more: code login creates the account when the
// email is unknown, so only "login" and "reset" remain.
type AuthMode = "login" | "reset";
type LoginMethod = "password" | "code";

const session = ref<SessionData | null>(getSession());
const booting = ref(Boolean(session.value));
const busy = ref(false);
const section = ref<Section>("overview");
const restrictions = ref<Restriction[]>([]);
const restrictionLoginMessage = ref("");
function restrictionText(item: Restriction) {
  const date = (value: string) => new Date(value).toLocaleString("zh-CN", {timeZone: "Asia/Shanghai", hour12: false});
  return `${item.label}：${item.reason}；开始日期：${date(item.started_at)}；解除日期：${item.until ? date(item.until) : "永久（需管理员解除）"}（北京时间）`;
}
function sessionEnded(event: Event) {
  const detail = String((event as CustomEvent).detail || "");
  clearSession(); session.value = null; profile.value = null; restrictions.value = [];
  if (detail.startsWith("账号封禁：")) restrictionLoginMessage.value = detail;
}
async function refreshRestrictions() {
  if (!session.value || document.visibilityState !== "visible") return;
  try { restrictions.value = (await request<{items: Restriction[]}>("/account/restrictions")).items; }
  catch { /* Authentication failures are handled by the shared request handler. */ }
}
const mobileMenuOpen = ref(false);
const authMode = ref<AuthMode>("login");
// Code login is the default: it is the only path that works for someone who
// has never been here before.
const loginMethod = ref<LoginMethod>("code");
const toast = reactive({ show: false, text: "", error: false });
let toastTimer = 0;

const profile = ref<Profile | null>(null);
const counts = reactive({ articles: 0, published_articles: 0, comments: 0, friend_applications: 0, replies: 0 });
const articles = ref<Article[]>([]);
const comments = ref<CommentItem[]>([]);
const notifications = ref<NotificationItem[]>([]);
const friendApps = ref<FriendApplication[]>([]);
const friendLimit = ref(3);
const friendActiveCount = ref(0);
const friendEditingId = ref<number | null>(null);

const loginForm = reactive({ identity: "", password: "", email: "", code: "" });
const resetForm = reactive({ email: "", code: "", password: "", confirm: "" });
const countdowns = reactive({ login: 0, reset: 0, email: 0 });

// The post-login setup dialog for accounts created by code login. `open` is the
// only gate; the username pre-fills with whatever was generated at creation so
// the person can simply accept it.
const setupOpen = ref(false);
const setupForm = reactive({ username: "", password: "", confirm: "" });

const profileForm = reactive({ display_name: "", avatar_url: "", bio: "", website_url: "" });
const emailForm = reactive({ email: "", code: "" });
const passwordForm = reactive({ old_password: "", new_password: "", confirm: "" });

type MediaTarget = "avatar" | "article" | "cover" | "icon";
const mediaTarget = ref<MediaTarget | null>(null);
const articleBodyRef = ref<HTMLTextAreaElement | null>(null);
const articleSelection = ref({start: 0, end: 0});
const mediaCategory = computed(() => mediaTarget.value === "avatar" ? "avatar" : "article");

function openMedia(target: MediaTarget) {
  if (target === "article") {
    articleSelection.value = {
      start: articleBodyRef.value?.selectionStart ?? articleForm.body_markdown.length,
      end: articleBodyRef.value?.selectionEnd ?? articleForm.body_markdown.length
    };
  }
  mediaTarget.value = target;
}

async function selectMedia(item: MediaItem) {
  if (!item.mime_type.startsWith("image/")) {
    notify("只能选择图片作为头像或文章插图", true);
    return;
  }
  const target = mediaTarget.value;
  mediaTarget.value = null;
  if (target === "avatar") {
    profileForm.avatar_url = item.public_url;
    await saveProfile();
  } else if (target === "cover") {
    articleForm.cover_url = item.public_url;
  } else if (target === "icon") {
    articleForm.icon_url = item.public_url;
  } else if (target === "article") {
    const {start, end} = articleSelection.value;
    const title = (item.original_name || "图片").replace(/([\\\]])/g, "\\$1");
    const markdown = `
![${title}](${item.public_url})
`;
    articleForm.body_markdown =
      articleForm.body_markdown.slice(0, start) + markdown +
      articleForm.body_markdown.slice(end);
    await nextTick();
    articleBodyRef.value?.focus();
    const position = start + markdown.length;
    articleBodyRef.value?.setSelectionRange(position, position);
  }
}

const articleEditorOpen = ref(false);
const articleEditingId = ref<number | null>(null);
const articleForm = reactive({
  title: "",
  slug: "",
  excerpt: "",
  body_markdown: "",
  cover_url: "",
  icon_url: "",
  category: "",
  tags: "",
  status: "draft"
});

const commentEditorOpen = ref(false);
const commentEditingId = ref<number | null>(null);
const commentBody = ref("");

const friendForm = reactive({
  site_name: "",
  website_url: "",
  avatar_url: "",
  language: "",
  rss_url: "",
  description: "",
  applicant_note: ""
});
const friendLanguageOptions = [
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
const friendQuotaRemaining = computed(() => Math.max(0, friendLimit.value - friendActiveCount.value));

const signedIn = computed(() => Boolean(session.value?.accessToken));
const isAdmin = computed(() => Boolean(session.value?.roles?.includes("admin") || profile.value?.role === "admin"));
const displayName = computed(() => profile.value?.display_name || session.value?.nickname || session.value?.username || "SilverCode 用户");

const navItems: Array<{ key: Section; label: string; icon: string }> = [
  { key: "overview", label: "概览", icon: "space_dashboard" },
  { key: "profile", label: "个人资料", icon: "account_circle" },
  { key: "security", label: "登录与安全", icon: "shield_lock" },
  { key: "articles", label: "我的文章", icon: "article" },
  { key: "media", label: "媒体库", icon: "image" },
  { key: "comments", label: "我的评论", icon: "forum" },
  { key: "notifications", label: "通知", icon: "notifications" },
  { key: "friends", label: "友情链接", icon: "link" },
  { key: "downloads", label: "历史下载", icon: "article" }
];

const currentSectionLabel = computed(
  () => navItems.find(item => item.key === section.value)?.label || "概览"
);

function selectSection(key: Section) {
  section.value = key;
  const url = new URL(window.location.href);
  url.searchParams.set("section", key);
  window.history.replaceState({}, "", url);
  mobileMenuOpen.value = false;
}

function returnToDownloader() {
  const value = new URL(window.location.href).searchParams.get('return_to');
  if (!value || setupOpen.value) return;
  try {
    const target = new URL(value);
    if (['https://www.replow.org', 'https://replow.org'].includes(target.origin) &&
        (/^\/(?:fanqie|post|posts)(?:\/|$)/.test(target.pathname))) window.location.assign(target.href);
  } catch { /* Ignore invalid external return URLs. */ }
}

function notify(text: string, error = false) {
  if (text.startsWith("账号封禁：")) restrictionLoginMessage.value = text;
  window.clearTimeout(toastTimer);
  toast.text = text;
  toast.error = error;
  toast.show = true;
  toastTimer = window.setTimeout(() => (toast.show = false), 3500);
}

function formatDate(value?: string) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function setAuthMode(mode: AuthMode) {
  authMode.value = mode;
  const url = new URL(window.location.href);
  if (mode === "login") url.searchParams.delete("mode");
  else url.searchParams.set("mode", mode);
  window.history.replaceState({}, "", url);
}

function startCountdown(key: keyof typeof countdowns, seconds = 60) {
  countdowns[key] = seconds;
  const timer = window.setInterval(() => {
    countdowns[key] -= 1;
    if (countdowns[key] <= 0) window.clearInterval(timer);
  }, 1000);
}

/**
 * Open the setup dialog when the account still needs a username and password.
 *
 * `requiresSetup` comes straight from the login response; on a restored session
 * we fall back to the profile flag. Both are the same server-side truth, the
 * profile just arrives one request later.
 */
function maybeOpenSetup(requiresSetup?: boolean) {
  const pending = requiresSetup ?? profile.value?.setup_completed === false;
  if (!pending) return;
  setupForm.username = profile.value?.username || session.value?.username || "";
  setupForm.password = "";
  setupForm.confirm = "";
  setupOpen.value = true;
}

async function finishAuth(data: SessionData, requiresSetup?: boolean) {
  saveSession(data);
  session.value = data;
  const url = new URL(window.location.href);
  url.searchParams.delete("mode");
  window.history.replaceState({}, "", url);
  await loadAll();
  maybeOpenSetup(requiresSetup);
  returnToDownloader();
}

const setupUsernamePreview = computed(() => setupForm.username.trim() || "自动生成");

async function saveSetup() {
  const username = setupForm.username.trim();
  if (username.length < 3) return notify("用户名至少需要 3 位", true);
  if (setupForm.password.length < 8) return notify("密码至少需要 8 位", true);
  if (setupForm.password !== setupForm.confirm) return notify("两次输入的密码不一致", true);
  busy.value = true;
  try {
    const result = await authApi.setupAccount(username, setupForm.password);
    saveSession(result.data);
    restrictionLoginMessage.value = "";
    session.value = result.data;
    setupOpen.value = false;
    setupForm.password = "";
    setupForm.confirm = "";
    await loadAll();
    notify("账号设置完成");
    returnToDownloader();
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    busy.value = false;
  }
}

async function skipSetup() {
  busy.value = true;
  try {
    const result = await authApi.skipAccountSetup();
    saveSession(result.data);
    restrictionLoginMessage.value = "";
    session.value = result.data;
    setupOpen.value = false;
    setupForm.password = "";
    setupForm.confirm = "";
    await loadAll();
    notify("已跳过，稍后可在「登录与安全」中设置密码");
    returnToDownloader();
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    busy.value = false;
  }
}

async function passwordLogin() {
  if (!loginForm.identity || !loginForm.password) return notify("请输入账号和密码", true);
  busy.value = true;
  try {
    const result = await authApi.passwordLogin(loginForm.identity, loginForm.password);
    await finishAuth(result.data);
    notify("欢迎回来");
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    busy.value = false;
  }
}

async function sendLoginCode() {
  if (!loginForm.email) return notify("请输入邮箱", true);
  if (countdowns.login > 0) return;
  busy.value = true;
  try {
    await authApi.sendCode({ email: loginForm.email, purpose: "login" });
    startCountdown("login");
    notify("登录验证码已发送");
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    busy.value = false;
  }
}

async function codeLogin() {
  if (!loginForm.email || loginForm.code.length !== 6) return notify("请输入邮箱和 6 位验证码", true);
  busy.value = true;
  try {
    const result = await authApi.codeLogin(loginForm.email, loginForm.code);
    await finishAuth(result.data, result.requiresSetup);
    notify(result.requiresSetup ? "账号已创建" : "登录成功");
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    busy.value = false;
  }
}

async function sendResetCode() {
  if (!resetForm.email) return notify("请输入账号邮箱", true);
  if (countdowns.reset > 0) return;
  busy.value = true;
  try {
    await authApi.sendCode({ email: resetForm.email, purpose: "reset" });
    startCountdown("reset");
    notify("重置验证码已发送");
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    busy.value = false;
  }
}

async function resetPassword() {
  if (resetForm.password.length < 8) return notify("新密码至少需要 8 位", true);
  if (resetForm.password !== resetForm.confirm) return notify("两次输入的密码不一致", true);
  if (resetForm.code.length !== 6) return notify("请输入 6 位邮箱验证码", true);
  busy.value = true;
  try {
    const verified = await authApi.resetVerify(resetForm.email, resetForm.code);
    const result = await authApi.resetConfirm(verified.resetToken, resetForm.password);
    await finishAuth(result.data);
    notify("密码已重置并完成登录");
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    busy.value = false;
  }
}

function syncProfileForm() {
  if (!profile.value) return;
  Object.assign(profileForm, {
    display_name: profile.value.display_name || "",
    avatar_url: profile.value.avatar_url || "",
    bio: profile.value.bio || "",
    website_url: profile.value.website_url || ""
  });
  emailForm.email = profile.value.email || "";
}

const refreshingNotifications = ref(false);
async function refreshNotifications() {
  if (!session.value || refreshingNotifications.value || document.visibilityState !== "visible") return;
  const username = session.value.username;
  refreshingNotifications.value = true;
  try {
    const result = await request<{ items: NotificationItem[] }>("/account/notifications?limit=200");
    if (session.value?.username === username) notifications.value = result.items || [];
  } catch { /* Preserve the current list during transient outages. */ }
  finally { refreshingNotifications.value = false; }
}
let notificationTimer = 0;

async function loadAll() {
  if (!session.value) return;
  booting.value = true;
  try {
    const overview = await request<any>("/account/overview");
    profile.value = overview.data.profile;
    restrictions.value = overview.data.restrictions || [];
    Object.assign(counts, overview.data.counts || {});
    notifications.value = overview.data.notifications || [];
    syncProfileForm();

    const [articleResult, commentResult, notificationResult, friendResult] = await Promise.all([
      request<any>("/account/articles?limit=200").catch(() => ({ items: [] })),
      request<any>("/account/comments?limit=200").catch(() => ({ items: [] })),
      request<any>("/account/notifications?limit=200").catch(() => ({ items: [] })),
      request<any>("/account/friend-links").catch(() => ({ items: [] }))
    ]);
    articles.value = articleResult.items || [];
    comments.value = commentResult.items || [];
    notifications.value = notificationResult.items || [];
    friendApps.value = friendResult.items || [];
    friendLimit.value = Number(friendResult.limit || 3);
    friendActiveCount.value = Number(
      friendResult.active_count ??
      friendApps.value.filter(item => item.status === "pending_email" || item.status === "approved").length
    );
  } catch (error) {
    clearSession();
    session.value = null;
    profile.value = null;
    notify(humanError(error), true);
  } finally {
    booting.value = false;
  }
}

async function saveProfile() {
  busy.value = true;
  try {
    const result = await request<any>("/account/profile", {
      method: "PUT",
      body: JSON.stringify(profileForm)
    });
    profile.value = result.data;
    syncProfileForm();
    notify("个人资料已保存");
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    busy.value = false;
  }
}

async function sendEmailCode() {
  if (!emailForm.email) return notify("请输入新邮箱", true);
  if (countdowns.email > 0) return;
  busy.value = true;
  try {
    await request("/account/email/verification", {
      method: "POST",
      body: JSON.stringify({ email: emailForm.email })
    });
    startCountdown("email");
    notify("邮箱变更验证码已发送");
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    busy.value = false;
  }
}

async function confirmEmailChange() {
  if (emailForm.code.length !== 6) return notify("请输入 6 位验证码", true);
  busy.value = true;
  try {
    const result = await request<any>("/account/email/change", {
      method: "POST",
      body: JSON.stringify({ email: emailForm.email, code: emailForm.code })
    });
    profile.value = result.data;
    emailForm.code = "";
    syncProfileForm();
    notify("邮箱已更新");
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    busy.value = false;
  }
}

async function changePassword() {
  if (passwordForm.new_password.length < 8) return notify("新密码至少需要 8 位", true);
  if (passwordForm.new_password !== passwordForm.confirm) return notify("两次输入的密码不一致", true);
  busy.value = true;
  try {
    const result = await request<any>("/account/password", {
      method: "POST",
      body: JSON.stringify({
        old_password: passwordForm.old_password || undefined,
        new_password: passwordForm.new_password
      })
    });
    if (result.data) {
      saveSession(result.data);
      restrictionLoginMessage.value = "";
    session.value = result.data;
    }
    Object.assign(passwordForm, { old_password: "", new_password: "", confirm: "" });
    notify("密码已更新");
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    busy.value = false;
  }
}

function emptyArticle() {
  return {
    title: "",
    slug: "",
    excerpt: "",
    body_markdown: "",
    cover_url: "",
    icon_url: "",
    category: "",
    tags: "",
    status: "draft"
  };
}

function slugify(value: string) {
  const slug = value
    .normalize("NFKD")
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/[\s-]+/g, "-");
  return slug || "post-" + Date.now();
}

function openNewArticle() {
  articleEditingId.value = null;
  Object.assign(articleForm, emptyArticle());
  articleEditorOpen.value = true;
}

async function openArticle(article: Article) {
  busy.value = true;
  try {
    const result = await request<any>("/account/articles/" + article.id);
    const item = result.data as Article;
    articleEditingId.value = item.id;
    Object.assign(articleForm, {
      title: item.title,
      slug: item.slug,
      excerpt: item.excerpt,
      body_markdown: item.body_markdown,
      cover_url: item.cover_url,
      icon_url: item.icon_url,
      category: item.category,
      tags: (item.tags || []).join(", "),
      status: item.status === "rejected" ? "draft" : item.status
    });
    articleEditorOpen.value = true;
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    busy.value = false;
  }
}

async function saveArticle() {
  if (!articleForm.title.trim() || !articleForm.body_markdown.trim()) return notify("标题和正文不能为空", true);
  if (!articleForm.slug) articleForm.slug = slugify(articleForm.title);
  const payload = {
    title: articleForm.title.trim(),
    slug: articleForm.slug.trim(),
    excerpt: articleForm.excerpt.trim(),
    body_markdown: articleForm.body_markdown,
    cover_url: articleForm.cover_url.trim(),
    icon_url: articleForm.icon_url.trim(),
    category: articleForm.category.trim(),
    tags: articleForm.tags.replace(/，/g, ",").split(",").map((v: string) => v.trim()).filter(Boolean),
    status: articleForm.status,
    is_pinned: false
  };
  busy.value = true;
  try {
    if (articleEditingId.value) {
      await request("/account/articles/" + articleEditingId.value, {
        method: "PUT",
        body: JSON.stringify(payload)
      });
      notify("文章已更新");
    } else {
      await request("/account/articles", { method: "POST", body: JSON.stringify(payload) });
      notify("文章已创建");
    }
    articleEditorOpen.value = false;
    await loadAll();
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    busy.value = false;
  }
}

async function removeArticle(article: Article) {
  if (!window.confirm("确定删除《" + article.title + "》吗？此操作不可撤销。")) return;
  busy.value = true;
  try {
    await request("/account/articles/" + article.id, { method: "DELETE" });
    notify("文章已删除");
    await loadAll();
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    busy.value = false;
  }
}

function openComment(item: CommentItem) {
  commentEditingId.value = item.id;
  commentBody.value = item.body_markdown;
  commentEditorOpen.value = true;
}

async function saveComment() {
  if (!commentEditingId.value || !commentBody.value.trim()) return notify("评论内容不能为空", true);
  busy.value = true;
  try {
    await request("/account/comments/" + commentEditingId.value, {
      method: "PUT",
      body: JSON.stringify({ body_markdown: commentBody.value })
    });
    commentEditorOpen.value = false;
    notify("评论已更新");
    await loadAll();
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    busy.value = false;
  }
}

async function removeComment(item: CommentItem) {
  if (!window.confirm("确定删除这条评论吗？")) return;
  busy.value = true;
  try {
    await request("/account/comments/" + item.id, { method: "DELETE" });
    notify("评论已删除");
    await loadAll();
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    busy.value = false;
  }
}

function resetFriendForm() {
  friendEditingId.value = null;
  Object.assign(friendForm, {
    site_name: "",
    website_url: "",
    avatar_url: "",
    language: "",
    rss_url: "",
    description: "",
    applicant_note: ""
  });
}

function editFriend(item: FriendApplication) {
  friendEditingId.value = item.id;
  Object.assign(friendForm, {
    site_name: item.site_name,
    website_url: item.website_url,
    avatar_url: item.avatar_url,
    language: item.language,
    rss_url: item.rss_url,
    description: item.description,
    applicant_note: item.applicant_note
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function createFriendApplication() {
  if (!friendForm.site_name || !friendForm.website_url) return notify("请填写站点名称和网址", true);
  if (!friendEditingId.value && friendQuotaRemaining.value <= 0) {
    return notify("每个账号最多只能拥有 3 个等待验证或已通过的友情链接", true);
  }
  busy.value = true;
  try {
    if (friendEditingId.value) {
      await request("/account/friend-links/" + friendEditingId.value, {
        method: "PUT",
        body: JSON.stringify(friendForm)
      });
      notify("友情链接资料已更新");
      resetFriendForm();
    } else {
      const result = await request<any>("/account/friend-links", {
        method: "POST",
        body: JSON.stringify(friendForm)
      });
      resetFriendForm();
      if (result.verification?.sent) {
        notify("申请已提交，认证地址已发送到账号邮箱");
      } else {
        notify("申请已提交，但认证邮件发送失败，可在申请记录中重新发送", true);
      }
    }
    await loadAll();
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    busy.value = false;
  }
}

async function resendFriendVerification(item: FriendApplication) {
  busy.value = true;
  try {
    await request("/account/friend-links/" + item.id + "/verification/send", { method: "POST" });
    notify("新的认证地址已发送到 " + (profile.value?.email || "账号邮箱"));
    await loadAll();
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    busy.value = false;
  }
}

async function removeFriend(item: FriendApplication) {
  const message = item.status === "approved"
    ? "确定删除「" + item.site_name + "」吗？删除后会立即从公开友情链接中移除。"
    : "确定删除「" + item.site_name + "」的申请吗？";
  if (!window.confirm(message)) return;
  busy.value = true;
  try {
    await request("/account/friend-links/" + item.id, { method: "DELETE" });
    if (friendEditingId.value === item.id) resetFriendForm();
    notify("友情链接已删除");
    await loadAll();
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    busy.value = false;
  }
}

async function verifyFriendFromUrl(token: string) {
  try {
    await request<any>(
      "/account/friend-links/verification/confirm?token=" + encodeURIComponent(token),
      {},
      false
    );
    notify("邮箱认证成功，友情链接已自动通过并公开展示");
    section.value = "friends";
  } catch (error) {
    notify(humanError(error), true);
  } finally {
    const url = new URL(window.location.href);
    url.searchParams.delete("friend_verify");
    window.history.replaceState({}, "", url);
  }
}

function logout() {
  void authApi.logout();
  clearSession();
  session.value = null;
  profile.value = null;
  articles.value = [];
  comments.value = [];
  notifications.value = [];
  friendApps.value = [];
  friendActiveCount.value = 0;
  friendLimit.value = 3;
  resetFriendForm();
  setAuthMode("login");
}

function goAdmin() {
  window.location.href = "https://admin.replow.org/";
}

let sessionSyncTimer: number | undefined;

async function syncSharedSession() {
  if (!session.value || document.visibilityState !== "visible") return;
  try {
    const restored = await authApi.session();
    if (restored) session.value = restored;
  } catch (error) {
    // A background probe must never end an active session on its own. Only a
    // hard 401 (revoked / expired refresh token) signs the user out; network
    // blips, cold starts, and transient 5xx responses are ignored.
    if (error instanceof ApiError && error.status === 401) {
      clearSession();
      session.value = null;
      profile.value = null;
      if (error.detail.startsWith("账号封禁：")) restrictionLoginMessage.value = error.detail;
      notify(humanError(error), true);
    }
  }
}

onMounted(async () => {
  window.addEventListener("silvercode-session-ended", sessionEnded);
  document.addEventListener("visibilitychange", refreshRestrictions);
  const url = new URL(window.location.href);
  const initialSection = url.searchParams.get("section");
  if (navItems.some(item => item.key === initialSection)) section.value = initialSection as Section;
  const mode = url.searchParams.get("mode");
  const friendVerifyToken = url.searchParams.get("friend_verify");
  if (mode === "reset") authMode.value = "reset";
  // The sign-up page no longer exists. Old links (bookmarks, docs, the main
  // site) that still carry ?mode=register should land on the login form rather
  // than on a blank screen, so drop the parameter.
  if (mode === "register") {
    url.searchParams.delete("mode");
    window.history.replaceState({}, "", url);
  }

  if (friendVerifyToken) {
    booting.value = true;
    await verifyFriendFromUrl(friendVerifyToken);
  }

  // The API's HttpOnly cookie is the source of truth shared with admin and
  // the public site. Local storage is only a rendering cache for this app.
  try {
    const restored = await authApi.session();
    session.value = restored;
  } catch (error) {
    clearSession();
    session.value = null;
    if (error instanceof ApiError && error.detail.startsWith("账号封禁：")) restrictionLoginMessage.value = error.detail;
  }

  if (session.value) {
    await loadAll();
    // A restored session may belong to an account that never finished setup.
    maybeOpenSetup();
    returnToDownloader();
  } else booting.value = false;
  document.addEventListener("visibilitychange", syncSharedSession);
  sessionSyncTimer = window.setInterval(syncSharedSession, 60_000);
  document.addEventListener("visibilitychange", refreshNotifications);
  notificationTimer = window.setInterval(() => { void refreshNotifications(); void refreshRestrictions(); }, 15_000);
});

onBeforeUnmount(() => {
  window.removeEventListener("silvercode-session-ended", sessionEnded);
  document.removeEventListener("visibilitychange", refreshRestrictions);
  document.removeEventListener("visibilitychange", syncSharedSession);
  if (sessionSyncTimer) window.clearInterval(sessionSyncTimer);
  document.removeEventListener("visibilitychange", refreshNotifications);
  window.clearInterval(notificationTimer);
});
</script>

<template>
  <div v-if="booting" class="loading-screen">
    <div>
      <div class="spinner"></div>
      <div>正在载入 SilverCode Account…</div>
    </div>
  </div>

  <main v-else-if="!signedIn" class="auth-page">
    <section class="auth-hero" aria-hidden="true">
      <img src="/illustration.svg" alt="" />
    </section>

    <section class="auth-panel">
      <div v-if="restrictionLoginMessage" class="restriction-notice" role="alert">{{ restrictionLoginMessage }}</div>
      <div class="auth-theme"><ThemePicker /></div>
      <div class="auth-card">
        <img class="login-avatar-logo" src="/avatar.svg" alt="" />
        <template v-if="authMode === 'login'">
          <h2>欢迎回来</h2>
          <p>输入邮箱收验证码即可登录，还没有账号会自动创建。</p>

          <div class="mode-tabs">
            <button :class="{ active: loginMethod === 'code' }" @click="loginMethod = 'code'">邮箱验证码</button>
            <button :class="{ active: loginMethod === 'password' }" @click="loginMethod = 'password'">密码</button>
          </div>

          <template v-if="loginMethod === 'code'">
            <div class="field">
              <label>邮箱</label>
              <input v-model.trim="loginForm.email" class="input" type="email" autocomplete="email" placeholder="name@example.com" />
            </div>
            <div class="field">
              <label>验证码</label>
              <div class="inline-field">
                <input v-model.trim="loginForm.code" class="input" inputmode="numeric" maxlength="6" placeholder="6 位验证码" @keyup.enter="codeLogin" />
                <button class="btn btn-soft" :disabled="busy || countdowns.login > 0" @click="sendLoginCode"><span class="material-symbols-rounded btn-icon" aria-hidden="true">mail</span>
                  {{ countdowns.login > 0 ? countdowns.login + "s" : "发送验证码" }}
                </button>
              </div>
            </div>
            <button class="btn btn-primary btn-wide" :disabled="busy" @click="codeLogin"><span class="material-symbols-rounded btn-icon" aria-hidden="true">mark_email_read</span>{{ busy ? "正在验证…" : "验证并登录" }}</button>
            <p class="hint">没注册过也没关系，验证通过后会自动创建账号，登录后可以再设置用户名和密码。</p>
          </template>

          <template v-else>
            <div class="field">
              <label>邮箱或用户名</label>
              <input v-model.trim="loginForm.identity" class="input" autocomplete="username" placeholder="name@example.com" @keyup.enter="passwordLogin" />
            </div>
            <div class="field">
              <label>密码</label>
              <input v-model="loginForm.password" class="input" type="password" autocomplete="current-password" placeholder="输入密码" @keyup.enter="passwordLogin" />
            </div>
            <button class="btn btn-primary btn-wide" :disabled="busy" @click="passwordLogin"><span class="material-symbols-rounded btn-icon" aria-hidden="true">login</span>{{ busy ? "正在登录…" : "登录" }}</button>
          </template>

          <div class="auth-links">
            <button @click="setAuthMode('reset')">忘记密码？</button>
            <a href="https://www.replow.org/">返回主站</a>
          </div>
        </template>

        <template v-else>
          <h2>找回密码</h2>
          <p>验证账号邮箱后设置一个新密码。</p>
          <div class="field"><label>邮箱</label><input v-model.trim="resetForm.email" class="input" type="email" autocomplete="email" placeholder="name@example.com" /></div>
          <div class="field">
            <label>验证码</label>
            <div class="inline-field">
              <input v-model.trim="resetForm.code" class="input" inputmode="numeric" maxlength="6" placeholder="6 位验证码" />
              <button class="btn btn-soft" :disabled="busy || countdowns.reset > 0" @click="sendResetCode"><span class="material-symbols-rounded btn-icon" aria-hidden="true">mail</span>
                {{ countdowns.reset > 0 ? countdowns.reset + "s" : "发送验证码" }}
              </button>
            </div>
          </div>
          <div class="field"><label>新密码</label><input v-model="resetForm.password" class="input" type="password" autocomplete="new-password" placeholder="至少 8 位" /></div>
          <div class="field"><label>确认新密码</label><input v-model="resetForm.confirm" class="input" type="password" autocomplete="new-password" placeholder="再次输入新密码" @keyup.enter="resetPassword" /></div>
          <button class="btn btn-primary btn-wide" :disabled="busy" @click="resetPassword"><span class="material-symbols-rounded btn-icon" aria-hidden="true">key</span>{{ busy ? "正在重置…" : "验证并重置密码" }}</button>
          <div class="auth-links"><button @click="setAuthMode('login')">返回登录</button></div>
        </template>
      </div>
    </section>
  </main>

  <div v-else class="app-shell">
    <div v-if="mobileMenuOpen" class="app-mask" @click="mobileMenuOpen = false"></div>

    <aside class="side-nav" :class="{ 'mobile-open': mobileMenuOpen }">
      <div class="sidebar-logo">
        <img src="/avatar.svg" alt="" />
        <div>
          <strong>SilverCode</strong>
          <span>Account Console</span>
        </div>
      </div>
      <div class="sidebar-caption">账号中心</div>
      <div class="sidebar-menu">
        <button
          v-for="item in navItems"
          :key="item.key"
          class="nav-item"
          :class="{ active: section === item.key }"
          @click="selectSection(item.key)"
        >
          <span class="nav-icon material-symbols-rounded" aria-hidden="true">{{ item.icon }}</span>
          <span>{{ item.label }}</span>
        </button>
      </div>
      <div class="sidebar-user">
        <div class="avatar">
          <img v-if="profile?.avatar_url" :src="profile.avatar_url" alt="" />
          <span v-else>{{ displayName.slice(0, 1).toUpperCase() }}</span>
        </div>
        <div>
          <strong>{{ displayName }}</strong>
          <span>{{ profile?.email || session?.username }}</span>
        </div>
      </div>
    </aside>

    <header class="topbar">
      <div class="topbar-left">
        <button class="top-icon menu-toggle" aria-label="打开菜单" @click="mobileMenuOpen = !mobileMenuOpen"><span class="material-symbols-rounded" aria-hidden="true">menu</span></button>
        <div class="page-context">
          <span>ACCOUNT</span>
          <strong>{{ currentSectionLabel }}</strong>
        </div>
      </div>
      <div class="top-actions">
        <ThemePicker />
        <a class="top-action-link hide-mobile" href="https://www.replow.org/"><span class="material-symbols-rounded btn-icon" aria-hidden="true">home</span>返回主站</a>
        <button v-if="isAdmin" class="top-action-link hide-mobile" @click="goAdmin"><span class="material-symbols-rounded btn-icon" aria-hidden="true">admin_panel_settings</span>管理后台</button>
        <div class="header-user">
          <div class="avatar">
            <img v-if="profile?.avatar_url" :src="profile.avatar_url" alt="" />
            <span v-else>{{ displayName.slice(0, 1).toUpperCase() }}</span>
          </div>
          <span class="hide-mobile">{{ displayName }}</span>
        </div>
        <button class="top-action-link" @click="logout"><span class="material-symbols-rounded btn-icon" aria-hidden="true">logout</span>退出登录</button>
      </div>
    </header>

    <div class="shell-grid">
      <section class="content">
        <div v-for="item in restrictions" :key="item.kind" class="restriction-notice" role="alert">{{ restrictionText(item) }}</div>
        <template v-if="section === 'overview'">
          <div class="page-heading">
            <div><h1>你好，{{ displayName }}</h1><p>这里是你的 SilverCode 账号概览。</p></div>
            <div class="page-actions"><button class="btn btn-soft" :disabled="busy" @click="loadAll"><span class="material-symbols-rounded btn-icon" aria-hidden="true">refresh</span>刷新</button></div>
          </div>

          <div class="card profile-hero">
            <div class="avatar">
              <img v-if="profile?.avatar_url" :src="profile.avatar_url" alt="" />
              <span v-else>{{ displayName.slice(0, 1).toUpperCase() }}</span>
            </div>
            <div class="profile-copy">
              <h2>{{ displayName }}</h2>
              <p>@{{ profile?.username }} · {{ profile?.email }}</p>
            </div>
            <span class="role-chip">{{ profile?.role === "admin" ? "管理员" : "SilverCode 用户" }}</span>
          </div>

          <div class="grid grid-4" style="margin-top:16px">
            <article class="card stat-card"><span class="stat-icon material-symbols-rounded" aria-hidden="true">article</span><div><div class="stat-value">{{ counts.articles }}</div><div class="stat-label">我的文章</div></div></article>
            <article class="card stat-card"><span class="stat-icon material-symbols-rounded" aria-hidden="true">task_alt</span><div><div class="stat-value">{{ counts.published_articles }}</div><div class="stat-label">已发布</div></div></article>
            <article class="card stat-card"><span class="stat-icon material-symbols-rounded" aria-hidden="true">forum</span><div><div class="stat-value">{{ counts.comments }}</div><div class="stat-label">我的评论</div></div></article>
            <article class="card stat-card"><span class="stat-icon material-symbols-rounded" aria-hidden="true">mark_unread_chat_alt</span><div><div class="stat-value">{{ counts.replies }}</div><div class="stat-label">评论回复</div></div></article>
          </div>

          <div class="grid grid-2" style="margin-top:16px">
            <article class="card">
              <div class="card-head"><div><h2>最近通知</h2><div class="card-sub">评论回复和系统状态更新</div></div><button class="link-button" @click="section='notifications'"><span class="material-symbols-rounded btn-icon" aria-hidden="true">arrow_forward</span>查看全部</button></div>
              <div v-if="notifications.length" class="list">
                <div v-for="item in notifications.slice(0,5)" :key="item.id" class="list-item">
                  <div class="nav-icon material-symbols-rounded" aria-hidden="true">{{ item.type === 'comment_reply' ? 'reply' : item.type === 'friend_link' ? 'link' : 'notifications' }}</div>
                  <div class="list-main"><strong>{{ item.title }}</strong><p>{{ item.body }}</p></div>
                  <span class="small">{{ formatDate(item.created_at) }}</span>
                </div>
              </div>
              <div v-else class="empty">暂时没有新通知</div>
            </article>
            <article class="card">
              <div class="card-head"><div><h2>快捷操作</h2><div class="card-sub">继续创作或完善账号资料</div></div></div>
              <div class="grid grid-2">
                <button class="btn btn-primary" @click="section='articles'; openNewArticle()"><span class="material-symbols-rounded btn-icon" aria-hidden="true">add</span>新建文章</button>
                <button class="btn btn-soft" @click="section='profile'"><span class="material-symbols-rounded btn-icon" aria-hidden="true">edit</span>修改资料</button>
                <button class="btn btn-ghost" @click="section='friends'"><span class="material-symbols-rounded btn-icon" aria-hidden="true">add_link</span>申请友链</button>
                <button class="btn btn-ghost" @click="section='security'"><span class="material-symbols-rounded btn-icon" aria-hidden="true">security</span>登录与安全</button>
              </div>
            </article>
          </div>
        </template>

        <template v-else-if="section === 'profile'">
          <div class="page-heading"><div><h1>个人资料</h1><p>管理别人看到的名称、头像和个人信息。</p></div></div>
          <div class="grid grid-2">
            <article class="card solid">
              <div class="card-head"><div><h2>公开资料</h2><div class="card-sub">修改后会同步用于文章作者和后续评论。</div></div></div>
              <div class="field"><label>显示名称</label><input v-model="profileForm.display_name" class="input" maxlength="80" /></div>
              <div class="field"><label>头像 URL</label><input v-model="profileForm.avatar_url" class="input" placeholder="https://..." />
                <div class="media-field-actions">
                  <button class="btn btn-soft" :disabled="busy" @click="openMedia('avatar')">上传头像 / 从媒体库选择</button>
                  <img v-if="profileForm.avatar_url" :src="profileForm.avatar_url" class="media-avatar-preview" alt="头像预览"/>
                </div>
              </div>
              <div class="field"><label>个人简介</label><textarea v-model="profileForm.bio" class="textarea" maxlength="500" placeholder="介绍一下自己"></textarea></div>
              <div class="field"><label>个人网站</label><input v-model="profileForm.website_url" class="input" placeholder="https://..." /></div>
              <button class="btn btn-primary" :disabled="busy" @click="saveProfile"><span class="material-symbols-rounded btn-icon" aria-hidden="true">save</span>保存资料</button>
            </article>
            <article class="card">
              <div class="card-head"><div><h2>账号邮箱</h2><div class="card-sub">修改邮箱必须验证新的邮箱地址。</div></div></div>
              <div class="notice">当前邮箱：{{ profile?.email }}。发送验证码后，新邮箱验证成功才会正式替换。</div>
              <div class="field" style="margin-top:18px"><label>新邮箱</label><input v-model.trim="emailForm.email" class="input" type="email" /></div>
              <div class="field">
                <label>验证码</label>
                <div class="inline-field">
                  <input v-model.trim="emailForm.code" class="input" inputmode="numeric" maxlength="6" placeholder="6 位验证码" />
                  <button class="btn btn-soft" :disabled="busy || countdowns.email > 0" @click="sendEmailCode"><span class="material-symbols-rounded btn-icon" aria-hidden="true">mail</span>{{ countdowns.email > 0 ? countdowns.email + "s" : "发送验证码" }}</button>
                </div>
              </div>
              <button class="btn btn-primary" :disabled="busy" @click="confirmEmailChange"><span class="material-symbols-rounded btn-icon" aria-hidden="true">verified</span>验证并修改邮箱</button>
            </article>
          </div>
        </template>

        <template v-else-if="section === 'security'">
          <div class="page-heading"><div><h1>登录与安全</h1><p>密码登录与邮箱验证码登录可以同时使用。</p></div></div>
          <div class="grid grid-2">
            <article class="card solid">
              <div class="card-head"><div><h2>修改密码</h2><div class="card-sub">新密码至少 8 位。未设置过密码的账号旧密码可留空。</div></div></div>
              <div class="field"><label>当前密码</label><input v-model="passwordForm.old_password" class="input" type="password" autocomplete="current-password" /></div>
              <div class="field"><label>新密码</label><input v-model="passwordForm.new_password" class="input" type="password" autocomplete="new-password" /></div>
              <div class="field"><label>确认新密码</label><input v-model="passwordForm.confirm" class="input" type="password" autocomplete="new-password" /></div>
              <button class="btn btn-primary" :disabled="busy" @click="changePassword"><span class="material-symbols-rounded btn-icon" aria-hidden="true">shield_lock</span>更新密码</button>
            </article>
            <article class="card">
              <div class="card-head"><div><h2>邮箱验证码登录</h2><div class="card-sub">不想输入密码时，可以直接使用账号邮箱获取一次性验证码。</div></div></div>
              <div class="notice">登录邮箱：{{ profile?.email }}。验证码 10 分钟有效，并有频率限制。</div>
              <div class="card-sub" style="margin-top:18px">如果忘记密码，请退出账号后在登录页选择“忘记密码”。</div>
            </article>
          </div>
        </template>

        <template v-else-if="section === 'articles'">
          <div class="page-heading">
            <div><h1>我的文章</h1><p>发布、修改或删除属于你的文章。</p></div>
            <div class="page-actions"><button class="btn btn-primary" @click="openNewArticle"><span class="material-symbols-rounded btn-icon" aria-hidden="true">add</span>新建文章</button></div>
          </div>
          <div class="card">
            <div v-if="articles.length" class="table-wrap">
              <table class="table">
                <thead><tr><th>标题</th><th>状态</th><th>分类</th><th>更新时间</th><th style="text-align:right">操作</th></tr></thead>
                <tbody>
                  <tr v-for="item in articles" :key="item.id">
                    <td><strong>{{ item.title }}</strong><div class="small">/{{ item.slug }}</div></td>
                    <td><span class="status-chip" :class="item.status">{{ item.status === 'published' ? '已发布' : item.status === 'draft' ? '草稿' : item.status === 'pending' ? '待处理' : '已拒绝' }}</span></td>
                    <td>{{ item.category || "—" }}</td>
                    <td>{{ formatDate(item.updated_at) }}</td>
                    <td><div class="table-actions"><button class="link-button" @click="openArticle(item)"><span class="material-symbols-rounded btn-icon" aria-hidden="true">edit</span>编辑</button><button class="link-button danger" @click="removeArticle(item)"><span class="material-symbols-rounded btn-icon" aria-hidden="true">delete</span>删除</button></div></td>
                  </tr>
                </tbody>
              </table>
            </div>
            <div v-else class="empty">还没有文章，创建你的第一篇内容吧。</div>
          </div>
        </template>

        <template v-else-if="section === 'comments'">
          <div class="page-heading"><div><h1>我的评论</h1><p>你可以修改或删除自己发布的评论。</p></div></div>
          <div class="card">
            <div v-if="comments.length" class="list">
              <div v-for="item in comments" :key="item.id" class="list-item">
                <div class="nav-icon material-symbols-rounded" aria-hidden="true">chat_bubble</div>
                <div class="list-main">
                  <strong>{{ item.article_title || "文章评论" }}</strong>
                  <p>{{ item.body_markdown }}</p>
                  <div class="small">{{ formatDate(item.created_at) }}<span v-if="item.edited_at"> · 已编辑</span></div>
                </div>
                <div class="list-meta">
                  <button class="link-button" @click="openComment(item)"><span class="material-symbols-rounded btn-icon" aria-hidden="true">edit</span>修改</button>
                  <button class="link-button danger" @click="removeComment(item)"><span class="material-symbols-rounded btn-icon" aria-hidden="true">delete</span>删除</button>
                </div>
              </div>
            </div>
            <div v-else class="empty">你还没有发表过评论。</div>
          </div>
        </template>

        <template v-else-if="section === 'notifications'">
          <div class="page-heading"><div><h1>通知</h1><p>评论回复、文章状态和友情链接结果会显示在这里。</p></div><button class="link-button" :disabled="refreshingNotifications" @click="refreshNotifications"><span class="material-symbols-rounded btn-icon" aria-hidden="true">refresh</span>刷新通知</button></div>
          <div class="card">
            <div v-if="notifications.length" class="list">
              <a v-for="item in notifications" :key="item.id" class="list-item" :href="item.href || undefined" :target="item.href ? '_blank' : undefined" rel="noopener">
                <div class="nav-icon material-symbols-rounded" aria-hidden="true">{{ item.type === 'comment_reply' ? 'reply' : item.type === 'friend_link' ? 'link' : 'notifications' }}</div>
                <div class="list-main"><strong>{{ item.title }}</strong><p>{{ item.body }}</p><div class="small">{{ formatDate(item.created_at) }}</div></div>
              </a>
            </div>
            <div v-else class="empty">暂时没有通知。</div>
          </div>
        </template>

        <MediaLibrary v-else-if="section === 'media'" />
        <DownloadHistory v-else-if="section === 'downloads'" />

        <template v-else>
          <div class="page-heading">
            <div>
              <h1>友情链接</h1>
              <p>每个账号最多 3 个。提交后会向账号邮箱发送认证地址，打开后自动通过并公开展示。</p>
            </div>
          </div>
          <div class="grid grid-2">
            <article class="card solid">
              <div class="card-head">
                <div>
                  <h2>{{ friendEditingId ? "管理友情链接" : "申请友情链接" }}</h2>
                  <div class="card-sub">
                    {{ friendEditingId ? "保存后会同步更新你的申请；已通过友链会立即更新公开展示。" : "认证邮件发送至 " + (profile?.email || "当前账号邮箱") }}
                  </div>
                </div>
              </div>

              <div class="notice" style="margin-bottom:18px">
                当前占用 {{ friendActiveCount }} / {{ friendLimit }} 个名额，还可申请 {{ friendQuotaRemaining }} 个。
                等待认证和已通过的友链会占用名额，删除后会立即释放。
              </div>

              <div class="field"><label>站点名称 <span class="req">*</span></label><input v-model="friendForm.site_name" class="input" maxlength="120" /></div>
              <div class="field"><label>网址 <span class="req">*</span></label><input v-model="friendForm.website_url" class="input" placeholder="https://example.com" /></div>
              <div class="field"><label>头像 / Logo URL <span class="opt">（可选，留空用默认图）</span></label><input v-model="friendForm.avatar_url" class="input" placeholder="https://..." /></div>
              <div class="field"><label>网站语言 / 技术栈 <span class="opt">（可选）</span></label><input v-model="friendForm.language" class="input" list="friend-language-options" placeholder="请选择或自定义填写" /></div>
              <datalist id="friend-language-options">
                <option v-for="item in friendLanguageOptions" :key="item" :value="item" />
              </datalist>
              <div class="field"><label>RSS 地址 <span class="opt">（可选，留空默认 /rss.xml）</span></label><input v-model="friendForm.rss_url" class="input" placeholder="留空默认使用网站根目录 /rss.xml" /></div>
              <div class="field"><label>站点介绍 <span class="opt">（可选）</span></label><textarea v-model="friendForm.description" class="textarea" maxlength="500"></textarea></div>
              <div class="field"><label>备注 <span class="opt">（可选）</span></label><textarea v-model="friendForm.applicant_note" class="textarea" maxlength="1000"></textarea></div>

              <div class="action-row">
                <button
                  class="btn btn-primary"
                  :disabled="busy || (!friendEditingId && friendQuotaRemaining <= 0)"
                  @click="createFriendApplication"
                >
                  <span class="material-symbols-rounded btn-icon" aria-hidden="true">{{ friendEditingId ? "save" : "send" }}</span>
                  {{ friendEditingId ? "保存修改" : "提交并发送认证邮件" }}
                </button>
                <button v-if="friendEditingId" class="btn btn-ghost" :disabled="busy" @click="resetFriendForm">取消编辑</button>
              </div>
            </article>

            <article class="card">
              <div class="card-head">
                <div>
                  <h2>我的友情链接</h2>
                  <div class="card-sub">你可以管理或删除自己提交的友链。已通过友链删除后会同时从公开页面移除。</div>
                </div>
              </div>
              <div v-if="friendApps.length" class="list">
                <div v-for="item in friendApps" :key="item.id" class="list-item">
                  <div class="list-main">
                    <strong>{{ item.site_name }}<span v-if="item.language" class="small"> · {{ item.language }}</span></strong>
                    <p>{{ item.website_url }}</p>
                    <p v-if="item.rss_url" class="small">RSS：{{ item.rss_url }}</p>
                    <span class="status-chip" :class="item.status">
                      {{ item.status === 'approved' ? '已通过并公开' : item.status === 'pending_email' ? '等待邮件认证' : '未通过' }}
                    </span>
                    <p v-if="item.status === 'pending_email' && item.verification_expires_at" class="small">
                      当前认证地址有效至 {{ formatDate(item.verification_expires_at) }}
                    </p>
                    <p v-if="item.rejection_reason">{{ item.rejection_reason }}</p>
                  </div>
                  <div class="list-meta">
                    <a class="link-button" :href="item.website_url" target="_blank" rel="noopener">访问</a>
                    <button class="link-button" :disabled="busy" @click="editFriend(item)">
                      <span class="material-symbols-rounded btn-icon" aria-hidden="true">edit</span>管理
                    </button>
                    <button
                      v-if="item.status === 'pending_email'"
                      class="link-button"
                      :disabled="busy"
                      @click="resendFriendVerification(item)"
                    >
                      <span class="material-symbols-rounded btn-icon" aria-hidden="true">mail</span>重发认证邮件
                    </button>
                    <button class="link-button danger" :disabled="busy" @click="removeFriend(item)">
                      <span class="material-symbols-rounded btn-icon" aria-hidden="true">delete</span>删除
                    </button>
                  </div>
                </div>
              </div>
              <div v-else class="empty">还没有申请过友情链接。</div>
            </article>
          </div>
        </template>
      </section>
    </div>

  </div>

  <div v-if="articleEditorOpen" class="modal-backdrop" @click.self="articleEditorOpen = false">
    <div class="modal wide">
      <div class="modal-head"><h2>{{ articleEditingId ? "编辑文章" : "新建文章" }}</h2><button class="close-btn" aria-label="关闭" @click="articleEditorOpen = false"><span class="material-symbols-rounded" aria-hidden="true">close</span></button></div>
      <div class="form-grid">
        <div class="field"><label>标题</label><input v-model="articleForm.title" class="input" maxlength="200" @blur="!articleForm.slug && (articleForm.slug = slugify(articleForm.title))" /></div>
        <div class="field"><label>Slug</label><input v-model="articleForm.slug" class="input" maxlength="220" placeholder="article-slug" /></div>
        <div class="field span-2"><label>摘要</label><input v-model="articleForm.excerpt" class="input" maxlength="500" /></div>
        <div class="field"><label>分类</label><input v-model="articleForm.category" class="input" maxlength="100" /></div>
        <div class="field"><label>标签（逗号分隔）</label><input v-model="articleForm.tags" class="input" placeholder="Astro, 随笔" /></div>
        <div class="field"><label>封面 URL</label><input v-model="articleForm.cover_url" class="input" placeholder="https://..." /><button class="btn btn-soft" @click="openMedia('cover')">从媒体库选择封面 / 上传图片</button></div>
        <div class="field"><label>图标 URL</label><input v-model="articleForm.icon_url" class="input" placeholder="可选" /><button class="btn btn-soft" @click="openMedia('icon')">选择图标图片</button></div>
        <div class="field"><label>状态</label><select v-model="articleForm.status" class="select"><option value="draft">草稿</option><option value="published">发布</option><option value="pending">待处理</option></select></div>
        <div class="field span-2">
          <div class="media-editor-row"><label>Markdown 正文</label><button class="btn btn-soft" @click="openMedia('article')">插入图片（上传 / 媒体库）</button></div>
          <textarea ref="articleBodyRef" v-model="articleForm.body_markdown" class="textarea markdown-editor" placeholder="# 开始写作…"></textarea>
          <div class="editor-meta"><span>支持 Markdown</span><span>{{ articleForm.body_markdown.length }} 字符</span></div>
        </div>
      </div>
      <div class="action-row"><button class="btn btn-primary" :disabled="busy" @click="saveArticle"><span class="material-symbols-rounded btn-icon" aria-hidden="true">save</span>保存文章</button><button class="btn btn-ghost" @click="articleEditorOpen = false">取消</button></div>
    </div>
  </div>

  <div v-if="mediaTarget" class="modal-backdrop media-picker-backdrop" @click.self="mediaTarget=null">
    <div class="modal wide">
      <MediaLibrary picker image-only :category="mediaCategory" @select="selectMedia" @close="mediaTarget=null" />
    </div>
  </div>

  <div v-if="commentEditorOpen" class="modal-backdrop" @click.self="commentEditorOpen = false">
    <div class="modal">
      <div class="modal-head"><h2>修改评论</h2><button class="close-btn" aria-label="关闭" @click="commentEditorOpen = false"><span class="material-symbols-rounded" aria-hidden="true">close</span></button></div>
      <div class="field"><label>Markdown 内容</label><textarea v-model="commentBody" class="textarea" style="min-height:220px"></textarea></div>
      <div class="action-row"><button class="btn btn-primary" :disabled="busy" @click="saveComment"><span class="material-symbols-rounded btn-icon" aria-hidden="true">save</span>保存修改</button><button class="btn btn-ghost" @click="commentEditorOpen = false">取消</button></div>
    </div>
  </div>

  <!-- Shown once for accounts created by a first-time code login. -->
  <div v-if="setupOpen" class="modal-backdrop">
    <div class="modal setup-modal">
      <div class="modal-head"><h2>设置你的账号</h2></div>

      <p class="setup-intro">
        账号已经创建好了。设好用户名和密码，下次就能直接用密码登录。
        显示名称会默认与用户名一致，之后可以在「个人资料」里随时修改。
      </p>

      <div class="field">
        <label>用户名</label>
        <input v-model.trim="setupForm.username" class="input" autocomplete="username" maxlength="32" placeholder="3–32 位用户名" />
        <div class="hint">用于登录，3–32 位字母、数字或 _ . -</div>
      </div>
      <div class="field">
        <label>密码</label>
        <input v-model="setupForm.password" class="input" type="password" autocomplete="new-password" placeholder="至少 8 位" />
      </div>
      <div class="field">
        <label>确认密码</label>
        <input v-model="setupForm.confirm" class="input" type="password" autocomplete="new-password" placeholder="再次输入密码" @keyup.enter="saveSetup" />
      </div>

      <div class="setup-actions">
        <!-- 图标名只能用字体子集里已有的：/assets/fonts/material-symbols-rounded-account.woff2
             是手工裁剪的子集，不在里面的连字会被当普通文字渲染出来，把按钮撑变形。
             save / arrow_forward 都在子集内（check_circle / skip_next 不在）。 -->
        <button class="btn btn-primary btn-wide" :disabled="busy" @click="saveSetup">
          <span class="material-symbols-rounded btn-icon" aria-hidden="true">save</span>{{ busy ? "正在保存…" : "保存并继续" }}
        </button>
        <button class="btn btn-skip btn-wide" :disabled="busy" @click="skipSetup">
          <span class="material-symbols-rounded btn-icon" aria-hidden="true">arrow_forward</span>先跳过
        </button>
      </div>

      <p class="setup-skip-note">
        跳过后会保留自动生成的用户名 <strong>{{ session?.username }}</strong>，密码留空，
        之后可以在「登录与安全」里补设密码。
      </p>
    </div>
  </div>

  <div v-if="toast.show" class="toast" :class="{ error: toast.error }">{{ toast.text }}</div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { getDashboard, type DashboardResponse } from "@/api/replow";
import { message } from "@/utils/message";
import { useUserStoreHook } from "@/store/modules/user";
import { MIRO_AVATAR } from "@/utils/miro-brand";
import ArticleIcon from "~icons/ri/article-line";
import CommentIcon from "~icons/ri/chat-3-line";
import UsersIcon from "~icons/ri/group-line";
import MediaIcon from "~icons/ri/image-2-line";
import ArrowIcon from "~icons/ri/arrow-right-up-line";
import SettingsIcon from "~icons/ri/settings-3-line";

defineOptions({ name: "Welcome" });

const loading = ref(true);
const dashboard = ref<DashboardResponse | null>(null);
const displayName = computed(
  () => useUserStoreHook().nickname || useUserStoreHook().username || "Replow"
);
const cards = [
  {
    key: "published_articles",
    label: "已发布文章",
    icon: ArticleIcon,
    tone: "violet"
  },
  { key: "comments", label: "评论", icon: CommentIcon, tone: "blue" },
  { key: "users", label: "用户", icon: UsersIcon, tone: "green" },
  { key: "media", label: "媒体文件", icon: MediaIcon, tone: "orange" }
] as const;
const shortcuts = [
  {
    path: "/replow/articles",
    title: "文章管理",
    description: "记录想法，继续写作",
    icon: ArticleIcon
  },
  {
    path: "/replow/media",
    title: "媒体库",
    description: "整理图片与附件",
    icon: MediaIcon
  },
  {
    path: "/replow/settings",
    title: "站点设置",
    description: "打造你的个人空间",
    icon: SettingsIcon
  }
];

function formatDate(value: string) {
  return value
    ? new Date(value).toLocaleString("zh-CN", { hour12: false })
    : "—";
}

async function loadDashboard() {
  loading.value = true;
  try {
    dashboard.value = await getDashboard();
  } catch {
    message("暂时无法读取仪表盘数据，请稍后重试", { type: "error" });
  } finally {
    loading.value = false;
  }
}

onMounted(loadDashboard);
</script>

<template>
  <div v-loading="loading" class="replow-dashboard">
    <section class="hero-card">
      <div class="hero-copy">
        <p class="eyebrow">MIRO / SILVER WOLF</p>
        <h1>欢迎回来，{{ displayName }}</h1>
        <p>管理你的文章、照片与站点，继续记录新的灵感。</p>
      </div>
      <img class="hero-portrait" :src="MIRO_AVATAR" alt="Silver Wolf 银狼" />
    </section>

    <section class="stat-grid">
      <el-card
        v-for="card in cards"
        :key="card.key"
        shadow="never"
        class="stat-card"
      >
        <div class="stat-icon" :class="'tone-' + card.tone">
          <component :is="card.icon" aria-hidden="true" />
        </div>
        <div>
          <p>{{ card.label }}</p>
          <strong>{{ dashboard?.counts?.[card.key] ?? 0 }}</strong>
        </div>
      </el-card>
    </section>

    <section class="content-grid">
      <el-card shadow="never" class="recent-card">
        <template #header>
          <div class="section-heading">
            <span>最近更新</span>
            <el-tag type="info" effect="plain"
              >{{ dashboard?.counts?.articles ?? 0 }} 篇文章</el-tag
            >
          </div>
        </template>
        <el-empty
          v-if="!dashboard?.recent_articles?.length"
          description="暂无文章"
        />
        <div v-else class="article-list">
          <div
            v-for="article in dashboard.recent_articles"
            :key="article.id"
            class="article-row"
          >
            <div class="article-copy">
              <strong>{{ article.title }}</strong>
              <span
                >{{ article.author || "未知作者" }} ·
                {{ formatDate(article.updated_at) }}</span
              >
            </div>
            <el-tag
              :type="article.status === 'published' ? 'success' : 'warning'"
              effect="light"
            >
              {{
                article.status === "published"
                  ? "已发布"
                  : article.status === "draft"
                    ? "草稿"
                    : article.status
              }}
            </el-tag>
          </div>
        </div>
      </el-card>

      <el-card shadow="never" class="shortcuts-card">
        <template #header
          ><div class="section-heading">
            <span>常用入口</span><span class="section-note">Miro Admin</span>
          </div></template
        >
        <div class="shortcut-list">
          <router-link
            v-for="item in shortcuts"
            :key="item.path"
            :to="item.path"
            class="shortcut"
          >
            <component
              :is="item.icon"
              class="shortcut-icon"
              aria-hidden="true"
            />
            <span
              ><strong>{{ item.title }}</strong
              ><small>{{ item.description }}</small></span
            >
            <ArrowIcon class="shortcut-arrow" aria-hidden="true" />
          </router-link>
          <a
            href="https://www.preview.replow.org/"
            target="_blank"
            rel="noopener noreferrer"
            class="site-link"
          >
            查看 Miro 站点 <ArrowIcon aria-hidden="true" />
          </a>
        </div>
      </el-card>
    </section>
  </div>
</template>

<style scoped>
.replow-dashboard {
  padding: 2px;
}
.hero-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  min-height: 180px;
  padding: 30px 36px;
  overflow: hidden;
  border: 1px solid #45405f;
  border-radius: 18px;
  color: #f8f5ff;
  background: linear-gradient(110deg, #242137, #443563);
}
.hero-copy {
  min-width: 0;
}
.eyebrow {
  margin: 0 0 10px;
  color: #c5b8e6;
  font-size: 11px;
  letter-spacing: 0.18em;
}
.hero-card h1 {
  margin: 0 0 12px;
  font-size: clamp(24px, 2.6vw, 34px);
  font-weight: 650;
  line-height: 1.4;
}
.hero-card p:not(.eyebrow) {
  margin: 0;
  color: #d9d1e9;
  font-size: 14px;
  line-height: 1.7;
}
.hero-portrait {
  width: 124px;
  height: 124px;
  flex: 0 0 auto;
  object-fit: cover;
  border: 3px solid #aa95d2;
  border-radius: 30px;
}
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-top: 18px;
}
.stat-card :deep(.el-card__body) {
  display: flex;
  gap: 14px;
  align-items: center;
  padding: 19px;
}
.stat-icon {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  flex: 0 0 auto;
  border-radius: 12px;
  font-size: 22px;
}
.stat-icon.tone-violet {
  color: #7760c9;
  background: #eee9fa;
}
.stat-icon.tone-blue {
  color: #397fa9;
  background: #e4f0f8;
}
.stat-icon.tone-green {
  color: #308467;
  background: #e2f3ea;
}
.stat-icon.tone-orange {
  color: #a16a35;
  background: #fcf0df;
}
.stat-card p {
  margin: 0 0 5px;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}
.stat-card strong {
  font-size: 27px;
  font-weight: 650;
  color: var(--el-text-color-primary);
}
.content-grid {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(280px, 0.8fr);
  gap: 18px;
  margin-top: 18px;
}
.recent-card :deep(.el-card__header),
.shortcuts-card :deep(.el-card__header) {
  padding: 17px 20px;
}
.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 650;
}
.section-note {
  color: var(--el-text-color-secondary);
  font-size: 11px;
  font-weight: 400;
}
.article-list {
  display: grid;
  gap: 3px;
}
.article-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 2px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.article-row:last-child {
  border-bottom: 0;
}
.article-copy {
  min-width: 0;
  display: grid;
  gap: 5px;
}
.article-copy strong {
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 14px;
  font-weight: 600;
  white-space: nowrap;
}
.article-copy span {
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.shortcut-list {
  display: grid;
  gap: 12px;
}
.shortcut {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 12px;
  color: var(--el-text-color-primary);
  transition:
    border-color 0.15s,
    background 0.15s;
}
.shortcut:hover {
  border-color: var(--el-color-primary);
  background: var(--el-fill-color-light);
}
.shortcut-icon {
  flex: 0 0 auto;
  color: var(--el-color-primary);
  font-size: 21px;
}
.shortcut span {
  min-width: 0;
  flex: 1;
}
.shortcut strong,
.shortcut small {
  display: block;
}
.shortcut strong {
  font-size: 14px;
  font-weight: 600;
}
.shortcut small {
  margin-top: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.shortcut-arrow {
  color: var(--el-text-color-secondary);
  font-size: 18px;
}
.site-link {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 10px;
  color: var(--el-color-primary);
  font-size: 13px;
}
@media (max-width: 1100px) {
  .stat-grid {
    grid-template-columns: repeat(2, 1fr);
  }
  .content-grid {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 600px) {
  .hero-card {
    min-height: 164px;
    padding: 24px 20px;
  }
  .hero-portrait {
    display: none;
  }
  .hero-card h1 {
    font-size: 23px;
  }
  .stat-grid {
    gap: 10px;
  }
  .stat-card :deep(.el-card__body) {
    gap: 9px;
    padding: 14px 12px;
  }
  .stat-icon {
    width: 34px;
    height: 34px;
    font-size: 19px;
  }
  .content-grid {
    gap: 12px;
  }
}
</style>

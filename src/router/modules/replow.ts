import BookIcon from "~icons/ri/book-open-line";
import AuditIcon from "~icons/ri/history-line";
import AlbumIcon from "~icons/ri/gallery-line";
import DynamicIcon from "~icons/ri/chat-smile-3-line";
import ContentIcon from "~icons/ri/layout-grid-line";
import ArticleIcon from "~icons/ri/article-line";
import MediaIcon from "~icons/ri/image-2-line";
import CommentIcon from "~icons/ri/chat-3-line";
import FriendsIcon from "~icons/ri/links-line";
import DomainIcon from "~icons/ri/global-line";
import SettingsIcon from "~icons/ri/settings-3-line";
import UsersIcon from "~icons/ri/group-line";
import ProfileIcon from "~icons/ri/account-circle-line";

const Layout = () => import("@/layout/index.vue");

export default {
  path: "/replow",
  name: "Replow",
  component: Layout,
  redirect: "/replow/articles",
  meta: {
    icon: ContentIcon,
    title: "内容管理",
    rank: 1
  },
  children: [
    {path:"/replow/fanqie",name:"ReplowFanqie",component:()=>import("@/views/replow/fanqie/index.vue"),meta:{title:"番茄小说管理",icon:BookIcon}},
    {
      path: "/replow/dynamics",
      name: "ReplowDynamics",
      component: () => import("@/views/replow/dynamics/index.vue"),
      meta: { title: "动态管理", icon: DynamicIcon }
    },
    {
      path: "/replow/albums",
      name: "ReplowAlbums",
      component: () => import("@/views/replow/albums/index.vue"),
      meta: { title: "相册管理", icon: AlbumIcon }
    },
    {
      path: "/replow/audit",
      name: "ReplowAudit",
      component: () => import("@/views/replow/audit/index.vue"),
      meta: { title: "操作日志", icon: AuditIcon }
    },
    {
      path: "/replow/articles",
      name: "ReplowArticles",
      component: () => import("@/views/replow/articles/index.vue"),
      meta: { title: "文章管理", icon: ArticleIcon }
    },
    {
      path: "/replow/media",
      name: "ReplowMedia",
      component: () => import("@/views/replow/media/index.vue"),
      meta: { title: "媒体库", icon: MediaIcon }
    },
    {
      path: "/replow/media/storage",
      name: "ReplowMediaStorage",
      component: () => import("@/views/replow/media/storage.vue"),
      meta: { title: "媒体存储设置", icon: SettingsIcon }
    },
    {
      path: "/replow/comments",
      name: "ReplowComments",
      component: () => import("@/views/replow/comments/index.vue"),
      meta: { title: "评论管理", icon: CommentIcon }
    },
    {
      path: "/replow/friends",
      name: "ReplowFriends",
      component: () => import("@/views/replow/friends/index.vue"),
      meta: { title: "友链管理", icon: FriendsIcon }
    },
    {
      path: "/replow/access-keys",
      name: "ReplowAccessKeys",
      component: () => import("@/views/replow/access-keys/index.vue"),
      meta: { title: "域名注册", icon: DomainIcon }
    },
    {
      path: "/replow/settings",
      name: "ReplowSettings",
      component: () => import("@/views/replow/settings/index.vue"),
      meta: { title: "站点设置", icon: SettingsIcon }
    },
    {
      path: "/replow/users",
      name: "ReplowUsers",
      component: () => import("@/views/replow/users/index.vue"),
      meta: { title: "用户管理", icon: UsersIcon }
    },
    {
      path: "/replow/profile",
      name: "ReplowProfile",
      component: () => import("@/views/replow/profile/index.vue"),
      meta: { title: "个人中心", icon: ProfileIcon }
    }
  ]
} satisfies RouteConfigsTable;

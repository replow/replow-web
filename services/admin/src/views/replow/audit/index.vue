<script setup lang="ts">
import { onMounted, ref } from "vue";
import { getAuditLogs, type AuditItem } from "@/api/replow";
import { localTime } from "@/utils/replow-time";
import { message } from "@/utils/message";
defineOptions({ name: "ReplowAudit" });
const rows = ref<AuditItem[]>([]),
  total = ref(0),
  page = ref(1),
  search = ref(""),
  outcome = ref(""),
  loading = ref(false);
const labels: Record<string, string> = {
  uid: "UID",
  username: "用户名",
  email: "邮箱",
  display_name: "显示名称",
  avatar_url: "头像",
  bio: "简介",
  website_url: "网站",
  role: "角色",
  status: "状态",
  password: "密码",
  enabled: "开放下载",
  paused: "暂停下载队列",
  user_queue_limit: "每用户排队上限",
  global_queue_limit: "全局排队上限",
  removed_files: "清理过期文件数"
};
const resources: Record<string, string> = {
  users: "用户",
  fq: "番茄小说",
  articles: "文章",
  albums: "相册",
  comments: "评论",
  friends: "友链",
  site: "站点",
  cdn: "CDN",
  storage: "存储",
  media: "媒体",
  account: "账号配置",
  "access-keys": "访问密钥"
};
async function load(reset = false) {
  if (reset) page.value = 1;
  loading.value = true;
  try {
    const r = await getAuditLogs({
      limit: 30,
      offset: (page.value - 1) * 30,
      search: search.value,
      outcome: outcome.value
    });
    rows.value = r.items;
    total.value = r.total;
  } catch {
    message("操作日志读取失败", { type: "error" });
  } finally {
    loading.value = false;
  }
}
onMounted(() => load());
</script>
<template>
  <div class="audit-page">
    <el-card shadow="never"
      ><template #header
        ><div class="audit-toolbar">
          <div>
            <strong>操作日志</strong
            ><small>记录后台写入、字段变化及执行结果</small>
          </div>
          <el-button :loading="loading" @click="load()">刷新日志</el-button>
        </div></template
      >
      <div class="filters">
        <el-input
          v-model="search"
          placeholder="搜索操作者、UID 或资源"
          clearable
          aria-label="搜索操作日志"
          @keyup.enter="load(true)"
        /><el-select
          v-model="outcome"
          aria-label="操作结果"
          @change="load(true)"
          ><el-option label="全部结果" value="" /><el-option
            label="成功"
            value="success" /><el-option
            label="失败"
            value="failed" /></el-select
        ><el-button type="primary" @click="load(true)">查询</el-button>
      </div>
      <p class="muted">
        密码、令牌和密钥不记录原值；时间为北京时间。展开一行查看变更。
      </p>
      <el-table v-loading="loading" :data="rows" row-key="id"
        ><el-table-column type="expand"
          ><template #default="{ row }"
            ><div class="changes">
              <p v-if="!row.changes.length">未修改字段或操作未执行。</p>
              <div v-for="(change, index) in row.changes" :key="index">
                <strong>{{ labels[change.field] || change.field }}</strong
                ><span
                  >{{ change.before || "—" }} → {{ change.after || "—" }}</span
                >
              </div>
            </div></template
          ></el-table-column
        ><el-table-column label="时间" min-width="170"
          ><template #default="{ row }">{{
            localTime(row.created_at)
          }}</template></el-table-column
        ><el-table-column label="操作者" min-width="160"
          ><template #default="{ row }"
            >{{ row.actor_name || "未登录"
            }}<small class="actor-uid"
              >UID {{ row.actor_uid || "—" }}</small
            ></template
          ></el-table-column
        ><el-table-column label="操作" min-width="150"
          ><template #default="{ row }"
            >{{ row.action }} · {{ resources[row.resource] || row.resource }}
            {{ row.target_id }}</template
          ></el-table-column
        ><el-table-column label="结果" width="90"
          ><template #default="{ row }"
            ><el-tag :type="row.status_code < 400 ? 'success' : 'danger'">{{
              row.status_code < 400 ? "成功" : "失败"
            }}</el-tag></template
          ></el-table-column
        ><el-table-column
          prop="ip_address"
          label="IP"
          min-width="140" /></el-table
      ><el-empty
        v-if="!loading && !rows.length"
        description="暂无操作记录" /><el-pagination
        v-model:current-page="page"
        :total="total"
        :page-size="30"
        layout="prev,pager,next"
        @current-change="load()"
    /></el-card>
  </div>
</template>
<style scoped>
.audit-toolbar,
.filters {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.audit-toolbar {
  justify-content: space-between;
}
.audit-toolbar > div {
  display: grid;
  gap: 5px;
}
.filters {
  margin-bottom: 12px;
}
.filters .el-input {
  max-width: 320px;
}
.filters .el-select {
  width: 140px;
}
.muted,
.actor-uid,
.audit-toolbar small {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.actor-uid {
  display: block;
  margin-top: 4px;
}
.changes {
  padding: 14px 24px;
  display: grid;
  gap: 10px;
}
.changes > div {
  display: grid;
  gap: 4px;
}
.changes span {
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.el-pagination {
  margin-top: 18px;
  justify-content: center;
}
@media (max-width: 600px) {
  .filters .el-input {
    max-width: none;
    flex-basis: 100%;
  }
}
</style>

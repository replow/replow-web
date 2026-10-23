<script setup lang="ts">
import { onMounted, ref } from "vue";
import { getFqOverview, fileSize, type FqOverview } from "@/api/fanqie";
import { message } from "@/utils/message";
import JobsTable from "./JobsTable.vue";
import ServiceSettings from "./ServiceSettings.vue";
import EventLogs from "./EventLogs.vue";
defineOptions({name:"ReplowFanqie"});
const overview=ref<FqOverview|null>(null),loading=ref(false),tab=ref("jobs"),revision=ref(0);
async function load(){
  loading.value=true;
  try{overview.value=(await getFqOverview()).data;}
  catch{message("番茄小说服务状态读取失败",{type:"error"});}
  finally{loading.value=false;}
}
function refresh(){revision.value++;void load();}
onMounted(load);
</script>
<template>
  <div class="fq-admin">
    <div class="fq-admin-heading">
      <div><h2>番茄小说管理</h2><p>管理下载队列、文件有效期与运行记录</p></div>
      <div class="heading-actions">
        <el-tag v-if="overview" :type="overview.worker_online?'success':'danger'">{{overview.worker_online?'下载进程在线':'下载进程暂无心跳'}}</el-tag>
        <el-button :loading="loading" @click="refresh">刷新</el-button>
        <el-button tag="a" href="https://www.preview.replow.org/fanqie/" target="_blank" rel="noopener noreferrer">打开下载器 ↗</el-button>
      </div>
    </div>
    <div v-if="overview" class="fq-metrics">
      <el-card shadow="never"><small>处理中 / 排队</small><strong>{{overview.counts.running||0}} <span>/ {{(overview.counts.queued||0)+(overview.counts.retry||0)}}</span></strong></el-card>
      <el-card shadow="never"><small>最近 24 小时任务</small><strong>{{overview.today_jobs}}</strong></el-card>
      <el-card shadow="never"><small>有效原文件</small><strong>{{overview.available_files}} <span>份</span></strong></el-card>
      <el-card shadow="never"><small>原文件占用</small><strong>{{fileSize(overview.cached_bytes)}}</strong></el-card>
    </div>
    <el-alert v-if="overview?.settings.paused" title="队列已暂停，新任务仍可排队；当前下载完成后不再领取下一个任务。" type="warning" :closable="false" show-icon />
    <el-alert v-if="overview && !overview.settings.enabled" title="下载入口已关闭，用户仍可查看历史并下载有效的原文件。" type="info" :closable="false" show-icon />
    <el-card shadow="never" class="fq-admin-panel">
      <el-tabs v-model="tab">
        <el-tab-pane label="下载任务" name="jobs"><JobsTable v-if="tab==='jobs'" :revision="revision" @changed="load" /></el-tab-pane>
        <el-tab-pane label="服务设置与缓存" name="settings"><ServiceSettings v-if="tab==='settings' && overview" :overview="overview" @changed="refresh" /></el-tab-pane>
        <el-tab-pane label="运行日志" name="logs"><EventLogs v-if="tab==='logs'" :revision="revision" /></el-tab-pane>
      </el-tabs>
    </el-card>
  </div>
</template>
<style scoped>
.fq-admin-heading{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;margin:5px 0 22px}
h2{font-size:22px;font-weight:650;margin:0 0 7px}.fq-admin-heading p{font-size:13px;color:var(--el-text-color-secondary);margin:0}
.heading-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.heading-actions .el-button+.el-button{margin-left:0}
.fq-metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:15px;margin-bottom:20px}
.fq-metrics small{display:block;color:var(--el-text-color-secondary);font-size:12px;margin-bottom:12px}
.fq-metrics strong{font-size:27px;font-weight:600;line-height:1.4}.fq-metrics strong span{font-size:15px;color:var(--el-text-color-secondary);font-weight:400}
.fq-admin-panel,.el-alert{margin-bottom:15px}@media(max-width:760px){.fq-metrics{grid-template-columns:1fr 1fr;gap:10px}.fq-metrics strong{font-size:22px}}
</style>

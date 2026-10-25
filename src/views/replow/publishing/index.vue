<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, computed } from "vue";
import { getSiteBuild, startSiteBuild, type SiteBuildStatus } from "@/api/replow";
import { message } from "@/utils/message";
defineOptions({name:"ReplowPublishing"});
const state=ref<SiteBuildStatus|null>(null), loading=ref(false), error=ref("");
let timer:ReturnType<typeof setTimeout>;
let disposed=false;
const running=computed(()=>['queued','building','deploying'].includes(state.value?.status || ''));
const labels:Record<string,string>={idle:'尚未构建',queued:'等待构建',building:'构建中',deploying:'部署验证中',success:'发布完成',failed:'发布失败'};
const label=computed(()=>labels[state.value?.status || 'idle'] || state.value?.status);
const steps:Record<string,number>={idle:0,queued:1,building:2,deploying:3,success:4,failed:2};
const step=computed(()=>steps[state.value?.status || 'idle'] || 0);
const date=(v?:string)=>v?new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(v)?v:v+'Z').toLocaleString('zh-CN'):'—';
async function refresh() {
  clearTimeout(timer);
  try { state.value=(await getSiteBuild()).data; error.value=''; }
  catch { error.value='发布状态读取失败，请稍后刷新'; }
  finally { if(!disposed) timer=setTimeout(refresh, running.value ? 4000 : 15000); }
}
async function publish() {
  loading.value=true;
  try { state.value=(await startSiteBuild()).data; await refresh(); message('已提交构建任务',{type:'success'}); }
  catch { message('构建任务提交失败',{type:'error'}); }
  finally { loading.value=false; }
}
onMounted(refresh);
onBeforeUnmount(()=>{disposed=true;clearTimeout(timer)});
</script>
<template>
  <el-card shadow="never">
    <template #header><div class="heading"><div><h2>内容发布</h2><p>查看内容保存、构建和实际部署进度</p></div><el-tag :type="state?.environment==='preview'?'warning':'info'">{{ state?.environment || '读取中' }}</el-tag></div></template>
    <el-alert v-if="error" :title="error" type="error" :closable="false"/>
    <el-alert v-if="state?.has_unpublished_changes" title="有已保存的内容尚未进入静态发布版本" type="warning" :closable="false" style="margin-bottom:24px"/>
    <el-steps :active="step" finish-status="success" align-center><el-step title="内容已保存"/><el-step title="排队"/><el-step title="构建"/><el-step title="部署完成"/></el-steps>
    <div class="status"><el-tag :type="state?.status==='failed'?'danger':state?.status==='success'?'success':'info'">{{ label }}</el-tag><span>{{ state?.stage }}</span></div>
    <el-alert v-if="state?.error" :title="state.error" type="error" :closable="false" style="margin-bottom:20px"/>
    <el-descriptions :column="1" border>
      <el-descriptions-item label="最新内容保存">{{ date(state?.content_saved_at) }}</el-descriptions-item>
      <el-descriptions-item label="最近成功上线">{{ date(state?.last_published_at) }}</el-descriptions-item>
      <el-descriptions-item label="线上版本">{{ state?.published_version || '—' }}</el-descriptions-item>
      <el-descriptions-item label="本次开始">{{ date(state?.started_at) }}</el-descriptions-item>
      <el-descriptions-item label="本次结束">{{ date(state?.finished_at) }}</el-descriptions-item>
      <el-descriptions-item label="提交">{{ state?.commit?.slice(0,12) || '—' }}</el-descriptions-item>
      <el-descriptions-item label="构建详情"><a v-if="state?.run_url" :href="state.run_url" target="_blank" rel="noopener noreferrer">查看 GitHub Actions</a><span v-else>—</span></el-descriptions-item>
    </el-descriptions>
    <div class="actions"><el-button type="primary" :loading="loading || running" @click="publish">{{ running?'正在发布…':state?.status==='failed'?'重试发布':'构建并发布' }}</el-button><el-button @click="refresh">刷新状态</el-button><el-button v-if="state?.site_url" tag="a" :href="state.site_url" target="_blank">查看站点</el-button></div>
  </el-card>
</template>
<style scoped>
.heading,.status,.actions {display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.heading {justify-content:space-between}.heading h2{margin:0;font-size:20px}.heading p{margin:6px 0 0;color:var(--el-text-color-secondary)}
.status{margin:24px 0}.actions{margin-top:24px}a{color:var(--el-color-primary)}
</style>

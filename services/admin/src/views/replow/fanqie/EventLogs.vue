<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { getFqLogs, eventLabels, detailLabels, settingLabels, fqTime, type FqEvent } from "@/api/fanqie";
import { message } from "@/utils/message";
const props=defineProps<{revision:number}>();
const rows=ref<FqEvent[]>([]),total=ref(0),page=ref(1),search=ref(""),event=ref(""),loading=ref(false);
async function load(reset=false){
  if(reset)page.value=1;
  loading.value=true;
  try{const result=await getFqLogs({page:page.value,size:30,search:search.value,event:event.value});rows.value=result.items;total.value=result.total;}
  catch{message("运行日志读取失败",{type:"error"});}
  finally{loading.value=false;}
}
function detail(value:FqEvent["details"][string]){
  if(Array.isArray(value))return value.map(v=>settingLabels[v]||v).join("、");
  if(typeof value==="boolean")return value?"是":"否";
  return value===null?"—":String(value);
}
watch(()=>props.revision,()=>void load());
onMounted(()=>void load());
</script>
<template>
  <div class="fq-log-filters">
    <el-input v-model="search" clearable placeholder="搜索任务 ID、书籍 ID、UID 或书名" aria-label="筛选运行日志" @keyup.enter="load(true)" />
    <el-select v-model="event" aria-label="事件类型" @change="load(true)"><el-option label="全部事件" value="" /><el-option v-for="(label,key) in eventLabels" :key="key" :label="label" :value="key" /></el-select>
    <el-button type="primary" @click="load(true)">查询</el-button><el-button :loading="loading" @click="load()">刷新日志</el-button>
  </div>
  <p class="fq-log-note">保留最近 90 天的下载、复用、更新检查及队列事件；不记录密码、签名密钥、令牌或小说正文。管理员写入另同步到“操作日志”。时间为北京时间。</p>
  <el-table v-loading="loading" :data="rows" row-key="id">
    <el-table-column type="expand"><template #default="{row}"><div class="fq-event-detail"><p v-if="row.job_id"><b>任务 ID</b> {{row.job_id}}</p><p v-if="row.book_id"><b>书籍 ID</b> {{row.book_id}}<span v-if="row.job_user_id"> · 所属用户 UID {{row.job_user_id}}</span></p><p v-for="(value,key) in row.details" :key="key"><b>{{detailLabels[key]||key}}</b> {{detail(value)}}</p></div></template></el-table-column>
    <el-table-column label="时间" min-width="175"><template #default="{row}">{{fqTime(row.created_at)}}</template></el-table-column>
    <el-table-column label="事件" min-width="155"><template #default="{row}"><el-tag :type="row.event==='failed'?'danger':row.event==='completed'?'success':'info'">{{eventLabels[row.event]||row.event}}</el-tag></template></el-table-column>
    <el-table-column label="操作者" min-width="120"><template #default="{row}">{{row.user_id?'UID '+row.user_id:'系统'}}</template></el-table-column>
    <el-table-column label="书籍 / 资源" min-width="220"><template #default="{row}"><span>{{row.title||row.book_id||'下载服务'}}</span><small v-if="row.book_id">{{row.book_id}}</small></template></el-table-column>
  </el-table>
  <el-pagination v-model:current-page="page" :total="total" :page-size="30" layout="total,prev,pager,next" @current-change="load()" />
</template>
<style scoped>
.fq-log-filters{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin:10px 0}.fq-log-filters .el-input{width:300px}.fq-log-filters .el-select{width:165px}.fq-log-note,small{font-size:12px;line-height:1.9;color:var(--el-text-color-secondary)}.fq-log-note{margin:14px 0 20px}small{display:block}.fq-event-detail{padding:14px 25px;font-size:12px;line-height:1.9;overflow-wrap:anywhere}.fq-event-detail b{display:inline-block;min-width:90px;font-weight:500;color:var(--el-text-color-secondary)}.el-pagination{justify-content:center;margin-top:22px}@media(max-width:600px){.fq-log-filters .el-input{width:100%}.el-pagination{justify-content:flex-start;overflow:auto}}
</style>

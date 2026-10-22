<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from "vue";
import { ElMessageBox } from "element-plus";
import { getFqJobs, manageFqJob, deleteFqJob, fqTime, fileSize, stateLabels, type FqJob } from "@/api/fanqie";
import { message } from "@/utils/message";
const props=defineProps<{revision:number}>();
const emit=defineEmits<{changed:[]}>();
const rows=ref<FqJob[]>([]),total=ref(0),page=ref(1),search=ref(""),state=ref(""),format=ref(""),loading=ref(false),working=ref(""),auto=ref(true);
let timer:ReturnType<typeof setTimeout>|undefined;
let alive=true;
async function load(reset=false){
  if(loading.value)return;
  if(reset)page.value=1;
  loading.value=true;clearTimeout(timer);
  try{
    const result=await getFqJobs({page:page.value,size:25,search:search.value,state:state.value,format:format.value});
    if(alive){rows.value=result.items;total.value=result.total;}
  }catch{if(alive)message("下载任务读取失败",{type:"error"});}
  finally{loading.value=false;if(alive&&auto.value)timer=setTimeout(()=>void load(),10000);}
}
async function act(row:FqJob,action:"retry"|"cancel"){
  try{await ElMessageBox.confirm(action==="cancel"?"取消这个尚未开始的任务？已保存的章节进度会保留。":"按原书籍、范围和格式重新排队，保留已验证的章节缓存。",action==="cancel"?"取消任务":"重试任务",{type:"warning",confirmButtonText:action==="cancel"?"取消任务":"重新排队",cancelButtonText:"返回"});}catch{return;}
  working.value=row.job_id;
  try{await manageFqJob(row.job_id,action);message(action==="cancel"?"任务已取消":"任务已重新排队",{type:"success"});await load();emit("changed");}
  catch{message("任务状态可能已变化，请刷新后重试。",{type:"error"});}
  finally{working.value="";}
}
async function remove(row:FqJob){
  try{
    await ElMessageBox.confirm(
      `确定删除《${row.title||row.book_id}》这条下载记录及对应原文件？此操作不可撤销。若其他记录复用了同一文件，其下载链接也会失效，需重新下载。`,
      "删除记录及文件",
      {type:"warning",confirmButtonText:"删除记录及文件",cancelButtonText:"返回",closeOnClickModal:false}
    );
  }catch{return;}
  working.value=row.job_id;
  try{
    const result=await deleteFqJob(row.job_id);
    message(`记录已删除，已移除 ${result.data.removed_files} 个原文件${result.data.affected_records ? `，${result.data.affected_records} 条关联记录需重新下载` : ""}`,{type:"success"});
    if(rows.value.length===1&&page.value>1)page.value--;
    await load();emit("changed");
  }catch(error:any){
    const detail=error?.response?.data?.detail;
    message(detail==="book_has_running_job"?"该书籍正在下载，请完成后再删除。":detail==="file_cache_purge_failed"?"CDN 缓存清理失败，文件和记录已保留，请稍后重试。":"删除失败，文件和记录已保留，请刷新后重试。",{type:"error"});
  }finally{working.value="";}
}
watch(()=>props.revision,()=>void load());
watch(auto,()=>{clearTimeout(timer);if(auto.value)void load();});
onMounted(()=>void load());
onBeforeUnmount(()=>{alive=false;clearTimeout(timer);});
</script>
<template>
  <div class="fq-job-filters">
    <el-input v-model="search" clearable placeholder="书名、作者、书籍 ID、UID 或任务 ID" aria-label="筛选下载任务" @keyup.enter="load(true)" />
    <el-select v-model="state" aria-label="任务状态" @change="load(true)"><el-option label="全部状态" value="" /><el-option v-for="(label,key) in stateLabels" :key="key" :label="label" :value="key" /></el-select>
    <el-select v-model="format" aria-label="文件格式" @change="load(true)"><el-option label="全部格式" value="" /><el-option label="TXT" value="txt" /><el-option label="EPUB" value="epub" /></el-select>
    <el-button type="primary" @click="load(true)">查询</el-button><el-switch v-model="auto" active-text="自动刷新" />
  </div>
  <p class="fq-note">一次处理一本书；有效原文件直接复用。可取消待处理任务、重试失败或已取消任务，可删除记录及对应原文件；共享该文件的其他记录将需要重新下载。正在下载的书籍须完成后才能删除。</p>
  <el-table v-loading="loading" :data="rows" row-key="job_id" style="width:100%">
    <el-table-column type="expand"><template #default="{row}"><div class="fq-job-detail">
      <p><b>任务 ID</b> {{row.job_id}}</p><p><b>书籍 ID</b> {{row.book_id}} · 用户 UID {{row.user_id}}</p>
      <p><b>创建时间</b> {{fqTime(row.created_at)}} · 尝试 {{row.attempts}} 次</p>
      <p><b>章节缓存</b> 复用 {{row.reused_chapters}} 项 · 新下载 {{row.added_chapters}} 项</p>
      <p v-if="row.error" class="error"><b>执行原因</b> {{row.error}}</p>
    </div></template></el-table-column>
    <el-table-column label="书籍 / 用户" min-width="250"><template #default="{row}"><div class="fq-admin-book"><el-image :src="row.cover_url" fit="cover" loading="lazy"><template #error><span class="cover-placeholder">书</span></template></el-image><div><strong>{{row.title||'书籍 '+row.book_id}}</strong><small>{{row.author||'作者信息待获取'}}</small><small>UID {{row.user_id}}</small></div></div></template></el-table-column>
    <el-table-column label="范围 / 格式" min-width="140"><template #default="{row}"><span>{{row.format.toUpperCase()}}</span><small class="block">目录 {{row.start_chapter}}—{{row.end_chapter||'最新'}}</small></template></el-table-column>
    <el-table-column label="状态 / 进度" min-width="160"><template #default="{row}"><el-tag :type="row.status==='completed'?'success':row.status==='failed'?'danger':row.status==='cancelled'?'info':'warning'">{{stateLabels[row.status]}}</el-tag><el-progress v-if="row.status==='running'" :percentage="Math.round(row.progress*100)" :stroke-width="5" /><small class="block">{{row.completed_chapters}}/{{row.total_chapters||'—'}} 项<span v-if="row.queue_position"> · 排位 {{row.queue_position}}</span></small></template></el-table-column>
    <el-table-column label="原文件有效期" min-width="185"><template #default="{row}"><span v-if="row.file_available">{{fqTime(row.expires_at)}}</span><span v-else>{{row.status==='completed'?'已过期或不可用':'—'}}</span><small v-if="row.size_bytes" class="block">{{fileSize(row.size_bytes)}}</small></template></el-table-column>
    <el-table-column label="操作" min-width="185" fixed="right"><template #default="{row}">
      <el-link v-if="row.file_available && row.download_url" :href="row.download_url" target="_blank" rel="noopener noreferrer" type="primary">下载原文件 ↗</el-link>
      <el-button v-if="['queued','retry'].includes(row.status)" text type="warning" :loading="working===row.job_id" @click="act(row,'cancel')">取消任务</el-button>
      <el-button v-if="['failed','cancelled'].includes(row.status)" text type="primary" :loading="working===row.job_id" @click="act(row,'retry')">重新排队</el-button>
      <el-button text type="danger" :disabled="row.status==='running'||!!working" :loading="working===row.job_id" @click="remove(row)">删除记录及文件</el-button>
    </template></el-table-column>
  </el-table>
  <el-pagination v-model:current-page="page" :total="total" :page-size="25" layout="total,prev,pager,next" @current-change="load()" />
</template>
<style scoped>
.fq-job-filters{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:10px 0}.fq-job-filters .el-input{width:300px}.fq-job-filters .el-select{width:135px}.fq-job-filters .el-switch{margin-left:auto}
.fq-note,.block,.fq-admin-book small{font-size:12px;color:var(--el-text-color-secondary)}.fq-note{line-height:1.8;margin:14px 0 18px}.block{display:block;margin-top:7px}
.fq-admin-book{display:flex;align-items:center;gap:12px;padding:6px 0}.fq-admin-book .el-image{width:44px;height:60px;border-radius:5px;flex:none;background:var(--el-fill-color-light)}.cover-placeholder{display:grid;place-items:center;height:100%;color:var(--el-text-color-placeholder)}.fq-admin-book strong{font-size:13px;font-weight:600;line-height:1.5}.fq-admin-book small{display:block;margin-top:3px}
.fq-job-detail{padding:10px 25px;font-size:12px;line-height:1.9;overflow-wrap:anywhere}.fq-job-detail p{margin:4px 0}.fq-job-detail b{font-weight:500;margin-right:12px;color:var(--el-text-color-secondary)}.error{color:var(--el-color-danger)}.el-pagination{justify-content:center;margin-top:22px}
@media(max-width:600px){.fq-job-filters .el-input{width:100%}.fq-job-filters .el-select{width:115px}.fq-job-filters .el-switch{margin-left:0}.el-pagination{justify-content:flex-start;overflow:auto}}
</style>

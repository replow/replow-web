<script setup lang="ts">
import { reactive, ref, watch } from "vue";
import { ElMessageBox } from "element-plus";
import { saveFqSettings, cleanFqExpired, fqTime, fileSize, type FqOverview } from "@/api/fanqie";
import { message } from "@/utils/message";
const props=defineProps<{overview:FqOverview}>();
const emit=defineEmits<{changed:[]}>();
const form=reactive({enabled:true,paused:false,user_queue_limit:3,global_queue_limit:100});
const saving=ref(false),cleaning=ref(false);
watch(()=>props.overview.settings,(value)=>Object.assign(form,{enabled:value.enabled,paused:value.paused,user_queue_limit:value.user_queue_limit,global_queue_limit:value.global_queue_limit}),{immediate:true});
async function save(){
  saving.value=true;
  try{await saveFqSettings({...form});message("服务设置已生效",{type:"success"});emit("changed");}
  catch{message("保存失败，请检查排队上限后重试。",{type:"error"});}
  finally{saving.value=false;}
}
async function cleanup(){
  try{await ElMessageBox.confirm("仅清理保留期已满的文件与缓存，历史下载记录保留。有效的原文件和正在下载的章节不会删除。","清理过期缓存",{confirmButtonText:"清理过期文件",cancelButtonText:"返回",type:"warning"});}catch{return;}
  cleaning.value=true;
  try{const result=await cleanFqExpired();message(`已清理 ${result.data.removed_files} 份到期原文件`,{type:"success"});emit("changed");}
  catch{message("清理失败，请稍后重试。",{type:"error"});}
  finally{cleaning.value=false;}
}
</script>
<template>
  <div class="fq-settings-grid">
    <section>
      <h3>下载服务</h3><p class="muted">保存后立即生效，已创建的任务与历史记录会保留。</p>
      <el-form label-position="top" class="fq-settings-form" @submit.prevent="save">
        <el-form-item label="开放下载入口"><el-switch v-model="form.enabled" active-text="开放" inactive-text="维护" /></el-form-item>
        <p class="field-help">维护时停止创建新下载；已有的有效原文件仍可下载。</p>
        <el-form-item label="暂停领取新任务"><el-switch v-model="form.paused" active-text="暂停" inactive-text="正常运行" /></el-form-item>
        <p class="field-help">暂停后仍可排队，正在下载的任务会完成；恢复后继续按顺序处理。</p>
        <div class="limit-fields">
          <el-form-item label="每用户待完成任务上限"><el-input-number v-model="form.user_queue_limit" :min="1" :max="20" :precision="0" /></el-form-item>
          <el-form-item label="全局待完成任务上限"><el-input-number v-model="form.global_queue_limit" :min="1" :max="1000" :precision="0" /></el-form-item>
        </div>
        <p class="field-help">上限包含排队、下载中和等待重试的任务。降低上限不取消已有任务。</p>
        <el-button native-type="submit" type="primary" :loading="saving">保存设置</el-button>
      </el-form>
    </section>
    <section class="fq-cache-panel">
      <h3>原文件与缓存</h3><p class="muted">固定保留策略，自动清理到期文件。</p>
      <dl>
        <div><dt>本地原文件有效期</dt><dd>{{overview.settings.retention_days}} 天</dd></div>
        <div><dt>CDN 缓存 TTL</dt><dd>{{overview.settings.cdn_ttl_days}} 天</dd></div>
        <div><dt>运行日志保留期</dt><dd>{{overview.settings.log_retention_days}} 天</dd></div>
        <div><dt>有效原文件</dt><dd>{{overview.available_files}} 份 · {{fileSize(overview.cached_bytes)}}</dd></div>
        <div><dt>磁盘可用空间</dt><dd>{{fileSize(overview.disk_free_bytes)}}</dd></div>
        <div><dt>最近清理</dt><dd>{{fqTime(overview.last_cleanup_at)}}</dd></div>
        <div><dt>下载进程活动</dt><dd>{{fqTime(overview.heartbeat_at)}}</dd></div>
      </dl>
      <p class="field-help">后台每小时检查一次到期文件。复用原文件不会延长有效期；更新生成不同文件，历史记录保留。</p>
      <el-button :loading="cleaning" @click="cleanup">清理过期文件</el-button>
      <p class="fq-download-base">下载域名 {{overview.settings.download_base}}</p>
    </section>
  </div>
</template>
<style scoped>
.fq-settings-grid{display:grid;grid-template-columns:1fr 1fr;gap:50px;padding:12px 5px 20px}.fq-settings-grid h3{font-size:16px;font-weight:600;margin:6px 0 10px}.muted,.field-help,.fq-download-base{color:var(--el-text-color-secondary);font-size:12px;line-height:1.85}.muted{margin-bottom:25px}.field-help{margin:-8px 0 23px;max-width:460px}.fq-settings-form .el-form-item{margin-bottom:18px}.limit-fields{display:flex;gap:22px;flex-wrap:wrap}.fq-cache-panel{padding-left:28px;border-left:1px solid var(--el-border-color-lighter)}dl{margin-bottom:30px}dl>div{display:flex;justify-content:space-between;gap:20px;padding:11px 0;border-bottom:1px solid var(--el-border-color-extra-light);font-size:12px}dt{color:var(--el-text-color-secondary)}dd{margin:0;text-align:right}.fq-download-base{margin-top:20px;overflow-wrap:anywhere}@media(max-width:1000px){.fq-settings-grid{grid-template-columns:1fr;gap:35px}.fq-cache-panel{border-left:0;border-top:1px solid var(--el-border-color-lighter);padding:24px 0 0}}
</style>

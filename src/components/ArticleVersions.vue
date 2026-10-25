<script setup lang="ts">
import { ref, watch } from "vue";
import { ElMessageBox } from "element-plus";
import { http } from "@/utils/http";
import { message } from "@/utils/message";
import { contentError } from "@/api/contentTools";
const props = defineProps<{ articleId: number; current: Record<string,unknown>; token: string }>();
const emit = defineEmits<{ restored: [article: Record<string,unknown>] }>();
const open = ref(false), busy = ref(false);
const versions = ref<{id:number; title:string; actor_name:string; reason:string; created_at:string}[]>([]);
const chosen = ref<{id:number; snapshot:Record<string,unknown>}|null>(null);
async function load() {
  busy.value = true; chosen.value = null;
  try { versions.value = (await http.request<{items:typeof versions.value}>("get", `/admin/articles/${props.articleId}/versions`)).items; }
  catch { message("历史版本读取失败", {type:"error"}); }
  finally { busy.value = false; }
}
async function select(id:number) {
  busy.value = true;
  try { chosen.value = (await http.request<{data:typeof chosen.value}>("get", `/admin/articles/${props.articleId}/versions/${id}`)).data; }
  catch { message("版本详情读取失败", {type:"error"}); }
  finally { busy.value = false; }
}
async function restore() {
  if (!chosen.value) return;
  try {
    await ElMessageBox.confirm("恢复会保存当前线上内容的历史版本，并替换文章内容；当前未保存的编辑请先保存。发布状态保持不变。", "恢复历史版本", {type:"warning"});
    busy.value = true;
    const result = await http.request<{data:Record<string,unknown>}>("post", `/admin/articles/${props.articleId}/versions/${chosen.value.id}/restore`, {data:{_base_token:props.token}});
    emit("restored", result.data); open.value = false; message("历史版本已恢复", {type:"success"});
  } catch(error) { if(error !== "cancel" && error !== "close") message(contentError(error,"恢复失败"), {type:"error"}); }
  finally { busy.value = false; }
}
watch(open, value => { if(value) void load(); });
</script>
<template>
  <el-button @click="open=true">历史版本</el-button>
  <el-dialog v-model="open" title="文章历史版本 · 最近 50 个" width="min(1100px,96vw)" append-to-body>
    <div v-loading="busy">
      <el-empty v-if="!versions.length" description="首次保存后开始记录历史版本" />
      <div class="versions">
        <el-button v-for="item in versions" :key="item.id" :type="chosen?.id===item.id?'primary':'default'" @click="select(item.id)">
          #{{ item.id }} · {{ item.created_at.replace('T',' ') }} · {{ item.actor_name || '系统' }} · {{ item.reason==='restore'?'恢复':item.reason==='before_save'?'修改前':'保存' }}
        </el-button>
      </div>
      <div v-if="chosen" class="compare">
        <section><h3>当前编辑内容</h3><strong>{{ current.title }}</strong><pre>{{ current.body_markdown }}</pre></section>
        <section><h3>所选历史版本</h3><strong>{{ chosen.snapshot.title }}</strong><pre>{{ chosen.snapshot.body_markdown }}</pre></section>
      </div>
    </div>
    <template #footer><el-button @click="open=false">关闭</el-button><el-button type="primary" :disabled="!chosen" :loading="busy" @click="restore">恢复此版本</el-button></template>
  </el-dialog>
</template>
<style scoped>
.versions { display:flex; flex-wrap:wrap; gap:8px; max-height:180px; overflow:auto; margin-bottom:18px; }
.versions .el-button { margin:0; }
.compare { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
.compare section { min-width:0; padding:14px; background:var(--el-fill-color-light); border-radius:10px; }
pre { white-space:pre-wrap; overflow-wrap:anywhere; max-height:45vh; overflow:auto; font:13px/1.7 monospace; }
@media(max-width:700px) { .compare { grid-template-columns:1fr; } }
</style>

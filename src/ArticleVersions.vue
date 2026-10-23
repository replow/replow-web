<script setup lang="ts">
import { ref } from "vue";
import { request, humanError, type Article } from "./api";
const props = defineProps<{articleId:number; current:Record<string,unknown>; token:string}>();
const emit = defineEmits<{restored:[article:Article]}>();
const open=ref(false), busy=ref(false), error=ref("");
const versions=ref<{id:number;title:string;created_at:string}[]>([]);
const chosen=ref<{id:number;snapshot:Record<string,unknown>}|null>(null);
async function load() {
  open.value=!open.value;
  if(!open.value) return;
  busy.value=true; chosen.value=null; error.value="";
  try { versions.value=(await request<{items:typeof versions.value}>(`/account/articles/${props.articleId}/versions`)).items; }
  catch(err) { error.value=humanError(err); } finally { busy.value=false; }
}
async function select(id:number) {
  busy.value=true;
  try { chosen.value=(await request<{data:typeof chosen.value}>(`/account/articles/${props.articleId}/versions/${id}`)).data; }
  catch(err) { error.value=humanError(err); } finally { busy.value=false; }
}
async function restore() {
  if(!chosen.value || !window.confirm("恢复会替换文章内容并保留当前内容的历史版本，发布状态不变。未保存的编辑请先保存。继续？")) return;
  busy.value=true;
  try {
    const r=await request<{data:Article}>(`/account/articles/${props.articleId}/versions/${chosen.value.id}/restore`, {method:"POST",body:JSON.stringify({_base_token:props.token})});
    emit("restored",r.data); open.value=false;
  } catch(err) { error.value=humanError(err); } finally { busy.value=false; }
}
</script>
<template>
  <div class="history-block">
    <button class="btn btn-soft" :disabled="busy" @click="load">{{ open?'收起历史版本':'历史版本' }}</button>
    <div v-if="open">
      <p v-if="error" role="alert">{{ error }}</p>
      <p v-if="!versions.length && !busy">首次保存后开始记录历史版本，最多保留 50 个。</p>
      <div class="version-list"><button v-for="item in versions" :key="item.id" class="btn btn-soft" :disabled="busy" @click="select(item.id)">#{{ item.id }} · {{ item.created_at.replace('T',' ') }}</button></div>
      <div v-if="chosen" class="version-compare">
        <section><h3>当前编辑内容</h3><strong>{{ current.title }}</strong><pre>{{ current.body_markdown }}</pre></section>
        <section><h3>所选历史版本</h3><strong>{{ chosen.snapshot.title }}</strong><pre>{{ chosen.snapshot.body_markdown }}</pre></section>
      </div>
      <button v-if="chosen" class="btn btn-primary" :disabled="busy" @click="restore">恢复此版本</button>
    </div>
  </div>
</template>
<style scoped>
.history-block { margin:10px 0 18px; }
.version-list { display:flex;flex-wrap:wrap;gap:8px;max-height:160px;overflow:auto;margin:12px 0; }
.version-compare { display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px; }
.version-compare section { min-width:0;padding:12px;border:1px solid var(--border,#ddd);border-radius:12px; }
pre { font:13px/1.7 monospace;white-space:pre-wrap;overflow-wrap:anywhere;max-height:300px;overflow:auto; }
@media(max-width:700px){.version-compare{grid-template-columns:1fr}}
</style>

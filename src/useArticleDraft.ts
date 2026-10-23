import { onBeforeUnmount, ref, watch, type Ref } from "vue";
import { request, humanError } from "./api";
const http = { request: <T>(method:string, path:string, options?:{data:unknown}) => request<T>(path, {method:method.toUpperCase(), ...(options ? {body:JSON.stringify(options.data)} : {})}) };
const contentError = (error: unknown, fallback: string) => humanError(error) || fallback;

/** Private autosave, with a synchronous local backup and serialized cloud writes. */
export function useArticleDraft<T extends object>(form: T, open: Ref<boolean>, articleId: Ref<number|null>,
  identity: () => string, recover: (data: T) => Promise<boolean>) {
  const status = ref("");
  let version = 0, ready = false, timer: ReturnType<typeof setTimeout>;
  let key = "", storageKey = "", generation = 0, active: Promise<void> = Promise.resolve();
  let paused = false;
  const local = () => {
    if (!ready || !open.value) return;
    try { localStorage.setItem(storageKey, JSON.stringify({payload: form, time: Date.now()})); }
    catch { status.value = "本机空间不足，正在尝试云端保存"; }
  };
  const cloud = () => {
    const token = generation, draftKey = key;
    const body = JSON.parse(JSON.stringify(form));
    const id = articleId.value;
    active = active.then(async () => {
      if (token !== generation || paused || !ready) return;
      status.value = "正在自动保存…";
      try {
        const result = await http.request<{data:{version:number}}>("put", `/account/article-drafts/${draftKey}`,
          {data: {version, article_id: id, payload: body}});
        if (token !== generation) return;
        version = result.data.version;
        status.value = `已自动保存 ${new Date().toLocaleTimeString("zh-CN")}`;
      } catch (error) {
        if (token !== generation) return;
        const code = (error as {status?:number})?.status;
        if (code === 409) paused = true;
        status.value = contentError(error, "云端保存失败，已保存在本机，继续编辑可重试");
      }
    });
    return active;
  };
  async function begin() {
    ready = false; paused = false; clearTimeout(timer); generation++;
    key = articleId.value ? `article-${articleId.value}` : "new";
    storageKey = `article-autosave:${identity()}:${key}`;
    const token = generation;
    version = 0;
    status.value = "正在检查可恢复草稿…";
    let candidate: {payload:T; time:number}|null = null;
    try { candidate = JSON.parse(localStorage.getItem(storageKey) || "null"); } catch { /* Invalid old backup. */ }
    try {
      const result = await http.request<{data: {payload:T; version:number; updated_at:string}|null}>("get", `/account/article-drafts/${key}`);
      if (token !== generation) return;
      if (result.data) {
        version = result.data.version;
        const time = new Date(result.data.updated_at + (/(?:Z|[+-]\d{2}:\d{2})$/.test(result.data.updated_at) ? "" : "Z")).getTime();
        if (!candidate || time > candidate.time) candidate = {payload:result.data.payload, time};
      }
      status.value = "修改会自动保存，不会自动发布";
    } catch { paused = true; status.value = "云端草稿暂不可用，当前修改会保存在本机；重新打开后重试"; }
    if (token !== generation) return;
    if (candidate && JSON.stringify(candidate.payload) !== JSON.stringify(form)) {
      if (await recover(candidate.payload)) Object.assign(form, candidate.payload);
    }
    if (token === generation) ready = true;
  }
  async function clear() {
    local(); clearTimeout(timer);
    await active;
    ready = false; generation++;
    try { await http.request("delete", `/account/article-drafts/${key}`); localStorage.removeItem(storageKey); }
    catch { status.value = "文章已保存，旧自动草稿稍后可清理"; }
  }
  watch(form, () => {
    if (!ready || !open.value) return;
    local(); status.value = "已保存到本机，等待云端同步…";
    clearTimeout(timer); timer = setTimeout(cloud, 1800);
  }, {deep:true, flush:"sync"});
  watch(open, visible => { if (!visible) {local(); clearTimeout(timer); if (ready) void cloud();} });
  function leave() { local(); }
  window.addEventListener("pagehide", leave);
  onBeforeUnmount(() => { local(); clearTimeout(timer); window.removeEventListener("pagehide", leave); });
  return {status, begin, clear};
}

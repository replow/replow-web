import { http } from "@/utils/http";

export type ReferenceList = { total: number; items: { type: string; title: string; id: string }[] };
export const mediaReferences = (id: number) => http.request<{data: ReferenceList}>("get", `/admin/media/${id}/references`);
export const restoreMedia = (id: number) => http.request("post", `/admin/media/${id}/restore`);
export const purgeMedia = (id: number) => http.request("delete", `/admin/media/${id}/purge`);

export function contentError(error: unknown, fallback: string) {
  const detail = (error as {response?: {data?: {detail?: string}}})?.response?.data?.detail;
  return ({media_in_use: "文件仍被引用，请先解除引用", media_must_be_trashed_first: "请先移入回收站",
    article_changed_reload: "文章已在其他页面修改，请重新打开后再保存",
    draft_changed_reload: "草稿已在其他页面修改，请重新打开，当前内容仍保存在本机",
    too_many_drafts: "自动保存草稿已达上限，请整理旧草稿", draft_too_large: "草稿超过 1 MB，已保存在本机"} as Record<string,string>)[detail || ""] || fallback;
}

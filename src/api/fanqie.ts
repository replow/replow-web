import { http } from "@/utils/http";

export type FqSettings = {
  enabled: boolean;
  paused: boolean;
  user_queue_limit: number;
  global_queue_limit: number;
  retention_days: number;
  cdn_ttl_days: number;
  log_retention_days: number;
  download_base: string;
  serial_downloads: boolean;
};
export type FqState = "queued" | "running" | "retry" | "completed" | "failed" | "cancelled";
export type FqJob = {
  job_id: string;
  user_id: number;
  book_id: string;
  title: string;
  author: string;
  cover_url: string;
  format: string;
  status: FqState;
  start_chapter: number;
  end_chapter: number | null;
  total_chapters: number;
  completed_chapters: number;
  progress: number;
  queue_position: number;
  file_available: boolean;
  download_url: string | null;
  size_bytes: number | null;
  expires_at: number | null;
  created_at: number;
  attempts: number;
  error: string | null;
  added_chapters: number;
  reused_chapters: number;
};
export type FqOverview = {
  counts: Partial<Record<FqState, number>>;
  today_jobs: number;
  available_files: number;
  cached_bytes: number;
  disk_free_bytes: number;
  worker_online: boolean;
  heartbeat_at: number | null;
  last_cleanup_at: number | null;
  settings: FqSettings;
};
export type FqEvent = {
  id: number;
  event: string;
  job_id: string | null;
  user_id: number | null;
  job_user_id: number | null;
  book_id: string | null;
  title: string | null;
  details: Record<string, string | number | boolean | string[] | null>;
  created_at: number;
};
export const stateLabels: Record<FqState, string> = {
  queued: "排队中", running: "下载中", retry: "等待重试", completed: "已完成", failed: "失败", cancelled: "已取消"
};
export const eventLabels: Record<string, string> = {
  recovered: "重启后恢复排队", queued: "任务入队", started: "开始下载", completed: "下载完成", retry: "等待重试",
  failed: "下载失败", cancelled: "管理员取消", admin_retry: "管理员重试",
  original_reused: "复用原文件", updates_checked: "检查更新", settings_updated: "调整服务设置",
  cleanup: "自动清理到期文件", admin_cleanup: "管理员清理到期文件", admin_deleted: "管理员删除记录及文件"
};
export const detailLabels: Record<string, string> = {
  reason: "原因", added_chapters: "新下载章节", reused_chapters: "复用章节", total_chapters: "目录条目",
  removed_files: "清理文件数", affected_records: "关联记录失效数", new_chapters: "新增章节", has_updates: "发现更新", changed_fields: "修改项", source_job_id: "原任务"
};
export const settingLabels: Record<string, string> = {
  enabled: "开放下载", paused: "暂停队列", user_queue_limit: "每用户排队上限", global_queue_limit: "全局排队上限"
};
export function fqTime(value: number | null) {
  return value ? new Date(value * 1000).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai", hour12: false }) : "—";
}
export function fileSize(value: number | null) {
  if (!value) return "0 B";
  const unit = value > 1024 ** 3 ? 3 : value > 1024 ** 2 ? 2 : value > 1024 ? 1 : 0;
  return (value / 1024 ** unit).toFixed(unit ? 1 : 0) + " " + ["B", "KB", "MB", "GB"][unit];
}
export const getFqOverview = () => http.request<{data:FqOverview}>("get", "/admin/fq/overview");
export const getFqJobs = (params: {page:number;size:number;search:string;state:string;format:string}) =>
  http.request<{items:FqJob[];total:number}>("get", "/admin/fq/jobs", {params});
export const manageFqJob = (id:string, action:"retry"|"cancel") =>
  http.request<{success:boolean;data:FqJob}>("post", `/admin/fq/jobs/${id}/${action}`);
export const saveFqSettings = (data:Pick<FqSettings,"enabled"|"paused"|"user_queue_limit"|"global_queue_limit">) =>
  http.request<{data:FqSettings}>("put", "/admin/fq/settings", {data});
export const cleanFqExpired = () => http.request<{data:{removed_files:number}}>("post", "/admin/fq/cleanup");
export const getFqLogs = (params:{page:number;size:number;search:string;event:string}) =>
  http.request<{items:FqEvent[];total:number}>("get", "/admin/fq/logs", {params});

export const deleteFqJob = (id:string) =>
  http.request<{success:boolean;data:{removed_files:number;affected_records:number}}>("delete", `/admin/fq/jobs/${encodeURIComponent(id)}`, {timeout:60000});

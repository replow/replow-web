import { http } from "@/utils/http";
import Axios from "axios";
import { quickXorHash } from "@/utils/quickxor";

export type DashboardResponse = {
  counts: {
    articles: number;
    published_articles: number;
    comments: number;
    users: number;
    friends: number;
    media: number;
  };
  recent_articles: Array<{
    id: number;
    title: string;
    slug: string;
    status: string;
    author: string;
    updated_at: string;
  }>;
};

export type ArticleItem = {
  revision_token?: string;
  id: number;
  title: string;
  slug: string;
  excerpt: string;
  body_markdown: string;
  cover_url: string;
  icon_url: string;
  category: string;
  tags: string[];
  status: string;
  is_pinned: boolean;
  published_at: string;
  updated_at: string;
};

export type ArticlePayload = {
  _base_token?: string;
  title: string;
  slug: string;
  excerpt?: string;
  body_markdown: string;
  cover_url?: string;
  icon_url?: string;
  category?: string;
  tags?: string[];
  status: "draft" | "pending" | "published" | "rejected";
  is_pinned?: boolean;
};

export type FriendItem = {
  id: number;
  name: string;
  avatar_url: string;
  description: string;
  website_url: string;
  language: string;
  rss_url: string;
  category: string;
  sort_order: number;
  is_enabled: boolean;
  updated_at: string;
};

export type FriendPayload = Omit<FriendItem, "id" | "updated_at">;

export type UserItem = {
  // UUID_SHORT() exceeds Number.MAX_SAFE_INTEGER; keep it lossless.
  uid: string;
  username: string;
  email: string;
  display_name: string;
  avatar_url: string;
  bio: string;
  website_url: string;
  role: "admin" | "user";
  status: "active" | "disabled";
  password_configured: boolean;
  generated_password?: string;
  last_login_at: string | null;
  created_at: string;
  updated_at: string;
};

export type UserPayload = {
  uid?: string;
  username: string;
  email: string;
  display_name?: string;
  avatar_url?: string;
  bio?: string;
  website_url?: string;
  role: "admin" | "user";
  status: "active" | "disabled";
  password?: string;
  generate_password?: boolean;
  confirm_sensitive?: boolean;
  allow_uid_override?: boolean;
};

export type UserUpdateResponse = {
  data: UserItem;
  session?: {
    accessToken: string;
    refreshToken: string;
    expires: Date;
    avatar: string;
    username: string;
    nickname: string;
    roles: string[];
    permissions: string[];
  };
};

export const getDashboard = () =>
  http.request<DashboardResponse>("get", "/admin/dashboard");

export const getAdminArticles = (params?: {
  limit?: number;
  offset?: number;
  search?: string;
}) =>
  http.request<{ items: ArticleItem[]; total: number }>(
    "get",
    "/admin/articles",
    {
      params
    }
  );

export const getAdminArticle = (articleId: number) =>
  http.request<{ data: ArticleItem }>("get", `/admin/articles/${articleId}`);

export const createArticle = (data: ArticlePayload) =>
  http.request<{ data: ArticleItem }>("post", "/admin/articles", { data });

export const updateArticle = (
  articleId: number,
  data: Partial<ArticlePayload>
) =>
  http.request<{ data: ArticleItem }>("put", `/admin/articles/${articleId}`, {
    data
  });

export const deleteArticle = (articleId: number) =>
  http.request<{ success: boolean }>("delete", `/admin/articles/${articleId}`);

export const getAdminComments = (params?: {
  limit?: number;
  offset?: number;
}) =>
  http.request<{ items: any[]; total: number }>("get", "/admin/comments", {
    params
  });

export const updateCommentStatus = (
  commentId: number,
  status: "visible" | "hidden"
) =>
  http.request<{ success: boolean }>(
    "patch",
    `/admin/comments/${commentId}/status`,
    {
      data: { status }
    }
  );

export const getAdminFriends = () =>
  http.request<{ items: FriendItem[]; total: number }>("get", "/admin/friends");

export const createFriend = (data: FriendPayload) =>
  http.request<{ data: FriendItem }>("post", "/admin/friends", { data });

export const updateFriend = (friendId: number, data: FriendPayload) =>
  http.request<{ data: FriendItem }>("put", `/admin/friends/${friendId}`, {
    data
  });

export const deleteFriend = (friendId: number) =>
  http.request<{ success: boolean }>("delete", `/admin/friends/${friendId}`);

export const getAdminUsers = () =>
  http.request<{ items: UserItem[]; total: number }>("get", "/admin/users");

export const createUser = (data: UserPayload) =>
  http.request<{ data: UserItem }>("post", "/admin/users", { data });

export const updateUser = (userId: string, data: Partial<UserPayload>) =>
  http.request<UserUpdateResponse>("put", `/admin/users/${userId}`, { data });

export const deleteUser = (userId: string) =>
  http.request<{ success: boolean }>(
    "delete",
    `/admin/users/${userId}?confirmed=true`
  );

export const getSiteSettings = () =>
  http.request<{ data: Record<string, unknown> }>(
    "get",
    "/admin/site/settings"
  );

export const updateSiteSettings = (data: Record<string, unknown>) =>
  http.request<{ success: boolean; data: Record<string, unknown> }>(
    "put",
    "/admin/site/settings",
    { data }
  );

export type FireflyConfig = Record<string, any>;

export const getFireflyConfig = () =>
  http.request<{ data: FireflyConfig }>("get", "/admin/firefly/config");

export const updateFireflyConfig = (config: FireflyConfig) =>
  http.request<{ success: boolean; data: FireflyConfig }>(
    "put",
    "/admin/firefly/config",
    { data: { config } }
  );

export type AccountSettings = {
  registration_enabled: boolean;
  email_verification_enabled: boolean;
  mail: {
    smtp_host: string;
    smtp_port: number;
    smtp_username: string;
    from_email: string;
    sender_name: string;
    use_tls: boolean;
    use_ssl: boolean;
    configured: boolean;
    password_configured: boolean;
  };
};

export const getAccountSettings = () =>
  http.request<{ data: AccountSettings }>("get", "/admin/account/settings");

export const updateAccountSettings = (data: Record<string, unknown>) =>
  http.request<{ success: boolean; data: AccountSettings }>(
    "put",
    "/admin/account/settings",
    { data }
  );

export const sendTestMail = (recipient: string) =>
  http.request<{ success: boolean; recipient: string }>(
    "post",
    "/admin/account/mail/test",
    { data: { recipient } }
  );

export type CloudflareSettings = {
  auth_type: "api_token" | "global_key";
  email: string;
  account_id: string;
  zone_id: string;
  zone_name: string;
  credential_configured: boolean;
  configured: boolean;
};

export const getCloudflareSettings = () =>
  http.request<{ data: CloudflareSettings }>(
    "get",
    "/admin/cdn/cloudflare/settings"
  );

export const updateCloudflareSettings = (data: Record<string, unknown>) =>
  http.request<{ success: boolean; data: CloudflareSettings }>(
    "put",
    "/admin/cdn/cloudflare/settings",
    { data }
  );

export const purgeCloudflareCache = () =>
  http.request<{
    success: boolean;
    zone_id: string;
    zone_name: string;
    purge_id: string;
    purged_at: string;
  }>("post", "/admin/cdn/cloudflare/purge-all");

export type MediaItem = {
  deleted_at?: string | null;
  id: number;
  object_key: string;
  public_url: string;
  original_name: string;
  mime_type: string;
  byte_size: number;
  category: string;
  storage_backend: "od" | "r2" | "local" | "legacy";
  sha256?: string;
  created_at: string;
  uploader_id?: number | null;
  uploader_name?: string | null;
  uploader_username?: string | null;
};

export type MediaStorageSettings = {
  r2_account_id: string;
  r2_bucket: string;
  r2_public_base_url: string;
  r2_endpoint_url: string;
  r2_limit_bytes: number;
  local_root: string;
  local_public_base_url: string;
  storage_mode: "od_first" | "r2_first" | "balanced";
  od_weight: number;
  r2_weight: number;
  fallback_enabled: boolean;
  od_enabled: boolean;
  od_configured: boolean;
  od_public_base_url: string;
  r2_access_key_configured: boolean;
  r2_secret_key_configured: boolean;
  r2_configured: boolean;
};

export type MediaStorageStatus = {
  r2_configured: boolean;
  r2_bytes: number;
  r2_limit_bytes: number;
  r2_used_percent: number;
  r2_remaining_bytes: number;
  local_bytes: number;
  total_bytes: number;
  od_configured: boolean;
  od_bytes: number;
  storage_mode: "od_first" | "r2_first" | "balanced";
  next_backend: "od" | "r2" | "balanced" | "unavailable";
};

export const getAdminMedia = (params?: { limit?: number; offset?: number; trash?: boolean }) =>
  http.request<{ items: MediaItem[]; total: number }>("get", "/admin/media", {
    params
  });

export type MediaUploadProgress = {
  loaded: number;
  total: number;
  bytesPerSecond: number;
};

/** Upload original bytes directly to the chosen cloud. Azure signs and verifies metadata. */
export const uploadAdminMedia = async (
  file: File,
  category = "general",
  onProgress?: (value: MediaUploadProgress) => void
): Promise<{ data: MediaItem }> => {
  if (window.location.hostname.endsWith(".preview.replow.org")) {
    const data = new FormData(); data.append("file", file); data.append("category", category);
    return http.request<{data:MediaItem}>("post", "/admin/media/upload", {data, headers:{"Content-Type":"multipart/form-data"},
      onUploadProgress:event=>onProgress?.({loaded:event.loaded,total:file.size,bytesPerSecond:event.rate||0})});
  }
  if (!globalThis.crypto?.subtle) {
    throw new Error("当前浏览器不支持安全直传，请使用 HTTPS 和较新的浏览器");
  }
  if (!file.size || file.size > 100 * 1024 * 1024) {
    throw new Error("文件不能为空或超过 100 MB");
  }
  const bytes = await file.arrayBuffer();
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  const quickxor = quickXorHash(bytes);
  const sha256 = Array.from(new Uint8Array(digest), byte =>
    byte.toString(16).padStart(2, "0")
  ).join("");
  const mimeTypes: Record<string, string> = {
    jpg: "image/jpeg",
    jpeg: "image/jpeg",
    png: "image/png",
    gif: "image/gif",
    webp: "image/webp",
    avif: "image/avif",
    bmp: "image/bmp",
    heic: "image/heic",
    heif: "image/heif",
    pdf: "application/pdf",
    txt: "text/plain",
    epub: "application/epub+zip",
    zip: "application/zip",
    mp3: "audio/mpeg",
    mp4: "video/mp4",
    webm: "video/webm",
    ogg: "audio/ogg",
    wav: "audio/wav",
    flac: "audio/flac"
  };
  const extension = file.name.split(".").pop()?.toLowerCase() || "";
  const contentType =
    mimeTypes[extension] || file.type || "application/octet-stream";
  const prepared = await http.request<{
    data: {
      upload_url: string;
      ticket: string;
      content_type: string;
      sha256: string;
      backend: "od" | "r2";
      chunk_size?: number;
    };
  }>("post", "/admin/media/direct/prepare", {
    data: {
      filename: file.name,
      category,
      content_type: contentType,
      byte_size: file.size,
      sha256,
      quickxor
    },
    timeout: 60_000
  });
  try {
    // A separate Axios instance: no site cookies, bearer tokens or app headers.
    if (prepared.data.backend === "od") {
      const chunkSize = prepared.data.chunk_size || 5 * 1024 * 1024;
      for (let offset = 0; offset < file.size; offset += chunkSize) {
        const end = Math.min(offset + chunkSize, file.size);
        await Axios.put(prepared.data.upload_url, file.slice(offset, end), {
          timeout: 300_000,
          withCredentials: false,
          headers: {
            "Content-Type": "application/octet-stream",
            "Content-Range": `bytes ${offset}-${end - 1}/${file.size}`
          },
          onUploadProgress: onProgress
            ? event =>
                onProgress({
                  loaded: offset + event.loaded,
                  total: file.size,
                  bytesPerSecond: event.rate || 0
                })
            : undefined
        });
      }
    } else
      await Axios.put(prepared.data.upload_url, file, {
        timeout: 300_000,
        withCredentials: false,
        headers: {
          "Content-Type": prepared.data.content_type,
          "x-amz-meta-sha256": prepared.data.sha256,
          "Cache-Control": "public, max-age=31536000, immutable"
        },
        onUploadProgress: onProgress
          ? event =>
              onProgress({
                loaded: event.loaded,
                total: event.total || file.size,
                bytesPerSecond: event.rate || 0
              })
          : undefined
      });
  } catch {
    // Never expose presigned URLs in errors or logs.
    throw new Error(
      `${prepared.data.backend === "od" ? "OneDrive" : "R2"} 直传失败，请检查当前网络或稍后重试`
    );
  }
  return http.request<{ data: MediaItem }>(
    "post",
    "/admin/media/direct/confirm",
    {
      data: { ticket: prepared.data.ticket },
      timeout: 60_000
    }
  );
};

/** Surface the actual upload failure instead of hiding it behind a generic toast. */
export function mediaUploadErrorMessage(error: unknown): string {
  const failure = error as {
    code?: string;
    response?: { status?: number; data?: { detail?: unknown } };
  } | null;
  const code = failure?.code;
  const status = failure?.response?.status;
  if (
    error instanceof Error &&
    (error.message.startsWith("R2 直传失败") ||
      error.message.startsWith("OneDrive 直传失败") ||
      error.message.startsWith("当前浏览器不支持安全直传") ||
      error.message.startsWith("文件不能为空"))
  )
    return error.message;
  if (code === "ECONNABORTED" || code === "ETIMEDOUT") {
    return "图片上传超时，请检查网络后重试";
  }
  if (status === 413) return "图片超过服务器上传大小限制";
  if (status === 401) return "登录状态已失效，请重新登录后上传";
  const detail = failure?.response?.data?.detail;
  if (typeof detail === "string") {
    if (detail.startsWith("media_r2_upload_failed")) {
      return "R2 存储上传失败，请检查存储服务状态";
    }
    const labels: Record<string, string> = {
      media_file_too_large: "文件不能超过 100 MB",
      media_file_empty: "图片文件为空",
      media_r2_sdk_not_installed: "服务器尚未安装 R2 存储依赖",
      media_r2_direct_not_configured: "R2 存储未配置，无法直接上传",
      media_r2_direct_limit_reached: "R2 剩余容量不足，已阻止上传",
      media_direct_object_mismatch: "云端文件校验未通过，请重新上传",
      media_direct_object_not_found: "R2 尚未收到图片，请稍后重试",
      media_direct_ticket_invalid: "上传授权已过期，请重新上传",
      media_direct_validation_failed: "R2 文件验证暂时失败",
      media_checksum_invalid: "图片完整性校验失败",
      media_r2_direct_sign_failed: "暂时无法生成 R2 上传授权",
      media_storage_unavailable: "没有可用的云存储，请检查存储策略或授权",
      media_storage_prepare_failed: "上传准备失败，请稍后重试或启用备用存储",
      media_onedrive_validation_failed: "OneDrive 文件尚未确认，请稍后重试",
      media_onedrive_delete_failed: "OneDrive 文件删除失败，请稍后重试",
      media_hash_required: "请刷新后台后重新上传",
      media_image_type_not_allowed: "文件格式或文件内容不受支持"
    };
    return labels[detail] || detail;
  }
  if (status === 502 || status === 504) return "上传服务响应超时，请稍后重试";
  return "图片上传失败，请检查网络后重试";
}

export const deleteAdminMedia = (mediaId: number) =>
  http.request<{ success: boolean }>("delete", `/admin/media/${mediaId}`);

export const getMediaStorageSettings = () =>
  http.request<{ data: MediaStorageSettings }>(
    "get",
    "/admin/storage/settings"
  );

export const updateMediaStorageSettings = (data: Record<string, unknown>) =>
  http.request<{ success: boolean; data: MediaStorageSettings }>(
    "put",
    "/admin/storage/settings",
    { data }
  );

export const getMediaStorageStatus = () =>
  http.request<{ data: MediaStorageStatus }>("get", "/admin/storage/status");

// -- domain registration / access keys -----------------------------------

export type AccessKeyStatus = "pending" | "active" | "revoked";

export type AccessKeyItem = {
  id: number;
  // UUID_SHORT() exceeds Number.MAX_SAFE_INTEGER; keep it lossless.
  user_uid: string | number;
  module_slug: string;
  module_name?: string;
  key_prefix: string;
  status: AccessKeyStatus;
  email: string;
  site_url: string;
  host: string;
  verified_at: string | null;
  verification_expires_at: string | null;
  last_used_at: string | null;
  rate_limit_override: number | null;
  expires_at: string | null;
  created_at: string | null;
};

export type VerificationChannel = {
  record_type?: string;
  name?: string;
  value?: string;
  url?: string;
  content?: string;
  description: string;
};

export type ChallengeInstructions = {
  token: string;
  dns: VerificationChannel & {
    record_type: string;
    name: string;
    value: string;
  };
  http: VerificationChannel & { url: string; content: string };
};

export type AccessKeyRegistration = {
  id: number;
  user_uid: number;
  module_slug: string;
  module_name: string;
  email: string;
  site_url: string;
  host: string;
  status: AccessKeyStatus;
  /** Plaintext key — returned exactly once, on registration or rotation. */
  key: string;
  key_prefix: string;
  verification: ChallengeInstructions;
  verification_expires_at: string | null;
};

export type AccessKeyVerifyCheck = {
  method: "dns" | "http";
  target: string;
  matched: boolean;
  detail: string;
};

export type AccessKeyVerifyResult = {
  verified: boolean;
  status: AccessKeyStatus;
  already_verified?: boolean;
  activated?: boolean;
  matched_by?: "dns" | "http";
  checks?: AccessKeyVerifyCheck[];
  detail: string;
};

export type AccessKeyRotateResult = {
  id: number;
  key: string;
  key_prefix: string;
};

export type ModuleItem = {
  slug: string;
  name: string;
  description: string;
  base_path: string;
  access_mode: string;
  enabled: boolean;
};

export const getAccessKeys = () =>
  http.request<{ data: AccessKeyItem[] }>("get", "/admin/access-keys");

export const registerAccessKey = (data: {
  site_url: string;
  module_slug: string;
  email?: string;
}) =>
  http.request<{ data: AccessKeyRegistration }>("post", "/admin/access-keys", {
    data
  });

export const verifyAccessKey = (
  keyId: number,
  method: "auto" | "dns" | "http" = "auto"
) =>
  http.request<{ data: AccessKeyVerifyResult }>(
    "post",
    `/admin/access-keys/${keyId}/verify`,
    { data: { method } }
  );

export const regenerateAccessKeyChallenge = (keyId: number) =>
  http.request<{ data: AccessKeyRegistration }>(
    "post",
    `/admin/access-keys/${keyId}/challenge`
  );

export const rotateAccessKey = (keyId: number) =>
  http.request<{ data: AccessKeyRotateResult }>(
    "post",
    `/admin/access-keys/${keyId}/rotate`
  );

export const deleteAccessKey = (keyId: number) =>
  http.request<{ success: boolean }>("delete", `/admin/access-keys/${keyId}`);

export const getAllAccessKeys = (params?: {
  user_uid?: number;
  module_slug?: string;
  status?: AccessKeyStatus;
}) =>
  http.request<{ data: AccessKeyItem[] }>("get", "/admin/access-keys/all", {
    params
  });

export const adminVerifyAccessKey = (
  keyId: number,
  method: "auto" | "dns" | "http" = "auto"
) =>
  http.request<{ data: AccessKeyVerifyResult }>(
    "post",
    `/admin/access-keys/all/${keyId}/verify`,
    { data: { method } }
  );

export const adminUpdateAccessKey = (
  keyId: number,
  data: {
    site_url?: string;
    email?: string;
    status?: AccessKeyStatus;
    rate_limit_override?: number | null;
  }
) =>
  http.request<{ data: AccessKeyItem }>(
    "patch",
    `/admin/access-keys/all/${keyId}`,
    { data }
  );

export const getApiModules = () =>
  http.request<{ data: ModuleItem[] }>("get", "/admin/access-keys/modules");

export type SiteBuildStatus = {
  environment?: string; site_url?: string; stage?: string; run_url?: string; commit?: string;
  last_published_at?: string; published_version?: string; content_saved_at?: string; has_unpublished_changes?: boolean;
  status: string;
  version: string;
  error: string;
  started_at?: string;
  finished_at?: string;
};
export const getSiteBuild = () =>
  http.request<{ data: SiteBuildStatus }>("get", "/admin/site/build");
export const startSiteBuild = () =>
  http.request<{ success: boolean; data: SiteBuildStatus }>(
    "post",
    "/admin/site/build"
  );

export type AuditItem = {
  id: number;
  actor_uid: string | null;
  actor_name: string;
  action: string;
  resource: string;
  target_id: string;
  status_code: number;
  ip_address: string;
  created_at: string;
  changes: Array<{ field: string; before: string; after: string }>;
};
export const getAuditLogs = (params: {
  limit: number;
  offset: number;
  search?: string;
  outcome?: string;
}) =>
  http.request<{ items: AuditItem[]; total: number }>(
    "get",
    "/admin/audit-logs",
    { params }
  );
export type DeviceSession = {
  id: string;
  user_agent: string;
  ip_address: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  is_current: boolean;
};
export const getDeviceSessions = () =>
  http.request<{ items: DeviceSession[]; tracked_current: boolean }>(
    "get",
    "/auth/sessions"
  );
export const revokeDeviceSession = (id: string) =>
  http.request<{ success: boolean; current_revoked: boolean }>(
    "delete",
    "/auth/sessions/" + id
  );
export const revokeOtherSessions = () =>
  http.request<{ data: NonNullable<UserUpdateResponse["session"]> }>(
    "post",
    "/auth/sessions/revoke-others",
    { data: { confirmed: true } }
  );
export type AlbumPhoto = {
  id?: number;
  media_id: number;
  caption: string;
  sort_order?: number;
  public_url?: string;
  original_name?: string;
};
export type AlbumItem = {
  id: number;
  title: string;
  description: string;
  cover_url: string;
  resolved_cover?: string;
  sort_order: number;
  is_published: boolean;
  photo_count?: number;
  photos?: AlbumPhoto[];
};
export const getAlbums = () =>
  http.request<{ items: AlbumItem[] }>("get", "/admin/albums");
export const getAlbum = (id: number) =>
  http.request<{ data: AlbumItem }>("get", "/admin/albums/" + id);
export const saveAlbum = (data: Omit<AlbumItem, "id">, id?: number) =>
  http.request<{ data: AlbumItem }>(
    id ? "put" : "post",
    id ? "/admin/albums/" + id : "/admin/albums",
    { data }
  );
export const saveAlbumPhotos = (id: number, photos: AlbumPhoto[]) =>
  http.request<{ data: AlbumItem }>("put", "/admin/albums/" + id + "/photos", {
    data: {
      photos: photos.map(({ media_id, caption }) => ({ media_id, caption }))
    }
  });
export const deleteAlbum = (id: number) =>
  http.request<{ success: boolean }>("delete", "/admin/albums/" + id);

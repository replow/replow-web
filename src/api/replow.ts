import { http } from "@/utils/http";

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
  id: number;
  object_key: string;
  public_url: string;
  original_name: string;
  mime_type: string;
  byte_size: number;
  category: string;
  storage_backend: "r2" | "local" | "legacy";
  sha256?: string;
  created_at: string;
};

export type MediaStorageSettings = {
  r2_account_id: string;
  r2_bucket: string;
  r2_public_base_url: string;
  r2_endpoint_url: string;
  r2_limit_bytes: number;
  local_root: string;
  local_public_base_url: string;
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
  next_backend: "r2" | "local";
};

export const getAdminMedia = (params?: { limit?: number; offset?: number }) =>
  http.request<{ items: MediaItem[]; total: number }>("get", "/admin/media", {
    params
  });

export const uploadAdminMedia = (file: File, category = "general") => {
  const form = new FormData();
  form.append("file", file);
  form.append("category", category);
  return http.request<{ data: MediaItem }>("post", "/admin/media/upload", {
    data: form,
    headers: { "Content-Type": "multipart/form-data" }
  });
};

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

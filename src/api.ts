// The session cookie is only shared between hosts on the same registrable
// domain. Whenever this app is served from a domain that proxies the API on
// its own origin, use that same-origin path so the browser actually sends the
// cookie back. Anything else falls back to the public API host.
const FALLBACK_API_BASE = (import.meta.env.VITE_API_BASE_URL || "https://api.example.com/v1").replace(/\/$/, "");
const SAME_ORIGIN_API_DOMAINS = ["example.com", "example.com"];

function resolveApiBase(): string {
  if (typeof window === "undefined") return FALLBACK_API_BASE;
  const host = window.location.hostname.toLowerCase();
  const matched = SAME_ORIGIN_API_DOMAINS.some(
    (domain) => host === domain || host.endsWith("." + domain)
  );
  return matched ? "/v1" : FALLBACK_API_BASE;
}

const API_BASE = resolveApiBase();
const SESSION_KEY = "silvercode.account.session";

export type SessionData = {
  accessToken: string;
  refreshToken: string;
  expires: string | Date;
  avatar: string;
  username: string;
  nickname: string;
  roles: string[];
  permissions: string[];
};

export type Profile = {
  uid: string;
  username: string;
  email: string;
  display_name: string;
  avatar_url: string;
  bio: string;
  website_url: string;
  role: "admin" | "user";
  status: string;
  /**
   * False only for accounts that a first-time verification-code login created
   * and that have neither picked a username nor set a password yet. Drives the
   * account-setup dialog.
   */
  setup_completed: boolean;
  last_login_at: string;
  created_at: string;
  updated_at: string;
};

export type Article = {
  id: number;
  title: string;
  slug: string;
  excerpt: string;
  body_markdown: string;
  cover_url: string;
  icon_url: string;
  category: string;
  tags: string[];
  status: "draft" | "pending" | "published" | "rejected";
  is_pinned: boolean;
  published_at: string;
  updated_at: string;
};

export type CommentItem = {
  id: number;
  article_id: number;
  article_title: string;
  article_slug: string;
  parent_id: number | null;
  body_markdown: string;
  status: string;
  edited_at: string;
  created_at: string;
  updated_at: string;
};

export type NotificationItem = {
  id: string;
  type: "comment_reply" | "friend_link" | "article_status" | string;
  title: string;
  body: string;
  created_at: string;
  href: string;
};

export type FriendApplication = {
  id: number;
  site_name: string;
  website_url: string;
  avatar_url: string;
  language: string;
  rss_url: string;
  description: string;
  applicant_note: string;
  status: "pending_email" | "approved" | "rejected";
  verification_expires_at: string;
  email_verified_at: string;
  rejection_reason: string;
  friend_link_id: number | null;
  created_at: string;
  updated_at: string;
};

export class ApiError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.status = status;
    this.detail = detail;
  }
}

let refreshing: Promise<boolean> | null = null;

export function getSession(): SessionData | null {
  try {
    const value = localStorage.getItem(SESSION_KEY);
    return value ? (JSON.parse(value) as SessionData) : null;
  } catch {
    return null;
  }
}

export function saveSession(data: SessionData) {
  localStorage.setItem(SESSION_KEY, JSON.stringify(data));
}

export function clearSession() {
  localStorage.removeItem(SESSION_KEY);
}

async function parseResponse(response: Response) {
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json")
    ? await response.json().catch(() => ({}))
    : await response.text().catch(() => "");
  if (!response.ok) {
    const detail =
      typeof body === "object" && body
        ? String((body as any).detail || ("http_" + response.status))
        : ("http_" + response.status);
    throw new ApiError(response.status, detail);
  }
  return body;
}

async function refreshSession(): Promise<boolean> {
  const session = getSession();
  if (!session?.refreshToken) return false;
  try {
    const response = await fetch(API_BASE + "/auth/refresh", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ refreshToken: session.refreshToken })
    });
    const result = await parseResponse(response);
    if (!(result as any)?.data?.accessToken) return false;
    saveSession((result as any).data);
    return true;
  } catch {
    clearSession();
    return false;
  }
}

async function ensureRefresh() {
  if (!refreshing) {
    refreshing = refreshSession().finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
  auth = true,
  retry = true
): Promise<T> {
  const headers = new Headers(options.headers || {});
  headers.set("Accept", "application/json");
  if (options.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");

  if (auth) {
    const session = getSession();
    if (session?.accessToken) headers.set("Authorization", "Bearer " + session.accessToken);
  }

  const response = await fetch(API_BASE + path, {
    ...options,
    credentials: "include",
    headers
  });
  if (response.status === 401 && auth && retry) {
    if (await ensureRefresh()) return request<T>(path, options, auth, false);
  }
  return (await parseResponse(response)) as T;
}

export const authApi = {
  async session() {
    const result = await request<{ success: boolean; data: SessionData }>(
      "/auth/session",
      { method: "POST" },
      false,
      false
    );
    saveSession(result.data);
    return result.data;
  },
  async logout() {
    try {
      await request("/auth/logout", { method: "POST" }, false, false);
    } finally {
      clearSession();
    }
  },
  passwordLogin(identity: string, password: string) {
    return request<{ success: boolean; data: SessionData }>(
      "/auth/login",
      { method: "POST", body: JSON.stringify({ identity, password }) },
      false
    );
  },
  sendCode(data: { email: string; purpose: "login" | "reset" }) {
    return request<{ success: boolean; expires_in?: number }>(
      "/auth/verification/send",
      { method: "POST", body: JSON.stringify(data) },
      false
    );
  },
  /**
   * Verification-code login. If the email has no account yet one is created on
   * the spot, and the response carries `requiresSetup: true` so the console can
   * ask for a username and password.
   */
  codeLogin(email: string, code: string) {
    return request<{ success: boolean; data: SessionData; requiresSetup?: boolean }>(
      "/auth/code-login",
      { method: "POST", body: JSON.stringify({ email, code }) },
      false
    );
  },
  /** Finish the account created by a first-time code login. */
  setupAccount(username: string, password: string, display_name?: string) {
    return request<{ success: boolean; data: SessionData }>(
      "/auth/account/setup",
      {
        method: "POST",
        body: JSON.stringify({ username, password, display_name: display_name || undefined })
      }
    );
  },
  /** Dismiss the setup dialog: keep the generated username, stay password-less. */
  skipAccountSetup() {
    return request<{ success: boolean; data: SessionData }>(
      "/auth/account/setup/skip",
      { method: "POST" }
    );
  },
  resetVerify(email: string, code: string) {
    return request<{ success: boolean; resetToken: string }>(
      "/auth/password-reset/verify",
      { method: "POST", body: JSON.stringify({ email, code }) },
      false
    );
  },
  resetConfirm(reset_token: string, password: string) {
    return request<{ success: boolean; data: SessionData }>(
      "/auth/password-reset/confirm",
      { method: "POST", body: JSON.stringify({ reset_token, password }) },
      false
    );
  }
};

export function humanError(error: unknown): string {
  const detail = error instanceof ApiError ? error.detail : "";
  const messages: Record<string, string> = {
    invalid_credentials: "账号或密码不正确",
    not_authenticated: "登录状态已失效，请重新登录",
    account_unavailable: "账号不可用或已被停用",
    invalid_email: "邮箱格式不正确",
    email_already_exists: "这个邮箱已经被其他账号使用",
    email_unchanged: "新邮箱与当前邮箱相同",
    invalid_username: "用户名需为 3–32 位字母、数字或常用符号",
    username_already_exists: "用户名已存在",
    registration_disabled: "当前暂未开放注册",
    verification_code_invalid: "验证码不正确",
    verification_code_expired: "验证码已过期，请重新获取",
    verification_code_locked: "验证码错误次数过多，请重新获取",
    too_many_verification_requests: "请求过于频繁，请稍后再试",
    mail_not_configured: "邮件服务尚未配置",
    mail_delivery_failed: "验证码邮件发送失败",
    invalid_password: "密码需为 8–128 位",
    old_password_invalid: "旧密码不正确",
    article_slug_already_exists: "文章 Slug 已存在，请换一个",
    article_not_found: "文章不存在或不属于当前账号",
    comment_not_found: "评论不存在或不属于当前账号",
    friend_application_exists: "你已经提交过这个站点",
    friend_link_exists: "这个站点已经在友情链接中",
    friend_application_not_found: "友链申请不存在",
    friend_application_not_pending: "该申请当前无法验证",
    friend_link_limit_reached: "每个账号最多只能拥有 3 个等待验证或已通过的友情链接",
    invalid_rss_url: "RSS 地址必须是 HTTP 或 HTTPS 地址",
    rss_url_too_long: "RSS 地址不能超过 2048 个字符",
    language_too_long: "网站语言不能超过 80 个字符",
    friend_verification_invalid: "友情链接认证地址无效",
    friend_verification_invalid_or_used: "友情链接认证地址无效、已使用或已失效",
    friend_verification_expired: "友情链接认证地址已过期，请登录账号中心重新发送"
  };
  return messages[detail] || (detail ? "操作失败：" + detail : "操作失败，请稍后再试");
}

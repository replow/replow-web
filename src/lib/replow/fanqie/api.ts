import type { Book } from './types';

const API = '/fq';
interface ServiceSettings { enabled: boolean; paused: boolean }
interface Token { token: string; expires_in: number; username?: string; service?: ServiceSettings }
interface Envelope<T> {
  data: T;
  detail?: string;
}
export class LoginRequired extends Error {}

// In-memory only: never save signed access tokens in localStorage/sessionStorage.
// Shared by Astro pages while the same document is open; cleared on identity changes.
let sharedAuth: { username: string; token: string; expires: number; service?: ServiceSettings } | null = null;
let lastIdentity = '';
if (typeof document !== 'undefined') {
  document.addEventListener('replow:signout', () => {
    sharedAuth = null;
    lastIdentity = '';
  });
  document.addEventListener('replow:auth', (event) => {
    const username = (event as CustomEvent<{ username?: string } | null>).detail?.username || '';
    if (lastIdentity && lastIdentity !== username) sharedAuth = null;
    lastIdentity = username;
  });
}
const identity = () =>
  (window as Window & { __replowAuthSession?: { username?: string } | null }).__replowAuthSession?.username || '';
const lookupCache = new Map<string, { expires: number; data: { books: Book[]; hasMore: boolean } }>();

const messages: Record<string, string> = {
  upstream_busy: '正在处理其他请求，请稍后重试。',
  upstream_unavailable: '小说服务暂时不可用，请稍后重试。',
  upstream_response_failed: '暂时无法获取这本书，请检查书籍 ID 或稍后重试。',
  download_service_disabled: '下载服务维护中，已有文件仍可从历史记录下载。',
  download_queue_full: '下载队列已满，请等待现有任务完成。',
  too_many_token_requests: '请求过于频繁，请稍后再试。',
  chapter_range_out_of_bounds: '选择的章节范围超出目录，请重新选择。',
};
export const errorMessage = (error: unknown) =>
  error instanceof Error ? messages[error.message] || error.message : '请求失败，请稍后再试。';

function normalizeBook(value: Record<string, unknown>): Book {
  return {
    id: String(value.bookId || value.book_id || ''),
    title: String(value.bookName || value.title || '未命名书籍'),
    author: String(value.author || '作者未知'),
    cover: String(value.coverUrl || value.cover_url || ''),
    coverPending: value.coverPending === true,
    total: Number(value.totalChapters || value.serialCount || value.serial_count || 0),
    description: String(value.description || value.abstract || value.bookAbstract || value.intro || '').trim(),
  };
}

export function createFqClient(signal: AbortSignal) {
  let token = '';
  let tokenExpires = 0;
  let authorizing: Promise<void> | null = null;
  let serviceInfo: ServiceSettings | null = null;
  async function fetchData<T>(url: string, options: RequestInit): Promise<T> {
    const response = await fetch(url, {
      ...options,
      signal: options.signal ? AbortSignal.any([signal, options.signal]) : signal,
      cache: 'no-store',
    });
    if (response.status === 401) throw new LoginRequired('请先登录后使用下载器。');
    const result = (await response.json().catch(() => ({ detail: '服务暂时不可用，请稍后重试。' }))) as Envelope<T>;
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '请求参数有误，请重新选择。');
    return result.data;
  }
  async function authorize() {
    if (token && tokenExpires > Date.now() + 30_000) return;
    if (sharedAuth && identity() && sharedAuth.username === identity() && sharedAuth.expires > Date.now() + 30_000) {
      token = sharedAuth.token;
      tokenExpires = sharedAuth.expires;
      serviceInfo = sharedAuth.service ?? null;
      return;
    }
    if (authorizing) return authorizing;
    authorizing = (async () => {
      const data = await fetchData<Token>(API + '/session', { method: 'POST', credentials: 'include' });
      if (!data?.token) throw new LoginRequired('请先登录后使用下载器。');
      token = data.token;
      tokenExpires = Date.now() + data.expires_in * 1000;
      serviceInfo = data.service ?? null;
      const username = identity() || data.username || '';
      if (username) sharedAuth = { username, token, expires: tokenExpires, service: serviceInfo ?? undefined };
    })().finally(() => { authorizing = null; });
    return authorizing;
  }
  async function request<T>(path: string, body?: unknown, retry = true, options: RequestInit = {}): Promise<T> {
    await authorize();
    try {
      return await fetchData<T>(API + path, {
        ...options,
        method: body === undefined ? 'GET' : 'POST',
        credentials: 'omit',
        headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch (error) {
      if (error instanceof LoginRequired && retry) {
        token = '';
        sharedAuth = null;
        await authorize();
        return request<T>(path, body, false, options);
      }
      throw error;
    }
  }
  const searches = new Map<string, { signal?: AbortSignal; promise: Promise<{ books: Book[]; hasMore: boolean }> }>();
  return {
    authorize,
    request,
    async serviceSettings(): Promise<ServiceSettings> {
      await authorize();
      return serviceInfo ?? request<ServiceSettings>('/settings');
    },
    async book(id: string) {
      return normalizeBook(await request<Record<string, unknown>>('/books/' + id));
    },
    async cover(id: string, options: RequestInit = {}) {
      const data = await request<{ coverUrl: string }>('/books/' + id + '/cover', undefined, true, options);
      return data.coverUrl || '';
    },
    async search(key: string, page: number, options: RequestInit = {}) {
      const cacheKey = JSON.stringify(['text-first-v1', key.trim(), page]);
      const hit = lookupCache.get(cacheKey);
      if (hit && hit.expires > Date.now()) return hit.data;
      const pending = searches.get(cacheKey);
      if (pending && !pending.signal?.aborted) return pending.promise;
      const promise = (async () => {
        const data = await request<{ books: Record<string, unknown>[]; hasMore: boolean }>(
          '/search?' + new URLSearchParams({ key, page: String(page), size: '10', defer_covers: 'true' }),
          undefined,
          true,
          options,
        );
        const result = { books: (data.books || []).slice(0, 10).map(normalizeBook), hasMore: Boolean(data.hasMore) };
        lookupCache.set(cacheKey, { expires: Date.now() + 300_000, data: result });
        if (lookupCache.size > 80) lookupCache.delete(lookupCache.keys().next().value!);
        return result;
      })();
      searches.set(cacheKey, { signal: options.signal || undefined, promise });
      try {
        return await promise;
      } finally {
        if (searches.get(cacheKey)?.promise === promise) searches.delete(cacheKey);
      }
    },
  };
}
export type FqClient = ReturnType<typeof createFqClient>;

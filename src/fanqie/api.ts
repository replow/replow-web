import type { Book } from './types';

const API = 'https://api.4z.ink/fq';
interface Grant { uid: number; grant_id: string; signing_key: string; server_time: number; expires_at: number }
interface Token { token: string; expires_in: number }
interface Envelope<T> { data: T; detail?: string }
export class LoginRequired extends Error {}

const messages: Record<string, string> = {
  upstream_busy: '正在处理其他请求，请稍后重试。', upstream_unavailable: '小说服务暂时不可用，请稍后重试。',
  upstream_response_failed: '暂时无法获取这本书，请检查书籍 ID 或稍后重试。',
  download_queue_full: '下载队列已满，请等待现有任务完成。', too_many_token_requests: '请求过于频繁，请稍后再试。',
  chapter_range_out_of_bounds: '选择的章节范围超出目录，请重新选择。',
};
export const errorMessage = (error: unknown) => error instanceof Error ? messages[error.message] || error.message : '请求失败，请稍后再试。';

function normalizeBook(value: Record<string, unknown>): Book {
  return { id: String(value.bookId || value.book_id || ''), title: String(value.bookName || value.title || '未命名书籍'),
    author: String(value.author || '作者未知'), cover: String(value.coverUrl || value.cover_url || ''),
    total: Number(value.totalChapters || value.serialCount || value.serial_count || 0), description: String(value.description || '') };
}

export function createFqClient(signal: AbortSignal) {
  let token = ''; let tokenExpires = 0; let authorizing: Promise<void> | null = null;
  async function fetchData<T>(url: string, options: RequestInit): Promise<T> {
    const response = await fetch(url, { ...options, signal, cache: 'no-store' });
    if (response.status === 401) throw new LoginRequired('请先登录后使用下载器。');
    const result = await response.json().catch(() => ({ detail: '服务暂时不可用，请稍后重试。' })) as Envelope<T>;
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '请求参数有误，请重新选择。');
    return result.data;
  }
  async function authorize() {
    if (token && tokenExpires > Date.now() + 30_000) return;
    if (authorizing) return authorizing;
    authorizing = (async () => {
      const session = await fetchData<{ accessToken: string }>('/v1/auth/session', { method: 'POST', credentials: 'include' });
      if (!session?.accessToken) throw new LoginRequired('请先登录后使用下载器。');
      const grant = await fetchData<Grant>(API + '/signing-key', { method: 'POST', credentials: 'omit', headers: { Authorization: `Bearer ${session.accessToken}` } });
      const base64 = grant.signing_key.replace(/-/g, '+').replace(/_/g, '/');
      const bytes = Uint8Array.from(atob(base64 + '='.repeat((4 - base64.length % 4) % 4)), c => c.charCodeAt(0));
      const secret = await crypto.subtle.importKey('raw', bytes, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
      bytes.fill(0);
      const nonce = Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('');
      const timestamp = grant.server_time;
      const message = `fq-token:v1\n${grant.uid}\n${grant.grant_id}\n${timestamp}\n${nonce}`;
      const signed = new Uint8Array(await crypto.subtle.sign('HMAC', secret, new TextEncoder().encode(message)));
      const signature = Array.from(signed, b => b.toString(16).padStart(2, '0')).join('');
      const data = await fetchData<Token>(API + '/token', { method: 'POST', credentials: 'omit', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ uid: grant.uid, key: `v1.${grant.grant_id}.${timestamp}.${nonce}.${signature}` }) });
      token = data.token; tokenExpires = Date.now() + data.expires_in * 1000;
    })().finally(() => { authorizing = null; });
    return authorizing;
  }
  async function request<T>(path: string, body?: unknown, retry = true): Promise<T> {
    await authorize();
    try {
      return await fetchData<T>(API + path, { method: body === undefined ? 'GET' : 'POST', credentials: 'omit',
        headers: { Authorization: `Bearer ${token}`, ...(body === undefined ? {} : { 'Content-Type': 'application/json' }) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    } catch (error) {
      if (error instanceof LoginRequired && retry) { token = ''; await authorize(); return request<T>(path, body, false); }
      throw error;
    }
  }
  return { authorize, request,
    async book(id: string) { return normalizeBook(await request<Record<string, unknown>>('/books/' + id)); },
    async search(key: string, page: number) {
      const data = await request<{ books: Record<string, unknown>[]; hasMore: boolean }>('/search?' + new URLSearchParams({ key, page: String(page), size: '10' }));
      return { books: (data.books || []).map(normalizeBook), hasMore: Boolean(data.hasMore) };
    },
  };
}
export type FqClient = ReturnType<typeof createFqClient>;

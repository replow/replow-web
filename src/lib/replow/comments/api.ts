export interface CommentItem {
  id: number;
  article_id: number;
  parent_id: number | null;
  user_id: number | null;
  user_name: string;
  user_avatar: string;
  body_markdown: string;
  created_at: string;
  edited_at: string | null;
}
export interface DiscussionPage {
  items: CommentItem[];
  total: number;
}
export interface Identity {
  username: string;
  nickname?: string;
}
export const identity = () => (window as Window & { __replowAuthSession?: Identity | null }).__replowAuthSession;
const messages: Record<string, string> = {
  not_authenticated: '请先登录，再加入讨论。',
  invalid_token: '登录已过期，请重新登录。',
  comment_too_fast: '发送有点快，请等 10 秒再试。',
  comment_empty: '先写一点内容吧。',
  comment_parent_invalid: '这条评论已不可回复，请取消回复后重试。',
  comment_image_too_large: '图片不能超过 5 MB。',
  comment_image_invalid: '请上传有效的 JPG、PNG、GIF、WebP 或 AVIF 图片。',
  comment_too_many_images: '图片数量超过账号限制，请减少后再发布。',
  comment_images_disabled: '此账号暂未开放图片上传。',
  comment_upload_too_fast: '本小时上传次数已达上限，请稍后再试。',
  comment_upload_failed: '图片上传失败，请稍后重试。',
  article_not_found: '文章暂不可评论。',
};
export function message(error: unknown): string {
  return error instanceof Error ? messages[error.message] || error.message : '暂时连接不上，请稍后再试。';
}
export function createCommentsApi(signal: AbortSignal) {
  let token = '',
    expires = 0,
    owner = '';
  async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const response = await fetch('/v1' + path, { ...options, credentials: 'include', cache: 'no-store', signal });
    const result = await response.json().catch(() => ({ detail: '服务暂时不可用，请稍后再试。' }));
    if (!response.ok) {
      if (response.status === 401) {
        token = '';
        expires = 0;
        throw new Error('not_authenticated');
      }
      throw new Error(typeof result.detail === 'string' ? result.detail : '请检查评论内容后重试。');
    }
    return result as T;
  }
  async function authorize() {
    const username = identity()?.username || '';
    if (!username) throw new Error('not_authenticated');
    if (token && expires > Date.now() + 30_000 && owner === username) return;
    const result = await request<{ data: { accessToken: string; expires: string } }>('/auth/session', { method: 'POST' });
    if (identity()?.username !== username) throw new Error('not_authenticated');
    token = result.data.accessToken;
    expires = new Date(result.data.expires).getTime();
    owner = username;
  }
  async function post<T>(path: string, body: FormData | object): Promise<T> {
    await authorize();
    const form = body instanceof FormData;
    return request<T>(path, {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + token, ...(form ? {} : { 'Content-Type': 'application/json' }) },
      body: form ? body : JSON.stringify(body),
    });
  }
  return {
    list: (article: number, offset: number) =>
      request<DiscussionPage>('/public/articles/' + article + '/discussion?limit=100&offset=' + offset),
    create: (body: object) => post<{ data: { id: number } }>('/account/comments', body),
    upload: (file: File) => {
      const body = new FormData();
      body.append('file', file);
      return post<{ data: { url: string } }>('/account/comments/images', body);
    },
  };
}

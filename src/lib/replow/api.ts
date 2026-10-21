const apiRoot = '/v1';
export async function fetchPublic<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(apiRoot + '/public/' + path, {
    headers: { Accept: 'application/json' },
    cache: 'no-store',
    signal,
  });
  if (!response.ok) throw new Error('Public API HTTP ' + response.status);
  return response.json() as Promise<T>;
}
export interface PublicArticle {
  id: number;
  slug: string;
  title: string;
  excerpt: string;
  body_markdown: string;
  published_at: string;
  updated_at: string;
  cover_url: string;
  category: string;
  tags: string[];
  is_pinned: boolean;
  status: string;
}
export async function allPublicArticles(signal?: AbortSignal): Promise<PublicArticle[]> {
  const articles: PublicArticle[] = [];
  let offset = 0;
  while (true) {
    const result = await fetchPublic<{ items: PublicArticle[]; total: number }>('articles?limit=200&offset=' + offset, signal);
    if (!Array.isArray(result.items) || !Number.isInteger(result.total)) throw new Error('Invalid article response');
    articles.push(...result.items);
    offset += result.items.length;
    if (offset >= result.total) return articles;
    if (!result.items.length) throw new Error('Incomplete article response');
  }
}

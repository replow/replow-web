import DOMPurify from 'dompurify';
import snapshot from '@/data/replow.json';
import { allPublicArticles, fetchPublic, type PublicArticle } from './api';

const escapeHtml = (value: unknown) =>
  String(value ?? '').replace(
    /[&<>"']/g,
    (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char] || char,
  );
const safeUrl = (url: string, fallback = '') => (/^(https?:\/\/|\/(?!\/))/.test(url) ? url : fallback);
const articlePath = (slug: string) => '/post/' + slug.split('/').map(encodeURIComponent).join('/') + '/';
const parseDate = (date: string) => Date.parse(/(?:Z|[+-]\d{2}:?\d{2})$/.test(date) ? date : date.replace(' ', 'T') + '+08:00');
const dateText = (date: string) => new Date(parseDate(date)).toLocaleDateString('zh-CN');

function articleCard(article: PublicArticle, index: number) {
  const cover = safeUrl(article.cover_url || snapshot.firefly.backgroundWallpaper.articlePlaceholderUrl);
  const href = articlePath(article.slug);
  const position = snapshot.firefly.koharuConfig.postCardImagePosition;
  const left = position === 'left' || (position !== 'right' && index % 2 === 0);
  return (
    '<article class="post-item-card replow-live-card shadow-card" data-api-slug="' +
    escapeHtml(article.slug) +
    '">' +
    '<a class="replow-live-cover ' +
    (left ? 'replow-cover-left' : 'replow-cover-right') +
    '" href="' +
    href +
    '" tabindex="-1" aria-hidden="true">' +
    '<img src="' +
    escapeHtml(cover) +
    '" alt="" loading="lazy" decoding="async" /></a>' +
    '<div class="replow-live-copy"><div class="replow-live-meta">' +
    escapeHtml(article.category) +
    ' · ' +
    escapeHtml(dateText(article.published_at)) +
    (article.is_pinned ? ' · 置顶' : '') +
    '</div>' +
    '<h2><a href="' +
    href +
    '">' +
    escapeHtml(article.title) +
    '</a></h2><p>' +
    escapeHtml(article.excerpt || article.body_markdown.replace(/[#*\x60>\n]/g, ' ').slice(0, 130)) +
    '</p>' +
    '<div class="replow-live-tags">' +
    (article.tags || [])
      .map(
        (tag) =>
          '<a href="/tags/' +
          encodeURIComponent(tag.trim().toLowerCase().replaceAll('/', '-')) +
          '/">' +
          escapeHtml(tag) +
          '</a>',
      )
      .join('') +
    '</div></div></article>'
  );
}

export async function refreshArticleList(signal: AbortSignal) {
  const container = document.querySelector<HTMLElement>('[data-replow-home-posts]');
  if (!container) return;
  const articles = await allPublicArticles(signal);
  if (signal.aborted || !container.isConnected) return;
  const key = JSON.stringify(
    articles.map(({ slug, updated_at, title, cover_url, category, tags }) => ({
      slug,
      updated_at,
      title,
      cover_url,
      category,
      tags,
    })),
  );
  const builtKey = JSON.stringify(
    snapshot.articles.map(({ slug, updated_at, title, cover_url, category, tags }) => ({
      slug,
      updated_at,
      title,
      cover_url,
      category,
      tags,
    })),
  );
  if (key === (container.dataset.liveKey || builtKey)) return;
  container.dataset.liveKey = key;
  const sorted = articles.toSorted(
    (a, b) => Number(b.is_pinned) - Number(a.is_pinned) || parseDate(b.published_at) - parseDate(a.published_at),
  );
  const size = Number(snapshot.firefly.siteConfig.pagination.postsPerPage || 10);
  let page = Math.min(
    Math.max(1, Number(new URL(location.href).searchParams.get('page')) || 1),
    Math.max(1, Math.ceil(sorted.length / size)),
  );
  function draw(container: HTMLElement) {
    container.innerHTML = DOMPurify.sanitize(
      sorted
        .slice((page - 1) * size, page * size)
        .map(articleCard)
        .join('') || '<p>暂无已发布文章。</p>',
    );
    const pages = Math.ceil(sorted.length / size);
    if (pages > 1) {
      const nav = document.createElement('nav');
      nav.className = 'replow-live-pagination';
      nav.setAttribute('aria-label', '文章分页');
      for (let number = 1; number <= pages; number++) {
        const button = document.createElement('button');
        button.textContent = String(number);
        button.setAttribute('aria-current', page === number ? 'page' : 'false');
        button.onclick = () => {
          page = number;
          const url = new URL(location.href);
          url.searchParams.set('page', String(number));
          history.replaceState(null, '', url);
          draw(container);
          container?.scrollIntoView({ block: 'start', behavior: 'smooth' });
        };
        nav.append(button);
      }
      container.append(nav);
    }
  }
  draw(container);
}

export async function refreshArticleBody(signal: AbortSignal) {
  const article = document.querySelector<HTMLElement>('[data-api-article-body]');
  if (!article) return;
  const slug =
    article.dataset.apiSlug ||
    new URL(location.href).searchParams.get('slug') ||
    decodeURIComponent(location.pathname.replace(/^\/posts?\//, '').replace(/\/$/, ''));
  if (!slug) return;
  try {
    const data = await fetchPublic<PublicArticle>('articles/' + encodeURIComponent(slug), signal);
    if (signal.aborted || !article.isConnected) return;
    const oldDate = parseDate(article.dataset.apiUpdated || '');
    const changed = !Number.isFinite(oldDate) || oldDate !== parseDate(data.updated_at);
    if (changed) {
      const { marked } = await import('marked');
      article.innerHTML = DOMPurify.sanitize(await marked.parse(data.body_markdown || ''));
      article.dataset.apiUpdated = data.updated_at;
    }
    article.dataset.apiSlug = data.slug;
    document.querySelectorAll('[data-replow-article-title], .cover-copy h1').forEach((element) => {
      element.textContent = data.title;
    });
    document.title = data.title + ' | ' + snapshot.site.name;
  } catch (error) {
    if (signal.aborted) return;
    if (String(error).includes('HTTP 404')) {
      article.innerHTML = '<p>这篇文章已撤回或不存在。<a href="/">返回主页</a></p>';
    } else if (!article.textContent?.trim()) {
      article.textContent = '暂时无法读取文章，请稍后刷新。';
    }
  }
}

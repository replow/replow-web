import { normalizeHexColor } from '@lib/utils';

export interface FriendCardData {
  id: string;
  name: string;
  websiteUrl: string;
  description: string;
  avatarUrl?: string | null;
  color?: string;
  latestArticleTitle?: string | null;
  latestArticleUrl?: string | null;
}

export function safeFriendUrl(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return '';
  try {
    const url = new URL(value.trim());
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : '';
  } catch {
    return '';
  }
}

export function normalizeFriendHostname(value: unknown): string {
  const url = safeFriendUrl(value);
  if (!url) return '';
  return new URL(url).hostname.toLowerCase().replace(/^www\./, '');
}

const escapeHtml = (value: unknown) =>
  String(value ?? '').replace(
    /[&<>"']/g,
    (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char] || char,
  );

function renderAvatar(value: unknown) {
  const url = safeFriendUrl(value);
  const image = url
    ? '<img data-friend-src="' +
      escapeHtml(url) +
      '" data-friend-avatar alt="" width="56" height="56" loading="lazy" decoding="async" hidden />' +
      '<noscript><img src="' +
      escapeHtml(url) +
      '" data-friend-avatar alt="" width="56" height="56" loading="lazy" decoding="async" /></noscript>'
    : '';
  return (
    '<span class="friend-avatar">' +
    image +
    '</span>'
  );
}

export function renderFriendCardMarkup(data: FriendCardData): string {
  const websiteUrl = safeFriendUrl(data.websiteUrl);
  if (!websiteUrl) return '';
  const hostname = new URL(websiteUrl).host;
  const color =
    data.color && /^#(?:[a-f\d]{3}|[a-f\d]{4}|[a-f\d]{6}|[a-f\d]{8})$/i.test(data.color)
      ? normalizeHexColor(data.color)
      : 'hsl(var(--primary))';
  const id = `friend-details-${data.id.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
  const name = escapeHtml(data.name);
  const description = escapeHtml(data.description);
  const avatar = renderAvatar(data.avatarUrl);
  const latestTitle = String(data.latestArticleTitle ?? '').trim();
  const latestUrl = safeFriendUrl(data.latestArticleUrl);
  const latest =
    latestTitle && latestUrl
      ? '<div class="friend-latest" data-friend-latest-block>' +
        '<span class="friend-latest-label">最新文章</span>' +
        '<a class="friend-latest-link" data-friend-latest href="' +
        escapeHtml(latestUrl) +
        '" target="_blank" rel="noopener noreferrer">' +
        escapeHtml(latestTitle) +
        '</a></div>'
      : '';

  return (
    '<article class="friend-card" data-friend-card data-friend-site-url="' +
    escapeHtml(websiteUrl) +
    '" style="--friend-color:' +
    escapeHtml(color) +
    '">' +
    '<button class="friend-card-summary" type="button" data-friend-summary aria-expanded="false" aria-controls="' +
    escapeHtml(id) +
    '" aria-label="打开 ' +
    name +
    ' 的网站">' +
    avatar +
    '<span class="friend-copy"><strong class="friend-name">' +
    name +
    '</strong><span class="friend-desc">' +
    description +
    '</span></span>' +
    '</button>' +
    '<div class="friend-card-details" id="' +
    escapeHtml(id) +
    '" data-friend-details aria-hidden="true">' +
    '<div class="friend-details-heading">' +
    renderAvatar(data.avatarUrl) +
    '<div class="friend-details-title"><strong class="friend-name">' +
    name +
    '</strong>' +
    '<a class="friend-site" data-friend-url href="' +
    escapeHtml(websiteUrl) +
    '" target="_blank" rel="noopener noreferrer">' +
    escapeHtml(hostname) +
    '</a></div></div>' +
    '<p class="friend-details-desc">' +
    description +
    '</p>' +
    '<div class="friend-status" data-friend-status data-status="loading" aria-live="polite">' +
    '<span class="friend-status-dot" aria-hidden="true"></span>' +
    '<span class="friend-status-label" data-friend-status-label>正在获取状态</span>' +
    '<span class="friend-status-latency" data-friend-latency></span></div>' +
    latest +
    '</div></article>'
  );
}

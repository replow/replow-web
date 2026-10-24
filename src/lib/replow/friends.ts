import DOMPurify from 'dompurify';
import snapshot from '@/data/replow.json';
import { fetchPublic } from './api';

type Friend = (typeof snapshot.friends)[number];
const escapeHtml = (value: unknown) =>
  String(value ?? '').replace(
    /[&<>"']/g,
    (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char] || char,
  );
const safeUrl = (value: string) => (/^https?:\/\//i.test(value) ? value : '');
const normalizeUrl = (value: string) => value.replace(/\/+$/, '');

function renderFriendCard(friend: Friend): string {
  return `
    <article class="friend-card">
      <a class="friend-main" href="${escapeHtml(safeUrl(friend.website_url))}" target="_blank" rel="noopener noreferrer">
        <span class="friend-avatar">
          <img src="${escapeHtml(safeUrl(friend.avatar_url) || snapshot.profile.avatar_url)}" alt="" width="56" height="56" loading="lazy" />
        </span>
        <span class="friend-copy">
          <span class="friend-heading"><strong class="friend-name">${escapeHtml(friend.name)}</strong></span>
          <span class="friend-desc">${escapeHtml(friend.description)}</span>
        </span>
        <span class="friend-arrow" aria-hidden="true">↗</span>
      </a>
      <a class="friend-latest" target="_blank" rel="noopener noreferrer" hidden>
        <svg class="friend-rss-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
          <path d="M4 11a9 9 0 0 1 9 9M4 4a16 16 0 0 1 16 16" />
          <circle cx="5" cy="19" r="1" fill="currentColor" />
        </svg>
        <span class="friend-latest-label">最新文章：</span>
        <span class="friend-latest-title" data-friend-latest-title></span>
        <span class="friend-latest-arrow" aria-hidden="true">↗</span>
      </a>
    </article>`;
}

function showLatestArticle(card: HTMLElement, friend: Friend | undefined) {
  const link = card.querySelector<HTMLAnchorElement>('.friend-latest');
  if (!link) return;
  const title = friend?.latest_article_title?.trim() ?? '';
  const url = safeUrl(friend?.latest_article_url ?? '');
  const visible = Boolean(title && url);
  link.hidden = !visible;
  if (visible) {
    link.href = url;
    link.title = `最新文章：${title}`;
  } else {
    link.removeAttribute('href');
    link.removeAttribute('title');
  }
  const titleElement = link.querySelector<HTMLElement>('[data-friend-latest-title]');
  if (titleElement) titleElement.textContent = visible ? title : '';
}

export async function refreshFriends(signal: AbortSignal) {
  const root = document.querySelector<HTMLElement>('[data-friends-grid]');
  if (!root) return;
  const result = await fetchPublic<{ items: Friend[] }>('friends', signal);
  if (!Array.isArray(result.items) || signal.aborted || !root.isConnected) return;
  const grid = root.querySelector<HTMLElement>('.friends-grid');
  if (!grid) return;
  const manifest = (items: Friend[]) =>
    JSON.stringify(
      items.map(({ name, website_url, description, avatar_url }) => ({ name, website_url, description, avatar_url })),
    );
  if (manifest(result.items) !== manifest(snapshot.friends)) {
    grid.innerHTML = DOMPurify.sanitize(result.items.map(renderFriendCard).join(''));
    root.querySelectorAll('[data-friends-filter] sup, .friends-section-rule small').forEach((element) => {
      element.textContent = String(result.items.length);
    });
  }
  for (const card of grid.querySelectorAll<HTMLElement>('.friend-card')) {
    const siteUrl = card.querySelector<HTMLAnchorElement>('.friend-main')?.href;
    const friend = result.items.find((item) => normalizeUrl(item.website_url) === normalizeUrl(siteUrl ?? ''));
    showLatestArticle(card, friend);
  }
}

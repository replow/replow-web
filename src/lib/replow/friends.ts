import DOMPurify from 'dompurify';
import snapshot from '@/data/replow.json';
import { fetchPublic } from './api';

type Friend = (typeof snapshot.friends)[number];
const escapeHtml = (value: unknown) =>
  String(value ?? '').replace(
    /[&<>"']/g,
    (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char] || char,
  );
const safeUrl = (value: string) => (/^https?:\/\//.test(value) ? value : '');
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
    grid.innerHTML = DOMPurify.sanitize(
      result.items
        .map(
          (friend) =>
            '<a class="friend-card" href="' +
            escapeHtml(safeUrl(friend.website_url)) +
            '" target="_blank" rel="noopener noreferrer"><span class="friend-avatar">' +
            '<img src="' +
            escapeHtml(safeUrl(friend.avatar_url) || snapshot.profile.avatar_url) +
            '" alt="" width="56" height="56" loading="lazy" /></span><span class="friend-copy">' +
            '<span class="friend-heading"><strong class="friend-name">' +
            escapeHtml(friend.name) +
            '</strong></span>' +
            '<span class="friend-desc">' +
            escapeHtml(friend.description) +
            '</span></span></a>',
        )
        .join(''),
    );
    root.querySelectorAll('[data-friends-filter] sup, .friends-section-rule small').forEach((element) => {
      element.textContent = String(result.items.length);
    });
  }
  for (const card of grid.querySelectorAll<HTMLAnchorElement>('.friend-card')) {
    const friend = result.items.find((item) => item.website_url.replace(/\/$/, '') === card.href.replace(/\/$/, ''));
    if (!friend?.latest_article_title || !safeUrl(friend.latest_article_url)) continue;
    card.title = '最新文章：' + friend.latest_article_title;
  }
}

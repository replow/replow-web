import DOMPurify from 'dompurify';
import snapshot from '@/data/replow.json';
import { fetchPublic } from './api';
import { normalizeFriendHostname, renderFriendCardMarkup, safeFriendUrl } from './friend-card';

type Friend = (typeof snapshot.friends)[number];

const manifest = (items: Friend[]) =>
  JSON.stringify(
    items.map(({ name, website_url, description, avatar_url }) => ({ name, website_url, description, avatar_url })),
  );

function updateLatestArticles(root: HTMLElement, items: Friend[]) {
  for (const card of root.querySelectorAll<HTMLElement>('[data-friend-card]')) {
    const host = normalizeFriendHostname(card.dataset.friendSiteUrl);
    const friend = items.find((item) => normalizeFriendHostname(item.website_url) === host);
    const title = friend?.latest_article_title?.trim() ?? '';
    const url = safeFriendUrl(friend?.latest_article_url);
    const details = card.querySelector<HTMLElement>('[data-friend-details]');
    const existing = details?.querySelector<HTMLElement>('[data-friend-latest-block]');

    if (!details || !title || !url) {
      existing?.remove();
      continue;
    }

    const block = existing ?? document.createElement('div');
    block.className = 'friend-latest';
    block.dataset.friendLatestBlock = '';
    let label = block.querySelector<HTMLElement>('.friend-latest-label');
    if (!label) {
      label = document.createElement('span');
      label.className = 'friend-latest-label';
      label.textContent = '最新文章';
      block.append(label);
    }

    let link = block.querySelector<HTMLAnchorElement>('[data-friend-latest]');
    if (!link) {
      link = document.createElement('a');
      link.className = 'friend-latest-link';
      link.dataset.friendLatest = '';
      link.target = '_blank';
      link.rel = 'noopener noreferrer';
      block.append(link);
    }
    link.href = url;
    link.textContent = title;
    if (!existing) details.append(block);
  }
}

export async function refreshFriends(signal: AbortSignal) {
  const root = document.querySelector<HTMLElement>('[data-friends-grid]');
  if (!root) return;
  const result = await fetchPublic<{ items: Friend[] }>('friends', signal);
  if (!Array.isArray(result.items) || signal.aborted || !root.isConnected) return;

  const grid = root.querySelector<HTMLElement>('.friends-grid');
  if (!grid) return;

  if (manifest(result.items) !== manifest(snapshot.friends)) {
    grid.innerHTML = DOMPurify.sanitize(
      result.items
        .map((friend, index) =>
          renderFriendCardMarkup({
            id: `api-${index}`,
            name: friend.name,
            websiteUrl: friend.website_url,
            description: friend.description,
            avatarUrl: friend.avatar_url || snapshot.profile.avatar_url,
            latestArticleTitle: friend.latest_article_title,
            latestArticleUrl: friend.latest_article_url,
          }),
        )
        .join(''),
    );
    root.querySelectorAll('[data-friends-filter] sup, .friends-section-rule small').forEach((element) => {
      element.textContent = String(result.items.length);
    });
    document.dispatchEvent(new Event('replow:friends-updated'));
  } else {
    updateLatestArticles(root, result.items);
  }
}

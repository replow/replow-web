import { readMotionLevel } from '@lib/motion-level';
import { normalizeFriendHostname, safeFriendUrl } from '@lib/replow/friend-card';

interface StatusMonitor {
  url?: string;
  status?: 'up' | 'down' | 'unknown';
  latencyMs?: number | null;
}

let dispose: (() => void) | undefined;
const statusApiUrl = 'https://status.4z.ink/api/status';

/**
 * Group tabs filter sections in place. Touch visitors get a two-step card interaction:
 * the first tap reveals the details, and the next tap opens the website.
 */
function init() {
  dispose?.();
  const grid = document.querySelector<HTMLElement>('[data-friends-grid]');
  if (!grid) return;

  const controller = new AbortController();
  const statusController = new AbortController();
  const statusTimeout = window.setTimeout(() => statusController.abort(), 10000);
  const touchMode = () => window.matchMedia('(hover: none), (pointer: coarse)').matches;
  const cards = () => [...grid.querySelectorAll<HTMLElement>('[data-friend-card]')];

  const setExpanded = (card: HTMLElement, expanded: boolean, pinned = false) => {
    const summary = card.querySelector<HTMLButtonElement>('[data-friend-summary]');
    const details = card.querySelector<HTMLElement>('[data-friend-details]');
    if (expanded) card.dataset.friendExpanded = 'true';
    else delete card.dataset.friendExpanded;
    if (pinned) card.dataset.friendPinned = 'true';
    else delete card.dataset.friendPinned;
    summary?.setAttribute('aria-expanded', String(expanded));
    details?.setAttribute('aria-hidden', String(!expanded));
  };

  const closeOtherCards = (except?: HTMLElement) => {
    for (const card of cards()) {
      if (card !== except) setExpanded(card, false);
    }
  };

  grid.addEventListener(
    'error',
    (event) => {
      if (event.target instanceof HTMLImageElement && event.target.hasAttribute('data-friend-avatar')) {
        event.target.hidden = true;
      }
    },
    { capture: true, signal: controller.signal },
  );
  for (const image of grid.querySelectorAll<HTMLImageElement>('[data-friend-avatar]')) {
    if (image.complete && image.naturalWidth === 0 && image.currentSrc) image.hidden = true;
  }

  for (const card of cards()) {
    card.addEventListener(
      'pointerenter',
      (event) => {
        if (!touchMode() && event.pointerType === 'mouse') setExpanded(card, true);
      },
      { signal: controller.signal },
    );
    card.addEventListener(
      'pointerleave',
      (event) => {
        if (!touchMode() && event.pointerType === 'mouse' && !card.matches(':focus-within')) {
          setExpanded(card, false);
        }
      },
      { signal: controller.signal },
    );
    card.addEventListener('focusin', () => setExpanded(card, true), { signal: controller.signal });
    card.addEventListener(
      'focusout',
      (event) => {
        if (event.relatedTarget instanceof Node && card.contains(event.relatedTarget)) return;
        window.requestAnimationFrame(() => {
          const hovered = !touchMode() && card.matches(':hover');
          if (!hovered && card.dataset.friendPinned !== 'true') setExpanded(card, false);
        });
      },
      { signal: controller.signal },
    );
  }

  const tabs = [...grid.querySelectorAll<HTMLButtonElement>('[data-friends-filter]')];
  const sections = [...grid.querySelectorAll<HTMLElement>('[data-friends-section]')];
  const select = (id: string) => {
    const filtered = id !== 'all';
    if (filtered) grid.dataset.friendsActive = id;
    else delete grid.dataset.friendsActive;
    for (const section of sections) section.hidden = filtered && section.dataset.friendsSection !== id;
    for (const tab of tabs) tab.setAttribute('aria-pressed', String(tab.dataset.friendsFilter === id));
    if (readMotionLevel() !== 'reduced') {
      for (const section of sections) {
        if (!section.hidden) section.animate({ opacity: [0, 1] }, { duration: 650, easing: 'cubic-bezier(0.25, 1, 0.5, 1)' });
      }
    }
  };
  grid.addEventListener(
    'click',
    (event) => {
      const target = event.target instanceof Element ? event.target : null;
      if (!target) return;
      const tab = target.closest<HTMLButtonElement>('[data-friends-filter]');
      if (tab?.dataset.friendsFilter) {
        select(tab.dataset.friendsFilter);
        return;
      }

      const card = target.closest<HTMLElement>('[data-friend-card]');
      if (!card || !grid.contains(card)) return;
      if (target.closest('a[data-friend-url], a[data-friend-latest]')) return;

      const summary = target.closest('[data-friend-summary]');
      const url = safeFriendUrl(card.dataset.friendSiteUrl);
      if (!url) return;

      if (touchMode()) {
        if (card.dataset.friendPinned !== 'true') {
          event.preventDefault();
          closeOtherCards(card);
          setExpanded(card, true, true);
          return;
        }
        event.preventDefault();
        window.open(url, '_blank', 'noopener,noreferrer');
        return;
      }

      if (summary) {
        event.preventDefault();
        window.open(url, '_blank', 'noopener,noreferrer');
      }
    },
    { signal: controller.signal },
  );
  document.addEventListener(
    'click',
    (event) => {
      const target = event.target instanceof Element ? event.target : null;
      if (target?.closest('[data-friend-card]')) return;
      for (const card of cards()) {
        if (card.dataset.friendPinned === 'true') setExpanded(card, false);
      }
    },
    { signal: controller.signal },
  );

  const selectHash = () => {
    let hash = window.location.hash.slice(1);
    try {
      hash = decodeURIComponent(hash);
    } catch {
      // Malformed escapes cannot identify a section; keep every link visible.
    }
    const linked = sections.find((section) => section.id === hash);
    select(linked?.dataset.friendsSection ?? 'all');
    linked?.scrollIntoView({ block: 'start', behavior: 'instant' });
  };
  window.addEventListener('hashchange', selectHash, { signal: controller.signal });
  selectHash();

  const pendingAvatars = [...grid.querySelectorAll<HTMLImageElement>('img[data-friend-src]')];
  const loadAvatar = (image: HTMLImageElement) => {
    const source = image.dataset.friendSrc;
    if (!source || controller.signal.aborted) return;
    image.hidden = false;
    image.src = source;
    delete image.dataset.friendSrc;
  };
  let avatarObserver: IntersectionObserver | undefined;
  if ('IntersectionObserver' in window) {
    avatarObserver = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const image = entry.target.querySelector<HTMLImageElement>('img[data-friend-src]');
          if (image) loadAvatar(image);
          avatarObserver?.unobserve(entry.target);
        }
      },
      { rootMargin: '160px' },
    );
    for (const image of pendingAvatars) {
      if (image.parentElement) avatarObserver.observe(image.parentElement);
    }
  } else {
    pendingAvatars.forEach(loadAvatar);
  }

  const setStatus = (card: HTMLElement, status: string, label: string, latency?: number | null) => {
    const statusNode = card.querySelector<HTMLElement>('[data-friend-status]');
    const labelNode = card.querySelector<HTMLElement>('[data-friend-status-label]');
    const latencyNode = card.querySelector<HTMLElement>('[data-friend-latency]');
    if (!statusNode || !labelNode || !latencyNode) return;
    statusNode.dataset.status = status;
    labelNode.textContent = label;
    latencyNode.textContent = typeof latency === 'number' && Number.isFinite(latency) ? `${latency} ms` : '';
  };

  const loadStatus = async () => {
    try {
      const response = await fetch(statusApiUrl, {
        cache: 'no-store',
        credentials: 'omit',
        signal: statusController.signal,
      });
      if (!response.ok) throw new Error(`Status API HTTP ${response.status}`);
      const data = (await response.json()) as { monitors?: StatusMonitor[] };
      if (!Array.isArray(data.monitors)) throw new Error('Invalid status response');
      for (const card of cards()) {
        const host = normalizeFriendHostname(card.dataset.friendSiteUrl);
        const monitor = data.monitors.find((item) => normalizeFriendHostname(item.url) === host);
        if (!monitor) {
          setStatus(card, 'unknown', '暂无状态数据');
        } else if (monitor.status === 'up') {
          setStatus(card, 'up', '运行正常', monitor.latencyMs);
        } else if (monitor.status === 'down') {
          setStatus(card, 'down', '访问异常', monitor.latencyMs);
        } else {
          setStatus(card, 'unknown', '状态未知', monitor.latencyMs);
        }
      }
    } catch {
      if (!statusController.signal.aborted) {
        for (const card of cards()) setStatus(card, 'unknown', '暂时无法获取状态');
      }
    }
  };
  void loadStatus();

  dispose = () => {
    controller.abort();
    statusController.abort();
    window.clearTimeout(statusTimeout);
    avatarObserver?.disconnect();
  };
}

if (document.readyState !== 'loading') init();
document.addEventListener('astro:page-load', init);
document.addEventListener('replow:friends-updated', init);
document.addEventListener('astro:before-swap', () => {
  dispose?.();
  dispose = undefined;
});

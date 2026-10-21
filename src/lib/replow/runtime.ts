import snapshot from '@/data/replow.json';
import { fetchPublic } from './api';
import { refreshArticleBody, refreshArticleList } from './articles';
import { refreshFriends } from './friends';
import { applySite, type PublicSite, updateUptime } from './site';

let started = false;
export function startReplowRuntime() {
  if (started) return;
  started = true;
  let controller: AbortController;
  let idleTimer: ReturnType<typeof setTimeout>;
  let idleDelay = Number(snapshot.firefly.koharuConfig.headerIdleMs || 400);
  let previousY = scrollY;
  function setHeader(hidden: boolean) {
    document.querySelectorAll<HTMLElement>('#site-header, #mobile-menu-container').forEach((element) => {
      element.classList.remove('-translate-y-full');
      element.classList.toggle('replow-scrolling', hidden);
    });
  }
  function observeScroll() {
    const y = window.scrollY;
    if (y === previousY) return;
    previousY = y;
    clearTimeout(idleTimer);
    const header = document.getElementById('site-header');
    header?.classList.toggle('with-background', y > innerHeight * 0.45);
    setHeader(y > 5);
    idleTimer = setTimeout(() => setHeader(false), idleDelay);
  }
  document.addEventListener('scroll', observeScroll, { capture: true, passive: true });
  window.addEventListener('scroll', observeScroll, { passive: true });
  // Older Chromium can postpone root scroll events while the animated cover repaints.
  // The position guard keeps the visible-page fallback cheap and prevents duplicate timers.
  setInterval(() => {
    if (document.visibilityState === 'visible') observeScroll();
  }, 50);
  async function refresh() {
    controller?.abort();
    controller = new AbortController();
    const signal = controller.signal;
    applySite(snapshot);
    const work: Promise<unknown>[] = [
      fetchPublic<PublicSite>('site', signal).then((site) => {
        if (!signal.aborted) {
          applySite(site);
          idleDelay = Math.min(2000, Math.max(100, Number(site.firefly.koharuConfig?.headerIdleMs || 400)));
        }
      }),
      refreshArticleBody(signal),
      refreshFriends(signal),
    ];
    if (snapshot.firefly.koharuConfig.runtimeArticles !== false) work.push(refreshArticleList(signal));
    await Promise.allSettled(work);
  }
  function init() {
    void refresh();
  }
  if (document.readyState !== 'loading') init();
  else document.addEventListener('DOMContentLoaded', init, { once: true });
  document.addEventListener('astro:page-load', init);
  document.addEventListener('astro:before-swap', () => {
    controller?.abort();
    clearTimeout(idleTimer);
  });
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') init();
  });
  setInterval(updateUptime, 1000);
  setInterval(() => {
    if (document.visibilityState === 'visible') init();
  }, 60_000);
}

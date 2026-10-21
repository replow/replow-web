import { normalizeDynamics } from './data';

let cleanup: (() => void) | undefined;
export function startRecentDynamics() {
  cleanup?.();
  const roots = [...document.querySelectorAll<HTMLElement>('[data-recent-dynamics]')];
  if (!roots.length) return;
  const controller = new AbortController(),
    signal = controller.signal;
  let busy = false;
  async function load() {
    if (busy) return;
    busy = true;
    try {
      const response = await fetch('/v1/public/dynamics?limit=2', { cache: 'no-store', signal });
      if (!response.ok) return;
      const payload = (await response.json()) as { items?: unknown };
      const items = normalizeDynamics(payload.items);
      for (const root of roots) {
        root.replaceChildren();
        for (const item of items) {
          const link = document.createElement('a');
          link.className = 'sidebar-dynamic';
          link.href = '/dynamic/';
          const summary = document.createElement('span');
          summary.textContent =
            item.content
              .replace(/<[^>]*>/g, '')
              .replace(/[#*_~]/g, '')
              .slice(0, 90) || '图片动态';
          const time = document.createElement('time');
          time.dateTime = new Date(item.published).toISOString();
          time.textContent = new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', dateStyle: 'medium' }).format(
            item.published,
          );
          link.append(summary, time);
          root.append(link);
        }
        if (!items.length) {
          const link = document.createElement('a');
          link.className = 'sidebar-dynamic';
          link.href = '/dynamic/';
          link.textContent = '还没有公开动态';
          root.append(link);
        }
      }
    } catch {
      /* Keep the direct dynamic-page link available when the network is unavailable. */
    } finally {
      busy = false;
    }
  }
  document.addEventListener(
    'visibilitychange',
    () => {
      if (document.visibilityState === 'visible') void load();
    },
    { signal },
  );
  document.addEventListener('replow:dynamics-updated', () => void load(), { signal });
  cleanup = () => controller.abort();
  void load();
}
export function stopRecentDynamics() {
  cleanup?.();
  cleanup = undefined;
}

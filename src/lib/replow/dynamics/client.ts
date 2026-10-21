import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { type DynamicItem, normalizeDynamics } from './data';

let cleanup: (() => void) | undefined;
function node<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = '') {
  const result = document.createElement(tag);
  result.className = className;
  result.textContent = text;
  return result;
}
export function startDynamics() {
  cleanup?.();
  const root = document.querySelector<HTMLElement>('[data-dynamics]');
  if (!root) return;
  const list = root.querySelector<HTMLElement>('[data-dynamic-list]');
  const status = root.querySelector<HTMLElement>('[data-dynamic-status]');
  const refresh = root.querySelector<HTMLButtonElement>('[data-dynamic-refresh]');
  const more = root.querySelector<HTMLButtonElement>('[data-dynamic-more]');
  if (!list || !status || !refresh || !more) return;
  const controller = new AbortController(),
    signal = controller.signal;
  let items: DynamicItem[] = [],
    offset = 0,
    total = 0,
    busy = false;
  const date = new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Shanghai' });
  function draw() {
    if (!list) return;
    list.replaceChildren();
    for (const item of items) {
      const card = node('article', 'dynamic-entry');
      card.dataset.dynamicId = String(item.id);
      const meta = node('header', 'dynamic-meta'),
        time = node('time', '', date.format(item.published));
      time.dateTime = new Date(item.published).toISOString();
      meta.append(time);
      if (item.pinned) meta.append(node('span', 'dynamic-pinned', '置顶'));
      if (item.location) meta.append(node('span', 'dynamic-location', item.location));
      const body = node('div', 'dynamic-body prose dark:prose-invert');
      body.innerHTML = DOMPurify.sanitize(marked.parse(item.content, { async: false, breaks: true }), {
        ALLOWED_TAGS: [
          'p',
          'br',
          'strong',
          'em',
          'del',
          'a',
          'code',
          'pre',
          'blockquote',
          'ul',
          'ol',
          'li',
          'hr',
          'h1',
          'h2',
          'h3',
          'h4',
          'h5',
          'h6',
          'table',
          'thead',
          'tbody',
          'tr',
          'th',
          'td',
          'img',
        ],
        ALLOWED_ATTR: ['href', 'title', 'src', 'alt'],
        ALLOWED_URI_REGEXP: /^(?:https?:|mailto:|\/(?!\/)|#)/i,
      });
      for (const link of body.querySelectorAll('a')) {
        link.target = '_blank';
        link.rel = 'noopener noreferrer';
      }
      for (const image of body.querySelectorAll('img')) image.loading = 'lazy';
      card.append(meta, body);
      if (item.images.length) {
        const grid = node('div', 'dynamic-images');
        for (const image of item.images) {
          const link = node('a');
          link.href = image.src;
          link.target = '_blank';
          link.rel = 'noopener noreferrer';
          link.setAttribute('aria-label', image.alt || '查看原图');
          const img = node('img');
          img.src = image.src;
          img.alt = image.alt;
          img.loading = 'lazy';
          link.append(img);
          grid.append(link);
        }
        card.append(grid);
      }
      list.append(card);
    }
    if (!items.length) list.append(node('p', 'dynamic-empty', '暂时没有公开动态，新的灵感很快就会出现。'));
  }
  async function load(append = false) {
    if (busy || !status || !refresh || !more) return;
    busy = true;
    refresh.disabled = true;
    more.disabled = true;
    status.textContent = '正在读取动态……';
    try {
      const response = await fetch('/v1/public/dynamics?limit=20&offset=' + (append ? offset : 0), {
        cache: 'no-store',
        headers: { Accept: 'application/json' },
        signal,
      });
      if (!response.ok) throw new Error('动态暂时无法读取，请稍后重试。');
      const payload = (await response.json()) as { items?: unknown; total?: unknown };
      if (!Array.isArray(payload.items) || !Number.isInteger(payload.total) || Number(payload.total) < 0)
        throw new Error('动态数据暂时不可用，请稍后重试。');
      const next = normalizeDynamics(payload.items);
      items = append ? [...items, ...next.filter((item) => !items.some((old) => old.id === item.id))] : next;
      offset = (append ? offset : 0) + payload.items.length;
      total = Number(payload.total);
      draw();
      document.dispatchEvent(new Event('replow:dynamics-updated'));
      more.hidden = offset >= total;
      status.textContent = total ? '共 ' + total + ' 条公开动态' : '';
    } catch (error) {
      if (!signal.aborted) status.textContent = error instanceof Error ? error.message : '动态加载失败，请重试。';
    } finally {
      busy = false;
      refresh.disabled = false;
      more.disabled = false;
    }
  }
  refresh.addEventListener('click', () => void load(), { signal });
  more.addEventListener('click', () => void load(true), { signal });
  document.addEventListener(
    'visibilitychange',
    () => {
      if (document.visibilityState === 'visible' && offset <= 20) void load();
    },
    { signal },
  );
  cleanup = () => controller.abort();
  void load();
}
export function stopDynamics() {
  cleanup?.();
  cleanup = undefined;
}

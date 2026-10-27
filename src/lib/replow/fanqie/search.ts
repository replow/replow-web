import type { FqClient } from './api';
import type { Book } from './types';
import { bookCard, button, cover, el, statusLine } from './view';

interface SearchOptions {
  root: HTMLElement;
  client: FqClient;
  initialQuery: string;
  knownBooks: Map<string, Book>;
  onQuery: (query: string) => void;
  onSelect: (id: string) => void;
  onError: (error: unknown) => void;
  actionLabel?: string;
  submitLabel?: string;
}

/** Foreground text has priority; only one following page is warmed at a time. */
export function mountSearch({
  root,
  client,
  initialQuery,
  knownBooks,
  onQuery,
  onSelect,
  onError,
  actionLabel = '选择章节与格式',
  submitLabel = '搜索 / 前往下载',
}: SearchOptions) {
  let page = 1;
  let query = initialQuery;
  let revision = 0;
  let closed = false;
  let queryController = new AbortController();
  let coverController = new AbortController();
  let coverObserver: IntersectionObserver | null = null;
  let prefetchTimer = 0;
  const form = el('form', 'fq-search-form');
  const label = el('label', '', '书名、作者或书籍 ID');
  label.htmlFor = 'fq-query';
  const input = el('input');
  input.id = 'fq-query';
  input.placeholder = '搜索喜欢的故事，或粘贴书籍 ID';
  input.required = true;
  input.maxLength = 100;
  input.value = initialQuery;
  const submit = el('button', 'fq-button', submitLabel);
  submit.type = 'submit';
  const row = el('div', 'fq-search-row');
  row.append(input, submit);
  form.append(label, row);
  const welcome = el('div', 'fq-welcome');
  welcome.append(
    el('span', 'fq-welcome-mark', '阅'),
    el('h3', '', '下一段故事，从这里开始'),
    el('p', 'fq-muted', '搜索书名或作者，也可以直接粘贴书籍 ID。'),
  );
  const results = el('div', 'fq-results');
  results.setAttribute('aria-live', 'polite');
  const navigation = el('div', 'fq-pagination');
  root.replaceChildren(
    form,
    el('p', 'fq-muted', '每页 10 本 · 书名与作者优先显示，封面逐步加载'),
    welcome,
    results,
    navigation,
  );

  async function search(scroll = false) {
    const ticket = ++revision;
    const startedAt = performance.now();
    const term = query;
    const requestedPage = page;
    coverController.abort();
    coverObserver?.disconnect();
    coverObserver = null;
    coverController = new AbortController();
    const coverSignal = coverController.signal;
    const querySignal = queryController.signal;
    const current = () => !closed && ticket === revision && !querySignal.aborted && !coverSignal.aborted;
    window.clearTimeout(prefetchTimer);
    welcome.hidden = true;
    results.setAttribute('aria-busy', 'true');
    for (const node of navigation.querySelectorAll('button')) node.disabled = true;
    statusLine(root, '正在寻找这本书…');
    const slowTimer = window.setTimeout(() => {
      if (current()) statusLine(root, '搜索仍在进行，正在等待小说服务响应…');
    }, 3000);
    try {
      const data = await client.search(term, requestedPage, { signal: querySignal });
      if (!current()) return;
      results.replaceChildren();
      navigation.replaceChildren();
      const cards: { book: Book; card: HTMLElement }[] = [];
      for (const book of data.books) {
        knownBooks.set(book.id, book);
        const { card, info } = bookCard(book);
        const choose = button(actionLabel, () => onSelect(book.id));
        choose.setAttribute('aria-label', `${actionLabel}《${book.title}》`);
        info.append(choose);
        results.append(card);
        cards.push({ book, card });
      }
      statusLine(
        root,
        data.books.length
          ? `第 ${requestedPage} 页 · ${data.books.length} 本小说 · 查询耗时 ${((performance.now() - startedAt) / 1000).toFixed(1)} 秒 · 封面按需加载`
          : '没有找到这本书，试试其他书名或直接输入书籍 ID。',
      );
      const turn = (next: number) => {
        page = next;
        void search(true);
      };
      if (requestedPage > 1) navigation.append(button('上一页', () => turn(requestedPage - 1), true));
      navigation.append(el('span', 'fq-muted', `第 ${requestedPage} 页`));
      if (data.hasMore) navigation.append(button('下一页', () => turn(requestedPage + 1), true));
      if (scroll) results.scrollIntoView({ block: 'start', behavior: 'auto' });

      // Only fetch missing covers near the viewport, two at a time. On mobile,
      // eager cover requests used to contend with foreground book/API requests.
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          if (!current()) return;
          const queue: typeof cards = [];
          let running = 0;
          const pump = () => {
            while (current() && running < 2 && queue.length) {
              const { book, card } = queue.shift()!;
              running++;
              void client
                .cover(book.id, { signal: coverSignal })
                .then((url) => {
                  if (!current()) return;
                  book.cover = url;
                  if (url) card.querySelector('.fq-cover')?.replaceWith(cover(url, book.title));
                })
                .catch(() => {
                  /* Missing artwork must never hide a book. */
                })
                .finally(() => {
                  running--;
                  pump();
                });
            }
          };
          const missing = cards.filter(({ book }) => !book.cover && book.coverPending);
          if ('IntersectionObserver' in window) {
            const candidates = new Map(missing.map(({ book, card }) => [card, book]));
            coverObserver = new IntersectionObserver(
              (entries, observer) => {
                for (const entry of entries) {
                  if (!entry.isIntersecting || !current()) continue;
                  const card = entry.target as HTMLElement;
                  const book = candidates.get(card);
                  observer.unobserve(card);
                  candidates.delete(card);
                  if (book) queue.push({ book, card });
                }
                pump();
              },
              { rootMargin: '180px 0px' },
            );
            for (const { card } of missing) coverObserver.observe(card);
          } else {
            queue.push(...missing);
            pump();
          }
          if (!data.hasMore || (navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData) return;
          prefetchTimer = window.setTimeout(() => {
            void (async () => {
              if (!current() || document.hidden) return;
              try {
                // Warm only the next page's text; its artwork waits until viewed.
                await client.search(term, requestedPage + 1, { signal: querySignal, priority: 'low' });
              } catch {
                /* Foreground navigation can retry a failed prefetch. */
              }
            })();
          }, 700);
        }),
      );
    } catch (error) {
      if (current()) onError(error);
    } finally {
      window.clearTimeout(slowTimer);
      if (current()) {
        results.removeAttribute('aria-busy');
        for (const node of navigation.querySelectorAll('button')) node.disabled = false;
      }
    }
  }
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const term = input.value.trim();
    if (!term) return;
    if (/^[0-9]{1,24}$/.test(term)) return onSelect(term);
    queryController.abort();
    queryController = new AbortController();
    query = term;
    onQuery(term);
    page = 1;
    void search();
  });
  if (query) void search();
  return () => {
    closed = true;
    revision++;
    window.clearTimeout(prefetchTimer);
    queryController.abort();
    coverController.abort();
    coverObserver?.disconnect();
  };
}

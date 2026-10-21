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
    const term = query;
    const requestedPage = page;
    coverController.abort();
    coverController = new AbortController();
    const coverSignal = coverController.signal;
    const querySignal = queryController.signal;
    const current = () => !closed && ticket === revision && !querySignal.aborted && !coverSignal.aborted;
    window.clearTimeout(prefetchTimer);
    welcome.hidden = true;
    results.setAttribute('aria-busy', 'true');
    for (const node of navigation.querySelectorAll('button')) node.disabled = true;
    statusLine(root, '正在寻找这本书…');
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
          ? `第 ${requestedPage} 页 · ${data.books.length} 本小说 · 每页 10 本，封面逐步加载`
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

      // Let all text cards paint before starting any cover processing.
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          if (!current()) return;
          let index = 0;
          async function loadVisible() {
            while (current() && index < cards.length) {
              const { book, card } = cards[index++];
              if (book.cover || !book.coverPending) continue;
              try {
                const url = await client.cover(book.id, { signal: coverSignal });
                if (!current()) return;
                book.cover = url;
                if (url) card.querySelector('.fq-cover')?.replaceWith(cover(url, book.title));
              } catch {
                /* A missing cover must never hide the title or actions. */
              }
            }
          }
          const visibleCovers = Promise.all([loadVisible(), loadVisible()]);
          if (!data.hasMore || (navigator as Navigator & { connection?: { saveData?: boolean } }).connection?.saveData) return;
          prefetchTimer = window.setTimeout(() => {
            void (async () => {
              if (!current() || document.hidden) return;
              try {
                const next = await client.search(term, requestedPage + 1, { signal: querySignal, priority: 'low' });
                await visibleCovers;
                // Warm following-page covers one at a time after visible covers.
                for (const book of next.books) {
                  if (!current() || document.hidden) return;
                  if (book.cover || !book.coverPending) continue;
                  try {
                    const url = await client.cover(book.id, { signal: coverSignal, priority: 'low' });
                    if (!current()) return;
                    book.cover = url;
                  } catch {
                    /* Background work is best effort and has no UI errors. */
                  }
                }
              } catch {
                /* Foreground navigation can retry a failed prefetch. */
              }
            })();
          }, 350);
        }),
      );
    } catch (error) {
      if (current()) onError(error);
    } finally {
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
  };
}

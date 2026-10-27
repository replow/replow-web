import { createFqClient, errorMessage, LoginRequired } from '../fanqie/api';
import { mountSearch } from '../fanqie/search';
import type { Book } from '../fanqie/types';
import { bookCard, button, el, link, statusLine } from '../fanqie/view';
import { chapterCounts } from './chapter-progress';
import { prepareBook } from './download';
import { inspectEpub } from './epub';
import { waitForReading } from './loading';
import {
  localFile,
  localProgress,
  localReadingStats,
  localShelf,
  removeLocalBook,
  saveFile,
  saveProgress,
  saveShelf,
} from './storage';
import type { LocalFile, Progress, ShelfBook } from './types';
import './style.css';

const active = new Map<HTMLElement, () => void>();
function mount(root: HTMLElement) {
  active.get(root)?.();
  const controller = new AbortController();
  const client = createFqClient(controller.signal);
  let uid = 0,
    books: ShelfBook[] = [],
    stopSearch = () => {},
    closeReader = () => {};
  let preparing: AbortController | undefined;
  let view: 'shelf' | 'search' = 'shelf';
  const knownBooks = new Map<string, Book>();
  let query = '',
    revision = 0;
  let identity = (window as Window & { __replowAuthSession?: { username: string } }).__replowAuthSession?.username || '';
  const stop = () => {
    controller.abort();
    preparing?.abort();
    stopSearch();
    closeReader();
    active.delete(root);
  };
  active.set(root, stop);
  function fail(error: unknown) {
    if (controller.signal.aborted) return;
    if (error instanceof LoginRequired) {
      const box = el('div', 'reading-welcome');
      box.append(
        el('span', 'reading-monogram', '阅'),
        el('h3', '', '登录，打开你的私人书架'),
        el('p', '', '使用主站账号管理书架、同步进度。EPUB 文件保存在当前浏览器。'),
        link('登录账号', `https://account.replow.org/?return_to=${encodeURIComponent(location.href)}`),
      );
      root.replaceChildren(box);
    } else statusLine(root, errorMessage(error), true);
  }
  async function run(action: () => Promise<void>) {
    try {
      await action();
    } catch (error) {
      fail(error);
    }
  }
  const toolbar = el('div', 'reading-actions');
  const content = el('div', 'reading-content');
  const fileInput = el('input');
  fileInput.type = 'file';
  fileInput.accept = '.epub,application/epub+zip';
  fileInput.hidden = true;
  fileInput.setAttribute('aria-label', '导入 EPUB 文件');
  const shelfButton = button('我的书架', () => {
    void run(showShelf);
  });
  const searchButton = button('搜索番茄', () => showSearch(), true);
  toolbar.append(
    shelfButton,
    searchButton,
    button('导入 EPUB', () => fileInput.click(), true),
    fileInput,
  );
  async function refresh() {
    const data = await client.request<{ uid: number; items: ShelfBook[] }>('/reading/shelf');
    controller.signal.throwIfAborted();
    uid = data.uid;
    books = data.items;
    await saveShelf(uid, books);
  }
  function setTab(next: 'shelf' | 'search') {
    view = next;
    revision++;
    stopSearch();
    stopSearch = () => {};
    shelfButton.classList.toggle('fq-secondary', next !== 'shelf');
    searchButton.classList.toggle('fq-secondary', next !== 'search');
    root.replaceChildren(toolbar, content);
  }
  function chapterText(item: ShelfBook, cached?: LocalFile) {
    const { read, total } = chapterCounts(item, cached);
    if (!total) return item.source === 'local' && !cached ? '重新导入后显示章节总数' : '正在统计章节…';
    return `已读 ${read} 章 / 共 ${total} 章`;
  }
  async function showShelf() {
    setTab('shelf');
    const ticket = revision;
    content.replaceChildren(el('p', 'fq-muted', '正在读取本机书籍…'));
    const [availability, progressValues, readingTimes] = await Promise.all([
      Promise.all(books.map((b) => localFile(uid, b.id))),
      Promise.all(books.map((b) => localProgress(uid, b.id))),
      Promise.all(books.map((b) => localReadingStats(uid, b.id))),
    ]);
    const conflicts = new Map<string, { local: Progress; remote: Progress; localNewer: boolean }>();
    books.forEach((item, index) => {
      const local = progressValues[index];
      if (local?.cfi && item.cfi && local.cfi !== item.cfi) {
        conflicts.set(item.id, {
          local,
          remote: {
            cfi: item.cfi,
            chapter: item.chapter,
            percentage: item.percentage,
            read_chapters: item.read_chapters,
            total_chapters: item.total_chapters,
            updated: item.updated_at * 1000,
          },
          localNewer: local.updated > item.updated_at * 1000,
        });
      }
      if (local && local.updated > item.updated_at * 1000) Object.assign(item, local, { updated_at: local.updated / 1000 });
    });
    if (ticket !== revision || controller.signal.aborted) return;
    const header = el('div', 'reading-shelf-heading');
    header.append(
      el('h3', '', '我的书架'),
      el('span', 'fq-muted', `${books.length} 本故事 · ${availability.filter(Boolean).length} 本已存本机`),
    );
    const list = el('div', 'reading-shelf');
    const pendingCounts: Array<{ item: ShelfBook; cached?: LocalFile; node: HTMLElement }> = [];
    books.forEach((item, index) => {
      const cached = availability[index];
      const book: Book = {
        id: item.source_id,
        title: item.title,
        author: item.author,
        cover: item.cover,
        total: 0,
        description: item.description,
      };
      const { card, info } = bookCard(book);
      card.classList.add('reading-book');
      info.append(
        el(
          'span',
          'reading-book-state',
          cached ? '已存本机 · EPUB' : item.source === 'fanqie' ? '番茄小说 · 尚未保存' : '本地导入 · 此设备需重新导入',
        ),
      );
      if (item.description) {
        const description = el('p', 'reading-description', item.description);
        info.append(description);
      }
      const chapterCount = el('p', 'reading-chapter-count', chapterText(item, cached));
      info.append(chapterCount);
      const minutes = Math.floor((readingTimes[index]?.seconds || 0) / 60);
      if (minutes) info.append(el('p', 'reading-time', `本设备累计阅读 ${minutes} 分钟`));
      if (!item.total_chapters) pendingCounts.push({ item, cached, node: chapterCount });
      const progress = el('progress');
      progress.max = 100;
      progress.value = item.percentage;
      progress.setAttribute('aria-label', `《${item.title}》阅读进度`);
      info.append(
        progress,
        el(
          'small',
          'fq-muted',
          item.chapter ? `${item.chapter} · 约 ${item.percentage.toFixed(1)}%` : '还未开始，故事正等着你',
        ),
      );
      const conflict = conflicts.get(item.id);
      if (conflict) {
        const note = el(
          'p',
          'reading-sync-conflict',
          `本机和云端的阅读位置不同，已优先使用${conflict.localNewer ? '本机' : '云端'}较新的进度。`,
        );
        const choose = button(
          conflict.localNewer ? '改用云端进度' : '恢复本机进度',
          () => {
            void run(async () => {
              const selected = conflict.localNewer ? conflict.remote : conflict.local;
              await saveProgress(uid, item.id, { ...selected, updated: Date.now() });
              await showShelf();
            });
          },
          true,
        );
        note.append(' ', choose);
        info.append(note);
      }
      const actions = el('div', 'reading-book-actions');
      const continueButton = button(
        cached ? '继续阅读' : item.source === 'fanqie' ? '保存到本机并阅读' : '重新导入 EPUB',
        () => {
          if (item.source === 'local' && !cached) {
            fileInput.click();
            return;
          }
          void run(() => read(item));
        },
      );
      continueButton.classList.add('reading-read-button');
      continueButton.setAttribute('aria-label', continueButton.textContent || '继续阅读');
      actions.append(continueButton);
      if (item.source === 'fanqie') {
        actions.append(
          button(
            '检查目录更新',
            () => {
              void run(async () => {
                const result = await client.request<{ total_chapters: number }>(`/books/${item.source_id}/toc`);
                const latest = Number(result.total_chapters || 0);
                if (!latest) throw new Error('暂时无法获取最新目录，请稍后再试。');
                const added = Math.max(0, latest - (item.total_chapters || 0));
                if (latest !== item.total_chapters) {
                  item.total_chapters = latest;
                  await client.request(`/reading/shelf/${item.id}/progress`, { total_chapters: latest });
                  await saveShelf(uid, books);
                }
                statusLine(root, added ? `发现 ${added} 个新目录条目，下次保存 EPUB 时可更新。` : '目录已是最新。');
                chapterCount.textContent = chapterText(item, cached);
              });
            },
            true,
          ),
        );
      }
      if (cached)
        actions.append(
          button(
            '导出 EPUB',
            () => {
              void run(async () => {
                const stored = await localFile(uid, item.id);
                if (!stored) throw new Error('本地文件已被清理，请重新保存。');
                const url = URL.createObjectURL(stored.blob);
                const anchor = el('a');
                anchor.href = url;
                anchor.download = `${item.title}.epub`;
                anchor.click();
                window.setTimeout(() => URL.revokeObjectURL(url), 30000);
              });
            },
            true,
          ),
        );
      actions.append(
        button(
          '移出书架',
          () => {
            void run(async () => {
              if (!window.confirm(`将《${item.title}》移出书架并删除本机副本？`)) return;
              await client.request(`/reading/shelf/${item.id}/remove`, {});
              await removeLocalBook(uid, item.id);
              books = books.filter((x) => x.id !== item.id);
              await saveShelf(uid, books);
              await showShelf();
            });
          },
          true,
        ),
      );
      info.append(actions);
      list.append(card);
    });
    if (!books.length) {
      const empty = el('div', 'reading-welcome');
      empty.append(
        el('span', 'reading-monogram', '阅'),
        el('h3', '', '给好故事，留一个位置'),
        el('p', '', '搜索番茄小说加入书架，或导入你自己的 EPUB。'),
        button('去找一本书', showSearch),
      );
      content.replaceChildren(header, empty);
    } else content.replaceChildren(header, list);
    // Backfill old metadata in sequence so opening a shelf never unzips many books at once.
    void (async () => {
      for (const entry of pendingCounts) {
        if (ticket !== revision || controller.signal.aborted) return;
        const { item, cached, node } = entry;
        try {
          let total = cached?.chapters || 0;
          if (!total && cached) {
            const metadata = await inspectEpub(cached.blob);
            total = metadata.chapters;
            cached.chapters = total;
            cached.chapterIndices = metadata.chapterIndices;
            await saveFile(uid, item.id, cached);
          }
          if (!total && item.source === 'fanqie') {
            const toc = await client.request<{ total_chapters: number }>(`/books/${item.source_id}/toc`);
            total = toc.total_chapters;
          }
          if (!total || ticket !== revision || controller.signal.aborted) continue;
          item.total_chapters = total;
          const text = chapterText(item, cached);
          item.read_chapters = chapterCounts(item, cached).read;
          node.textContent = text;
          await saveShelf(uid, books);
          await client.request(`/reading/shelf/${item.id}/progress`, {
            total_chapters: total,
          });
        } catch {
          if (node.isConnected && !item.total_chapters) node.textContent = '章节数暂未获取，打开阅读后自动更新';
        }
      }
    })();
  }
  async function addFanqie(id: string) {
    statusLine(root, '正在加入书架…');
    const detail = await client.book(id);
    const item = await client.request<ShelfBook>('/reading/shelf', {
      source: 'fanqie',
      source_id: id,
      title: detail.title.slice(0, 300),
      author: detail.author.slice(0, 200),
      cover: detail.cover,
      description: detail.description.slice(0, 10000),
      total_chapters: detail.total || 0,
    });
    controller.signal.throwIfAborted();
    if (!books.some((x) => x.id === item.id)) books.unshift(item);
    await saveShelf(uid, books);
    await showShelf();
    statusLine(root, '已加入书架。点击“保存到本机并阅读”，即可在浏览器内生成 EPUB。');
  }
  function showSearch() {
    setTab('search');
    stopSearch = mountSearch({
      root: content,
      client,
      initialQuery: query,
      knownBooks,
      onQuery: (term) => {
        query = term;
      },
      onSelect: (id) => {
        void run(() => addFanqie(id));
      },
      onError: fail,
      actionLabel: '加入我的书架',
      submitLabel: '搜索书籍',
    });
  }
  async function read(item: ShelfBook) {
    if (preparing) throw new Error('已有书籍正在准备，请先完成或取消。');
    const localController = new AbortController();
    preparing = localController;
    for (const node of root.querySelectorAll('button')) node.disabled = true;
    controller.signal.addEventListener('abort', () => localController.abort(), { once: true });
    const box = el('section', 'reading-preparing');
    const message = el('p', '', '正在打开本机 EPUB…');
    message.setAttribute('role', 'status');
    box.append(
      message,
      button('取消，保留已获取章节', () => localController.abort(), true),
    );
    toolbar.after(box);
    try {
      const blob = await prepareBook(uid, item, client, localController.signal, (text) => {
        message.textContent = text;
      });
      localController.signal.throwIfAborted();
      const { openReader } = await waitForReading(import('./reader'), localController.signal, '加载阅读器');
      const readerController = new AbortController();
      localController.signal.addEventListener('abort', () => readerController.abort(), { once: true });
      controller.signal.addEventListener('abort', () => readerController.abort(), { once: true });
      closeReader = () => readerController.abort();
      await openReader(uid, item, blob, client, readerController.signal, () => {
        if (!controller.signal.aborted) void run(showShelf);
      });
    } catch (error) {
      if (!localController.signal.aborted) {
        localController.abort();
        throw error;
      }
      if (!controller.signal.aborted) statusLine(root, '已取消，已保存的章节留在本机，下次可继续。');
    } finally {
      preparing = undefined;
      for (const node of root.querySelectorAll('button')) node.disabled = false;
      box.remove();
    }
  }
  fileInput.addEventListener('change', () => {
    void run(async () => {
      const file = fileInput.files?.[0];
      fileInput.value = '';
      if (!file) return;
      statusLine(root, '正在本地解析 EPUB，文件不会上传…');
      const info = await inspectEpub(file);
      controller.signal.throwIfAborted();
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', info.buffer)), (x) =>
        x.toString(16).padStart(2, '0'),
      ).join('');
      const item = await client.request<ShelfBook>('/reading/shelf', {
        source: 'local',
        source_id: hash,
        title: info.title.slice(0, 300),
        author: info.author.slice(0, 200),
        total_chapters: info.chapters,
      });
      await saveFile(uid, item.id, {
        blob: file,
        updated: Date.now(),
        chapters: info.chapters,
        chapterIndices: info.chapterIndices,
      });
      controller.signal.throwIfAborted();
      if (!books.some((x) => x.id === item.id)) books.unshift(item);
      await saveShelf(uid, books);
      await showShelf();
      statusLine(root, 'EPUB 已保存在此浏览器，点击“继续阅读”即可打开。');
      void navigator.storage?.persist?.().catch(() => false);
    });
  });
  const authChanged = (event: Event) => {
    const next = (event as CustomEvent<{ username?: string } | null>).detail?.username || '';
    if (uid && identity && identity !== next) {
      stop();
      mount(root);
      return;
    }
    identity = next;
  };
  document.addEventListener('replow:auth', authChanged, { signal: controller.signal });
  document.addEventListener(
    'replow:signout',
    () => {
      stop();
      mount(root);
    },
    { signal: controller.signal },
  );
  void run(async () => {
    await refresh();
    controller.signal.throwIfAborted();
    // Restore account metadata after authentication; the browser owns all EPUB bytes.
    const cached = await localShelf(uid);
    if (!books.length && cached?.length) books = cached;
    if (view === 'shelf') await showShelf();
  });
}
export function startReading() {
  for (const root of document.querySelectorAll<HTMLElement>('[data-reading]')) if (!active.has(root)) mount(root);
}
document.addEventListener('astro:before-swap', () => {
  for (const stop of active.values()) stop();
});

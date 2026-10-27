import { button, el } from '../fanqie/view';
import { addBookmark, removeBookmark } from './bookmarks';
import { localBookmarks, saveBookmarks } from './storage';
import type { Progress } from './types';

interface Options {
  uid: number;
  bookId: string;
  getProgress: () => Progress | undefined;
  onNavigate: (cfi: string) => void;
  onMessage: (message: string) => void;
}

/** Local-only EPUB bookmarks; no book text or CFI is sent to the public API. */
export async function createBookmarkControls({ uid, bookId, getProgress, onNavigate, onMessage }: Options) {
  let bookmarks = (await localBookmarks(uid, bookId)) || [];
  const panel = el('section', 'reading-bookmark-panel');
  panel.id = 'reading-bookmarks';
  panel.hidden = true;
  panel.setAttribute('role', 'region');
  panel.setAttribute('aria-label', '本地书签');
  const list = el('div', 'reading-bookmark-list');
  const toggle = button(
    '',
    () => {
      panel.hidden = !panel.hidden;
      toggle.setAttribute('aria-expanded', String(!panel.hidden));
    },
    true,
  );
  toggle.setAttribute('aria-controls', panel.id);
  toggle.setAttribute('aria-expanded', 'false');

  function render() {
    toggle.textContent = `书签 (${bookmarks.length})`;
    list.replaceChildren();
    if (!bookmarks.length) {
      list.append(el('p', 'fq-muted', '还没有书签。读到喜欢的地方，就把它留下来吧。'));
      return;
    }
    for (const bookmark of bookmarks) {
      const row = el('div', 'reading-bookmark-row');
      const label = el('span', '', `${bookmark.chapter} · ${bookmark.percentage.toFixed(1)}%`);
      row.append(
        label,
        button('前往', () => onNavigate(bookmark.cfi), true),
        button(
          '删除',
          () => {
            void (async () => {
              const next = removeBookmark(bookmarks, bookmark.id);
              await saveBookmarks(uid, bookId, next);
              bookmarks = next;
              render();
            })().catch(() => onMessage('删除书签失败，请检查浏览器存储。'));
          },
          true,
        ),
      );
      list.append(row);
    }
  }

  const add = button(
    '添加书签',
    () => {
      void (async () => {
        const progress = getProgress();
        if (!progress?.cfi) return onMessage('章节还没加载完成，稍后再添加书签。');
        const next = addBookmark(bookmarks, progress, crypto.randomUUID());
        if (next === bookmarks) return onMessage('这里已经有书签了。');
        await saveBookmarks(uid, bookId, next);
        bookmarks = next;
        render();
        onMessage('书签已保存在当前浏览器。');
      })().catch((error: unknown) => onMessage(error instanceof Error ? error.message : '保存书签失败。'));
    },
    true,
  );
  panel.append(el('h3', '', '我的书签'), list);
  render();
  return { add, toggle, panel };
}

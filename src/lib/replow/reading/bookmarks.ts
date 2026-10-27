import type { Progress, ReadingBookmark } from './types';

export const MAX_BOOKMARKS = 100;

/** A bookmark is tied to an EPUB CFI, not a page number that changes with font size. */
export function addBookmark(existing: ReadingBookmark[], progress: Progress, id: string): ReadingBookmark[] {
  if (!progress.cfi) return existing;
  if (existing.some((bookmark) => bookmark.cfi === progress.cfi)) return existing;
  if (existing.length >= MAX_BOOKMARKS) throw new Error('每本书最多保存 100 个书签。');
  return [
    {
      id,
      cfi: progress.cfi,
      chapter: progress.chapter || '未命名章节',
      percentage: Math.max(0, Math.min(100, progress.percentage)),
      created: Date.now(),
    },
    ...existing,
  ];
}

export function removeBookmark(existing: ReadingBookmark[], id: string): ReadingBookmark[] {
  return existing.filter((bookmark) => bookmark.id !== id);
}

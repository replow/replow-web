import type { LocalFile, ShelfBook } from './types';

/** Recover older CFI-based progress using the EPUB's actual linear reading order. */
export function chapterCounts(
  item: Pick<ShelfBook, 'cfi' | 'percentage' | 'read_chapters' | 'total_chapters'>,
  file?: Pick<LocalFile, 'chapters' | 'chapterIndices'>,
) {
  const total = Math.max(0, Math.floor(item.total_chapters || file?.chapters || 0));
  let read = Math.max(0, Math.floor(item.read_chapters || 0));
  if (!read && item.cfi) {
    const step = Number(/^epubcfi\(\/6\/(\d+)/.exec(item.cfi)?.[1]);
    if (step > 0 && step % 2 === 0) {
      const index = step / 2 - 1;
      read = file?.chapterIndices ? file.chapterIndices.filter((n) => n <= index).length : index + 1;
    }
  }
  if (item.percentage >= 100 && total) read = total;
  return { read: total ? Math.min(total, read) : read, total };
}

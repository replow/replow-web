import type { FqClient } from '../fanqie/api';
import type { Chapter } from '../fanqie/types';
import { packageEpub } from './epub';
import { localChapter, localFile, saveChapter, saveFile } from './storage';
import type { ChapterText, ShelfBook } from './types';

export async function prepareBook(
  uid: number,
  book: ShelfBook,
  client: FqClient,
  signal: AbortSignal,
  report: (text: string) => void,
) {
  const cached = await localFile(uid, book.id);
  if (cached) return cached.blob;
  if (book.source === 'local') throw new Error('此浏览器没有这本 EPUB，请重新导入原文件。');
  report('正在获取目录…');
  const toc = await client.request<{ chapters: Chapter[]; total_chapters: number }>(`/books/${book.source_id}/toc`);
  if (!toc.chapters.length) throw new Error('目录暂时不可用，请稍后重试。');
  const chapters = new Map<string, ChapterText>();
  for (const entry of toc.chapters) {
    const old = await localChapter(uid, book.id, entry.id);
    if (old) chapters.set(entry.id, old);
  }
  const started = Date.now();
  const reused = chapters.size;
  const groups: number[] = [];
  for (let offset = 0; offset < toc.chapters.length; offset += 10) {
    if (toc.chapters.slice(offset, offset + 10).some((x) => !chapters.has(x.id))) groups.push(offset);
  }
  let next = 0;
  async function worker() {
    while (next < groups.length) {
      signal.throwIfAborted();
      const offset = groups[next++];
      let lastError: unknown;
      for (let attempt = 0; attempt < 3; attempt++) {
        try {
          const result = await client.request<{ chapters: ChapterText[]; total: number; offset: number }>(
            `/reading/batch/${book.source_id}?offset=${offset}&limit=10`,
            undefined,
            true,
            { signal },
          );
          const expected = toc.chapters.slice(offset, offset + 10);
          if (
            result.total !== toc.chapters.length ||
            result.offset !== offset ||
            result.chapters.length !== expected.length ||
            result.chapters.some((x, i) => x.chapter_id !== expected[i].id)
          )
            throw new Error('目录发生变化，请重新尝试。');
          for (const chapter of result.chapters) {
            await saveChapter(uid, book.id, chapter);
            chapters.set(chapter.chapter_id, chapter);
          }
          const seconds = (Date.now() - started) / 1000;
          const done = chapters.size - reused;
          const eta = done > 0 ? Math.ceil(((toc.chapters.length - chapters.size) * seconds) / done) : 0;
          report(
            '正在保存到浏览器 ' +
              chapters.size +
              ' / ' +
              toc.chapters.length +
              ' 章 · 已用 ' +
              Math.floor(seconds) +
              ' 秒 · 预计剩余 ' +
              eta +
              ' 秒',
          );
          lastError = undefined;
          break;
        } catch (error) {
          signal.throwIfAborted();
          lastError = error;
        }
      }
      if (lastError) throw lastError;
    }
  }
  await Promise.all([worker(), worker()]);
  signal.throwIfAborted();
  report('正在浏览器内打包 EPUB…');
  const blob = await packageEpub(
    book,
    toc.chapters.map((x) => {
      const chapter = chapters.get(x.id);
      if (!chapter) throw new Error('章节不完整，请重试。');
      return chapter;
    }),
  );
  signal.throwIfAborted();
  await saveFile(uid, book.id, { blob, updated: Date.now(), chapters: chapters.size });
  // A persistent-storage request may be declined; the saved file remains usable.
  void navigator.storage?.persist?.().catch(() => false);
  return blob;
}

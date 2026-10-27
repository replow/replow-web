import type { ChapterText, LocalFile, Progress, ReadingBookmark, ReadingStats, ShelfBook } from './types';

let database: Promise<IDBDatabase> | undefined;
function open() {
  database ??= new Promise<IDBDatabase>((resolve, reject) => {
    // Keep the legacy database name so existing EPUB files and progress survive.
    const request = indexedDB.open('miro-reading', 2);
    request.onupgradeneeded = () => {
      for (const name of ['files', 'chapters', 'progress', 'shelf', 'bookmarks', 'stats']) {
        if (!request.result.objectStoreNames.contains(name)) request.result.createObjectStore(name);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => {
      database = undefined;
      reject(new Error('浏览器本地存储不可用，请检查隐私设置。'));
    };
    request.onblocked = () => reject(new Error('请关闭其他阅读页面后重试。'));
  });
  return database;
}
async function read<T>(store: string, key: string): Promise<T | undefined> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const request = db.transaction(store).objectStore(store).get(key);
    request.onsuccess = () => resolve(request.result as T | undefined);
    request.onerror = () => reject(request.error);
  });
}
async function write(store: string, key: string, value?: unknown) {
  const db = await open();
  return new Promise<void>((resolve, reject) => {
    const transaction = db.transaction(store, 'readwrite');
    if (value === undefined) transaction.objectStore(store).delete(key);
    else transaction.objectStore(store).put(value, key);
    transaction.oncomplete = () => resolve();
    transaction.onabort = () => reject(new Error('本地保存失败，可能存储空间不足。请释放空间后重试。'));
    transaction.onerror = () => reject(new Error('本地保存失败，可能存储空间不足。'));
  });
}
const key = (uid: number, id: string) => `${uid}:${id}`;
export const localFile = (uid: number, id: string) => read<LocalFile>('files', key(uid, id));
export const saveFile = (uid: number, id: string, file: LocalFile) => write('files', key(uid, id), file);
export const localProgress = (uid: number, id: string) => read<Progress>('progress', key(uid, id));
export const saveProgress = (uid: number, id: string, progress: Progress) => write('progress', key(uid, id), progress);
export const localBookmarks = (uid: number, id: string) => read<ReadingBookmark[]>('bookmarks', key(uid, id));
export const saveBookmarks = (uid: number, id: string, bookmarks: ReadingBookmark[]) =>
  write('bookmarks', key(uid, id), bookmarks);
export const localReadingStats = (uid: number, id: string) => read<ReadingStats>('stats', key(uid, id));
export const saveReadingStats = (uid: number, id: string, stats: ReadingStats) => write('stats', key(uid, id), stats);
export const localShelf = (uid: number) => read<ShelfBook[]>('shelf', String(uid));
export const saveShelf = (uid: number, books: ShelfBook[]) => write('shelf', String(uid), books);
export const localChapter = (uid: number, id: string, chapter: string) =>
  read<ChapterText>('chapters', key(uid, `${id}:${chapter}`));
export const saveChapter = (uid: number, id: string, chapter: ChapterText) =>
  write('chapters', key(uid, `${id}:${chapter.chapter_id}`), chapter);

export async function removeLocalBook(uid: number, id: string) {
  await Promise.all([
    write('files', key(uid, id)),
    write('progress', key(uid, id)),
    write('bookmarks', key(uid, id)),
    write('stats', key(uid, id)),
  ]);
  const db = await open();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction('chapters', 'readwrite');
    const prefix = key(uid, `${id}:`);
    tx.objectStore('chapters').delete(IDBKeyRange.bound(prefix, `${prefix}\uffff`));
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

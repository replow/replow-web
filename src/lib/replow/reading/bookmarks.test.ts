import assert from 'node:assert/strict';
import test from 'node:test';
import { addBookmark, MAX_BOOKMARKS, removeBookmark } from './bookmarks';
import type { Progress } from './types';

const progress: Progress = { cfi: 'epubcfi(/6/2)', chapter: '第一章', percentage: 12.5, updated: 1 };

test('adds a stable CFI bookmark without duplicating the same location', () => {
  const list = addBookmark([], progress, 'one');
  assert.equal(list[0]?.chapter, '第一章');
  assert.equal(list[0]?.percentage, 12.5);
  assert.equal(addBookmark(list, progress, 'two'), list);
  assert.deepEqual(removeBookmark(list, 'one'), []);
});

test('caps bookmarks per book and ignores positions without a CFI', () => {
  assert.deepEqual(addBookmark([], { ...progress, cfi: '' }, 'empty'), []);
  const full = Array.from({ length: MAX_BOOKMARKS }, (_, i) => ({
    id: String(i),
    cfi: String(i),
    chapter: '',
    percentage: 0,
    created: 0,
  }));
  assert.throws(() => addBookmark(full, progress, 'overflow'), /100/);
});

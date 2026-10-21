import assert from 'node:assert/strict';
import { test } from 'node:test';
import { chapterCounts } from './chapter-progress';

test('new books show zero read and their known chapter total', () => {
  assert.deepEqual(chapterCounts({ cfi: '', percentage: 0, total_chapters: 12 }), { read: 0, total: 12 });
});
test('existing CFI progress recovers the current chapter without rounding percentages', () => {
  assert.deepEqual(chapterCounts({ cfi: 'epubcfi(/6/8[chapter]!/4/2:0)', percentage: 1 }, { chapters: 9 }), {
    read: 4,
    total: 9,
  });
});
test('nonlinear resources are excluded when recovering local EPUB progress', () => {
  assert.deepEqual(chapterCounts({ cfi: 'epubcfi(/6/8!/4/2:0)', percentage: 10 }, { chapters: 3, chapterIndices: [0, 2, 3] }), {
    read: 3,
    total: 3,
  });
});
test('saved chapter counts remain independent of the approximate percentage', () => {
  assert.deepEqual(chapterCounts({ cfi: '', percentage: 75, read_chapters: 2, total_chapters: 10 }), { read: 2, total: 10 });
});
test('completed books and changed totals stay within chapter bounds', () => {
  assert.deepEqual(chapterCounts({ cfi: '', percentage: 100, total_chapters: 8 }), { read: 8, total: 8 });
  assert.deepEqual(chapterCounts({ cfi: '', percentage: 1, read_chapters: 20, total_chapters: 8 }), { read: 8, total: 8 });
});
test('unknown or invalid metadata never invents a total or a CFI chapter', () => {
  assert.deepEqual(chapterCounts({ cfi: 'invalid', percentage: 80 }), { read: 0, total: 0 });
  assert.deepEqual(chapterCounts({ cfi: 'epubcfi(/6/3!/4)', percentage: 1, total_chapters: 5 }), { read: 0, total: 5 });
});

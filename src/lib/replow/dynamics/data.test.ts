import assert from 'node:assert/strict';
import test from 'node:test';
import { normalizeDynamics } from './data';

const item = {
  id: 1,
  published: 1784081487000,
  content: '**Fixture**',
  pinned: true,
  location: 'Fixture',
  images: [{ src: 'https://example.invalid/a.png', alt: 'Image' }],
};
test('preserves image objects, timestamps, pinned state and text', () => {
  assert.deepEqual(normalizeDynamics([item]), [item]);
});
test('drops draft, invalid IDs, duplicates and invalid dates', () => {
  assert.equal(
    normalizeDynamics([
      item,
      item,
      { ...item, id: 2, is_published: false },
      { ...item, id: -1 },
      { ...item, id: 3, published: 'bad' },
    ]).length,
    1,
  );
});
test('rejects unsafe media URLs and never coerces image objects into src', () => {
  const result = normalizeDynamics([
    {
      ...item,
      images: [
        { src: 'javascript:alert(1)' },
        { src: 'https://user:pass@example.invalid/a.png' },
        { src: 'data:image/svg+xml,a' },
        '[object Object]',
        item.images[0],
      ],
    },
  ]);
  assert.deepEqual(result[0].images, item.images);
});
test('handles empty and malformed payloads', () => {
  assert.deepEqual(normalizeDynamics(null), []);
  assert.deepEqual(normalizeDynamics({ items: [item] }), []);
});

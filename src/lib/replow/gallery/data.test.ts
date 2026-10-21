import assert from 'node:assert/strict';
import { test } from 'node:test';
import { imageUrl, normalizeAlbums, normalizeDetail, selectedAlbum } from './data';

test('rejects executable and protocol-relative image URLs', () => {
  for (const value of ['javascript:alert(1)', 'data:text/html,x', '//evil.invalid/x', 'bad']) assert.equal(imageUrl(value), '');
  assert.equal(imageUrl('/uploads/photo.jpg'), '/uploads/photo.jpg');
});
test('album URL state accepts positive safe IDs', () => {
  assert.equal(selectedAlbum('?album=12'), 12);
  for (const query of ['?album=-1', '?album=0', '?album=x', '?album=1e2']) assert.equal(selectedAlbum(query), null);
});
test('normalizes only valid public albums', () => {
  assert.equal(normalizeAlbums([{ id: 1, title: 'Fixture', resolved_cover: 'javascript:x' }, { id: -1 }]).length, 1);
  assert.equal(normalizeAlbums(null).length, 0);
});
test('invalid media sources never reach the image viewer', () => {
  assert.equal(
    normalizeDetail({
      id: 1,
      title: 'Fixture',
      description: '',
      photos: [{ id: 1, media_id: 1, caption: '', original_name: 'x', public_url: 'javascript:x' }],
    }).photos.length,
    0,
  );
});

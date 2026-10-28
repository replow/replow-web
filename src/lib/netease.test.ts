import assert from 'node:assert/strict';
import { test } from 'node:test';
import { formatTime, musicUrl, normalizeSong, parseLyrics, restoreQueue } from './netease';

test('normalizes both search API song shapes and upgrades artwork to HTTPS', () => {
  const song = normalizeSong({
    id: 123,
    name: 'Song',
    ar: [{ name: 'A' }, { name: 'B' }],
    al: { name: 'Album', picUrl: 'http://p3.music.126.net/cover.jpg' },
    dt: 120000,
  });
  assert.equal(song?.artist, 'A / B');
  assert.equal(song?.cover, 'https://p3.music.126.net/cover.jpg');
  assert.equal(
    normalizeSong({ id: 1, name: 'Old', artists: [{ name: 'Singer' }], album: { name: 'Album' }, duration: 123000 })?.duration,
    123000,
  );
  assert.equal(normalizeSong({ id: -1, name: 'Invalid' }), null);
  assert.equal(musicUrl('javascript:alert(1)'), '');
  assert.equal(musicUrl('https://user:password@example.org/file'), '');
});

test('parses fractional and repeated LRC timestamps, offset, CRLF and empty metadata', () => {
  assert.deepEqual(parseLyrics('[ar:Singer]\r\n[offset:100]\r\n[00:03.50][00:01.005] hello\r\n[00:00.000]\r\n[01:02] End'), [
    { time: 1.105, text: 'hello' },
    { time: 3.6, text: 'hello' },
    { time: 62.1, text: 'End' },
  ]);
  assert.deepEqual(parseLyrics('Pure instrumental'), []);
});

test('restores only validated, deduplicated metadata and handles broken browser storage', () => {
  const song = {
    id: 123,
    name: 'Song',
    artist: 'Singer',
    album: 'Album',
    cover: 'https://example.org/cover.jpg',
    duration: 120000,
  };
  assert.deepEqual(restoreQueue(JSON.stringify({ version: 1, songs: [song, song, { id: 'bad' }] })), [song]);
  assert.deepEqual(restoreQueue('{broken'), []);
  assert.deepEqual(restoreQueue(JSON.stringify({ version: 9, songs: [song] })), []);
  assert.equal(
    restoreQueue(JSON.stringify({ version: 1, songs: Array.from({ length: 250 }, (_, i) => ({ ...song, id: i + 1 })) })).length,
    200,
  );
  assert.equal(formatTime(Number.NaN), '0:00');
  assert.equal(formatTime(125.9), '2:05');
});

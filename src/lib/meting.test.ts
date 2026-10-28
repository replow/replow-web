import assert from 'node:assert/strict';
import test, { type TestContext } from 'node:test';
import { fetchMeting, fetchNeteaseEnhanced, resolvePlaylist, type MetingSong } from './meting';

const song: MetingSong = {
  name: 'Test song',
  artist: 'Test artist',
  url: 'http://163.hyc.moe?server=netease&type=url&id=42',
  pic: 'http://163.hyc.moe?server=netease&type=pic&id=42',
  lrc: 'http://163.hyc.moe?server=netease&type=lrc&id=42&format=lrc',
};

function mockMeting(t: TestContext, songs: MetingSong[]) {
  const originalStorage = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  const storage = new Map<string, string>();
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
    },
  });
  t.after(() => {
    if (originalStorage) Object.defineProperty(globalThis, 'localStorage', originalStorage);
    else Reflect.deleteProperty(globalThis, 'localStorage');
  });
  const fetch = t.mock.method(globalThis, 'fetch', async () => Response.json(songs));
  return { storage, fetch };
}

test('HTTPS Meting responses use HTTPS for lyrics and media on the API host', async (t) => {
  mockMeting(t, [song]);
  const [resolved] = await fetchMeting('netease', 'playlist', '42');
  for (const field of ['url', 'pic', 'lrc'] as const) {
    const expected = new URL(song[field]);
    expected.protocol = 'https:';
    assert.equal(resolved[field], expected.href);
  }
});

test('old cached HTTP lyric addresses are repaired without refetching the playlist', async (t) => {
  const { storage, fetch } = mockMeting(t, []);
  storage.set('meting:netease:playlist:42', JSON.stringify({ data: [song], timestamp: Date.now() }));
  const [resolved] = await fetchMeting('netease', 'playlist', '42');
  assert.equal(new URL(resolved.lrc).protocol, 'https:');
  assert.equal(fetch.mock.callCount(), 0);
});

test('custom HTTPS APIs upgrade their own lyric URLs and preserve other hosts and ports', async (t) => {
  mockMeting(t, [
    {
      ...song,
      lrc: 'http://music.example/api/?type=lrc&id=42',
      url: 'http://cdn.example/song.mp3',
      pic: 'http://music.example:8080/cover.jpg',
    },
  ]);
  const [resolved] = await fetchMeting('netease', 'playlist', '42', 'https://music.example/api/');
  assert.equal(resolved.lrc, 'https://music.example/api/?type=lrc&id=42');
  assert.equal(resolved.url, 'http://cdn.example/song.mp3');
  assert.equal(resolved.pic, 'http://music.example:8080/cover.jpg');
});

test('an explicitly configured HTTP API keeps its HTTP resource URLs', async (t) => {
  mockMeting(t, [song]);
  const [resolved] = await fetchMeting('netease', 'playlist', '42', 'http://163.hyc.moe/');
  assert.deepEqual(resolved, song);
});

test('inline lyrics, relative assets, and absent lyrics remain unchanged', async (t) => {
  const inline = { ...song, lrc: '[00:00.00]Inline lyrics', pic: '/cover.jpg', url: 'https://163.hyc.moe/song.mp3' };
  const noLyrics = { ...song, lrc: '', pic: '', url: '/song.mp3' };
  mockMeting(t, [inline, noLyrics]);
  const resolved = await fetchMeting('netease', 'playlist', '42');
  assert.deepEqual(resolved, [inline, noLyrics]);
});


test('custom Meting URLs preserve configured backend query parameters', async (t) => {
  const { fetch } = mockMeting(t, [song]);
  await fetchMeting('netease', 'song', '42', 'https://music.example/api/?cookie=default');
  const requested = new URL(fetch.mock.calls[0].arguments[0] as URL);
  assert.equal(requested.searchParams.get('cookie'), 'default');
  assert.equal(requested.searchParams.get('server'), 'netease');
  assert.equal(requested.searchParams.get('type'), 'song');
  assert.equal(requested.searchParams.get('id'), '42');
});

test('Enhanced playlist fills missing metadata and requests exhigh streams without browser Cookies', async (t) => {
  const calls: { url: URL; options?: RequestInit }[] = [];
  t.mock.method(globalThis, 'fetch', async (input: URL, options?: RequestInit) => {
    const url = new URL(input.toString());
    calls.push({ url, options });
    if (url.pathname === '/playlist/detail') {
      return Response.json({
        code: 200,
        playlist: {
          tracks: [{ id: 7, name: 'First', ar: [{ name: 'Artist A' }], al: { picUrl: 'https://img.example/7.jpg' } }],
          trackIds: [{ id: 7 }, { id: 8 }],
        },
      });
    }
    if (url.pathname === '/song/detail') {
      return Response.json({
        code: 200,
        songs: [{ id: 8, name: 'Second', ar: [{ name: 'Artist B' }], al: { picUrl: 'https://img.example/8.jpg' } }],
      });
    }
    return Response.json({ code: 404 }, { status: 404 });
  });

  const songs = await fetchNeteaseEnhanced('playlist', '42');
  assert.deepEqual(songs.map((entry) => entry.name), ['First', 'Second']);
  assert.equal(songs[0].artist, 'Artist A');
  assert.equal(songs[1].pic, 'https://img.example/8.jpg');
  assert.equal(calls[0].url.searchParams.get('id'), '42');
  assert.equal(calls[1].url.searchParams.get('ids'), '8');
  assert.ok(calls.every((call) => call.options?.credentials === 'omit'));

  for (const [index, entry] of songs.entries()) {
    const audio = new URL(entry.url);
    const lyrics = new URL(entry.lrc);
    assert.equal(audio.origin, 'https://api.replow.org');
    assert.equal(audio.pathname, '/song/url/v1/302');
    assert.equal(audio.searchParams.get('id'), String(index + 7));
    assert.equal(audio.searchParams.get('level'), 'exhigh');
    assert.equal(lyrics.pathname, '/lyric');
  }
});

test('default NetEase URL resolution uses Enhanced while custom Meting remains supported', async (t) => {
  const requests: URL[] = [];
  t.mock.method(globalThis, 'fetch', async (input: URL) => {
    const url = new URL(input.toString());
    requests.push(url);
    return Response.json({ code: 200, songs: [{ id: 42, name: 'Test', ar: [{ name: 'Artist' }] }] });
  });

  const songs = await resolvePlaylist(['https://music.163.com/#/song?id=42']);
  assert.equal(songs[0].name, 'Test');
  assert.equal(requests[0].pathname, '/song/detail');
});

test('Enhanced API errors are propagated instead of returning an empty playlist', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => Response.json({ code: 401 }));
  await assert.rejects(
    resolvePlaylist(['https://music.163.com/#/song?id=31415926']),
    /NetEase API error: 401/,
  );
});

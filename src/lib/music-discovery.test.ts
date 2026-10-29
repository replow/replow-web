import assert from 'node:assert/strict';
import test from 'node:test';
import { $bgmPanelOpen, $bgmSelection, playBgmTracks } from '../store/bgm';
import { discoverySong, playlistMusic, recommendedMusic, searchMusic } from './music-discovery';

test('discovery selections use the existing player with lazy exhigh URLs', () => {
  const song = discoverySong({
    id: 42,
    name: 'Test song',
    ar: [{ name: 'Test artist' }],
    al: { picUrl: 'http://example.com/art.jpg' },
    dt: 120000,
  });
  assert.ok(song);
  assert.equal(new URL(song.url).pathname, '/song/url/v1/302');
  assert.equal(new URL(song.url).searchParams.get('level'), 'exhigh');
  assert.equal(song.pic, 'https://example.com/art.jpg');
  assert.equal(discoverySong({ id: -1, name: 'invalid' }), null);
  const tracks = Array.from({ length: 250 }, (_, index) => ({ ...song, name: String(index) }));
  playBgmTracks(tracks, 249);
  const selection = $bgmSelection.get();
  assert.ok(selection);
  assert.equal(selection.tracks[selection.index].name, '249');
  assert.equal(selection.tracks.length, 200);
  assert.equal($bgmPanelOpen.get(), true);
  playBgmTracks([], 0);
  assert.equal($bgmSelection.get(), selection);
  $bgmSelection.set(null);
  $bgmPanelOpen.set(false);
});

test('search, recommendations and playlists use Enhanced defaults and preserve pagination', async (t) => {
  const calls: URL[] = [];
  t.mock.method(globalThis, 'fetch', async (input: URL, options: RequestInit) => {
    const url = new URL(input);
    calls.push(url);
    assert.equal(options.credentials, 'omit');
    assert.ok(options.signal);
    assert.equal(url.searchParams.has('cookie'), false);
    return Response.json(
      url.pathname === '/cloudsearch'
        ? {
            code: 200,
            result: { songCount: 21, songs: [{ id: 42, name: 'Test' }] },
          }
        : url.pathname === '/personalized'
          ? {
              code: 200,
              result: [{ id: 1, name: 'Recommended', picUrl: 'https://example.com/cover.jpg', trackCount: 3 }],
            }
          : { code: 200, songs: [{ id: 43, name: 'Playlist track' }] },
    );
  });
  const result = await searchMusic('test song', 1);
  assert.equal(result.total, 21);
  assert.equal(result.songs[0].id, 42);
  assert.equal(calls[0].searchParams.get('offset'), '20');
  assert.equal(calls[0].searchParams.get('keywords'), 'test song');
  assert.equal((await recommendedMusic())[0].name, 'Recommended');
  assert.equal((await playlistMusic(1))[0].id, 43);
});

test('service errors are surfaced to discovery retry UI', async (t) => {
  t.mock.method(globalThis, 'fetch', async () => Response.json({ code: 500 }));
  await assert.rejects(searchMusic('test', 0), /音乐服务暂时不可用/);
});

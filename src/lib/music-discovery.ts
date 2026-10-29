import type { MetingSong } from './meting';

export interface DiscoverySong extends MetingSong {
  id: number;
  duration: number;
}
export interface DiscoveryPlaylist {
  id: number;
  name: string;
  cover: string;
  count: number;
}
type Data = Record<string, unknown>;
function record(value: unknown): Data {
  return value && typeof value === 'object' ? (value as Data) : {};
}
function safeImage(value: unknown): string {
  if (typeof value !== 'string') return '';
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.href.replace(/^http:/, 'https:') : '';
  } catch {
    return '';
  }
}
export function discoverySong(value: unknown): DiscoverySong | null {
  const item = record(value);
  const id = Number(item.id);
  if (!Number.isSafeInteger(id) || id <= 0 || typeof item.name !== 'string') return null;
  const album = record(item.al ?? item.album);
  const artists = item.ar ?? item.artists;
  return {
    id,
    name: item.name,
    artist: Array.isArray(artists)
      ? artists
          .map((artist) => String(record(artist).name ?? ''))
          .filter(Boolean)
          .join(' / ')
      : '',
    duration: Math.max(0, Number(item.dt ?? item.duration) || 0),
    pic: safeImage(album.picUrl),
    url: `https://api.replow.org/song/url/v1/302?id=${id}&level=exhigh`,
    lrc: `https://api.replow.org/lyric?id=${id}`,
  };
}
async function request(path: string, params: Record<string, string | number>, signal?: AbortSignal): Promise<Data> {
  const url = new URL(path, 'https://api.replow.org');
  for (const [key, value] of Object.entries(params)) url.searchParams.set(key, String(value));
  // The Enhanced API applies its configured default Cookie server-side.
  const response = await fetch(url, {
    credentials: 'omit',
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(18000)]) : AbortSignal.timeout(18000),
  });
  if (!response.ok) throw new Error('音乐服务暂时无法连接，请稍后重试。');
  const data = record(await response.json());
  if (data.code !== 200) throw new Error('音乐服务暂时不可用，请稍后重试。');
  return data;
}
function songs(value: unknown): DiscoverySong[] {
  return Array.isArray(value) ? value.map(discoverySong).filter((song): song is DiscoverySong => song !== null) : [];
}
export async function searchMusic(query: string, page: number, signal?: AbortSignal) {
  const data = await request('/cloudsearch', { keywords: query, type: 1, limit: 20, offset: page * 20 }, signal);
  const result = record(data.result);
  return { songs: songs(result.songs), total: Number(result.songCount) || 0 };
}
export async function recommendedMusic(signal?: AbortSignal): Promise<DiscoveryPlaylist[]> {
  const data = await request('/personalized', { limit: 8 }, signal);
  return Array.isArray(data.result)
    ? data.result.flatMap((value) => {
        const item = record(value);
        const id = Number(item.id);
        return Number.isSafeInteger(id) && id > 0
          ? [
              {
                id,
                name: String(item.name ?? '网易云歌单'),
                cover: safeImage(item.picUrl),
                count: Number(item.trackCount) || 0,
              },
            ]
          : [];
      })
    : [];
}
export async function playlistMusic(id: number, signal?: AbortSignal) {
  const data = await request('/playlist/track/all', { id, limit: 100, offset: 0 }, signal);
  return songs(data.songs);
}

export interface Song {
  id: number;
  name: string;
  artist: string;
  album: string;
  cover: string;
  duration: number;
}

export interface Playlist {
  id: number;
  name: string;
  cover: string;
  count: number;
}

export interface LyricLine {
  time: number;
  text: string;
}

const API = 'https://api.replow.org';
type RecordData = Record<string, unknown>;
function record(value: unknown): RecordData {
  return value !== null && typeof value === 'object' ? (value as RecordData) : {};
}

export function musicUrl(value: unknown): string {
  if (typeof value !== 'string') return '';
  try {
    const url = new URL(value);
    if (url.protocol === 'http:') url.protocol = 'https:';
    return url.protocol === 'https:' && !url.username && !url.password ? url.href : '';
  } catch {
    return '';
  }
}

export function normalizeSong(value: unknown): Song | null {
  const source = record(value);
  const id = Number(source.id);
  if (!Number.isSafeInteger(id) || id <= 0 || typeof source.name !== 'string') return null;
  const album = record(source.al ?? source.album);
  const artists = source.ar ?? source.artists;
  return {
    id,
    name: source.name,
    artist: Array.isArray(artists)
      ? artists
          .map((item) => String(record(item).name ?? ''))
          .filter(Boolean)
          .join(' / ')
      : String(source.artist ?? '未知歌手'),
    album: String(album.name ?? source.album ?? ''),
    cover: musicUrl(album.picUrl ?? source.cover),
    duration: Math.max(0, Number(source.dt ?? source.duration) || 0),
  };
}

async function request(path: string, params: Record<string, string | number>, signal?: AbortSignal): Promise<RecordData> {
  const url = new URL(path, API);
  for (const [key, value] of Object.entries(params)) url.searchParams.set(key, String(value));
  const response = await fetch(url, {
    signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(18000)]) : AbortSignal.timeout(18000),
    credentials: 'omit',
    headers: { Accept: 'application/json' },
  });
  if (!response.ok) throw new Error('音乐服务暂时无法连接，请稍后重试。');
  const data = record(await response.json());
  if (data.code !== 200) throw new Error('音乐服务暂时不可用，请稍后重试。');
  return data;
}

function songsFrom(values: unknown): Song[] {
  return Array.isArray(values) ? values.map(normalizeSong).filter((song): song is Song => song !== null) : [];
}

export async function searchSongs(query: string, page: number, signal?: AbortSignal) {
  const data = await request('/cloudsearch', { keywords: query, type: 1, limit: 20, offset: page * 20 }, signal);
  const result = record(data.result);
  return { songs: songsFrom(result.songs), total: Number(result.songCount) || 0 };
}

export async function recommendedPlaylists(signal?: AbortSignal): Promise<Playlist[]> {
  const data = await request('/personalized', { limit: 4 }, signal);
  return Array.isArray(data.result)
    ? data.result.slice(0, 4).flatMap((value) => {
        const item = record(value);
        const id = Number(item.id);
        return Number.isSafeInteger(id) && id > 0
          ? [{ id, name: String(item.name ?? '网易云歌单'), cover: musicUrl(item.picUrl), count: Number(item.trackCount) || 0 }]
          : [];
      })
    : [];
}

export async function playlistSongs(id: number, signal?: AbortSignal): Promise<Song[]> {
  const data = await request('/playlist/track/all', { id, limit: 100, offset: 0 }, signal);
  return songsFrom(data.songs);
}

export async function songSource(id: number, signal?: AbortSignal) {
  const data = await request('/song/url/v1', { id, level: 'standard' }, signal);
  const source = record(Array.isArray(data.data) ? data.data[0] : null);
  const url = musicUrl(source.url);
  if (!url) throw new Error('这首歌暂时无法播放，可能需要网易云会员或受地区限制。试试其他歌曲吧。');
  return { url, trial: Boolean(source.freeTrialInfo) };
}

export function parseLyrics(source: string): LyricLine[] {
  const lines: LyricLine[] = [];
  const offset = Number(source.match(/\[offset:([+-]?\d+)\]/i)?.[1] ?? 0) / 1000;
  for (const line of source.split(/\r?\n/)) {
    const text = line.replace(/\[[^\]]*\]/g, '').trim();
    if (!text) continue;
    for (const match of line.matchAll(/\[(\d+):(\d{2}(?:\.\d+)?)\]/g)) {
      lines.push({ time: Math.max(0, Number(match[1]) * 60 + Number(match[2]) + offset), text });
    }
  }
  return lines.sort((a, b) => a.time - b.time);
}

export async function songLyrics(id: number, signal?: AbortSignal): Promise<LyricLine[]> {
  const data = await request('/lyric', { id }, signal);
  return parseLyrics(String(record(data.lrc).lyric ?? ''));
}

export function formatTime(seconds: number): string {
  const value = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`;
}

/** A versioned queue stores metadata only; expiring audio URLs are always fetched on play. */
export function restoreQueue(value: string | null): Song[] {
  try {
    const data = record(JSON.parse(value ?? '{}'));
    if (data.version !== 1 || !Array.isArray(data.songs)) return [];
    const seen = new Set<number>();
    return songsFrom(data.songs)
      .filter((song) => {
        if (seen.has(song.id)) return false;
        seen.add(song.id);
        return true;
      })
      .slice(0, 200);
  } catch {
    return [];
  }
}

/**
 * Music URL resolver. NetEase uses our Enhanced API with its server-side
 * default Cookie; QQ Music and explicitly configured Meting endpoints retain
 * the original Meting integration.
 */

const DEFAULT_API = 'https://163.hyc.moe/';
const NETEASE_API = 'https://api.replow.org/';
const NETEASE_QUALITY = 'exhigh';
const CACHE_TTL = 24 * 60 * 60 * 1000; // 24 hours

export interface MetingSong {
  name: string;
  artist: string;
  url: string;
  pic: string;
  lrc: string;
}

interface ParsedUrl {
  server: string;
  type: string;
  id: string;
}

// URL parsing rules (ported from Shoka player.js:30-47)
const URL_RULES: [RegExp, string, string][] = [
  [/music\.163\.com.*song.*id=(\d+)/, 'netease', 'song'],
  [/music\.163\.com.*album.*id=(\d+)/, 'netease', 'albumlist'],
  [/music\.163\.com.*playlist.*id=(\d+)/, 'netease', 'playlist'],
  [/music\.163\.com.*discover\/toplist.*id=(\d+)/, 'netease', 'playlist'],
  [/y\.qq\.com.*song\/(\w+)/, 'tencent', 'song'],
  [/y\.qq\.com.*album\/(\w+)/, 'tencent', 'albumlist'],
  [/y\.qq\.com.*playsquare\/(\w+)/, 'tencent', 'playlist'],
  [/y\.qq\.com.*playlist\/(\w+)/, 'tencent', 'playlist'],
];

/** Parse a music platform URL into server/type/id triple. */
export function parseMusicUrl(url: string): ParsedUrl | null {
  for (const [regex, server, type] of URL_RULES) {
    const match = url.match(regex);
    if (match?.[1]) {
      return { server, type, id: match[1] };
    }
  }
  return null;
}

interface CacheEntry {
  data: MetingSong[];
  timestamp: number;
}

function getCacheKey(server: string, type: string, id: string): string {
  return `meting:${server}:${type}:${id}`;
}

function getFromCache(key: string): MetingSong[] | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const entry: CacheEntry = JSON.parse(raw);
    if (Date.now() - entry.timestamp > CACHE_TTL) {
      localStorage.removeItem(key);
      return null;
    }
    return entry.data;
  } catch {
    return null;
  }
}

function setCache(key: string, data: MetingSong[]): void {
  try {
    const entry: CacheEntry = { data, timestamp: Date.now() };
    localStorage.setItem(key, JSON.stringify(entry));
  } catch {
    // localStorage full or unavailable — non-critical, skip silently
  }
}

function isMetingSong(obj: unknown): obj is MetingSong {
  if (typeof obj !== 'object' || obj === null) return false;
  const o = obj as Record<string, unknown>;
  return typeof o.name === 'string' && typeof o.artist === 'string' && typeof o.url === 'string';
}

/** Some HTTPS Meting servers return HTTP links whose redirects fail browser CORS checks. */
function normalizeMediaUrls(songs: MetingSong[], apiUrl: URL): MetingSong[] {
  if (apiUrl.protocol !== 'https:') return songs;

  const normalize = (source: string): string => {
    if (!source?.startsWith('http://')) return source;
    try {
      const url = new URL(source);
      if (url.host !== apiUrl.host) return source;
      url.protocol = 'https:';
      return url.href;
    } catch {
      return source;
    }
  };

  return songs.map((song) => ({
    ...song,
    url: normalize(song.url),
    pic: normalize(song.pic),
    lrc: normalize(song.lrc),
  }));
}

/** Fetch songs from Meting API for a single parsed URL. */
export async function fetchMeting(server: string, type: string, id: string, apiUrl?: string): Promise<MetingSong[]> {
  const url = new URL(apiUrl || DEFAULT_API);
  const cacheKey = getCacheKey(server, type, id);
  const cached = getFromCache(cacheKey);
  if (cached) return normalizeMediaUrls(cached, url);

  // Keep configured endpoint parameters (for example a backend-side auth selector).
  url.searchParams.set('server', server);
  url.searchParams.set('type', type);
  url.searchParams.set('id', id);
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Meting API error: ${response.status}`);

  const data: unknown = await response.json();
  if (!Array.isArray(data)) return [];
  const songs = normalizeMediaUrls(data.filter(isMetingSong), url);
  if (songs.length > 0) setCache(cacheKey, songs);
  return songs;
}


interface EnhancedTrack {
  id: number | string;
  name: string;
  ar?: { name: string }[];
  artists?: { name: string }[];
  al?: { picUrl?: string };
  album?: { picUrl?: string };
}

interface EnhancedResponse {
  code?: number;
  songs?: EnhancedTrack[];
  playlist?: {
    tracks?: EnhancedTrack[];
    trackIds?: { id: number | string }[];
  };
}

/** Enhanced API reads NETEASE_COOKIE on the server when no client Cookie is provided. */
async function fetchEnhancedJson(path: string, params: Record<string, string>): Promise<EnhancedResponse> {
  const url = new URL(path, NETEASE_API);
  for (const [key, value] of Object.entries(params)) url.searchParams.set(key, value);

  const response = await fetch(url, { credentials: 'omit' });
  if (!response.ok) throw new Error(`NetEase API error: ${response.status}`);

  const data: EnhancedResponse = await response.json();
  if (data.code !== 200) throw new Error(`NetEase API error: ${data.code ?? 'invalid response'}`);
  return data;
}

function isEnhancedTrack(value: unknown): value is EnhancedTrack {
  if (typeof value !== 'object' || value === null) return false;
  const track = value as Record<string, unknown>;
  return (typeof track.id === 'number' || typeof track.id === 'string') && typeof track.name === 'string';
}

function toMetingSong(track: EnhancedTrack): MetingSong {
  const audio = new URL('/song/url/v1/302', NETEASE_API);
  audio.searchParams.set('id', String(track.id));
  audio.searchParams.set('level', NETEASE_QUALITY);

  const lyrics = new URL('/lyric', NETEASE_API);
  lyrics.searchParams.set('id', String(track.id));

  const artists = track.ar ?? track.artists ?? [];
  return {
    name: track.name,
    artist: artists.map((artist) => artist.name).filter(Boolean).join(' / '),
    url: audio.href,
    pic: track.al?.picUrl ?? track.album?.picUrl ?? '',
    lrc: lyrics.href,
  };
}

/** Fetch full NetEase metadata; audio links are resolved lazily via the 302 endpoint. */
export async function fetchNeteaseEnhanced(type: string, id: string): Promise<MetingSong[]> {
  const cacheKey = `netease-enhanced:v1:${type}:${id}`;
  const cached = getFromCache(cacheKey);
  if (cached) return cached;

  let tracks: EnhancedTrack[] = [];
  if (type === 'song') {
    const data = await fetchEnhancedJson('/song/detail', { ids: id });
    tracks = (data.songs ?? []).filter(isEnhancedTrack);
  } else if (type === 'albumlist') {
    const data = await fetchEnhancedJson('/album', { id });
    tracks = (data.songs ?? []).filter(isEnhancedTrack);
  } else if (type === 'playlist') {
    const data = await fetchEnhancedJson('/playlist/detail', { id });
    const playlist = data.playlist;
    if (!playlist) throw new Error('NetEase playlist response has no playlist');

    // Unauthenticated playlist responses may omit tracks, while trackIds remains complete.
    const byId = new Map(
      (playlist.tracks ?? []).filter(isEnhancedTrack).map((track) => [String(track.id), track] as const),
    );
    const ids = (playlist.trackIds ?? []).map((entry) => String(entry.id));
    if (ids.length === 0) ids.push(...byId.keys());

    const missingIds = ids.filter((trackId) => !byId.has(trackId));
    for (let offset = 0; offset < missingIds.length; offset += 200) {
      const batch = missingIds.slice(offset, offset + 200);
      const detail = await fetchEnhancedJson('/song/detail', { ids: batch.join(',') });
      for (const track of (detail.songs ?? []).filter(isEnhancedTrack)) byId.set(String(track.id), track);
    }
    tracks = ids.flatMap((trackId) => {
      const track = byId.get(trackId);
      return track ? [track] : [];
    });
  } else {
    return [];
  }

  const songs = tracks.map(toMetingSong);
  if (songs.length > 0) setCache(cacheKey, songs);
  return songs;
}

/** Resolve multiple music URLs into a flat song list. */
export async function resolvePlaylist(urls: string[], apiUrl?: string): Promise<MetingSong[]> {
  const results = await Promise.allSettled(
    urls.map((url) => {
      const parsed = parseMusicUrl(url);
      if (!parsed) return Promise.resolve([]);
      const useEnhanced = parsed.server === 'netease' && (!apiUrl || new URL(apiUrl).origin === NETEASE_API.slice(0, -1));
      return useEnhanced
        ? fetchNeteaseEnhanced(parsed.type, parsed.id)
        : fetchMeting(parsed.server, parsed.type, parsed.id, apiUrl);
    }),
  );

  const songs = results.flatMap((r) => (r.status === 'fulfilled' ? r.value : []));
  if (songs.length === 0) {
    const failure = results.find((r) => r.status === 'rejected');
    if (failure?.status === 'rejected') throw failure.reason;
  }
  return songs;
}

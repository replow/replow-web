export interface AlbumSummary {
  id: number;
  title: string;
  description: string;
  resolved_cover: string;
  photo_count: number;
}
export interface Photo {
  id: number;
  media_id: number;
  caption: string;
  public_url: string;
  original_name: string;
}
export interface AlbumDetail {
  id: number;
  title: string;
  description: string;
  photos: Photo[];
}
export function imageUrl(value: unknown): string {
  if (typeof value !== 'string') return '';
  if (value.startsWith('/') && !value.startsWith('//')) return value;
  try {
    const url = new URL(value);
    return ['http:', 'https:'].includes(url.protocol) ? url.href : '';
  } catch {
    return '';
  }
}
export function selectedAlbum(search: string): number | null {
  const value = new URLSearchParams(search).get('album');
  return value && /^[1-9]\d{0,14}$/.test(value) ? Number(value) : null;
}
export function normalizeAlbums(value: unknown): AlbumSummary[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item) => item && Number.isSafeInteger(item.id) && item.id > 0)
    .map((item) => ({
      id: item.id,
      title: String(item.title || '未命名相册'),
      description: String(item.description || ''),
      resolved_cover: imageUrl(item.resolved_cover),
      photo_count: Math.max(0, Number(item.photo_count) || 0),
    }));
}
export function normalizeDetail(value: AlbumDetail): AlbumDetail {
  return {
    ...value,
    title: String(value.title || ''),
    description: String(value.description || ''),
    photos: Array.isArray(value.photos)
      ? value.photos
          .filter((photo) => imageUrl(photo.public_url))
          .map((photo) => ({
            ...photo,
            public_url: imageUrl(photo.public_url),
            caption: String(photo.caption || ''),
            original_name: String(photo.original_name || ''),
          }))
      : [],
  };
}

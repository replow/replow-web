export interface DynamicImage {
  src: string;
  alt: string;
}
export interface DynamicItem {
  id: number;
  content: string;
  images: DynamicImage[];
  location: string;
  pinned: boolean;
  published: number;
}
function image(value: unknown): DynamicImage | null {
  if (typeof value !== 'object' || !value) return null;
  const raw = value as Record<string, unknown>;
  if (typeof raw.src !== 'string') return null;
  try {
    const url = new URL(raw.src);
    if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password) return null;
    return { src: url.href, alt: typeof raw.alt === 'string' ? raw.alt : '' };
  } catch {
    return null;
  }
}
export function normalizeDynamics(value: unknown): DynamicItem[] {
  if (!Array.isArray(value)) return [];
  const result: DynamicItem[] = [],
    seen = new Set<number>();
  for (const raw of value) {
    if (!raw || typeof raw !== 'object' || raw.is_published === false) continue;
    const id = Number(raw.id),
      published = Number(raw.published);
    if (
      !Number.isSafeInteger(id) ||
      id < 1 ||
      seen.has(id) ||
      !Number.isFinite(published) ||
      !Number.isFinite(new Date(published).getTime())
    )
      continue;
    seen.add(id);
    const rawImages: unknown[] = Array.isArray(raw.images) ? raw.images : [];
    const images = rawImages
      .map(image)
      .filter((i): i is DynamicImage => !!i)
      .slice(0, 9);
    result.push({
      id,
      published,
      content: typeof raw.content === 'string' ? raw.content : '',
      location: typeof raw.location === 'string' ? raw.location : '',
      pinned: raw.pinned === true,
      images,
    });
  }
  return result;
}

import snapshot from '@/data/gallery.json';
import { type AlbumDetail, type AlbumSummary, normalizeAlbums, normalizeDetail, type Photo, selectedAlbum } from './data';

function element<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = '') {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}
function required<T extends Element>(parent: Element, selector: string): T {
  const found = parent.querySelector<T>(selector);
  if (!found) throw new Error('Gallery markup is incomplete: ' + selector);
  return found;
}
let cleanup: (() => void) | undefined;

export function startGallery() {
  cleanup?.();
  const root = document.querySelector<HTMLElement>('[data-gallery]');
  if (!root) return;
  const controller = new AbortController(),
    signal = controller.signal;
  const list = required<HTMLElement>(root, '[data-gallery-list]');
  const title = required<HTMLElement>(root, '[data-gallery-title]');
  const description = required<HTMLElement>(root, '[data-gallery-description]');
  const status = required<HTMLElement>(root, '[data-gallery-status]');
  const back = required<HTMLButtonElement>(root, '[data-gallery-back]');
  const dialog = required<HTMLDialogElement>(root, 'dialog');
  const large = required<HTMLImageElement>(dialog, '[data-lightbox-image]');
  const caption = required<HTMLElement>(dialog, '[data-lightbox-caption]');
  const counter = required<HTMLElement>(dialog, '[data-lightbox-counter]');
  let albums: AlbumSummary[] = normalizeAlbums(snapshot.items),
    photos: Photo[] = [],
    index = 0,
    version = 0;
  let previousOverflow = '',
    touchX: number | null = null;
  let scrollLocked = false;
  async function get<T>(path: string): Promise<T> {
    const response = await fetch('/v1/public/albums' + path, {
      headers: { Accept: 'application/json' },
      cache: 'no-store',
      signal,
    });
    if (!response.ok) throw new Error(response.status === 404 ? '此相册未发布或已移除。' : '相册暂时无法读取，请稍后重试。');
    return response.json() as Promise<T>;
  }
  function showAlbums() {
    title.textContent = '相册';
    description.textContent = '收集日常、风景与值得留下的瞬间。';
    back.hidden = true;
    list.className = 'gallery-albums';
    list.replaceChildren();
    for (const album of albums) {
      const link = element('a', 'gallery-album');
      link.href = '?album=' + album.id;
      link.dataset.album = String(album.id);
      if (album.resolved_cover) {
        const image = element('img');
        image.src = album.resolved_cover;
        image.alt = '';
        image.loading = 'lazy';
        link.append(image);
      } else link.append(element('span', 'gallery-placeholder', '还没有封面'));
      const content = element('div', 'gallery-album-info');
      content.append(
        element('h3', '', album.title),
        element('p', '', album.description),
        element('small', '', album.photo_count + ' 张图片'),
      );
      link.append(content);
      list.append(link);
    }
    if (!albums.length) list.append(element('p', 'gallery-empty', '相册正在整理中，新的瞬间很快就会出现。'));
  }
  function closeLightbox() {
    if (dialog.open) dialog.close();
  }
  function updatePhoto() {
    const photo = photos[index];
    if (!photo) return;
    large.src = photo.public_url;
    large.alt = photo.caption || photo.original_name;
    caption.textContent = photo.caption || photo.original_name;
    counter.textContent = index + 1 + ' / ' + photos.length;
  }
  function openPhoto(position: number) {
    index = position;
    updatePhoto();
    previousOverflow = document.documentElement.style.overflow;
    scrollLocked = true;
    document.documentElement.style.overflow = 'hidden';
    dialog.showModal();
  }
  function step(delta: number) {
    if (!photos.length) return;
    index = (index + delta + photos.length) % photos.length;
    updatePhoto();
  }
  function showAlbum(album: AlbumDetail) {
    title.textContent = album.title;
    description.textContent = album.description;
    back.hidden = false;
    photos = album.photos;
    list.className = 'gallery-photos';
    list.replaceChildren();
    photos.forEach((photo, position) => {
      const button = element('button', 'gallery-photo');
      button.type = 'button';
      button.dataset.photo = String(position);
      button.setAttribute('aria-label', '查看大图：' + (photo.caption || photo.original_name || '图片'));
      const image = element('img');
      image.src = photo.public_url;
      image.alt = photo.caption || photo.original_name;
      image.loading = 'lazy';
      image.decoding = 'async';
      button.append(image);
      if (photo.caption) button.append(element('span', '', photo.caption));
      list.append(button);
    });
    if (!photos.length) list.append(element('p', 'gallery-empty', '这本相册还没有图片。'));
  }
  async function loadSelected() {
    const task = ++version,
      id = selectedAlbum(location.search);
    closeLightbox();
    if (!id) {
      showAlbums();
      status.textContent = '';
      return;
    }
    status.textContent = '正在读取相册…';
    try {
      const response = await get<{ data: AlbumDetail }>('/' + id);
      if (task !== version || signal.aborted) return;
      showAlbum(normalizeDetail(response.data));
      status.textContent = '';
    } catch (error) {
      if (signal.aborted || task !== version) return;
      list.replaceChildren();
      title.textContent = '相册';
      description.textContent = '';
      back.hidden = false;
      status.textContent = error instanceof Error ? error.message : '相册读取失败。';
    }
  }
  async function refresh() {
    const task = ++version;
    status.textContent = '正在刷新相册…';
    try {
      const response = await get<{ items: unknown }>('');
      if (task !== version || signal.aborted) return;
      albums = normalizeAlbums(response.items);
      await loadSelected();
    } catch {
      if (signal.aborted || task !== version) return;
      showAlbums();
      status.textContent = '暂时无法连接，正在展示上次构建的公开相册。点击刷新重试。';
    }
  }
  function navigate(id: number | null) {
    const url = new URL(location.href);
    if (id) url.searchParams.set('album', String(id));
    else url.searchParams.delete('album');
    history.pushState(null, '', url);
    void loadSelected();
  }
  root.addEventListener(
    'click',
    (event) => {
      const target = event.target instanceof Element ? event.target : null;
      const album = target?.closest<HTMLElement>('[data-album]');
      if (album) {
        event.preventDefault();
        navigate(Number(album.dataset.album));
        return;
      }
      const photo = target?.closest<HTMLElement>('[data-photo]');
      if (photo) {
        openPhoto(Number(photo.dataset.photo));
        return;
      }
      if (target?.closest('[data-gallery-back]')) navigate(null);
      if (target?.closest('[data-gallery-refresh]')) void refresh();
      if (target?.closest('[data-lightbox-close]')) closeLightbox();
      if (target?.closest('[data-lightbox-prev]')) step(-1);
      if (target?.closest('[data-lightbox-next]')) step(1);
    },
    { signal },
  );
  dialog.addEventListener(
    'close',
    () => {
      if (scrollLocked) document.documentElement.style.overflow = previousOverflow;
      scrollLocked = false;
    },
    { signal },
  );
  dialog.addEventListener(
    'click',
    (event) => {
      if (event.target === dialog) closeLightbox();
    },
    { signal },
  );
  dialog.addEventListener(
    'keydown',
    (event) => {
      if (event.key === 'ArrowRight') {
        event.preventDefault();
        step(1);
      }
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        step(-1);
      }
    },
    { signal },
  );
  large.addEventListener(
    'pointerdown',
    (event) => {
      if (event.pointerType === 'touch') touchX = event.clientX;
    },
    { signal },
  );
  large.addEventListener(
    'pointerup',
    (event) => {
      if (touchX === null) return;
      const delta = event.clientX - touchX;
      touchX = null;
      if (Math.abs(delta) > 50) step(delta < 0 ? 1 : -1);
    },
    { signal },
  );
  window.addEventListener('popstate', () => void loadSelected(), { signal });
  cleanup = () => {
    controller.abort();
    closeLightbox();
    if (scrollLocked) document.documentElement.style.overflow = previousOverflow;
    scrollLocked = false;
  };
  showAlbums();
  void refresh();
}
export function stopGallery() {
  cleanup?.();
  cleanup = undefined;
}

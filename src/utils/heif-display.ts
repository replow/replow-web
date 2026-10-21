/**
 * Keep HEIF/HEIC URLs native. Safari displays originals directly; browsers
 * without a HEIF decoder get a temporary, in-memory PNG preview (never JPEG).
 * Neither the stored file nor the public cover URL is rewritten.
 */
const HEIF_URL = /\.hei(?:c|f)(?:[?#]|$)/i;
const MAX_BYTES = 32 * 1024 * 1024;
let installed = false;
let running = 0;
const waiting: Array<() => void> = [];
const objectUrls = new Set<string>();

function enqueue(task: () => Promise<void>) {
  const start = () => {
    running++;
    void task().finally(() => {
      running--;
      waiting.shift()?.();
    });
  };
  if (running < 2) start();
  else waiting.push(start);
}

async function fetchOriginal(url: string): Promise<Blob> {
  let response: Response | undefined;
  try {
    response = await fetch(url, { mode: 'cors', credentials: 'omit' });
    if (!response.ok) throw new Error('HEIF original unavailable');
  } catch {
    // R2 custom domains may not allow browser-side cross-origin fetches.
    // The API only proxies HEIF objects below the configured public media prefix.
    response = await fetch('/v1/public/heif-source?url=' + encodeURIComponent(url));
    if (!response.ok) throw new Error('HEIF same-origin source unavailable');
  }
  const declared = Number(response.headers.get('content-length') || 0);
  if (declared > MAX_BYTES) throw new Error('HEIF source is too large');
  const blob = await response.blob();
  if (blob.size > MAX_BYTES) throw new Error('HEIF source is too large');
  return blob;
}

async function decodeImage(img: HTMLImageElement, original: string) {
  try {
    const blob = await fetchOriginal(original);
    if (!img.isConnected || img.src !== original) return;
    const { default: heic2any } = await import('heic2any');
    const converted = await heic2any({ blob, toType: 'image/png' });
    if (!img.isConnected || img.src !== original) return;
    const preview = URL.createObjectURL(Array.isArray(converted) ? converted[0] : converted);
    objectUrls.add(preview);
    img.dataset.heifPreview = 'png-memory';
    img.src = preview;
    img.addEventListener('load', () => {
      // Once decoded by the browser, the temporary URL can be released.
      setTimeout(() => {
        URL.revokeObjectURL(preview);
        objectUrls.delete(preview);
      }, 3000);
    }, { once: true });
  } catch {
    if (!img.isConnected || img.src !== original) return;
    img.alt = img.alt || '当前浏览器无法显示 HEIF 原图，请使用 Safari 查看';
    img.title = 'HEIF 原文件已保留，但当前浏览器暂时无法解码';
    img.dataset.heifPreview = 'unavailable';
  }
}

export function installHeifImageFallback() {
  if (installed || typeof document === 'undefined') return;
  installed = true;
  // Native HEIF-capable browsers will never trigger an error for supported files.
  document.addEventListener('error', event => {
    if (!(event.target instanceof HTMLImageElement)) return;
    const img = event.target;
    if (img.dataset.heifPreview || !HEIF_URL.test(img.src)) return;
    const original = img.src;
    img.dataset.heifPreview = 'decoding';
    enqueue(() => decodeImage(img, original));
  }, true);
  window.addEventListener('pagehide', () => {
    for (const url of objectUrls) URL.revokeObjectURL(url);
    objectUrls.clear();
  });
}

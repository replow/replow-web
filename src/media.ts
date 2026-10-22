import { request } from "./api";

export type MediaItem = {
  id: number;
  original_name: string;
  public_url: string;
  object_key: string;
  mime_type: string;
  byte_size: number;
  category: string;
  storage_backend: string;
  created_at: string;
  uploader_id: number;
};

export type MediaCategory = "site" | "avatar" | "article";

export const mediaApi = {
  list: (limit = 60, offset = 0) => request<{items: MediaItem[]; total: number}>(
    `/account/media?limit=${limit}&offset=${offset}`
  ),
  rename: (id: number, original_name: string) =>
    request<{data: MediaItem}>(`/account/media/${id}`, {
      method: "PATCH", body: JSON.stringify({original_name})
    }),
  delete: (id: number) =>
    request<{success: boolean}>(`/account/media/${id}`, {method: "DELETE"})
};

/** OneDrive quickXorHash matches the checked algorithm in the admin uploader. */
function quickXorHash(buffer: ArrayBuffer): string {
  const folded = new Uint8Array(160);
  const bytes = new Uint8Array(buffer);
  let slot = 0;
  for (const value of bytes) {
    folded[slot++] ^= value;
    if (slot === 160) slot = 0;
  }
  const result = new Uint8Array(20);
  for (let index = 0; index < 160; index++) {
    const bit = (index * 11) % 160;
    const byte = Math.floor(bit / 8);
    const shift = bit % 8;
    result[byte] ^= (folded[index] << shift) & 255;
    if (shift) result[(byte + 1) % 20] ^= folded[index] >>> (8 - shift);
  }
  for (let index = 0; index < 8; index++)
    result[12 + index] ^= Math.floor(bytes.length / 2 ** (index * 8)) & 255;
  return btoa(String.fromCharCode(...result));
}

function sendChunk(url: string, body: Blob, headers: Record<string, string>,
                   onProgress: (loaded: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.timeout = 300_000;
    // Cloud uploads must never receive account credentials.
    xhr.withCredentials = false;
    for (const [key, value] of Object.entries(headers)) xhr.setRequestHeader(key, value);
    xhr.upload.onprogress = event => { if (event.lengthComputable) onProgress(event.loaded); };
    xhr.onload = () => xhr.status >= 200 && xhr.status < 300
      ? resolve() : reject(new Error("云端上传失败"));
    xhr.onerror = xhr.ontimeout = () => reject(new Error("云端上传超时或网络异常"));
    xhr.send(body);
  });
}

const contentTypes: Record<string, string> = {
  jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png",
  gif: "image/gif", webp: "image/webp", avif: "image/avif",
  bmp: "image/bmp", heic: "image/heic", heif: "image/heif",
  pdf: "application/pdf", txt: "text/plain", epub: "application/epub+zip",
  zip: "application/zip", mp3: "audio/mpeg", mp4: "video/mp4",
  webm: "video/webm", ogg: "audio/ogg", wav: "audio/wav", flac: "audio/flac"
};

export async function uploadMedia(
  file: File, category: MediaCategory, onProgress: (fraction: number) => void
): Promise<MediaItem> {
  if (!file.size || file.size > 100 * 1024 * 1024) throw new Error("文件必须在 100 MB 以内");
  const ext = file.name.split(".").pop()?.toLowerCase() || "";
  const contentType = contentTypes[ext];
  if (!contentType) throw new Error("暂不支持该文件类型");
  if (category !== "site" && !contentType.startsWith("image/"))
    throw new Error("头像和文章图片只支持图片文件");
  if (!crypto?.subtle) throw new Error("浏览器不支持安全直传，请使用 HTTPS");
  const bytes = await file.arrayBuffer();
  const checksum = await crypto.subtle.digest("SHA-256", bytes);
  const sha256 = [...new Uint8Array(checksum)].map(x => x.toString(16).padStart(2, "0")).join("");
  const prepared = await request<{data: {
    upload_url: string; ticket: string; content_type: string; sha256: string;
    backend: "od" | "r2"; chunk_size?: number;
  }}>("/account/media/direct/prepare", {
    method: "POST",
    body: JSON.stringify({
      filename: file.name, category, content_type: contentType,
      byte_size: file.size, sha256, quickxor: quickXorHash(bytes)
    })
  });
  const data = prepared.data;
  try {
    if (data.backend === "od") {
      const chunk = data.chunk_size || 5 * 1024 * 1024;
      for (let start = 0; start < file.size; start += chunk) {
        const end = Math.min(start + chunk, file.size);
        await sendChunk(data.upload_url, file.slice(start, end), {
          "Content-Type": "application/octet-stream",
          "Content-Range": `bytes ${start}-${end-1}/${file.size}`
        }, loaded => onProgress((start + loaded) / file.size));
      }
    } else {
      await sendChunk(data.upload_url, file, {
        "Content-Type": data.content_type,
        "x-amz-meta-sha256": data.sha256,
        "Cache-Control": "public, max-age=31536000, immutable"
      }, loaded => onProgress(loaded / file.size));
    }
    onProgress(1);
  } catch {
    // Never print signed upload URLs or authorization tickets.
    throw new Error("云存储直传失败，请检查网络后重试");
  }
  const confirmed = await request<{data: MediaItem}>("/account/media/direct/confirm", {
    method: "POST", body: JSON.stringify({ ticket: data.ticket })
  });
  return confirmed.data;
}

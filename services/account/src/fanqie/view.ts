import type { Book, Job } from './types';

export function el<K extends keyof HTMLElementTagNameMap>(tag: K, className = '', text = '') {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}
export function button(label: string, action: () => void, secondary = false) {
  const node = el('button', secondary ? 'fq-button fq-secondary' : 'fq-button', label);
  node.type = 'button';
  node.addEventListener('click', action);
  return node;
}
export function link(label: string, href: string, secondary = false) {
  const node = el('a', secondary ? 'fq-button fq-secondary' : 'fq-button', label);
  node.href = href;
  return node;
}
export function cover(url: string, title: string) {
  const box = el('div', 'fq-cover', '书');
  try {
    const source = new URL(url);
    if (!['http:', 'https:'].includes(source.protocol)) return box;
    if (source.protocol === 'http:') source.protocol = 'https:';
    const image = el('img');
    image.src = source.href;
    image.alt = title + '封面';
    image.loading = 'lazy';
    image.referrerPolicy = 'no-referrer';
    image.addEventListener('error', () => {
      box.textContent = '书';
    });
    box.replaceChildren(image);
  } catch {
    /* Empty and invalid covers use the same placeholder. */
  }
  return box;
}
export function bookCard(book: Book) {
  const card = el('article', 'fq-book');
  card.append(cover(book.cover, book.title));
  const info = el('div', 'fq-book-info');
  info.append(el('h3', '', book.title), el('p', 'fq-author', book.author));
  if (book.total) info.append(el('p', 'fq-muted', `${book.total} 个目录条目`));
  card.append(info);
  return { card, info };
}
const labels: Record<Job['status'], string> = {
  queued: '排队中',
  running: '正在下载',
  retry: '保留进度，等待重试',
  completed: '已完成',
  failed: '下载失败',
};
export function jobProgress(job: Job) {
  const box = el('div', 'fq-progress');
  box.append(
    el('strong', '', labels[job.status]),
    el(
      'p',
      'fq-muted',
      job.status === 'queued'
        ? `队列位置：${job.queue_position}`
        : `${job.completed_chapters} / ${job.total_chapters || '—'} 个目录条目`,
    ),
  );
  const progress = el('progress');
  progress.max = 1;
  progress.value = job.progress || 0;
  progress.setAttribute('aria-label', '下载进度');
  box.append(progress);
  if (job.reused_chapters || job.added_chapters)
    box.append(el('p', 'fq-muted', `复用 ${job.reused_chapters} 项 · 新下载 ${job.added_chapters} 项`));
  if (job.file_available && job.download_url) {
    box.append(
      link(`下载 ${job.format.toUpperCase()} 文件`, job.download_url),
      el('p', 'fq-muted', `文件保留至 ${date(job.expires_at)}`),
    );
  } else if (job.status === 'failed') box.append(el('p', 'fq-error', '未生成完整文件。可稍后重新提交，已验证的进度会保留。'));
  return box;
}
export function date(seconds: number | null) {
  return seconds ? new Date(seconds * 1000).toLocaleString('zh-CN', { hour12: false }) : '—';
}
export function statusLine(root: HTMLElement, message: string, error = false) {
  let node = root.querySelector<HTMLElement>('.fq-status');
  if (!node) {
    node = el('p', 'fq-status');
    node.setAttribute('role', 'status');
    node.setAttribute('aria-live', 'polite');
    root.prepend(node);
  }
  node.classList.toggle('fq-error', error);
  node.textContent = message;
}

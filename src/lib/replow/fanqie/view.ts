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
    image.decoding = 'async';
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
  cancelled: '任务已取消',
};
export function duration(seconds: number) {
  const total = Math.max(0, Math.floor(Number.isFinite(seconds) ? seconds : 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor(total % 3600 / 60);
  const secs = String(total % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${secs}` : `${String(minutes).padStart(2, '0')}:${secs}`;
}

/** Refresh the countdown without resetting the progress bar or controls. */
export function updateJobTiming(box: HTMLElement, job: Job, now = Date.now() / 1000) {
  const elapsed = box.querySelector<HTMLElement>('.fq-elapsed');
  const remaining = box.querySelector<HTMLElement>('.fq-remaining');
  const speed = box.querySelector<HTMLElement>('.fq-speed');
  if (!elapsed || !remaining) return;
  elapsed.textContent = duration(now - job.created_at);
  if (job.status === 'queued') {
    remaining.textContent = '等待队列分配';
    if (speed) speed.textContent = '排队中';
  } else if (job.status === 'retry') {
    remaining.textContent = '等待自动重试';
    if (speed) speed.textContent = '已保留下载进度';
  } else if (job.status === 'running') {
    const todo = Math.max(0, job.total_chapters - job.completed_chapters);
    const fetched = Math.max(0, job.completed_chapters - job.reused_chapters);
    const runtime = now - (job.started_at || job.created_at);
    if (job.total_chapters && todo === 0) {
      remaining.textContent = '正在整理文件…';
      if (speed) speed.textContent = '章节已全部获取';
    } else if (!job.total_chapters || fetched < 2 || runtime < 1) {
      remaining.textContent = '采样中，等待章节返回';
      if (speed) speed.textContent = '正在连接解析服务';
    } else {
      // The average is observed throughput, excluding reused chapters / queue time.
      const perSecond = fetched / runtime;
      remaining.textContent = `约 ${duration(todo / perSecond)}`;
      if (speed) speed.textContent = `约 ${(perSecond * 60).toFixed(1)} 章/分钟`;
    }
  } else {
    remaining.textContent = '—';
    if (speed) speed.textContent = '';
  }
}

export function jobProgress(job: Job) {
  const ready = job.file_available && Boolean(job.download_url);
  const box = el('section', 'fq-progress' + (ready ? ' fq-ready' : ''));
  box.setAttribute('aria-label', '下载任务状态');
  if (ready) {
    const hero = el('div', 'fq-ready-hero');
    const symbol = el('span', 'fq-ready-check', '✓');
    symbol.setAttribute('aria-hidden', 'true');
    const title = el('div');
    title.append(
      el('span', 'fq-ready-eyebrow', 'DOWNLOAD READY'),
      el('h3', '', '你的故事，已准备就绪'),
      el('p', 'fq-muted', `《${job.title || '这本书'}》已经打包完成，点击下方按钮即可保存。`),
    );
    hero.append(symbol, title);
    const facts = el('div', 'fq-ready-facts');
    for (const [label, value] of [
      ['文件格式', job.format.toUpperCase()],
      ['章节数量', `${job.completed_chapters || job.total_chapters} 项`],
      ['保存期限', '31 天'],
      ['任务用时', duration((job.updated_at || Date.now() / 1000) - job.created_at)],
    ]) {
      const item = el('div');
      item.append(el('small', '', label), el('strong', '', value));
      facts.append(item);
    }
    const actions = el('div', 'fq-ready-actions');
    const download = link(`保存 ${job.format.toUpperCase()} 文件 ↓`, job.download_url!);
    download.classList.add('fq-ready-download');
    download.setAttribute('download', '');
    actions.append(download, link('前往历史下载 ↗', 'https://account.replow.org/?section=downloads', true));
    box.append(hero, facts, actions, el('p', 'fq-ready-expiry', `原文件有效至 ${date(job.expires_at)}，到期前可以重复下载。`));
    return box;
  }
  const labels: Record<Job['status'], string> = {
    queued: '排队中',
    running: '正在下载',
    retry: '保留进度，等待重试',
    completed: '已完成',
    failed: '下载失败',
    cancelled: '任务已取消',
  };
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
  const timing = el('div', 'fq-timing');
  const elapsed = el('div');
  elapsed.append(el('small', '', '已用时间'), el('strong', 'fq-elapsed', '00:00'));
  const remaining = el('div');
  remaining.append(el('small', '', '预计剩余'), el('strong', 'fq-remaining', '计算中…'));
  timing.append(elapsed, remaining);
  box.append(timing, el('p', 'fq-speed fq-muted'));
  updateJobTiming(box, job);
  if (job.reused_chapters || job.added_chapters)
    box.append(el('p', 'fq-muted', `复用 ${job.reused_chapters} 项 · 新下载 ${job.added_chapters} 项`));
  if (job.status === 'cancelled') box.append(el('p', 'fq-muted', '此任务已由管理员取消。需要时可重新提交。'));
  else if (job.status === 'failed') box.append(el('p', 'fq-error', '未生成完整文件。可稍后重新提交，已验证的进度会保留。'));
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

import { createFqClient, errorMessage, LoginRequired } from './api';
import type { Chapter, History, Job, Updates, ViewMode } from './types';
import { bookCard, button, date, el, jobProgress, link, statusLine } from './view';
import './style.css';

const active = new WeakMap<HTMLElement, () => void>();
export function mountFanqie(root: HTMLElement, mode: ViewMode) {
  active.get(root)?.();
  const controller = new AbortController(); const client = createFqClient(controller.signal);
  let timer = 0; let historyPage = 1;
  const updates = new Map<string, Updates>();
  const stop = () => { controller.abort(); window.clearTimeout(timer); active.delete(root); };
  active.set(root, stop);
  let currentIdentity: string | null | undefined;
  const authChanged = (event: Event) => {
    const identity = (event as CustomEvent<{ username?: string } | null>).detail?.username || null;
    if (currentIdentity !== undefined && currentIdentity !== identity) {
      stop(); mountFanqie(root, mode);
    }
    currentIdentity = identity;
  };
  document.addEventListener('replow:auth', authChanged, { signal: controller.signal });
  function login() {
    const box = el('div', 'fq-login'); box.append(el('div', 'fq-emblem', '书'), el('h2', '', '登录后，把故事带走'),
      el('p', 'fq-muted', '使用现有 SilverCode 账号，即可搜索小说、选择章节并保存下载历史。'),
      link('登录账号', 'https://account.replow.org/?return_to=' + encodeURIComponent(location.href)));
    root.replaceChildren(box);
  }
  function fail(error: unknown) {
    if (controller.signal.aborted) return;
    if (error instanceof LoginRequired) login(); else statusLine(root, errorMessage(error), true);
  }
  async function run(action: () => Promise<void>) { try { await action(); } catch (error) { fail(error); } }
  async function track(job: Job, target: HTMLElement) {
    if (controller.signal.aborted) return;
    target.replaceChildren(jobProgress(job));
    if (['queued', 'running', 'retry'].includes(job.status)) {
      timer = window.setTimeout(() => { void run(async () => track(await client.request<Job>('/jobs/' + job.job_id), target)); }, 3000);
    }
  }
  async function showSearch() {
    const form = el('form', 'fq-search-form');
    const label = el('label', '', '书名、作者或书籍 ID'); label.htmlFor = 'fq-query';
    const input = el('input'); input.id = 'fq-query'; input.placeholder = '搜索喜欢的故事，或粘贴书籍 ID'; input.required = true; input.maxLength = 100;
    const submit = el('button', 'fq-button', '搜索 / 前往下载'); submit.type = 'submit';
    const row = el('div', 'fq-search-row'); row.append(input, submit); form.append(label, row);
    const results = el('div', 'fq-results'); results.setAttribute('aria-live', 'polite');
    const navigation = el('div', 'fq-pagination'); let page = 1; let query = '';
    root.replaceChildren(form, el('p', 'fq-muted', '支持 TXT 与 EPUB · 可选章节范围 · 文件保留 31 天'), results, navigation);
    const openBook = (id: string) => { location.href = new URL('download/?book_id=' + encodeURIComponent(id), location.href).href; };
    async function search() {
      submit.disabled = true; results.setAttribute('aria-busy', 'true'); statusLine(root, '正在寻找这本书…');
      try {
        const data = await client.search(query, page); results.replaceChildren(); navigation.replaceChildren();
        for (const book of data.books) {
          const { card, info } = bookCard(book);
          const choose = button('选择章节与格式', () => openBook(book.id)); choose.setAttribute('aria-label', '下载《' + book.title + '》');
          info.append(choose); results.append(card);
        }
        statusLine(root, data.books.length ? `第 ${page} 页 · 找到 ${data.books.length} 本小说` : '没有找到这本书，试试其他书名或直接输入书籍 ID。');
        if (page > 1) navigation.append(button('上一页', () => { page--; void run(search); }, true));
        navigation.append(el('span', 'fq-muted', `第 ${page} 页`));
        if (data.hasMore) navigation.append(button('下一页', () => { page++; void run(search); }, true));
      } finally { submit.disabled = false; results.removeAttribute('aria-busy'); }
    }
    form.addEventListener('submit', event => {
      event.preventDefault(); query = input.value.trim();
      if (/^[0-9]{1,24}$/.test(query)) return openBook(query);
      if (!query) return; page = 1; void run(search);
    });
  }
  async function showConfirm() {
    const id = new URL(location.href).searchParams.get('book_id') || '';
    if (!/^[0-9]{1,24}$/.test(id)) { root.replaceChildren(el('p', 'fq-error', '书籍 ID 无效，请返回搜索页面选择一本书。'), link('返回搜索', '../')); return; }
    statusLine(root, '正在读取书籍信息与完整目录…');
    const book = await client.book(id); const { card, info } = bookCard(book); card.classList.add('fq-confirm-book');
    root.replaceChildren(card); statusLine(root, '正在读取完整目录…');
    if (book.description) root.append(el('p', 'fq-description', book.description));
    const toc = await client.request<{ chapters: Chapter[]; total_chapters: number }>('/books/' + id + '/toc');
    if (!toc.chapters.length) throw new Error('这本书的目录暂时不可用，请稍后重试。');
    info.append(el('p', 'fq-muted', `${toc.total_chapters} 个目录条目 · ID ${id}`));
    const form = el('form', 'fq-download-form'); const range = el('div', 'fq-range');
    const start = el('select'); start.id = 'fq-start'; const end = el('select'); end.id = 'fq-end';
    const latest = el('option', '', '最新章节（随整本目录）'); latest.value = ''; end.append(latest);
    for (const chapter of toc.chapters) {
      for (const select of [start, end]) { const option = el('option', '', `${chapter.index}. ${chapter.title}`); option.value = String(chapter.index); select.append(option); }
    }
    for (const [select, text] of [[start, '起始章节（目录序号）'], [end, '结束章节']] as const) {
      const field = el('label', 'fq-field', text); field.append(select); range.append(field);
    }
    const format = el('fieldset', 'fq-formats'); format.append(el('legend', '', '下载格式'));
    for (const [value, text] of [['epub', 'EPUB · 带目录，适合阅读器'], ['txt', 'TXT · 纯文本，适合导入']] as const) {
      const label = el('label'); const radio = el('input'); radio.type = 'radio'; radio.name = 'format'; radio.value = value; radio.checked = value === 'epub';
      label.append(radio, document.createTextNode(text)); format.append(label);
    }
    const submit = el('button', 'fq-button', '确认并加入下载队列'); submit.type = 'submit';
    form.append(range, format, el('p', 'fq-muted', '默认下载完整目录。自选范围包含起止项；版权页、序言等也按目录顺序编号。'), submit);
    const progress = el('div'); progress.setAttribute('aria-live', 'polite');
    const directory = el('details', 'fq-directory'); directory.append(el('summary', '', `展开完整目录 · ${toc.total_chapters} 项`));
    const list = el('ol'); for (const chapter of toc.chapters) list.append(el('li', '', chapter.title)); directory.append(list);
    root.append(form, progress, directory); statusLine(root, '确认书名、作者和封面后，选择下载范围与格式。');
    form.addEventListener('submit', event => {
      event.preventDefault(); const first = Number(start.value); const last = end.value ? Number(end.value) : null;
      if (last !== null && last < first) return statusLine(root, '结束章节不能早于起始章节。', true);
      submit.disabled = true;
      void run(async () => {
        try {
          const selected = form.querySelector<HTMLInputElement>('input[name="format"]:checked');
          const job = await client.request<Job>('', { book_id: id, format: selected?.value || 'epub', start_chapter: first, end_chapter: last });
          statusLine(root, '任务已保存。离开页面后仍会继续，可到用户中心查看。'); await track(job, progress);
        } finally { submit.disabled = false; }
      });
    });
  }
  async function showHistory() {
    const data = await client.request<History>('/history?' + new URLSearchParams({ page: String(historyPage), size: '20' }));
    root.replaceChildren();
    const heading = el('div', 'fq-history-heading'); heading.append(el('p', 'fq-muted', `共 ${data.total} 条下载记录 · 文件保留 31 天`), link('去下载小说', 'https://www.replow.org/fanqie/', true)); root.append(heading);
    if (!data.items.length) root.append(el('div', 'fq-empty', '书架还是空的。去搜一本喜欢的小说吧。'));
    for (const job of data.items) {
      const { card, info } = bookCard({ id: job.book_id, title: job.title || '小说 ' + job.book_id, author: job.author || '作者信息待获取', cover: job.cover_url, total: 0, description: '' });
      card.classList.add('fq-history-card'); info.append(el('p', 'fq-muted', `${job.format.toUpperCase()} · 目录 ${job.start_chapter}—${job.end_chapter || '最新'} · ${date(job.created_at)}`));
      const actions = el('div', 'fq-actions'); const hint = el('p', 'fq-muted');
      if (job.file_available && job.download_url) {
        actions.append(link('再次下载原文件', job.download_url)); info.append(el('p', 'fq-muted', `可下载至 ${date(job.expires_at)}`));
      } else if (job.status === 'completed' || job.status === 'failed') {
        info.append(el('p', 'fq-muted', job.expired ? '原文件已过期或不可用，重新生成后可继续下载。' : '上次未完成，可保留进度重新尝试。'));
        actions.append(button('重新请求下载', () => { void run(async () => { await client.request<Job>('/jobs/' + job.job_id + '/reuse', {}); await showHistory(); }); }));
      } else {
        info.append(el('p', 'fq-muted', `正在处理 · ${job.completed_chapters}/${job.total_chapters || '—'} 项`));
      }
      const updateAction = () => { void run(async () => { await client.request<Job>('/jobs/' + job.job_id + '/update', {}); await showHistory(); }); };
      if (job.status === 'completed') actions.append(button('检查是否更新', () => {
        void run(async () => {
          hint.textContent = '正在检查最新目录…'; const result = await client.request<Updates>('/jobs/' + job.job_id + '/updates'); updates.set(job.job_id, result); renderUpdate(result);
        });
      }, true));
      function renderUpdate(result: Updates) {
        hint.textContent = result.has_updates ? `目录有更新，新增 ${result.new_chapters} 项；当前共 ${result.current_total_chapters} 项。${result.latest_chapter_title}` : `已是最新，共 ${result.current_total_chapters} 项。`;
        if (result.has_updates && !actions.querySelector('[data-incremental]')) { const item = button('增量更新至最新', updateAction, true); item.dataset.incremental = 'true'; actions.append(item); }
      }
      const cached = updates.get(job.job_id); if (cached) renderUpdate(cached);
      info.append(actions, hint); root.append(card);
    }
    const pages = el('div', 'fq-pagination');
    if (historyPage > 1) pages.append(button('上一页', () => { historyPage--; void run(showHistory); }, true));
    pages.append(el('span', 'fq-muted', `第 ${historyPage} 页`));
    if (data.has_more) pages.append(button('下一页', () => { historyPage++; void run(showHistory); }, true));
    root.append(pages); window.clearTimeout(timer);
    if (data.items.some(job => ['queued', 'running', 'retry'].includes(job.status))) timer = window.setTimeout(() => { void run(showHistory); }, 5000);
  }
  root.replaceChildren(el('p', 'fq-muted', '正在确认登录状态…'));
  void run(async () => { await client.authorize(); if (mode === 'history') await showHistory(); else if (mode === 'confirm') await showConfirm(); else await showSearch(); });
  return stop;
}

export function startFanqie() {
  for (const root of document.querySelectorAll<HTMLElement>('[data-fanqie]')) {
    if (!active.has(root)) mountFanqie(root, (root.dataset.fanqie as ViewMode) || 'search');
  }
}
export function stopFanqie() { for (const root of document.querySelectorAll<HTMLElement>('[data-fanqie]')) active.get(root)?.(); }

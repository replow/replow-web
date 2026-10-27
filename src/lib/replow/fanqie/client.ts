import { createFqClient, errorMessage, LoginRequired } from './api';
import { mountSearch } from './search';
import type { Book, Chapter, History, Job, Updates, ViewMode } from './types';
import { bookCard, button, date, duration, el, jobProgress, link, statusLine, updateJobTiming } from './view';
import './style.css';

const active = new Map<HTMLElement, () => void>();
export function mountFanqie(root: HTMLElement, mode: ViewMode) {
  active.get(root)?.();
  const controller = new AbortController();
  const client = createFqClient(controller.signal);
  let timer = 0;
  let clock = 0;
  let historyPage = 1;
  const knownBooks = new Map<string, Book>();
  let authenticated = false;
  let selectedBookId = new URL(location.href).searchParams.get('book_id') || location.hash.replace(/^#book_id=/, '');
  let activeMode: ViewMode =
    mode === 'history'
      ? 'history'
      : /^#book_id=[0-9]{1,24}$/.test(location.hash) || new URL(location.href).searchParams.get('step') === 'confirm'
        ? 'confirm'
        : mode;
  let pageRevision = 0;
  let searchTerm = '';
  let stopSearch = () => {};
  const updates = new Map<string, Updates>();
  const stop = () => {
    stopSearch();
    controller.abort();
    window.clearTimeout(timer);
    window.clearInterval(clock);
    active.delete(root);
  };
  active.set(root, stop);
  let currentIdentity =
    (window as Window & { __replowAuthSession?: { username: string } | null }).__replowAuthSession?.username || null;
  const authChanged = (event: Event) => {
    const identity = (event as CustomEvent<{ username?: string } | null>).detail?.username || null;
    if (authenticated && currentIdentity !== null && currentIdentity !== identity) {
      stop();
      mountFanqie(root, activeMode);
      return;
    }
    currentIdentity = identity;
  };
  document.addEventListener('replow:auth', authChanged, { signal: controller.signal });
  function setHeading(next: ViewMode) {
    const surface = root.closest('.fq-surface');
    const title = surface?.querySelector('.fq-page-heading h2');
    const description = surface?.querySelector('.fq-page-heading p');
    if (title) title.textContent = next === 'confirm' ? '确认下载' : '番茄小说下载器';
    if (description)
      description.textContent = next === 'confirm' ? '确认书籍，输入章节范围。' : '寻找一本好书，让故事陪你走得更远。';
    surface?.querySelectorAll('.fq-steps li').forEach((step, index) => {
      step.classList.toggle('current', next === 'confirm' ? index === 1 : index === 0);
    });
  }
  function goto(next: ViewMode, url: string) {
    // Keep the current document and URL untouched: the theme's router treats
    // History/hash edits as navigations and otherwise remounts the downloader.
    selectedBookId = next === 'confirm' ? new URL(url).searchParams.get('book_id') || '' : '';
    stopSearch();
    stopSearch = () => {};
    activeMode = next;
    pageRevision++;
    setHeading(next);
    window.clearTimeout(timer);
    window.clearInterval(clock);
    void run(next === 'confirm' ? showConfirm : showSearch);
  }
  function login() {
    const box = el('div', 'fq-login');
    box.append(
      el('div', 'fq-emblem', '阅'),
      el('h2', '', '登录后，把故事带走'),
      el('p', 'fq-muted', '使用现有 SilverCode 账号，即可搜索小说、选择章节并保存下载历史。'),
      link('登录账号', 'https://account.replow.org/?return_to=' + encodeURIComponent(location.href)),
    );
    root.replaceChildren(box);
  }
  function fail(error: unknown) {
    if (controller.signal.aborted) return;
    if (error instanceof LoginRequired) login();
    else statusLine(root, errorMessage(error), true);
  }
  async function run(action: () => Promise<void>) {
    try {
      await action();
    } catch (error) {
      fail(error);
    }
  }
  async function track(job: Job, target: HTMLElement) {
    if (controller.signal.aborted) return;
    if (!target.isConnected) return;
    target.replaceChildren(jobProgress(job));
    window.clearInterval(clock);
    if (['queued', 'running', 'retry'].includes(job.status)) {
      clock = window.setInterval(() => {
        if (target.isConnected && !controller.signal.aborted) updateJobTiming(target, job);
      }, 1000);
      timer = window.setTimeout(() => {
        void run(async () => track(await client.request<Job>('/jobs/' + job.job_id), target));
      }, 1500);
    }
  }
  async function showSearch() {
    stopSearch();
    stopSearch = mountSearch({
      root,
      client,
      initialQuery: searchTerm,
      knownBooks,
      onQuery: (term) => {
        searchTerm = term;
      },
      onSelect: (id) => goto('confirm', new URL('/fanqie/download/?book_id=' + encodeURIComponent(id), location.origin).href),
      onError: fail,
    });
  }
  async function showConfirm() {
    const id = selectedBookId || new URL(location.href).searchParams.get('book_id') || '';
    if (!/^[0-9]{1,24}$/.test(id)) {
      root.replaceChildren(el('p', 'fq-error', '书籍 ID 无效，请返回搜索页面选择一本书。'), link('返回搜索', '../'));
      return;
    }
    const currentPageRevision = pageRevision;
    const storedBook = knownBooks.get(id);
    if (storedBook) {
      const { card } = bookCard(storedBook);
      card.classList.add('fq-confirm-book');
      root.replaceChildren(card);
      statusLine(root, '已找到书籍，正在载入章节目录…');
    } else statusLine(root, '正在读取书籍信息与章节目录…');
    // Search results are text-first and often omit the synopsis. Always load
    // complete details here, while retaining the search card as a fast preview.
    const bookPromise = client.book(id);
    const tocPromise = client.request<{ chapters: Chapter[]; total_chapters: number }>('/books/' + id + '/toc');
    const [book, toc] = await Promise.all([bookPromise, tocPromise]);
    if (currentPageRevision !== pageRevision || controller.signal.aborted) return;
    // Keep an already-loaded search cover if the detail image proxy is unavailable.
    const { card, info } = bookCard({ ...book, cover: book.cover || storedBook?.cover || '' });
    card.classList.add('fq-confirm-book');
    root.replaceChildren(card);
    const intro = el('section', 'fq-intro');
    intro.setAttribute('aria-label', '小说简介');
    intro.append(
      el('h3', 'fq-intro-title', '作品简介'),
      el('p', 'fq-description', book.description.trim() || '这本书暂时没有提供简介。'),
    );
    root.append(intro);
    if (!toc.chapters.length) throw new Error('这本书的目录暂时不可用，请稍后重试。');
    info.append(el('p', 'fq-muted', `ID ${id}`));
    info.append(button('← 返回搜索', () => goto('search', location.href), true));
    info.append(el('span', 'fq-book-badge', `完整目录 · ${toc.total_chapters} 项`));
    const form = el('div', 'fq-download-form');
    const range = el('div', 'fq-range');
    const start = el('input');
    start.type = 'number';
    start.inputMode = 'numeric';
    start.id = 'fq-start';
    start.min = '1';
    start.max = String(toc.total_chapters);
    start.step = '1';
    start.value = '1';
    start.required = true;
    const end = el('input');
    end.type = 'number';
    end.inputMode = 'numeric';
    end.id = 'fq-end';
    end.min = '1';
    end.max = String(toc.total_chapters);
    end.step = '1';
    end.value = String(toc.total_chapters);
    end.required = true;
    for (const [input, text] of [
      [start, '从第几章开始'],
      [end, '下载到第几章'],
    ] as const) {
      const field = el('label', 'fq-field', text);
      field.append(input);
      range.append(field);
    }
    const hint = el('p', 'fq-range-hint');
    const presets = el('div', 'fq-presets');
    const applyRange = (first: number, last: number) => {
      start.value = String(first);
      end.value = String(last);
      updatePreview();
    };
    const updatePreview = () => {
      const first = start.valueAsNumber;
      const last = end.valueAsNumber;
      if (![first, last].every(Number.isInteger) || first < 1 || last < first || last > toc.total_chapters) {
        hint.textContent = `请输入 1—${toc.total_chapters} 范围内的整数，结束章节不得早于开始章节。`;
        hint.classList.add('fq-error');
        return;
      }
      hint.classList.remove('fq-error');
      hint.textContent = `已选 ${last - first + 1} 项 · ${toc.chapters[first - 1]?.title || '第' + first + '项'} → ${toc.chapters[last - 1]?.title || '第' + last + '项'}`;
    };
    start.addEventListener('input', updatePreview);
    end.addEventListener('input', updatePreview);
    presets.append(el('span', 'fq-muted', '快捷范围'));
    presets.append(button('全部章节', () => applyRange(1, toc.total_chapters), true));
    presets.append(button('前 100 章', () => applyRange(1, Math.min(100, toc.total_chapters)), true));
    presets.append(button('最新 100 章', () => applyRange(Math.max(1, toc.total_chapters - 99), toc.total_chapters), true));
    updatePreview();
    const format = el('fieldset', 'fq-formats');
    format.append(el('legend', '', '下载格式'));
    for (const [value, text] of [
      ['epub', 'EPUB · 带目录，适合阅读器'],
      ['txt', 'TXT · 纯文本，适合导入'],
    ] as const) {
      const label = el('label');
      const radio = el('input');
      radio.type = 'radio';
      radio.name = 'format';
      radio.value = value;
      radio.checked = value === 'epub';
      label.append(radio, document.createTextNode(text));
      format.append(label);
    }
    const submit = el('button', 'fq-button', '确认并加入下载队列');
    submit.type = 'button';
    form.append(
      el('h3', 'fq-form-title', '定制你的阅读文件'),
      range,
      presets,
      hint,
      format,
      el('p', 'fq-muted', '默认下载完整目录。自选范围包含起止项；版权页、序言等也按目录顺序编号。'),
      submit,
    );
    const progress = el('div');
    progress.setAttribute('aria-live', 'polite');
    const directory = el('details', 'fq-directory');
    directory.append(el('summary', '', `浏览章节目录 · ${toc.total_chapters} 项（每页 100 条）`));
    const list = el('ol');
    let directoryPage = 0;
    const directoryNav = el('div', 'fq-pagination');
    function showDirectoryPage() {
      list.replaceChildren();
      directoryNav.replaceChildren();
      for (const chapter of toc.chapters.slice(directoryPage * 100, (directoryPage + 1) * 100)) {
        const item = el('li', '', `${chapter.index}. ${chapter.title}`);
        item.value = chapter.index;
        list.append(item);
      }
      if (directoryPage > 0)
        directoryNav.append(
          button(
            '上一页',
            () => {
              directoryPage--;
              showDirectoryPage();
            },
            true,
          ),
        );
      directoryNav.append(el('span', 'fq-muted', `第 ${directoryPage + 1} / ${Math.ceil(toc.chapters.length / 100)} 页`));
      if ((directoryPage + 1) * 100 < toc.chapters.length)
        directoryNav.append(
          button(
            '下一页',
            () => {
              directoryPage++;
              showDirectoryPage();
            },
            true,
          ),
        );
    }
    directory.addEventListener('toggle', () => {
      if (directory.open && !list.children.length) showDirectoryPage();
    });
    directory.append(list, directoryNav);
    root.append(form, progress, directory);
    statusLine(root, '确认书名、作者和封面后，选择下载范围与格式。');
    submit.addEventListener('click', () => {
      const first = start.valueAsNumber;
      const last = end.valueAsNumber;
      if (![first, last].every(Number.isInteger) || first < 1 || last < first || last > toc.total_chapters)
        return statusLine(root, `请输入 1—${toc.total_chapters} 范围内的有效章节序号。`, true);
      submit.disabled = true;
      void run(async () => {
        const startedAt = performance.now();
        const waiting = el('section', 'fq-submit-wait');
        waiting.setAttribute('aria-live', 'polite');
        const waitingText = el('p', 'fq-muted');
        const updateWaiting = () => {
          const elapsed = (performance.now() - startedAt) / 1000;
          waitingText.textContent =
            elapsed < 5
              ? `正在提交下载任务 · 已等待 ${duration(elapsed)}`
              : `小说服务仍在处理请求 · 已等待 ${duration(elapsed)}，请稍候…`;
        };
        waiting.append(el('span', 'fq-submit-spinner'), waitingText);
        progress.replaceChildren(waiting);
        statusLine(root, '正在联系下载服务，任务建立后会立即显示进度。');
        updateWaiting();
        const waitingTimer = window.setInterval(updateWaiting, 1000);
        try {
          const selected = form.querySelector<HTMLInputElement>('input[name="format"]:checked');
          const job = await client.request<Job>('', {
            book_id: id,
            format: selected?.value || 'epub',
            start_chapter: first,
            end_chapter: last,
          });
          statusLine(root, '任务已保存。离开页面后仍会继续，可到用户中心查看。');
          await track(job, progress);
        } catch (error) {
          progress.replaceChildren();
          throw error;
        } finally {
          window.clearInterval(waitingTimer);
          submit.disabled = false;
        }
      });
    });
  }
  async function showHistory() {
    const data = await client.request<History>('/history?' + new URLSearchParams({ page: String(historyPage), size: '20' }));
    root.replaceChildren();
    const heading = el('div', 'fq-history-heading');
    heading.append(
      el('p', 'fq-muted', `共 ${data.total} 条下载记录 · 文件保留 31 天`),
      link('去下载小说', 'https://www.replow.org/fanqie/', true),
    );
    root.append(heading);
    if (!data.items.length) root.append(el('div', 'fq-empty', '书架还是空的。去搜一本喜欢的小说吧。'));
    for (const job of data.items) {
      const { card, info } = bookCard({
        id: job.book_id,
        title: job.title || '小说 ' + job.book_id,
        author: job.author || '作者信息待获取',
        cover: job.cover_url,
        total: 0,
        description: '',
      });
      card.classList.add('fq-history-card');
      info.append(
        el(
          'p',
          'fq-muted',
          `${job.format.toUpperCase()} · 目录 ${job.start_chapter}—${job.end_chapter || '最新'} · ${date(job.created_at)}`,
        ),
      );
      const actions = el('div', 'fq-actions');
      const hint = el('p', 'fq-muted');
      if (job.file_available && job.download_url) {
        actions.append(link('再次下载原文件', job.download_url));
        info.append(el('p', 'fq-muted', `可下载至 ${date(job.expires_at)}`));
      } else if (job.status === 'completed' || job.status === 'failed' || job.status === 'cancelled') {
        info.append(
          el(
            'p',
            'fq-muted',
            job.expired ? '原文件已过期或不可用，重新生成后可继续下载。' : '上次未完成，可保留进度重新尝试。',
          ),
        );
        actions.append(
          button('重新请求下载', () => {
            void run(async () => {
              await client.request<Job>('/jobs/' + job.job_id + '/reuse', {});
              await showHistory();
            });
          }),
        );
      } else {
        info.append(el('p', 'fq-muted', `正在处理 · ${job.completed_chapters}/${job.total_chapters || '—'} 项`));
      }
      const updateAction = () => {
        void run(async () => {
          await client.request<Job>('/jobs/' + job.job_id + '/update', {});
          await showHistory();
        });
      };
      if (job.status === 'completed')
        actions.append(
          button(
            '检查是否更新',
            () => {
              void run(async () => {
                hint.textContent = '正在检查最新目录…';
                const result = await client.request<Updates>('/jobs/' + job.job_id + '/updates');
                updates.set(job.job_id, result);
                renderUpdate(result);
              });
            },
            true,
          ),
        );
      function renderUpdate(result: Updates) {
        hint.textContent = result.has_updates
          ? `目录有更新，新增 ${result.new_chapters} 项；当前共 ${result.current_total_chapters} 项。${result.latest_chapter_title}`
          : `已是最新，共 ${result.current_total_chapters} 项。`;
        if (result.has_updates && !actions.querySelector('[data-incremental]')) {
          const item = button('增量更新至最新', updateAction, true);
          item.dataset.incremental = 'true';
          actions.append(item);
        }
      }
      const cached = updates.get(job.job_id);
      if (cached) renderUpdate(cached);
      info.append(actions, hint);
      root.append(card);
    }
    const pages = el('div', 'fq-pagination');
    if (historyPage > 1)
      pages.append(
        button(
          '上一页',
          () => {
            historyPage--;
            void run(showHistory);
          },
          true,
        ),
      );
    pages.append(el('span', 'fq-muted', `第 ${historyPage} 页`));
    if (data.has_more)
      pages.append(
        button(
          '下一页',
          () => {
            historyPage++;
            void run(showHistory);
          },
          true,
        ),
      );
    root.append(pages);
    window.clearTimeout(timer);
    if (data.items.some((job) => ['queued', 'running', 'retry'].includes(job.status)))
      timer = window.setTimeout(() => {
        void run(showHistory);
      }, 5000);
  }
  // The search form can render immediately. All API actions still require
  // a valid server-issued token, checked asynchronously.
  if (activeMode === 'search') void run(showSearch);
  else root.replaceChildren(el('p', 'fq-muted', '正在载入书籍信息…'));
  void run(async () => {
    await client.authorize();
    if (controller.signal.aborted) return;
    authenticated = true;
    if (activeMode !== mode) setHeading(activeMode);
    if (activeMode === 'history') await showHistory();
    else {
      const service = await client.serviceSettings();
      if (controller.signal.aborted) return;
      if (!service.enabled) {
        root.replaceChildren(el('div', 'fq-empty', '下载器正在维护，已有文件仍可在历史下载中获取。'));
        return;
      }
      if (activeMode === 'confirm') await showConfirm();
      else if (activeMode !== 'search') await showSearch();
      if (service.paused) statusLine(root, '下载队列暂时暂停。可以提交任务，恢复后将按顺序继续处理。');
    }
  });
  return stop;
}

export function startFanqie() {
  // ClientRouter can emit page-load more than once. Only tear down a downloader
  // after its root has actually left the document, not at before-swap.
  for (const [root, stop] of active) if (!root.isConnected) stop();
  for (const root of document.querySelectorAll<HTMLElement>('[data-fanqie]')) {
    if (!active.has(root)) mountFanqie(root, (root.dataset.fanqie as ViewMode) || 'search');
  }
}
export function stopFanqie() {
  for (const root of document.querySelectorAll<HTMLElement>('[data-fanqie]')) active.get(root)?.();
}

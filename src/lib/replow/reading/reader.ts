import type Contents from 'epubjs/types/contents';
import type { NavItem } from 'epubjs/types/navigation';
import type { Location } from 'epubjs/types/rendition';
import type { FqClient } from '../fanqie/api';
import { button, el } from '../fanqie/view';
import { inspectEpub } from './epub';
import { waitForReading } from './loading';
import { localProgress, saveProgress } from './storage';
import { bindPageSwipe } from './swipe';
import type { Progress, ShelfBook } from './types';

const palettes = {
  paper: { background: '#fcfaf5', color: '#302e2a' },
  green: { background: '#dce8dc', color: '#293b30' },
  night: { background: '#191c23', color: '#c7ccd6' },
};
export async function openReader(
  uid: number,
  item: ShelfBook,
  blob: Blob,
  client: FqClient,
  signal: AbortSignal,
  onClose: () => void,
) {
  const [{ default: Book }, { default: DOMPurify }] = await Promise.all([import('epubjs'), import('dompurify')]);
  signal.throwIfAborted();
  const epub = Book();
  let closed = false;
  let opening = true;
  let saveTimer = 0;
  let current: Progress | undefined;
  const listeners = new AbortController();
  const dialog = el('dialog', 'reading-dialog');
  dialog.setAttribute('aria-label', `${item.title} EPUB 阅读器`);
  const top = el('div', 'reading-toolbar');
  const title = el('strong', 'reading-title', item.title);
  const status = el('p', 'reading-position', '正在打开 EPUB…');
  status.setAttribute('aria-live', 'polite');
  const toc = el('select');
  toc.setAttribute('aria-label', '章节目录');
  const controls = el('div', 'reading-controls');
  const settings = el('div', 'reading-settings');
  settings.id = 'reading-preferences';
  settings.hidden = true;
  settings.setAttribute('role', 'region');
  settings.setAttribute('aria-label', '阅读设置');
  const toggleSettings = button(
    '设置',
    () => {
      settings.hidden = !settings.hidden;
      toggleSettings.setAttribute('aria-expanded', String(!settings.hidden));
      if (!settings.hidden) size.focus();
    },
    true,
  );
  toggleSettings.setAttribute('aria-expanded', 'false');
  toggleSettings.setAttribute('aria-controls', settings.id);
  const size = el('input');
  size.type = 'range';
  size.min = '14';
  size.max = '32';
  size.step = '1';
  size.setAttribute('aria-label', '字号');
  size.value = '20';
  const theme = el('select');
  theme.setAttribute('aria-label', '阅读主题');
  for (const [value, label] of [
    ['paper', '纸张'],
    ['green', '护眼'],
    ['night', '夜间'],
  ]) {
    const option = el('option', '', label);
    option.value = value;
    theme.append(option);
  }
  const flow = el('select');
  flow.setAttribute('aria-label', '阅读模式');
  for (const [value, label] of [
    ['paginated', '左右翻页'],
    ['scrolled-doc', '上下滚动'],
  ]) {
    const option = el('option', '', label);
    option.value = value;
    flow.append(option);
  }
  try {
    const old = JSON.parse(localStorage.getItem(`miro.reader.settings.${uid}`) || '{}') as { size?: number; theme?: string };
    if (old.size) size.value = String(Math.min(32, Math.max(14, old.size)));
    if (old.theme && old.theme in palettes) theme.value = old.theme;
  } catch {
    /* Defaults work when browser settings are unavailable. */
  }
  const viewport = el('div', 'reading-viewport');
  const footer = el('div', 'reading-bottom');
  const sync = el('span', 'reading-sync', '进度保存在本机');
  async function flush() {
    window.clearTimeout(saveTimer);
    if (!current) return;
    const snapshot = { ...current };
    try {
      await saveProgress(uid, item.id, snapshot);
    } catch {
      if (!closed) sync.textContent = '本地空间不足，正在同步进度';
    }
    try {
      await client.request(`/reading/shelf/${item.id}/progress`, {
        cfi: snapshot.cfi,
        percentage: snapshot.percentage,
        chapter: snapshot.chapter,
        read_chapters: snapshot.read_chapters,
        total_chapters: snapshot.total_chapters,
      });
      if (!closed) sync.textContent = '进度已同步';
    } catch {
      if (!closed) sync.textContent = '进度已保存在本机，联网后同步';
    }
  }
  function cleanup() {
    if (closed) return;
    closed = true;
    window.clearTimeout(saveTimer);
    observer.disconnect();
    listeners.abort();
    if (!opening) epub.destroy();
    dialog.remove();
    signal.removeEventListener('abort', cleanup);
    onClose();
  }
  const close = button(
    '返回书架',
    () => {
      void flush();
      cleanup();
    },
    true,
  );
  top.append(close, title);
  controls.append(toc, toggleSettings);
  const sizeLabel = el('label', 'reading-setting');
  const sizeValue = el('output', '', size.value);
  sizeValue.setAttribute('aria-hidden', 'true');
  sizeLabel.append(el('span', '', '字号'), size, sizeValue);
  const themeLabel = el('label', 'reading-setting');
  themeLabel.append(el('span', '', '纸张'), theme);
  const flowLabel = el('label', 'reading-setting');
  flowLabel.append(el('span', '', '阅读模式'), flow);
  settings.append(
    sizeLabel,
    themeLabel,
    flowLabel,
    el('p', 'reading-gesture-hint', '左右滑动翻页 · 底部按钮切换章节；手机选择文字请用上下滚动模式'),
  );
  footer.append(status, sync);
  dialog.append(top, controls, settings, viewport, footer);
  document.body.append(dialog);
  const observer = new ResizeObserver(() => {
    if (!closed && epub.rendition) epub.rendition.resize(viewport.clientWidth, viewport.clientHeight);
  });
  signal.addEventListener('abort', cleanup, { once: true });
  dialog.addEventListener('cancel', (event) => {
    event.preventDefault();
    if (!settings.hidden) {
      settings.hidden = true;
      toggleSettings.setAttribute('aria-expanded', 'false');
      toggleSettings.focus();
      return;
    }
    void flush();
    cleanup();
  });
  const waitFor = <T>(task: Promise<T>, stage: string) => waitForReading(task, listeners.signal, stage);
  dialog.showModal();
  try {
    const { buffer } = await waitFor(inspectEpub(blob), '解析 EPUB');
    status.textContent = '正在加载目录与资源…';
    await waitFor(epub.open(buffer, 'binary'), '读取 EPUB');
    await waitFor(Promise.all([epub.ready, epub.opened]), '加载目录与资源');
    opening = false;
    if (closed) {
      epub.destroy();
      return;
    }
    signal.throwIfAborted();
    if (closed) return;
    epub.spine.hooks.serialize.register((_output: string, section: { output: string }) => {
      section.output = DOMPurify.sanitize(section.output, {
        WHOLE_DOCUMENT: true,
        ADD_ATTR: ['epub:type'],
        FORBID_TAGS: ['script', 'iframe', 'object', 'embed', 'form'],
      });
    });
    const rendition = epub.renderTo(viewport, {
      width: '100%',
      height: '100%',
      spread: 'none',
      flow: 'paginated',
      allowScriptedContent: false,
    });
    const spine = await epub.loaded.spine;
    const navigation = await epub.loaded.navigation;
    const chapterIndices: number[] = [];
    epub.spine.each((section: { index: number; linear: boolean; properties: string[] }) => {
      if (section.linear && !section.properties.includes('nav')) chapterIndices.push(section.index);
    });
    function appendNav(items: NavItem[], depth = 0) {
      for (const entry of items) {
        const option = el('option', '', '　'.repeat(Math.min(depth, 4)) + entry.label.trim());
        option.value = entry.href;
        toc.append(option);
        if (entry.subitems) appendNav(entry.subitems, depth + 1);
      }
    }
    appendNav(navigation.toc);
    if (!toc.options.length) {
      epub.spine.each((section: { href: string; linear: boolean }) => {
        if (!section.linear) return;
        const option = el('option', '', `第 ${toc.options.length + 1} 章`);
        option.value = section.href;
        toc.append(option);
      });
    }
    if (!toc.options.length) {
      const option = el('option', '', '正文');
      option.value = '';
      toc.append(option);
    }
    function preferences() {
      const palette = palettes[theme.value as keyof typeof palettes] || palettes.paper;
      dialog.style.background = palette.background;
      dialog.style.color = palette.color;
      const paged = flow.value === 'paginated';
      dialog.classList.toggle('reading-paged', paged);
      const touchAction = paged ? 'pinch-zoom' : 'auto';
      viewport.style.touchAction = touchAction;
      rendition.themes.default({
        html: { 'touch-action': `${touchAction} !important`, 'overscroll-behavior-x': 'contain' },
        body: {
          'touch-action': `${touchAction} !important`,
          background: `${palette.background} !important`,
          color: `${palette.color} !important`,
          'font-family': 'Georgia, "Noto Serif SC", "Songti SC", serif',
          'font-size': `${size.value}px !important`,
          'line-height': '1.95 !important',
          padding: '12px 22px !important',
        },
        p: { 'line-height': '1.95 !important', 'text-align': 'justify' },
        img: { 'max-width': '100% !important', height: 'auto !important' },
        a: { color: 'inherit !important' },
      });
      sizeValue.value = size.value;
      try {
        localStorage.setItem(`miro.reader.settings.${uid}`, JSON.stringify({ size: Number(size.value), theme: theme.value }));
      } catch {
        /* Reading still works. */
      }
    }
    preferences();
    const fail = (error: unknown) => {
      if (!closed) status.textContent = error instanceof Error ? error.message : '翻页失败，请重试。';
    };
    let navigating = false;
    let activeIndex = 0;
    const adjacentChapter = (direction: 'next' | 'prev') => {
      const section = epub.spine.get(activeIndex);
      return section?.[direction]();
    };
    const previousChapter = button('上一章', () => chapter('prev'), true);
    const nextChapter = button('下一章', () => chapter('next'), true);
    previousChapter.disabled = true;
    nextChapter.disabled = true;
    function updateChapterButtons() {
      previousChapter.disabled = navigating || !adjacentChapter('prev');
      nextChapter.disabled = navigating || !adjacentChapter('next');
    }
    async function navigate(action: () => Promise<unknown>) {
      if (closed || navigating) return;
      navigating = true;
      updateChapterButtons();
      try {
        await action();
      } catch (error) {
        fail(error);
      } finally {
        navigating = false;
        if (!closed) updateChapterButtons();
      }
    }
    const turn = (direction: 'next' | 'prev') => {
      void navigate(() => rendition[direction]());
    };
    function chapter(direction: 'next' | 'prev') {
      const target = adjacentChapter(direction);
      if (target?.href) void navigate(() => rendition.display(target.href));
    }
    footer.prepend(previousChapter);
    footer.append(nextChapter);
    const keys = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) return;
      if (event.key === 'ArrowRight') {
        event.preventDefault();
        turn('next');
      }
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        turn('prev');
      }
    };
    dialog.addEventListener('keydown', keys);
    rendition.on('rendered', () => {
      preferences();
    });
    const canSwipe = () => !closed && !navigating && flow.value === 'paginated';
    bindPageSwipe(viewport, turn, canSwipe, listeners.signal);
    rendition.hooks.content.register((contents: Contents) => {
      const doc = contents.document;
      doc.addEventListener('keydown', keys);
      bindPageSwipe(doc, turn, canSwipe, listeners.signal);
    });
    rendition.on('relocated', (location: Location) => {
      if (closed) return;
      const start = location.start;
      activeIndex = start.index;
      updateChapterButtons();
      const chapter = navigation.get(start.href)?.label?.trim() || toc.selectedOptions[0]?.textContent || '正文';
      const fraction = (start.displayed.page - 1) / Math.max(1, start.displayed.total);
      const percentage = location.atEnd
        ? 100
        : Math.min(100, Math.max(0, ((start.index + fraction) / Math.max(1, spine.length)) * 100));
      const total_chapters = chapterIndices.length;
      const read_chapters = location.atEnd ? total_chapters : chapterIndices.filter((index) => index <= start.index).length;
      current = { cfi: start.cfi, percentage, chapter, updated: Date.now(), read_chapters, total_chapters };
      item.read_chapters = read_chapters;
      item.total_chapters = total_chapters;
      item.cfi = start.cfi;
      item.percentage = percentage;
      item.chapter = chapter;
      item.updated_at = Date.now() / 1000;
      status.textContent = `${chapter} · 约 ${percentage.toFixed(1)}%`;
      const matching = Array.from(toc.options).find((x) => x.value.split('#')[0] === start.href.split('#')[0]);
      if (matching) toc.value = matching.value;
      sync.textContent = '进度已保存在本机';
      void saveProgress(uid, item.id, current).catch(() => {
        sync.textContent = '本地存储空间不足，进度暂存于本页';
      });
      window.clearTimeout(saveTimer);
      saveTimer = window.setTimeout(() => {
        void flush();
      }, 900);
    });
    const local = await waitFor(localProgress(uid, item.id), '读取阅读进度');
    const position = local && local.updated > item.updated_at * 1000 ? local.cfi : item.cfi;
    async function display(target?: string) {
      // epub.js emits displayError but does not reject display() for a failed chapter load.
      let rejectDisplay: (error: unknown) => void = () => {};
      const failed = new Promise<never>((_resolve, reject) => {
        rejectDisplay = reject;
      });
      rendition.on('displayError', rejectDisplay);
      try {
        await waitFor(Promise.race([rendition.display(target), failed]), '显示章节');
      } finally {
        rendition.off('displayError', rejectDisplay);
      }
    }
    status.textContent = '正在显示章节…';
    try {
      await display(position || undefined);
    } catch (error) {
      if (!position || closed) throw error;
      await display();
      status.textContent = '原阅读位置已失效，已从开头打开。';
    }
    if (closed) return;
    toc.addEventListener('change', () => {
      void navigate(() => rendition.display(toc.value || undefined));
    });
    size.addEventListener('input', preferences);
    theme.addEventListener('change', preferences);
    flow.addEventListener('change', () => {
      rendition.flow(flow.value);
      preferences();
    });
    observer.observe(viewport);
  } catch (error) {
    opening = false;
    if (closed) {
      epub.destroy();
      return;
    }
    cleanup();
    throw error;
  }
}

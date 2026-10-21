import { type CommentItem, createCommentsApi, identity, message } from './api';
import { escapeHtml, markdown, safeUrl } from './markdown';

let cleanup: (() => void) | undefined;
function mount(root: HTMLElement) {
  const controller = new AbortController(),
    { signal } = controller;
  const api = createCommentsApi(signal);
  const find = <T extends HTMLElement>(selector: string) => {
    const element = root.querySelector<T>(selector);
    if (!element) throw new Error(selector);
    return element;
  };
  const body = find<HTMLTextAreaElement>('[data-comment-body]');
  const submit = find<HTMLButtonElement>('[data-comment-submit]');
  const upload = find<HTMLButtonElement>('[data-upload-image]');
  const file = find<HTMLInputElement>('[data-comment-file]');
  const preview = find('[data-comment-preview]');
  const status = find('[data-comment-status]');
  const more = find<HTMLButtonElement>('[data-comment-more]');
  const article = Number(root.dataset.articleId);
  let items: CommentItem[] = [],
    total = 0,
    replying: CommentItem | undefined;
  let sending = false,
    uploading = false,
    loading = false,
    showingPreview = false,
    lastUser = '';
  const notify = (value: string, error = false) => {
    status.textContent = value;
    status.dataset.error = String(error);
  };
  const login = find<HTMLAnchorElement>('[data-comment-login]');
  login.href =
    'https://account.replow.org/?return_to=' +
    encodeURIComponent(window.location.origin + window.location.pathname + '#comments');
  function auth() {
    const user = identity(),
      name = user?.username || '';
    const changed = !!lastUser && name !== lastUser;
    lastUser = name;
    if (changed) {
      body.value = '';
      replying = undefined;
      showReply();
      updatePreview();
    }
    body.disabled = !user || sending;
    submit.disabled = !user || sending || uploading || !body.value.trim();
    upload.disabled = !user || uploading || sending;
    for (const button of root.querySelectorAll<HTMLButtonElement>('[data-format]'))
      button.disabled = !user || sending || showingPreview;
    login.hidden = !!user;
    find('[data-comment-identity]').textContent = user
      ? '以 ' + (user.nickname || user.username) + ' 的身份评论'
      : '登录后加入讨论';
    submit.textContent = sending ? '正在发布…' : replying ? '发送回复 ↗' : '发表评论 ↗';
    upload.textContent = uploading ? '上传中…' : '＋ 图片';
  }
  function showReply() {
    find('[data-replying]').hidden = !replying;
    find('[data-reply-name]').textContent = replying ? '回复 @' + replying.user_name : '';
    auth();
  }
  function updatePreview() {
    if (showingPreview) preview.innerHTML = markdown(body.value || '还没有写下内容。');
  }
  function render() {
    const byId = new Map(items.map((item) => [item.id, item]));
    const groups = new Map<number, CommentItem[]>();
    for (const item of items) {
      let ancestor = item;
      const visited = new Set<number>([item.id]);
      while (ancestor.parent_id && byId.has(ancestor.parent_id) && !visited.has(ancestor.parent_id)) {
        visited.add(ancestor.parent_id);
        ancestor = byId.get(ancestor.parent_id) as CommentItem;
      }
      const group = groups.get(ancestor.id) || [];
      group.push(item);
      groups.set(ancestor.id, group);
    }
    const card = (item: CommentItem, child: boolean) => {
      const parent = item.parent_id ? byId.get(item.parent_id) : undefined;
      const name = escapeHtml(item.user_name || '用户'),
        avatar = safeUrl(item.user_avatar || '');
      const date = new Date(item.created_at.replace(/(?<!Z)$/, 'Z'));
      const dateText = Number.isNaN(date.getTime())
        ? ''
        : date.toLocaleString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
      return (
        '<article class="discussion-comment' +
        (child ? ' is-reply' : '') +
        '" id="comment-' +
        item.id +
        '"><div class="discussion-avatar">' +
        (avatar
          ? '<img src="' + escapeHtml(avatar) + '" alt="" loading="lazy" referrerpolicy="no-referrer">'
          : escapeHtml((item.user_name || '用').slice(0, 1))) +
        '</div><div class="discussion-comment-main"><header><strong>' +
        name +
        '</strong>' +
        (parent ? '<span class="discussion-reply-target">回复 @' + escapeHtml(parent.user_name) + '</span>' : '') +
        '<time>' +
        escapeHtml(dateText) +
        (item.edited_at ? ' · 已编辑' : '') +
        '</time></header><div class="discussion-markdown">' +
        markdown(item.body_markdown) +
        '</div><button type="button" class="discussion-reply-button" data-reply-id="' +
        item.id +
        '">回复 ↗</button></div></article>'
      );
    };
    find('[data-comment-list]').innerHTML = [...groups.values()]
      .map((group) => '<div class="discussion-thread">' + group.map((item, index) => card(item, index > 0)).join('') + '</div>')
      .join('');
    find('[data-comment-count]').textContent = String(total);
    more.hidden = items.length >= total;
    more.disabled = loading;
  }
  async function load(reset = false, target?: number) {
    if (loading) return;
    loading = true;
    more.disabled = true;
    try {
      if (reset) items = [];
      do {
        const page = await api.list(article, items.length);
        total = page.total;
        const known = new Set(items.map((item) => item.id));
        items = [...items, ...page.items.filter((item) => !known.has(item.id))];
        if (!page.items.length) break;
      } while (target && !items.some((item) => item.id === target) && items.length < total);
      render();
      notify(total ? '共 ' + total + ' 条评论 · 回复后会在个人中心通知对方' : '还没有评论，来留下第一条想法吧。');
      if (target) document.getElementById('comment-' + target)?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    } catch (error) {
      if (!signal.aborted) {
        notify(message(error), true);
        more.hidden = false;
        more.textContent = '重新加载';
      }
    } finally {
      loading = false;
      more.disabled = false;
    }
  }
  function insert(before: string, after = '') {
    if (!identity() || sending || uploading) return;
    showingPreview = false;
    preview.hidden = true;
    body.hidden = false;
    find('[data-toggle-preview]').setAttribute('aria-pressed', 'false');
    const start = body.selectionStart,
      end = body.selectionEnd,
      selected = body.value.slice(start, end);
    body.setRangeText(before + selected + after, start, end, 'end');
    body.focus();
    auth();
  }
  async function uploadFile(image: File) {
    if (uploading || sending || !identity()) return;
    if (image.size > 5 * 1024 * 1024) {
      notify('图片不能超过 5 MB。', true);
      return;
    }
    uploading = true;
    auth();
    notify('正在上传图片…');
    const user = identity()?.username;
    try {
      const result = await api.upload(image);
      if (identity()?.username !== user) return;
      // Allow the insertion after upload completes; uploads never publish a comment.
      uploading = false;
      insert('\n![图片](' + result.data.url + ')\n');
      notify('图片已插入，可预览后发布。');
    } catch (error) {
      if (!signal.aborted) notify(message(error), true);
    } finally {
      uploading = false;
      file.value = '';
      auth();
    }
  }
  body.addEventListener(
    'input',
    () => {
      auth();
      updatePreview();
    },
    { signal },
  );
  body.addEventListener(
    'paste',
    (event) => {
      const image = [...(event.clipboardData?.files || [])].find((item) => item.type.startsWith('image/'));
      if (image) {
        event.preventDefault();
        void uploadFile(image);
      }
    },
    { signal },
  );
  root.addEventListener(
    'click',
    (event) => {
      const button = (event.target as HTMLElement).closest<HTMLElement>('button');
      if (!button) return;
      if (button.hasAttribute('data-cancel-reply')) {
        replying = undefined;
        showReply();
      }
      if (button.dataset.replyId) {
        if (!identity()) {
          notify('登录后即可回复。');
          login.focus();
          return;
        }
        replying = items.find((item) => item.id === Number(button.dataset.replyId));
        showReply();
        root.querySelector('[data-editor]')?.scrollIntoView({ block: 'center', behavior: 'smooth' });
        body.focus();
      }
      const formats: Record<string, [string, string]> = {
        bold: ['**', '**'],
        italic: ['*', '*'],
        code: ['\n```\n', '\n```\n'],
        quote: ['\n> ', ''],
      };
      if (button.dataset.format) {
        const format = formats[button.dataset.format];
        if (format) insert(...format);
      }
      if (button.hasAttribute('data-upload-image')) file.click();
      if (button.hasAttribute('data-toggle-preview')) {
        showingPreview = !showingPreview;
        preview.hidden = !showingPreview;
        body.hidden = showingPreview;
        button.setAttribute('aria-pressed', String(showingPreview));
        button.textContent = showingPreview ? '继续编辑' : '预览';
        updatePreview();
        auth();
      }
    },
    { signal },
  );
  file.addEventListener(
    'change',
    () => {
      if (file.files?.[0]) void uploadFile(file.files[0]);
    },
    { signal },
  );
  submit.addEventListener(
    'click',
    async () => {
      if (sending || uploading || !body.value.trim()) return;
      sending = true;
      auth();
      const user = identity()?.username;
      try {
        const result = await api.create({ article_id: article, parent_id: replying?.id ?? null, body_markdown: body.value });
        if (identity()?.username !== user) return;
        body.value = '';
        replying = undefined;
        showingPreview = false;
        preview.hidden = true;
        body.hidden = false;
        find('[data-toggle-preview]').textContent = '预览';
        find('[data-toggle-preview]').setAttribute('aria-pressed', 'false');
        showReply();
        await load(true, result.data.id);
        notify('发布成功。' + (total ? '对话已更新。' : ''));
      } catch (error) {
        if (!signal.aborted) notify(message(error), true);
      } finally {
        sending = false;
        auth();
      }
    },
    { signal },
  );
  more.addEventListener('click', () => void load(), { signal });
  document.addEventListener('replow:auth', auth, { signal });
  document.addEventListener('replow:signout', auth, { signal });
  const focusHash = () => {
    const target = Number(location.hash.match(/^#comment-(\d+)$/)?.[1]);
    if (target) void load(false, target);
  };
  window.addEventListener('hashchange', focusHash, { signal });
  auth();
  void load(false, Number(location.hash.match(/^#comment-(\d+)$/)?.[1]) || undefined);
  return () => controller.abort();
}
export function startComments() {
  cleanup?.();
  cleanup = undefined;
  const root = document.querySelector<HTMLElement>('[data-discussion]');
  if (root) cleanup = mount(root);
}
if (typeof document !== 'undefined')
  document.addEventListener('astro:before-swap', () => {
    cleanup?.();
    cleanup = undefined;
  });

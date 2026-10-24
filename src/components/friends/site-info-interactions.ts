let dispose: (() => void) | undefined;

async function copyText(value: string) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(value);
      return;
    } catch {
      // Clipboard permissions may be unavailable; try the selection-based fallback below.
    }
  }

  const textarea = document.createElement('textarea');
  textarea.value = value;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.left = '0';
  textarea.style.top = '0';
  textarea.style.opacity = '0';
  textarea.style.pointerEvents = 'none';
  document.body.append(textarea);
  textarea.select();
  const copied = document.execCommand('copy');
  textarea.remove();

  if (!copied) throw new Error('Clipboard copy failed');
}

function init() {
  dispose?.();
  const controller = new AbortController();
  const timers = new Set<number>();

  document.addEventListener(
    'click',
    async (event) => {
      const button =
        event.target instanceof Element
          ? event.target.closest<HTMLButtonElement>('[data-site-info-copy]')
          : null;
      if (!button || button.disabled) return;

      const value = button.dataset.copyValue;
      const label = button.dataset.copyLabel ?? '内容';
      const text = button.querySelector<HTMLElement>('[data-copy-label-text]');
      if (!value || !text) return;

      button.disabled = true;
      try {
        await copyText(value);
        text.textContent = '已复制';
        button.dataset.copySuccess = 'true';
        button.setAttribute('aria-label', '已复制' + label);
      } catch {
        text.textContent = '复制失败';
        button.setAttribute('aria-label', '复制' + label + '失败，请重试');
      }

      const timer = window.setTimeout(() => {
        text.textContent = '复制';
        delete button.dataset.copySuccess;
        button.disabled = false;
        button.setAttribute('aria-label', '复制' + label);
        timers.delete(timer);
      }, 1800);
      timers.add(timer);
    },
    { signal: controller.signal },
  );

  dispose = () => {
    controller.abort();
    for (const timer of timers) window.clearTimeout(timer);
    timers.clear();
  };
}

if (document.readyState !== 'loading') init();
document.addEventListener('astro:page-load', init);
document.addEventListener('astro:before-swap', () => {
  dispose?.();
  dispose = undefined;
});

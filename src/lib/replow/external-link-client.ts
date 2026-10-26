import { guardedLink } from './external-link';

export function installExternalLinkGuard(): void {
  let observer: MutationObserver | undefined;
  const rewrite = (anchor: HTMLAnchorElement) => {
    const href = anchor.getAttribute('href');
    if (!href) return;
    const guarded = guardedLink(href, window.location.href);
    if (guarded !== href) {
      anchor.setAttribute('href', guarded);
      anchor.removeAttribute('download');
    }
  };
  const scan = (root: ParentNode) => {
    if (root instanceof HTMLAnchorElement) rewrite(root);
    root.querySelectorAll<HTMLAnchorElement>('a[href]').forEach(rewrite);
  };
  const init = () => {
    observer?.disconnect();
    scan(document);
    observer = new MutationObserver((records) => {
      for (const record of records) {
        if (record.type === 'attributes' && record.target instanceof HTMLAnchorElement) rewrite(record.target);
        for (const node of record.addedNodes) if (node instanceof Element) scan(node);
      }
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['href'] });
  };
  // Capture also covers links inserted and activated within the same browser task.
  const onActivate = (event: MouseEvent) => {
    const target = event.target instanceof Element ? event.target.closest<HTMLAnchorElement>('a[href]') : null;
    if (target) rewrite(target);
  };
  document.addEventListener('click', onActivate, true);
  document.addEventListener('auxclick', onActivate, true);
  document.addEventListener('astro:before-swap', () => observer?.disconnect());
  document.addEventListener('astro:page-load', init);
  if (document.readyState !== 'loading') init();
  else document.addEventListener('DOMContentLoaded', init, { once: true });
}

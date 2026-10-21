import { closeDrawer } from '@store/modal';

/** Measure the full desktop row even while collapsed, so the breakpoint follows its content. */
export function observeHeaderNavigation(): () => void {
  const header = document.getElementById('site-header');
  const content = header?.querySelector<HTMLElement>('.header-content');
  const logo = header?.querySelector<HTMLElement>('.header-desktop-logo');
  const nav = header?.querySelector<HTMLElement>('.header-desktop-nav');
  const actions = header?.querySelector<HTMLElement>('.header-actions');
  if (!header || !content || !logo || !nav || !actions) return () => {};

  const tablet = window.matchMedia('(max-width: 992px)');
  let frame = 0;
  const measure = () => {
    const logoStyle = getComputedStyle(logo);
    const required = logo.offsetWidth + Number.parseFloat(logoStyle.marginRight) + nav.offsetWidth + actions.offsetWidth;
    const compact = tablet.matches || required + 2 > content.clientWidth;
    if (header.hasAttribute('data-nav-compact') && !compact) closeDrawer();
    header.toggleAttribute('data-nav-compact', compact);
    // Hidden measurement elements must not remain in the keyboard or accessibility navigation.
    nav.inert = compact;
    logo.inert = compact;
  };
  const schedule = () => {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(measure);
  };
  const observer = new ResizeObserver(schedule);
  for (const element of [content, logo, nav, actions]) observer.observe(element);
  tablet.addEventListener('change', schedule);
  document.fonts.addEventListener('loadingdone', schedule);
  measure();

  return () => {
    cancelAnimationFrame(frame);
    observer.disconnect();
    tablet.removeEventListener('change', schedule);
    document.fonts.removeEventListener('loadingdone', schedule);
  };
}

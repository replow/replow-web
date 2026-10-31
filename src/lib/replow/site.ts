import DOMPurify from 'dompurify';
import snapshot from '@/data/replow.json';
import { applyBranding } from './branding';
export type PublicSite = typeof snapshot;

function releaseFooter(html: string): string {
  const [version, update] = snapshot.version.split('-u');
  return html
    .replace(/(href=["'])https:\/\/api\.4z\.ink\/?(["'])/gi, '$1https://status.4z.ink$2')
    .replace(/>API\s*站<\/a>/gi, '>Status</a>')
    .replace(/Theme\s+Firefly/gi, 'Theme astro-koharu')
    .replace(/Version[：:]\s*v[\d.]+/g, 'Version：' + version)
    .replace(/Update[：:]\s*\d+/g, 'Update：' + update);
}
function setText(selector: string, value: string) {
  for (const element of document.querySelectorAll(selector)) element.textContent = value;
}
export function updateUptime() {
  for (const element of document.querySelectorAll<HTMLElement>('[data-site-uptime]')) {
    const start = Date.parse(element.dataset.start || '2026-07-01T00:00:00Z');
    const seconds = Math.max(0, Math.floor((Date.now() - start) / 1000));
    element.textContent =
      Math.floor(seconds / 86400) +
      '天 ' +
      Math.floor((seconds / 3600) % 24) +
      '时 ' +
      Math.floor((seconds / 60) % 60) +
      '分 ' +
      (seconds % 60) +
      '秒';
  }
}
export function applySite(payload: PublicSite) {
  if (!payload?.site || !payload.profile || !payload.firefly) return;
  const config = payload.firefly;
  applyBranding(payload);
  setText('.home-name, [data-runtime-profile-name]', payload.profile.name);
  setText('.home-description', payload.profile.intro);
  setText('[data-runtime-hero-title]', config.koharuConfig?.heroTitle || 'Silver Wolf');
  for (const img of document.querySelectorAll<HTMLImageElement>('.home-avatar img')) {
    if (img.getAttribute('src') !== payload.profile.avatar_url) {
      img.src = payload.profile.avatar_url;
      img.removeAttribute('srcset');
    }
  }
  for (const picture of document.querySelectorAll<HTMLElement>('[data-replow-wallpaper]')) {
    const img = picture.querySelector<HTMLImageElement>('img');
    const source = picture.querySelector<HTMLSourceElement>('source');
    const desktop = payload.theme.desktop_background_url;
    const mobile = payload.theme.mobile_background_url || desktop;
    if (img && desktop && img.getAttribute('src') !== desktop) img.src = desktop;
    if (source && mobile && source.getAttribute('srcset') !== mobile) source.srcset = mobile;
    picture
      .closest<HTMLElement>('.cover-hero')
      ?.classList.toggle('replow-wallpaper-disabled', config.backgroundWallpaper?.mode === 'none');
  }
  const footer = config.footerConfig;
  const html = releaseFooter(footer.customHtml || '');
  for (const element of document.querySelectorAll<HTMLElement>('[data-runtime-footer]'))
    element.hidden = footer.enable === false;
  for (const element of document.querySelectorAll<HTMLElement>('[data-runtime-footer-content]')) {
    if (element.dataset.currentHtml !== html) {
      element.innerHTML = DOMPurify.sanitize(html, {
        ADD_ATTR: ['data-runtime-profile-name', 'data-site-uptime', 'data-start', 'data-footer-year'],
      });
      element.dataset.currentHtml = html;
    }
  }
  for (const element of document.querySelectorAll<HTMLElement>('[data-replow-announcement]')) {
    element.hidden = !payload.announcement.enabled || config.announcementConfig.enable === false;
    const title = element.querySelector('[data-announcement-title]');
    const body = element.querySelector('[data-announcement-body]');
    if (title) title.textContent = payload.announcement.title;
    if (body) body.textContent = payload.announcement.body_markdown;
  }
  document.documentElement.style.setProperty('--replow-page-width', String(config.siteConfig.pageWidth || 120) + 'rem');
  document.querySelectorAll<HTMLElement>('.page-home-sider').forEach((element) => {
    element.hidden = config.sidebarLayoutConfig?.enable === false;
  });
  for (const link of config.profileConfig.links || []) {
    for (const element of document.querySelectorAll<HTMLAnchorElement>('.home-social a[data-platform]')) {
      if (element.dataset.platform === link.name && /^(https?:\/\/|mailto:)/.test(link.url)) element.href = link.url;
    }
  }
  setText('[data-footer-year]', String(new Date().getFullYear()));
  updateUptime();
}

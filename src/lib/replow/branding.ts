export interface BrandingSource {
  site?: { name?: string; url?: string; icon_url?: string; description?: string };
  profile?: { avatar_url?: string };
  firefly?: Record<string, unknown>;
}

function webUrl(value: unknown, fallback: string): string {
  if (typeof value !== 'string') return fallback;
  const url = value.trim();
  return /^(https?:\/\/|\/(?!\/))/.test(url) ? url : fallback;
}

export function resolveBranding(source: BrandingSource) {
  const raw = source.firefly?.friendSiteInfo;
  const info = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  const avatar = webUrl(source.profile?.avatar_url, '/favicon.ico');
  return {
    icon: webUrl(source.site?.icon_url, avatar),
    name: typeof info.name === 'string' ? info.name : source.site?.name || '',
    description: typeof info.description === 'string' ? info.description : source.site?.description || '',
    url: webUrl(info.url, webUrl(source.site?.url, 'https://www.replow.org/')),
    avatar: webUrl(info.avatar_url, avatar),
  };
}

export function applyBranding(source: BrandingSource) {
  const branding = resolveBranding(source);
  for (const link of document.querySelectorAll<HTMLLinkElement>('link[rel="icon"], link[rel="apple-touch-icon"]')) {
    link.removeAttribute('type');
    if (link.getAttribute('href') !== branding.icon) link.setAttribute('href', branding.icon);
  }
  const values = { name: branding.name, url: branding.url, avatar: branding.avatar, description: branding.description };
  for (const [key, value] of Object.entries(values)) {
    for (const field of document.querySelectorAll<HTMLElement>(`[data-site-info-field="${key}"]`)) {
      const text = field.querySelector<HTMLElement>('.site-info-value');
      if (text) {
        text.textContent = value;
        if (text instanceof HTMLAnchorElement) text.href = branding.url;
      }
      const button = field.querySelector<HTMLButtonElement>('[data-site-info-copy]');
      if (button) button.dataset.copyValue = value;
    }
  }
  for (const image of document.querySelectorAll<HTMLImageElement>('[data-site-info-avatar]')) {
    if (image.getAttribute('src') !== branding.avatar) image.src = branding.avatar;
    image.alt = branding.name + '站点头像';
  }
}

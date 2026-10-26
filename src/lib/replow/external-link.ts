const OWN_DOMAINS = ['replow.org', '4z.ink', 'ronova.top'];

export function parseWebUrl(value: string, base?: string): URL | null {
  try {
    const url = new URL(value, base);
    return ['http:', 'https:'].includes(url.protocol) ? url : null;
  } catch {
    return null;
  }
}

export function isOwnHostname(hostname: string): boolean {
  const host = hostname.toLowerCase().replace(/\.$/, '');
  return OWN_DOMAINS.some((domain) => host === domain || host.endsWith('.' + domain));
}

export function guardedLink(value: string, base: string): string {
  const url = parseWebUrl(value, base);
  if (!url || isOwnHostname(url.hostname)) return value;
  return '/go/?url=' + encodeURIComponent(url.href);
}

/** Confirmation never accepts script URLs, relative targets or embedded credentials. */
export function confirmationTarget(value: string): URL | null {
  const url = parseWebUrl(value);
  return url && !url.username && !url.password ? url : null;
}

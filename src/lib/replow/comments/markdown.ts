import DOMPurify from 'dompurify';
import { marked } from 'marked';

export function safeUrl(value: string): string {
  if (!value.trim()) return '';
  try {
    const url = new URL(value, window.location.origin);
    return ['https:', 'http:'].includes(url.protocol) ? url.href : '';
  } catch {
    return '';
  }
}
export function markdown(value: string): string {
  const html = DOMPurify.sanitize(marked.parse(value, { async: false, gfm: true, breaks: true }), {
    ALLOWED_TAGS: [
      'p',
      'br',
      'strong',
      'em',
      'del',
      'blockquote',
      'ul',
      'ol',
      'li',
      'pre',
      'code',
      'a',
      'img',
      'hr',
      'h1',
      'h2',
      'h3',
      'h4',
      'table',
      'thead',
      'tbody',
      'tr',
      'th',
      'td',
    ],
    ALLOWED_ATTR: ['href', 'src', 'alt', 'title'],
    ALLOW_DATA_ATTR: false,
  });
  const template = document.createElement('template');
  template.innerHTML = html;
  for (const link of template.content.querySelectorAll('a')) {
    const url = safeUrl(link.getAttribute('href') || '');
    if (!url) link.removeAttribute('href');
    else link.href = url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer nofollow ugc';
  }
  for (const image of template.content.querySelectorAll('img')) {
    const url = safeUrl(image.getAttribute('src') || '');
    if (!url) {
      image.remove();
      continue;
    }
    image.src = url;
    image.loading = 'lazy';
    image.decoding = 'async';
    image.referrerPolicy = 'no-referrer';
  }
  return template.innerHTML;
}
export const escapeHtml = (value: string) =>
  value.replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char] || char);

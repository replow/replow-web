import fs from 'node:fs/promises';
import path from 'node:path';
import YAML from 'yaml';
import { articleMarkdown, DEFAULT_COVER, footerHtml, makeSiteConfig } from './replow-data.mjs';

const api = (process.env.API_BASE_URL || 'http://127.0.0.1:8800').replace(/\/+$/, '');

async function fetchJson(endpoint) {
  let last;
  for (let attempt = 0; attempt < 4; attempt++) {
    try {
      const response = await fetch(api + '/v1/public/' + endpoint, {
        signal: AbortSignal.timeout(20_000),
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) throw new Error('Public API HTTP ' + response.status);
      return await response.json();
    } catch (error) {
      last = error;
      if (attempt < 3) await new Promise((resolve) => setTimeout(resolve, 500 * 2 ** attempt));
    }
  }
  throw last;
}

const payload = await fetchJson('site');
if (!payload.site?.name || !payload.profile?.name || !payload.firefly) throw new Error('Invalid site data');
const currentFooter = String(payload.firefly.footerConfig?.customHtml || '');
const currentVersion = currentFooter.match(/Version[：:]\s*(v[\d.]+)/)?.[1];
const currentUpdate = currentFooter.match(/Update[：:]\s*(\d+)/)?.[1];
const version = process.env.REPLOW_RELEASE || (currentVersion && currentUpdate ? currentVersion + '-u' + currentUpdate : '');
if (!version) throw new Error('REPLOW_RELEASE is required when the backend has no release footer');

const articles = [];
let offset = 0;
while (true) {
  const batch = await fetchJson('articles?limit=200&offset=' + offset);
  if (!Array.isArray(batch.items) || !Number.isInteger(batch.total)) throw new Error('Invalid article response');
  articles.push(...batch.items);
  offset += batch.items.length;
  if (offset >= batch.total) break;
  if (!batch.items.length) throw new Error('Incomplete article pagination');
}
const friendsResult = await fetchJson('friends');
if (!Array.isArray(friendsResult.items)) throw new Error('Invalid friends response');
const friends = friendsResult.items;
const slugs = new Set();
for (const article of articles) {
  if (slugs.has(article.slug)) throw new Error('Duplicate public article slug');
  slugs.add(article.slug);
  articleMarkdown(article);
}

payload.firefly.koharuConfig = {
  heroTitle: 'Silver Wolf',
  navbarTitle: 'Miro',
  headerIdleMs: 400,
  postCardImagePosition: 'alternating',
  motionLevel: 'lively',
  runtimeArticles: true,
  ...payload.firefly.koharuConfig,
};

payload.firefly.announcementConfig = { enable: payload.announcement.enabled, ...payload.firefly.announcementConfig };
payload.announcement.enabled = payload.firefly.announcementConfig.enable !== false;
const base = YAML.parse(await fs.readFile('config/replow-base.yaml', 'utf8'));
const config = makeSiteConfig(base, payload, friends);
payload.firefly.footerConfig = {
  ...payload.firefly.footerConfig,
  customHtml: footerHtml(payload.firefly.footerConfig?.customHtml, version),
};
const cover = payload.firefly.backgroundWallpaper?.articlePlaceholderUrl || DEFAULT_COVER;
const staged = 'src/content/replow-staging';
await fs.rm(staged, { recursive: true, force: true });
await fs.mkdir(staged, { recursive: true });
for (const article of articles) {
  await fs.writeFile(path.join(staged, String(article.id) + '.md'), articleMarkdown(article, cover));
}
await fs.mkdir('src/data', { recursive: true });
await fs.writeFile('config/site.yaml', YAML.stringify(config));
await fs.writeFile(
  'src/data/replow.json',
  JSON.stringify(
    {
      ...payload,
      friends,
      version,
      articles: articles.map(({ id, slug, updated_at, title, cover_url, category, tags }) => ({
        id,
        slug,
        updated_at,
        title,
        cover_url,
        category,
        tags,
      })),
    },
    null,
    2,
  ) + '\n',
);
const about = articles.find((article) => article.slug === '关于本站');
if (about)
  await fs.writeFile(
    'src/pages/about.md',
    '---\nlayout: ../layouts/PageLayout.astro\ntitle: 关于本站\n---\n\n' + about.body_markdown + '\n',
  );
await fs.rm('src/content/blog', { recursive: true, force: true });
await fs.rename(staged, 'src/content/blog');
console.log('Replow snapshot: ' + articles.length + ' published articles, ' + friends.length + ' friends; release ' + version);

const albums = await fetchJson('albums');
if (!Array.isArray(albums.items)) throw new Error('Invalid public album response');
await fs.writeFile('src/data/gallery.json', JSON.stringify({ items: albums.items }, null, 2) + '\n');

const dynamics = await fetchJson('dynamics?limit=1');
if (!Array.isArray(dynamics.items) || !Number.isInteger(dynamics.total)) throw new Error('Invalid public dynamic response');
console.log('Dynamic API ready: ' + dynamics.total + ' public updates; runtime feed enabled');

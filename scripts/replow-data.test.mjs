import assert from 'node:assert/strict';
import { test } from 'node:test';
import { articleMarkdown, footerHtml, makeSiteConfig, validSlug } from './replow-data.mjs';

function findNavigationItem(items, name) {
  for (const item of items) {
    if (item.name === name) return item;
    const nested = findNavigationItem(item.children ?? [], name);
    if (nested) return nested;
  }
  return undefined;
}

function flattenNavigation(items) {
  return items.flatMap((item) => [item, ...flattenNavigation(item.children ?? [])]);
}

test('public permalinks and real cover survive theme conversion', () => {
  const output = articleMarkdown({
    title: '中文文章',
    slug: '关于本站',
    status: 'published',
    published_at: '2026-01-01',
    cover_url: 'https://example.com/cover.png',
    body_markdown: '# 正文',
  });
  assert.match(output, /link: "关于本站"/);
  assert.match(output, /https:\/\/example.com\/cover.png/);
  assert.match(output, /# 正文/);
  assert.throws(() => validSlug('../secret'));
  assert.throws(() => articleMarkdown({ status: 'draft' }));
});

test('footer updates status link, theme and release while preserving legal and uptime', () => {
  const output = footerHtml(
    'Theme Firefly | Power By Astro Version：v26.9.26 Update：2 <a href="https://api.4z.ink">API 站</a><a href="/privacy">隐私协议</a><time data-site-uptime></time>',
    'v26.10.13-u1',
  );
  assert.match(output, /Theme astro-koharu/);
  assert.match(output, /Version：v26.10.13 Update：1/);
  assert.match(output, /href="\/privacy"/);
  assert.match(output, /data-site-uptime/);
  assert.match(output, /href="https:\/\/status\.4z\.ink">Status<\/a>/);
  assert.doesNotMatch(output, /api\.4z\.ink|API 站/);
});

test('mapping groups header navigation and deduplicates preview account links', () => {
  const mapped = makeSiteConfig(
    { site: {}, content: {} },
    {
      site: { name: 'Example', url: 'https://example.com' },
      profile: { name: 'Owner' },
      firefly: {
        profileConfig: {
          links: [
            { name: 'GitHub', url: 'https://github.com/example' },
            { name: '邮箱', url: 'mailto:a@example.com' },
          ],
        },
        koharuConfig: { postCardImagePosition: 'right' },
        navBarConfig: {
          links: [{ name: '账号中心', url: 'https://account.preview.replow.org/', external: true }],
        },
      },
    },
    [],
  );
  assert.deepEqual(Object.keys(mapped.social), ['GitHub', '邮箱']);
  assert.equal(mapped.content.postCardImagePosition, 'right');
  assert.deepEqual(mapped.featuredSeries, []);
  assert.deepEqual(mapped.friends.data, []);
  assert.deepEqual(mapped.navigation.map((item) => item.name), ['主页', '文章', '阅读', '发现', '站点']);
  assert.deepEqual(mapped.navigation.find((item) => item.name === '文章')?.children?.map((item) => item.name), [
    '归档',
    '分类',
    '标签',
  ]);
  const status = findNavigationItem(mapped.navigation, 'Status');
  assert.equal(status?.path, 'https://status.4z.ink');
  assert.equal(status?.localeIndependent, true);
  const accountLinks = flattenNavigation(mapped.navigation).filter((item) =>
    /account(?:\.preview)?\.replow\.org/.test(item.path ?? ''),
  );
  assert.equal(accountLinks.length, 1);
  assert.equal(accountLinks[0].path, 'https://account.replow.org/');
});

test('keeps the configured background music player when syncing public site data', () => {
  const bgm = {
    enabled: true,
    audio: [{ title: 'Favorites', list: ['https://music.163.com/playlist?id=42'] }],
  };
  const mapped = makeSiteConfig(
    { site: {}, content: {}, bgm },
    {
      site: { name: 'Example', url: 'https://example.com' },
      profile: { name: 'Owner' },
      firefly: {},
    },
    [],
  );
  assert.deepEqual(mapped.bgm, bgm);
  assert.notStrictEqual(mapped.bgm, bgm);
});

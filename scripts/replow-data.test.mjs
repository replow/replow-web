import assert from 'node:assert/strict';
import { test } from 'node:test';
import { articleMarkdown, footerHtml, makeSiteConfig, validSlug } from './replow-data.mjs';

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
test('mapping removes sample content and preserves social order', () => {
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
      },
    },
    [],
  );
  assert.deepEqual(Object.keys(mapped.social), ['GitHub', '邮箱']);
  assert.equal(mapped.content.postCardImagePosition, 'right');
  assert.deepEqual(mapped.featuredSeries, []);
  assert.deepEqual(mapped.friends.data, []);
  const status = mapped.navigation.find((item) => item.name === 'Status');
  assert.equal(status?.path, 'https://status.4z.ink');
  assert.equal(status?.localeIndependent, true);
});

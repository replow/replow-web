export const DEFAULT_COVER = 'https://cdn.replow.org/replow-org/images/cover.webp';

export function validSlug(value) {
  const slug = String(value ?? '').trim();
  if (!slug || slug.split('/').some((part) => !part || part === '.' || part === '..') || /[\\?#\0]/.test(slug)) {
    throw new Error('Invalid public article slug');
  }
  return slug;
}

export function articleMarkdown(article, cover = DEFAULT_COVER) {
  const slug = validSlug(article.slug);
  if (article.status !== 'published' || !article.title || !article.published_at) {
    throw new Error('Incomplete published article');
  }
  const q = (value) => JSON.stringify(value ?? '');
  const lines = [
    '---',
    'title: ' + q(article.title),
    'link: ' + q(slug),
    'date: ' + q(article.published_at),
    'updated: ' + q(article.updated_at || article.published_at),
    'description: ' + q(article.excerpt || ''),
    'cover: ' + q(String(article.cover_url || '').trim() || cover),
    'tags: ' + JSON.stringify(Array.isArray(article.tags) ? article.tags : []),
    'categories: ' + JSON.stringify(article.category ? [article.category] : []),
    'sticky: ' + Boolean(article.is_pinned),
    'draft: false',
    'excludeFromSummary: true',
    '---',
    '',
    String(article.body_markdown || '').trim(),
    '',
  ];
  return lines.join('\n');
}

export function footerHtml(html, version) {
  const match = version.match(/^(v\d+\.\d+\.\d+)-u(\d+)$/);
  if (!match) throw new Error('Invalid release version');
  return String(html || '')
    .replace(/(href=["'])https:\/\/api\.4z\.ink\/?(["'])/gi, '$1https://status.4z.ink$2')
    .replace(/>API\s*站<\/a>/gi, '>Status</a>')
    .replace(/Theme\s+Firefly/gi, 'Theme astro-koharu')
    .replace(/Version[：:]\s*v[\d.]+/g, 'Version：' + match[1])
    .replace(/Update[：:]\s*\d+/g, 'Update：' + match[2]);
}

export function makeSiteConfig(base, payload, friends) {
  const f = payload.firefly || {};
  const k = f.koharuConfig || {};
  const oldSite = f.siteConfig || {};
  const profile = f.profileConfig || {};
  const wallpaper = f.backgroundWallpaper || {};
  const cover = wallpaper.articlePlaceholderUrl || DEFAULT_COVER;
  const yaml = structuredClone(base);
  yaml.site = {
    ...yaml.site,
    title: payload.site.name,
    alternate: 'SilverCode Nexus',
    subtitle: oldSite.subtitle || "Replow's Blog",
    name: payload.profile.name,
    author: payload.profile.name,
    description: payload.site.description,
    avatar: payload.profile.avatar_url,
    showLogo: false,
    url: payload.site.url,
    defaultOgImage: payload.profile.avatar_url,
    startYear: Number(String(oldSite.siteStartDate || '2025').slice(0, 4)),
    timezone: oldSite.timezone || 'Asia/Shanghai',
    keywords: payload.site.keywords || [],
    enableSlugTransliteration: false,
  };
  yaml.i18n = { defaultLocale: 'zh', locales: [{ code: 'zh', label: '中文' }] };
  yaml.featuredCategories = [];
  yaml.featuredSeries = [];
  delete yaml.colophon;
  yaml.categoryMap = {};
  yaml.defaultCoverList = [cover];
  yaml.social = {};
  const iconMap = {
    GitHub: 'ri:github-fill',
    Bilibili: 'ri:bilibili-fill',
    QQ: 'ri:qq-fill',
    QQ群: 'ri:group-fill',
    邮箱: 'ri:mail-line',
  };
  for (const link of profile.links || []) {
    if (link.url) yaml.social[link.name] = { url: link.url, icon: iconMap[link.name] || 'ri:link', color: '#b7a5ff' };
  }
  yaml.navigation = [
    { name: '主页', path: '/', icon: 'ri:home-4-line' },
    {
      name: '文章',
      icon: 'ri:article-line',
      children: [
        { name: '归档', path: '/archives', icon: 'ri:archive-line' },
        { name: '分类', path: '/categories', icon: 'ri:folder-line' },
        { name: '标签', path: '/tags', icon: 'ri:price-tag-3-line' },
      ],
    },
    {
      name: '阅读',
      icon: 'ri:book-open-line',
      children: [
        { name: '番茄小说', path: '/fanqie', icon: 'ri:book-open-line' },
        { name: '阅读书架', path: '/reading', icon: 'ri:book-shelf-line' },
      ],
    },
    {
      name: '发现',
      icon: 'ri:compass-3-line',
      children: [
        ...(oldSite.pages?.dynamic !== false ? [{ name: '动态', path: '/dynamic', icon: 'ri:chat-3-line' }] : []),
        { name: '音乐', path: '/music', icon: 'ri:music-2-line' },
        ...(oldSite.pages?.friends !== false ? [{ name: '友链', path: '/friends', icon: 'ri:links-line' }] : []),
        { name: '相册', path: '/gallery', icon: 'ri:gallery-line' },
      ],
    },
    {
      name: '站点',
      icon: 'ri:global-line',
      children: [
        { name: '关于', path: '/about', icon: 'ri:information-line' },
        { name: 'Status', path: 'https://status.4z.ink', icon: 'ri:heart-pulse-line', localeIndependent: true },
        { name: '账号中心', path: 'https://account.replow.org/', icon: 'ri:account-circle-line', localeIndependent: true },
      ],
    },
  ];
  // The preview build rewrites the canonical account URL to account.preview.replow.org.
  // Treat both hosts as the same navigation destination so the API-provided preview link
  // does not create a duplicate top-level entry.
  const canonicalNavPath = (value) => {
    const canonical = value.replace(/^https:\/\/account\.preview\.replow\.org\/?$/, 'https://account.replow.org');
    return canonical === '/' ? '/' : canonical.replace(/\/+$/, '');
  };
  const hasNavPath = (items, path) =>
    items.some(
      (item) =>
        (typeof item.path === 'string' && canonicalNavPath(item.path) === canonicalNavPath(path)) ||
        hasNavPath(item.children || [], path),
    );
  for (const link of f.navBarConfig?.links || []) {
    if (typeof link.url === 'string' && /^(https?:\/\/|\/(?!\/))/.test(link.url) && !hasNavPath(yaml.navigation, link.url)) {
      yaml.navigation.push({
        name: link.name || link.url,
        path: link.url,
        icon: 'ri:link',
        localeIndependent: Boolean(link.external),
      });
    }
  }
  yaml.friends = {
    groups: [{ id: 'community', title: '友情链接', description: '交换友链，共享日常与技术。' }],
    intro: { title: '友情链接', subtitle: '欢迎交换友链！', applyTitle: '申请友链', applyDesc: '邮箱验证后自动加入友链。' },
    data: friends.map((friend) => ({
      site: friend.name,
      url: friend.website_url,
      owner: friend.name,
      desc: friend.description || '',
      image: friend.avatar_url || payload.profile.avatar_url,
      group: 'community',
      color: '#b7a5ff',
    })),
  };
  yaml.content = {
    ...yaml.content,
    postCardImagePosition: k.postCardImagePosition || 'alternating',
    enableOGPreview: false,
    enableLinkEmbed: false,
  };
  yaml.motion = {
    level: k.motionLevel || 'lively',
    heroPetals: Boolean(f.sakuraConfig?.enable),
    clickBurst: Boolean(f.sakuraConfig?.enable),
  };
  yaml.moments = { enabled: false };
  yaml.editor = { enabled: false };
  yaml.christmas = { ...yaml.christmas, enabled: false };
  delete yaml.bangumi;
  yaml.bgm = { enabled: false, audio: [] };
  yaml.comment = {};
  const comments = f.commentConfig || {};
  if (comments.type && comments.type !== 'none' && comments[comments.type]) {
    const type = comments.type;
    if (['giscus', 'waline', 'twikoo', 'remark42'].includes(type)) {
      yaml.comment[type] = { ...comments[type], enable: true };
    }
  }
  yaml.analytics = {};
  const analytics = f.analyticsConfig || {};
  if (analytics.umami?.enable && analytics.umami.websiteId) {
    yaml.analytics.umami = { enabled: true, websiteId: analytics.umami.websiteId, src: analytics.umami.src };
  }
  return yaml;
}

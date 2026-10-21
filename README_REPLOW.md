# Replow integration

This deployment uses astro-koharu with the existing SilverCode backend. The theme's AGPL-3.0 license remains in LICENSE; the public footer links to this source archive.

## Build

Use Node.js 22 and the pnpm version declared in package.json.

    pnpm install --frozen-lockfile
    API_BASE_URL=https://www.replow.org REPLOW_RELEASE=v26.10.14-u1 pnpm build

Every build imports the backend's published articles, public site settings and friend links. It replaces demonstration content, retains existing article slugs, and creates the Pagefind index, RSS, sitemap and static article pages. Only public API data enters the theme source and static snapshot.

## Runtime and administration

The front end refreshes same-origin /v1/public data. It retains built content during API outages and supports articles published since the last build through the /post/ and /posts/ fallback to /read/index.html. The old /posts/<slug>/ links reach the corresponding Koharu /post/<slug>/ article.

The existing admin stores theme controls under firefly_config.koharuConfig for compatibility. Theme, profile, wallpaper, announcements and footer changes can refresh at runtime. Building updates layout, motion, static pages, archives, search, RSS and sitemap.

The admin build action uses authenticated GET/POST /v1/admin/site/build. The fixed Azure systemd service performs checks and an atomic static release with rollback on validation failure. It does not accept a shell command from the client.

## Source ownership

Replow-specific components live in src/components/replow and browser modules in src/lib/replow. The public content conversion and validation live in scripts/replow-data.mjs and scripts/sync-replow.mjs.

Never copy private admin settings, credentials or environment files into the public source archive. Keep the legacy Firefly source and releases available for rollback.

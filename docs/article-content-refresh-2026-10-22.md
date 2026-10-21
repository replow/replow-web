# Published article review — 2026-10-22

The published article content is managed in the production API database, not stored in this Astro source repository. This source-only record captures the content review and triggers the existing GitHub Actions Astro build so that the generated `/post/<slug>/` HTML reflects the database revisions.

## Article updates

- 60000 — SilverCode Nexus: clarify current Astro + API architecture and preserve old PHP/XML history.
- 60002 — About this site: correct the domain, current routes and static publication behavior.
- 60013 — CC Switch/Codex: reference official 4.0.18 release and updated UI caveats.
- 60014 — BiliBiliToolPro: note 4.1.1, `platforms/qinglong`, 1Panel v2, and safety guidance.
- 60015 — Beginner website building, chapter 1: remove time-sensitive domain price figures and add DNS migration checks.
- 60016 — Beginner website building, chapter 2: update 1Panel v2 installation path, remove stale promotional prices and clarify supported distributions.
- 60017 — NapCat + TRSS-Yunzai: official links, current Node.js 24 guidance and operational warnings.
- 60018 — Legacy AccessKey API guide: prominently mark retired interface and preserve old contract for migration reference.
- 60019 — Legacy AI AccessKey specification: mark superseded; prohibit agents from invoking stale authenticated endpoints.

60001 — Yuexin Music was retained as a dated historical project release description and was not rewritten.

Before changes, a private snapshot of all 10 published articles and its SHA-256 digest were stored on the Azure host in the restricted backup directory `/www/wwwroot/backup/article-refresh-20261022/`. Do not commit the database snapshot or secrets to GitHub.

## Verification

After the Actions build finishes, Azure's static deployer should verify the release artifact checksum, atomically switch the `web` symlink, and invalidate relevant CDN cache. Confirm the new text at both the API and the public article URLs before considering the content refresh fully deployed.

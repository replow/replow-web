import { spawnSync } from 'node:child_process';
import fs from 'node:fs/promises';

await fs.mkdir('public/source', { recursive: true });
const files = [
  'package.json',
  'pnpm-lock.yaml',
  'pnpm-workspace.yaml',
  'astro.config.mjs',
  'tailwind.config.mjs',
  'tsconfig.json',
  'tsconfig.site.json',
  'biome.json',
  'components.json',
  'config',
  'src',
  'scripts',
  'public',
  'LICENSE',
  'README.md',
  'README_REPLOW.md',
  'AGENTS.md',
];
const result = spawnSync(
  'tar',
  ['-czf', 'public/source/astro-koharu-replow.tar.gz', '--exclude=public/source', '--exclude=.env*', ...files],
  { encoding: 'utf8' },
);
if (result.status !== 0) throw new Error('Theme source archive failed: ' + result.stderr);
console.log('Packaged public theme source');

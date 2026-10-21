import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';

async function pages(directory) {
  const entries = await fs.readdir(directory, { withFileTypes: true });
  return (await Promise.all(entries.map(async (entry) => {
    const name = path.join(directory, entry.name);
    return entry.isDirectory() ? pages(name) : name.endsWith('.html') ? [name] : [];
  }))).flat();
}
let verified = 0;
for (const file of await pages('dist/post')) {
  const html = await fs.readFile(file, 'utf8');
  if (!html.includes('data-discussion')) continue;
  assert(html.includes('data-comment-avatar-image'), file + ': comment identity avatar missing');
  assert(!html.includes('回复会通知对方'), file + ': obsolete reply explanation returned');
  const script = html.match(/src="(\/_astro\/Comments[^"]+\.js)"/)?.[1];
  assert(script, file + ': comment editor script missing');
  const code = await fs.readFile(path.join('dist', script), 'utf8');
  assert(code.includes('setSelectionRange'), file + ': selection-aware formatting missing');
  assert(!code.includes('回复后会在个人中心通知对方'), file + ': obsolete status explanation returned');
  verified++;
}
assert(verified > 0, 'No article comment editors were checked');
console.log('Verified updated comment editors on ' + verified + ' article pages');

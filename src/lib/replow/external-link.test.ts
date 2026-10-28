import assert from 'node:assert/strict';
import { test } from 'node:test';
import { confirmationTarget, guardedLink, isOwnHostname } from './external-link';

test('only exact own domains and their subdomains are trusted', () => {
  for (const h of ['replow.org', 'www.preview.replow.org', 'api.4z.ink', 'ronova.top', 'WWW.REPLOW.ORG.'])
    assert.equal(isOwnHostname(h), true);
  for (const h of ['evilreplow.org', 'replow.org.evil.example', '4z.ink.evil.example', 'example.com'])
    assert.equal(isOwnHostname(h), false);
});
test('external targets preserve query, fragments and encoding through confirmation', () => {
  const target = 'https://example.com/中文?a=1&next=%2Fhello#world';
  const guarded = guardedLink(target, 'https://www.preview.replow.org/friends/');
  assert.equal(
    confirmationTarget(new URL(guarded, 'https://www.replow.org').searchParams.get('url') ?? '')?.href,
    new URL(target).href,
  );
});
test('relative, own and non-web actions are unchanged', () => {
  for (const href of ['/friends/', '#section', 'mailto:a@example.com', 'https://account.replow.org/', 'https://ronova.top/'])
    assert.equal(guardedLink(href, 'https://www.replow.org/'), href);
  assert.ok(guardedLink('//example.com', 'https://www.replow.org/').startsWith('/go/?url='));
});
test('confirmation rejects executable, malformed, relative and credential-bearing targets', () => {
  for (const value of ['javascript:alert(1)', 'data:text/html,hi', '/friends/', '', 'https://user:password@example.com'])
    assert.equal(confirmationTarget(value), null);
});

test('local preview links stay unchanged and external confirmation is idempotent', () => {
  const base = 'http://terminal.local:4173/music/';
  for (const href of ['/', '/music/', '#lyrics', 'http://terminal.local:4173/friends/']) {
    assert.equal(guardedLink(href, base), href);
  }
  const once = guardedLink('https://example.com/music', base);
  assert.equal(guardedLink(once, base), once);
  assert.ok(guardedLink('http://terminal.local:9999/', base).startsWith('/go/?url='));
});

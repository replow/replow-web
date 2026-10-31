import assert from 'node:assert/strict';
import test from 'node:test';
import { resolveBranding } from './branding';

test('branding uses independently configured icon and friend information', () => {
  const result = resolveBranding({
    site: { name: 'Site', icon_url: '/icon.png', url: 'https://example.com/' },
    profile: { avatar_url: '/profile.png' },
    firefly: {
      friendSiteInfo: { name: 'Friend name', description: '', avatar_url: '/friend.png', url: 'https://friend.example/' },
    },
  });
  assert.deepEqual(result, {
    icon: '/icon.png',
    name: 'Friend name',
    description: '',
    avatar: '/friend.png',
    url: 'https://friend.example/',
  });
});

test('missing friend settings fall back to profile and site settings', () => {
  const result = resolveBranding({
    site: { name: 'Site', url: '/home', description: 'Intro' },
    profile: { avatar_url: '/profile.png' },
  });
  assert.deepEqual(result, { icon: '/profile.png', avatar: '/profile.png', name: 'Site', url: '/home', description: 'Intro' });
});

test('unsafe URLs and malformed configuration never become image or link targets', () => {
  const result = resolveBranding({
    site: { icon_url: 'javascript:alert(1)' },
    profile: { avatar_url: '//unknown.example/a.png' },
    firefly: { friendSiteInfo: { avatar_url: 'data:text/html,unsafe', url: 'javascript:alert(1)' } },
  });
  assert.equal(result.icon, '/favicon.ico');
  assert.equal(result.avatar, '/favicon.ico');
  assert.equal(result.url, 'https://www.replow.org/');
  assert.doesNotThrow(() => resolveBranding({ firefly: { friendSiteInfo: null } }));
});

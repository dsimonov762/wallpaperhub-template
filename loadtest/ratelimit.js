// Is the gateway's rate limiter working as shipped? One user (the one of VU 1) searches until the gateway says 429.
import { check, sleep } from 'k6';
import { call } from './lib/api.js';
import { data, pick } from './lib/data.js';
import { num } from './lib/config.js';

export function ratelimitProbe() {
  const limit = num('EXPECT_LIMIT', 60); // searchWallpapers per user and minute in services/gateway/envoy/envoy.yaml
  let ok = 0;
  let limited = null;
  for (let i = 0; i < limit * 3; i++) {
    const res = call('searchWallpapers', 'GET', '/wallpapers/search', { query: { q: pick(data.words), size: 5 }, expect: [200, 429] });
    if (res.status === 429) {
      limited = res;
      break;
    }
    ok++;
  }
  console.log(`${ok} searches were served before the first 429 (limit ${limit} per minute)`);
  check(null, { 'a 429 came within three times the limit': () => limited !== null });
  if (!limited) return;
  check(limited, {
    'served roughly as many as the limit allows (not far fewer, not many more)': () => ok >= limit * 0.5 && ok <= limit * 1.5,
    '429 carries Retry-After': (r) => Number(r.headers['Retry-After']) > 0,
    '429 is problem+json': (r) => String(r.headers['Content-Type']).indexOf('application/problem+json') !== -1,
  });
  if (__ENV.RATELIMIT_RECOVER === '0') return;
  const wait = Math.min(Number(limited.headers['Retry-After']) || 60, 120);
  console.log(`waiting ${wait} s (Retry-After) to see the user served again`);
  sleep(wait + 1);
  const again = call('searchWallpapers', 'GET', '/wallpapers/search', { query: { q: pick(data.words), size: 5 }, expect: [200] });
  check(again, { 'served again after Retry-After': (r) => r.status === 200 });
}

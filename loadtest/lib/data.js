// The seed data (make seed-build writes seed/out/manifest.json) is the source of ids: users that can log in, published wallpapers,
// words to search for. Loaded once and shared by all VUs (SharedArray), so the memory cost does not grow with the VU count.
import { SharedArray } from 'k6/data';

const manifest = new SharedArray('manifest', function () {
  let raw;
  try {
    raw = open('../../seed/out/manifest.json');
  } catch (e) {
    throw new Error('seed/out/manifest.json not found. Run: make seed-build   (and make seed, so the stack holds the same data)');
  }
  const m = JSON.parse(raw);
  const users = m.users.filter((u) => u.status === 'ACTIVE' && !u.deleted && (u.in_keycloak || u.username === 'alice') && u.username !== 'admin' && u.username !== 'mod');
  const published = m.wallpapers.filter((w) => w.status === 'PUBLISHED');
  const words = new Set();
  published.forEach((w) => {
    (w.tags || []).forEach((t) => words.add(t));
    w.title.split(/\s+/).filter((x) => x.length > 3).forEach((x) => words.add(x.toLowerCase().replace(/[^\p{L}\p{N}]/gu, '')));
  });
  return [{
    users: users.map((u) => ({ id: u.id, username: u.username, avatar: u.avatarAssetId })),
    wallpapers: published.map((w) => ({ id: w.id, authorId: w.authorId, assetId: w.assetId, category: w.category })),
    words: Array.from(words).filter(Boolean),
    categories: Array.from(new Set(published.map((w) => w.category))),
    collections: m.collections.map((c) => ({ id: c.id, ownerId: c.ownerId })),
  }];
});

export const data = manifest[0];

export function pick(list) {
  return list[Math.floor(Math.random() * list.length)];
}

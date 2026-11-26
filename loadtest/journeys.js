// What a user does, as the functions the scenarios (lib/profiles.js) run. A journey is a few related requests, like a screen of the web app:
// the rate of a profile is journeys per second, not requests per second.
import http from 'k6/http';
import { sleep } from 'k6';
import { Counter, Trend } from 'k6/metrics';
import { check } from 'k6';
import { call, json } from './lib/api.js';
import { data, pick } from './lib/data.js';
import { currentUser, bearer } from './lib/auth.js';
import { BASE_URL, num, str, skipped } from './lib/config.js';

const think = () => sleep(num('THINK_TIME', 0)); // seconds between the steps of a journey; 0 = a pure throughput test

const GRAPHQL_PAGE = open('../contracts/graphql/examples/wallpapers-page.graphql');

/** The home screen: a page of the catalog, three wallpapers opened, an author. */
export function browse() {
  const res = call('listWallpapers', 'GET', '/wallpapers', { query: { page: Math.floor(Math.random() * 2), size: 20, category: Math.random() < 0.3 ? pick(data.categories) : undefined } });
  const items = (json(res) || {}).items || [];
  think();
  for (let i = 0; i < 3; i++) {
    const w = items.length && Math.random() < 0.5 ? pick(items) : pick(data.wallpapers);
    call('getWallpaper', 'GET', `/wallpapers/${w.id}`);
    think();
  }
  call('getUser', 'GET', `/users/${pick(data.wallpapers).authorId}`);
}

/** The search box: a word, now and then a facet or the search-as-you-type form. */
export function search() {
  const q = pick(data.words);
  const kind = Math.random();
  if (kind < 0.2) {
    call('searchWallpapers', 'GET', '/wallpapers/search', { query: { q: q.slice(0, 3), autocomplete: true, size: 8 } });
  } else {
    call('searchWallpapers', 'GET', '/wallpapers/search', { query: { q, size: 20, facets: kind < 0.5 ? 'CATEGORY,TAG' : undefined } });
  }
}

/** Favoriting and un-favoriting someone else's wallpaper: the state ends where it began. */
export function favorites() {
  const me = currentUser();
  const w = pick(data.wallpapers.filter((x) => x.authorId !== me.id));
  call('favoriteWallpaper', 'POST', `/wallpapers/${w.id}/favorite`);
  think();
  call('listMyFavorites', 'GET', '/users/me/favorites', { query: { size: 20 } });
  think();
  call('unfavoriteWallpaper', 'DELETE', `/wallpapers/${w.id}/favorite`);
}

/** The bell icon: the inbox and the preferences. */
export function inbox() {
  call('listNotifications', 'GET', '/notifications', { query: { page: 0, size: 20, unread: Math.random() < 0.5 ? true : undefined } });
  think();
  call('getNotificationPreferences', 'GET', '/notification-preferences');
}

/** The profile page of the signed-in user. */
export function profile() {
  call('getCurrentUser', 'GET', '/users/me');
  const me = currentUser();
  if (me.avatar) {
    call('getMedia', 'GET', `/media/${me.avatar}`);
    call('getMediaUrl', 'GET', `/media/${me.avatar}/url`);
  }
}

/** Collections of the signed-in user. */
export function collections() {
  const res = call('listCollections', 'GET', '/collections', { query: { page: 0, size: 20 } });
  const mine = data.collections.filter((c) => c.ownerId === currentUser().id);
  if (mine.length) call('getCollection', 'GET', `/collections/${pick(mine).id}`);
  return res;
}

/** The GraphQL endpoint: the same page of the catalog as one query, with its authors (the N+1 case). */
export function graphql() {
  const res = http.post(`${BASE_URL}/graphql`, JSON.stringify({ query: GRAPHQL_PAGE, variables: { first: 20 } }), {
    headers: Object.assign({ 'Content-Type': 'application/json', Accept: 'application/graphql-response+json, application/json' }, bearer()),
    tags: { name: 'graphql' },
    responseCallback: http.expectedStatuses(200),
  });
  check(res, {
    'graphql: 200 and no errors': (r) => r.status === 200 && !(json(r) || {}).errors,
  }, { name: 'graphql' });
}

// ---- uploads: need unique pictures (media rejects duplicates by SHA-256 and perceptual hash), made by `make load-data` ----------------
export const uploadToReady = new Trend('upload_to_ready', true); // time: k6 trends of time are in milliseconds
export const uploadsRejected = new Counter('uploads_rejected');
export const uploadsTimedOut = new Counter('uploads_timed_out');

const WANT_UPLOADS = str('PROFILE', 'smoke') === 'uploads' || __ENV.WITH_UPLOADS === '1';
export const UPLOAD_VUS = num('UPLOAD_MAX_VUS', 30);
// open() copies the file into every VU: each VU therefore loads only its own slice of the pictures (every UPLOAD_VUS-th one), which also
// guarantees that two VUs never send the same picture.
const POOL = [];
if (WANT_UPLOADS) {
  const n = num('UPLOAD_POOL', 200);
  // k6 only lets a VU open files that VU 0 has opened during the init stage, so VU 0 opens all of them (and drops them again)
  const first = __VU === 0 ? 0 : (__VU - 1) % UPLOAD_VUS;
  const step = __VU === 0 ? 1 : UPLOAD_VUS;
  for (let i = first; i < n; i += step) {
    const file = `.data/uploads/${String(i).padStart(4, '0')}.png`;
    let bytes;
    try {
      bytes = open(file, 'b');
    } catch (e) {
      if (String(e).indexOf('previously opened') !== -1) throw e;
      throw new Error(`cannot read loadtest/${file} (${e}). Run: make load-data   (UPLOAD_POOL=n pictures, one per upload)`);
    }
    if (__VU > 0) POOL.push(bytes);
  }
}
let nextPicture = 0;
export const picturesExhausted = new Counter('upload_pictures_exhausted');
export const hasUploads = () => WANT_UPLOADS && POOL.length > 0;

/** An upload, and the wait until the image processing says READY: the number that matters is upload_to_ready. */
export function upload() {
  if (nextPicture >= POOL.length) {
    picturesExhausted.add(1); // more uploads than pictures: raise UPLOAD_POOL (make load-data) instead of sending duplicates
    sleep(1);
    return;
  }
  const picture = POOL[nextPicture++];
  const t0 = Date.now();
  const res = call('uploadMedia', 'POST', '/media', {
    form: { file: http.file(picture, `k6-${__VU}-${nextPicture}.png`, 'image/png'), purpose: 'WALLPAPER' },
    expect: [202],
  });
  const id = (json(res) || {}).assetId;
  if (res.status !== 202 || !id) return;
  const deadline = Date.now() + num('UPLOAD_READY_TIMEOUT', 60) * 1000;
  for (;;) {
    sleep(1);
    const st = call('getMedia', 'GET', `/media/${id}`);
    const status = (json(st) || {}).status;
    if (status === 'READY') {
      uploadToReady.add(Date.now() - t0);
      return;
    }
    if (status === 'REJECTED') {
      uploadsRejected.add(1);
      return;
    }
    if (Date.now() > deadline) {
      uploadsTimedOut.add(1);
      return;
    }
  }
}

/** Every journey once, in order: the functional pass of the smoke profile. */
export function everything() {
  browse(); search(); favorites(); inbox(); profile(); collections();
  if (!skipped('graphql')) graphql();
  if (hasUploads()) upload();
}

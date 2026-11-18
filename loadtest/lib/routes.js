// The performance budget, one line per operation: the 95th percentile (ms) a request must stay under. These are the names of the
// requests (the `name` tag, the operationId of the OpenAPI contract), so a failed threshold, a Grafana panel and the contract use one word.
//
// The README defines no latency targets: these numbers are a starting point for a laptop (docker, 2 gateway threads, services next to
// the databases). Tighten them once you have measured a baseline; BUDGET_SCALE=2 doubles all of them (slow CI runner).
import { num, skipped } from './config.js';

export const BUDGET = {
  listWallpapers: 300,
  searchWallpapers: 500,
  getWallpaper: 200,
  favoriteWallpaper: 300,
  unfavoriteWallpaper: 300,
  listMyFavorites: 300,
  listCollections: 300,
  getCollection: 250,
  getCurrentUser: 150,
  getUser: 200,
  listNotifications: 250,
  getNotificationPreferences: 200,
  getMedia: 200,
  getMediaUrl: 250,
  uploadMedia: 1500,
  graphql: 500,
  'keycloak.token': 800,
};

export function thresholds({ scale = 1, failedRate = 0.01, strict = false, uploads = false } = {}) {
  const s = scale * num('BUDGET_SCALE', 1);
  const t = {
    checks: [strict ? 'rate==1' : 'rate>0.99'],
    http_req_failed: [strict ? 'rate==0' : `rate<${failedRate}`],
    // the gateway turned requests away: the numbers of this run are about the rate limiter, not about the services (make up-load raises the limits)
    rate_limited: ['count==0'],
  };
  if (strict) t.server_errors = ['count==0']; // smoke: not one 5xx; the other profiles judge errors by http_req_failed
  for (const [name, p95] of Object.entries(BUDGET)) {
    if (name === 'uploadMedia' && !uploads && __ENV.WITH_UPLOADS !== '1') continue; // no sample, no budget
    if (name === 'graphql' && skipped('graphql')) continue;
    t[`http_req_duration{name:${name}}`] = [`p(95)<${Math.round(p95 * s)}`];
  }
  return t;
}

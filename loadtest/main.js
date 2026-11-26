// k6 entry point:  PROFILE=smoke|load|stress|spike|soak|uploads|ratelimit  k6 run loadtest/main.js     (scripts/k6.sh / make load-run do the rest)
import http from 'k6/http';
import { PROFILE, BASE_URL, assertLocalTarget } from './lib/config.js';
import { profiles } from './lib/profiles.js';

export { browse, search, favorites, inbox, profile, collections, graphql, upload, everything } from './journeys.js';
export { ratelimitProbe } from './ratelimit.js';

const selected = profiles[PROFILE];
if (!selected) {
  throw new Error(`unknown PROFILE "${PROFILE}"; one of: ${Object.keys(profiles).join(', ')}`);
}

export const options = {
  scenarios: selected.scenarios,
  thresholds: selected.thresholds,
  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
  noConnectionReuse: false,
};

export function setup() {
  assertLocalTarget();
  const res = http.get(`${BASE_URL}/health`, { tags: { name: 'health' } });
  if (res.status !== 200) {
    throw new Error(`${BASE_URL}/health answered ${res.status}: is the stack up? (make up-load, or make up-load-mocks)`);
  }
}

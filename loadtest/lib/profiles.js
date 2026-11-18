// The test profiles (PROFILE=name). Each returns the k6 scenarios and thresholds.
//
// A rate is *journeys per second* (RATE, default 5; one journey is 2-5 requests, see journeys.js), shared out by MIX. Arrival-rate executors
// start journeys at that rate whatever the system answers (an "open" model, like real users): when the system slows down, the queue grows and k6
// reports dropped_iterations, instead of politely sending less like a fixed number of looping VUs would.
import { num, str, skipped } from './config.js';
import { thresholds } from './routes.js';

const MIX = { browse: 40, search: 15, favorites: 10, inbox: 10, profile: 10, collections: 5, graphql: 10 };
if (__ENV.WITH_UPLOADS === '1') MIX.upload = 3;
for (const name of Object.keys(MIX)) if (skipped(name)) delete MIX[name];

const RATE = () => num('RATE', 5);

/** One scenario per journey; `steps` is [{duration, mult}]: the rate goes linearly to RATE x mult during the duration. */
function mix(steps) {
  const out = {};
  const peak = Math.max(...steps.map((s) => s.mult));
  for (const [exec, weight] of Object.entries(MIX)) {
    const perSecond = (RATE() * weight) / 100;
    const perMin = (m) => Math.round(perSecond * 60 * m);
    out[exec] = {
      executor: 'ramping-arrival-rate',
      exec,
      timeUnit: '1m',
      startRate: 0,
      stages: steps.map((s) => ({ duration: s.duration, target: perMin(s.mult) })),
      preAllocatedVUs: Math.max(2, Math.ceil(perSecond * 2)),
      maxVUs: Math.max(10, Math.ceil(perSecond * peak * 10)),
    };
  }
  return out;
}

export const profiles = {
  // Every journey once with one user: does the harness, the data and the API work at all? Strict: not one error, not one 429.
  smoke: {
    scenarios: { smoke: { executor: 'per-vu-iterations', vus: 1, iterations: num('SMOKE_ITERATIONS', 1), maxDuration: '3m', exec: 'everything' } },
    thresholds: thresholds({ scale: 3, strict: true }),
  },

  // The normal day: ramp up, hold the rate, ramp down. The budgets of routes.js apply.
  load: {
    scenarios: mix([
      { duration: str('RAMP', '1m'), mult: 1 },
      { duration: str('DURATION', '5m'), mult: 1 },
      { duration: '30s', mult: 0 },
    ]),
    thresholds: thresholds(),
  },

  // Find the knee: the rate doubles every step (1, 2, 4 ... x RATE) until MAX_RATE or until more than 5% of the requests fail.
  // Passing means "survived to MAX_RATE"; the answer is in the graphs: where did latency leave the budget, what saturated first.
  stress: (() => {
    const steps = [];
    for (let m = 1; m * RATE() <= num('MAX_RATE', 80); m *= 2) {
      steps.push({ duration: '15s', mult: m }, { duration: str('STEP', '1m'), mult: m });
    }
    return {
      scenarios: mix(steps),
      thresholds: {
        http_req_failed: [{ threshold: 'rate<0.05', abortOnFail: true, delayAbortEval: '30s' }],
        dropped_iterations: ['count==0'], // k6 itself ran out of VUs: raise maxVUs or you are measuring the generator
      },
    };
  })(),

  // A sudden crowd: SPIKE x the rate within 10 seconds, held for a minute, then back. The last two minutes show whether the system recovers.
  spike: {
    scenarios: mix([
      { duration: '1m', mult: 1 },
      { duration: '10s', mult: num('SPIKE', 10) },
      { duration: '1m', mult: num('SPIKE', 10) },
      { duration: '10s', mult: 1 },
      { duration: '2m', mult: 1 },
    ]),
    thresholds: thresholds({ scale: 3, failedRate: 0.05 }),
  },

  // The normal rate for a long time (DURATION, default 30m): leaks, pool exhaustion, log or disk growth, outbox lag. Watch Grafana, not the summary.
  soak: {
    scenarios: mix([
      { duration: '1m', mult: 1 },
      { duration: str('DURATION', '30m'), mult: 1 },
    ]),
    thresholds: thresholds(),
  },

  // Uploads and the image processing behind them (needs make load-data). The number that matters: upload_to_ready (upload sent until status READY).
  uploads: {
    scenarios: {
      upload: {
        executor: 'constant-arrival-rate', exec: 'upload', timeUnit: '1m', rate: Math.max(1, Math.round(num('UPLOAD_RATE', 0.5) * 60)),
        duration: str('DURATION', '2m'), preAllocatedVUs: 10, maxVUs: num('UPLOAD_MAX_VUS', 30), // each VU holds its slice of the pictures
      },
    },
    thresholds: Object.assign(thresholds({ scale: 2, uploads: true }), {
      upload_to_ready: [`p(95)<${num('UPLOAD_READY_P95', 20) * 1000}`], // UPLOAD_READY_P95 in seconds
      uploads_rejected: ['count==0'],
      uploads_timed_out: ['count==0'],
      upload_pictures_exhausted: ['count==0'], // more uploads than pictures: UPLOAD_POOL too small for rate x duration
    }),
  },

  // The gateway's own limiter, with the SHIPPED limits (do not run it against make up-load): after about 60 searches in a minute the
  // user gets 429 + Retry-After + problem+json, and is served again after the wait.
  ratelimit: {
    scenarios: { ratelimit: { executor: 'shared-iterations', vus: 1, iterations: 1, maxDuration: '5m', exec: 'ratelimitProbe' } },
    thresholds: { checks: ['rate==1'] },
  },
};

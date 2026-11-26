// One way to call the API, so that every request is named after its operation, checked the same way and counted when the gateway or a
// service misbehaves. Every 4xx/5xx of the platform is application/problem+json (contracts/openapi/common.yaml): that is checked on every error.
import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';
import { API } from './config.js';
import { bearer } from './auth.js';

export const rateLimited = new Counter('rate_limited');
export const serverErrors = new Counter('server_errors');

function qs(query) {
  if (!query) return '';
  const parts = Object.keys(query).filter((k) => query[k] !== undefined && query[k] !== null)
    .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(query[k])}`);
  return parts.length ? `?${parts.join('&')}` : '';
}

/** call(route, method, path, {query, body, form, expect: [200], headers, auth, tags}) -> k6 response */
export function call(route, method, path, o = {}) {
  const expect = o.expect || [200];
  const headers = Object.assign({ Accept: 'application/json', 'Accept-Language': 'en' }, o.auth === false ? {} : bearer(), o.headers || {});
  let payload = null;
  if (o.body !== undefined) {
    payload = JSON.stringify(o.body);
    headers['Content-Type'] = 'application/json';
  } else if (o.form) {
    payload = o.form; // k6 sets the multipart boundary
  }
  if (method !== 'GET') headers['Idempotency-Key'] = `k6-${__VU}-${__ITER}-${Date.now()}-${Math.floor(Math.random() * 1e9)}`;
  const res = http.request(method, `${API}${path}${qs(o.query)}`, payload, {
    headers,
    tags: Object.assign({ name: route }, o.tags || {}),
    responseCallback: http.expectedStatuses(...expect),
    timeout: o.timeout || '30s',
  });
  if (res.status === 429) rateLimited.add(1, { name: route });
  if (res.status >= 500 || res.status === 0) serverErrors.add(1, { name: route });
  const ct = String(res.headers['Content-Type'] || '');
  check(res, {
    'status as the contract allows': (r) => expect.indexOf(r.status) !== -1,
    'body matches the status (JSON, or problem+json on errors)': (r) =>
      r.status === 204 || (r.status >= 400 ? ct.indexOf('application/problem+json') !== -1 : ct.indexOf('json') !== -1),
  }, { name: route });
  return res;
}

export function json(res) {
  try {
    return res.json();
  } catch (e) {
    return null;
  }
}

// Everything that comes from the environment, in one place. Set with  -e NAME=value  or through scripts/k6.sh (reads infra/.env).
export const BASE_URL = (__ENV.BASE_URL || 'http://localhost:8080').replace(/\/+$/, '');
export const API = `${BASE_URL}/api/v1`;
export const KEYCLOAK_URL = (__ENV.KEYCLOAK_URL || 'http://localhost:8180').replace(/\/+$/, '');
export const REALM = __ENV.REALM || 'wallpaperhub';
export const CLIENT_ID = __ENV.CLIENT_ID || 'e2e-tests'; // password grant is enabled for this client only
export const PASSWORD = __ENV.PASSWORD || 'password';
export const PROFILE = __ENV.PROFILE || 'smoke';

export const num = (name, dflt) => (__ENV[name] !== undefined && __ENV[name] !== '' ? Number(__ENV[name]) : dflt);
export const str = (name, dflt) => (__ENV[name] !== undefined && __ENV[name] !== '' ? __ENV[name] : dflt);

// A load test is an attack on whatever it points at: refuse anything that is not this machine unless told so.
export function assertLocalTarget() {
  const host = BASE_URL.replace(/^https?:\/\//, '').split(/[/:]/)[0];
  const local = /^(localhost|127\.\d+\.\d+\.\d+|host\.docker\.internal|\[::1\]|.*\.local|.*\.localhost)$/.test(host);
  if (!local && __ENV.ALLOW_REMOTE !== '1') {
    throw new Error(`BASE_URL ${BASE_URL} is not a local address. A load test can take a shared environment down: set ALLOW_REMOTE=1 if you own it and mean it.`);
  }
}

// SKIP=graphql,collections  leaves journeys out (the Prism mocks of make up-load-mocks serve REST only, so SKIP=graphql there).
const SKIPPED = (__ENV.SKIP || '').split(',').map((x) => x.trim()).filter(Boolean);
export const skipped = (journey) => SKIPPED.indexOf(journey) !== -1;

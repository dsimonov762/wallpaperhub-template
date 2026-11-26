// One seeded user per VU (round robin), logged in with the password grant of the e2e-tests client. The token is kept in the VU and
// renewed shortly before it expires, so a soak test longer than the token lifetime (5 minutes) keeps working.
import http from 'k6/http';
import { check, fail } from 'k6';
import { KEYCLOAK_URL, REALM, CLIENT_ID, PASSWORD } from './config.js';
import { data } from './data.js';

let state = null; // per VU

export function currentUser() {
  const u = data.users[(__VU - 1) % data.users.length];
  return u;
}

export function bearer() {
  const now = Date.now();
  if (!state || state.exp - now < 30000) {
    const user = currentUser();
    const res = http.post(
      `${KEYCLOAK_URL}/realms/${REALM}/protocol/openid-connect/token`,
      { grant_type: 'password', client_id: CLIENT_ID, username: user.username, password: PASSWORD },
      { tags: { name: 'keycloak.token' }, responseCallback: http.expectedStatuses(200) },
    );
    if (!check(res, { 'login ok': (r) => r.status === 200 })) {
      fail(`login of ${user.username} failed with ${res.status} from ${KEYCLOAK_URL}: is Keycloak up, is the realm imported (make seed for bob and the others)?`);
    }
    const body = res.json();
    state = { token: body.access_token, exp: now + body.expires_in * 1000 };
  }
  return { Authorization: `Bearer ${state.token}` };
}

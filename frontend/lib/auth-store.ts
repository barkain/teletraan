/**
 * In-memory access token store.
 *
 * The access token lives only in JS memory — never in localStorage or a cookie —
 * so it is invisible to XSS attacks. The companion refresh token is stored in an
 * httpOnly cookie managed entirely by the browser.
 */

let _accessToken: string | null = null;

export function getAccessToken(): string | null {
  return _accessToken;
}

export function setAccessToken(token: string | null): void {
  _accessToken = token;
}

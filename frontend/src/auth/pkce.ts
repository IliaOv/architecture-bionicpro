/** PKCE (RFC 7636): code_verifier + S256 code_challenge. Генерируется на фронтенде. */

const PKCE_STORAGE_KEY = 'bionicpro_pkce';

function randomUrlSafe(length: number): string {
  const alphabet =
    'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~';
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  let out = '';
  for (let i = 0; i < length; i += 1) {
    out += alphabet[bytes[i] % alphabet.length];
  }
  return out;
}

function base64UrlEncode(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  bytes.forEach((b) => {
    binary += String.fromCharCode(b);
  });
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export async function generatePkce(): Promise<{
  verifier: string;
  challenge: string;
}> {
  // 43–128 символов по спецификации PKCE.
  const verifier = randomUrlSafe(64);
  const digest = await crypto.subtle.digest(
    'SHA-256',
    new TextEncoder().encode(verifier)
  );
  return { verifier, challenge: base64UrlEncode(digest) };
}

export function generateState(): string {
  return randomUrlSafe(32);
}

export function storePkce(verifier: string, state: string): void {
  sessionStorage.setItem(PKCE_STORAGE_KEY, JSON.stringify({ verifier, state }));
}

export function takePkce(): { verifier: string; state: string } | null {
  const raw = sessionStorage.getItem(PKCE_STORAGE_KEY);
  sessionStorage.removeItem(PKCE_STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as { verifier: string; state: string };
  } catch {
    return null;
  }
}

export function buildAuthorizationUrl(params: {
  keycloakUrl: string;
  realm: string;
  clientId: string;
  redirectUri: string;
  state: string;
  codeChallenge: string;
}): string {
  const q = new URLSearchParams({
    client_id: params.clientId,
    response_type: 'code',
    scope: 'openid profile email',
    redirect_uri: params.redirectUri,
    state: params.state,
    code_challenge: params.codeChallenge,
    code_challenge_method: 'S256',
  });
  return `${params.keycloakUrl}/realms/${params.realm}/protocol/openid-connect/auth?${q}`;
}

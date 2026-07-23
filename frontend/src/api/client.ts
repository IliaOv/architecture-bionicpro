import {
  buildAuthorizationUrl,
  generatePkce,
  generateState,
  storePkce,
  takePkce,
} from '../auth/pkce';

const AUTH_URL = process.env.REACT_APP_AUTH_URL || 'http://localhost:8000';
const KEYCLOAK_URL = process.env.REACT_APP_KEYCLOAK_URL || 'http://localhost:8080';
const KEYCLOAK_REALM = process.env.REACT_APP_KEYCLOAK_REALM || 'reports-realm';
const KEYCLOAK_CLIENT_ID =
  process.env.REACT_APP_KEYCLOAK_CLIENT_ID || 'reports-frontend';
const OIDC_REDIRECT_URI =
  process.env.REACT_APP_OIDC_REDIRECT_URI || 'http://localhost:3000/callback';

export interface User {
  sub: string;
  username: string;
  email?: string;
  name?: string;
  roles: string[];
  idp?: string;
}

export interface MeResponse {
  authenticated: boolean;
  session_id: string;
  user: User;
  consent_required: boolean;
}

// Все API-запросы идут на BFF с сессионной cookie. Токены на фронтенде отсутствуют.
async function request(path: string, init?: RequestInit): Promise<Response> {
  return fetch(`${AUTH_URL}${path}`, {
    ...init,
    credentials: 'include',
  });
}

/**
 * Задача 2: фронтенд инициирует Authorization Code + PKCE (S256).
 * Задача 3: обмен code→tokens делает только BFF (completePkceLogin).
 */
export async function login(): Promise<void> {
  const { verifier, challenge } = await generatePkce();
  const state = generateState();
  storePkce(verifier, state);
  window.location.href = buildAuthorizationUrl({
    keycloakUrl: KEYCLOAK_URL,
    realm: KEYCLOAK_REALM,
    clientId: KEYCLOAK_CLIENT_ID,
    redirectUri: OIDC_REDIRECT_URI,
    state,
    codeChallenge: challenge,
  });
}

/** Обмен authorization code на сессию: code_verifier уходит на BFF. */
export async function completePkceLogin(
  code: string,
  state: string
): Promise<{ consent_required: boolean }> {
  const pkce = takePkce();
  if (!pkce) {
    throw new Error('PKCE-состояние потеряно (обновите страницу и войдите снова)');
  }
  if (pkce.state !== state) {
    throw new Error('State не совпадает — возможен CSRF');
  }

  const resp = await request('/auth/callback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      code,
      state,
      code_verifier: pkce.verifier,
      redirect_uri: OIDC_REDIRECT_URI,
    }),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || `Ошибка обмена кода: ${resp.status}`);
  }
  const data = await resp.json();
  return { consent_required: Boolean(data.consent_required) };
}

export async function logout(): Promise<void> {
  const resp = await request('/auth/logout', { method: 'POST' });
  let keycloakLogoutUrl: string | undefined;
  try {
    const data = await resp.json();
    keycloakLogoutUrl = data.keycloak_logout_url;
  } catch {
    // ignore — сессию BFF всё равно считаем завершённой
  }
  // Сброс SSO в браузере (иначе Login мгновенно вернёт в Keycloak-сессию).
  if (keycloakLogoutUrl) {
    window.location.href = keycloakLogoutUrl;
    return;
  }
  window.location.href = '/';
}

export async function fetchMe(): Promise<MeResponse | null> {
  const resp = await request('/api/me');
  if (resp.status === 401) {
    return null;
  }
  if (!resp.ok) {
    throw new Error(`Auth check failed: ${resp.status}`);
  }
  return (await resp.json()) as MeResponse;
}

/** Задача 6: согласие на использование профиля + сохранение в БД BFF. */
export async function grantConsent(): Promise<void> {
  const resp = await request('/api/consent', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ accepted: true }),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.detail || `Consent failed: ${resp.status}`);
  }
}

export interface ReportDailyRow {
  report_date: string;
  device_serial: string;
  device_model: string;
  steps: number;
  avg_battery_pct: number;
  avg_motor_load_pct: number;
  error_count: number;
  readings_count: number;
  active_hours: number;
}

export interface Report {
  user: string;
  period: { from: string; to: string };
  data_available_until: string;
  summary: {
    total_steps: number;
    avg_battery_pct: number | null;
    avg_motor_load_pct: number | null;
    total_errors: number;
    total_active_hours: number;
    days: number;
  };
  daily: ReportDailyRow[];
}

// Task 3: API отдаёт не сам отчёт, а ссылку на CDN, где лежит готовый файл.
export interface ReportRef {
  user: string;
  period: { from: string; to: string };
  data_available_until: string;
  cached: boolean;
  report_url: string;
}

export async function fetchReport(): Promise<Response> {
  return request('/api/reports');
}

// Содержимое отчёта берём напрямую с CDN (nginx перед MinIO), не нагружая OLAP.
export async function fetchReportContent(url: string): Promise<Report> {
  const resp = await fetch(url, { cache: 'no-store' });
  if (!resp.ok) {
    throw new Error(`Не удалось загрузить отчёт с CDN: ${resp.status}`);
  }
  return (await resp.json()) as Report;
}

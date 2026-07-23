import React, { useEffect, useState } from 'react';
import { completePkceLogin } from '../api/client';

/**
 * Callback после редиректа из Keycloak (?code=&state=).
 * Фронт предъявляет code_verifier BFF; токены на фронт не попадают.
 */
const AuthCallback: React.FC = () => {
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const state = params.get('state');
    const oauthError = params.get('error');

    if (oauthError) {
      setError(params.get('error_description') || oauthError);
      return;
    }
    if (!code || !state) {
      setError('В ответе Keycloak нет code/state');
      return;
    }

    completePkceLogin(code, state)
      .then((result) => {
        window.location.replace(result.consent_required ? '/?consent=1' : '/');
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
        <div className="p-6 bg-red-100 text-red-700 rounded">{error}</div>
        <a href="/" className="mt-4 text-blue-600 underline">
          На главную
        </a>
      </div>
    );
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-gray-100">
      Завершение входа (PKCE)…
    </div>
  );
};

export default AuthCallback;

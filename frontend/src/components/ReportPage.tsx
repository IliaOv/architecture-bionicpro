import React, { useCallback, useEffect, useState } from 'react';
import {
  Report,
  ReportRef,
  User,
  fetchMe,
  fetchReport,
  fetchReportContent,
  grantConsent,
  login,
  logout,
} from '../api/client';

const ReportPage: React.FC = () => {
  const [initialized, setInitialized] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [consentRequired, setConsentRequired] = useState(false);
  const [loading, setLoading] = useState(false);
  const [consentLoading, setConsentLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [source, setSource] = useState<string | null>(null);

  useEffect(() => {
    fetchMe()
      .then((me) => {
        if (!me) {
          setUser(null);
          return;
        }
        setUser(me.user);
        setConsentRequired(me.consent_required);
      })
      .catch((err) => setError(err.message))
      .finally(() => setInitialized(true));
  }, []);

  const handleConsent = useCallback(async () => {
    try {
      setConsentLoading(true);
      setError(null);
      await grantConsent();
      setConsentRequired(false);
      window.history.replaceState({}, '', '/');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Ошибка согласия');
    } finally {
      setConsentLoading(false);
    }
  }, []);

  const downloadReport = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      setReport(null);
      setSource(null);
      const response = await fetchReport();
      if (response.status === 401) {
        setUser(null);
        setError('Сессия истекла, войдите заново');
        return;
      }
      if (response.status === 409) {
        const body = await response.json().catch(() => ({}));
        setError(body.detail || 'Данные за период ещё не готовы');
        return;
      }
      if (!response.ok) {
        throw new Error(`Ошибка получения отчёта: ${response.status}`);
      }
      const ref = (await response.json()) as ReportRef;
      setReport(await fetchReportContent(ref.report_url));
      setSource(ref.cached ? 'CDN/S3 (кеш)' : 'сформирован из OLAP');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Произошла ошибка');
    } finally {
      setLoading(false);
    }
  }, []);

  const downloadJson = useCallback(() => {
    if (!report) return;
    const blob = new Blob([JSON.stringify(report, null, 2)], {
      type: 'application/json',
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `report_${report.user}_${report.period.from}_${report.period.to}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }, [report]);

  const handleLogout = useCallback(async () => {
    try {
      await logout(); // уводит на Keycloak logout → обратно на /
    } catch {
      setUser(null);
      setConsentRequired(false);
      setReport(null);
      setSource(null);
    }
  }, []);

  if (!initialized) {
    return <div>Loading...</div>;
  }

  if (!user) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
        <button
          onClick={() => {
            void login();
          }}
          className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
        >
          Login
        </button>
      </div>
    );
  }

  if (consentRequired) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
        <div className="p-8 bg-white rounded-lg shadow-md max-w-lg">
          <h1 className="text-xl font-bold mb-4">Согласие на использование данных</h1>
          <p className="text-gray-700 mb-4">
            Сервис протезов BionicPRO запрашивает разрешение использовать данные вашего
            профиля (из IdP / Яндекс ID) для работы приложения. Данные будут сохранены
            в локальной БД сервиса только после вашего согласия.
          </p>
          {error && (
            <div className="mb-4 p-3 bg-red-100 text-red-700 rounded">{error}</div>
          )}
          <div className="flex gap-3">
            <button
              onClick={() => {
                void handleConsent();
              }}
              disabled={consentLoading}
              className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 disabled:opacity-50"
            >
              {consentLoading ? 'Сохранение…' : 'Разрешить'}
            </button>
            <button
              onClick={() => {
                void handleLogout();
              }}
              className="px-4 py-2 bg-gray-200 rounded hover:bg-gray-300"
            >
              Отклонить и выйти
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center min-h-screen bg-gray-100 py-10">
      <div className="p-8 bg-white rounded-lg shadow-md w-full max-w-4xl">
        <div className="flex items-center justify-between mb-6">
          <h1 className="text-2xl font-bold">Usage Reports</h1>
          <button
            onClick={handleLogout}
            className="ml-6 px-3 py-1 text-sm bg-gray-200 rounded hover:bg-gray-300"
          >
            Logout
          </button>
        </div>

        <p className="mb-4 text-gray-600">
          {user.name || user.username} ({user.roles.join(', ') || 'no roles'})
        </p>

        <div className="flex gap-3">
          <button
            onClick={downloadReport}
            disabled={loading}
            className={`px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 ${
              loading ? 'opacity-50 cursor-not-allowed' : ''
            }`}
          >
            {loading ? 'Generating Report...' : 'Get Report'}
          </button>
          {report && (
            <button
              onClick={downloadJson}
              className="px-4 py-2 bg-gray-700 text-white rounded hover:bg-gray-800"
            >
              Download JSON
            </button>
          )}
        </div>

        {error && (
          <div className="mt-4 p-4 bg-red-100 text-red-700 rounded">{error}</div>
        )}

        {report && (
          <div className="mt-6">
            <p className="text-sm text-gray-500 mb-3">
              Период: {report.period.from} — {report.period.to} · данные готовы до{' '}
              {report.data_available_until}
              {source ? ` · источник: ${source}` : ''}
            </p>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
              <Stat label="Шаги" value={report.summary.total_steps.toLocaleString()} />
              <Stat label="Активн. часы" value={String(report.summary.total_active_hours)} />
              <Stat
                label="Заряд, %"
                value={report.summary.avg_battery_pct?.toString() ?? '—'}
              />
              <Stat label="Ошибки" value={String(report.summary.total_errors)} />
            </div>

            {report.daily.length === 0 ? (
              <p className="text-gray-500">За выбранный период данных нет.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm border">
                  <thead className="bg-gray-100">
                    <tr>
                      <Th>Дата</Th>
                      <Th>Устройство</Th>
                      <Th>Модель</Th>
                      <Th>Шаги</Th>
                      <Th>Заряд %</Th>
                      <Th>Нагрузка %</Th>
                      <Th>Ошибки</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.daily.map((r, i) => (
                      <tr key={i} className="border-t">
                        <Td>{r.report_date}</Td>
                        <Td>{r.device_serial}</Td>
                        <Td>{r.device_model}</Td>
                        <Td>{r.steps.toLocaleString()}</Td>
                        <Td>{r.avg_battery_pct}</Td>
                        <Td>{r.avg_motor_load_pct}</Td>
                        <Td>{r.error_count}</Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

const Stat: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div className="p-3 bg-gray-50 rounded border">
    <div className="text-xs text-gray-500">{label}</div>
    <div className="text-lg font-semibold">{value}</div>
  </div>
);

const Th: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <th className="px-3 py-2 text-left font-medium text-gray-600">{children}</th>
);

const Td: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <td className="px-3 py-2">{children}</td>
);

export default ReportPage;

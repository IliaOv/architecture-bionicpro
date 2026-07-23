"""Доступ к OLAP-витрине (ClickHouse). Только чтение готовых строк —
никаких тяжёлых вычислений в реальном времени."""

from datetime import date
from typing import Optional

import clickhouse_connect

from .config import settings

MART = "user_daily_report"


def _client():
    return clickhouse_connect.get_client(
        host=settings.clickhouse_host,
        port=settings.clickhouse_port,
        username=settings.clickhouse_user,
        password=settings.clickhouse_password,
    )


def get_watermark() -> Optional[date]:
    """Максимальная дата, за которую витрина уже наполнена (или None).

    Task 4: витрина наполняется потоково из CDC (Debezium→Kafka→ClickHouse),
    отдельной таблицы watermark у batch-ETL больше нет — «граница готовности»
    данных = максимальная дата, реально присутствующая в витрине.
    """
    try:
        client = _client()
        rows = client.query(
            f"SELECT max(report_date) FROM {settings.clickhouse_db}.{MART}"
        ).result_rows
    except Exception as exc:  # noqa: BLE001 — наружу отдаём контролируемую ошибку API
        raise RuntimeError(f"ClickHouse unavailable: {exc}") from exc
    value = rows[0][0] if rows else None
    return value if value and value >= date(1971, 1, 1) else None


def fetch_daily_rows(username: str, date_from: date, date_to: date) -> list[dict]:
    """Строки витрины по конкретному пользователю за период. Фильтр по username
    задаётся сервером из токена — доступ строго к собственным данным."""
    client = _client()
    result = client.query(
        f"""
        SELECT
            report_date, device_serial, device_model,
            steps, avg_battery_pct, avg_motor_load_pct,
            error_count, readings_count, active_hours
        FROM {settings.clickhouse_db}.{MART}
        WHERE username = %(u)s
          AND report_date BETWEEN %(f)s AND %(t)s
        ORDER BY report_date, device_serial
        """,
        parameters={"u": username, "f": date_from, "t": date_to},
    )
    cols = result.column_names
    return [dict(zip(cols, row)) for row in result.result_rows]

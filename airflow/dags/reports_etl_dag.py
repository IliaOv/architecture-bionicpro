from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta

import clickhouse_connect
import pendulum
from airflow.decorators import dag, task

log = logging.getLogger(__name__)

MART = "user_daily_report"

PG_HOSTPORT = os.getenv("SOURCES_PG_HOSTPORT", "sources-db:5432")
PG_DB = os.getenv("SOURCES_PG_DB", "sources")
PG_USER = os.getenv("SOURCES_PG_USER", "sources_user")
PG_PASSWORD = os.getenv("SOURCES_PG_PASSWORD", "sources_password")

CH_HOST = os.getenv("CLICKHOUSE_HOST", "clickhouse")
CH_PORT = int(os.getenv("CLICKHOUSE_PORT", "8123"))
CH_USER = os.getenv("CLICKHOUSE_USER", "default")
CH_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")


def _ch_client():
    return clickhouse_connect.get_client(
        host=CH_HOST, port=CH_PORT, username=CH_USER, password=CH_PASSWORD
    )


def _pg(table: str, schema: str) -> str:
    """SQL-выражение табличной функции postgresql() для чтения источника из ClickHouse."""
    return (
        f"postgresql('{PG_HOSTPORT}', '{PG_DB}', '{table}', "
        f"'{PG_USER}', '{PG_PASSWORD}', '{schema}')"
    )


@dag(
    dag_id="reports_etl",
    description="CRM + телеметрия → витрина отчётности в ClickHouse",
    schedule="@daily",
    start_date=pendulum.datetime(2025, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=2)},
    tags=["bionicpro", "reports", "etl", "olap"],
)
def reports_etl():
    @task
    def create_mart() -> None:
        """Идемпотентно создаёт БД, витрину и таблицу watermark в ClickHouse."""
        client = _ch_client()
        client.command("CREATE DATABASE IF NOT EXISTS reports")
        client.command(
            """
            CREATE TABLE IF NOT EXISTS reports.user_daily_report
            (
                report_date        Date,
                username           String,
                client_id          UInt64,
                full_name          String,
                device_serial      String,
                device_model       String,
                steps              UInt64,
                avg_battery_pct    Float64,
                avg_motor_load_pct Float64,
                error_count        UInt64,
                readings_count     UInt64,
                active_hours       Float64,
                generated_at       DateTime DEFAULT now()
            )
            ENGINE = MergeTree
            PARTITION BY toYYYYMM(report_date)
            ORDER BY (username, report_date, device_serial)
            """
        )
        client.command(
            """
            CREATE TABLE IF NOT EXISTS reports.etl_watermark
            (
                mart String, last_date Date, updated_at DateTime
            )
            ENGINE = ReplacingMergeTree(updated_at)
            ORDER BY mart
            """
        )

    @task
    def resolve_window() -> dict:
        """Определяет диапазон [start; end] по watermark и границе завершённых суток."""
        client = _ch_client()
        yesterday = date.today() - timedelta(days=1)

        wm = client.query(
            "SELECT max(last_date) FROM reports.etl_watermark FINAL WHERE mart = %(m)s",
            parameters={"m": MART},
        ).result_rows
        last_done = wm[0][0] if wm and wm[0][0] else None

        if last_done and last_done >= date(1971, 1, 1):
            start = last_done + timedelta(days=1)
        else:
            min_ts = client.query(
                f"SELECT min(toDate(ts)) FROM {_pg('readings', 'telemetry')}"
            ).result_rows
            start = min_ts[0][0] if min_ts and min_ts[0][0] else yesterday

        if start > yesterday:
            log.info("Витрина уже актуальна: start=%s > yesterday=%s", start, yesterday)
            return {"start": None, "end": None}
        return {"start": start.isoformat(), "end": yesterday.isoformat()}

    @task
    def build_mart(window: dict) -> str:
        """Грузит витрину по суткам: агрегирует телеметрию в разрезе клиента,
        обогащает атрибутами CRM. Идемпотентно (DELETE перед INSERT по каждой дате)."""
        if not window["start"]:
            return "up-to-date"

        client = _ch_client()
        start = date.fromisoformat(window["start"])
        end = date.fromisoformat(window["end"])

        readings, devices, clients = (
            _pg("readings", "telemetry"),
            _pg("devices", "crm"),
            _pg("clients", "crm"),
        )

        day = start
        while day <= end:
            d = day.isoformat()
            # Идемпотентность: удаляем возможные ранее загруженные строки за сутки.
            client.command(
                "DELETE FROM reports.user_daily_report WHERE report_date = %(d)s",
                parameters={"d": d},
            )
            client.command(
                f"""
                INSERT INTO reports.user_daily_report
                    (report_date, username, client_id, full_name, device_serial,
                     device_model, steps, avg_battery_pct, avg_motor_load_pct,
                     error_count, readings_count, active_hours, generated_at)
                SELECT
                    toDate(t.ts)                              AS report_date,
                    c.username                                AS username,
                    c.client_id                               AS client_id,
                    c.full_name                               AS full_name,
                    t.device_serial                           AS device_serial,
                    d.model                                   AS device_model,
                    sum(t.steps)                              AS steps,
                    round(avg(t.battery_pct), 2)              AS avg_battery_pct,
                    round(avg(t.motor_load_pct), 2)           AS avg_motor_load_pct,
                    countIf(t.error_code != '')               AS error_count,
                    count()                                   AS readings_count,
                    round(count() / 60.0, 2)                  AS active_hours,
                    now()                                     AS generated_at
                FROM {readings} AS t
                INNER JOIN {devices} AS d ON d.device_serial = t.device_serial
                INNER JOIN {clients} AS c ON c.client_id = d.client_id
                WHERE toDate(t.ts) = %(d)s
                GROUP BY report_date, c.username, c.client_id, c.full_name,
                         t.device_serial, d.model
                """,
                parameters={"d": d},
            )
            log.info("Витрина загружена за %s", d)
            day += timedelta(days=1)
        return window["end"]

    @task
    def update_watermark(processed_end: str) -> None:
        """Сдвигает watermark: сервис отчётов отдаёт данные только до этой даты."""
        if processed_end == "up-to-date":
            return
        client = _ch_client()
        client.command(
            "INSERT INTO reports.etl_watermark (mart, last_date, updated_at) "
            "VALUES (%(m)s, %(d)s, %(u)s)",
            parameters={"m": MART, "d": processed_end, "u": datetime.utcnow()},
        )
        log.info("Watermark обновлён: %s = %s", MART, processed_end)

    window = resolve_window()
    create_mart() >> window
    update_watermark(build_mart(window))


reports_etl()

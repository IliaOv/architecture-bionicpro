-- DDL витрины Task 2 (batch-ETL / Airflow).
-- Используется только изолированным стендом airflow/docker-compose.task2.yml.

CREATE DATABASE IF NOT EXISTS reports;

CREATE TABLE IF NOT EXISTS reports.user_daily_report
(
    report_date         Date,
    username            String,
    client_id           UInt64,
    full_name           String,
    device_serial       String,
    device_model        String,
    steps               UInt64,
    avg_battery_pct     Float64,
    avg_motor_load_pct  Float64,
    error_count         UInt64,
    readings_count      UInt64,
    active_hours        Float64,
    generated_at        DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(report_date)
ORDER BY (username, report_date, device_serial);

CREATE TABLE IF NOT EXISTS reports.etl_watermark
(
    mart         String,
    last_date    Date,
    updated_at   DateTime
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY mart;

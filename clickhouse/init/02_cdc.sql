-- ============================================================================
-- Task 4. Приём CDC из Kafka в ClickHouse и витрина через MaterializedView.
--
-- Цель (разделение OLTP/OLAP): массовые выгрузки больше не читают CRM.
-- Изменения идут из WAL → Debezium → Kafka → сюда. Аналитика — только в OLAP.
--
-- Поток:
--   KafkaEngine (очереди) → MaterializedView → сырые измерения / витрина
--
-- Debezium SMT ExtractNewRecordState (unwrap): значение = плоская строка after
-- + метаполя __op, __source_ts_ms, __deleted. Формат JSONEachRow.
-- Топики: bionic.<schema>.<table> (topic.prefix=bionic).
--
-- П.4 задания: витрина собирается MaterializedView mv_user_daily_report,
-- который ОБЪЕДИНЯЕТ телеметрию с CRM (clients + devices) через JOIN.
-- ============================================================================

CREATE DATABASE IF NOT EXISTS reports;

-- ----------------------------------------------------------------------------
-- CRM: clients. Kafka → MV → текущее состояние.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reports.clients_queue
(
    client_id  UInt64,
    username   String,
    full_name  String,
    __deleted  String
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9092',
         kafka_topic_list = 'bionic.crm.clients',
         kafka_group_name = 'ch_clients_v3',
         kafka_format = 'JSONEachRow',
         kafka_num_consumers = 1,
         input_format_skip_unknown_fields = 1,
         input_format_null_as_default = 1;

CREATE TABLE IF NOT EXISTS reports.clients_raw
(
    client_id  UInt64,
    username   String,
    full_name  String,
    is_deleted UInt8,
    synced_at  DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(synced_at)
ORDER BY client_id;

CREATE MATERIALIZED VIEW IF NOT EXISTS reports.mv_clients TO reports.clients_raw AS
SELECT
    client_id,
    username,
    full_name,
    toUInt8(__deleted = 'true') AS is_deleted,
    now()                       AS synced_at
FROM reports.clients_queue;

-- ----------------------------------------------------------------------------
-- CRM: devices. Kafka → MV → текущее состояние.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reports.devices_queue
(
    device_serial String,
    client_id     UInt64,
    model         String,
    __deleted     String
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9092',
         kafka_topic_list = 'bionic.crm.devices',
         kafka_group_name = 'ch_devices_v3',
         kafka_format = 'JSONEachRow',
         kafka_num_consumers = 1,
         input_format_skip_unknown_fields = 1,
         input_format_null_as_default = 1;

CREATE TABLE IF NOT EXISTS reports.devices_raw
(
    device_serial String,
    client_id     UInt64,
    model         String,
    is_deleted    UInt8,
    synced_at     DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(synced_at)
ORDER BY device_serial;

CREATE MATERIALIZED VIEW IF NOT EXISTS reports.mv_devices TO reports.devices_raw AS
SELECT
    device_serial,
    client_id,
    model,
    toUInt8(__deleted = 'true') AS is_deleted,
    now()                       AS synced_at
FROM reports.devices_queue;

-- ----------------------------------------------------------------------------
-- Телеметрия: очередь Kafka (факт).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reports.readings_queue
(
    reading_id     Int64,
    device_serial  String,
    ts             String,
    steps          Int64,
    battery_pct    Float64,
    motor_load_pct Float64,
    error_code     String,
    __deleted      String
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9092',
         kafka_topic_list = 'bionic.telemetry.readings',
         kafka_group_name = 'ch_readings_v3',
         kafka_format = 'JSONEachRow',
         kafka_num_consumers = 1,
         input_format_skip_unknown_fields = 1,
         input_format_null_as_default = 1;

-- ----------------------------------------------------------------------------
-- Состояние витрины (денормализованная «звезда» Кимбалла в одной таблице).
-- Агрегаты — AggregateFunction: инкрементально без повторного чтения OLTP.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reports.user_daily_report_state
(
    report_date      Date,
    username         String,
    client_id        UInt64,
    full_name        String,
    device_serial    String,
    device_model     String,
    steps_state      AggregateFunction(sum, UInt64),
    battery_state    AggregateFunction(avg, Float64),
    motor_load_state AggregateFunction(avg, Float64),
    error_state      AggregateFunction(sum, UInt64),
    readings_state   AggregateFunction(count)
)
ENGINE = AggregatingMergeTree
PARTITION BY toYYYYMM(report_date)
ORDER BY (username, report_date, device_serial);

-- ----------------------------------------------------------------------------
-- П.4: MaterializedView, который ОБЪЕДИНЯЕТ телеметрию с CRM (JOIN) и пишет
-- в состояние витрины. LIMIT 1 BY — актуальная версия строки ReplacingMergeTree
-- без FINAL в потоковом JOIN.
-- ----------------------------------------------------------------------------
CREATE MATERIALIZED VIEW IF NOT EXISTS reports.mv_user_daily_report
TO reports.user_daily_report_state AS
SELECT
    toDate(parseDateTimeBestEffortOrNull(r.ts)) AS report_date,
    c.username                                  AS username,
    c.client_id                                 AS client_id,
    c.full_name                                 AS full_name,
    r.device_serial                             AS device_serial,
    d.model                                     AS device_model,
    sumState(toUInt64(r.steps))                 AS steps_state,
    avgState(r.battery_pct)                     AS battery_state,
    avgState(r.motor_load_pct)                  AS motor_load_state,
    sumState(toUInt64(r.error_code != ''))      AS error_state,
    countState()                                AS readings_state
FROM reports.readings_queue AS r
INNER JOIN
(
    SELECT device_serial, client_id, model
    FROM reports.devices_raw
    WHERE is_deleted = 0
    ORDER BY synced_at DESC
    LIMIT 1 BY device_serial
) AS d ON d.device_serial = r.device_serial
INNER JOIN
(
    SELECT client_id, username, full_name
    FROM reports.clients_raw
    WHERE is_deleted = 0
    ORDER BY synced_at DESC
    LIMIT 1 BY client_id
) AS c ON c.client_id = d.client_id
WHERE r.__deleted != 'true'
  AND r.ts != ''
  AND parseDateTimeBestEffortOrNull(r.ts) IS NOT NULL
GROUP BY
    report_date,
    username,
    client_id,
    full_name,
    device_serial,
    device_model;

-- ----------------------------------------------------------------------------
-- Контракт чтения для reports-api (те же колонки, что в Task 2/3).
-- Финализация AggregateFunction → обычные числа.
-- ----------------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS reports.user_daily_report AS
SELECT
    report_date,
    username,
    client_id,
    full_name,
    device_serial,
    device_model,
    sumMerge(steps_state)                       AS steps,
    round(avgMerge(battery_state), 2)           AS avg_battery_pct,
    round(avgMerge(motor_load_state), 2)        AS avg_motor_load_pct,
    sumMerge(error_state)                       AS error_count,
    countMerge(readings_state)                  AS readings_count,
    round(countMerge(readings_state) / 60.0, 2) AS active_hours
FROM reports.user_daily_report_state
GROUP BY
    report_date,
    username,
    client_id,
    full_name,
    device_serial,
    device_model;

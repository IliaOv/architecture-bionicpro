
CREATE SCHEMA IF NOT EXISTS crm;
CREATE SCHEMA IF NOT EXISTS telemetry;

CREATE TABLE crm.clients (
    client_id   BIGINT PRIMARY KEY,
    username    TEXT NOT NULL UNIQUE,
    full_name   TEXT NOT NULL,
    email       TEXT,
    country     TEXT NOT NULL DEFAULT 'RU',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE crm.devices (
    device_serial TEXT PRIMARY KEY,
    client_id     BIGINT NOT NULL REFERENCES crm.clients(client_id),
    model         TEXT NOT NULL,
    implant_date  DATE NOT NULL
);

INSERT INTO crm.clients (client_id, username, full_name, email, country) VALUES
    (1001, 'prothetic1', 'Prothetic One', 'prothetic1@example.com', 'RU'),
    (1002, 'user1',      'User One',      'user1@example.com',      'RU'),
    (1003, 'admin1',     'Admin One',     'admin1@example.com',     'RU');

INSERT INTO crm.devices (device_serial, client_id, model, implant_date) VALUES
    ('BP-ARM-0001', 1001, 'BionicArm X2',  '2025-01-15'),
    ('BP-LEG-0007', 1001, 'BionicLeg L1',  '2025-03-02'),
    ('BP-ARM-0042', 1002, 'BionicArm X1',  '2025-05-20'),
    ('BP-ARM-0100', 1003, 'BionicArm X2',  '2025-02-10');


CREATE TABLE telemetry.readings (
    reading_id      BIGSERIAL PRIMARY KEY,
    device_serial   TEXT NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    steps           INTEGER NOT NULL,
    battery_pct     NUMERIC(5,2) NOT NULL,
    motor_load_pct  NUMERIC(5,2) NOT NULL,
    error_code      TEXT NOT NULL DEFAULT ''
);

CREATE INDEX idx_readings_ts ON telemetry.readings (ts);
CREATE INDEX idx_readings_device ON telemetry.readings (device_serial);

INSERT INTO telemetry.readings (device_serial, ts, steps, battery_pct, motor_load_pct, error_code)
SELECT
    d.device_serial,
    (CURRENT_DATE - offs) + (make_interval(hours => h)) AS ts,
    (random() * 400)::int                                AS steps,
    round((40 + random() * 60)::numeric, 2)              AS battery_pct,
    round((10 + random() * 80)::numeric, 2)              AS motor_load_pct,
    CASE WHEN random() < 0.03 THEN 'E' || (100 + (random() * 5)::int)::text ELSE '' END AS error_code
FROM (VALUES ('BP-ARM-0001'), ('BP-LEG-0007'), ('BP-ARM-0042'), ('BP-ARM-0100')) AS d(device_serial)
CROSS JOIN generate_series(1, 45) AS offs      -- дни назад: 1..45 (все завершённые сутки)
CROSS JOIN generate_series(0, 23) AS h;        -- часы 0..23

-- OLAP сервиса отчётов (ClickHouse).
-- База создаётся здесь; CDC-очереди, MaterializedView и витрина — в 02_cdc.sql.

CREATE DATABASE IF NOT EXISTS reports;

FROM apache/airflow:2.9.3-python3.11

# Нужен для DAG reports_etl (импорт на этапе parse DagBag).
USER airflow
RUN pip install --no-cache-dir "clickhouse-connect==0.7.16"

"""reports-api — ресурс-сервис отчётности BionicPRO.

Отдаёт пользователю готовый отчёт по его протезам. Ключевые свойства:
  * bearer-only: без валидного токена — 401 (см. security.py);
  * self-only: отчёт строится ТОЛЬКО по username из токена, клиент не может
    запросить чужой отчёт;
  * без realtime-вычислений: читаются заранее собранные строки витрины
    (Task 4 — потоково через CDC: Debezium → Kafka → ClickHouse MaterializedView);
  * не отдаёт данные за период, которого ещё нет в OLAP (ограничение по watermark).

Task 3 — снижение нагрузки на OLAP через кеш готовых отчётов в S3 + CDN:
  * отчёт версии витрины (watermark) строится из ClickHouse один раз и
    кладётся в S3; повторный запрос не делает тяжёлый SELECT по витрине —
    только HEAD в S3 (+ лёгкий watermark) и ссылка на CDN; байты раздаёт CDN.
"""

import json
import logging
from datetime import date, timedelta
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, status

from . import storage
from .config import settings
from .olap import fetch_daily_rows, get_watermark
from .security import Principal, current_principal

logger = logging.getLogger("reports-api")

app = FastAPI(title="reports-api", version="1.1.0")


@app.on_event("startup")
async def _bootstrap_storage() -> None:
    """Best-effort: создать бакет и открыть анонимное чтение для CDN.
    Если MinIO ещё не поднялся — не валим сервис, повторим при первом запросе."""
    try:
        storage.ensure_bucket()
    except Exception as exc:  # noqa: BLE001 — старт не должен падать из-за MinIO
        logger.warning("S3 bucket bootstrap deferred: %s", exc)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


def _summarize(rows: list[dict]) -> dict:
    if not rows:
        return {
            "total_steps": 0,
            "avg_battery_pct": None,
            "avg_motor_load_pct": None,
            "total_errors": 0,
            "total_active_hours": 0.0,
            "days": 0,
        }
    total_steps = sum(r["steps"] for r in rows)
    total_errors = sum(r["error_count"] for r in rows)
    total_active = round(sum(r["active_hours"] for r in rows), 2)
    weighted_batt = sum(r["avg_battery_pct"] * r["readings_count"] for r in rows)
    weighted_load = sum(r["avg_motor_load_pct"] * r["readings_count"] for r in rows)
    total_readings = sum(r["readings_count"] for r in rows) or 1
    return {
        "total_steps": total_steps,
        "avg_battery_pct": round(weighted_batt / total_readings, 2),
        "avg_motor_load_pct": round(weighted_load / total_readings, 2),
        "total_errors": total_errors,
        "total_active_hours": total_active,
        "days": len({r["report_date"] for r in rows}),
    }


def _resolve_window(
    date_from: Optional[date], date_to: Optional[date]
) -> tuple[date, date, date]:
    """Возвращает (watermark, date_from, effective_to) с теми же проверками
    готовности данных. Вычисляется до похода в OLAP — от него зависит ключ кеша."""
    try:
        watermark = get_watermark()
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    if watermark is None:
        # Витрина ещё пуста (CDC не успел наполнить OLAP).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Отчёты ещё не готовы: витрина не наполнена CDC",
        )

    # Период по умолчанию: последние N суток до watermark.
    if date_to is None:
        date_to = watermark
    if date_from is None:
        date_from = watermark - timedelta(days=settings.default_window_days - 1)

    if date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from > date_to")

    # Нельзя запрашивать данные за период, ещё не попавший в витрину (CDC).
    if date_from > watermark:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Данные за запрошенный период ещё не готовы. "
                f"Доступно до {watermark.isoformat()} включительно."
            ),
        )
    # Верхнюю границу подрезаем до watermark (частично готовый период).
    return watermark, date_from, min(date_to, watermark)


def _build_report_body(
    principal: Principal, date_from: date, effective_to: date, watermark: date
) -> dict:
    """Тяжёлая часть: читает готовые строки витрины из OLAP и собирает отчёт."""
    rows = fetch_daily_rows(principal.username, date_from, effective_to)
    for r in rows:
        r["report_date"] = r["report_date"].isoformat()

    return {
        "user": principal.username,
        "period": {"from": date_from.isoformat(), "to": effective_to.isoformat()},
        "data_available_until": watermark.isoformat(),
        "summary": _summarize(rows),
        "daily": rows,
    }


@app.api_route("/reports", methods=["GET", "POST"])
async def reports(
    principal: Principal = Depends(current_principal),
    date_from: Optional[date] = Query(default=None, alias="from"),
    date_to: Optional[date] = Query(default=None, alias="to"),
) -> dict:
    """Возвращает ссылку на CDN с готовым отчётом текущего пользователя.

    Сначала проверяет наличие отчёта в S3 (по версионному ключу с watermark):
      * есть  → отдаёт ссылку на CDN (тяжёлый SELECT по витрине не выполняется);
      * нет   → строит из OLAP, кладёт в S3, отдаёт ссылку на CDN.
    """
    watermark, dfrom, dto = _resolve_window(date_from, date_to)
    key = storage.object_key(principal.username, dfrom, dto, watermark)

    try:
        cached = storage.report_exists(key)
        if not cached:
            body = _build_report_body(principal, dfrom, dto, watermark)
            storage.put_report(
                key, json.dumps(body, ensure_ascii=False).encode("utf-8")
            )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return {
        "user": principal.username,
        "period": {"from": dfrom.isoformat(), "to": dto.isoformat()},
        "data_available_until": watermark.isoformat(),
        "cached": cached,
        "report_url": storage.cdn_url(key),
    }

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

from . import ReservationYamlRepository
from .yaml_store import BUSINESS_END_HOUR, BUSINESS_START_HOUR, suggest_reservation_options_from_text
import reservation_manager.yaml_store as yaml_store

ROOM_RESOURCES = [f"회의실{i}" for i in range(1, 11)]
DEVICE_RESOURCES = [f"테스트단말기{i}" for i in range(1, 21)]


def create_app(data_dir: str | Path = "data") -> Flask:
    app = Flask(__name__, template_folder="../templates")
    repository = ReservationYamlRepository(data_dir)

    @app.after_request
    def add_cors_headers(response: Any) -> Any:
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET,POST,OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/schedule")
    def get_schedule() -> Any:
        now = datetime.now()
        repository.close_expired(now)

        active = repository.get_active_reservations()
        period = str(request.args.get("period", "day")).lower()
        period_days = _period_to_days(period)
        default_window_start = now.replace(hour=BUSINESS_START_HOUR, minute=0, second=0, microsecond=0)
        window_start = default_window_start
        window_end = window_start + timedelta(days=period_days)

        if period == "day":
            business_start = now.replace(hour=BUSINESS_START_HOUR, minute=0, second=0, microsecond=0)
            business_end = now.replace(hour=BUSINESS_END_HOUR, minute=0, second=0, microsecond=0)
            if now <= business_start:
                window_start = business_start
            elif now >= business_end:
                window_start = business_end - timedelta(minutes=10)
            else:
                window_start = now.replace(minute=(now.minute // 10) * 10, second=0, microsecond=0)
            window_end = business_end

        blocked_intervals, blocked_days, _business_days = _build_blocked_intervals(window_start, window_end)
        rooms = _build_rows(ROOM_RESOURCES, active, window_start, window_end, blocked_days, now)
        devices = _build_rows(DEVICE_RESOURCES, active, window_start, window_end, blocked_days, now)

        return jsonify(
            {
                "period": period,
                "window_start": window_start.isoformat(timespec="minutes"),
                "window_end": window_end.isoformat(timespec="minutes"),
                "blocked_intervals": blocked_intervals,
                "rooms": rooms,
                "devices": devices,
            }
        )

    @app.post("/api/reserve/options")
    def reserve_options() -> Any:
        payload = request.get_json(silent=True) or {}
        text = str(payload.get("text", "")).strip()
        if not text:
            return jsonify({"ok": False, "message": "예약 요청 문장을 입력해주세요."}), 400

        now = datetime.now()
        try:
            options = suggest_reservation_options_from_text(text, repository, now=now, limit=3)
        except ValueError as error:
            return jsonify({"ok": False, "message": str(error)}), 400
        except Exception:
            return jsonify({"ok": False, "message": "예약 처리 중 알 수 없는 오류가 발생했습니다."}), 500

        if not options:
            return jsonify({"ok": False, "message": "요청 조건으로 가능한 회피 예약 옵션을 찾지 못했습니다."}), 400

        strategy_labels = {
            "requested": "요청 시간 그대로",
            "time_shift_before": "요청 시간 이전으로 이동",
            "time_shift_after": "요청 시간 이후로 이동",
            "other_resource_same_time": "다른 자원 동일 시간",
        }

        return jsonify(
            {
                "ok": True,
                "options": [
                    {
                        **option.to_dict(),
                        "label": strategy_labels.get(option.strategy, option.strategy),
                    }
                    for option in options
                ],
            }
        )

    @app.post("/api/reserve/commit")
    def reserve_commit() -> Any:
        payload = request.get_json(silent=True) or {}
        text = str(payload.get("text", "")).strip()
        option = payload.get("option") or {}

        if not text:
            return jsonify({"ok": False, "message": "예약 요청 문장을 입력해주세요."}), 400

        try:
            strategy = str(option.get("strategy", "")).strip()
            resource = str(option.get("resource", "")).strip()
            start = datetime.fromisoformat(str(option.get("start", "")))
            end = datetime.fromisoformat(str(option.get("end", "")))
        except Exception:
            return jsonify({"ok": False, "message": "선택한 예약 옵션 형식이 올바르지 않습니다."}), 400

        now = datetime.now()
        try:
            created = repository.add_reservation(
                resource=resource,
                start=start,
                end=end,
                request_text=text,
                now=now,
            )
        except ValueError as error:
            return jsonify({"ok": False, "message": str(error)}), 400
        except Exception:
            return jsonify({"ok": False, "message": "예약 확정 중 알 수 없는 오류가 발생했습니다."}), 500

        return jsonify(
            {
                "ok": True,
                "strategy": strategy,
                "reservation": {
                    "resource": created.resource,
                    "start": created.start.isoformat(timespec="minutes"),
                    "end": created.end.isoformat(timespec="minutes"),
                },
            }
        )

    return app


def _period_to_days(period: str) -> int:
    if period == "day":
        return 1
    if period == "week":
        return 7
    return 30


def _build_blocked_intervals(window_start: datetime, window_end: datetime) -> tuple[list[dict[str, str]], int, int]:
    blocked: list[dict[str, str]] = []
    blocked_days = 0
    business_days = 0

    cursor = window_start.date()
    while cursor < window_end.date():
        day_start = datetime(cursor.year, cursor.month, cursor.day, BUSINESS_START_HOUR, 0)
        day_end = datetime(cursor.year, cursor.month, cursor.day, BUSINESS_END_HOUR, 0)
        if yaml_store._is_business_day(cursor):
            business_days += 1
        else:
            blocked_days += 1
            blocked.append(
                {
                    "start": day_start.isoformat(timespec="minutes"),
                    "end": day_end.isoformat(timespec="minutes"),
                }
            )
        cursor += timedelta(days=1)

    return blocked, blocked_days, business_days


def _build_rows(
    resources: list[str],
    active_records: list[Any],
    window_start: datetime,
    window_end: datetime,
    blocked_days: int,
    now: datetime,
) -> list[dict[str, Any]]:
    grouped: dict[str, list[Any]] = {resource: [] for resource in resources}
    for record in active_records:
        if record.resource in grouped:
            grouped[record.resource].append(record)

    slots_per_day = BUSINESS_END_HOUR - BUSINESS_START_HOUR
    blocked_slots = blocked_days * slots_per_day
    bookable_minutes = _calculate_bookable_minutes(window_start, window_end)
    bookable_slots = max(0, (bookable_minutes + 59) // 60)

    rows: list[dict[str, Any]] = []
    for resource in resources:
        reservations = sorted(
            [item for item in grouped[resource] if _overlaps_window(item.start, item.end, window_start, window_end)],
            key=lambda item: item.start,
        )

        reserved_minutes = 0
        for row in reservations:
            clipped_start = max(row.start, window_start)
            clipped_end = min(row.end, window_end)
            minutes = max(0, int((clipped_end - clipped_start).total_seconds() // 60))
            reserved_minutes += minutes

        reserved_slots = 0 if reserved_minutes <= 0 else max(1, (reserved_minutes + 59) // 60)

        unavailable_slots = blocked_slots + reserved_slots
        remaining_minutes = max(0, bookable_minutes - reserved_minutes)
        available_slots = 0 if remaining_minutes <= 0 else max(1, (remaining_minutes + 59) // 60)

        rows.append(
            {
                "resource": resource,
                "reservation_count": len(reservations),
                "reserved_slots": reserved_slots,
                "available_slots": available_slots,
                "unavailable_slots": unavailable_slots,
                "occupancy_rate": (reserved_minutes / bookable_minutes) if bookable_minutes > 0 else 0.0,
                "is_currently_occupied": any(item.start <= now < item.end for item in grouped[resource]),
                "reservations": [
                    {
                        "reservation_id": row.reservation_id,
                        "start": row.start.isoformat(timespec="minutes"),
                        "end": row.end.isoformat(timespec="minutes"),
                        "request_text": row.request_text,
                    }
                    for row in reservations
                ],
            }
        )

    return sorted(rows, key=lambda row: (row["reservation_count"], row["resource"]))


def _overlaps_window(start: datetime, end: datetime, window_start: datetime, window_end: datetime) -> bool:
    return start < window_end and end > window_start


def _calculate_bookable_minutes(window_start: datetime, window_end: datetime) -> int:
    if window_end <= window_start:
        return 0

    total_minutes = 0
    cursor = window_start.date()

    while True:
        day_start = datetime(cursor.year, cursor.month, cursor.day, BUSINESS_START_HOUR, 0)
        day_end = datetime(cursor.year, cursor.month, cursor.day, BUSINESS_END_HOUR, 0)

        if yaml_store._is_business_day(cursor):
            segment_start = max(window_start, day_start)
            segment_end = min(window_end, day_end)
            if segment_end > segment_start:
                total_minutes += int((segment_end - segment_start).total_seconds() // 60)

        if day_end >= window_end:
            break
        cursor += timedelta(days=1)

    return total_minutes


if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=5000, debug=False)

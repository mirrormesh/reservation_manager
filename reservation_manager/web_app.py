from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from flask import Flask, jsonify, render_template, request

from . import ReservationYamlRepository
from .natural_language import parse_reservation_request
from .yaml_store import BUSINESS_END_HOUR, BUSINESS_START_HOUR, suggest_reservation_options
import reservation_manager.yaml_store as yaml_store

ROOM_RESOURCES = [f"회의실{i}" for i in range(1, 11)]
DEVICE_RESOURCES = [f"테스트단말기{i}" for i in range(1, 21)]
SELF_OVERLAP_STRATEGIES = {"merge_existing", "replace_existing", "keep_existing"}


def create_app(
    data_dir: str | Path = "data",
    now_provider: Callable[[], datetime] | None = None,
) -> Flask:
    app = Flask(__name__, template_folder="../templates")
    repository = ReservationYamlRepository(data_dir)
    clock: Callable[[], datetime] = now_provider or datetime.now

    def _serialize_user_reservation(record: Any) -> dict[str, Any]:
        return {
            "reservation_id": record.reservation_id,
            "resource": record.resource,
            "start": record.start.isoformat(timespec="minutes"),
            "end": record.end.isoformat(timespec="minutes"),
            "created_at": record.created_at.isoformat(timespec="seconds"),
            "updated_at": record.updated_at.isoformat(timespec="seconds"),
            "request_text": record.request_text,
            "owner": getattr(record, "owner", None),
            "is_mine": getattr(record, "owner", None) == yaml_store.OWNER_SELF,
        }

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
        now = clock()
        repository.close_expired(now)

        active = repository.get_active_reservations()
        period = str(request.args.get("period", "day")).lower()
        period_days = _period_to_days(period)
        default_window_start = now.replace(hour=BUSINESS_START_HOUR, minute=0, second=0, microsecond=0)
        window_start = default_window_start
        window_end = window_start + timedelta(days=period_days)

        if period == "day":
            business_start_today = now.replace(hour=BUSINESS_START_HOUR, minute=0, second=0, microsecond=0)
            business_end_today = now.replace(hour=BUSINESS_END_HOUR, minute=0, second=0, microsecond=0)

            if now >= business_end_today:
                next_day = _next_business_day(now.date())
                window_start, window_end = _business_day_bounds(next_day)
            elif now <= business_start_today:
                window_start = business_start_today
                window_end = business_end_today
            else:
                window_start = now.replace(minute=(now.minute // 10) * 10, second=0, microsecond=0)
                window_end = business_end_today

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

    @app.get("/api/my-reservations")
    def get_my_reservations() -> Any:
        now = clock()
        repository.close_expired(now)
        owned = [record for record in repository.get_active_reservations() if record.owner == yaml_store.OWNER_SELF]
        owned.sort(key=lambda record: (record.start, record.resource))
        return jsonify({"ok": True, "reservations": [_serialize_user_reservation(record) for record in owned]})

    @app.post("/api/my-reservations/delete")
    def delete_my_reservation() -> Any:
        payload = request.get_json(silent=True) or {}
        reservation_id = str(payload.get("reservation_id", "")).strip()
        if not reservation_id:
            return jsonify({"ok": False, "message": "reservation_id가 필요합니다."}), 400

        record = repository.get_active_reservation(reservation_id)
        if record is None:
            return jsonify({"ok": False, "message": "예약을 찾지 못했습니다."}), 404
        if record.owner != yaml_store.OWNER_SELF:
            return jsonify({"ok": False, "message": "이 예약은 삭제할 수 없습니다."}), 403

        deleted = repository.delete_reservation(reservation_id, now=clock())
        return jsonify({"ok": True, "reservation": _serialize_user_reservation(deleted)})

    @app.post("/api/my-reservations/update")
    def update_my_reservation() -> Any:
        payload = request.get_json(silent=True) or {}
        reservation_id = str(payload.get("reservation_id", "")).strip()
        text = str(payload.get("text", "")).strip()
        if not reservation_id or not text:
            return jsonify({"ok": False, "message": "reservation_id와 수정 요청 문장을 모두 입력해주세요."}), 400

        existing = repository.get_active_reservation(reservation_id)
        if existing is None:
            return jsonify({"ok": False, "message": "예약을 찾지 못했습니다."}), 404
        if existing.owner != yaml_store.OWNER_SELF:
            return jsonify({"ok": False, "message": "이 예약은 변경할 수 없습니다."}), 403

        now = clock()
        try:
            parsed = parse_reservation_request(text, reference_datetime=now)
        except ValueError as error:
            return jsonify({"ok": False, "message": str(error)}), 400

        if not parsed.resource:
            return jsonify({"ok": False, "message": "예약 자원을 찾지 못했습니다."}), 400

        try:
            updated = repository.update_reservation(
                reservation_id,
                resource=parsed.resource,
                start=parsed.start,
                end=parsed.end,
                now=now,
                request_text=text,
            )
        except ValueError as error:
            return jsonify({"ok": False, "message": str(error)}), 400

        return jsonify({"ok": True, "reservation": _serialize_user_reservation(updated)})

    @app.post("/api/reserve/options")
    def reserve_options() -> Any:
        payload = request.get_json(silent=True) or {}
        text = str(payload.get("text", "")).strip()
        if not text:
            return jsonify({"ok": False, "message": "예약 요청 문장을 입력해주세요."}), 400

        now = clock()
        try:
            parsed = parse_reservation_request(text, reference_datetime=now)
        except ValueError as error:
            return jsonify({"ok": False, "message": str(error)}), 400

        if not parsed.resource:
            return jsonify({"ok": False, "message": "예약 자원을 찾지 못했습니다."}), 400

        overlaps = repository.find_self_owned_overlaps(parsed.resource, parsed.start, parsed.end, now=now)
        if overlaps:
            options = _build_self_overlap_options(parsed.resource, parsed.start, parsed.end, overlaps)
            return jsonify(
                {
                    "ok": True,
                    "self_overlap": True,
                    "options": options,
                    "existing": [_serialize_user_reservation(record) for record in overlaps],
                    "requested": {
                        "resource": parsed.resource,
                        "start": parsed.start.isoformat(timespec="minutes"),
                        "end": parsed.end.isoformat(timespec="minutes"),
                    },
                }
            )

        try:
            created = repository.add_reservation(
                resource=parsed.resource,
                start=parsed.start,
                end=parsed.end,
                request_text=text,
                now=now,
            )
            merged_existing = created.change_source == "merged"
            return jsonify(
                {
                    "ok": True,
                    "auto_reserved": True,
                    "strategy": "merged" if merged_existing else "requested",
                    "merged_existing": merged_existing,
                    "reservation": {
                        "resource": created.resource,
                        "start": created.start.isoformat(timespec="minutes"),
                        "end": created.end.isoformat(timespec="minutes"),
                        "change_source": created.change_source,
                    },
                }
            )
        except ValueError as error:
            if "overlaps" not in str(error):
                return jsonify({"ok": False, "message": str(error)}), 400

        try:
            options = suggest_reservation_options(
                repository=repository,
                resource=parsed.resource,
                start=parsed.start,
                end=parsed.end,
                now=now,
                limit=3,
            )
        except ValueError as error:
            return jsonify({"ok": False, "message": str(error)}), 400

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

        reservation_ids = [str(value).strip() for value in option.get("reservation_ids", []) if str(value).strip()]

        if strategy in SELF_OVERLAP_STRATEGIES:
            if not reservation_ids:
                return jsonify({"ok": False, "message": "겹치는 예약 정보가 누락되었습니다."}), 400

            now = clock()
            try:
                if strategy == "merge_existing":
                    created = repository.merge_self_owned_reservations(
                        resource,
                        start,
                        end,
                        reservation_ids,
                        request_text=text,
                        now=now,
                    )
                    response_payload = {
                        "ok": True,
                        "strategy": strategy,
                        "merged_existing": True,
                        "reservation": {
                            "resource": created.resource,
                            "start": created.start.isoformat(timespec="minutes"),
                            "end": created.end.isoformat(timespec="minutes"),
                            "change_source": created.change_source,
                        },
                    }
                elif strategy == "replace_existing":
                    created = repository.replace_self_owned_reservations(
                        resource,
                        start,
                        end,
                        reservation_ids,
                        request_text=text,
                        now=now,
                    )
                    response_payload = {
                        "ok": True,
                        "strategy": strategy,
                        "reservation": {
                            "resource": created.resource,
                            "start": created.start.isoformat(timespec="minutes"),
                            "end": created.end.isoformat(timespec="minutes"),
                            "change_source": created.change_source,
                        },
                    }
                else:  # keep_existing
                    kept_records = [repository.get_active_reservation(reservation_id) for reservation_id in reservation_ids]
                    kept_records = [record for record in kept_records if record is not None]
                    if not kept_records:
                        return jsonify({"ok": False, "message": "유지할 예약을 찾지 못했습니다."}), 404
                    kept = min(kept_records, key=lambda record: (record.start, record.created_at))
                    response_payload = {
                        "ok": True,
                        "strategy": strategy,
                        "kept_existing": True,
                        "reservation": {
                            "resource": kept.resource,
                            "start": kept.start.isoformat(timespec="minutes"),
                            "end": kept.end.isoformat(timespec="minutes"),
                            "change_source": "kept",
                        },
                    }
            except ValueError as error:
                return jsonify({"ok": False, "message": str(error)}), 400
            except Exception:
                return jsonify({"ok": False, "message": "예약 확정 중 알 수 없는 오류가 발생했습니다."}), 500

            return jsonify(response_payload)

        now = clock()
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

        merged_existing = created.change_source == "merged"
        return jsonify(
            {
                "ok": True,
                "strategy": "merged" if merged_existing else strategy,
                "merged_existing": merged_existing,
                "reservation": {
                    "resource": created.resource,
                    "start": created.start.isoformat(timespec="minutes"),
                    "end": created.end.isoformat(timespec="minutes"),
                    "change_source": created.change_source,
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


def _business_day_bounds(target_date: date) -> tuple[datetime, datetime]:
    start = datetime(target_date.year, target_date.month, target_date.day, BUSINESS_START_HOUR, 0)
    end = datetime(target_date.year, target_date.month, target_date.day, BUSINESS_END_HOUR, 0)
    return start, end


def _next_business_day(base_date: date) -> date:
    candidate = base_date + timedelta(days=1)
    for _ in range(90):
        if yaml_store._is_business_day(candidate):
            return candidate
        candidate += timedelta(days=1)
    return candidate


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
                        "is_mine": row.owner == yaml_store.OWNER_SELF,
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


def _build_self_overlap_options(
    resource: str,
    requested_start: datetime,
    requested_end: datetime,
    overlaps: list[Any],
) -> list[dict[str, Any]]:
    overlap_ids = [record.reservation_id for record in overlaps]
    existing_start = min(record.start for record in overlaps)
    existing_end = max(record.end for record in overlaps)
    merged_start = min(existing_start, requested_start)
    merged_end = max(existing_end, requested_end)

    def _serialize_option(strategy: str, label: str, start_value: datetime, end_value: datetime) -> dict[str, Any]:
        return {
            "strategy": strategy,
            "label": label,
            "resource": resource,
            "start": start_value.isoformat(timespec="minutes"),
            "end": end_value.isoformat(timespec="minutes"),
            "reservation_ids": overlap_ids,
            "option_type": "self_overlap",
        }

    options = [
        _serialize_option("merge_existing", "기존 예약과 합치기", merged_start, merged_end),
        _serialize_option("replace_existing", "새 예약으로 덮어쓰기", requested_start, requested_end),
        {
            "strategy": "keep_existing",
            "label": "변경하지 않음",
            "resource": resource,
            "start": existing_start.isoformat(timespec="minutes"),
            "end": existing_end.isoformat(timespec="minutes"),
            "reservation_ids": overlap_ids,
            "option_type": "self_overlap",
        },
    ]
    return options


if __name__ == "__main__":
    app = create_app()
    app.run(host="127.0.0.1", port=5000, debug=False)

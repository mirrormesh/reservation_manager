from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
import random
import shutil
from uuid import uuid4

import holidays as pyholidays
import yaml

from .booking import Reservation, can_reserve


@dataclass(frozen=True)
class ReservationRecord:
    reservation_id: str
    resource: str
    start: datetime
    end: datetime
    created_at: datetime
    updated_at: datetime
    request_text: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {
            "reservation_id": self.reservation_id,
            "resource": self.resource,
            "start": self.start.isoformat(timespec="minutes"),
            "end": self.end.isoformat(timespec="minutes"),
            "created_at": self.created_at.isoformat(timespec="seconds"),
            "updated_at": self.updated_at.isoformat(timespec="seconds"),
        }
        if self.request_text is not None:
            payload["request_text"] = self.request_text
        return payload

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "ReservationRecord":
        return ReservationRecord(
            reservation_id=str(data["reservation_id"]),
            resource=str(data["resource"]),
            start=datetime.fromisoformat(str(data["start"])),
            end=datetime.fromisoformat(str(data["end"])),
            created_at=datetime.fromisoformat(str(data["created_at"])),
            updated_at=datetime.fromisoformat(str(data["updated_at"])),
            request_text=(str(data.get("request_text")) if data.get("request_text") is not None else None),
        )


@dataclass(frozen=True)
class ReservationAttemptResult:
    strategy: str
    reservation: ReservationRecord


@dataclass(frozen=True)
class ReservationOption:
    strategy: str
    resource: str
    start: datetime
    end: datetime

    def to_dict(self) -> dict[str, str]:
        return {
            "strategy": self.strategy,
            "resource": self.resource,
            "start": self.start.isoformat(timespec="minutes"),
            "end": self.end.isoformat(timespec="minutes"),
        }


class ReservationStorageError(RuntimeError):
    pass


BUSINESS_START_HOUR = 8
BUSINESS_END_HOUR = 19
RESERVATION_WINDOW_DAYS = 30
_KR_HOLIDAY_CACHE: dict[int, set[date]] = {}


class ReservationYamlRepository:
    def __init__(self, base_dir: str | Path = "data") -> None:
        self.base_dir = Path(base_dir)
        self.active_file = self.base_dir / "active_reservations.yaml"
        self.closed_file = self.base_dir / "closed_reservations.yaml"
        self.log_file = self.base_dir / "reservation_events.yaml"
        self._ensure_files()

    def _ensure_files(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        for path in (self.active_file, self.closed_file, self.log_file):
            if not path.exists():
                path.write_text("[]\n", encoding="utf-8")

    def _read_yaml_list(self, path: Path) -> list[dict[str, Any]]:
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            path.write_text("[]\n", encoding="utf-8")
            return []
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
            self._recover_corrupted_yaml(path, error)
            return []

        if payload is None:
            return []
        if not isinstance(payload, list):
            self._recover_corrupted_yaml(path, ValueError("top-level YAML is not a list"))
            return []

        sanitized: list[dict[str, Any]] = []
        for index, row in enumerate(payload):
            if isinstance(row, dict):
                sanitized.append(row)
            else:
                self._log_event(
                    "YAML_ROW_SKIPPED",
                    {
                        "file": str(path.name),
                        "index": index,
                        "reason": "row is not a mapping",
                    },
                )
        return sanitized

    def _write_yaml_list(self, path: Path, rows: list[dict[str, Any]]) -> None:
        temp_path = path.with_suffix(path.suffix + ".tmp")
        try:
            temp_path.write_text(yaml.safe_dump(rows, allow_unicode=True, sort_keys=False), encoding="utf-8")
            temp_path.replace(path)
        except OSError as error:
            raise ReservationStorageError(f"Failed to write YAML file: {path}") from error
        finally:
            if temp_path.exists():
                temp_path.unlink(missing_ok=True)

    def _recover_corrupted_yaml(self, path: Path, error: Exception) -> None:
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        backup_path = path.with_name(f"{path.stem}.corrupt.{timestamp}{path.suffix}")
        try:
            if path.exists():
                shutil.copy2(path, backup_path)
        except OSError:
            pass

        path.write_text("[]\n", encoding="utf-8")
        if path != self.log_file:
            self._log_event(
                "YAML_RECOVERED",
                {
                    "file": str(path.name),
                    "backup": str(backup_path.name),
                    "reason": str(error),
                },
            )

    def _log_event(self, event_type: str, payload: dict[str, Any], event_time: datetime | None = None) -> None:
        timestamp = (event_time or datetime.now()).isoformat(timespec="seconds")
        events = self._read_yaml_list(self.log_file)
        events.append({"event_time": timestamp, "event_type": event_type, "payload": payload})
        self._write_yaml_list(self.log_file, events)

    def get_active_reservations(self) -> list[ReservationRecord]:
        rows = self._read_yaml_list(self.active_file)
        return [ReservationRecord.from_dict(row) for row in rows]

    def get_closed_reservations(self) -> list[ReservationRecord]:
        rows = self._read_yaml_list(self.closed_file)
        return [ReservationRecord.from_dict(row) for row in rows]

    def add_reservation(
        self,
        resource: str,
        start: datetime,
        end: datetime,
        request_text: str | None = None,
        now: datetime | None = None,
    ) -> ReservationRecord:
        resource = _normalize_resource_name(resource)
        effective_now = now or datetime.now()
        start, end = _normalize_reservation_range(start, end)
        start, end = _apply_same_day_business_end_cap(start, end, effective_now)
        if start >= end:
            raise ValueError("Reservation start time must be earlier than end time.")

        _validate_bookable_request(start, end, effective_now)

        self.close_expired(effective_now)

        active = self.get_active_reservations()
        same_resource = [row for row in active if row.resource == resource]
        if not can_reserve(start, end, [Reservation(row.start, row.end) for row in same_resource]):
            raise ValueError("Reservation overlaps with an existing active reservation.")

        record = ReservationRecord(
            reservation_id=str(uuid4()),
            resource=resource,
            start=start,
            end=end,
            created_at=effective_now,
            updated_at=effective_now,
            request_text=request_text,
        )
        rows = self._read_yaml_list(self.active_file)
        rows.append(record.to_dict())
        self._write_yaml_list(self.active_file, rows)

        self._log_event(
            "RESERVATION_CREATED",
            {
                "reservation_id": record.reservation_id,
                "resource": resource,
                "start": record.start.isoformat(timespec="minutes"),
                "end": record.end.isoformat(timespec="minutes"),
                "request_text": request_text,
            },
            effective_now,
        )
        return record

    def update_reservation(
        self,
        reservation_id: str,
        *,
        resource: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        now: datetime | None = None,
    ) -> ReservationRecord:
        effective_now = now or datetime.now()
        self.close_expired(effective_now)

        rows = self._read_yaml_list(self.active_file)
        found_index = -1
        for index, row in enumerate(rows):
            if str(row.get("reservation_id")) == reservation_id:
                found_index = index
                break

        if found_index < 0:
            raise ValueError("reservation_id not found in active reservations")

        current = ReservationRecord.from_dict(rows[found_index])
        new_resource = _normalize_resource_name(resource) if resource is not None else current.resource
        new_start = start or current.start
        new_end = end or current.end
        new_start, new_end = _normalize_reservation_range(new_start, new_end)
        new_start, new_end = _apply_same_day_business_end_cap(new_start, new_end, effective_now)
        _validate_bookable_request(new_start, new_end, effective_now)

        other_rows = [ReservationRecord.from_dict(row) for i, row in enumerate(rows) if i != found_index]
        same_resource = [row for row in other_rows if row.resource == new_resource]
        if not can_reserve(new_start, new_end, [Reservation(row.start, row.end) for row in same_resource]):
            raise ValueError("Updated reservation overlaps with an existing active reservation.")

        updated = ReservationRecord(
            reservation_id=current.reservation_id,
            resource=new_resource,
            start=new_start,
            end=new_end,
            created_at=current.created_at,
            updated_at=effective_now,
            request_text=current.request_text,
        )
        rows[found_index] = updated.to_dict()
        self._write_yaml_list(self.active_file, rows)

        self._log_event(
            "RESERVATION_UPDATED",
            {
                "reservation_id": reservation_id,
                "resource": new_resource,
                "start": new_start.isoformat(timespec="minutes"),
                "end": new_end.isoformat(timespec="minutes"),
            },
            effective_now,
        )
        return updated

    def close_expired(self, now: datetime | None = None) -> int:
        effective_now = now or datetime.now()

        active_rows = self._read_yaml_list(self.active_file)
        remaining_active: list[dict[str, Any]] = []
        closed_now: list[dict[str, Any]] = []

        for row in active_rows:
            record = ReservationRecord.from_dict(row)
            if record.end <= effective_now:
                closed_now.append(record.to_dict())
            else:
                remaining_active.append(record.to_dict())

        if not closed_now:
            return 0

        closed_rows = self._read_yaml_list(self.closed_file)
        closed_rows.extend(closed_now)
        self._write_yaml_list(self.active_file, remaining_active)
        self._write_yaml_list(self.closed_file, closed_rows)

        for row in closed_now:
            self._log_event(
                "RESERVATION_CLOSED",
                {
                    "reservation_id": row["reservation_id"],
                    "resource": row["resource"],
                    "end": row["end"],
                },
                effective_now,
            )

        return len(closed_now)

    def seed_test_data(self, now: datetime | None = None, overwrite: bool = True) -> list[ReservationRecord]:
        effective_now = now or datetime.now()
        generated = generate_test_reservations(effective_now.date())

        if overwrite:
            self._write_yaml_list(self.active_file, [])
            self._write_yaml_list(self.closed_file, [])

        rows = self._read_yaml_list(self.active_file)
        rows.extend([row.to_dict() for row in generated])
        self._write_yaml_list(self.active_file, rows)

        self._log_event(
            "TEST_DATA_GENERATED",
            {
                "count": len(generated),
                "resource_types": {"meeting_rooms": 10, "test_devices": 20},
                "date_window_days": 30,
                "weekday_only": True,
                "business_hours": "08:00-19:00",
                "overwrite": overwrite,
            },
            effective_now,
        )
        return generated

    def seed_large_test_data(
        self,
        now: datetime | None = None,
        days: int = 30,
        slots_per_day: int = 4,
        overwrite: bool = True,
    ) -> list[ReservationRecord]:
        effective_now = now or datetime.now()
        generated = generate_large_test_reservations(
            start_date=effective_now.date(),
            days=days,
            slots_per_day=slots_per_day,
            reference_now=effective_now,
        )

        if overwrite:
            self._write_yaml_list(self.active_file, [])
            self._write_yaml_list(self.closed_file, [])

        rows = self._read_yaml_list(self.active_file)
        rows.extend([row.to_dict() for row in generated])
        self._write_yaml_list(self.active_file, rows)

        self._log_event(
            "TEST_DATA_GENERATED_LARGE",
            {
                "count": len(generated),
                "days": days,
                "slots_per_day": slots_per_day,
                "resources": 30,
                "weekday_only": True,
                "business_hours": "08:00-19:00",
                "overwrite": overwrite,
            },
            effective_now,
        )
        return generated

    def seed_specific_resource_test_data(
        self,
        resource: str,
        now: datetime | None = None,
        overwrite_resource: bool = True,
    ) -> list[ReservationRecord]:
        effective_now = now or datetime.now()
        weekdays = _collect_weekdays(effective_now.date(), effective_now.date() + timedelta(days=30))
        if len(weekdays) < 3:
            raise ValueError("Not enough weekdays available in the next 30 days window.")

        generated: list[ReservationRecord] = []
        slots = [(9, 0), (11, 0), (15, 0)]
        for index, (hour, minute) in enumerate(slots):
            day = weekdays[index]
            start = datetime(day.year, day.month, day.day, hour, minute)
            end = start + timedelta(hours=1)
            generated.append(
                ReservationRecord(
                    reservation_id=str(uuid4()),
                    resource=resource,
                    start=start,
                    end=end,
                    created_at=effective_now,
                    updated_at=effective_now,
                )
            )

        rows = self._read_yaml_list(self.active_file)
        if overwrite_resource:
            rows = [row for row in rows if str(row.get("resource")) != resource]

        rows.extend([row.to_dict() for row in generated])
        self._write_yaml_list(self.active_file, rows)

        self._log_event(
            "TEST_DATA_GENERATED_SPECIFIC_RESOURCE",
            {
                "resource": resource,
                "count": len(generated),
                "date_window_days": 30,
                "weekday_only": True,
                "business_hours": "08:00-19:00",
                "overwrite_resource": overwrite_resource,
            },
            effective_now,
        )
        return generated


def generate_test_reservations(start_date: date) -> list[ReservationRecord]:
    resources = [f"회의실{i}" for i in range(1, 11)] + [f"테스트단말기{i}" for i in range(1, 21)]
    business_days = _collect_business_days(start_date, start_date + timedelta(days=30))
    if not business_days:
        raise ValueError("No weekdays available in the next 30 days window.")

    rng = random.Random(f"test:{start_date.isoformat()}")
    records: list[ReservationRecord] = []
    now = datetime.now()
    for resource in resources:
        day = _pick_weighted_business_day(rng, business_days)
        start_hour = rng.randint(BUSINESS_START_HOUR, BUSINESS_END_HOUR - 2)
        start_minute = rng.choice([0, 10, 20, 30, 40, 50])
        start = datetime(day.year, day.month, day.day, start_hour, start_minute)
        max_duration = 60 - start_minute
        duration_minutes = rng.choice([value for value in [10, 20, 30, 40, 50, 60] if value <= max_duration])
        end = start + timedelta(minutes=duration_minutes)

        record = ReservationRecord(
            reservation_id=str(uuid4()),
            resource=resource,
            start=start,
            end=end,
            created_at=now,
            updated_at=now,
        )
        records.append(record)

    return records


def generate_large_test_reservations(
    start_date: date,
    days: int = 30,
    slots_per_day: int = 4,
    reference_now: datetime | None = None,
) -> list[ReservationRecord]:
    if days <= 0:
        raise ValueError("days must be greater than zero")
    if slots_per_day <= 0:
        raise ValueError("slots_per_day must be greater than zero")

    resources = [f"회의실{i}" for i in range(1, 11)] + [f"테스트단말기{i}" for i in range(1, 21)]
    business_days = _collect_business_days(start_date, start_date + timedelta(days=days))
    if not business_days:
        raise ValueError("No weekdays available in the given window.")

    if slots_per_day > 5:
        raise ValueError("slots_per_day is too large for business-hour constraints")

    rng = random.Random(f"large:{start_date.isoformat()}:{days}:{slots_per_day}")
    weighted_resources = _build_weighted_resource_pool(resources)

    records: list[ReservationRecord] = []
    now = datetime.now()
    effective_now = reference_now or datetime.now()
    preferred_minutes = (effective_now.hour * 60) + (effective_now.minute // 10) * 10

    total_business_days = len(business_days)
    for day_index, day in enumerate(business_days):
        day_density = _near_term_density_ratio(day_index, total_business_days)
        slot_factor = max(0.75, slots_per_day / 4)

        daily_min = max(20, int(36 * day_density * slot_factor))
        daily_max = max(daily_min + 8, int(70 * day_density * slot_factor))
        daily_target = rng.randint(daily_min, daily_max)

        candidate_starts: list[datetime] = []
        candidate_weights: list[float] = []
        for hour in range(BUSINESS_START_HOUR, BUSINESS_END_HOUR):
            for minute in [0, 10, 20, 30, 40, 50]:
                start = datetime(day.year, day.month, day.day, hour, minute)
                if start >= datetime(day.year, day.month, day.day, BUSINESS_END_HOUR, 0):
                    continue

                minute_of_day = (hour * 60) + minute
                distance = abs(minute_of_day - preferred_minutes)
                time_weight = 1.2 / (1 + (distance / 120))
                if day == effective_now.date() and minute_of_day >= preferred_minutes:
                    time_weight *= 1.4
                candidate_starts.append(start)
                candidate_weights.append(time_weight)

        resource_usage: dict[str, list[tuple[datetime, datetime]]] = {resource: [] for resource in resources}
        start_usage: dict[str, int] = {}

        attempts = 0
        max_attempts = daily_target * 8
        while len([item for bucket in resource_usage.values() for item in bucket]) < daily_target and attempts < max_attempts:
            attempts += 1

            resource = _weighted_choice(rng, weighted_resources)

            adjusted_weights: list[float] = []
            for start, weight in zip(candidate_starts, candidate_weights):
                start_key = start.isoformat(timespec="minutes")
                repeated_penalty = 1 + (start_usage.get(start_key, 0) * 0.65)
                adjusted_weights.append(weight / repeated_penalty)

            start = _weighted_choice(rng, list(zip(candidate_starts, adjusted_weights)))
            max_duration = int((datetime(day.year, day.month, day.day, BUSINESS_END_HOUR, 0) - start).total_seconds() // 60)
            duration_candidates = [value for value in [10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120] if value <= max_duration]
            if not duration_candidates:
                continue
            duration_minutes = rng.choice(duration_candidates)
            end = start + timedelta(minutes=duration_minutes)

            overlaps = any(start < existing_end and end > existing_start for existing_start, existing_end in resource_usage[resource])
            if overlaps:
                continue

            resource_usage[resource].append((start, end))
            start_key = start.isoformat(timespec="minutes")
            start_usage[start_key] = start_usage.get(start_key, 0) + 1

            records.append(
                ReservationRecord(
                    reservation_id=str(uuid4()),
                    resource=resource,
                    start=start,
                    end=end,
                    created_at=now,
                    updated_at=now,
                )
            )

    return records


def _collect_weekdays(start_inclusive: date, end_exclusive: date) -> list[date]:
    cursor = start_inclusive
    weekdays: list[date] = []
    while cursor < end_exclusive:
        if cursor.weekday() < 5:
            weekdays.append(cursor)
        cursor += timedelta(days=1)
    return weekdays


def _collect_business_days(start_inclusive: date, end_exclusive: date) -> list[date]:
    cursor = start_inclusive
    business_days: list[date] = []
    while cursor < end_exclusive:
        if _is_business_day(cursor):
            business_days.append(cursor)
        cursor += timedelta(days=1)
    return business_days


def reserve_from_text(
    text: str,
    repository: ReservationYamlRepository,
    now: datetime | None = None,
) -> ReservationRecord:
    from .natural_language import parse_reservation_request

    parsed = parse_reservation_request(text)
    if not parsed.resource:
        raise ValueError("Could not determine resource from request text.")

    return repository.add_reservation(
        resource=parsed.resource,
        start=parsed.start,
        end=parsed.end,
        request_text=text,
        now=now,
    )


def reserve_with_conflict_avoidance(
    repository: ReservationYamlRepository,
    resource: str,
    start: datetime,
    end: datetime,
    now: datetime | None = None,
    allow_time_shift: bool = True,
    allow_other_resource: bool = True,
) -> ReservationAttemptResult:
    effective_now = now or datetime.now()

    try:
        created = repository.add_reservation(resource=resource, start=start, end=end, now=effective_now)
        return ReservationAttemptResult(strategy="requested", reservation=created)
    except ValueError as error:
        if "overlaps" not in str(error):
            raise

    duration = end - start
    if allow_time_shift:
        before_start = start - duration
        before_end = start
        if _is_within_business_hours(before_start, before_end) and before_start.date() == start.date():
            try:
                created_before = repository.add_reservation(
                    resource=resource,
                    start=before_start,
                    end=before_end,
                    now=effective_now,
                )
                return ReservationAttemptResult(strategy="time_shift_before", reservation=created_before)
            except ValueError:
                pass

        after_start = end
        after_end = end + duration
        if _is_within_business_hours(after_start, after_end) and after_start.date() == start.date():
            try:
                created_after = repository.add_reservation(
                    resource=resource,
                    start=after_start,
                    end=after_end,
                    now=effective_now,
                )
                return ReservationAttemptResult(strategy="time_shift_after", reservation=created_after)
            except ValueError:
                pass

    if allow_other_resource:
        for candidate_resource in _candidate_resources_for_same_time(repository, resource):
            try:
                created_alt = repository.add_reservation(
                    resource=candidate_resource,
                    start=start,
                    end=end,
                    now=effective_now,
                )
                return ReservationAttemptResult(strategy="other_resource_same_time", reservation=created_alt)
            except ValueError:
                continue

    raise ValueError("Could not reserve requested slot or find a conflict-avoidance alternative.")


def reserve_from_text_with_conflict_avoidance(
    text: str,
    repository: ReservationYamlRepository,
    now: datetime | None = None,
) -> ReservationAttemptResult:
    from .natural_language import parse_reservation_request

    parsed = parse_reservation_request(text)
    if not parsed.resource:
        raise ValueError("Could not determine resource from request text.")

    return reserve_with_conflict_avoidance(
        repository=repository,
        resource=parsed.resource,
        start=parsed.start,
        end=parsed.end,
        now=now,
    )


def suggest_reservation_options(
    repository: ReservationYamlRepository,
    resource: str,
    start: datetime,
    end: datetime,
    now: datetime | None = None,
    limit: int = 3,
) -> list[ReservationOption]:
    if limit <= 0:
        raise ValueError("limit must be greater than zero")

    normalized_resource = _normalize_resource_name(resource)
    effective_now = now or datetime.now()
    start, end = _normalize_reservation_range(start, end)
    start, end = _apply_same_day_business_end_cap(start, end, effective_now)
    _validate_bookable_request(start, end, effective_now)

    repository.close_expired(effective_now)

    options: list[ReservationOption] = []
    seen: set[tuple[str, str, str]] = set()

    def push_option(strategy: str, target_resource: str, option_start: datetime, option_end: datetime) -> None:
        if len(options) >= limit:
            return
        try:
            _validate_bookable_request(option_start, option_end, effective_now)
        except ValueError:
            return

        key = (
            target_resource,
            option_start.isoformat(timespec="minutes"),
            option_end.isoformat(timespec="minutes"),
        )
        if key in seen:
            return
        seen.add(key)

        if _is_resource_available(repository, target_resource, option_start, option_end):
            options.append(
                ReservationOption(
                    strategy=strategy,
                    resource=target_resource,
                    start=option_start,
                    end=option_end,
                )
            )

    push_option("requested", normalized_resource, start, end)

    duration = end - start
    push_option("time_shift_before", normalized_resource, start - duration, start)
    push_option("time_shift_after", normalized_resource, end, end + duration)

    for candidate_resource in _candidate_resources_for_same_time(repository, normalized_resource):
        if len(options) >= limit:
            break
        push_option("other_resource_same_time", candidate_resource, start, end)

    return options[:limit]


def suggest_reservation_options_from_text(
    text: str,
    repository: ReservationYamlRepository,
    now: datetime | None = None,
    limit: int = 3,
) -> list[ReservationOption]:
    from .natural_language import parse_reservation_request

    parsed = parse_reservation_request(text)
    if not parsed.resource:
        raise ValueError("Could not determine resource from request text.")

    return suggest_reservation_options(
        repository=repository,
        resource=parsed.resource,
        start=parsed.start,
        end=parsed.end,
        now=now,
        limit=limit,
    )


def _is_within_business_hours(start: datetime, end: datetime) -> bool:
    if start.date() != end.date():
        return False
    return start.hour >= BUSINESS_START_HOUR and end.hour <= BUSINESS_END_HOUR and (end.hour > BUSINESS_START_HOUR or end.minute >= 0)


def _apply_same_day_business_end_cap(start: datetime, end: datetime, now: datetime) -> tuple[datetime, datetime]:
    if start.date() != now.date() or end.date() != now.date():
        return start, end

    cutoff = now.replace(hour=BUSINESS_END_HOUR, minute=0, second=0, microsecond=0)
    if end > cutoff:
        end = cutoff
    return start, end


def _normalize_reservation_range(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    normalized_start = _floor_to_ten_minutes(start)
    normalized_end = _ceil_to_ten_minutes(end)
    return normalized_start, normalized_end


def _floor_to_ten_minutes(value: datetime) -> datetime:
    return value.replace(minute=(value.minute // 10) * 10, second=0, microsecond=0)


def _ceil_to_ten_minutes(value: datetime) -> datetime:
    normalized = value.replace(second=0, microsecond=0)
    minute_remainder = normalized.minute % 10
    has_sub_minute = value.second > 0 or value.microsecond > 0
    if minute_remainder == 0 and not has_sub_minute:
        return normalized

    minutes_to_add = (10 - minute_remainder) % 10
    if minutes_to_add == 0:
        minutes_to_add = 10
    return normalized + timedelta(minutes=minutes_to_add)


def _candidate_resources_for_same_time(repository: ReservationYamlRepository, requested_resource: str) -> list[str]:
    prefix = _resource_prefix(requested_resource)
    if prefix == "회의실":
        return [f"회의실{i}" for i in range(1, 11) if f"회의실{i}" != requested_resource]
    if prefix == "테스트단말기":
        return [f"테스트단말기{i}" for i in range(1, 21) if f"테스트단말기{i}" != requested_resource]

    resources = {record.resource for record in repository.get_active_reservations()}
    resources.update(record.resource for record in repository.get_closed_reservations())
    return sorted(resource for resource in resources if resource != requested_resource and _resource_prefix(resource) == prefix)


def _is_resource_available(
    repository: ReservationYamlRepository,
    resource: str,
    start: datetime,
    end: datetime,
) -> bool:
    active = repository.get_active_reservations()
    same_resource = [row for row in active if row.resource == resource]
    return can_reserve(start, end, [Reservation(row.start, row.end) for row in same_resource])


def _resource_prefix(resource: str) -> str:
    index = len(resource)
    for offset, char in enumerate(resource):
        if char.isdigit():
            index = offset
            break
    return resource[:index]


def _normalize_resource_name(resource: str | None) -> str:
    if resource is None:
        raise ValueError("resource must not be None")

    normalized = resource.strip()
    if not normalized:
        raise ValueError("resource must not be empty")
    return normalized


def _build_weighted_resource_pool(resources: list[str]) -> list[tuple[str, int]]:
    high_demand_rooms = {"회의실1", "회의실2", "회의실3"}
    high_demand_devices = {"테스트단말기1", "테스트단말기2", "테스트단말기3", "테스트단말기4", "테스트단말기5"}

    weighted: list[tuple[str, int]] = []
    for resource in resources:
        if resource in high_demand_rooms:
            weight = 7
        elif resource in high_demand_devices:
            weight = 4
        elif resource.startswith("회의실"):
            weight = 1
        else:
            weight = 2
        weighted.append((resource, weight))
    return weighted


def _weighted_sample_without_replacement(
    rng: random.Random,
    weighted_resources: list[tuple[str, int]],
    count: int,
) -> list[str]:
    pool = weighted_resources[:]
    selected: list[str] = []

    target = max(0, min(count, len(pool)))
    for _ in range(target):
        total_weight = sum(weight for _, weight in pool)
        pick = rng.uniform(0, total_weight)
        cumulative = 0.0
        chosen_index = 0
        for index, (_, weight) in enumerate(pool):
            cumulative += weight
            if pick <= cumulative:
                chosen_index = index
                break

        resource, _ = pool.pop(chosen_index)
        selected.append(resource)

    return selected


def _weighted_choice[T](rng: random.Random, weighted_items: list[tuple[T, float]]) -> T:
    if not weighted_items:
        raise ValueError("weighted_items must not be empty")

    total_weight = sum(max(0.0, float(weight)) for _, weight in weighted_items)
    if total_weight <= 0:
        return weighted_items[rng.randrange(len(weighted_items))][0]

    pick = rng.uniform(0, total_weight)
    cumulative = 0.0
    for item, weight in weighted_items:
        cumulative += max(0.0, float(weight))
        if pick <= cumulative:
            return item
    return weighted_items[-1][0]


def _pick_weighted_business_day(rng: random.Random, business_days: list[date]) -> date:
    if len(business_days) == 1:
        return business_days[0]

    weighted_days = [(day, _near_term_density_ratio(index, len(business_days))) for index, day in enumerate(business_days)]
    total_weight = sum(weight for _, weight in weighted_days)
    pick = rng.uniform(0, total_weight)
    cumulative = 0.0
    for day, weight in weighted_days:
        cumulative += weight
        if pick <= cumulative:
            return day
    return weighted_days[-1][0]


def _near_term_density_ratio(index: int, total_count: int) -> float:
    if total_count <= 1:
        return 1.0

    progress = index / (total_count - 1)
    base = 1.45 - (0.65 * progress)
    return max(0.75, base)


def _validate_bookable_request(start: datetime, end: datetime, now: datetime) -> None:
    if start >= end:
        raise ValueError("Reservation start time must be earlier than end time.")
    if start < now:
        raise ValueError("Reservation start time cannot be in the past.")
    if start.date() != end.date():
        raise ValueError("Reservation must start and end on the same day.")

    window_end = now + timedelta(days=RESERVATION_WINDOW_DAYS)
    if start > window_end or end > window_end:
        raise ValueError("Reservation must be within 30 days from now.")
    if not _is_within_business_hours(start, end):
        raise ValueError("Reservation must be within business hours (08:00-19:00).")
    if not _is_business_day(start.date()):
        raise ValueError("Reservation is not allowed on weekends or holidays.")


def _is_business_day(target_date: date) -> bool:
    return target_date.weekday() < 5 and not _is_korean_holiday(target_date)


def _is_korean_holiday(target_date: date) -> bool:
    year = target_date.year
    if year not in _KR_HOLIDAY_CACHE:
        holiday_map = pyholidays.country_holidays("KR", years=[year])
        _KR_HOLIDAY_CACHE[year] = set(holiday_map.keys())
    return target_date in _KR_HOLIDAY_CACHE[year]

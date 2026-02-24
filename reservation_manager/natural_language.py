import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from .booking import Reservation, can_reserve

_DATE_RE = re.compile(r"(?P<date>\d{4}[/-]\d{1,2}[/-]\d{1,2})")
_TIME_RE = re.compile(r"(?<!\d)(?P<time>(?:[01]?\d|2[0-3]):[0-5]\d)(?!\d)")
_RELATIVE_DATE_RE = re.compile(r"(?P<day>오늘|내일)")
_MERIDIEM_TIME_RE = re.compile(r"(?:(?P<ampm>오전|오후)\s*)?(?P<hour>\d{1,2})\s*시(?:\s*(?P<minute>\d{1,2})\s*분)?")
_DURATION_RE = re.compile(r"(?P<hours>\d+)\s*시간(?:\s*(?P<minutes>\d+)\s*분)?")
_RESOURCE_CLEAN_RE = re.compile(r"(예약(해줘|해주세요)?|잡아줘|로|을|를|에|좀|해줘)")


@dataclass(frozen=True)
class ParsedReservationRequest:
    resource: str | None
    start: datetime
    end: datetime
    raw_text: str


def _parse_date(date_text: str) -> datetime.date:
    normalized = date_text.replace("/", "-")
    return datetime.strptime(normalized, "%Y-%m-%d").date()


def _extract_resource(text: str, date_text: str, start_time: str, end_time: str) -> str | None:
    candidate = text
    candidate = candidate.replace(date_text, " ")
    candidate = candidate.replace(start_time, " ")
    candidate = candidate.replace(end_time, " ")
    candidate = re.sub(r"[~\-]", " ", candidate)
    candidate = re.sub(r"부터|까지", " ", candidate)
    candidate = _RESOURCE_CLEAN_RE.sub(" ", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip()
    return candidate or None


def _extract_resource_from_fragments(text: str, fragments: list[str]) -> str | None:
    candidate = text
    for fragment in fragments:
        if fragment:
            candidate = candidate.replace(fragment, " ")
    candidate = re.sub(r"[~\-]", " ", candidate)
    candidate = re.sub(r"부터|까지", " ", candidate)
    candidate = _RESOURCE_CLEAN_RE.sub(" ", candidate)
    candidate = re.sub(r"\s+", " ", candidate).strip()
    return candidate or None


def parse_reservation_request(text: str, reference_datetime: datetime | None = None) -> ParsedReservationRequest:
    if not text or not text.strip():
        raise ValueError("text must not be empty")

    date_match = _DATE_RE.search(text)
    if date_match:
        time_matches = _TIME_RE.findall(text)
        if len(time_matches) < 2:
            raise ValueError("Could not find start/end time in text. Expected format: HH:MM")

        date_text = date_match.group("date")
        start_time, end_time = time_matches[0], time_matches[1]

        date_part = _parse_date(date_text)
        start_dt = datetime.strptime(f"{date_part.isoformat()} {start_time}", "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(f"{date_part.isoformat()} {end_time}", "%Y-%m-%d %H:%M")

        if start_dt >= end_dt:
            raise ValueError("start time must be earlier than end time")

        resource = _extract_resource(text, date_text, start_time, end_time)
        return ParsedReservationRequest(resource=resource, start=start_dt, end=end_dt, raw_text=text)

    relative_date_match = _RELATIVE_DATE_RE.search(text)
    relative_time_match = _MERIDIEM_TIME_RE.search(text)
    duration_match = _DURATION_RE.search(text)
    if not (relative_date_match and relative_time_match and duration_match):
        raise ValueError("Could not find a date in text. Expected format: YYYY-MM-DD or relative form like '오늘 오후 5시 1시간'")

    now = reference_datetime or datetime.now()
    day_keyword = relative_date_match.group("day")
    base_date = now.date() + timedelta(days=1 if day_keyword == "내일" else 0)

    hour = int(relative_time_match.group("hour"))
    minute_group = relative_time_match.group("minute")
    minute = int(minute_group) if minute_group else 0
    ampm = relative_time_match.group("ampm")

    if ampm == "오후" and hour < 12:
        hour += 12
    if ampm == "오전" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        raise ValueError("Invalid hour/minute in relative time expression")

    duration_hours = int(duration_match.group("hours"))
    duration_minutes_group = duration_match.group("minutes")
    duration_minutes = int(duration_minutes_group) if duration_minutes_group else 0
    duration_delta = timedelta(hours=duration_hours, minutes=duration_minutes)
    if duration_delta <= timedelta(0):
        raise ValueError("duration must be greater than zero")

    start_dt = datetime(base_date.year, base_date.month, base_date.day, hour, minute)
    end_dt = start_dt + duration_delta

    resource = _extract_resource_from_fragments(
        text,
        [
            relative_date_match.group(0),
            relative_time_match.group(0),
            duration_match.group(0),
            "오전",
            "오후",
        ],
    )

    return ParsedReservationRequest(resource=resource, start=start_dt, end=end_dt, raw_text=text)


def can_reserve_from_text(text: str, existing_reservations: Iterable[Reservation]) -> bool:
    parsed = parse_reservation_request(text)
    return can_reserve(parsed.start, parsed.end, existing_reservations)

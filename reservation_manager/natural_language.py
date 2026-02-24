import re
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from .booking import Reservation, can_reserve

_DATE_RE = re.compile(r"(?P<date>\d{4}[/-]\d{1,2}[/-]\d{1,2})")
_TIME_RE = re.compile(r"(?<!\d)(?P<time>(?:[01]?\d|2[0-3]):[0-5]\d)(?!\d)")
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


def parse_reservation_request(text: str) -> ParsedReservationRequest:
    if not text or not text.strip():
        raise ValueError("text must not be empty")

    date_match = _DATE_RE.search(text)
    if not date_match:
        raise ValueError("Could not find a date in text. Expected format: YYYY-MM-DD")

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


def can_reserve_from_text(text: str, existing_reservations: Iterable[Reservation]) -> bool:
    parsed = parse_reservation_request(text)
    return can_reserve(parsed.start, parsed.end, existing_reservations)

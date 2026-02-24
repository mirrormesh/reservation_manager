from dataclasses import dataclass
from datetime import datetime
from typing import Iterable


@dataclass(frozen=True)
class Reservation:
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError("Reservation start time must be earlier than end time.")


def has_time_overlap(new_start: datetime, new_end: datetime, exist_start: datetime, exist_end: datetime) -> bool:
    """Return True when two time intervals overlap by even one minute.

    Intervals are treated as half-open ranges: [start, end)
    so touching boundaries (e.g. 10:00-11:00 and 11:00-12:00) do not overlap.
    """
    if new_start >= new_end:
        raise ValueError("new_start must be earlier than new_end.")
    if exist_start >= exist_end:
        raise ValueError("exist_start must be earlier than exist_end.")

    return new_start < exist_end and new_end > exist_start


def can_reserve(new_start: datetime, new_end: datetime, existing_reservations: Iterable[Reservation]) -> bool:
    """Return True if the requested interval does not overlap any existing reservation."""
    if new_start >= new_end:
        raise ValueError("new_start must be earlier than new_end.")

    for reservation in existing_reservations:
        if has_time_overlap(new_start, new_end, reservation.start, reservation.end):
            return False
    return True

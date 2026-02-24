from __future__ import annotations

from datetime import datetime
from pathlib import Path
import traceback

from reservation_manager import ReservationYamlRepository, reserve_with_conflict_avoidance


def main() -> int:
    print("[INFO] Reservation Manager Windows Quick Check")
    print("[INFO] Generating and validating test data...")

    repo = ReservationYamlRepository("data")
    now = datetime(2026, 2, 24, 10, 0)

    generated = repo.seed_large_test_data(now=now, days=30, slots_per_day=4, overwrite=True)
    print(f"[OK] Large test data generated: {len(generated)} records")

    result = reserve_with_conflict_avoidance(
        repository=repo,
        resource="회의실1",
        start=datetime(2026, 2, 24, 13, 0),
        end=datetime(2026, 2, 24, 14, 0),
        now=now,
        allow_time_shift=True,
        allow_other_resource=True,
    )

    active_count = len(repo.get_active_reservations())
    closed_count = len(repo.get_closed_reservations())

    print(f"[OK] Conflict avoidance strategy: {result.strategy}")
    print(
        "[OK] Reserved slot: "
        f"{result.reservation.resource},"
        f"{result.reservation.start.isoformat(timespec='minutes')}"
        f"~{result.reservation.end.isoformat(timespec='minutes')}"
    )
    print(f"[OK] Active reservations: {active_count}")
    print(f"[OK] Closed reservations: {closed_count}")
    print(f"[OK] Active YAML: {Path('data/active_reservations.yaml').resolve()}")
    print(f"[OK] Closed YAML: {Path('data/closed_reservations.yaml').resolve()}")
    print(f"[OK] Event Log YAML: {Path('data/reservation_events.yaml').resolve()}")

    print("[DONE] Quick check completed successfully.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("[ERROR] Quick check failed.")
        traceback.print_exc()
        raise SystemExit(1)

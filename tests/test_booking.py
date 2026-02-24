import unittest
from datetime import datetime

from reservation_manager import Reservation, can_reserve, has_time_overlap


class TestTimeOverlap(unittest.TestCase):
    def setUp(self) -> None:
        self.exist_start = datetime(2026, 2, 24, 10, 0)
        self.exist_end = datetime(2026, 2, 24, 11, 0)

    def test_non_overlapping_before_passes(self) -> None:
        self.assertFalse(
            has_time_overlap(
                datetime(2026, 2, 24, 9, 0),
                datetime(2026, 2, 24, 9, 59),
                self.exist_start,
                self.exist_end,
            )
        )

    def test_non_overlapping_after_passes(self) -> None:
        self.assertFalse(
            has_time_overlap(
                datetime(2026, 2, 24, 11, 1),
                datetime(2026, 2, 24, 12, 0),
                self.exist_start,
                self.exist_end,
            )
        )

    def test_exactly_touching_boundary_passes(self) -> None:
        self.assertFalse(
            has_time_overlap(
                datetime(2026, 2, 24, 11, 0),
                datetime(2026, 2, 24, 12, 0),
                self.exist_start,
                self.exist_end,
            )
        )

    def test_partially_overlapping_fails(self) -> None:
        self.assertTrue(
            has_time_overlap(
                datetime(2026, 2, 24, 10, 30),
                datetime(2026, 2, 24, 11, 30),
                self.exist_start,
                self.exist_end,
            )
        )

    def test_fully_contained_fails(self) -> None:
        self.assertTrue(
            has_time_overlap(
                datetime(2026, 2, 24, 10, 15),
                datetime(2026, 2, 24, 10, 45),
                self.exist_start,
                self.exist_end,
            )
        )


class TestCanReserve(unittest.TestCase):
    def test_can_reserve_returns_false_when_any_overlap(self) -> None:
        existing = [
            Reservation(datetime(2026, 2, 24, 9, 0), datetime(2026, 2, 24, 10, 0)),
            Reservation(datetime(2026, 2, 24, 10, 30), datetime(2026, 2, 24, 11, 30)),
        ]
        self.assertFalse(
            can_reserve(
                datetime(2026, 2, 24, 11, 0),
                datetime(2026, 2, 24, 12, 0),
                existing,
            )
        )

    def test_can_reserve_returns_true_when_no_overlap(self) -> None:
        existing = [
            Reservation(datetime(2026, 2, 24, 9, 0), datetime(2026, 2, 24, 10, 0)),
            Reservation(datetime(2026, 2, 24, 10, 30), datetime(2026, 2, 24, 11, 30)),
        ]
        self.assertTrue(
            can_reserve(
                datetime(2026, 2, 24, 12, 0),
                datetime(2026, 2, 24, 13, 0),
                existing,
            )
        )


if __name__ == "__main__":
    unittest.main()

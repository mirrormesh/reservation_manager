import unittest
from datetime import datetime

from reservation_manager import Reservation
from reservation_manager.natural_language import can_reserve_from_text, parse_reservation_request


class TestNaturalLanguageParsing(unittest.TestCase):
    def test_parse_with_tilde_format(self) -> None:
        parsed = parse_reservation_request("회의실A 2026-02-24 10:00~11:00 예약")

        self.assertEqual(parsed.resource, "회의실A")
        self.assertEqual(parsed.start, datetime(2026, 2, 24, 10, 0))
        self.assertEqual(parsed.end, datetime(2026, 2, 24, 11, 0))

    def test_parse_with_korean_connector(self) -> None:
        parsed = parse_reservation_request("테스트 단말기 2026/02/24 14:30부터 15:30까지 예약해줘")

        self.assertEqual(parsed.resource, "테스트 단말기")
        self.assertEqual(parsed.start, datetime(2026, 2, 24, 14, 30))
        self.assertEqual(parsed.end, datetime(2026, 2, 24, 15, 30))

    def test_parse_raises_when_missing_date(self) -> None:
        with self.assertRaises(ValueError):
            parse_reservation_request("회의실A 10:00~11:00 예약")


class TestNaturalLanguageReservation(unittest.TestCase):
    def test_can_reserve_from_text_true_when_boundary_touching(self) -> None:
        existing = [Reservation(datetime(2026, 2, 24, 10, 0), datetime(2026, 2, 24, 11, 0))]
        self.assertTrue(can_reserve_from_text("회의실A 2026-02-24 11:00~12:00 예약", existing))

    def test_can_reserve_from_text_false_when_overlapping(self) -> None:
        existing = [Reservation(datetime(2026, 2, 24, 10, 0), datetime(2026, 2, 24, 11, 0))]
        self.assertFalse(can_reserve_from_text("회의실A 2026-02-24 10:30~11:30 예약", existing))


if __name__ == "__main__":
    unittest.main()

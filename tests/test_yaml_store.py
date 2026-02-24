import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from reservation_manager import (
    ReservationYamlRepository,
    generate_large_test_reservations,
    generate_test_reservations,
    reserve_from_text,
    reserve_with_conflict_avoidance,
)
from reservation_manager.yaml_store import OWNER_EXTERNAL, OWNER_SELF


class TestGenerateTestReservations(unittest.TestCase):
    def test_generates_30_resources_within_constraints(self) -> None:
        records = generate_test_reservations(date(2026, 2, 24))

        self.assertEqual(len(records), 30)

        resources = {record.resource for record in records}
        expected_rooms = {f"회의실{i}" for i in range(1, 11)}
        expected_devices = {f"테스트단말기{i}" for i in range(1, 21)}
        self.assertEqual(resources, expected_rooms | expected_devices)

        for record in records:
            self.assertGreaterEqual(record.start.hour, 8)
            self.assertLessEqual(record.end.hour, 19)
            duration_minutes = int((record.end - record.start).total_seconds() // 60)
            self.assertGreaterEqual(duration_minutes, 10)
            self.assertLessEqual(duration_minutes, 60)
            self.assertEqual(record.start.minute % 10, 0)
            self.assertEqual(record.end.minute % 10, 0)
            self.assertLess(record.start.date(), date(2026, 3, 26))
            self.assertGreaterEqual(record.start.date(), date(2026, 2, 24))
            self.assertLess(record.start.weekday(), 5)

    def test_generate_large_test_reservations_with_constraints(self) -> None:
        records = generate_large_test_reservations(date(2026, 2, 24), days=7, slots_per_day=3)

        self.assertGreater(len(records), 30)
        for record in records:
            self.assertLess(record.start.weekday(), 5)
            self.assertGreaterEqual(record.start.hour, 8)
            self.assertLessEqual(record.end.hour, 19)
            self.assertEqual(record.start.minute % 10, 0)
            self.assertEqual(record.end.minute % 10, 0)

    def test_generate_large_test_reservations_raises_on_invalid_params(self) -> None:
        with self.assertRaises(ValueError):
            generate_large_test_reservations(date(2026, 2, 24), days=0, slots_per_day=3)

        with self.assertRaises(ValueError):
            generate_large_test_reservations(date(2026, 2, 24), days=30, slots_per_day=0)

        with self.assertRaises(ValueError):
            generate_large_test_reservations(date(2026, 2, 24), days=30, slots_per_day=6)


class TestReservationYamlRepository(unittest.TestCase):
    def test_auto_close_moves_expired_to_closed_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            repo.add_reservation(
                "회의실1",
                datetime(2026, 2, 24, 10, 0),
                datetime(2026, 2, 24, 11, 0),
                now=datetime(2026, 2, 24, 9, 0),
            )

            moved = repo.close_expired(datetime(2026, 2, 24, 11, 1))

            self.assertEqual(moved, 1)
            self.assertEqual(len(repo.get_active_reservations()), 0)
            self.assertEqual(len(repo.get_closed_reservations()), 1)

    def test_logs_create_update_close_events(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            created = repo.add_reservation(
                "회의실2",
                datetime(2026, 2, 24, 13, 0),
                datetime(2026, 2, 24, 14, 0),
                now=datetime(2026, 2, 24, 12, 0),
            )
            repo.update_reservation(
                created.reservation_id,
                start=datetime(2026, 2, 24, 14, 0),
                end=datetime(2026, 2, 24, 15, 0),
                now=datetime(2026, 2, 24, 12, 30),
            )
            repo.close_expired(datetime(2026, 2, 24, 15, 1))

            log_path = Path(temp_dir) / "data" / "reservation_events.yaml"
            contents = log_path.read_text(encoding="utf-8")
            self.assertIn("RESERVATION_CREATED", contents)
            self.assertIn("RESERVATION_UPDATED", contents)
            self.assertIn("RESERVATION_CLOSED", contents)

    def test_seed_test_data_writes_active_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            repo.seed_test_data(now=datetime(2026, 2, 24, 9, 0), overwrite=True)

            active = repo.get_active_reservations()
            closed = repo.get_closed_reservations()

            self.assertEqual(len(active), 30)
            self.assertEqual(len(closed), 0)

    def test_seed_test_data_marks_records_as_external(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            repo.seed_test_data(now=datetime(2026, 2, 24, 9, 0), overwrite=True)

            active = repo.get_active_reservations()
            self.assertGreater(len(active), 0)
            self.assertTrue(all(record.owner == OWNER_EXTERNAL for record in active))

    def test_add_reservation_defaults_to_self_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            created = repo.add_reservation(
                "회의실1",
                datetime(2026, 2, 24, 10, 0),
                datetime(2026, 2, 24, 11, 0),
                now=datetime(2026, 2, 24, 9, 0),
            )

            self.assertEqual(created.owner, OWNER_SELF)

    def test_delete_reservation_removes_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            created = repo.add_reservation(
                "회의실2",
                datetime(2026, 2, 24, 15, 0),
                datetime(2026, 2, 24, 16, 0),
                now=datetime(2026, 2, 24, 9, 0),
            )

            deleted = repo.delete_reservation(created.reservation_id, now=datetime(2026, 2, 24, 9, 30))
            self.assertEqual(deleted.reservation_id, created.reservation_id)
            self.assertEqual(len(repo.get_active_reservations()), 0)

    def test_add_reservation_requires_resolution_for_self_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            repo.add_reservation(
                "회의실1",
                datetime(2026, 2, 24, 10, 0),
                datetime(2026, 2, 24, 11, 0),
                now=datetime(2026, 2, 24, 9, 0),
            )

            with self.assertRaises(ValueError):
                repo.add_reservation(
                    "회의실1",
                    datetime(2026, 2, 24, 10, 30),
                    datetime(2026, 2, 24, 12, 0),
                    now=datetime(2026, 2, 24, 9, 30),
                )

    def test_add_reservation_does_not_merge_other_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            repo.add_reservation(
                "회의실1",
                datetime(2026, 2, 24, 10, 0),
                datetime(2026, 2, 24, 11, 0),
                now=datetime(2026, 2, 24, 9, 0),
                owner=OWNER_EXTERNAL,
            )

            with self.assertRaises(ValueError):
                repo.add_reservation(
                    "회의실1",
                    datetime(2026, 2, 24, 10, 30),
                    datetime(2026, 2, 24, 11, 30),
                    now=datetime(2026, 2, 24, 9, 30),
                )

    def test_find_self_owned_overlaps_returns_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            now = datetime(2026, 2, 24, 9, 0)
            repo.add_reservation("회의실1", datetime(2026, 2, 25, 10, 0), datetime(2026, 2, 25, 11, 0), now=now)

            overlaps = repo.find_self_owned_overlaps(
                "회의실1",
                datetime(2026, 2, 25, 10, 30),
                datetime(2026, 2, 25, 11, 30),
                now=now,
            )

            self.assertEqual(len(overlaps), 1)
            self.assertEqual(overlaps[0].resource, "회의실1")

    def test_merge_self_owned_reservations_combines_ranges(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            now = datetime(2026, 2, 24, 9, 0)
            first = repo.add_reservation("회의실1", datetime(2026, 2, 25, 9, 0), datetime(2026, 2, 25, 10, 0), now=now)
            second = repo.add_reservation("회의실1", datetime(2026, 2, 25, 10, 0), datetime(2026, 2, 25, 10, 30), now=now)

            merged = repo.merge_self_owned_reservations(
                "회의실1",
                datetime(2026, 2, 25, 9, 30),
                datetime(2026, 2, 25, 11, 0),
                [first.reservation_id, second.reservation_id],
                now=now,
            )

            self.assertEqual(merged.start, datetime(2026, 2, 25, 9, 0))
            self.assertEqual(merged.end, datetime(2026, 2, 25, 11, 0))
            self.assertEqual(merged.change_source, "merged")
            self.assertEqual(len(repo.get_active_reservations()), 1)

    def test_replace_self_owned_reservations_creates_new_range(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            now = datetime(2026, 2, 24, 9, 0)
            existing = repo.add_reservation("회의실1", datetime(2026, 2, 25, 9, 0), datetime(2026, 2, 25, 10, 0), now=now)

            replaced = repo.replace_self_owned_reservations(
                "회의실1",
                datetime(2026, 2, 25, 13, 0),
                datetime(2026, 2, 25, 14, 0),
                [existing.reservation_id],
                now=now,
            )

            self.assertEqual(replaced.start, datetime(2026, 2, 25, 13, 0))
            self.assertEqual(replaced.end, datetime(2026, 2, 25, 14, 0))
            self.assertEqual(replaced.change_source, "replaced")
            self.assertEqual(len(repo.get_active_reservations()), 1)

    def test_reserve_from_text_creates_yaml_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            record = reserve_from_text(
                "회의실A 2026-02-24 10:00~11:00 예약",
                repo,
                now=datetime(2026, 2, 24, 8, 0),
            )

            self.assertEqual(record.resource, "회의실A")
            self.assertEqual(len(repo.get_active_reservations()), 1)

    def test_seed_specific_resource_test_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            generated = repo.seed_specific_resource_test_data(
                "테스트단말기5",
                now=datetime(2026, 2, 24, 9, 0),
                overwrite_resource=True,
            )

            self.assertEqual(len(generated), 3)
            for record in generated:
                self.assertEqual(record.resource, "테스트단말기5")
                self.assertLess(record.start.weekday(), 5)
                self.assertGreaterEqual(record.start.hour, 8)
                self.assertLessEqual(record.end.hour, 19)

    def test_seed_large_test_data_generates_many_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            generated = repo.seed_large_test_data(
                now=datetime(2026, 2, 24, 9, 0),
                days=7,
                slots_per_day=3,
                overwrite=True,
            )

            self.assertGreater(len(generated), 100)
            self.assertEqual(len(repo.get_active_reservations()), len(generated))

    def test_conflict_avoidance_time_shift_after(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            now = datetime(2026, 2, 24, 9, 0)
            repo.add_reservation(
                "회의실1",
                datetime(2026, 2, 24, 10, 0),
                datetime(2026, 2, 24, 11, 0),
                now=now,
                owner=OWNER_EXTERNAL,
            )

            result = reserve_with_conflict_avoidance(
                repo,
                resource="회의실1",
                start=datetime(2026, 2, 24, 10, 30),
                end=datetime(2026, 2, 24, 11, 30),
                now=now,
            )

            self.assertEqual(result.strategy, "time_shift_after")
            self.assertEqual(result.reservation.start, datetime(2026, 2, 24, 11, 30))
            self.assertEqual(result.reservation.end, datetime(2026, 2, 24, 12, 30))

    def test_conflict_avoidance_other_resource_same_time(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            now = datetime(2026, 2, 24, 9, 0)
            repo.add_reservation(
                "회의실1",
                datetime(2026, 2, 24, 10, 0),
                datetime(2026, 2, 24, 11, 0),
                now=now,
                owner=OWNER_EXTERNAL,
            )

            result = reserve_with_conflict_avoidance(
                repo,
                resource="회의실1",
                start=datetime(2026, 2, 24, 10, 30),
                end=datetime(2026, 2, 24, 11, 30),
                now=now,
                allow_time_shift=False,
                allow_other_resource=True,
            )

            self.assertEqual(result.strategy, "other_resource_same_time")
            self.assertNotEqual(result.reservation.resource, "회의실1")
            self.assertEqual(result.reservation.start, datetime(2026, 2, 24, 10, 30))
            self.assertEqual(result.reservation.end, datetime(2026, 2, 24, 11, 30))

    def test_add_reservation_raises_on_empty_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            with self.assertRaises(ValueError):
                repo.add_reservation(
                    "   ",
                    datetime(2026, 2, 24, 10, 0),
                    datetime(2026, 2, 24, 11, 0),
                    now=datetime(2026, 2, 24, 9, 0),
                )

    def test_add_reservation_raises_on_past_start_time(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            with self.assertRaises(ValueError):
                repo.add_reservation(
                    "회의실1",
                    datetime(2026, 2, 24, 8, 0),
                    datetime(2026, 2, 24, 9, 0),
                    now=datetime(2026, 2, 24, 9, 30),
                )

    def test_add_reservation_caps_same_day_end_at_19(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            now = datetime(2026, 2, 24, 9, 0)

            created = repo.add_reservation(
                "회의실1",
                datetime(2026, 2, 24, 18, 20),
                datetime(2026, 2, 24, 20, 0),
                now=now,
            )

            self.assertEqual(created.start, datetime(2026, 2, 24, 18, 20))
            self.assertEqual(created.end, datetime(2026, 2, 24, 19, 0))

    def test_add_reservation_rounds_to_ten_minute_increment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = ReservationYamlRepository(Path(temp_dir) / "data")
            created = repo.add_reservation(
                "회의실1",
                datetime(2026, 2, 24, 10, 7),
                datetime(2026, 2, 24, 11, 1),
                now=datetime(2026, 2, 24, 9, 0),
            )

            self.assertEqual(created.start, datetime(2026, 2, 24, 10, 0))
            self.assertEqual(created.end, datetime(2026, 2, 24, 11, 10))

    def test_corrupted_yaml_is_recovered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            repo = ReservationYamlRepository(data_dir)
            active_path = data_dir / "active_reservations.yaml"
            active_path.write_text("this: [is: invalid", encoding="utf-8")

            active = repo.get_active_reservations()

            self.assertEqual(active, [])
            recovered_text = active_path.read_text(encoding="utf-8")
            self.assertIn("[]", recovered_text)


if __name__ == "__main__":
    unittest.main()

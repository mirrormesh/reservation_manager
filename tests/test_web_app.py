import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from reservation_manager import ReservationYamlRepository
from reservation_manager.web_app import create_app
from reservation_manager.yaml_store import OWNER_EXTERNAL


class TestWebApp(unittest.TestCase):
    def test_schedule_groups_and_sorts_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            repo = ReservationYamlRepository(data_dir)
            now = datetime(2026, 2, 24, 9, 0)
            repo.add_reservation("회의실1", datetime(2026, 2, 25, 10, 0), datetime(2026, 2, 25, 11, 0), now=now)
            repo.add_reservation("회의실1", datetime(2026, 2, 26, 10, 0), datetime(2026, 2, 26, 11, 0), now=now)
            repo.add_reservation("회의실2", datetime(2026, 2, 25, 10, 0), datetime(2026, 2, 25, 11, 0), now=now)

            app = create_app(data_dir)
            client = app.test_client()
            response = client.get("/api/schedule?period=month")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertIsNotNone(payload)
            self.assertIn("rooms", payload)
            self.assertIn("devices", payload)
            self.assertEqual(len(payload["rooms"]), 10)
            self.assertEqual(len(payload["devices"]), 20)

            meeting_room_rows = payload["rooms"]
            self.assertEqual(meeting_room_rows[0]["reservation_count"], 0)
            self.assertEqual(meeting_room_rows[-1]["resource"], "회의실1")
            self.assertEqual(meeting_room_rows[-1]["reservation_count"], 2)

    def test_day_schedule_moves_to_next_business_day_after_hours(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            ReservationYamlRepository(data_dir)

            late_evening = datetime(2026, 2, 24, 21, 30)
            app = create_app(data_dir, now_provider=lambda: late_evening)
            client = app.test_client()
            response = client.get("/api/schedule?period=day")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["window_start"], "2026-02-25T08:00")
            self.assertEqual(payload["window_end"], "2026-02-25T19:00")

    def test_reserve_option_and_commit_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            repo = ReservationYamlRepository(data_dir)

            app = create_app(data_dir, now_provider=lambda: datetime(2026, 2, 24, 9, 0))
            client = app.test_client()
            request_text_free = "회의실1 2026-02-27 10:00~11:00 예약"

            first_response = client.post("/api/reserve/options", json={"text": request_text_free})
            self.assertEqual(first_response.status_code, 200)
            first_payload = first_response.get_json()
            self.assertTrue(first_payload["ok"])
            self.assertTrue(first_payload.get("auto_reserved"))
            self.assertEqual(first_payload["reservation"]["resource"], "회의실1")

            active = repo.get_active_reservations()
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0].resource, "회의실1")

            conflict_text = "회의실1 2026-02-26 10:00~11:00 예약"
            repo.add_reservation(
                "회의실1",
                datetime(2026, 2, 26, 10, 0),
                datetime(2026, 2, 26, 11, 0),
                now=datetime(2026, 2, 24, 9, 0),
                owner=OWNER_EXTERNAL,
            )

            # Second attempt should provide conflict-avoidance options.
            second_response = client.post("/api/reserve/options", json={"text": conflict_text})
            self.assertEqual(second_response.status_code, 200)
            second_payload = second_response.get_json()
            self.assertTrue(second_payload["ok"])
            self.assertIn("options", second_payload)
            self.assertGreater(len(second_payload["options"]), 0)

            selected = second_payload["options"][0]
            commit_response = client.post(
                "/api/reserve/commit",
                json={
                    "text": conflict_text,
                    "option": selected,
                },
            )

            self.assertEqual(commit_response.status_code, 200)
            commit_payload = commit_response.get_json()
            self.assertTrue(commit_payload["ok"])
            self.assertEqual(commit_payload["reservation"]["resource"], selected["resource"])

    def test_reserve_options_rejects_far_future_date(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            ReservationYamlRepository(data_dir)

            app = create_app(data_dir)
            client = app.test_client()
            response = client.post("/api/reserve/options", json={"text": "회의실1 2099-02-24 10:00~11:00 예약"})

            self.assertEqual(response.status_code, 400)
            payload = response.get_json()
            self.assertFalse(payload["ok"])

    def test_options_other_resource_stays_same_group(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            repo = ReservationYamlRepository(data_dir)
            base_day = datetime.now() + timedelta(days=1)
            now = base_day.replace(hour=9, minute=0, second=0, microsecond=0)
            start = base_day.replace(hour=10, minute=0, second=0, microsecond=0)
            end = base_day.replace(hour=11, minute=0, second=0, microsecond=0)

            repo.add_reservation("회의실1", start, end, now=now, owner=OWNER_EXTERNAL)

            app = create_app(data_dir)
            client = app.test_client()
            text = f"회의실1 {start.strftime('%Y-%m-%d')} 10:00~11:00 예약"
            response = client.post("/api/reserve/options", json={"text": text})

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            other_group_options = [
                option
                for option in payload["options"]
                if option["strategy"] == "other_resource_same_time"
            ]
            for option in other_group_options:
                self.assertTrue(option["resource"].startswith("회의실"))

    def test_my_reservations_endpoints_allow_only_owned_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            repo = ReservationYamlRepository(data_dir)
            now = datetime(2026, 2, 24, 9, 0)
            owned = repo.add_reservation(
                "회의실1",
                datetime(2026, 2, 25, 10, 0),
                datetime(2026, 2, 25, 11, 0),
                now=now,
            )
            other = repo.add_reservation(
                "회의실2",
                datetime(2026, 2, 25, 12, 0),
                datetime(2026, 2, 25, 13, 0),
                now=now,
                owner=OWNER_EXTERNAL,
            )

            app = create_app(data_dir, now_provider=lambda: now)
            client = app.test_client()

            list_response = client.get("/api/my-reservations")
            self.assertEqual(list_response.status_code, 200)
            listed = list_response.get_json()
            self.assertEqual(len(listed["reservations"]), 1)
            self.assertEqual(listed["reservations"][0]["reservation_id"], owned.reservation_id)

            update_text = "회의실1 2026-02-25 15:00~16:00 예약"
            update_response = client.post(
                "/api/my-reservations/update",
                json={"reservation_id": owned.reservation_id, "text": update_text},
            )
            self.assertEqual(update_response.status_code, 200)
            update_payload = update_response.get_json()
            self.assertEqual(update_payload["reservation"]["start"], "2026-02-25T15:00")

            delete_response = client.post(
                "/api/my-reservations/delete",
                json={"reservation_id": owned.reservation_id},
            )
            self.assertEqual(delete_response.status_code, 200)

            final_list = client.get("/api/my-reservations")
            self.assertEqual(final_list.status_code, 200)
            self.assertEqual(len(final_list.get_json()["reservations"]), 0)

            forbidden_delete = client.post(
                "/api/my-reservations/delete",
                json={"reservation_id": other.reservation_id},
            )
            self.assertEqual(forbidden_delete.status_code, 403)

            forbidden_update = client.post(
                "/api/my-reservations/update",
                json={"reservation_id": other.reservation_id, "text": update_text},
            )
            self.assertEqual(forbidden_update.status_code, 403)

    def test_schedule_marks_owned_reservations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            repo = ReservationYamlRepository(data_dir)
            now = datetime(2026, 2, 24, 9, 0)
            repo.add_reservation(
                "회의실1",
                datetime(2026, 2, 24, 10, 0),
                datetime(2026, 2, 24, 11, 0),
                now=now,
                owner=OWNER_EXTERNAL,
            )
            repo.add_reservation(
                "회의실1",
                datetime(2026, 2, 24, 11, 0),
                datetime(2026, 2, 24, 12, 0),
                now=now,
            )

            app = create_app(data_dir, now_provider=lambda: now)
            client = app.test_client()
            response = client.get("/api/schedule?period=day")
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            room_rows = [row for row in payload["rooms"] if row["resource"] == "회의실1"]
            self.assertEqual(len(room_rows), 1)
            is_mine_values = {reservation["is_mine"] for reservation in room_rows[0]["reservations"]}
            self.assertIn(True, is_mine_values)
            self.assertIn(False, is_mine_values)

    def test_self_overlap_options_require_user_choice(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            repo = ReservationYamlRepository(data_dir)
            now = datetime(2026, 2, 24, 9, 0)
            existing = repo.add_reservation(
                "회의실1",
                datetime(2026, 2, 25, 10, 0),
                datetime(2026, 2, 25, 11, 0),
                now=now,
            )

            app = create_app(data_dir, now_provider=lambda: now)
            client = app.test_client()
            request_text = "회의실1 2026-02-25 10:30~11:30 예약"

            response = client.post("/api/reserve/options", json={"text": request_text})
            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            self.assertTrue(payload.get("self_overlap"))
            self.assertEqual(len(payload["options"]), 3)

            merge_option = next(option for option in payload["options"] if option["strategy"] == "merge_existing")
            self.assertIn(existing.reservation_id, merge_option["reservation_ids"])

            commit_response = client.post(
                "/api/reserve/commit",
                json={"text": request_text, "option": merge_option},
            )
            self.assertEqual(commit_response.status_code, 200)
            commit_payload = commit_response.get_json()
            self.assertTrue(commit_payload["ok"])
            self.assertEqual(commit_payload["strategy"], "merge_existing")
            self.assertEqual(commit_payload["reservation"]["start"], "2026-02-25T10:00")
            self.assertEqual(commit_payload["reservation"]["end"], "2026-02-25T11:30")


if __name__ == "__main__":
    unittest.main()

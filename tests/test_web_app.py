import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from reservation_manager import ReservationYamlRepository
from reservation_manager.web_app import create_app


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

    def test_reserve_option_and_commit_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir) / "data"
            ReservationYamlRepository(data_dir)

            app = create_app(data_dir)
            client = app.test_client()
            target_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            request_text = f"회의실1 {target_date} 10:00~11:00 예약"
            options_response = client.post("/api/reserve/options", json={"text": request_text})

            self.assertEqual(options_response.status_code, 200)
            options_payload = options_response.get_json()
            self.assertTrue(options_payload["ok"])
            self.assertLessEqual(len(options_payload["options"]), 3)
            self.assertGreaterEqual(len(options_payload["options"]), 1)

            selected = options_payload["options"][0]
            response = client.post(
                "/api/reserve/commit",
                json={
                    "text": request_text,
                    "option": selected,
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["reservation"]["resource"], selected["resource"])

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

            repo.add_reservation("회의실1", start, end, now=now)

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


if __name__ == "__main__":
    unittest.main()

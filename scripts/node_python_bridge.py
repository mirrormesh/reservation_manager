from __future__ import annotations

import json
from pathlib import Path
import sys
from urllib.parse import quote


def _read_payload() -> dict:
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        return {}
    except json.JSONDecodeError:
        return {}


def _emit(status_code: int, payload: dict) -> None:
    print(json.dumps({"status": status_code, "json": payload}))


def main() -> int:
    if len(sys.argv) < 2:
        print("missing action", file=sys.stderr)
        return 2

    action = sys.argv[1]
    payload = _read_payload()

    workspace_root = Path(__file__).resolve().parent.parent
    if str(workspace_root) not in sys.path:
        sys.path.insert(0, str(workspace_root))

    from reservation_manager.web_app import create_app

    app = create_app("data")
    client = app.test_client()

    if action == "schedule":
        period = str(payload.get("period", "day"))
        response = client.get(f"/api/schedule?period={quote(period)}")
        _emit(response.status_code, response.get_json() or {})
        return 0

    if action == "options":
        text = str(payload.get("text", ""))
        response = client.post("/api/reserve/options", json={"text": text})
        _emit(response.status_code, response.get_json() or {})
        return 0

    if action == "commit":
        text = str(payload.get("text", ""))
        option = payload.get("option") if isinstance(payload.get("option"), dict) else {}
        response = client.post("/api/reserve/commit", json={"text": text, "option": option})
        _emit(response.status_code, response.get_json() or {})
        return 0

    print(f"unsupported action: {action}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

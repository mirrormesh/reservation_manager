from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP

from reservation_manager import ReservationYamlRepository

mcp = FastMCP(
    "Reservation MCP Server",
    instructions="Expose reservation data and utilities from the reservation_manager project.",
    json_response=True,
)

DATA_DIR = Path(__file__).parent / "data"
REPOSITORY = ReservationYamlRepository(DATA_DIR)


@mcp.resource("reservation://rooms")
async def list_rooms() -> list[str]:
    """List available meeting room resource names."""
    return [f"회의실{i}" for i in range(1, 11)]


@mcp.resource("reservation://devices")
async def list_devices() -> list[str]:
    """List available test device resource names."""
    return [f"테스트단말기{i}" for i in range(1, 21)]


@mcp.tool()
def list_active_reservations(resource: str | None = None) -> list[dict[str, str]]:
    """Return active reservations, optionally filtered by resource."""
    records = REPOSITORY.get_active_reservations()
    filtered = [record for record in records if resource is None or record.resource == resource]
    return [record.to_dict() for record in filtered]


@mcp.tool()
def add_quick_reservation(resource: str, start_iso: str, end_iso: str, request_text: str = "MCP 예약") -> dict[str, str]:
    """Create a reservation using ISO timestamps."""
    from datetime import datetime

    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)
    created = REPOSITORY.add_reservation(resource, start, end, request_text=request_text)
    return created.to_dict()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

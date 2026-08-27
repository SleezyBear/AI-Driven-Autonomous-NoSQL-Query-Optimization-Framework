"""Minimal long-running worker process owning durable PostgreSQL repositories."""

from __future__ import annotations

import asyncio

from app.db.runtime import create_control_plane_repositories


async def main() -> None:
    engine, _repositories = create_control_plane_repositories()
    try:
        while True:
            await asyncio.sleep(3600)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

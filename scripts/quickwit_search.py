#!/usr/bin/env python3
"""CLI Quickwit search — same client as SMF API."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.quickwit_service import run_quickwit_search  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="Search Quickwit console logs")
    parser.add_argument("query", help="Quickwit query string (e.g. api_key or sId)")
    parser.add_argument("--minutes", type=int, default=60)
    parser.add_argument("--index", default=None, help="Override index name")
    parser.add_argument("--max-hits", type=int, default=500)
    args = parser.parse_args()

    result = await run_quickwit_search(
        args.query,
        index=args.index,
        minutes=args.minutes,
        max_hits=args.max_hits,
    )
    print(
        json.dumps(
            {
                "index": result.index,
                "query": result.query,
                "minutes": result.minutes,
                "status": result.status,
                "num_hits": result.num_hits,
                "hits": result.hits,
            },
            indent=2,
            default=str,
        )
    )


if __name__ == "__main__":
    asyncio.run(main())

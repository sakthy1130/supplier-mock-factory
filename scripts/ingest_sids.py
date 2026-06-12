#!/usr/bin/env python3
"""CLI to ingest reference SIDs into templates/. Implement fully in P1."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add backend to path when run from repo root
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.ingest.template_ingestor import TemplateIngestor  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest reference SIDs into SMF templates")
    parser.add_argument(
        "--input",
        default=str(REPO_ROOT / "reference-sids.json"),
        help="JSON file with HBS and EXP SIDs",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Missing {input_path}. Copy reference-sids.json.example and add your SIDs.")
        sys.exit(1)

    sids = json.loads(input_path.read_text())
    ingestor = TemplateIngestor()
    counts = await ingestor.ingest_from_sids(sids)
    print("Ingest complete:", counts)


if __name__ == "__main__":
    asyncio.run(main())

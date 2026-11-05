"""Command-line interface; parsing arguments is separate from the conversion API."""

from __future__ import annotations

import argparse
import logging
import re
from datetime import date, datetime
from pathlib import Path

from book_reconstruction.conversion import ConversionError, convert_itch_to_parquet
from common.enums import Ticker

# This repository layout makes defaults independent of the current directory.
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = PROJECT_ROOT / "data/raw/12302019.NASDAQ_ITCH50.gz"


def _session_date(source: Path, supplied: date | None) -> date:
    """Return an explicit date or parse MMDDYYYY from a standard Nasdaq filename.

    Reject a conflicting explicit date: otherwise the same event times could
    silently be labeled as the wrong trading day. ITCH itself has no date field.
    """
    match = re.fullmatch(r"(\d{8})\.NASDAQ_ITCH50\.gz", source.name)
    inferred = datetime.strptime(match[1], "%m%d%Y").date() if match else None
    if supplied is not None and inferred is not None and supplied != inferred:
        raise ValueError("--session-date conflicts with the date in the source filename.")
    result = supplied or inferred
    if result is None:
        raise ValueError("Supply --session-date YYYY-MM-DD for a nonstandard source filename.")
    return result


def main() -> None:
    """Parse arguments, convert, print paths, and exit nonzero on failure; return None."""
    parser = argparse.ArgumentParser(
        description="Validate a complete ITCH session and save Parquet."
    )
    parser.add_argument(
        "--source", type=Path, default=DEFAULT_SOURCE, help="Already downloaded .gz"
    )
    parser.add_argument("--output-dir", type=Path, default=PROJECT_ROOT / "data/processed")
    parser.add_argument("--ticker", choices=[item.value for item in Ticker], default="AAPL")
    parser.add_argument(
        "--session-date",
        type=date.fromisoformat,
        help="YYYY-MM-DD; inferred from standard filename",
    )
    parser.add_argument(
        "--batch-size", type=int, default=50_000, help="Maximum buffered retained rows"
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        session = _session_date(args.source, args.session_date)
    except ValueError as exc:
        parser.error(str(exc))
    try:
        report = convert_itch_to_parquet(
            args.source,
            args.output_dir,
            session,
            Ticker(args.ticker),
            args.batch_size,
        )
    except ConversionError as exc:
        parser.exit(1, f"Conversion stopped: {exc}\n")
    print(f"Validated rows: {report.rows_written:,}")
    print(f"Parquet: {report.output_path}")
    print(f"Report: {report.report_path}")

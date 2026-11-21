"""Stream .gz events into a temporary Parquet file, validate, then publish it.

A final file is created only after clean EOF, replay validation, and footer
checks. Failures create a JSON diagnostic; existing output is never overwritten.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

import pyarrow as pa
import pyarrow.parquet as pq

from book_reconstruction.parser import decode_message, iter_messages
from book_reconstruction.validation import ReplayValidator
from common.enums import Ticker
from common.models import (
    DatasetMetadata,
    Diagnostic,
    EventRow,
    ExtractionReport,
    ValidationError,
)
from common.schema import BODY_FIELDS, SCHEMA_VERSION, schema_for_dataset

LOGGER = logging.getLogger(__name__)


class ConversionError(RuntimeError):
    """A failed conversion with the path of its persisted diagnostic report."""

    def __init__(self, diagnostic: Diagnostic, report_path: Path) -> None:
        """Attach a structured failure and its JSON location; return None."""
        self.diagnostic = diagnostic
        self.report_path = report_path
        super().__init__(f"{diagnostic.code}: {diagnostic.message}\nReport: {report_path}")


def _sha256(path: Path) -> str:
    """Return the SHA-256 of the compressed source using bounded one-MiB reads."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, document: dict[str, object]) -> None:
    """Atomically write a complete JSON report; return None.

    A temporary sibling keeps readers from seeing a partially written report.
    This helper owns and removes only the temporary file it creates.
    """
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(document, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def convert_itch_to_parquet(
    source: Path,
    output_dir: Path,
    session_date: date,
    ticker: Ticker = Ticker.AAPL,
    batch_size: int = 50_000,
) -> ExtractionReport:
    """Convert a complete session to one schema-versioned, Zstandard Parquet file.

    Args:
        source: An already downloaded gzip BinaryFILE (no download is attempted).
        output_dir: Directory for the final file and a unique JSON report per run.
        session_date: Explicit calendar date; timestamps in ITCH carry only time.
        ticker: Supported target enum; AAPL is the default.
        batch_size: Maximum retained event dictionaries buffered before a write.

    Returns:
        ExtractionReport with output paths, retained row counts, and source counts.

    Raises:
        ConversionError: Bad input, validation, output collision, or I/O failure.
            Its report_path points to the first diagnostic and partial-run counts.
        OSError: The output/report directory itself cannot be created or written.

    Memory is proportional to batch_size plus the target's live orders, seen
    order IDs, and match IDs; the entire day's event table is never accumulated.
    """
    source, output_dir = source.resolve(), output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / f"{ticker.value}_{session_date.isoformat()}.parquet"
    report_path = output_dir / f"{output.stem}.{uuid4().hex}.report.json"
    report: dict[str, object] = {
        "status": "running",
        "schema_version": SCHEMA_VERSION,
        "ticker": ticker.value,
        "session_date": session_date.isoformat(),
        "source": str(source),
        "output": str(output),
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "validation_scope": (
            "All framing; selected ticker replay and timestamps; global session markers"
        ),
        "completeness_limit": (
            "Checks cannot establish absence of well-formed missing source messages."
        ),
    }
    counts: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    source_records = 0
    rows_written = 0
    temporary: Path | None = None
    validator = ReplayValidator(ticker)
    try:
        if batch_size <= 0:
            raise ValidationError(Diagnostic("INVALID_BATCH_SIZE", "batch_size must be positive."))
        if output.exists():
            raise ValidationError(Diagnostic("OUTPUT_EXISTS", f"Refusing to overwrite {output}."))
        if not source.is_file():
            raise ValidationError(Diagnostic("SOURCE_NOT_FOUND", f"No source file at {source}."))
        before = source.stat()
        LOGGER.info("Hashing compressed source: %s", source)
        metadata = DatasetMetadata(
            ticker,
            session_date,
            source.name,
            before.st_size,
            _sha256(source),
        )
        report["source_sha256"] = metadata.source_sha256
        schema = schema_for_dataset(metadata)

        # A sibling temporary file guarantees the final publication stays on
        # the same filesystem. Closing the handle lets ParquetWriter own it.
        with tempfile.NamedTemporaryFile(
            prefix=f".{output.stem}.",
            suffix=".partial",
            dir=output_dir,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
        rows: list[EventRow] = []
        with pq.ParquetWriter(temporary, schema, compression="zstd", version="2.6") as writer:
            for sequence, payload in iter_messages(source):
                source_records = sequence
                code = chr(payload[0])
                if sequence == 1 and (code != "S" or payload[11:12] != b"O"):
                    raise ValidationError(
                        Diagnostic(
                            "MISSING_SESSION_START",
                            "Source does not begin with S/O.",
                            sequence,
                            code,
                        )
                    )
                if validator.session_codes and validator.session_codes[-1] == "C":
                    raise ValidationError(
                        Diagnostic(
                            "AFTER_SESSION_END",
                            "Source record follows S/C.",
                            sequence,
                            code,
                        )
                    )
                locate = int.from_bytes(payload[1:3], "big")
                # Directory symbol bytes allow discovery of the day-specific
                # locate. We never hardcode AAPL's numeric stock_locate.
                is_directory = code == "R" and payload[11:19].rstrip(b" ") == ticker.value.encode()
                is_target = validator.locate is not None and locate == validator.locate
                if code == "S" or is_directory or (is_target and code in BODY_FIELDS):
                    event = decode_message(sequence, payload)
                    validator.accept(event)
                    rows.append(event.to_row())
                    counts[code] += 1
                    if len(rows) >= batch_size:
                        writer.write_table(pa.Table.from_pylist(rows, schema=schema))
                        rows_written += len(rows)
                        rows.clear()
                else:
                    skipped[code] += 1
                if sequence % 5_000_000 == 0:
                    LOGGER.info(
                        "Read %s source records; retained %s rows",
                        f"{sequence:,}",
                        f"{sum(counts.values()):,}",
                    )
            validator.finish()
            if rows:
                writer.write_table(pa.Table.from_pylist(rows, schema=schema))
                rows_written += len(rows)

        after = source.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValidationError(Diagnostic("SOURCE_CHANGED", "Source changed during conversion."))
        # Reopen the completed footer before publication. Unit tests additionally
        # check full row round-trips, including nulls and large unsigned IDs.
        footer = pq.read_metadata(temporary)
        if footer.num_rows != rows_written or not footer.schema.to_arrow_schema().equals(
            schema,
            check_metadata=True,
        ):
            raise ValidationError(
                Diagnostic("PARQUET_MISMATCH", "Footer schema/count differs from writer.")
            )
        # Windows refuses fsync on a read-only handle (EBADF), hence "r+b".
        with temporary.open("r+b") as stream:
            os.fsync(stream.fileno())
        report.update(
            {
                "status": "validated",
                "rows_written": rows_written,
                "source_records": source_records,
                "counts_by_type": dict(counts),
                "skipped_by_type": dict(skipped),
                "live_orders_at_end": len(validator.orders),
                "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        _write_json(report_path, report)
        # A hard link publishes the already complete file atomically, and fails
        # if another run created the destination. os.replace would overwrite it.
        os.link(temporary, output)
        return ExtractionReport(
            output,
            report_path,
            rows_written,
            source_records,
            dict(counts),
            dict(skipped),
        )
    except (Exception, KeyboardInterrupt) as exc:
        if isinstance(exc, ValidationError):
            diagnostic = exc.diagnostic
        else:
            # Unexpected errors remain visible by class and message, with source
            # context when available; the original exception is chained below.
            last = validator.last_event
            diagnostic = Diagnostic(
                type(exc).__name__,
                str(exc),
                source_records or None,
                last.message_type.value if last else None,
                last.timestamp_ns if last else None,
            )
        report.update(
            {
                "status": "failed",
                "diagnostic": asdict(diagnostic),
                "rows_written_to_temporary": rows_written,
                "retained_before_failure": sum(counts.values()),
                "source_records": source_records,
                "counts_by_type": dict(counts),
                "skipped_by_type": dict(skipped),
                "finished_at_utc": datetime.now(timezone.utc).isoformat(),
            }
        )
        _write_json(report_path, report)
        raise ConversionError(diagnostic, report_path) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

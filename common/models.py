"""Annotated objects exchanged by the parser, validator, and conversion API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from common.enums import MessageType, Ticker

# A decoded field is an unsigned integer or original ASCII text. Missing fields
# are absent from the body dictionary and become null through the Arrow schema.
FieldValue = int | str
EventRow = dict[str, FieldValue]


@dataclass(frozen=True)
class Event:
    """One decoded retained message. Body contains only fields present on the wire."""

    sequence: int
    timestamp_ns: int
    message_type: MessageType
    stock_locate: int
    tracking_number: int
    body: EventRow

    def to_row(self) -> EventRow:
        """Return one flat row; Arrow supplies nulls for the other message types' fields."""
        return {
            "sequence": self.sequence,
            "timestamp_ns": self.timestamp_ns,
            "message_type": self.message_type.value,
            "stock_locate": self.stock_locate,
            "tracking_number": self.tracking_number,
            **self.body,
        }


@dataclass(frozen=True)
class DatasetMetadata:
    """Session/source identity embedded in the Parquet schema metadata.

    The date is caller-supplied: ITCH timestamps contain no calendar date.
    source_sha256 identifies the compressed file and is not a vendor checksum.
    """

    ticker: Ticker
    session_date: date
    source_file: str
    source_bytes: int
    source_sha256: str


@dataclass(frozen=True)
class Diagnostic:
    """Machine-readable reason for the first failure; context is null if unavailable."""

    code: str
    message: str
    sequence: int | None = None
    message_type: str | None = None
    timestamp_ns: int | None = None
    order_id: int | None = None


class ValidationError(ValueError):
    """A data error carrying a Diagnostic, rather than a silent cleaning decision."""

    def __init__(self, diagnostic: Diagnostic) -> None:
        """Initialize the exception from its structured diagnostic; return None."""
        self.diagnostic = diagnostic
        super().__init__(f"{diagnostic.code}: {diagnostic.message}")


@dataclass(frozen=True)
class ExtractionReport:
    """Successful conversion result; events themselves remain on disk."""

    output_path: Path
    report_path: Path
    rows_written: int
    source_records: int
    counts_by_type: dict[str, int]
    skipped_by_type: dict[str, int]

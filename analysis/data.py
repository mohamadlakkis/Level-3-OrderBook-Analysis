"""Load Parquet through the shared contract, preserving original types and nulls.

This reader validates stored data; it does not reconstruct an order book or infer
trade directions. A source path is always explicit, with no silent fallback.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from common.enums import Ticker
from common.schema import (
    BODY_FIELDS,
    EVENT_SCHEMA,
    NANOSECONDS_PER_DAY,
    PRICE_SCALE,
    SCHEMA_VERSION,
    TIMEZONE,
)


@dataclass(frozen=True)
class MarketData:
    """Known reader result: typed events plus the session identity they belong to."""

    ticker: Ticker
    session_date: date
    timezone: str
    schema_version: str
    source_path: Path
    events: pa.Table


def file_sha256(path: Path) -> str:
    """Return a file's SHA-256 without loading the complete file into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def load_market_data(
    path: Path,
    *,
    expected_ticker: Ticker = Ticker.AAPL,
    expected_date: date | None = None,
    expected_sha256: str | None = None,
) -> MarketData:
    """Return checked Arrow events and metadata; raise ValueError for inconsistencies.

    Missing files raise FileNotFoundError and unreadable Parquet raises PyArrow's
    original exception. No rows are dropped, imputed, sorted, or deduplicated.
    The optional checksum identifies a specific reference file, not a vendor
    checksum. Full order-lifecycle validation belongs to the conversion stage.
    """
    path = path.resolve(strict=True)
    if expected_sha256 is not None and file_sha256(path) != expected_sha256.lower():
        raise ValueError("Parquet checksum does not match the requested reference file.")
    # Use ParquetFile to read exactly this file, without inferring folder partitions.
    file = pq.ParquetFile(path)
    schema = file.schema_arrow
    if not schema.remove_metadata().equals(EVENT_SCHEMA):
        raise ValueError("Parquet columns, types, or nullability differ from the shared schema.")
    metadata = schema.metadata or {}
    required_metadata = ("ticker", "session_date", "timezone", "schema_version", "price_scale")
    if any(key.encode() not in metadata for key in required_metadata):
        raise ValueError("Required dataset identity metadata is missing.")
    values = {key: metadata[key.encode()].decode("utf-8") for key in required_metadata}
    if values["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"Unsupported schema version: {values['schema_version']}.")
    if values["timezone"] != TIMEZONE or values["price_scale"] != str(PRICE_SCALE):
        raise ValueError("Unexpected timezone convention or price scale.")
    ticker = Ticker(values["ticker"])
    session_date = date.fromisoformat(values["session_date"])
    if ticker != expected_ticker or (expected_date is not None and session_date != expected_date):
        raise ValueError("Dataset ticker/date differs from the requested analysis session.")
    table = file.read()
    table.validate(full=True)
    if table.num_rows == 0:
        raise ValueError("Cannot analyze an empty event table.")
    for field in EVENT_SCHEMA:
        if not field.nullable and table[field.name].null_count:
            raise ValueError(f"Required header field {field.name} contains nulls.")
    sequence, timestamp = table["sequence"], table["timestamp_ns"]
    if sequence[0].as_py() < 1 or (
        table.num_rows > 1
        and not pc.all(pc.greater(sequence.slice(1), sequence.slice(0, table.num_rows - 1))).as_py()
    ):
        raise ValueError("Source sequence must be positive and strictly increasing.")
    if pc.max(timestamp).as_py() >= NANOSECONDS_PER_DAY or (
        table.num_rows > 1
        and not pc.all(
            pc.greater_equal(timestamp.slice(1), timestamp.slice(0, table.num_rows - 1))
        ).as_py()
    ):
        raise ValueError("Timestamp is outside the day or retained events go backwards.")
    codes = set(table["message_type"].unique().to_pylist())
    if not codes.issubset(BODY_FIELDS):
        raise ValueError(f"Unexpected message types: {codes - set(BODY_FIELDS)}.")
    supplied_stocks = set(table["stock"].drop_null().unique().to_pylist())
    if supplied_stocks - {ticker.value}:
        raise ValueError("Stock field disagrees with the dataset ticker metadata.")
    for code in codes:
        mask = pc.equal(table["message_type"], code)
        # An applicable field must be present; an inapplicable field must be null.
        # This distinguishes structural absence from accidentally missing data.
        for field in EVENT_SCHEMA.names[5:]:
            invalid = (
                pc.is_null(table[field])
                if field in BODY_FIELDS[code]
                else pc.is_valid(table[field])
            )
            if pc.any(pc.and_(mask, invalid)).as_py():
                raise ValueError(f"Field {field} violates its applicability rule for {code}.")
    return MarketData(ticker, session_date, TIMEZONE, SCHEMA_VERSION, path, table)

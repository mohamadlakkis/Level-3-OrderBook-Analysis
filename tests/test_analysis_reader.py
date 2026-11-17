"""Reader contract tests use tiny files without pandas or notebook dependencies."""

from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from analysis.data import MarketData, file_sha256, load_market_data
from common.enums import Ticker
from common.models import DatasetMetadata
from common.schema import schema_for_dataset

LARGE_ID = 2**63 + 321
SESSION = date(2019, 12, 30)


@pytest.fixture
def event_table() -> pa.Table:
    """Return add/execution/delete rows with structural nulls and source-position gaps."""
    metadata = DatasetMetadata(Ticker.AAPL, SESSION, "synthetic.gz", 0, "0" * 64)
    rows = [
        {
            "sequence": 1,
            "timestamp_ns": 10,
            "message_type": "A",
            "stock_locate": 7,
            "tracking_number": 0,
            "order_id": LARGE_ID,
            "side": "B",
            "shares": 20,
            "stock": "AAPL",
            "price_units": 100_000,
        },
        {
            "sequence": 4,
            "timestamp_ns": 10,
            "message_type": "E",
            "stock_locate": 7,
            "tracking_number": 0,
            "order_id": LARGE_ID,
            "shares": 5,
            "match_id": 77,
        },
        {
            "sequence": 5,
            "timestamp_ns": 11,
            "message_type": "D",
            "stock_locate": 7,
            "tracking_number": 0,
            "order_id": LARGE_ID,
        },
    ]
    return pa.Table.from_pylist(rows, schema=schema_for_dataset(metadata))


def test_known_object_preserves_ids_nulls_and_equal_timestamps(
    tmp_path: Path,
    event_table: pa.Table,
) -> None:
    path = tmp_path / "events.parquet"
    pq.write_table(event_table, path)
    result = load_market_data(path, expected_date=SESSION, expected_sha256=file_sha256(path))
    assert isinstance(result, MarketData)
    assert result.ticker == Ticker.AAPL and result.session_date == SESSION
    assert result.events["order_id"].to_pylist() == [LARGE_ID] * 3
    assert result.events["shares"].to_pylist() == [20, 5, None]
    assert result.events["side"].to_pylist() == ["B", None, None]
    assert result.events["sequence"].to_pylist() == [1, 4, 5]


@pytest.mark.parametrize(
    ("column", "values", "error"),
    [
        ("sequence", [1, 1, 5], "sequence"),
        ("timestamp_ns", [10, 9, 11], "Timestamp"),
        ("timestamp_ns", [10, 10, 86_400_000_000_000], "Timestamp"),
        ("shares", [20, None, None], "applicability"),
        ("price_units", [100_000, None, 100_000], "applicability"),
        ("message_type", ["A", "Z", "D"], "message types"),
        ("stock", ["MSFT", None, None], "Stock field"),
    ],
)
def test_invalid_stored_events_are_rejected(
    tmp_path: Path,
    event_table: pa.Table,
    column: str,
    values: list[object],
    error: str,
) -> None:
    position = event_table.schema.get_field_index(column)
    changed = event_table.set_column(
        position,
        event_table.schema.field(column),
        pa.array(values, type=event_table.schema.field(column).type),
    )
    path = tmp_path / "bad.parquet"
    pq.write_table(changed, path)
    with pytest.raises(ValueError, match=error):
        load_market_data(path)


def test_identity_schema_and_checksum_are_checked(tmp_path: Path, event_table: pa.Table) -> None:
    path = tmp_path / "events.parquet"
    pq.write_table(event_table, path)
    with pytest.raises(ValueError, match="ticker/date"):
        load_market_data(path, expected_date=date(2020, 1, 1))
    with pytest.raises(ValueError, match="checksum"):
        load_market_data(path, expected_sha256="0" * 64)
    wrong = event_table.replace_schema_metadata(
        {**event_table.schema.metadata, b"schema_version": b"99"}
    )
    pq.write_table(wrong, path)
    with pytest.raises(ValueError, match="schema version"):
        load_market_data(path)
    pq.write_table(event_table.drop(["sequence"]), path)
    with pytest.raises(ValueError, match="shared schema"):
        load_market_data(path)


def test_empty_table_fails_and_single_event_is_valid(tmp_path: Path, event_table: pa.Table) -> None:
    path = tmp_path / "events.parquet"
    pq.write_table(event_table.slice(0, 0), path)
    with pytest.raises(ValueError, match="empty"):
        load_market_data(path)
    pq.write_table(event_table.slice(0, 1), path)
    assert load_market_data(path).events.num_rows == 1

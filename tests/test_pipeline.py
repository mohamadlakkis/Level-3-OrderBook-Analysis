"""Small, independently constructed wire streams test the public conversion behavior.

These fixtures exercise whole conversions, not just parser implementation details.
No network or multi-gigabyte input is required to run the test suite.
"""

from __future__ import annotations

import gzip
import json
import os
import struct
import subprocess
from datetime import date
from pathlib import Path

import pyarrow.parquet as pq
import pytest
from book_reconstruction.cli import _session_date
from book_reconstruction.conversion import ConversionError, convert_itch_to_parquet
from book_reconstruction.parser import iter_messages

from common.enums import Ticker
from common.models import ValidationError
from common.schema import EVENT_SCHEMA

SESSION_DATE = date(2019, 12, 30)
LARGE_ID = 2**63 + 123  # This must survive Parquet without signed overflow or float rounding.


def message(code: str, body: bytes, timestamp: int = 10, locate: int = 7) -> bytes:
    """Return one framed ITCH message, with a deliberately nonzero tracking number."""
    header = code.encode() + struct.pack(">HH", locate, 19) + timestamp.to_bytes(6, "big")
    payload = header + body
    return struct.pack(">H", len(payload)) + payload


def system(phase: str, timestamp: int) -> bytes:
    """Return an S message; phase is a body code distinct from the message type."""
    return message("S", phase.encode(), timestamp, locate=0)


def directory(stock: bytes = b"AAPL    ", locate: int = 7) -> bytes:
    """Return a stock directory with actual field widths from the specification."""
    body = struct.pack(
        ">8sccIcc2scccccIc",
        stock,
        b"Q",
        b"N",
        100,
        b"N",
        b"C",
        b"  ",
        b"P",
        b"N",
        b"N",
        b"1",
        b"N",
        1,
        b"N",
    )
    return message("R", body, timestamp=2, locate=locate)


def add(oid: int = LARGE_ID, shares: int = 100, side: bytes = b"S", timestamp: int = 10) -> bytes:
    """Return an unattributed add with an exact integer $200.0000 price."""
    return message(
        "A", struct.pack(">QcI8sI", oid, side, shares, b"AAPL    ", 2_000_000), timestamp
    )


def source_file(tmp_path: Path, events: list[bytes], close: bool = True) -> Path:
    """Write a complete synthetic session unless a test explicitly requests truncation."""
    prefix = [system("O", 1), directory(), system("S", 3), system("Q", 4)]
    suffix = [system("M", 1000), system("E", 1001), system("C", 1002)] if close else []
    path = tmp_path / "12302019.NASDAQ_ITCH50.gz"
    path.write_bytes(gzip.compress(b"".join([*prefix, *events, *suffix])))
    return path


def test_full_lifecycle_preserves_supplied_fields_and_nulls(tmp_path: Path) -> None:
    """A cancelled/deleted order stays in the event log, without derived fields."""
    events = [
        add(),
        message("X", struct.pack(">QI", LARGE_ID, 30), 11),
        message("E", struct.pack(">QIQ", LARGE_ID, 20, 100), 12),
        message("U", struct.pack(">QQII", LARGE_ID, LARGE_ID + 1, 40, 2_000_100), 13),
        message("C", struct.pack(">QIQcI", LARGE_ID + 1, 10, 101, b"N", 2_000_050), 14),
        message("D", struct.pack(">Q", LARGE_ID + 1), 15),
        message("B", struct.pack(">Q", 100), 16),
    ]
    report = convert_itch_to_parquet(
        source_file(tmp_path, events), tmp_path / "out", SESSION_DATE, batch_size=2
    )
    table = pq.read_table(report.output_path)
    assert table.schema.remove_metadata().equals(EVENT_SCHEMA)
    assert table.num_rows == report.rows_written == 14
    rows = table.to_pylist()
    cancel = next(row for row in rows if row["message_type"] == "X")
    assert cancel["order_id"] == LARGE_ID
    assert cancel["shares"] == 30
    assert cancel["side"] is None and cancel["price_units"] is None
    execution = next(row for row in rows if row["message_type"] == "E")
    assert execution["shares"] == 20 and execution["price_units"] is None
    replacement = next(row for row in rows if row["message_type"] == "U")
    assert (replacement["order_id"], replacement["new_order_id"]) == (LARGE_ID, LARGE_ID + 1)
    assert replacement["side"] is None
    deleted = next(row for row in rows if row["message_type"] == "D")
    assert deleted["shares"] is None  # No synthetic zero or replay-derived 30.
    assert "aggressor_side" not in table.column_names
    assert "remaining_shares" not in table.column_names
    metadata = table.schema.metadata
    assert metadata[b"session_date"] == b"2019-12-30"
    assert metadata[b"timezone"] == b"America/New_York"
    assert len(metadata[b"source_sha256"]) == 64
    assert json.loads(report.report_path.read_text())["status"] == "validated"
    assert not list((tmp_path / "out").glob("*.partial"))


def test_supporting_messages_and_other_stocks(tmp_path: Path) -> None:
    """Keep status/trade information and exact flags while filtering other tickers."""
    events = [
        message("H", struct.pack(">8scc4s", b"AAPL    ", b"T", b" ", b"    "), 10),
        message("h", struct.pack(">8scc", b"AAPL    ", b"Q", b"H"), 11),
        message("F", struct.pack(">QcI8sI4s", 30, b"B", 10, b"AAPL    ", 1000, b"ABCD"), 12),
        message("P", struct.pack(">QcI8sIQ", 0, b"B", 10, b"AAPL    ", 1000, 200), 13),
        message("Q", struct.pack(">Q8sIQc", 0, b"AAPL    ", 0, 201, b"O"), 14),
        message("B", struct.pack(">Q", 200), 15),
        # Known, excluded NOII message: its body is deliberately not interpreted.
        message("I", b"\0" * 39, 16),
        message("D", struct.pack(">Q", 999), 17, locate=8),
    ]
    report = convert_itch_to_parquet(source_file(tmp_path, events), tmp_path / "out", SESSION_DATE)
    rows = pq.read_table(report.output_path).to_pylist()
    assert next(row for row in rows if row["message_type"] == "H")["reason"] == "    "
    assert next(row for row in rows if row["message_type"] == "F")["attribution"] == "ABCD"
    assert next(row for row in rows if row["message_type"] == "P")["order_id"] == 0
    assert next(row for row in rows if row["message_type"] == "Q")["shares"] == 0
    assert report.skipped_by_type == {"I": 1, "D": 1}
    assert report.source_records == report.rows_written + 2


@pytest.mark.parametrize(
    ("events", "error_code"),
    [
        ([message("D", struct.pack(">Q", 999))], "UNKNOWN_ORDER"),
        ([add(), message("E", struct.pack(">QIQ", LARGE_ID, 101, 1), 11)], "EXCESS_REMOVAL"),
        ([add(), message("X", struct.pack(">QI", LARGE_ID, 101), 11)], "EXCESS_REMOVAL"),
        ([add(), add(timestamp=11)], "DUPLICATE_OR_INVALID_ORDER"),
        ([add(side=b"?")], "INVALID_SIDE"),
        ([add(shares=0)], "INVALID_SHARES"),
        ([add(timestamp=20), message("D", struct.pack(">Q", LARGE_ID), 19)], "BACKWARD_TIMESTAMP"),
        (
            [add(), message("U", struct.pack(">QQII", LARGE_ID, LARGE_ID, 1, 1000), 11)],
            "DUPLICATE_OR_INVALID_ORDER",
        ),
        ([message("B", struct.pack(">Q", 444))], "INVALID_TRADE_BREAK"),
        (
            [message("H", struct.pack(">8scc4s", b"MSFT    ", b"T", b" ", b"    "))],
            "SYMBOL_MISMATCH",
        ),
        ([message("A", struct.pack(">QcI8sI", 1, b"B", 1, b"AAPL    ", 0))], "INVALID_PRICE"),
        (
            [message("P", struct.pack(">QcI8sIQ", 0, b"B", 0, b"AAPL    ", 100, 2))],
            "INVALID_SHARES",
        ),
    ],
)
def test_data_errors_stop_without_publishing(
    tmp_path: Path,
    events: list[bytes],
    error_code: str,
) -> None:
    """Failures after batch writes still remove partial output and retain diagnostics."""
    with pytest.raises(ConversionError) as caught:
        convert_itch_to_parquet(
            source_file(tmp_path, events), tmp_path / "out", SESSION_DATE, batch_size=1
        )
    error = caught.value
    assert error.diagnostic.code == error_code
    document = json.loads(error.report_path.read_text())
    assert document["status"] == "failed"
    assert document["diagnostic"]["sequence"] is not None
    assert not list((tmp_path / "out").glob("*.parquet"))
    assert not list((tmp_path / "out").glob("*.partial"))


def test_equal_timestamps_remain_in_source_order(tmp_path: Path) -> None:
    """Monotonic means nondecreasing timestamps, not strictly increasing time."""
    events = [add(), message("D", struct.pack(">Q", LARGE_ID), 10)]
    report = convert_itch_to_parquet(source_file(tmp_path, events), tmp_path / "out", SESSION_DATE)
    rows = pq.read_table(report.output_path).to_pylist()
    selected = [row for row in rows if row["timestamp_ns"] == 10]
    assert [row["message_type"] for row in selected] == ["A", "D"]
    assert selected[0]["sequence"] < selected[1]["sequence"]


def test_trade_break_does_not_restore_displayed_shares(tmp_path: Path) -> None:
    """A broken execution affects trade interpretation, not the current book."""
    events = [
        add(),
        message("E", struct.pack(">QIQ", LARGE_ID, 40, 100), 11),
        message("B", struct.pack(">Q", 100), 12),
        message("X", struct.pack(">QI", LARGE_ID, 60), 13),
    ]
    report = convert_itch_to_parquet(
        source_file(tmp_path, events),
        tmp_path / "out",
        SESSION_DATE,
    )
    assert json.loads(report.report_path.read_text())["live_orders_at_end"] == 0


def test_session_boundary_rejects_even_filtered_records(tmp_path: Path) -> None:
    """An out-of-scope stock after S/C cannot hide behind ticker filtering."""
    source = source_file(tmp_path, [add()])
    raw = gzip.decompress(source.read_bytes())
    raw += message("D", struct.pack(">Q", 999), 1010, locate=8)
    source.write_bytes(gzip.compress(raw))
    with pytest.raises(ConversionError) as caught:
        convert_itch_to_parquet(source, tmp_path / "out", SESSION_DATE)
    assert caught.value.diagnostic.code == "AFTER_SESSION_END"


def test_missing_source_has_a_report(tmp_path: Path) -> None:
    """Failure before parsing still records an explicit source diagnostic."""
    with pytest.raises(ConversionError) as caught:
        convert_itch_to_parquet(tmp_path / "absent.gz", tmp_path / "out", SESSION_DATE)
    assert caught.value.diagnostic.code == "SOURCE_NOT_FOUND"
    assert json.loads(caught.value.report_path.read_text())["status"] == "failed"


def test_missing_end_marker_is_not_a_valid_partial_day(tmp_path: Path) -> None:
    """A well-formed gzip with an incomplete session still fails."""
    with pytest.raises(ConversionError) as caught:
        convert_itch_to_parquet(
            source_file(tmp_path, [add()], close=False), tmp_path / "out", SESSION_DATE
        )
    assert caught.value.diagnostic.code == "INCOMPLETE_SESSION"


def test_existing_output_is_preserved(tmp_path: Path) -> None:
    """A second run cannot replace a previous validated file."""
    source = source_file(tmp_path, [add()])
    report = convert_itch_to_parquet(source, tmp_path / "out", SESSION_DATE)
    original = report.output_path.read_bytes()
    with pytest.raises(ConversionError) as caught:
        convert_itch_to_parquet(source, tmp_path / "out", SESSION_DATE)
    assert caught.value.diagnostic.code == "OUTPUT_EXISTS"
    assert report.output_path.read_bytes() == original


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (b"\0", "TRUNCATED_LENGTH"),
        (b"\0\x24A", "TRUNCATED_MESSAGE"),
        (message("Z", b""), "UNKNOWN_MESSAGE_TYPE"),
        (message("D", b""), "INVALID_MESSAGE_LENGTH"),
        (b"\0\0extra", "TRAILING_DATA"),
    ],
)
def test_binary_framing_errors(tmp_path: Path, raw: bytes, code: str) -> None:
    """Malformed framing is rejected before a message can change replay state."""
    path = tmp_path / "broken.gz"
    path.write_bytes(gzip.compress(raw))
    with pytest.raises(ValidationError) as caught:
        list(iter_messages(path))
    assert caught.value.diagnostic.code == code


def test_gzip_crc_error_generates_diagnostic(tmp_path: Path) -> None:
    """gzip corruption is an explicit conversion failure, with no final Parquet."""
    source = source_file(tmp_path, [add()])
    compressed = bytearray(source.read_bytes())
    compressed[-8] ^= 1  # Change the gzip trailer's CRC, leaving framing intact.
    source.write_bytes(compressed)
    with pytest.raises(ConversionError) as caught:
        convert_itch_to_parquet(source, tmp_path / "out", SESSION_DATE)
    assert caught.value.diagnostic.code == "BadGzipFile"
    assert caught.value.report_path.exists()
    assert not list((tmp_path / "out").glob("*.parquet"))


def test_optional_terminator_and_missing_ticker(tmp_path: Path) -> None:
    """A zero terminator is allowed, while an absent selected symbol fails."""
    source = source_file(tmp_path, [add()])
    source.write_bytes(gzip.compress(gzip.decompress(source.read_bytes()) + b"\0\0"))
    convert_itch_to_parquet(source, tmp_path / "out", SESSION_DATE)
    missing = tmp_path / "missing.gz"
    missing.write_bytes(gzip.compress(system("O", 1) + system("S", 2)))
    with pytest.raises(ConversionError) as caught:
        convert_itch_to_parquet(missing, tmp_path / "missing-out", SESSION_DATE)
    assert caught.value.diagnostic.code == "TICKER_NOT_FOUND"


def test_cli_session_date_resolution() -> None:
    """Calendar labels are explicit or filename-derived, never guessed from ITCH time."""
    assert _session_date(Path("12302019.NASDAQ_ITCH50.gz"), None) == SESSION_DATE
    assert _session_date(Path("custom.gz"), SESSION_DATE) == SESSION_DATE
    with pytest.raises(ValueError, match="conflicts"):
        _session_date(Path("12302019.NASDAQ_ITCH50.gz"), date(2020, 1, 1))
    with pytest.raises(ValueError, match="Supply"):
        _session_date(Path("custom.gz"), None)
    assert Ticker.AAPL.value == "AAPL"


def test_downloader_destination_is_independent_of_working_directory(tmp_path: Path) -> None:
    """Replace wget with a local recorder; verify the script without any network."""
    project = Path(__file__).resolve().parents[1]
    capture = tmp_path / "wget-arguments.txt"
    fake_wget = tmp_path / "wget"
    fake_wget.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ITCH_TEST_CAPTURE"\n')
    fake_wget.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "ITCH_TEST_CAPTURE": str(capture),
    }
    subprocess.run(
        ["bash", str(project / "setup_scripts" / "ubuntu_setup.sh")],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
    )
    assert capture.read_text().splitlines() == [
        "-c",
        "-P",
        str(project / "data/raw"),
        "https://emi.nasdaq.com/ITCH/Nasdaq%20ITCH/12302019.NASDAQ_ITCH50.gz",
    ]

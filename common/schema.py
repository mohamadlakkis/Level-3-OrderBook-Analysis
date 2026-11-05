"""The versioned Parquet contract shared by conversion and future readers.

Columns are the union of retained wire-message fields. Header fields are always
present; body fields are required only for the message types in BODY_FIELDS.
No price is converted to float and no missing value is replaced by zero.
"""

from __future__ import annotations

import json

import pyarrow as pa

from common.models import DatasetMetadata

SCHEMA_VERSION = "1.0.0"
PRICE_SCALE = 10_000
TIMEZONE = "America/New_York"
NANOSECONDS_PER_DAY = 86_400_000_000_000

# Descriptions also become field metadata in the Parquet file. uint64 supports
# the entire eight-byte ITCH order/match range without signed-integer overflow.
COLUMNS: list[tuple[str, pa.DataType, str]] = [
    ("sequence", pa.uint64(), "One-based source record position; not a vendor packet sequence."),
    ("timestamp_ns", pa.uint64(), "Exchange nanoseconds since local midnight."),
    ("message_type", pa.string(), "Original case-sensitive ITCH code."),
    ("stock_locate", pa.uint16(), "Day-specific instrument code; zero for system events."),
    ("tracking_number", pa.uint16(), "Original Nasdaq internal tracking number."),
    ("order_id", pa.uint64(), "Order reference; old reference for U; legacy zero for P."),
    ("new_order_id", pa.uint64(), "Replacement order reference supplied by U."),
    ("side", pa.string(), "Supplied B/S code; P's legacy B is not an economic side."),
    ("shares", pa.uint64(), "Supplied added/executed/cancelled/replacement/cross quantity."),
    ("stock", pa.string(), "Symbol when supplied in the message body."),
    ("price_units", pa.uint32(), "Supplied price integer; divide by 10000 for dollars."),
    ("attribution", pa.string(), "Four-character MPID supplied by F."),
    ("match_id", pa.uint64(), "Original execution/trade match reference."),
    ("printable", pa.string(), "C printability flag Y/N; retained as text."),
    ("cross_type", pa.string(), "Q auction code, such as O, C, or H."),
    ("event_code", pa.string(), "S session phase O/S/Q/M/E/C."),
    ("trading_state", pa.string(), "H state H/P/Q/T."),
    ("reserved", pa.string(), "H reserved byte, preserved including a space."),
    ("reason", pa.string(), "Four-byte H reason, preserved including padding."),
    ("market_code", pa.string(), "h venue code Q/B/X."),
    ("operational_halt_action", pa.string(), "h action H/T."),
    ("market_category", pa.string(), "R market category."),
    ("financial_status", pa.string(), "R financial status indicator."),
    ("round_lot_size", pa.uint32(), "R shares per round lot."),
    ("round_lots_only", pa.string(), "R round-lots-only flag."),
    ("issue_classification", pa.string(), "R issue classification."),
    ("issue_subtype", pa.string(), "R two-byte subtype, padding preserved."),
    ("authenticity", pa.string(), "R production/test indicator."),
    ("short_sale_threshold", pa.string(), "R short-sale threshold indicator."),
    ("ipo_flag", pa.string(), "R IPO flag."),
    ("luld_tier", pa.string(), "R LULD reference price tier."),
    ("etp_flag", pa.string(), "R exchange-traded product flag."),
    ("etp_leverage", pa.uint32(), "R integer leverage factor."),
    ("inverse_indicator", pa.string(), "R inverse ETP indicator."),
]

# These are the exact body fields required by each type. Header fields are
# common. Everything outside a type's field list must remain null in Parquet.
DIRECTORY_FIELDS = (
    "stock",
    "market_category",
    "financial_status",
    "round_lot_size",
    "round_lots_only",
    "issue_classification",
    "issue_subtype",
    "authenticity",
    "short_sale_threshold",
    "ipo_flag",
    "luld_tier",
    "etp_flag",
    "etp_leverage",
    "inverse_indicator",
)
ADD_FIELDS = ("order_id", "side", "shares", "stock", "price_units")
BODY_FIELDS: dict[str, tuple[str, ...]] = {
    "S": ("event_code",),
    "R": DIRECTORY_FIELDS,
    "H": ("stock", "trading_state", "reserved", "reason"),
    "h": ("stock", "market_code", "operational_halt_action"),
    "A": ADD_FIELDS,
    "F": (*ADD_FIELDS, "attribution"),
    "E": ("order_id", "shares", "match_id"),
    "C": ("order_id", "shares", "match_id", "printable", "price_units"),
    "X": ("order_id", "shares"),
    "D": ("order_id",),
    "U": ("order_id", "new_order_id", "shares", "price_units"),
    "P": (*ADD_FIELDS, "match_id"),
    "Q": ("shares", "stock", "price_units", "match_id", "cross_type"),
    "B": ("match_id",),
}

EVENT_SCHEMA = pa.schema(
    [
        pa.field(name, dtype, nullable=index >= 5, metadata={"description": description})
        for index, (name, dtype, description) in enumerate(COLUMNS)
    ]
)


def schema_for_dataset(metadata: DatasetMetadata) -> pa.Schema:
    """Return the shared Arrow schema with this session's identity attached."""
    values = {
        "schema_version": SCHEMA_VERSION,
        "ticker": metadata.ticker.value,
        "session_date": metadata.session_date.isoformat(),
        "timezone": TIMEZONE,
        "price_scale": str(PRICE_SCALE),
        "source_file": metadata.source_file,
        "source_bytes": str(metadata.source_bytes),
        "source_sha256": metadata.source_sha256,
        "retained_message_types": json.dumps(list(BODY_FIELDS)),
    }
    # Arrow stores metadata as bytes; explicit UTF-8 is portable across readers.
    return EVENT_SCHEMA.with_metadata(
        {key.encode(): value.encode() for key, value in values.items()}
    )

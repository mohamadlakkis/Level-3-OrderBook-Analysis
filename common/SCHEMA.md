# Stored event contract, version 1.0.0

This document is the contract between the `.gz` converter and analysis.
The executable definition is [schema.py](schema.py). A Parquet file contains
one table: each row is one original retained message, in source order. Nothing
is silently dropped because it failed validation. Invalid input stops the run.

## Original fields and metadata

The first five columns are always non-null. Every other column is nullable at
table level because different message types carry different body fields. The
per-message matrix below makes the applicable fields mandatory for each type.
Inapplicable fields are null, not zero, an empty string, or a replay estimate.

| Column | Arrow type | Meaning |
|---|---|---|
| `sequence` | uint64 | One-based record position in the **whole source file**, across all stocks. Filtering creates gaps. This is our source position, not a network sequence number supplied by Nasdaq. |
| `timestamp_ns` | uint64 | Original six-byte exchange time, nanoseconds since midnight, widened losslessly to uint64. |
| `message_type` | string | Original case-sensitive code: `H` and `h` are different messages. |
| `stock_locate` | uint16 | Original daily instrument identifier; global system messages use zero. |
| `tracking_number` | uint16 | Original internal Nasdaq tracking number. It is not a missing-packet counter. |
| `order_id` | uint64 | Original referenced order; for `U` this is the old ID. For `P` the supplied value is normally the legacy zero. |
| `new_order_id` | uint64 | New replacement ID supplied by `U`. |
| `side` | string | Original B/S field, only in `A`, `F`, `P`. The legacy `P` value is **not** a reliable economic side. |
| `shares` | uint64 | Quantity supplied by the message. Wide enough for the eight-byte cross volume. |
| `stock` | string | Stock symbol when included in the body; trailing spaces removed. |
| `price_units` | uint32 | Original Price(4) integer. Divide by 10,000 for dollars; use Decimal if exact decimal arithmetic is needed. |
| `attribution` | string | Four ASCII bytes of MPID supplied by `F`; padding retained. |
| `match_id` | uint64 | Original execution/trade reference; `B` references the broken match. |
| `printable` | string | Original `C` flag `Y`/`N`. Non-printable executions still update the displayed book. |
| `cross_type` | string | `Q` auction type, including opening, closing, halt/IPO, or intraday. |
| `event_code` | string | `S` session phase; this is separate from `message_type`. |
| `trading_state` | string | `H` state: halted `H`, paused `P`, quotation-only `Q`, trading `T`. |
| `reserved` | string | Original `H` reserved byte. A space remains a space. |
| `reason` | string | Original four-byte trading-action reason, including space padding. |
| `market_code` | string | Operational-halt venue from `h`: Nasdaq `Q`, BX `B`, PSX `X`. |
| `operational_halt_action` | string | `h` action: halt `H` or resume `T`. |
| `market_category` | string | Original `R` market-category indicator. |
| `financial_status` | string | Original `R` financial-status indicator. |
| `round_lot_size` | uint32 | `R` shares per round lot. |
| `round_lots_only` | string | Original `R` round-lots-only flag. |
| `issue_classification` | string | Original `R` issue classification. |
| `issue_subtype` | string | Original two-byte `R` subtype, padding retained. |
| `authenticity` | string | Original `R` production/test flag. |
| `short_sale_threshold` | string | Original `R` short-sale threshold indicator. |
| `ipo_flag` | string | Original `R` IPO indicator. |
| `luld_tier` | string | Original `R` Limit Up/Limit Down price tier. |
| `etp_flag` | string | Original `R` exchange-traded-product indicator. |
| `etp_leverage` | uint32 | Original `R` leverage factor. |
| `inverse_indicator` | string | Original `R` inverse-product flag. |

All integer types are unsigned because the corresponding Nasdaq fields are
unsigned. `uint64` prevents precision loss for order IDs above 2^63 or 2^53;
never route these IDs through floating point.

## Required body fields by message type

Every row also has all five common header columns above. All body fields not
listed for that type must be null. There is no synthetic `SNAPSHOT` message.

| Type | Meaning | Required body fields |
|---|---|---|
| `S` | Global session event | `event_code` |
| `R` | Selected ticker's directory | All directory fields listed below |
| `H` | Trading action | `stock`, `trading_state`, `reserved`, `reason` |
| `h` | Operational halt | `stock`, `market_code`, `operational_halt_action` |
| `A` | Add displayed order | `order_id`, `side`, `shares`, `stock`, `price_units` |
| `F` | Add with attribution | All `A` fields plus `attribution` |
| `E` | Execute at resting price | `order_id`, `shares`, `match_id` |
| `C` | Execute with supplied price | `order_id`, `shares`, `match_id`, `printable`, `price_units` |
| `X` | Partial cancellation | `order_id`, `shares` |
| `D` | Full deletion | `order_id` |
| `U` | Cancel/replace | `order_id`, `new_order_id`, `shares`, `price_units` |
| `P` | Non-displayed trade | All `A` fields plus `match_id` |
| `Q` | Auction/cross trade | `shares`, `stock`, `price_units`, `match_id`, `cross_type` |
| `B` | Broken trade | `match_id` |

Directory fields are `stock`, `market_category`, `financial_status`,
`round_lot_size`, `round_lots_only`, `issue_classification`, `issue_subtype`,
`authenticity`, `short_sale_threshold`, `ipo_flag`, `luld_tier`, `etp_flag`,
`etp_leverage`, and `inverse_indicator`. All fields of the selected `R` message
are retained, even when a flag contains a space.

The quantity in `shares` means: newly added shares for `A/F`; executed shares
for `E/C/P`; withdrawn shares for `X`; the **new total** for `U`; cross volume
for `Q`. A `D` supplies no quantity: its removed shares come from later replay.
Likewise an `E` supplies no price or side, and a `U` supplies no side. Those
columns deliberately remain null.

The `P` side is historically always `B` regardless of the actual resting side
in this dataset's period; preserve the code but never use it to sign a trade.
The order reference in `P` is also a legacy field and does not identify a live
displayed order. Neither `P` nor `Q` updates the displayed order dictionary.
`B` invalidates a reported trade without rolling back today's displayed book.

## Session metadata

Parquet stores key/value metadata in its schema, outside event rows:

| Key | Meaning |
|---|---|
| `schema_version` | Contract version, currently `1.0.0`. |
| `ticker` | Selected ticker, currently `AAPL`. |
| `session_date` | ISO calendar date, supplied explicitly or inferred by the CLI from the filename. |
| `timezone` | `America/New_York`, not a fixed EST offset. |
| `price_scale` | `10000`. |
| `source_file` | Compressed input filename. |
| `source_bytes` | Compressed file size. |
| `source_sha256` | SHA-256 of compressed bytes, identifying the exact source. |
| `retained_message_types` | JSON list of retained codes. |

An ITCH time has no date or timezone offset. To obtain a calendar timestamp,
analysis must combine `session_date` with `timestamp_ns` using the
documented exchange timezone. We do not invent a UTC timestamp during storage.

The converter keeps equal timestamps in original sequence order and rejects a
backward timestamp among retained messages. Readers must preserve sequence;
sorting only by timestamp can scramble events with equal times.

## Scope and evolution

Known message types outside this scope (`Y/L/V/W/K/J/I/N`) and other stocks are
not written. Their counts appear in the report. Their framing and fixed lengths
are checked; their bodies and order lifecycles are not validated. Unknown codes
stop conversion, allowing explicit review of a different protocol revision.

No aggressor, provider/consumer classification, resting-side enrichment,
remaining quantity, or book snapshot is stored. (It is our job to define these, I tried to make them decoupled from the core event data). Changes to names, meanings, applicability,
or types require a schema-version change and corresponding reader support.

Reference: the repository's `NASDAQ_GUIDE_PDF/totalview-itch-5.0.pdf`, especially
sections 1.1, 1.2.1, 1.2.2, 1.3–1.5, and the official
[Nasdaq ITCH specification](https://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NQTVITCHspecification.pdf).

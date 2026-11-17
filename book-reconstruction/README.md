# Conversion guide

This folder turns an existing complete daily Nasdaq ITCH 5.0 `.gz` file into
validated Parquet. The name reserves room for book reconstruction, but the
current product is an **event history**, not a saved order book or strategy.

## Quick start

From the repository root:

```bash
uv sync --locked
uv run itch-convert
```

The default input is `data/raw/12302019.NASDAQ_ITCH50.gz`, the ticker is AAPL,
and the output is `data/processed/AAPL_2019-12-30.parquet`. Conversion covers the
entire daily file, including premarket, regular hours, and after-hours.
The command also prints a unique JSON report path in `data/processed/`.

To download, use `ubuntu_setup.sh`, `macos_setup.sh`, or `windows_setup.ps1`.
The command and terminal to use are written at the top of the new scripts.
These download data without installing Python dependencies or running conversion.

For another daily file or output directory:

```bash
uv run itch-convert \
  --source data/raw/12302019.NASDAQ_ITCH50.gz \
  --ticker AAPL \
  --output-dir data/processed \
  --batch-size 50000
```

For a filename without the Nasdaq `MMDDYYYY.NASDAQ_ITCH50.gz` pattern, also pass
`--session-date YYYY-MM-DD`. A conflicting standard filename date is rejected.
The default paths are anchored to the source checkout, not the working directory.
Paths explicitly supplied on the command line follow normal working-directory
rules. Invoke `uv` from the project or use its `--project /path/to/repository`
option from elsewhere.

The final output is never overwritten. A repeat run stops with `OUTPUT_EXISTS`
and a new diagnostic report. To compare runs, choose a different output directory.
The old scripts have been replaced rather than archived.

## What is Parquet?

It is a binary, typed, column-oriented table format. Unlike a CSV, a Parquet file
records column types, null values, and metadata. It is not a Python object or a
database server, and it cannot infer economic meaning for missing fields.
See the [Apache Parquet overview](https://parquet.apache.org/docs/overview/).

The writer uses PyArrow with Zstandard compression. A row group is a chunk of
rows written together. We buffer at most 50,000 retained rows by default and
write each batch as a row group. Sparse columns (null for most message types)
compress well. This avoids retaining the whole day's event table in RAM.
The replay validator also holds live orders plus sets of seen order and match
references; those sets grow with selected-ticker activity. Memory is not constant.
See [PyArrow ParquetWriter](https://arrow.apache.org/docs/python/generated/pyarrow.parquet.ParquetWriter.html).

For manual inspection, without implementing the analysis package yet:

```python
from pathlib import Path
import pyarrow.parquet as pq

path = Path("data/processed/AAPL_2019-12-30.parquet")
file = pq.ParquetFile(path)
print(file.metadata.num_rows)  # Reads the footer, not every event.
print(file.schema_arrow)  # Includes column types and dataset metadata.
batch = next(file.iter_batches(batch_size=5))
print(batch.to_pylist())  # Five dictionaries; Python None means null.
```

This example is for learning; the structured, schema-checking analysis reader
will be implemented later. Reading all rows is a separate choice from conversion.

## Loading, replay, and cancellations

Loading reads stored event rows. Replay applies rows to a dictionary of live
orders, using source sequence to establish the order of events. An add creates
an order; an execution or partial cancellation reduces its remaining shares;
a deletion removes it; a replacement removes the old ID and creates the new ID.

```text
ADD 123: SELL 100 @ $200      live state: 123 → SELL 100 @ $200
X   123: cancel 30           live state: 123 → SELL  70 @ $200
E   123: execute 20          live state: 123 → SELL  50 @ $200
D   123: delete              live state: empty
```

All four events remain in Parquet. The stored `D` has no supplied quantity;
replay can later determine that the deletion removed 50 shares. The live state
contains active orders; the event history retains the lifecycle of removed orders.
Adding supplies liquidity, executing consumes it through a trade, and cancelling
withdraws it without a trade. Future indicator definitions belong in analysis.

Start replay at the beginning of the full daily feed, including premarket. A
09:30-only event slice cannot reconstruct its opening state without earlier
events or a suitable snapshot. This data represents Nasdaq's displayed book;
it does not reveal hidden orders or other venues' order books. Unknown order
references stop validation instead of assuming yesterday's state.

## Checks and failure behavior

1. Check file existence, a positive batch size, and absence of an existing output.
2. Compute SHA-256 of the compressed source; record its size and identity.
3. Read gzip through EOF, allowing Python to verify its CRC/trailer. Check every
   BinaryFILE record's length, known message code, and expected payload size.
4. Require the source to start with `S/O`, discover AAPL through `R`, and retain
   its events plus global session markers. Record skipped-message counts.
5. Decode ASCII strictly and require each retained message's expected fields.
6. Check retained timestamps, source order, daily session phases, stock identity,
   sides, quantities, prices, and the supported status/printability flags.
7. Replay only the selected ticker: reject unknown orders, reused order IDs,
   excessive removals, invalid replacements, or invalid trade-break references.
   A non-printable execution still reduces order shares. A broken trade does
   not restore an order. Zero-volume cross messages are explicitly allowed.
8. Require all six `O/S/Q/M/E/C` session phases, in order, and no records after
   End of Messages. A zero-length BinaryFILE terminator is optional.
9. Close the temporary Parquet writer, recheck source size/modification time,
   and reopen the footer to compare schema and row count.
10. Persist a JSON report and publish the completed Parquet atomically without
    overwriting another file. Delete this run's temporary file on exit.

On failure the command exits with status 1, prints the diagnostic/report path,
and does not publish the new Parquet. Existing output is preserved. Reports
contain the first failing check, source context when available, counts, and run
times. If the disk/report directory itself cannot be written, the I/O error is
visible but a report cannot be guaranteed. A forced process kill or power loss
can leave a `.partial` file; it is never a validated final file.

These checks establish structural and selected-ticker replay consistency. They
cannot prove that the source contains every exchange message: a well-formed
omission can evade checks. The computed SHA-256 is an identity, not independent
verification against a Nasdaq-published checksum. Timestamp ordering is checked
on retained rows; other stocks' field semantics and timestamps are not audited.
This version requires an ordinary full daily session, not a mid-session capture
or an exceptional session with missing/different markers.

## Python API and return values

```python
from datetime import date
from pathlib import Path
from book_reconstruction.conversion import convert_itch_to_parquet
from common.enums import Ticker

report = convert_itch_to_parquet(
    source=Path("data/raw/12302019.NASDAQ_ITCH50.gz"),
    output_dir=Path("data/processed"),
    session_date=date(2019, 12, 30),
    ticker=Ticker.AAPL,
)
print(report.output_path)
print(report.rows_written)
```

The result is an `ExtractionReport`, not an in-memory event table. Its annotated
fields are defined in [models.py](../common/models.py). On failure, catch
`ConversionError` to inspect `diagnostic` and `report_path`. The programmatic API
treats `session_date` as authoritative; the CLI additionally checks standard
filenames for conflicting dates.

To support another stock, extend `Ticker` in `common/enums.py`. Selection and
directory discovery are generic; no numeric stock-locate is hardcoded. Multi-
ticker conversion in one pass is intentionally outside the current interface.

Continue with the [schema](../common/SCHEMA.md) and
[code walkthrough](../docs/CODE_WALKTHROUGH.md).

## Verified local run

The initial run on the existing December 30, 2019 download completed successfully:

| Result | Value |
|---|---|
| Compressed source size | 3,524,013,057 bytes, across all stocks |
| Source ITCH records scanned | 268,744,780 |
| Retained AAPL and global session rows | 1,519,367 |
| Output size | 23,255,583 bytes (about 23.3 MB) |
| Live AAPL orders at the end | 0 |
| Automated tests | 29 passed; Ruff and strict mypy checks passed |

The output is `data/processed/AAPL_2019-12-30.parquet`. Its adjacent unique JSON
report contains the source hash and per-message counts. An independent full
readback checked all 1,519,367 saved rows, the schema, header nullability,
per-message field applicability, source order, timestamps, and report counts.
This is a full-day dataset. The output represents AAPL only, while the compressed input
contains the entire exchange; their sizes are not a compression-ratio comparison.

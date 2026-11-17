# Reference AAPL dataset

Use `AAPL_2019-12-30.parquet` to start working with converted data when the raw
download or full conversion is unavailable. This is the complete retained AAPL
event history for the day, including global session messages; it is not a book
snapshot or a precomputed analysis result.

| Property | Value |
|---|---|
| Ticker | AAPL |
| Session date | December 30, 2019 |
| Exchange timezone | America/New_York |
| Schema version | 1.0.0 |
| Rows | 1,519,367 |
| File size | 23,255,583 bytes (23.26 MB) |
| Raw source filename | `12302019.NASDAQ_ITCH50.gz` |

SHA-256 of this **Parquet file**:

```text
2c93c9d258a079fcc2c19f2d3eba04609d1782b58260621631a277a7c0b20279
```

This is an exact copy of the successfully validated converter output. Before
bundling, all rows were read back, the shared schema/session metadata and event
ordering were checked, and the copy's checksum was compared with the original.
The embedded `source_sha256` identifies the compressed Nasdaq source; it differs
from the Parquet checksum above.

Use this path explicitly; do not silently fall back to it when another file
fails. There is no need to copy it into `data/processed/`. Keep this reference
unchanged and write generated outputs elsewhere. The analysis reader
must check the [shared schema](../../common/SCHEMA.md) whichever input is chosen.

After `uv sync --locked`, you can inspect it from the repository root:

```python
import pyarrow.parquet as pq

file = pq.ParquetFile("data/default/AAPL_2019-12-30.parquet")
print(file.metadata.num_rows)
print(next(file.iter_batches(batch_size=5)).to_pylist())
```

This uses PyArrow directly. The structured analysis reader and book replay are
not implemented yet. See the [conversion guide](../../book-reconstruction/README.md)
to generate your own dataset in `data/processed/`.

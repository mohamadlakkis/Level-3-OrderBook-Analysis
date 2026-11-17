# Reading the code, step by step

Read this alongside the source in the order below. Every function has parameter
and return annotations; docstrings explain behavior, and inline comments explain
the binary operations and publication rules. This guide explains the Python
constructs and the purpose of each block without assuming previous experience
with Parquet or binary protocols.

## 1. The project and environment

In `pyproject.toml`, `[project]` gives the package name, supported Python versions,
and runtime dependency (`pyarrow`). Its version range is a constraint;
`uv.lock` records the exact resolution. `[dependency-groups].dev` adds pytest,
Ruff, and mypy for development. They are not required by the converter itself.

`[project.scripts]` maps `itch-convert` to `book_reconstruction.cli:main`:
import that module and call its `main` function. `uv sync` installs this command
inside `.venv/bin/`. `uv run` uses that environment automatically.

`[build-system]` selects setuptools to install the local code. The explicit
`package-dir` mapping tells setuptools where to find the two importable packages.
The outer folder is `book-reconstruction`, but Python imports use the name
`book_reconstruction`. `analysis/` is reserved and contains no implementation.
The remaining tool sections configure tests, formatting, and strict annotation
checks. PyArrow has incomplete typing information, so its imports are exempted
from missing-stub errors; our own interfaces are still checked.

## 2. Python vocabulary used here

| Construct | Meaning in this project |
|---|---|
| `from __future__ import annotations` | Defer evaluation of type annotations, useful for forward references and version compatibility. |
| `def f(source: Path) -> Event` | `source` is expected to be a Path; the result is an Event. Hints are checked by mypy, not automatic runtime conversion. |
| `-> None` | The function changes state or writes something but returns no useful value. |
| `int \| str` | A value can be an integer or text. |
| `Path \| None` | A Path may be absent; no magic string represents absence. |
| `list[EventRow]` | An in-memory list of event-row dictionaries. |
| `dict[str, int]` | A mapping from text keys to integer values. |
| `@dataclass(frozen=True)` | Generate standard methods and disallow attribute reassignment. Nested dictionaries are not deeply immutable.(Lke in C++ when using const) |
| `class Ticker(str, Enum)` | Named choices with string values, such as `Ticker.AAPL.value == 'AAPL'`. |
| `self` | The current object, whose state persists between method calls. |
| `_name` | A convention for an internal helper, not a security restriction. |
| `with ... as stream` | Close a resource automatically on success or failure. |
| `yield` | Produce one result at a time, without a whole-file list. (Used in async functions) |
| `try / except / finally` | Perform work, handle failure, and clean up in either case. |
| `raise ... from exc` | Raise an informative error while retaining the original cause.(Then the latter exception is chained.) |
| `assert` in tests | State an expected result; pytest reports a failure if false. |

## 3. `common/enums.py` and `common/models.py`

`Ticker` limits this release to AAPL. The parser is generic; the enum makes the
supported interface explicit. `Side` documents original `B/S` codes with the
special legacy `P` caveat. `MessageType` gives readable names to retained wire
codes, without replacing the codes in storage.

`FieldValue = int | str` names supported decoded body values. `EventRow` maps
column names to supplied values. Inapplicable keys are absent; Arrow inserts
nulls according to the explicit schema.[IMPORTANT]

`Event` contains the five common columns plus a `body` dictionary. The parser
returns an Event; the validator consumes it without modifying it. `to_row()`
returns a flat dictionary. `**self.body` expands body entries into that
dictionary; it does not calculate missing prices, sides, or quantities. [Note: the ** is to unpack the dictionary into key value pairs, example: if body = {'a':1, 'b':2}, then **body will be equivalent to a=1, b=2]

`DatasetMetadata` carries source/session facts. `Diagnostic` gives stable error
codes and optional source context. `ValidationError` attaches this object to an
ordinary exception. `ExtractionReport` is the successful public return object:
paths and counts, with no loaded event table.

## 4. `common/schema.py`

`SCHEMA_VERSION`, `PRICE_SCALE`, `TIMEZONE`, and `NANOSECONDS_PER_DAY` name the
constants on which converter and readers must agree. Prices are integers and
timestamps are time-of-day nanoseconds, so there is no float precision loss.

`COLUMNS` is an ordered list of `(name, Arrow type, description)` tuples. An
Arrow type specifies the column representation. `uint16` is an unsigned 16-bit
integer; `uint64` represents all eight-byte ITCH references. `string` stores
decoded ASCII as text. Descriptions become field metadata inside the file.

`DIRECTORY_FIELDS` and `ADD_FIELDS` avoid repeating long field sequences.
`BODY_FIELDS` is the applicability contract: each message has exactly its listed
body fields. `(*ADD_FIELDS, 'attribution')` expands the add fields and appends
one field. These sequences also define wire decoding order.

`EVENT_SCHEMA` builds Arrow fields in column order. `enumerate` yields each
column's index and tuple. `nullable=index >= 5` makes only body columns nullable.
Table-level nullability does not override per-message requirements.

`schema_for_dataset()` returns a new schema with dataset metadata. ISO dates
avoid locale ambiguity. `json.dumps` serializes the retained-code list. The
dictionary comprehension encodes metadata keys and values as UTF-8 bytes, as
Arrow expects. No input row is changed. See [SCHEMA.md](../common/SCHEMA.md)
for every field and its applicability.

## 5. `parser.py`: frame the stream, then decode fields

`WIRE_LENGTHS` records supported ITCH 5.0 payload lengths, including the common
header. Known excluded types still get length checks. An unknown type fails
rather than using a guessed layout.

`BODY_STRUCTS` compiles binary layouts once. These `struct` symbols are used:

| Symbol | Meaning |
|---|---|
| `>` | Big-endian: most significant byte first, as Nasdaq specifies. |
| `Q` | Eight-byte unsigned integer. |
| `I` | Four-byte unsigned integer. |
| `c` | One byte of ASCII text. |
| `8s`, `4s`, `2s` | Fixed byte strings of that width. |

For example, `>QcI8sI` reads order reference, side, shares, symbol, and price.
`unpack_from(payload, 11)` starts after the eleven-byte common header.

`iter_messages(path)` opens gzip in binary mode and is a generator:

1. Read two bytes for the next message's length. Empty means EOF; one byte means
   truncation. Zero length is the optional BinaryFILE terminator.
2. Read exactly the announced payload. A shorter result is an error.
3. Obtain the code from its first byte and check the expected fixed length.
4. Yield record number and original payload. Conversion decides whether to
   decode and retain it. Filtering never renumbers source records.

Reading through EOF also triggers gzip's trailer and checksum checks.

`decode_message()` returns an Event. Python slices are end-exclusive: `[1:3]`
is the two-byte locate, `[3:5]` the tracking number, `[5:11]` the six-byte time.
`int.from_bytes(..., 'big')` decodes a number.

The body struct returns a tuple. `zip(..., strict=True)` pairs it with the
schema's field names and rejects inconsistent counts. Text uses strict ASCII;
replacing invalid bytes would hide damaged input. Only symbol padding is
trimmed; reason/status spaces are preserved. No inferred fields are added.

## 6. `validation.py`: internal replay

`_Order` is private validation state: resting side, price, remaining shares.
It is never added to saved event rows.

`ReplayValidator.__init__()` creates a live-order dictionary, seen-ID and match
sets, session-phase history, and last-event counters. Dictionaries provide
direct lookup by ID. Sets support membership checks and detect reused IDs or
repeated breaks. Their memory grows with selected-ticker activity.

`_fail()` raises a diagnostic with event context; its return type is `NoReturn`.
`_integer()` returns a required integer or fails. `_order()` returns a live
order or rejects a missing reference. `_new_id()` requires a positive reference
not previously used as a displayed order that day.

`accept(event)` checks structural/time invariants first. Fields must match the
schema. Time must be in the day; source positions strictly increase; retained
timestamps never decrease. Equal timestamps are allowed.

Global `S` messages require locate zero and ordered phases `OSQMEC`: start
messages, start system, start market, end market, end system, end messages.
The selected directory sets the daily locate. Later ticker messages must use
that locate, and supplied symbols must match the target.

The next checks reject invalid supplied codes, quantities, and prices. A zero-
volume `Q` is explicitly permitted by the protocol and is preserved.

| Branch | Internal replay action |
|---|---|
| `A/F` | Require a new reference; create an order with supplied side, price, shares. |
| `E/C/X` | Find the order; reject excessive removal; subtract shares; remove it at zero. `C`'s execution price does not change the resting limit. |
| `D` | Require a live order and remove it; no quantity is invented in storage. |
| `U` | Require the old order and new day-unique ID; replace state, carrying the old side internally. |
| `P/Q` | Track match references without changing the displayed book. |
| `B` | Require a known, not-yet-broken match; flag it without restoring book shares. |

Subtraction occurs only after checking removal bounds. No `max(..., 0)` hides
inconsistency. Dictionary `del` removes live state, never saved history.
`finish()` requires a directory and the full session markers. It does not
require the book to finish empty or claim to detect every missing message.

## 7. `conversion.py`: safely produce a file

`ConversionError` attaches the diagnostic and report path. `_sha256()` reads
one MiB at a time; `while block := ...` assigns each read result and ends at
an empty block. This hashes compressed source bytes without decompressing them.

`_write_json()` writes its own temporary sibling, flushes Python's buffer,
requests persistence with `fsync`, and uses `os.replace` to expose a complete
report. `finally` removes only its own temporary file if still present.

`convert_itch_to_parquet()` is the main public API:

1. Resolve paths, create the output directory, and give the report a unique
   UUID filename so attempts do not overwrite each other's diagnostics.
2. Initialize counters, report facts, and a fresh validator. `Counter` maps
   each message code to its count.
3. Reject invalid settings, missing input, or existing output. Read source stat
   information and hash; build the session-specific Arrow schema.
4. Create a unique `.partial` in the output directory, on the same filesystem
   as the final output. Close its initial handle so ParquetWriter owns it.
5. Open the writer with explicit schema/compression and iterate source records.
   Check boundaries even for records that would otherwise be excluded.
6. Discover the target's locate through directory symbol bytes. Retain that
   ticker's supported types and all global `S` messages.
7. Decode and validate an event; append its original fields to the batch. At
   the limit, create an Arrow table using the schema, write it, update counts,
   and clear the list. No complete daily table accumulates in RAM.
8. Count excluded messages without body decoding. Log progress every five
   million records without affecting their sequence.
9. At EOF, finish validation and flush the last batch. Closing the writer
   completes the Parquet footer.
10. Recheck source size/modification time. Reopen the Parquet footer to compare
    schema and row count. This is not a second replay or independent audit.
11. Write a validated report and use `os.link` to publish the complete file.
    A hard link gives the complete contents a final name atomically and fails
    if that name exists. Cleanup removes the temporary name; the final name
    keeps the file alive.
12. Return an ExtractionReport. On failure or user interrupt, record diagnostics,
    chain a ConversionError, and remove the owned temporary output.

Failure reports distinguish successfully written temporary batches from events
still buffered. A failed attempt does not invalidate an older output. Report
and publication are separate filesystem operations: require the final Parquet
path, not just a report. Forced termination can leave an unpublished `.partial`.

## 8. `cli.py` and `ubuntu_setup.sh`

`PROJECT_ROOT` walks upward from the module location so defaults do not depend
on the working directory. `_session_date()` parses a standard Nasdaq filename
with a regular expression or requires an explicit date. ITCH time alone cannot
tell us the date. `main()` parses arguments, configures logging, invokes the
API, prints successful paths, or exits nonzero. Bad arguments use argparse's
own visible error handling.

In the downloader, `set -euo pipefail` stops on command failures, undefined
variables, and failed pipelines. `BASH_SOURCE[0]` points to the script itself.
`dirname`, `cd`, and `pwd` locate its directory; quotes protect paths containing
spaces. `mkdir -p` creates missing folders and accepts existing ones. `wget -c`
resumes the compressed download; `-P` selects root `data/raw/`. No decompressed
copy is written to disk.

## 9. Tests and limits

Tests construct tiny binary sessions with known outcomes and exercise the public
converter. Actual Parquet round-trips check unsigned IDs, supplied text, nulls,
replacements, and cancellation history. Failure tests check that no new final
Parquet is published and the report explains the failure.

Runtime checks validate real sources; synthetic tests validate the code.
Neither proves absence of every well-formed omission in the original download.
No analysis reader, indicator, or public book-replay API is implemented yet.

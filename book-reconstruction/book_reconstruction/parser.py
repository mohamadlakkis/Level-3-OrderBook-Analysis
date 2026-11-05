"""Read BinaryFILE framing and decode selected ITCH 5.0 messages.

gzip decompresses a small stream buffer in memory; no uncompressed file is
created. Framing checks apply to every stock, while body decoding is performed
only for retained messages of the selected stock (plus global session markers).
"""

from __future__ import annotations

import gzip
import struct
from collections.abc import Iterator
from pathlib import Path

from common.enums import MessageType
from common.models import Diagnostic, Event, EventRow, ValidationError
from common.schema import BODY_FIELDS

# The protocol fixes message lengths, including the eleven-byte common header.
# Known out-of-scope messages are checked for framing and counted, not decoded.
# Unknown codes fail explicitly: another protocol revision needs an explicit review.
WIRE_LENGTHS = {
    "S": 12,
    "R": 39,
    "H": 25,
    "Y": 20,
    "L": 26,
    "V": 35,
    "W": 12,
    "K": 28,
    "J": 35,
    "h": 21,
    "A": 36,
    "F": 40,
    "E": 31,
    "C": 36,
    "X": 23,
    "D": 19,
    "U": 35,
    "P": 44,
    "Q": 40,
    "B": 19,
    "I": 50,
    "N": 20,
}

# '>' means big-endian, Q is uint64, I uint32, c one ASCII byte, and Ns N bytes.
# Each tuple produced by unpack is paired with BODY_FIELDS in exactly wire order.
BODY_STRUCTS = {
    "S": struct.Struct(">c"),
    "R": struct.Struct(">8sccIcc2scccccIc"),
    "H": struct.Struct(">8scc4s"),
    "h": struct.Struct(">8scc"),
    "A": struct.Struct(">QcI8sI"),
    "F": struct.Struct(">QcI8sI4s"),
    "E": struct.Struct(">QIQ"),
    "C": struct.Struct(">QIQcI"),
    "X": struct.Struct(">QI"),
    "D": struct.Struct(">Q"),
    "U": struct.Struct(">QQII"),
    "P": struct.Struct(">QcI8sIQ"),
    "Q": struct.Struct(">Q8sIQc"),
    "B": struct.Struct(">Q"),
}


def iter_messages(path: Path) -> Iterator[tuple[int, bytes]]:
    """Yield (one-based source record number, raw payload) from a gzip file.

    Raise ValidationError for incomplete framing, invalid lengths, unsupported
    codes, or bytes after the optional zero-length BinaryFILE terminator.
    gzip itself raises for CRC errors or an incomplete compressed stream.
    """
    with gzip.open(path, "rb") as stream:
        sequence = 0
        while True:
            prefix = stream.read(2)
            if not prefix:
                return  # Clean EOF; the session validator still requires S/C.
            sequence += 1
            if len(prefix) != 2:
                raise ValidationError(
                    Diagnostic(
                        "TRUNCATED_LENGTH",
                        "Expected two length bytes.",
                        sequence,
                    )
                )
            length = int.from_bytes(prefix, "big")
            if length == 0:
                # Consume EOF too, so gzip verifies its checksum/trailer.
                if stream.read(1):
                    raise ValidationError(
                        Diagnostic(
                            "TRAILING_DATA",
                            "Bytes follow the BinaryFILE terminator.",
                            sequence,
                        )
                    )
                return
            payload = stream.read(length)
            if len(payload) != length:
                raise ValidationError(
                    Diagnostic(
                        "TRUNCATED_MESSAGE",
                        f"Expected {length} bytes, got {len(payload)}.",
                        sequence,
                    )
                )
            code = chr(payload[0])
            expected = WIRE_LENGTHS.get(code)
            if expected is None:
                raise ValidationError(
                    Diagnostic(
                        "UNKNOWN_MESSAGE_TYPE",
                        f"Unsupported ITCH code {code!r}.",
                        sequence,
                        code,
                    )
                )
            if length != expected:
                raise ValidationError(
                    Diagnostic(
                        "INVALID_MESSAGE_LENGTH",
                        f"{code} needs {expected} bytes, got {length}.",
                        sequence,
                        code,
                    )
                )
            yield sequence, payload


def decode_message(sequence: int, payload: bytes) -> Event:
    """Return a retained wire message as an Event, without inferred fields.

    Fixed-width text is preserved except the right-padding of stock symbols.
    Input normally comes from iter_messages; direct callers get length checks too.
    """
    code = chr(payload[0]) if payload else ""
    if code not in BODY_STRUCTS or len(payload) != WIRE_LENGTHS.get(code):
        raise ValidationError(
            Diagnostic(
                "INVALID_RETAINED_MESSAGE",
                "Unsupported code or incorrect message length.",
                sequence,
                code,
            )
        )
    timestamp = int.from_bytes(payload[5:11], "big")
    body: EventRow = {}
    try:
        values = BODY_STRUCTS[code].unpack_from(payload, 11)
        for name, value in zip(BODY_FIELDS[code], values, strict=True):
            if isinstance(value, bytes):
                text = value.decode("ascii")  # Strict: never replace corrupt bytes silently.
                body[name] = text.rstrip(" ") if name == "stock" else text
            else:
                body[name] = value
    except (UnicodeDecodeError, struct.error, ValueError) as exc:
        raise ValidationError(
            Diagnostic(
                "INVALID_BODY",
                str(exc),
                sequence,
                code,
                timestamp,
            )
        ) from exc
    return Event(
        sequence=sequence,
        timestamp_ns=timestamp,
        message_type=MessageType(code),
        stock_locate=int.from_bytes(payload[1:3], "big"),
        tracking_number=int.from_bytes(payload[3:5], "big"),
        body=body,
    )

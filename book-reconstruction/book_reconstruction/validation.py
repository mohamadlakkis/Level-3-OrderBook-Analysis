"""Replay retained messages only to check data integrity, never to enrich output.

The private order dictionary is current state, not a saved historical snapshot.
All source events, including cancelled/deleted orders, remain in the Parquet log.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from common.enums import Ticker
from common.models import Diagnostic, Event, ValidationError
from common.schema import BODY_FIELDS, NANOSECONDS_PER_DAY


@dataclass(frozen=True)
class _Order:
    """Private replay state; deliberately never serialized into event rows."""

    side: str
    price_units: int
    remaining: int


class ReplayValidator:
    """Validate one complete ticker/day stream in its original record order."""

    def __init__(self, ticker: Ticker) -> None:
        """Create empty session and order state; return None."""
        self.ticker = ticker
        self.orders: dict[int, _Order] = {}
        self.seen_order_ids: set[int] = set()
        self.matches: set[int] = set()
        self.broken_matches: set[int] = set()
        self.session_codes: list[str] = []
        self.last_sequence = 0
        self.last_timestamp = 0
        self.last_event: Event | None = None
        self.locate: int | None = None

    def _fail(self, event: Event, code: str, message: str) -> NoReturn:
        """Raise a contextual ValidationError; this function never returns."""
        oid = event.body.get("order_id")
        raise ValidationError(
            Diagnostic(
                code,
                message,
                event.sequence,
                event.message_type.value,
                event.timestamp_ns,
                oid if isinstance(oid, int) else None,
            )
        )

    def _integer(self, event: Event, field: str) -> int:
        """Return a required integer body field or raise a diagnostic error."""
        value = event.body.get(field)
        if not isinstance(value, int):
            self._fail(event, "INVALID_FIELD", f"{field} must be an integer.")
        return value

    def _order(self, event: Event, oid: int) -> _Order:
        """Return an existing live order; unknown/previously removed orders fail."""
        old = self.orders.get(oid)
        if old is None:
            self._fail(event, "UNKNOWN_ORDER", f"Order {oid} is not in the live book.")
        return old

    def _new_id(self, event: Event, oid: int) -> None:
        """Require a positive, day-unique displayed order reference; return None."""
        if oid <= 0 or oid in self.seen_order_ids:
            self._fail(event, "DUPLICATE_OR_INVALID_ORDER", f"Invalid/reused order ID {oid}.")
        self.seen_order_ids.add(oid)

    def accept(self, event: Event) -> None:
        """Validate and apply one retained event internally; return None.

        Equal timestamps are valid; source sequence establishes event order.
        P/Q/B never modify the displayed book. B invalidates a trade record,
        without restoring shares to the current order state.
        """
        code, body = event.message_type.value, event.body
        if set(body) != set(BODY_FIELDS[code]):
            self._fail(event, "INVALID_FIELDS", "Body fields do not match the stored schema.")
        if not 0 <= event.timestamp_ns < NANOSECONDS_PER_DAY:
            self._fail(event, "INVALID_TIMESTAMP", "Timestamp is outside the session day.")
        if event.sequence <= self.last_sequence:
            self._fail(event, "INVALID_SEQUENCE", "Source positions must strictly increase.")
        if event.timestamp_ns < self.last_timestamp:
            self._fail(event, "BACKWARD_TIMESTAMP", "Retained timestamps went backwards.")
        if self.session_codes and self.session_codes[-1] == "C":
            self._fail(event, "AFTER_SESSION_END", "A retained message follows End of Messages.")
        if not self.session_codes and (code != "S" or body["event_code"] != "O"):
            self._fail(event, "MISSING_SESSION_START", "First record must be S with event code O.")

        self.last_sequence, self.last_timestamp = event.sequence, event.timestamp_ns
        self.last_event = event
        if code == "S":
            if event.stock_locate != 0:
                self._fail(event, "INVALID_LOCATE", "System events require stock_locate=0.")
            expected = "OSQMEC"
            phase = str(body["event_code"])
            if (
                len(self.session_codes) >= len(expected)
                or phase != expected[len(self.session_codes)]
            ):
                self._fail(event, "INVALID_SESSION_PHASE", f"Unexpected session phase {phase!r}.")
            self.session_codes.append(phase)
            return

        if "stock" in body and body["stock"] != self.ticker.value:
            self._fail(event, "SYMBOL_MISMATCH", "Stock field disagrees with selected ticker.")
        if code == "R":
            if self.locate is not None or event.stock_locate == 0:
                self._fail(event, "INVALID_DIRECTORY", "Duplicate directory or zero stock locate.")
            self.locate = event.stock_locate
            return
        if self.locate is None or event.stock_locate != self.locate:
            self._fail(event, "INVALID_LOCATE", "Missing directory or inconsistent stock locate.")
        if "side" in body and body["side"] not in ("B", "S"):
            self._fail(event, "INVALID_SIDE", "Supplied side must be B or S.")
        if "shares" in body:
            shares = self._integer(event, "shares")
            # Q may explicitly report zero volume when auction interest is insufficient.
            if shares < 0 or (shares == 0 and code != "Q"):
                self._fail(
                    event, "INVALID_SHARES", "Quantity must be positive, except zero-volume Q."
                )
        if "price_units" in body:
            price = self._integer(event, "price_units")
            if not 0 <= price <= 2_000_000_000 or (price == 0 and body.get("shares") != 0):
                self._fail(
                    event, "INVALID_PRICE", "Price is outside the supported ITCH Price(4) range."
                )
        if code == "C" and body["printable"] not in ("Y", "N"):
            self._fail(event, "INVALID_PRINTABLE", "C printable flag must be Y or N.")
        if code == "Q" and body["cross_type"] not in ("O", "C", "H", "I"):
            self._fail(event, "INVALID_CROSS_TYPE", "Unrecognized cross type.")
        if code == "H" and body["trading_state"] not in ("H", "P", "Q", "T"):
            self._fail(event, "INVALID_TRADING_STATE", "Unrecognized trading state.")
        if code == "h" and (
            body["market_code"] not in ("Q", "B", "X")
            or body["operational_halt_action"] not in ("H", "T")
        ):
            self._fail(event, "INVALID_HALT", "Unrecognized operational halt code.")

        if code in ("A", "F"):
            oid = self._integer(event, "order_id")
            self._new_id(event, oid)
            self.orders[oid] = _Order(
                str(body["side"]),
                self._integer(event, "price_units"),
                self._integer(event, "shares"),
            )
        elif code in ("E", "C", "X"):
            oid = self._integer(event, "order_id")
            old = self._order(event, oid)
            removed = self._integer(event, "shares")
            if removed > old.remaining:
                self._fail(
                    event, "EXCESS_REMOVAL", f"Removing {removed} from {old.remaining} shares."
                )
            remaining = old.remaining - removed  # Never clamp an inconsistent quantity to zero.
            if remaining:
                self.orders[oid] = _Order(old.side, old.price_units, remaining)
            else:
                del self.orders[oid]
        elif code == "D":
            oid = self._integer(event, "order_id")
            self._order(event, oid)
            del self.orders[oid]
        elif code == "U":
            oid = self._integer(event, "order_id")
            old = self._order(event, oid)
            new_id = self._integer(event, "new_order_id")
            self._new_id(event, new_id)
            del self.orders[oid]
            self.orders[new_id] = _Order(
                old.side,
                self._integer(event, "price_units"),
                self._integer(event, "shares"),
            )

        if code in ("E", "C", "P", "Q"):
            self.matches.add(self._integer(event, "match_id"))
        elif code == "B":
            match = self._integer(event, "match_id")
            if match not in self.matches or match in self.broken_matches:
                self._fail(event, "INVALID_TRADE_BREAK", f"Unknown/already broken match {match}.")
            self.broken_matches.add(match)

    def finish(self) -> None:
        """Require a directory and all daily session markers after clean EOF; return None."""
        if self.locate is None:
            raise ValidationError(
                Diagnostic(
                    "TICKER_NOT_FOUND",
                    f"No directory message found for {self.ticker.value}.",
                )
            )
        if "".join(self.session_codes) != "OSQMEC":
            raise ValidationError(
                Diagnostic(
                    "INCOMPLETE_SESSION",
                    "Expected the complete O/S/Q/M/E/C session marker sequence.",
                    self.last_sequence,
                )
            )

"""Nasdaq codes used by the stored schema, without derived trading classifications."""

from enum import Enum


class Ticker(str, Enum):
    """Supported conversion targets; extend this enum to enable another ticker."""

    AAPL = "AAPL"


class Side(str, Enum):
    """The supplied ITCH B/S code, not an inferred aggressor side.

    P messages have a legacy B value which does not identify the resting side.
    """

    BUY = "B"
    SELL = "S"


class MessageType(str, Enum):
    """Retained ITCH message types; enum values are the original wire codes."""

    SYSTEM_EVENT = "S"
    STOCK_DIRECTORY = "R"
    TRADING_ACTION = "H"
    OPERATIONAL_HALT = "h"
    ADD = "A"
    ADD_ATTRIBUTED = "F"
    EXECUTION = "E"
    EXECUTION_WITH_PRICE = "C"
    CANCEL = "X"
    DELETE = "D"
    REPLACE = "U"
    TRADE = "P"
    CROSS = "Q"
    BROKEN_TRADE = "B"

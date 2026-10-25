#!/usr/bin/env python3
"""Inspect one Nasdaq TotalView-ITCH 5.0 BinaryFILE (.gz) without decompressing it to disk.

Displays order lifecycle events for one Nasdaq symbol. All other ITCH messages
are skipped, but the instrument directory and existing orders are reconstructed
as the input stream is consumed. Output is a compact CSV for inspection only;
not a complete research-grade LPI/LCI implementation.
"""
import argparse
import csv
import gzip
import struct
import sys

FIELDS = ('sequence', 'time', 'type', 'event', 'order_id', 'side',
          'quantity', 'price', 'remaining_quantity', 'aggressor', 'notes')
NANO = 1_000_000_000
OPEN = 9 * 3600 + 30 * 60
CLOSE = 16 * 3600


def time_fmt(ns):
    seconds, nano = divmod(ns, NANO)
    h, sec = divmod(seconds, 3600)
    m, s = divmod(sec, 60)
    return f'{h:02d}:{m:02d}:{s:02d}.{nano:09d}'


def read_exact(f, n):
    b = f.read(n)
    if len(b) != n:
        raise ValueError(f'Unexpected EOF while reading {n} bytes (got {len(b)}).')
    return b


def messages(path):
    # Official Nasdaq BinaryFILE protocol: 2-byte big-endian record length,
    # followed by a raw ITCH 5.0 message (whose first byte is message type).
    with gzip.open(path, 'rb') as f:
        seq = 0
        while True:
            prefix = f.read(2)
            if not prefix:
                return  # Some sample files omit the optional terminator.
            if len(prefix) != 2:
                raise ValueError('Truncated two-byte message length.')
            n = struct.unpack('>H', prefix)[0]
            if n == 0:
                return
            payload = read_exact(f, n)
            seq += 1
            yield seq, payload


def price_str(encoded):
    return f'{encoded / 10_000:.4f}' if encoded is not None else ''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('file', help='Downloaded .gz Nasdaq ITCH 5.0 file')
    parser.add_argument('--symbol', default='AAPL', help='Ticker to inspect (default AAPL)')
    parser.add_argument('--limit', type=int, default=30, help='Maximum displayed events')
    parser.add_argument('--regular-hours', action='store_true', help='Only display 09:30–16:00 ET events (still process premarket book state)')
    parser.add_argument('--output', default=None, help='Save CSV to this path, otherwise print to terminal')
    args = parser.parse_args()
    symbol = args.symbol.upper()
    locate = None
    # Live order state ONLY for target instrument, not for the entire exchange.
    # Map from order reference number to (resting side, integer price, remaining shares)
    orders = {}
    printed = 0
    seen = 0
    out = open(args.output, 'w', newline='', encoding='utf-8') if args.output else sys.stdout
    try:
        writer = csv.writer(out)
        writer.writerow(FIELDS)
        for sequence, p in messages(args.file):
            if len(p) < 11:
                raise ValueError(f'Short ITCH payload at record {sequence}')
            ty = chr(p[0])
            code = int.from_bytes(p[1:3], 'big')
            if ty == 'R':
                name = p[11:19].decode('ascii', errors='replace').strip()
                if name == symbol:
                    locate = code
                    print(f'# Found {symbol}: stock_locate={locate}', file=sys.stderr)
                continue
            if locate is None or code != locate or ty not in 'AFECXDUP':
                continue
            seen += 1
            ns = int.from_bytes(p[5:11], 'big')
            rid, side, qty, price, remaining, aggressor, notes = '', '', '', None, '', '', ''
            event = ''
            if ty in ('A', 'F'):
                oid, raw_side, qty, name, price = struct.unpack_from('>QcI8sI', p, 11)
                side = raw_side.decode('ascii')
                orders[oid] = (side, price, qty)
                rid, remaining = oid, qty
                event = 'ADD'
            elif ty in ('E', 'C'):
                if ty == 'E':
                    oid, qty, match = struct.unpack_from('>QIQ', p, 11)
                else:
                    oid, qty, match, printable, px = struct.unpack_from('>QIQcI', p, 11)
                rid = oid
                old = orders.get(oid)
                event = 'EXECUTION'
                if old:
                    side, resting_price, oldqty = old
                    price = resting_price if ty == 'E' else px
                    aggressor = 'BUY' if side == 'S' else 'SELL'
                    remaining = max(oldqty - qty, 0)
                    if remaining == 0:
                        del orders[oid]
                    else:
                        orders[oid] = (side, resting_price, remaining)
                else:
                    notes = 'Unknown resting order: cannot sign execution'
                if ty == 'C' and printable == b'N':
                    notes = (notes + '; ' if notes else '') + 'non-printable execution'
            elif ty == 'X':
                oid, qty = struct.unpack_from('>QI', p, 11)
                rid, event = oid, 'PARTIAL_CANCEL'
                old = orders.get(oid)
                if old:
                    side, price, oldqty = old
                    remaining = max(oldqty - qty, 0)
                    if remaining == 0:
                        del orders[oid]
                    else:
                        orders[oid] = (side, price, remaining)
                else:
                    notes = 'Unknown resting order'
            elif ty == 'D':
                (oid,) = struct.unpack_from('>Q', p, 11)
                rid, event = oid, 'DELETE'
                old = orders.pop(oid, None)
                if old:
                    side, price, qty = old
                    remaining = 0
                else:
                    notes = 'Unknown resting order: cancel quantity unavailable'
            elif ty == 'U':
                old_id, new_id, new_qty, new_price = struct.unpack_from('>QQII', p, 11)
                old = orders.pop(old_id, None)
                rid, event = f'{old_id}->{new_id}', 'REPLACE'
                qty, price, remaining = new_qty, new_price, new_qty
                if old:
                    side, old_price, old_qty = old
                    orders[new_id] = (side, new_price, new_qty)
                    notes = f'remove old {old_qty} shares at {price_str(old_price)}, add new {new_qty} shares at {price_str(new_price)}'
                else:
                    notes = 'Unknown old order: replacement side unavailable'
            else:  # P: non-displayed trade (not book-state update)
                oid, raw_side, qty, name, price, match = struct.unpack_from('>QcI8sIQ', p, 11)
                rid, event = oid, 'NONDISPLAYED_TRADE'
                side = raw_side.decode('ascii')
                notes = 'Trade side is not a reliable aggressor sign; excluded from signed LCI'
            sec = ns // NANO
            if args.regular_hours and not (OPEN <= sec < CLOSE):
                continue
            writer.writerow((sequence, time_fmt(ns), ty, event, rid, side,
                             qty, price_str(price), remaining, aggressor, notes))
            printed += 1
            if printed >= args.limit:
                break
        if locate is None:
            print(f'ERROR: {symbol} was not found in stock-directory messages.', file=sys.stderr)
            sys.exit(2)
        print(f'# Displayed {printed} {symbol} events, processed {seen} target-stock messages.', file=sys.stderr)
    finally:
        if args.output:
            out.close()


if __name__ == '__main__':
    main()

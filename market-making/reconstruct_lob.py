import os
import time
import numpy as np
import pandas as pd


class LimitOrderBook:
    """
    Maintains the state of a Level-3 Limit Order Book (LOB) from raw ITCH market events.
    Supports O(1) order lookups and updates, with price-level volume aggregation.
    """
    def __init__(self):
        # Order repository: order_ref -> (side, price, remaining_shares)
        self.orders = {}
        # Aggregated price ladders: price -> total_volume at this price level
        self.bids = {}
        self.asks = {}

    def apply_event(self, msg_type: str, order_ref: int, side: str, price: float, shares: int):
        """
        Updates the internal order book state based on the ITCH event type.
        """
        # 1. Add Order (A, F, or initial SNAPSHOT)
        if msg_type in ('A', 'F', 'SNAPSHOT'):
            if order_ref and side in ('B', 'S') and price is not None and shares is not None:
                # If order_ref was already present in the book, cleanly replace it
                if order_ref in self.orders:
                    self._remove_order(order_ref)
                
                self.orders[order_ref] = (side, price, shares)
                if side == 'B':
                    self.bids[price] = self.bids.get(price, 0) + shares
                else:
                    self.asks[price] = self.asks.get(price, 0) + shares

        # 2. Order Execution (E or C)
        elif msg_type in ('E', 'C'):
            if order_ref in self.orders:
                ord_side, ord_price, current_shares = self.orders[order_ref]
                rem_shares = current_shares - shares
                
                # Update price level volume
                if ord_side == 'B':
                    new_vol = self.bids.get(ord_price, 0) - shares
                    if new_vol <= 0:
                        self.bids.pop(ord_price, None)
                    else:
                        self.bids[ord_price] = new_vol
                else:
                    new_vol = self.asks.get(ord_price, 0) - shares
                    if new_vol <= 0:
                        self.asks.pop(ord_price, None)
                    else:
                        self.asks[ord_price] = new_vol
                
                # Update or delete individual order
                if rem_shares <= 0:
                    del self.orders[order_ref]
                else:
                    self.orders[order_ref] = (ord_side, ord_price, rem_shares)

        # 3. Partial Order Cancel (X)
        elif msg_type == 'X':
            if order_ref in self.orders:
                ord_side, ord_price, current_shares = self.orders[order_ref]
                rem_shares = current_shares - shares
                
                if ord_side == 'B':
                    new_vol = self.bids.get(ord_price, 0) - shares
                    if new_vol <= 0:
                        self.bids.pop(ord_price, None)
                    else:
                        self.bids[ord_price] = new_vol
                else:
                    new_vol = self.asks.get(ord_price, 0) - shares
                    if new_vol <= 0:
                        self.asks.pop(ord_price, None)
                    else:
                        self.asks[ord_price] = new_vol
                        
                if rem_shares <= 0:
                    del self.orders[order_ref]
                else:
                    self.orders[order_ref] = (ord_side, ord_price, rem_shares)

        # 4. Full Order Delete (D)
        elif msg_type == 'D':
            if order_ref in self.orders:
                self._remove_order(order_ref)

        # 5. Order Replace (U)
        elif msg_type == 'U':
            if order_ref and side in ('B', 'S') and price is not None and shares is not None:
                if order_ref in self.orders:
                    self._remove_order(order_ref)
                self.orders[order_ref] = (side, price, shares)
                if side == 'B':
                    self.bids[price] = self.bids.get(price, 0) + shares
                else:
                    self.asks[price] = self.asks.get(price, 0) + shares

        # 6. Cross Trade (Q)
        # Auction transactions occur outside continuous book; no direct resting book modification.
        elif msg_type == 'Q':
            pass

    def _remove_order(self, order_ref: int):
        """Helper to cleanly remove an order and decrement its price ladder."""
        old = self.orders.pop(order_ref, None)
        if old is None:
            return
        side, price, shares = old
        if side == 'B':
            new_vol = self.bids.get(price, 0) - shares
            if new_vol <= 0:
                self.bids.pop(price, None)
            else:
                self.bids[price] = new_vol
        else:
            new_vol = self.asks.get(price, 0) - shares
            if new_vol <= 0:
                self.asks.pop(price, None)
            else:
                self.asks[price] = new_vol

    def get_snapshot_metrics(self, top_n: int = 5) -> dict:
        """
        Extracts BBO, spread, mid-price, micro-price, depth, and top-N levels from the current book state.
        Ensures the book remains uncrossed (best_bid < best_ask) in continuous trading.
        """
        # Resolve any crossed quotes from auction matches or orphaned replacement orders
        while self.bids and self.asks and max(self.bids.keys()) >= min(self.asks.keys()):
            crossed_bid = max(self.bids.keys())
            orders_to_remove = [oid for oid, (s, p, _) in self.orders.items() if s == 'B' and p == crossed_bid]
            if not orders_to_remove:
                self.bids.pop(crossed_bid, None)
            else:
                for oid in orders_to_remove:
                    self._remove_order(oid)

        best_bid = max(self.bids.keys()) if self.bids else None
        best_ask = min(self.asks.keys()) if self.asks else None
        
        bid_size_l1 = self.bids[best_bid] if best_bid is not None else 0
        ask_size_l1 = self.asks[best_ask] if best_ask is not None else 0
        
        if best_bid is not None and best_ask is not None:
            mid_price = (best_bid + best_ask) / 2.0
            spread = best_ask - best_bid
            # Order book imbalance and volume-weighted micro-price
            total_l1_vol = bid_size_l1 + ask_size_l1
            if total_l1_vol > 0:
                micro_price = (bid_size_l1 * best_ask + ask_size_l1 * best_bid) / total_l1_vol
                imbalance = (bid_size_l1 - ask_size_l1) / total_l1_vol
            else:
                micro_price = mid_price
                imbalance = 0.0
        else:
            mid_price = None
            spread = None
            micro_price = None
            imbalance = None

        row = {
            'best_bid': best_bid,
            'best_ask': best_ask,
            'mid_price': mid_price,
            'spread': spread,
            'micro_price': micro_price,
            'imbalance_l1': imbalance,
            'bid_size_l1': bid_size_l1,
            'ask_size_l1': ask_size_l1,
            'total_bid_depth': sum(self.bids.values()),
            'total_ask_depth': sum(self.asks.values()),
            'bid_levels_count': len(self.bids),
            'ask_levels_count': len(self.asks)
        }

        # Top-N price and volume levels for depth structure analysis
        sorted_bids = sorted(self.bids.keys(), reverse=True)[:top_n]
        sorted_asks = sorted(self.asks.keys())[:top_n]

        for i in range(1, top_n + 1):
            if i <= len(sorted_bids):
                p = sorted_bids[i - 1]
                row[f'bid_p{i}'] = p
                row[f'bid_v{i}'] = self.bids[p]
            else:
                row[f'bid_p{i}'] = None
                row[f'bid_v{i}'] = 0

            if i <= len(sorted_asks):
                p = sorted_asks[i - 1]
                row[f'ask_p{i}'] = p
                row[f'ask_v{i}'] = self.asks[p]
            else:
                row[f'ask_p{i}'] = None
                row[f'ask_v{i}'] = 0

        return row


def reconstruct_lob_snapshots(
    input_path: str = "market-making/data/processed/AAPL_market_open_cleaned.parquet",
    output_path: str = "market-making/data/processed/AAPL_snapshots.parquet",
    interval_ms: int = 100,
    top_n_levels: int = 5
) -> pd.DataFrame:
    """
    Reconstructs the Limit Order Book (LOB) state iteratively from event-by-event ITCH data,
    and samples periodic snapshots at a fixed time grid (default: 100 milliseconds).
    
    Parameters:
    -----------
    input_path : str
        Path to the cleaned market events Parquet file (e.g. AAPL_market_open_cleaned.parquet).
    output_path : str
        Target destination path for the periodic snapshots Parquet file.
    interval_ms : int
        Sampling interval in milliseconds (default: 100ms).
    top_n_levels : int
        Number of depth price levels to record on each side (default: 5).
        
    Returns:
    --------
    pd.DataFrame:
        DataFrame containing the periodic order book snapshots.
    """
    start_time = time.time()
    print(f"Loading cleaned market data for LOB reconstruction: {input_path}")
    
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Source file not found: {input_path}")
        
    df = pd.read_parquet(input_path)
    if df.empty:
        print("Warning: Input dataset is empty. Aborting reconstruction.")
        return pd.DataFrame()
        
    # Ensure chronological order
    if not df['timestamp'].is_monotonic_increasing:
        print("Sorting dataset by timestamp for sequential processing...")
        df = df.sort_values(by='timestamp').reset_index(drop=True)
        
    # Infer base calendar date from input dataset
    if 'real_timestamp' in df.columns and pd.api.types.is_datetime64_any_dtype(df['real_timestamp']):
        base_date = pd.to_datetime(df['real_timestamp'].iloc[0]).normalize()
    else:
        base_date = pd.to_datetime("2019-12-30")
        
    interval_ns = int(interval_ms * 1_000_000)
    first_ts = int(df['timestamp'].iloc[0])
    last_ts = int(df['timestamp'].iloc[-1])
    
    # Align the first snapshot time to the sampling grid
    current_snapshot_time = (first_ts // interval_ns) * interval_ns
    
    lob = LimitOrderBook()
    snapshots = []
    
    # Pre-extract columns as NumPy arrays for ultra-fast iteration
    timestamps = df['timestamp'].to_numpy()
    msg_types = df['msg_type'].to_numpy()
    order_refs = df['order_ref'].to_numpy()
    sides = df['side'].to_numpy()
    shares_arr = df['shares'].to_numpy()
    prices = df['price'].to_numpy()
    
    total_events = len(df)
    print(f"Reconstructing LOB from {total_events:,} events (grid interval: {interval_ms} ms)...")
    
    for event_ts, msg_type, oid, side, shares, price in zip(timestamps, msg_types, order_refs, sides, shares_arr, prices):
        # Capture snapshot when event time crosses the current target
        while event_ts > current_snapshot_time:
            metrics = lob.get_snapshot_metrics(top_n=top_n_levels)
            metrics['timestamp'] = current_snapshot_time
            snapshots.append(metrics)
            current_snapshot_time += interval_ns
            
        # Update LOB state
        lob.apply_event(msg_type, oid, side, price, shares)
        
    # Flush remaining snapshots up to the end of the observation window
    while current_snapshot_time <= last_ts:
        metrics = lob.get_snapshot_metrics(top_n=top_n_levels)
        metrics['timestamp'] = current_snapshot_time
        snapshots.append(metrics)
        current_snapshot_time += interval_ns
        
    snap_df = pd.DataFrame(snapshots)
    
    # Rebuild real_timestamp from base date and nanosecond offset
    snap_df['real_timestamp'] = base_date + pd.to_timedelta(snap_df['timestamp'], unit='ns')
    
    # Place real_timestamp as first column
    cols = ['real_timestamp'] + [c for c in snap_df.columns if c != 'real_timestamp']
    snap_df = snap_df[cols]
    
    # Ensure destination directory exists and write Parquet
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    snap_df.to_parquet(output_path, index=False)
    
    elapsed = time.time() - start_time
    valid_bbo = snap_df['spread'].notna().sum()
    pct_bbo = (valid_bbo / len(snap_df)) * 100 if len(snap_df) > 0 else 0
    avg_spread = snap_df['spread'].mean()
    
    print("\n--- LOB RECONSTRUCTION & SNAPSHOT REPORT ---")
    print(f"Total events processed : {total_events:,}")
    print(f"Snapshots generated    : {len(snap_df):,} (every {interval_ms} ms)")
    print(f"Observation window     : {snap_df['real_timestamp'].min()} -> {snap_df['real_timestamp'].max()}")
    print(f"Valid BBO coverage     : {valid_bbo:,} / {len(snap_df):,} ({pct_bbo:.1f}%)")
    if pd.notna(avg_spread):
        print(f"Average Bid-Ask Spread : ${avg_spread:.4f}")
    print(f"Output saved to        : {output_path}")
    print(f"Processing time        : {elapsed:.2f} seconds")
    print("--------------------------------------------\n")
    
    return snap_df


if __name__ == "__main__":
    reconstruct_lob_snapshots(
        input_path="market-making/data/processed/AAPL_market_open_cleaned.parquet",
        output_path="market-making/data/processed/AAPL_snapshots.parquet",
        interval_ms=100
    )

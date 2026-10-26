import gzip
import os
import struct
import time
import pandas as pd

def extract_aapl_market_open(start_hour=9.5, end_hour=10.0):
    input_file = "market-making/data/raw/12302019.NASDAQ_ITCH50.gz"
    output_file = "market-making/data/processed/AAPL_market_open.parquet"
    
    # Convert hours (EST) to nanoseconds since midnight
    START_TIME = int(start_hour * 3600 * 1_000_000_000)
    END_TIME = int(end_hour * 3600 * 1_000_000_000)
    
    # Track live AAPL orders state: order_ref -> (side, price, remaining_shares)
    orders = {}
    records = []
    aapl_locate = None
    snapshot_taken = False
    
    print("Starting .gz file reading process...")
    start_process = time.time()
    
    with gzip.open(input_file, 'rb') as f:
        while True:
            # Read the 2 bytes indicating message length (BinaryFILE protocol)
            length_bytes = f.read(2)
            if not length_bytes:
                break
            
            msg_length = struct.unpack('>H', length_bytes)[0]
            if msg_length == 0:
                break
                
            msg_data = f.read(msg_length)
            if len(msg_data) != msg_length:
                break
                
            msg_type = chr(msg_data[0])
            
            # 1. Identify AAPL's stock_locate via the 'R' message (Stock Directory)
            if aapl_locate is None:
                if msg_type == 'R':
                    stock = msg_data[11:19].decode('ascii', errors='replace').strip()
                    if stock == 'AAPL':
                        aapl_locate = struct.unpack_from('>H', msg_data, 1)[0]
                        print(f"AAPL ticker identified: stock_locate = {aapl_locate}")
                continue
            
            # 2. Filter immediately by stock_locate (major performance boost)
            stock_locate = struct.unpack_from('>H', msg_data, 1)[0]
            if stock_locate != aapl_locate:
                continue
            
            # Timestamp (6 bytes, positions 5 to 11)
            timestamp = int.from_bytes(msg_data[5:11], byteorder='big')
            
            # Stop once the end time is exceeded (ITCH stream is chronological)
            if timestamp > END_TIME:
                break
            
            # 3. Initial Snapshot at exact start time: inject live pre-market orders
            if not snapshot_taken and timestamp >= START_TIME:
                print(f"Taking Opening Snapshot at {start_hour}h ({len(orders)} live orders in book)...")
                for oid, (s, px, q) in orders.items():
                    records.append({
                        'timestamp': START_TIME,
                        'msg_type': 'SNAPSHOT',
                        'order_ref': oid,
                        'side': s,
                        'shares': q,
                        'price': px,
                        'aggressor': None
                    })
                snapshot_taken = True
            
            in_window = timestamp >= START_TIME
            
            # --- Processing ITCH 5.0 Event Types ---
            
            # A : Add Order | F : Add Order with MPID
            if msg_type in ('A', 'F'):
                oid, raw_side, qty, _, raw_px = struct.unpack_from('>QcI8sI', msg_data, 11)
                side = raw_side.decode('ascii')
                price = raw_px / 10000.0
                orders[oid] = (side, price, qty)
                
                if in_window:
                    records.append({
                        'timestamp': timestamp,
                        'msg_type': msg_type,
                        'order_ref': oid,
                        'side': side,
                        'shares': qty,
                        'price': price,
                        'aggressor': None
                    })
                    
            # E : Execution (at the initial limit order price)
            elif msg_type == 'E':
                oid, qty = struct.unpack_from('>QI', msg_data, 11)
                old = orders.get(oid)
                aggressor = None
                if old:
                    side, price, old_qty = old
                    aggressor = 'BUY' if side == 'S' else 'SELL'
                    rem = max(old_qty - qty, 0)
                    if rem == 0:
                        del orders[oid]
                    else:
                        orders[oid] = (side, price, rem)
                else:
                    side, price = None, None
                
                if in_window:
                    records.append({
                        'timestamp': timestamp,
                        'msg_type': msg_type,
                        'order_ref': oid,
                        'side': side,
                        'shares': qty,
                        'price': price,
                        'aggressor': aggressor
                    })
                    
            # C : Execution with Price (explicit execution price)
            elif msg_type == 'C':
                oid, qty, _, _, raw_px = struct.unpack_from('>QIQcI', msg_data, 11)
                exec_price = raw_px / 10000.0
                old = orders.get(oid)
                aggressor = None
                if old:
                    side, resting_price, old_qty = old
                    aggressor = 'BUY' if side == 'S' else 'SELL'
                    rem = max(old_qty - qty, 0)
                    if rem == 0:
                        del orders[oid]
                    else:
                        orders[oid] = (side, resting_price, rem)
                else:
                    side = None
                    
                if in_window:
                    records.append({
                        'timestamp': timestamp,
                        'msg_type': msg_type,
                        'order_ref': oid,
                        'side': side,
                        'shares': qty,
                        'price': exec_price,
                        'aggressor': aggressor
                    })
                    
            # X : Cancel (partial cancellation)
            elif msg_type == 'X':
                oid, qty = struct.unpack_from('>QI', msg_data, 11)
                old = orders.get(oid)
                if old:
                    side, price, old_qty = old
                    rem = max(old_qty - qty, 0)
                    if rem == 0:
                        del orders[oid]
                    else:
                        orders[oid] = (side, price, rem)
                else:
                    side, price = None, None
                    
                if in_window:
                    records.append({
                        'timestamp': timestamp,
                        'msg_type': msg_type,
                        'order_ref': oid,
                        'side': side,
                        'shares': qty,
                        'price': price,
                        'aggressor': None
                    })
                    
            # D : Delete (full order deletion)
            elif msg_type == 'D':
                (oid,) = struct.unpack_from('>Q', msg_data, 11)
                old = orders.pop(oid, None)
                if old:
                    side, price, del_qty = old
                else:
                    side, price, del_qty = None, None, 0
                    
                if in_window:
                    records.append({
                        'timestamp': timestamp,
                        'msg_type': msg_type,
                        'order_ref': oid,
                        'side': side,
                        'shares': del_qty,  # Exact retrieval of removed shares
                        'price': price,
                        'aggressor': None
                    })
                    
            # U : Replace (replacing one order with another)
            elif msg_type == 'U':
                old_id, new_id, new_qty, new_px = struct.unpack_from('>QQII', msg_data, 11)
                new_price = new_px / 10000.0
                old = orders.pop(old_id, None)
                side = old[0] if old else None
                orders[new_id] = (side, new_price, new_qty)
                
                if in_window:
                    records.append({
                        'timestamp': timestamp,
                        'msg_type': msg_type,
                        'order_ref': new_id,
                        'side': side,
                        'shares': new_qty,
                        'price': new_price,
                        'aggressor': None
                    })
                    
            # Q : Cross Trade (notably the Opening Cross at 09:30:00)
            elif msg_type == 'Q':
                cross_shares, _, cross_px, _, raw_cross_type = struct.unpack_from('>Q8sIQc', msg_data, 11)
                cross_type = raw_cross_type.decode('ascii', errors='replace')
                cross_price = cross_px / 10000.0
                
                if in_window:
                    records.append({
                        'timestamp': timestamp,
                        'msg_type': msg_type,
                        'order_ref': 0,
                        'side': f'CROSS_{cross_type}',
                        'shares': cross_shares,
                        'price': cross_price,
                        'aggressor': None
                    })

    print(f"Extraction completed in {round(time.time() - start_process, 2)} seconds.")
    print(f"{len(records)} AAPL messages captured (including initial book at start time).")
    
    if len(records) == 0:
        print("No records found.")
        return
        
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    
    df = pd.DataFrame(records)
    
    # 1. Define the exact date of the file (December 30, 2019)
    file_date = pd.to_datetime("2019-12-30")
    
    # 2. Convert to nanoseconds
    nanoseconds_since_midnight = pd.to_timedelta(df["timestamp"], unit="ns")
    
    # 3. Create the real_timestamp column
    df["real_timestamp"] = file_date + nanoseconds_since_midnight
    
    # 4. Reorder columns
    cols = ['real_timestamp'] + [c for c in df.columns if c != 'real_timestamp']
    df = df[cols]
    
    # 5. Save to Parquet
    df.to_parquet(output_file, index=False)
    print(f"File successfully saved: {output_file}")


def check_parquet_data():
    file_path = "market-making/data/processed/AAPL_market_open.parquet"
    
    try:
        df = pd.read_parquet(file_path)
    except FileNotFoundError:
        print(f"Error: The file {file_path} could not be found. Did you run the extraction?")
        return

    print("\n=== AAPL FILE ANALYSIS ===")
    print(f"Dimensions: {df.shape[0]} rows and {df.shape[1]} columns\n")
    
    print("--- 1. DATA TYPES ---")
    print(df.dtypes)
    print("\n")
    
    print("--- 2. FIRST 5 ROWS ---")
    pd.set_option('display.max_columns', None) 
    print(df.head())
    print("\n")
    
    print("--- 3. MESSAGE TYPE DISTRIBUTION ---")
    distribution = df['msg_type'].value_counts()
    print(distribution)
    print("\n")
    
    print("--- 4. TIME VERIFICATION ---")
    print(f"First message: {df['real_timestamp'].min()}")
    print(f"Last message: {df['real_timestamp'].max()}")


def check_monotonicity():
    file_path = "market-making/data/processed/AAPL_market_open.parquet"
    
    try:
        df = pd.read_parquet(file_path)
    except FileNotFoundError:
        return
        
    print("\n--- 5. MONOTONICITY CHECK ---")
    is_monotonic = df['timestamp'].is_monotonic_increasing
    
    if is_monotonic:
        print("SUCCESS: Time integrity is perfect. Timestamps are strictly chronological.")
    else:
        print("WARNING: Timestamps are going backwards!")
        df['time_diff'] = df['timestamp'].diff()
        errors = df[df['time_diff'] < 0]
        print(f"Number of backward jumps detected: {len(errors)}")
        print("\nHere are the first anomalies:")
        print(errors[['real_timestamp', 'timestamp', 'time_diff']].head())


def clean_and_validate_data(input_path: str, output_path: str):
    print(f"Loading dataset: {input_path}")
    df = pd.read_parquet(input_path)
    initial_count = len(df)
    
    # 1. Filter out Add orders (A, F) with missing critical values
    is_add = df['msg_type'].isin(['A', 'F'])
    valid_adds = df[is_add & df[['timestamp', 'order_ref', 'side', 'shares', 'price']].notna().all(axis=1)]
    other_msgs = df[~is_add]
    df_filtered = pd.concat([valid_adds, other_msgs]).sort_index()
    
    # 2. Remove rows with negative or zero prices where a price is required
    has_price = df_filtered['price'].notna()
    valid_prices = (df_filtered['price'] > 0) | (~has_price)
    df_filtered = df_filtered[valid_prices]
    
    # 3. Remove invalid shares (Delete 'D' messages have 0 shares by convention)
    valid_shares = (df_filtered['msg_type'] == 'D') | (df_filtered['shares'] > 0)
    df_filtered = df_filtered[valid_shares]
    
    final_count = len(df_filtered)
    dropped_count = initial_count - final_count
    
    # Save the cleaned dataset to parquet format
    df_filtered.to_parquet(output_path, index=False)
    
    # Professional summary report
    print("\n--- CLEANING REPORT ---")
    print(f"Initial row count    : {initial_count:,}")
    print(f"Dropped rows         : {dropped_count:,}")
    print(f"Final retained rows  : {final_count:,}")
    print(f"Saved to             : {output_path}")
    print("-----------------------\n")


if __name__ == "__main__":
    extract_aapl_market_open(start_hour=9.5, end_hour=10.0)
    check_parquet_data()
    check_monotonicity()
    clean_and_validate_data("market-making/data/processed/AAPL_market_open.parquet", "market-making/data/processed/AAPL_market_open_cleaned.parquet")
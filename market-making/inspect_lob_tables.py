import os
import pandas as pd


def inspect_snapshots_dataset(parquet_path: str = "market-making/data/processed/AAPL_snapshots.parquet"):
    """
    Displays the structural properties, schemas, and sample records of the 100ms LOB snapshots dataset.
    """
    print("\n" + "=" * 90)
    print("                    1. LOB SNAPSHOTS DATASET INSPECTION")
    print("=" * 90)

    if not os.path.exists(parquet_path):
        print(f"Error: The file {parquet_path} does not exist.")
        return

    df = pd.read_parquet(parquet_path)

    # 1. Dimensions and memory footprint
    memory_mb = df.memory_usage(deep=True).sum() / (1024 * 1024)
    print(f"\nSource File     : {parquet_path}")
    print(f"Dimensions      : {df.shape[0]:,} rows x {df.shape[1]} columns")
    print(f"Memory Usage    : {memory_mb:.2f} MB")
    print(f"Time Horizon    : {df['real_timestamp'].min()}  -->  {df['real_timestamp'].max()}")

    # 2. Schema and data types
    print("\n--- SCHEMA AND DATA TYPES ---")
    schema_info = pd.DataFrame({
        'Data Type': df.dtypes,
        'Non-Null Count': df.notna().sum(),
        'Sample (Row 0)': df.iloc[0]
    })
    print(schema_info.to_string())

    # 3. Best Bid & Offer (BBO) and spread metrics preview
    print("\n--- FIRST 5 SNAPSHOTS PREVIEW (BBO & SPREAD) ---")
    bbo_cols = ['real_timestamp', 'best_bid', 'best_ask', 'mid_price', 'spread', 'bid_size_l1', 'ask_size_l1', 'imbalance_l1']
    print(df[bbo_cols].head().to_string(index=False))

    # 4. Multi-level depth profile preview (L1 to L5)
    print("\n--- ORDER BOOK DEPTH PROFILE (L1 to L5) ON FIRST SNAPSHOT ---")
    first_row = df.iloc[0]
    depth_ladder = []
    for level in range(1, 6):
        depth_ladder.append({
            'Level': f'Level {level}',
            'Bid Volume': f"{int(first_row.get(f'bid_v{level}', 0)):,}",
            'Bid Price ($)': f"{first_row.get(f'bid_p{level}', 0):.4f}",
            'Ask Price ($)': f"{first_row.get(f'ask_p{level}', 0):.4f}",
            'Ask Volume': f"{int(first_row.get(f'ask_v{level}', 0)):,}"
        })
    ladder_df = pd.DataFrame(depth_ladder)
    print(ladder_df.to_string(index=False))


def display_instantaneous_lob_ladder(
    parquet_path: str = "market-making/data/processed/AAPL_snapshots.parquet",
    snapshot_index: int = 50
):
    """
    Prints a classic trading terminal ASCII Depth Ladder for a specific snapshot index.
    """
    df = pd.read_parquet(parquet_path)
    if snapshot_index >= len(df):
        snapshot_index = 0

    row = df.iloc[snapshot_index]
    snap_time = row['real_timestamp']
    spread = row['spread']
    mid = row['mid_price']

    print("\n" + "=" * 65)
    print(f"       LEVEL-2 ORDER BOOK DEPTH LADDER (SNAPSHOT #{snapshot_index})")
    print(f"       Timestamp : {snap_time}")
    print(f"       Mid-Price : ${mid:.4f} | Spread : ${spread:.4f}")
    print("=" * 65)
    print(f"{'BID SHARES':>12} | {'BID PRICE':>10} || {'ASK PRICE':<10} | {'ASK SHARES':<12}")
    print("-" * 65)

    for i in range(1, 6):
        bp = row.get(f'bid_p{i}')
        bv = row.get(f'bid_v{i}', 0)
        ap = row.get(f'ask_p{i}')
        av = row.get(f'ask_v{i}', 0)

        bid_str = f"{int(bv):>12,d} | ${bp:>9.4f}" if pd.notna(bp) and bv > 0 else f"{'':>12} | {'':>10}"
        ask_str = f"${ap:<9.4f} | {int(av):<12,d}" if pd.notna(ap) and av > 0 else f"{'':<10} | {'':<12}"
        print(f"{bid_str} || {ask_str}")

    print("=" * 65 + "\n")


if __name__ == "__main__":
    snapshots_file = "market-making/data/processed/AAPL_snapshots.parquet"

    # 1. Structural schema and statistical overview of the parquet dataset
    inspect_snapshots_dataset(snapshots_file)

    # 2. ASCII visual order book ladder at a specific moment (e.g. index 50 = 5.0 seconds after open)
    display_instantaneous_lob_ladder(snapshots_file, snapshot_index=50)

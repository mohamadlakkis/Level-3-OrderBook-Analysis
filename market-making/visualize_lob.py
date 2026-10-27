import os
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def load_snapshots(parquet_path: str = "market-making/data/processed/AAPL_snapshots.parquet") -> pd.DataFrame:
    """
    Loads and prepares the 100ms periodic order book snapshots for visualization.
    """
    if not os.path.exists(parquet_path):
        raise FileNotFoundError(
            f"Snapshot file not found: {parquet_path}.\n"
            f"Please run 'python market-making/reconstruct_lob.py' first."
        )

    print(f"Loading snapshots from: {parquet_path}")
    df = pd.read_parquet(parquet_path)

    # Ensure real_timestamp is parsed as datetime
    if not pd.api.types.is_datetime64_any_dtype(df['real_timestamp']):
        df['real_timestamp'] = pd.to_datetime(df['real_timestamp'])

    # Set real_timestamp as index for time-series slicing
    df = df.sort_values(by='real_timestamp').reset_index(drop=True)
    return df


def plot_lob_timeseries_dashboard(
    df: pd.DataFrame,
    output_path: str = "market-making/figures/AAPL_lob_dynamics.png",
    show_plot: bool = True
):
    """
    Generates a professional 4-panel quantitative dashboard visualizing the Limit Order Book over time:
      1. Best Bid, Best Ask, Mid-Price, and Micro-Price with Top-5 Depth corridor
      2. Bid-Ask Spread dynamics in cents ($) and basis points (bps)
      3. Top-of-Book Order Imbalance (I_L1) with color-coded directional pressure
      4. Total Cumulative Liquidity Depth (Bids vs Asks)
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    fig, axes = plt.subplots(4, 1, figsize=(16, 12), sharex=True, gridspec_kw={'height_ratios': [2.2, 1.2, 1.2, 1.2]})
    plt.subplots_adjust(hspace=0.08)

    t = df['real_timestamp']

    # -------------------------------------------------------------
    # Panel 1: Price Dynamics & Top-N Depth Corridor
    # -------------------------------------------------------------
    ax1 = axes[0]
    
    # Corridor between best bid and best ask
    ax1.fill_between(t, df['best_bid'], df['best_ask'], color='#cbd5e1', alpha=0.6, label='BBO Spread Corridor')

    # Top-3 depth levels (subtle lines showing order book queue structure)
    for level in (2, 3):
        if f'bid_p{level}' in df.columns:
            ax1.plot(t, df[f'bid_p{level}'], color='#16a34a', linestyle=':', linewidth=0.8, alpha=0.5)
        if f'ask_p{level}' in df.columns:
            ax1.plot(t, df[f'ask_p{level}'], color='#dc2626', linestyle=':', linewidth=0.8, alpha=0.5)

    # Best Bid, Best Ask, Mid-Price, and Micro-Price
    ax1.plot(t, df['best_bid'], color='#15803d', linewidth=1.2, label='Best Bid (BBO)')
    ax1.plot(t, df['best_ask'], color='#b91c1c', linewidth=1.2, label='Best Ask (BBO)')
    ax1.plot(t, df['mid_price'], color='#0f172a', linewidth=1.5, label='Mid-Price')
    ax1.plot(t, df['micro_price'], color='#7c3aed', linewidth=1.0, linestyle='--', alpha=0.8, label='Volume-Weighted Micro-Price')

    ax1.set_ylabel("Price ($)", fontsize=11, fontweight='bold')
    ax1.set_title("AAPL - High-Frequency Limit Order Book Dynamics (100ms Sampling)", fontsize=14, fontweight='bold', pad=12)
    ax1.legend(loc='upper right', frameon=True, framealpha=0.9, fontsize=9, ncol=2)
    ax1.grid(True, linestyle="--", alpha=0.4)

    # -------------------------------------------------------------
    # Panel 2: Bid-Ask Spread Dynamics (USD and Basis Points)
    # -------------------------------------------------------------
    ax2 = axes[1]
    spread = df['spread']
    spread_bps = (spread / df['mid_price']) * 10_000

    ax2.plot(t, spread, color='#d97706', linewidth=1.0, label='Spread ($)')
    mean_spread = spread.mean()
    ax2.axhline(mean_spread, color='#b45309', linestyle='--', linewidth=1.2, label=f'Mean Spread: ${mean_spread:.4f}')

    ax2.set_ylabel("Spread ($)", fontsize=10, fontweight='bold', color='#d97706')
    ax2.tick_params(axis='y', labelcolor='#d97706')
    ax2.grid(True, linestyle="--", alpha=0.4)

    # Secondary axis for Spread in Basis Points (bps)
    ax2_twin = ax2.twinx()
    ax2_twin.plot(t, spread_bps, color='#64748b', linewidth=0.5, alpha=0.4)
    ax2_twin.set_ylabel("Spread (bps)", fontsize=10, fontweight='bold', color='#64748b')
    ax2_twin.tick_params(axis='y', labelcolor='#64748b')

    # Combine legends from both axes
    lines_1, labels_1 = ax2.get_legend_handles_labels()
    ax2.legend(lines_1, labels_1, loc='upper right', frameon=True, framealpha=0.9, fontsize=9)

    # -------------------------------------------------------------
    # Panel 3: Order Book Imbalance (I_L1)
    # -------------------------------------------------------------
    ax3 = axes[2]
    imbalance = df['imbalance_l1'].fillna(0)

    # Color code positive (buying pressure) vs negative (selling pressure)
    ax3.fill_between(t, 0, imbalance, where=(imbalance >= 0), color='#22c55e', alpha=0.6, label='Bid Dominance (Buy Pressure)')
    ax3.fill_between(t, 0, imbalance, where=(imbalance < 0), color='#ef4444', alpha=0.6, label='Ask Dominance (Sell Pressure)')
    ax3.axhline(0, color='#334155', linestyle='-', linewidth=0.8)

    # 5-second moving average for smoothed flow direction (50 periods of 100ms)
    rolling_imbalance = imbalance.rolling(window=50, min_periods=1).mean()
    ax3.plot(t, rolling_imbalance, color='#0f172a', linewidth=1.2, label='5s Rolling Imbalance')

    ax3.set_ylabel("Imbalance (L1)", fontsize=10, fontweight='bold')
    ax3.set_ylim(-1.05, 1.05)
    ax3.legend(loc='upper right', frameon=True, framealpha=0.9, fontsize=9, ncol=3)
    ax3.grid(True, linestyle="--", alpha=0.4)

    # -------------------------------------------------------------
    # Panel 4: Total Aggregate Depth (Bids vs Asks)
    # -------------------------------------------------------------
    ax4 = axes[3]
    ax4.plot(t, df['total_bid_depth'], color='#16a34a', linewidth=1.2, label='Total Bid Depth (Shares)')
    ax4.plot(t, df['total_ask_depth'], color='#dc2626', linewidth=1.2, label='Total Ask Depth (Shares)')

    ax4.set_ylabel("Depth (Shares)", fontsize=10, fontweight='bold')
    ax4.set_xlabel("Time (EST)", fontsize=11, fontweight='bold')
    ax4.legend(loc='upper right', frameon=True, framealpha=0.9, fontsize=9)
    ax4.grid(True, linestyle="--", alpha=0.4)

    # Format x-axis with nanosecond/millisecond clean timestamps
    ax4.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
    fig.autofmt_xdate()

    print(f"Saving high-resolution figure to: {output_path}")
    plt.savefig(output_path, dpi=300, bbox_inches='tight')

    if show_plot:
        plt.show()

    plt.close()


def plot_instantaneous_depth_profile(
    df: pd.DataFrame,
    timestamp_idx: int = 100,
    output_path: str = "market-making/figures/AAPL_depth_profile.png",
    show_plot: bool = True
):
    """
    Plots the classic cumulative Limit Order Book depth curve (Supply/Demand Step Function)
    at a specific instantaneous snapshot index.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if timestamp_idx >= len(df):
        timestamp_idx = len(df) // 2

    row = df.iloc[timestamp_idx]
    snap_time = row['real_timestamp']

    # Extract Top-5 Bids and Asks
    bids = []
    asks = []

    for i in range(1, 6):
        bp, bv = row.get(f'bid_p{i}'), row.get(f'bid_v{i}')
        ap, av = row.get(f'ask_p{i}'), row.get(f'ask_v{i}')
        if pd.notna(bp) and bv > 0:
            bids.append((bp, bv))
        if pd.notna(ap) and av > 0:
            asks.append((ap, av))

    if not bids or not asks:
        print(f"Insufficient levels to plot depth profile at index {timestamp_idx}.")
        return

    # Sort bids descending, asks ascending
    bids.sort(key=lambda x: x[0], reverse=True)
    asks.sort(key=lambda x: x[0])

    bid_px = [b[0] for b in bids]
    bid_vol = [b[1] for b in bids]
    cum_bid = np.cumsum(bid_vol)

    ask_px = [a[0] for a in asks]
    ask_vol = [a[1] for a in asks]
    cum_ask = np.cumsum(ask_vol)

    plt.figure(figsize=(10, 6))

    # Bid step curve
    plt.step(bid_px, cum_bid, where='post', color='#16a34a', linewidth=2.0, label='Bid Depth (Buy Orders)')
    plt.fill_between(bid_px, 0, cum_bid, step='post', color='#22c55e', alpha=0.25)

    # Ask step curve
    plt.step(ask_px, cum_ask, where='post', color='#dc2626', linewidth=2.0, label='Ask Depth (Sell Orders)')
    plt.fill_between(ask_px, 0, cum_ask, step='post', color='#ef4444', alpha=0.25)

    # BBO and Mid-Price lines
    plt.axvline(row['mid_price'], color='#0f172a', linestyle='--', linewidth=1.5, label=f"Mid-Price: ${row['mid_price']:.4f}")

    plt.title(f"AAPL Cumulative Limit Order Book Depth\nSnapshot Time: {snap_time}", fontsize=13, fontweight='bold')
    plt.xlabel("Price ($)", fontsize=11, fontweight='bold')
    plt.ylabel("Cumulative Depth (Shares)", fontsize=11, fontweight='bold')
    plt.grid(True, linestyle="--", alpha=0.5)
    plt.legend(loc='upper center', frameon=True, framealpha=0.9, fontsize=10)

    print(f"Saving instantaneous depth curve to: {output_path}")
    plt.savefig(output_path, dpi=300, bbox_inches='tight')

    if show_plot:
        plt.show()

    plt.close()


if __name__ == "__main__":
    snapshot_file = "market-making/data/processed/AAPL_snapshots.parquet"
    
    # 1. Load generated snapshots
    snapshots_df = load_snapshots(snapshot_file)

    # 2. Generate the multi-panel time-series dashboard
    plot_lob_timeseries_dashboard(
        df=snapshots_df,
        output_path="market-making/figures/AAPL_lob_dynamics.png",
        show_plot=False
    )

    # 3. Generate instantaneous cumulative depth profile (e.g. 5 seconds after open)
    plot_instantaneous_depth_profile(
        df=snapshots_df,
        timestamp_idx=50,  # 50 * 100ms = 5.0 seconds into the session
        output_path="market-making/figures/AAPL_depth_profile_093005.png",
        show_plot=False
    )


import os
import numpy as np
import pandas as pd


def load_snapshots(parquet_path: str = "market-making/data/processed/AAPL_snapshots.parquet") -> pd.DataFrame:
    """
    Loads 100ms periodic LOB snapshots from a Parquet file.
    """
    if not os.path.exists(parquet_path):
        raise FileNotFoundError(
            f"Snapshot file not found: {parquet_path}.\n"
            f"Please run 'python market-making/reconstruct_lob.py' first."
        )

    df = pd.read_parquet(parquet_path)
    if not pd.api.types.is_datetime64_any_dtype(df['real_timestamp']):
        df['real_timestamp'] = pd.to_datetime(df['real_timestamp'])

    return df.sort_values(by='real_timestamp').reset_index(drop=True)


def compute_lob_descriptive_stats(df: pd.DataFrame) -> dict:
    """
    Computes professional quantitative microstructure descriptive statistics on the LOB.
    
    Returns a dictionary of DataFrames:
      - 'summary_table': Key statistical distribution metrics (mean, std, percentiles, skew, kurt).
      - 'microstructure_table': High-frequency microstructure properties (tick distribution, volatility, memory).
      - 'depth_ladder_table': Average liquidity profile across Top-5 price levels.
    """
    # -------------------------------------------------------------
    # 1. Feature Engineering for Microstructure Metrics
    # -------------------------------------------------------------
    df = df.copy()

    # Relative Spread in Basis Points (bps): (Spread / Mid) * 10,000
    df['spread_bps'] = (df['spread'] / df['mid_price']) * 10_000

    # L1 Total Size (Shares)
    df['total_l1_depth'] = df['bid_size_l1'] + df['ask_size_l1']

    # Total Book Depth and Total Imbalance
    df['total_book_depth'] = df['total_bid_depth'] + df['total_ask_depth']
    denom_total = df['total_bid_depth'] + df['total_ask_depth']
    df['imbalance_total'] = np.where(denom_total > 0, (df['total_bid_depth'] - df['total_ask_depth']) / denom_total, 0.0)

    # Micro-Price Deviation (absolute distance in cents between weighted micro-price and mid-price)
    df['micro_mid_diff_cents'] = (df['micro_price'] - df['mid_price']).abs() * 100

    # High-Frequency Log Returns on Mid-Price: r_t = ln(Mid_t / Mid_{t-1})
    df['mid_log_ret'] = np.log(df['mid_price'] / df['mid_price'].shift(1))

    # Top-5 cumulative volumes
    bid_v_cols = [f'bid_v{i}' for i in range(1, 6) if f'bid_v{i}' in df.columns]
    ask_v_cols = [f'ask_v{i}' for i in range(1, 6) if f'ask_v{i}' in df.columns]
    df['top5_bid_volume'] = df[bid_v_cols].sum(axis=1)
    df['top5_ask_volume'] = df[ask_v_cols].sum(axis=1)

    # -------------------------------------------------------------
    # 2. Main Distribution Summary Table
    # -------------------------------------------------------------
    vars_to_analyze = [
        ('Mid-Price ($)', 'mid_price'),
        ('Micro-Price ($)', 'micro_price'),
        ('Bid-Ask Spread ($)', 'spread'),
        ('Relative Spread (bps)', 'spread_bps'),
        ('Micro-Mid Discrepancy (¢)', 'micro_mid_diff_cents'),
        ('Best Bid Size (Shares)', 'bid_size_l1'),
        ('Best Ask Size (Shares)', 'ask_size_l1'),
        ('Top-of-Book Total Size (Shares)', 'total_l1_depth'),
        ('L1 Imbalance [-1, +1]', 'imbalance_l1'),
        ('Top-5 Bid Volume (Shares)', 'top5_bid_volume'),
        ('Top-5 Ask Volume (Shares)', 'top5_ask_volume'),
        ('Total Book Bid Depth (Shares)', 'total_bid_depth'),
        ('Total Book Ask Depth (Shares)', 'total_ask_depth'),
        ('Total Book Depth (Shares)', 'total_book_depth'),
        ('Total Book Imbalance [-1, +1]', 'imbalance_total'),
    ]

    summary_rows = []
    for label, col in vars_to_analyze:
        if col not in df.columns:
            continue
        series = df[col].dropna()
        if series.empty:
            continue

        q25, q75 = series.quantile(0.25), series.quantile(0.75)
        summary_rows.append({
            'Metric': label,
            'Mean': series.mean(),
            'Std Dev': series.std(),
            'Min': series.min(),
            '25%': q25,
            'Median (50%)': series.median(),
            '75%': q75,
            'Max': series.max(),
            'IQR': q75 - q25,
            'Skewness': series.skew(),
            'Kurtosis': series.kurt()
        })

    summary_table = pd.DataFrame(summary_rows).set_index('Metric')

    # -------------------------------------------------------------
    # 3. Microstructure Specific Properties
    # -------------------------------------------------------------
    total_snapshots = len(df)
    valid_spread = df['spread'].dropna()

    # Tick size distribution (1 cent is 0.0100)
    pct_1_cent = (valid_spread == 0.01).mean() * 100
    pct_2_cents = (valid_spread == 0.02).mean() * 100
    pct_wider = (valid_spread > 0.02).mean() * 100
    pct_locked = (valid_spread == 0.00).mean() * 100

    # Realized Volatility: standard deviation of 100ms log-returns scaled to annualized vol
    # 1 second = 10 periods; 1 day = 6.5 trading hours = 23,400 seconds = 234,000 periods (100ms)
    # Annual trading days = 252 -> Annualization factor = sqrt(234,000 * 252)
    returns = df['mid_log_ret'].dropna()
    realized_vol_30m = returns.std() * np.sqrt(len(returns)) * 100  # in %
    annualized_vol = returns.std() * np.sqrt(234_000 * 252) * 100  # in %

    # Autocorrelations
    ret_autocorr_lag1 = returns.autocorr(lag=1) if len(returns) > 1 else np.nan
    spread_autocorr_lag1 = df['spread'].autocorr(lag=1)
    spread_autocorr_lag10 = df['spread'].autocorr(lag=10)  # 1 second memory
    imbalance_autocorr_lag1 = df['imbalance_l1'].autocorr(lag=1)
    imbalance_autocorr_lag10 = df['imbalance_l1'].autocorr(lag=10)  # 1 second memory

    # Price drift across the session
    start_mid = df['mid_price'].dropna().iloc[0]
    end_mid = df['mid_price'].dropna().iloc[-1]
    net_drift = end_mid - start_mid
    net_drift_bps = (net_drift / start_mid) * 10_000

    micro_properties = [
        ('Total Snapshots Analyzed', f"{total_snapshots:,}"),
        ('Time Horizon', f"{df['real_timestamp'].min().strftime('%H:%M:%S')} - {df['real_timestamp'].max().strftime('%H:%M:%S')} EST"),
        ('Starting Mid-Price', f"${start_mid:.4f}"),
        ('Ending Mid-Price', f"${end_mid:.4f}"),
        ('Net Session Drift', f"${net_drift:+.4f} ({net_drift_bps:+.2f} bps)"),
        ('Spread = 1 Tick (0.01$)', f"{pct_1_cent:.2f} %"),
        ('Spread = 2 Ticks (0.02$)', f"{pct_2_cents:.2f} %"),
        ('Spread > 2 Ticks (>0.02$)', f"{pct_wider:.2f} %"),
        ('Locked Market (Spread = 0)', f"{pct_locked:.2f} %"),
        ('Realized Volatility (30 min)', f"{realized_vol_30m:.2f} %"),
        ('Annualized Realized Volatility', f"{annualized_vol:.2f} %"),
        ('100ms Return Autocorrelation (Lag 1)', f"{ret_autocorr_lag1:.4f}"),
        ('Spread Autocorrelation (Lag 1 / 100ms)', f"{spread_autocorr_lag1:.4f}"),
        ('Spread Autocorrelation (Lag 10 / 1.0s)', f"{spread_autocorr_lag10:.4f}"),
        ('L1 Imbalance Autocorrelation (Lag 1 / 100ms)', f"{imbalance_autocorr_lag1:.4f}"),
        ('L1 Imbalance Autocorrelation (Lag 10 / 1.0s)', f"{imbalance_autocorr_lag10:.4f}")
    ]
    microstructure_table = pd.DataFrame(micro_properties, columns=['Property', 'Value']).set_index('Property')

    # -------------------------------------------------------------
    # 4. Depth Ladder Profile Table (Top-5 Levels Average)
    # -------------------------------------------------------------
    ladder_rows = []
    for i in range(1, 6):
        bp_col, bv_col = f'bid_p{i}', f'bid_v{i}'
        ap_col, av_col = f'ask_p{i}', f'ask_v{i}'

        avg_bid_vol = df[bv_col].mean() if bv_col in df.columns else np.nan
        avg_ask_vol = df[av_col].mean() if av_col in df.columns else np.nan

        # Distance from Mid-Price in Cents
        bid_dist = ((df['mid_price'] - df[bp_col]) * 100).mean() if bp_col in df.columns else np.nan
        ask_dist = ((df[ap_col] - df['mid_price']) * 100).mean() if ap_col in df.columns else np.nan

        ladder_rows.append({
            'Level': f'Level {i}',
            'Avg Bid Dist from Mid (¢)': bid_dist,
            'Avg Bid Shares': avg_bid_vol,
            'Avg Ask Dist from Mid (¢)': ask_dist,
            'Avg Ask Shares': avg_ask_vol
        })

    depth_ladder_table = pd.DataFrame(ladder_rows).set_index('Level')

    return {
        'summary': summary_table,
        'microstructure': microstructure_table,
        'ladder': depth_ladder_table
    }


def display_and_save_reports(stats: dict, output_dir: str = "market-making/reports"):
    """
    Prints reports to console and saves them as formatted Markdown and CSV files.
    """
    os.makedirs(output_dir, exist_ok=True)

    summary_df = stats['summary']
    micro_df = stats['microstructure']
    ladder_df = stats['ladder']

    # -------------------------------------------------------------
    # Console Display
    # -------------------------------------------------------------
    print("\n" + "=" * 90)
    print("        LIMIT ORDER BOOK (LOB) DESCRIPTIVE STATISTICS - HIGH-FREQUENCY REPORT")
    print("=" * 90)

    print("\n--- 1. MARKET MICROSTRUCTURE SUMMARY & DYNAMICS ---")
    print(micro_df.to_string())

    print("\n--- 2. LOB DISTRIBUTIONAL METRICS ---")
    pd.set_option('display.float_format', lambda x: f'{x:.4f}')
    print(summary_df.to_string())

    print("\n--- 3. AVERAGE TOP-5 DEPTH LADDER PROFILE ---")
    print(ladder_df.to_string())
    print("=" * 90 + "\n")

    # -------------------------------------------------------------
    # File Export (CSV and Markdown)
    # -------------------------------------------------------------
    csv_summary_path = os.path.join(output_dir, "AAPL_lob_summary_stats.csv")
    csv_micro_path = os.path.join(output_dir, "AAPL_lob_microstructure.csv")
    csv_ladder_path = os.path.join(output_dir, "AAPL_lob_depth_ladder.csv")
    md_report_path = os.path.join(output_dir, "AAPL_lob_report.md")

    summary_df.to_csv(csv_summary_path)
    micro_df.to_csv(csv_micro_path)
    ladder_df.to_csv(csv_ladder_path)

    # Helper to export markdown table safely without requiring optional 'tabulate'
    def safe_markdown(df_to_export: pd.DataFrame) -> str:
        try:
            return df_to_export.to_markdown()
        except (ImportError, ModuleNotFoundError):
            # Fallback text representation wrapped in markdown code fence
            return f"```\n{df_to_export.to_string()}\n```"

    # Build formatted Markdown report
    with open(md_report_path, 'w', encoding='utf-8') as f:
        f.write("# AAPL Limit Order Book (LOB) - Descriptive Statistics Report\n\n")
        f.write("Generated from 100ms periodic order book snapshots (TotalView-ITCH 5.0).\n\n")
        
        f.write("## 1. High-Frequency Market Microstructure Properties\n\n")
        f.write(safe_markdown(micro_df))
        f.write("\n\n---\n\n")
        
        f.write("## 2. Statistical Distribution of Core LOB Variables\n\n")
        f.write(safe_markdown(summary_df))
        f.write("\n\n---\n\n")
        
        f.write("## 3. Average Liquidity Depth Ladder (Top-5 Levels)\n\n")
        f.write(safe_markdown(ladder_df))
        f.write("\n")

    print(f"Reports successfully saved to: {output_dir}")
    print(f"  • Markdown: {md_report_path}")
    print(f"  • CSVs    : {csv_summary_path}")


if __name__ == "__main__":
    snapshots_path = "market-making/data/processed/AAPL_snapshots.parquet"
    
    # 1. Load snapshots dataset
    df_snapshots = load_snapshots(snapshots_path)

    # 2. Compute quantitative statistics
    stats_dict = compute_lob_descriptive_stats(df_snapshots)

    # 3. Print and export report files
    display_and_save_reports(stats_dict, output_dir="market-making/reports")

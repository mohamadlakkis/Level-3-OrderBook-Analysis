"""Helpers for the order flow studies: book replay, OFI by message group, grid, tests.

Used by the multi-day notebook (04) to apply the pipeline of notebooks 02 and 03 to several
sessions. The functions are the ones of notebook 03, moved here so they are written once.
pandas and statsmodels are optional notebook dependencies (group ``analysis``), so this module
is left out of the strict type checking.
"""

# mypy: ignore-errors

from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats

from analysis.data import load_market_data
from common.enums import Ticker
from common.schema import PRICE_SCALE, TIMEZONE

GROUP_OF = {
    "A": "add",
    "F": "add",
    "X": "cancel",
    "D": "cancel",
    "E": "exec",
    "C": "exec",
    "U": "replace",
}
GROUPS = ["add", "cancel", "exec", "replace"]
FLOW = [f"ofi_{group}" for group in GROUPS]
STATIC = ["spread", "obi_1", "log_depth"]
NS_PER_SECOND = 1_000_000_000


def replay_top_of_book(events):
    """Replay the displayed ITCH messages; return the best bid/ask and sizes after each one."""
    orders = {}  # order id -> [side, price, shares left]
    levels = {"B": {}, "S": {}}  # side -> {price: shares resting at this price}
    best = {"B": 0, "S": 0}  # best price of each side, 0 when the side is empty

    def add_order(order_id, side, price, shares):
        orders[order_id] = [side, price, shares]
        levels[side][price] = levels[side].get(price, 0) + shares
        current = best[side]
        if current == 0 or (price > current if side == "B" else price < current):
            best[side] = price

    def remove_shares(side, price, shares):
        book = levels[side]
        book[price] -= shares
        if book[price] <= 0:
            del book[price]
            if price == best[side]:
                if not book:
                    best[side] = 0
                else:
                    best[side] = max(book) if side == "B" else min(book)

    kinds = events["message_type"].to_numpy(dtype=object)
    sides = events["side"].to_numpy(dtype=object)
    order_ids = events["order_id"].to_numpy(dtype="float64", na_value=np.nan)
    new_ids = events["new_order_id"].to_numpy(dtype="float64", na_value=np.nan)
    shares = events["shares"].to_numpy(dtype="float64", na_value=np.nan)
    prices = events["price_units"].to_numpy(dtype="float64", na_value=np.nan)

    n_events = len(events)
    out = {name: np.zeros(n_events, dtype=np.int64) for name in ("bid", "bid_q", "ask", "ask_q")}
    for i in range(n_events):
        kind = kinds[i]
        if kind in ("A", "F"):
            add_order(int(order_ids[i]), sides[i], int(prices[i]), int(shares[i]))
        elif kind in ("E", "C", "X"):
            order = orders.get(int(order_ids[i]))
            if order is not None:
                side, price, left = order
                remove_shares(side, price, int(shares[i]))
                if left - int(shares[i]) > 0:
                    order[2] = left - int(shares[i])
                else:
                    del orders[int(order_ids[i])]
        elif kind == "D":
            order = orders.pop(int(order_ids[i]), None)
            if order is not None:
                remove_shares(order[0], order[1], order[2])
        elif kind == "U":
            order = orders.pop(int(order_ids[i]), None)
            if order is not None:
                remove_shares(order[0], order[1], order[2])
                add_order(int(new_ids[i]), order[0], int(prices[i]), int(shares[i]))
        out["bid"][i] = best["B"]
        out["bid_q"][i] = levels["B"].get(best["B"], 0)
        out["ask"][i] = best["S"]
        out["ask_q"][i] = levels["S"].get(best["S"], 0)

    return pd.DataFrame(
        {
            "timestamp_ns": events["timestamp_ns"].to_numpy(dtype="int64"),
            "message_type": kinds,
            "bid_price": out["bid"],
            "bid_shares": out["bid_q"],
            "ask_price": out["ask"],
            "ask_shares": out["ask_q"],
        }
    )


def regular_hours_book(events, session_date):
    """Best quotes after each event, regular hours only, without empty/locked/crossed quotes."""
    tob = replay_top_of_book(events)
    tob["bid_price"] = tob["bid_price"] / PRICE_SCALE
    tob["ask_price"] = tob["ask_price"] / PRICE_SCALE
    in_hours = (tob["timestamp_ns"] >= 34_200 * NS_PER_SECOND) & (
        tob["timestamp_ns"] < 57_600 * NS_PER_SECOND
    )
    valid_quote = (tob["bid_price"] > 0) & (tob["ask_price"] > tob["bid_price"])
    tob = tob[in_hours & valid_quote].reset_index(drop=True)
    midnight = pd.Timestamp(session_date.isoformat(), tz=TIMEZONE)
    tob["timestamp"] = midnight + pd.to_timedelta(tob["timestamp_ns"], unit="ns")
    return tob


def event_ofi(tob):
    """OFI contribution of each event (Cont, Kukanov and Stoikov, 2014), best quotes only."""
    pb, qb = tob["bid_price"].to_numpy(), tob["bid_shares"].to_numpy()
    pa, qa = tob["ask_price"].to_numpy(), tob["ask_shares"].to_numpy()
    pb_diff, pa_diff = np.diff(pb, prepend=pb[0]), np.diff(pa, prepend=pa[0])
    qb_diff, qa_diff = np.diff(qb, prepend=qb[0]), np.diff(qa, prepend=qa[0])
    qb_prev, qa_prev = np.roll(qb, 1), np.roll(qa, 1)
    qb_prev[0] = qa_prev[0] = 0
    delta_w = np.where(pb_diff > 0, qb, np.where(pb_diff == 0, qb_diff, -qb_prev))
    delta_v = np.where(pa_diff > 0, -qa_prev, np.where(pa_diff == 0, qa_diff, qa))
    return delta_w - delta_v


def one_second_grid(tob, session_date):
    """Features on a 1-second grid (09:35 to 15:55) and the 5-second ahead mid-price change.

    Static features use the last quote at or before t, the OFI groups sum the events of
    (t-1s, t], and the target looks at (t, t+5s], so features and target never overlap.
    """
    tob = tob.copy()
    tob["ofi"] = event_ofi(tob)
    tob["mid_price"] = 0.5 * (tob["bid_price"] + tob["ask_price"])
    tob["group"] = tob["message_type"].map(GROUP_OF).fillna("other")
    # Messages that do not touch the displayed book (P, Q, S, ...) never move the quotes
    assert (tob.loc[tob["group"] == "other", "ofi"] == 0).all()
    for group in GROUPS:
        tob[f"ofi_{group}"] = np.where(tob["group"] == group, tob["ofi"], 0.0)
    assert np.allclose(tob[FLOW].sum(axis=1), tob["ofi"])  # the groups add up to the total OFI

    tob = tob.set_index("timestamp")
    grid = (
        tob[["bid_price", "ask_price", "bid_shares", "ask_shares", "mid_price"]]
        .resample("1s", label="right", closed="right")
        .last()
        .ffill()
    )
    flow = tob[["ofi", *FLOW]].resample("1s", label="right", closed="right").sum().fillna(0)
    grid = grid.join(flow)
    grid["spread"] = grid["ask_price"] - grid["bid_price"]
    depth = grid["bid_shares"] + grid["ask_shares"]
    grid["obi_1"] = (grid["bid_shares"] - grid["ask_shares"]) / depth
    grid["log_depth"] = np.log(depth)
    grid["target"] = (grid["mid_price"].shift(-5) - grid["mid_price"]) / 0.01

    start = pd.Timestamp(f"{session_date.isoformat()} 09:35:00", tz=TIMEZONE)
    end = pd.Timestamp(f"{session_date.isoformat()} 15:55:00", tz=TIMEZONE)
    columns = ["mid_price", *STATIC, "ofi", *FLOW, "target"]
    return grid.loc[start:end].dropna(subset=["target"])[columns]


def load_sessions(event_dirs, cache_path, ticker="AAPL"):
    """Return {session date: 1-second grid} for every session available.

    A grid is rebuilt from the converted event file when one is found in `event_dirs`. Other
    sessions are read from `cache_path`, one small Parquet file shipped with the repository so
    that the notebook runs without the multi-GB raw files. The cache is then rewritten with all
    sessions, so it always matches the code that produced it.
    """
    sources = {}
    for directory in event_dirs:
        for path in sorted(Path(directory).glob(f"{ticker}_????-??-??.parquet")):
            sources.setdefault(date.fromisoformat(path.stem[len(ticker) + 1 :]), path)

    sessions = {}
    for session, path in sorted(sources.items()):
        market = load_market_data(path, expected_ticker=Ticker(ticker), expected_date=session)
        tob = regular_hours_book(market.events.to_pandas(), session)
        sessions[session] = one_second_grid(tob, session)

    cache_path = Path(cache_path)
    if cache_path.is_file():
        for key, grid in pd.read_parquet(cache_path).groupby("session"):
            sessions.setdefault(date.fromisoformat(key), grid.drop(columns="session"))
    if not sessions:
        raise FileNotFoundError("No converted event file and no cached grid were found.")

    sessions = dict(sorted(sessions.items()))
    combined = pd.concat([grid.assign(session=day.isoformat()) for day, grid in sessions.items()])
    combined.to_parquet(cache_path)
    return sessions


def split_day(data, train_share=0.70, purge=5):
    """Chronological split; drop the last `purge` training rows, whose target enters the test."""
    split = int(len(data) * train_share)
    return data.iloc[: split - purge], data.iloc[split:]


def fit_predict(columns, train, test, lags=5):
    """OLS on standardized features (fitted on train only) with Newey-West standard errors."""
    mean, std = train[columns].mean(), train[columns].std(ddof=0)
    x_train = sm.add_constant((train[columns] - mean) / std)
    x_test = sm.add_constant((test[columns] - mean) / std, has_constant="add")
    result = sm.OLS(train["target"], x_train).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return result, np.asarray(result.predict(x_test))


def fit_predict_shrunk(train, test, penalty):
    """M3 with a ridge penalty that pulls the four flow coefficients towards a common value.

    The flows are written as b * ofi + sum_g d_g * ofi_g and only the d_g are penalized, so
    penalty = 0 gives the OLS fit of M3 and a very large penalty gives M2. All flows share one
    scale (the training sd of the total OFI), so "equal coefficients" means equal per share.
    """
    mean, std = train[STATIC].mean(), train[STATIC].std(ddof=0)
    flow_mean, scale = train[["ofi", *FLOW]].mean(), train["ofi"].std(ddof=0)

    def design(sample):
        static = (sample[STATIC] - mean) / std
        flow = (sample[["ofi", *FLOW]] - flow_mean) / scale
        return np.column_stack([np.ones(len(sample)), static, flow])

    x_train, y_train = design(train), train["target"].to_numpy()
    weights = np.r_[np.zeros(1 + len(STATIC) + 1), np.ones(len(FLOW))]
    if penalty == 0:
        beta = np.linalg.lstsq(x_train, y_train, rcond=None)[0]
    else:
        gram = x_train.T @ x_train + penalty * len(train) * np.diag(weights)
        beta = np.linalg.solve(gram, x_train.T @ y_train)
    per_share = (beta[1 + len(STATIC)] + beta[-len(FLOW) :]) / scale  # ticks per share, by group
    return per_share, design(test) @ beta


def choose_penalty(train, penalties, n_blocks=6, purge=5):
    """Pick the penalty with the lowest pooled MSE on expanding windows inside the training set."""
    blocks = np.array_split(np.arange(len(train)), n_blocks)
    errors = {penalty: [] for penalty in penalties}
    for k in range(1, n_blocks):
        fold_train, fold_test = train.iloc[: blocks[k][0] - purge], train.iloc[blocks[k]]
        y = fold_test["target"].to_numpy()
        for penalty in penalties:
            errors[penalty].append((y - fit_predict_shrunk(fold_train, fold_test, penalty)[1]) ** 2)
    pooled = pd.Series({penalty: np.concatenate(e).mean() for penalty, e in errors.items()})
    return pooled.idxmin(), pooled


def scores(y, prediction, benchmark_mean):
    """Return MSE, MAE and out-of-sample R2 against a benchmark mean."""
    error = y - prediction
    r2 = 1 - np.sum(error**2) / np.sum((y - benchmark_mean) ** 2)
    return float(np.mean(error**2)), float(np.mean(np.abs(error))), float(r2)


def clark_west(y, pred_small, pred_big, lags=5):
    """Clark-West test for nested models: mean adjusted gain, HAC t-stat, one-sided p-value."""
    adjusted = (y - pred_small) ** 2 - (y - pred_big) ** 2 + (pred_small - pred_big) ** 2
    fit = sm.OLS(adjusted, np.ones(len(adjusted))).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    t_stat = float(fit.tvalues[0])
    return float(adjusted.mean()), t_stat, float(1 - stats.norm.cdf(t_stat))


def wald_equal_coefficients(sample, lags=5):
    """Wald test (HAC) that the four raw flow coefficients are equal, in a model with statics."""
    exog = sm.add_constant(sample[[*STATIC, *FLOW]])
    fit = sm.OLS(sample["target"], exog).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    names = list(exog.columns)
    equal = np.zeros((len(FLOW) - 1, len(names)))
    for i in range(len(FLOW) - 1):
        equal[i, names.index(FLOW[i])], equal[i, names.index(FLOW[i + 1])] = 1, -1
    result = fit.wald_test(equal, use_f=False, scalar=True)
    return float(result.statistic), float(result.pvalue)


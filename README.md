# Does order flow help predict short-term price moves? Level-3 order book of AAPL on Nasdaq

Python for Data Science project, by [@mohamadlakkis](https://github.com/mohamadlakkis),
[@surryjules](https://github.com/surryjules) and [@AspiringTrickstar](https://github.com/AspiringTrickstar).

**Report:** [report/report.pdf](report/report.pdf) (same text in [report/report.md](report/report.md)).

## Table of contents

- [Question](#question)
- [Data](#data)
- [Method](#method)
- [Main results](#main-results)
- [Reproducing the results](#reproducing-the-results)
- [Repository structure](#repository-structure)
- [How we worked](#how-we-worked)

## Question

A limit order book lists the buy and sell orders waiting to be executed. Every second, thousands
of orders are added, cancelled or executed. We ask whether this flow of orders helps to predict
the move of the Apple (AAPL) mid-price over the next 5 seconds, beyond what the current state of
the book already tells.

- **H1.** Adding the order flow of the last second to the state of the book improves the forecast.
- **H2.** Splitting this flow by type of order (added, cancelled, executed, replaced) improves it
  further.

## Data

**Source.** Nasdaq TotalView-ITCH 5.0, the message feed of the exchange: every order added,
cancelled, executed or replaced, for every stock ("level 3" data). Nasdaq publishes a few sample
days for free at <https://emi.nasdaq.com/ITCH/Nasdaq%20ITCH/>. Each day is one compressed binary
file of about 4 GB covering all stocks.

| Day | Raw file | AAPL messages kept | Used in |
|---|---|---|---|
| 2019-12-30 | `12302019.NASDAQ_ITCH50.gz` | 1,519,367 | notebooks 01, 02, 03 |
| 2019-07-30 | `07302019.NASDAQ_ITCH50.gz` | 1,315,849 | notebook 04 |

**Collection and cleaning.** The raw files cannot be read with pandas. We wrote a converter
(`book-reconstruction/`) that:

1. decodes the binary messages following the Nasdaq specification
   ([NASDAQ_GUIDE_PDF/](NASDAQ_GUIDE_PDF/)),
2. keeps the AAPL messages and the session messages,
3. turns them into a table with a fixed schema ([common/SCHEMA.md](common/SCHEMA.md)): readable
   names, typed columns, prices in dollars, timestamps in New York time,
4. checks the result as it goes (message sizes, time order, life of each order: an order cannot
   be cancelled before it was added) and stops with a report instead of failing silently,
5. writes one Parquet file and a JSON report.

Then, in the analysis, we rebuild the best bid and ask after each message, keep regular trading
hours, drop the rare crossed books and aggregate everything on a one-second grid from 09:35 to
15:55.

**What is in the repository.** The raw files are too large for Git, so a script downloads them.
We ship two small files so that every notebook runs without the download:

- `data/default/AAPL_2019-12-30.parquet` (23 MB): the converted December day, with its checksum in
  [data/default/README.md](data/default/README.md);
- `data/default/AAPL_grids_1s.parquet` (1 MB): the one-second tables of both days, used by
  notebook 04. It is rebuilt from the converted files when they are present.

## Method

**Variables, one row per second (22,801 rows per day).**

- *State of the book* at t: spread, imbalance between the shares at the best bid and at the best
  ask, total depth at these two prices.
- *Order flow* over the last second: the order flow imbalance (OFI) of Cont, Kukanov and Stoikov
  (2014), in total and split by message type, so that the four parts add up to the total.
- *Target*: change of the mid-price between t and t + 5 seconds, in ticks of one cent.

**Models.** Three nested linear regressions: M1 (state of the book), M2 = M1 + total OFI (H1),
M3 = M1 + OFI split in four (H2), plus the forecast "the price does not move" as a reference.

**Evaluation.** Fit on the first 70 % of the day, test on the last 30 %, in time order. We drop
the last 5 training seconds, whose target overlaps the test part, and scale the features on the
training part only. Models are compared by their test MSE and by the Clark-West test, made for
nested models. Standard errors are corrected for the overlap of the 5-second targets
(Newey-West). We also fit on one day and test on the other, and add two checks asked during the
review: a ridge version of M3 and a target scaled by the recent volatility.

## Main results

| Clark-West p-value (one-sided) | H1: M2 better than M1 | H2: M3 better than M2 |
|---|---|---|
| 2019-12-30, within the day | < 0.001 | 0.67 |
| 2019-07-30, within the day | 0.09 | 0.01 |
| fitted on July, tested on December | < 0.001 | 0.44 |
| fitted on December, tested on July | 0.01 | 0.47 |

- **H1 is supported.** The total OFI improves the forecast on both days and from one day to the
  other. Its effect is five times smaller on the calmer July day, so the model has to be
  re-fitted on recent data, or the target scaled by the recent volatility.
- **H2 is not supported.** The four parts of the flow have different coefficients on December 30,
  but M3 forecasts worse than M2 on the test part. July gives the opposite answer, and from one
  day to the other M3 is never better. The total OFI is as useful as its four parts.
- **The gains are small.** The best model reduces the error of "the price does not move" by less
  than 0.5 %. We measure forecast errors, not trading profits.

The limits (two days, one stock, one horizon, best prices only) are discussed in the report.

## Reproducing the results

**Requirements.** Python 3.10 or later and [uv](https://docs.astral.sh/uv/getting-started/installation/)
(`pip install uv`). Works on Linux, macOS and Windows. All dependency versions are pinned in
`uv.lock`.

**1. Install the dependencies.**

```bash
uv sync --locked --group analysis
```

**2. Run the notebooks.** Open them in VS Code with the `.venv` kernel, or run
`uv run --group analysis jupyter lab`, then run all cells in order. They read the files of
`data/default/`, so no download is needed. The outputs are saved in the notebooks.

| Notebook | Content |
|---|---|
| [01_event_descriptive_analysis.ipynb](analysis/01_event_descriptive_analysis.ipynb) | description of the messages: types, sizes, activity during the day |
| [02_mid_price_prediction.ipynb](analysis/02_mid_price_prediction.ipynb) | H1 on December 30 |
| [03_hypothesis2_decomposed_flow.ipynb](analysis/03_hypothesis2_decomposed_flow.ipynb) | H2 on December 30, ridge version of M3 |
| [04_second_day_replication.ipynb](analysis/04_second_day_replication.ipynb) | H1 and H2 on July 30 and across the two days, scaled target |

**3. Optional: rebuild the data from the raw Nasdaq files** (about 4 GB of free disk per day).

```bash
bash setup_scripts/ubuntu_setup.sh   # or macos_setup.sh / windows_setup.ps1: downloads December 30 to data/raw/
uv run itch-convert                  # writes data/processed/AAPL_2019-12-30.parquet and a JSON report
```

For July 30, download `07302019.NASDAQ_ITCH50.gz` from the same page into `data/raw/`, then run
`uv run itch-convert --source data/raw/07302019.NASDAQ_ITCH50.gz`. Notebook 04 uses the files of
`data/processed/` when they exist. The converter options are listed in
[book-reconstruction/README.md](book-reconstruction/README.md).

## Repository structure

```
book-reconstruction/   converter from raw ITCH files to Parquet (parser, checks, command line)
common/                schema shared by the converter and the analysis
analysis/              notebooks 01-04, data reader (data.py) and model code (flow_study.py)
data/default/          small reference files shipped with the repository
report/                final report (Markdown and PDF) and its figures
tests/                 tests of the converter, the reader and the download scripts
setup_scripts/         download scripts for Linux, macOS and Windows
docs/                  walkthrough of the converter code
NASDAQ_GUIDE_PDF/      Nasdaq ITCH 5.0 specification
```

The notebooks import their code from `analysis/flow_study.py` instead of repeating cells.
Notebook 03 checks that this shared code gives exactly the results of notebook 02.

## How we worked

- Every change goes through a pull request. Merging into `master` needs the CI to pass (pytest,
  ruff, mypy, download scripts), a branch up to date with `master`, and two approvals.
- Each notebook was reviewed by another member. Review comments and replies are left in the code
  (`# [review XX]` / `# [reply XX]`) and tracked in [AUDIT_LOG.md](AUDIT_LOG.md).

To run the checks locally before a pull request:

```bash
uv sync --locked --group dev
uv run --locked pytest -q
uv run --locked ruff check .
uv run --locked mypy
```

**Reference.** R. Cont, A. Kukanov and S. Stoikov (2014), "The price impact of order book events",
*Journal of Financial Econometrics* 12(1), 47-88.

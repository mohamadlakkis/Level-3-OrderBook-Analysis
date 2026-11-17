# Analysis

Here we read the Parquet data and start understanding it through statistics,
plots, and explanations. For now we are using AAPL on December 30, 2019.

## Running the notebook

From the project root, run:

```bash
uv sync --locked --group analysis
```

Then open [01_event_descriptive_analysis.ipynb](01_event_descriptive_analysis.ipynb)
in VS Code, select the project's `.venv` Python kernel, and run the cells from top
to bottom. The notebook already has saved results, so you can also read it directly.

If you prefer JupyterLab, run:

```bash
uv run --group analysis jupyter lab
```

[NOTE: the notebook uses `data/default/AAPL_2019-12-30.parquet` directly. No need
to download the raw file again or copy the Parquet into `processed/`.]

## What is in this folder?

- **The notebook:** checks the data, creates variables, and shows descriptive
  statistics and six plots with interpretations.
- **[data.py](data.py):** reads the Parquet and checks it against the schema in
  `common`. It returns a `MarketData` object containing the events and session
  information. The notebook calls it before starting the analysis.
- **`outputs/`:** generated CSV summaries and PNG figures. This folder is ignored
  by Git; the notebook keeps its displayed results.

[NOTE: interpretations are separate Markdown cells. If you change the data or
calculations, review the numbers and explanations in those cells too.]

Next we need book reconstruction and the prediction models to evaluate our
hypotheses. 

# Cross-review log

We review each other's work before it is merged. Comments are left in the code, next to what they refer to, and listed here so nothing gets lost.

## How we comment

- In a code cell or a `.py` file: `# [review <initials>] ...`
- In a notebook, after the cell: a markdown cell starting with `> **[review <initials>]**`
- The author answers in the same place: `# [reply <initials>] agreed / will fix / disagree because ...`
- When the reviewer is happy, the item is checked off below.

Rule of thumb: a few useful remarks, not a long list. Say "OK" when something is fine.

---

## Round 1: GC reviews Jules, `analysis/02_mid_price_prediction.ipynb`

- [x] Anti-leakage alignment (features on (t-1s, t], target on (t, t+5s]): OK
- [x] Chronological split, purge and train-only scaling: OK
- [x] Diebold-Mariano test on nested models (Clark-West?) and ddof, hit rate without uncertainty: addressed (Clark-West added, ddof=1 aligned, Wilson CI & McNemar test added)
- [x] Wording of the H1 conclusion: too strong for a 0.35 % MSE gain (the gain itself holds with Clark-West): addressed (conclusions and takeaways softened to reflect modest magnitude)
- [x] Zero-change baseline from `TODO.md`: addressed (Zero-change baseline added to evaluation table)
- [ ] Optional: move the order book replay to `book-reconstruction/`

---

## Round 2: JS reviews GC, `analysis/03_hypothesis2_decomposed_flow.ipynb` and `analysis/04_second_day_replication.ipynb`

GitHub PR comment: see review posted by [@surryjules](https://github.com/surryjules).

### General Pipeline & Architecture
- [x] Modularization: helpers, replay, and OFI logic cleanly moved to `analysis/flow_study.py`: OK
- [x] Alignment and leakage: strict zero-lookahead, exact additive decomposition ($\sum \text{OFI}_g = \text{OFI}_{\text{total}}$), 5-row purge: OK
- [x] Econometric testing: Clark-West test properly implemented and substituted for nested comparisons: OK
- [x] Reproduction checks: exact numerical reproduction of notebook 02 on 2019-12-30 ($< 5 \times 10^{-4}$): OK
- [x] Lightweight replication: pre-computed 1-second grid cache in `data/default/AAPL_grids_1s.parquet` allows running without downloading the 3.7 GB raw July file: OK

### Methodological & Modeling Enhancements to Address
- [ ] **Bias-variance tradeoff & Ridge shrinkage on $M_3$** (`03_hypothesis2_decomposed_flow.ipynb`, cell 9):
  The in-sample Wald test rejects coefficient equality ($p < 0.001$), but out-of-sample $M_3$ deteriorates ($MSE = 11.22 > 11.11$) due to multicollinearity and parameter estimation variance. Add an L2 Ridge regression test on $M_3$ to see if shrinking the 4 flow coefficients toward each other reduces variance and outperforms $M_2$.
- [ ] **Cross-day volatility / target scale mismatch** (`04_second_day_replication.ipynb`, cell 3):
  Target is in raw ticks ($0.01$). December volatility ($4.69$ ticks) is double July's ($2.39$ ticks), so the December $\beta_{\text{OFI}}$ is $5\times$ larger ($0.29$ vs $0.05$). The December model applied to July yields higher MSE than the zero forecast ($5.79$ vs $5.72$). Test volatility-normalized ($\Delta P / \sigma_t$) or spread-normalized targets to enable scale-invariant cross-day transferability.
- [ ] **Raw vs. standardized coefficients** (`03_hypothesis2_decomposed_flow.ipynb`, cells 6 & 9):
  Replacement orders have low dispersion ($\sigma = 154.7$ shares vs $785.4$ for additions) and only $2.4\%$ event frequency, meaning their per-share price impact ($\text{ticks/share}$) is $\approx 4\times$ that of additions. Add a brief table or note reporting both raw ($\text{ticks/share}$) and standardized ($\text{ticks/sd}$) impacts to clarify why replacement flow exhibits high leverage out-of-sample.


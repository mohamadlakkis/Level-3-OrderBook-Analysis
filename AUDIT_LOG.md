# Cross-review log

We review each other's work before it is merged. Comments are left in the code, next to what
they refer to, and listed here so nothing gets lost.

## How we comment

- In a code cell or a `.py` file: `# [review <initials>] ...`
- In a notebook, after the cell: a markdown cell starting with `> **[review <initials>]**`
- The author answers in the same place: `# [reply <initials>] agreed / will fix / disagree because ...`
- When the reviewer is happy, the item is checked off below.

Rule of thumb: a few useful remarks, not a long list. Say "OK" when something is fine.

## Round 1: GC reviews Jules, `analysis/02_mid_price_prediction.ipynb`

- [x] Anti-leakage alignment (features on (t-1s, t], target on (t, t+5s]): OK
- [x] Chronological split, purge and train-only scaling: OK
- [x] Diebold-Mariano test on nested models (Clark-West?) and ddof, hit rate without uncertainty: addressed (Clark-West added, ddof=1 aligned, Wilson CI & McNemar test added). Checked by GC: OK
- [x] Wording of the H1 conclusion: too strong for a 0.35 % MSE gain (the gain itself holds with Clark-West): addressed (conclusions and takeaways softened to reflect modest magnitude). Checked by GC: mostly OK, see the follow-up below
- [x] Zero-change baseline from `TODO.md`: addressed (Zero-change baseline added to evaluation table). Checked by GC: OK
- [x] Optional: move the order book replay to `book-reconstruction/`: kept in the notebook for now, OK
- [x] Follow-up (GC): MAE of Model 1 vs the zero baseline, a few strong words and untested explanations, Wilson wording, tab typo in the last cell: addressed (MAE nuance clarified, speculative phrasing softened, Wilson/McNemar wording adjusted, typo fixed). Checked by GC: OK, with the MAE figures of Model 2 corrected (2.4943, not 2.4912). Round 1 approved by GC

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
- [x] **Bias-variance tradeoff & Ridge shrinkage on $M_3$** (`03_hypothesis2_decomposed_flow.ipynb`, cell 9):
  The in-sample Wald test rejects coefficient equality ($p < 0.001$), but out-of-sample $M_3$ deteriorates ($MSE = 11.22 > 11.11$) due to multicollinearity and parameter estimation variance. Add an L2 Ridge regression test on $M_3$ to see if shrinking the 4 flow coefficients toward each other reduces variance and outperforms $M_2$.
- [x] **Cross-day volatility / target scale mismatch** (`04_second_day_replication.ipynb`, cell 3):
  Target is in raw ticks ($0.01$). December volatility ($4.69$ ticks) is double July's ($2.39$ ticks), so the December $\beta_{\text{OFI}}$ is $5\times$ larger ($0.29$ vs $0.05$). The December model applied to July yields higher MSE than the zero forecast ($5.79$ vs $5.72$). Test volatility-normalized ($\Delta P / \sigma_t$) or spread-normalized targets to enable scale-invariant cross-day transferability.
- [x] **Raw vs. standardized coefficients** (`03_hypothesis2_decomposed_flow.ipynb`, cells 6 & 9):
  Replacement orders have low dispersion ($\sigma = 154.7$ shares vs $785.4$ for additions) and only $2.4\%$ event frequency, meaning their per-share price impact ($\text{ticks/share}$) is $\approx 4\times$ that of additions. Add a brief table or note reporting both raw ($\text{ticks/share}$) and standardized ($\text{ticks/sd}$) impacts to clarify why replacement flow exhibits high leverage out-of-sample.

Replies from GC (round 2):
- Ridge on $M_3$: done in notebook 03, section 8, and on both days in notebook 04, section 2. The penalty pulls the four coefficients towards each other and is chosen on the training part only. December: as good as $M_2$, not better (MSE 11.106 vs 11.108, Clark-West p = 0.17). July: keeps the gain of $M_3$ (p = 0.005).
- Scaled target: done in notebook 04, section 4 (target divided by the volatility of the last 5 minutes, and by the spread). It removes the cross-day MSE cost of the December models on July, and H1 stays significant. The H2 result moves a lot with the volatility window (p from 0.005 to 0.30), so we do not count it as evidence for H2.
- Raw vs standardized: done in notebook 03, cell 16 (coefficients per 1000 shares). Replace is about 4.7x add per share with the training sd (1.57 vs 0.34 tick), consistent with your ~4x.

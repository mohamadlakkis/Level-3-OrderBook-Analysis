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
- [x] Diebold-Mariano test on nested models (Clark-West?) and ddof, hit rate without uncertainty: addressed (Clark-West added, ddof=1 aligned, Wilson CI & McNemar test added)
- [x] Wording of the H1 conclusion: too strong for a 0.35 % MSE gain (the gain itself holds with Clark-West): addressed (conclusions and takeaways softened to reflect modest magnitude)
- [x] Zero-change baseline from `TODO.md`: addressed (Zero-change baseline added to evaluation table)
- [ ] Optional: move the order book replay to `book-reconstruction/`

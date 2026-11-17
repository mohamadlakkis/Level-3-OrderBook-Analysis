# Next Steps 

## Where we are now

We already have the [descriptive notebook](analysis/01_event_descriptive_analysis.ipynb).
It shows us how the events behave, their sizes, and how activity changes during
the day. This helps us decide what variables to use, but we still need to check
whether these variables help predict future mid-price changes.

## What we want to test

1. Does adding aggregated order flow improve predictions compared to the static book alone?
2. Does separating additions, cancellations, and aggressive execution flow improve predictions even more?

## So direct next steps

1. **Reconstruct the book.** We need the mid-price, book state, and the quantities
   and sides missing from some messages. Then create features using the previous
   **one second** and predict `mid(t + 5 seconds) - mid(t)`.
   [NOTE: the current minute-level summaries are for exploration; rebuild the
   features from events for the one-second window.]
2. **Check these new variables.** Look at their distributions and how often the
   five-second price change is zero. This connects our descriptive work to the
   actual prediction problem.
3. **Compare the models:** zero-change forecast, static book, static book +
   aggregated flow, and static book + decomposed flow. Start with the same linear
   or ridge regression for the three feature sets so the comparison is fair.
4. **Train on earlier data and evaluate on later data.** Compare MSE and MAE on
   the same timestamps. Fit preprocessing only on training data, and remove
   training observations whose five-second target reaches the next split.
   [NOTE: do not randomly shuffle the rows; nearby targets overlap.]
5. **Check which flow groups help.** Try each group individually with the static
   book, then remove one group at a time from the full model. Explain whether
   the results support our two hypotheses, including uncertainty and limitations.

Put this in `analysis/02_midprice_prediction.ipynb`, with explanations of the
choices and results, like we did for the descriptive notebook.

[NOTE: our current reference data is December 30, 2019. Use it to develop the
pipeline, then repeat the checks on the 2025 data before reporting those results.]

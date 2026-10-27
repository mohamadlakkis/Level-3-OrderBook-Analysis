# AAPL Limit Order Book (LOB) - Descriptive Statistics Report

Generated from 100ms periodic order book snapshots (TotalView-ITCH 5.0).

## 1. High-Frequency Market Microstructure Properties

| Property                                     | Value                   |
|:---------------------------------------------|:------------------------|
| Total Snapshots Analyzed                     | 18,000                  |
| Time Horizon                                 | 09:30:00 - 09:59:59 EST |
| Starting Mid-Price                           | $289.6350               |
| Ending Mid-Price                             | $286.8350               |
| Net Session Drift                            | $-2.8000 (-96.67 bps)   |
| Spread = 1 Tick (0.01$)                      | 0.00 %                  |
| Spread = 2 Ticks (0.02$)                     | 0.00 %                  |
| Spread > 2 Ticks (>0.02$)                    | 86.71 %                 |
| Locked Market (Spread = 0)                   | 0.00 %                  |
| Realized Volatility (30 min)                 | 0.51 %                  |
| Annualized Realized Volatility               | 29.08 %                 |
| 100ms Return Autocorrelation (Lag 1)         | 0.0427                  |
| Spread Autocorrelation (Lag 1 / 100ms)       | 0.8605                  |
| Spread Autocorrelation (Lag 10 / 1.0s)       | 0.5099                  |
| L1 Imbalance Autocorrelation (Lag 1 / 100ms) | 0.7292                  |
| L1 Imbalance Autocorrelation (Lag 10 / 1.0s) | 0.2057                  |

---

## 2. Statistical Distribution of Core LOB Variables

| Metric                          |             Mean |        Std Dev |          Min |              25% |     Median (50%) |              75% |              Max |            IQR |   Skewness |    Kurtosis |
|:--------------------------------|-----------------:|---------------:|-------------:|-----------------:|-----------------:|-----------------:|-----------------:|---------------:|-----------:|------------:|
| Mid-Price ($)                   |    287.47        |      0.802203  |   286.35     |    286.925       |    287.195       |    287.57        |    289.635       |      0.645     |  1.13563   |   0.0214488 |
| Micro-Price ($)                 |    287.47        |      0.80259   |   286.341    |    286.923       |    287.2         |    287.573       |    289.693       |      0.650833  |  1.13598   |   0.0238494 |
| Bid-Ask Spread ($)              |      0.0385056   |      0.0152578 |     0.01     |      0.03        |      0.04        |      0.05        |      0.21        |      0.02      |  1.03372   |   6.91535   |
| Relative Spread (bps)           |      1.33896     |      0.52882   |     0.345513 |      1.04415     |      1.39121     |      1.7359      |      7.2505      |      0.69175   |  1.01634   |   6.75472   |
| Micro-Mid Discrepancy (¢)       |      0.735838    |      0.657161  |     0        |      0.184834    |      0.656498    |      1.07692     |      5.75959     |      0.892089  |  1.07764   |   1.34332   |
| Best Bid Size (Shares)          |    252.865       |    568.664     |     1        |    100           |    110           |    227           |  10042           |    127         |  9.95043   | 124.512     |
| Best Ask Size (Shares)          |    177.41        |    211.444     |     1        |    100           |    101           |    200           |   7499           |    100         | 13.099     | 332.592     |
| Top-of-Book Total Size (Shares) |    430.274       |    614.432     |     4        |    200           |    300           |    443           |  10358           |    243         |  8.47898   |  94.4506    |
| L1 Imbalance [-1, +1]           |      0.0297549   |      0.496408  |    -0.996327 |     -0.333333    |      0           |      0.351351    |      0.999774    |      0.684685  | -0.0709238 |  -0.620675  |
| Top-5 Bid Volume (Shares)       |   1439.36        |   1073.02      |   221        |    932           |   1209           |   1600           |  22987           |    668         |  5.46244   |  47.1722    |
| Top-5 Ask Volume (Shares)       |   1318.26        |   1125.19      |   252        |    900           |   1118           |   1410           |  13604           |    510         |  7.21016   |  63.148     |
| Total Book Bid Depth (Shares)   |      1.43701e+06 | 215149         | 20266        |      1.3941e+06  |      1.40341e+06 |      1.55542e+06 |      1.6126e+06  | 161319         | -4.97075   |  28.7216    |
| Total Book Ask Depth (Shares)   | 595743           |  94295.7       | 63201        | 538604           | 571996           | 682527           | 706589           | 143923         | -2.28128   |  10.5939    |
| Total Book Depth (Shares)       |      2.03276e+06 | 302932         | 83467        |      1.94098e+06 |      1.96568e+06 |      2.24157e+06 |      2.31255e+06 | 300591         | -4.22857   |  23.5411    |
| Total Book Imbalance [-1, +1]   |      0.403709    |      0.0941018 |    -0.514395 |      0.393739    |      0.416284    |      0.443173    |      0.460852    |      0.0494333 | -6.19744   |  40.384     |

---

## 3. Average Liquidity Depth Ladder (Top-5 Levels)

| Level   |   Avg Bid Dist from Mid (¢) |   Avg Bid Shares |   Avg Ask Dist from Mid (¢) |   Avg Ask Shares |
|:--------|----------------------------:|-----------------:|----------------------------:|-----------------:|
| Level 1 |                     1.92528 |          252.865 |                     1.92528 |          177.41  |
| Level 2 |                     3.08328 |          249.15  |                     3.15439 |          212.771 |
| Level 3 |                     4.141   |          284.355 |                     4.24172 |          271.217 |
| Level 4 |                     5.19122 |          312.574 |                     5.33728 |          320.568 |
| Level 5 |                     6.23078 |          340.414 |                     6.39028 |          336.29  |

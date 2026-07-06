# Market Watchlist

`telos_market_watchlist.json` defines the thesis-linked market watchlist used by:

```powershell
python telos_market.py run
```

The output is a research-priority ranking, not investment advice, not a buy/sell
signal and not a portfolio allocation.

## Structure

```json
{
  "version": 1,
  "name": "Telos 100",
  "benchmarks": [],
  "themes": {},
  "stocks": []
}
```

## Benchmarks

Benchmarks are used for comparison in the daily market report.

Default examples:

```json
[
  { "symbol": "^GSPC", "name": "S&P 500" },
  { "symbol": "^IXIC", "name": "Nasdaq Composite" }
]
```

You can replace or extend them with other Yahoo Finance symbols, for example
`^DJI`, `^RUT`, `QQQ`, `SPY` or sector ETFs.

## Themes

Themes connect stocks to the worldview you want Telos to monitor.

```json
{
  "frontier_ai": {
    "label": "Frontier AI",
    "claim_ids": []
  },
  "energy_grid": {
    "label": "Energy / Grid",
    "claim_ids": []
  }
}
```

`claim_ids` can stay empty. After you create local claims with
`python telos.py claim ...`, you can link a theme to those claim IDs. Stronger
linked claims make the theme more important in the market-priority score.

## Stocks

Each stock needs a Yahoo Finance symbol, a readable name and theme exposures:

```json
{
  "symbol": "MSFT",
  "name": "Microsoft",
  "themes": {
    "frontier_ai": 1.0,
    "compute": 0.7,
    "agent_workflows": 0.6
  }
}
```

Theme values are relative exposure scores from `0.0` to `1.0`. They are not
portfolio weights. They tell Telos why this stock belongs in the research
universe.

## Replace the Telos 100

The current `telos_market.py` implementation expects exactly 100 stocks:

```text
Telos 100 must contain exactly 100 stocks
```

To fully replace the list:

1. Edit `themes` so they match your research theses.
2. Replace the `stocks` array with exactly 100 stock objects.
3. Make sure every stock uses theme keys that exist under `themes`.
4. Keep or replace `benchmarks`.
5. Run:

```powershell
python telos_market.py run
```

If you want a smaller or larger list, either fill the config to 100 names or
edit the validation rule in `telos_market.py`. For a public template, keeping
100 forces a consistent index-like comparison.

## How Ranking Works

The market stage combines:

- linked claim strength from Telos claims and beliefs
- stock theme exposure from the watchlist
- relative price movement and attention signals
- benchmark comparison

The result is a monitoring priority. A stock can move higher because its linked
theme became more important, because its price action changed, or because the
worldview shifted. It should be reviewed by a human before any financial
decision.

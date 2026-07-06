#!/usr/bin/env python3
"""Build the daily Telos 100 thesis-linked market ranking."""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import json
import math
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
TELOS_DIR = ROOT / "telos"
DB_PATH = TELOS_DIR / "telos.db"
CONFIG_PATH = ROOT / "telos_market_watchlist.json"
MARKET_DIR = TELOS_DIR / "markets"
PRICE_DIR = MARKET_DIR / "prices"
USER_AGENT = "Mozilla/5.0 TelosMarket/0.1"


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    stocks = config.get("stocks", [])
    symbols = [stock["symbol"] for stock in stocks]
    if len(stocks) != 100:
        raise SystemExit(f"Telos 100 must contain exactly 100 stocks, found {len(stocks)}")
    if len(set(symbols)) != len(symbols):
        raise SystemExit("Duplicate stock symbols in Telos 100")
    return config


def fetch_chart(symbol: str, attempts: int = 2) -> dict[str, Any]:
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=3mo&interval=1d&events=div%2Csplits"
    last_error = ""
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=25) as response:
                payload = json.loads(response.read().decode("utf-8"))
            result = payload["chart"]["result"][0]
            timestamps = result.get("timestamp") or []
            quote = result.get("indicators", {}).get("quote", [{}])[0]
            closes = quote.get("close") or []
            points = [(ts, float(close)) for ts, close in zip(timestamps, closes) if close is not None]
            if not points:
                raise ValueError("No daily closes returned")
            return summarize_prices(symbol, points, result.get("meta", {}), url)
        except (urllib.error.URLError, TimeoutError, KeyError, IndexError, TypeError, ValueError) as exc:
            last_error = str(exc)
            if attempt + 1 < attempts:
                time.sleep(1.5 * (attempt + 1))
    return {"symbol": symbol, "status": "error", "error": last_error, "url": url}


def pct_change(new: float, old: float) -> float:
    return (new / old - 1.0) * 100.0


def summarize_prices(symbol: str, points: list[tuple[int, float]], meta: dict[str, Any], url: str) -> dict[str, Any]:
    closes = [point[1] for point in points]
    latest_ts, latest = points[-1]
    result: dict[str, Any] = {
        "symbol": symbol,
        "status": "ok",
        "currency": meta.get("currency"),
        "exchange": meta.get("exchangeName"),
        "price": round(latest, 4),
        "price_date": dt.datetime.fromtimestamp(latest_ts, dt.timezone.utc).date().isoformat(),
        "return_1d": round(pct_change(latest, closes[-2]), 3) if len(closes) >= 2 else None,
        "return_5d": round(pct_change(latest, closes[-6]), 3) if len(closes) >= 6 else None,
        "return_20d": round(pct_change(latest, closes[-21]), 3) if len(closes) >= 21 else None,
        "url": url,
    }
    return result


def fetch_all(symbols: list[str], workers: int) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(fetch_chart, symbol): symbol for symbol in symbols}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results[result["symbol"]] = result
    return results


def claim_scores() -> dict[str, float]:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT id, confidence, importance FROM claims WHERE status = 'active'").fetchall()
    con.close()
    return {row["id"]: float(row["confidence"]) * float(row["importance"]) * 100.0 for row in rows}


def theme_scores(config: dict[str, Any], claims: dict[str, float]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for theme_id, theme in config["themes"].items():
        values = [claims[claim_id] for claim_id in theme.get("claim_ids", []) if claim_id in claims]
        scores[theme_id] = sum(values) / len(values) if values else 50.0
    return scores


def weighted_average(values: list[tuple[float, float]], default: float = 50.0) -> float:
    denominator = sum(weight for _, weight in values)
    if denominator <= 0:
        return default
    return sum(value * weight for value, weight in values) / denominator


def previous_ranks(date: str) -> dict[str, int]:
    candidates = sorted(path for path in PRICE_DIR.glob("*.json") if path.stem < date)
    if not candidates:
        return {}
    data = json.loads(candidates[-1].read_text(encoding="utf-8"))
    return {item["symbol"]: int(item["rank"]) for item in data.get("ranking", [])}


def value_or_zero(value: Any) -> float:
    return float(value) if value is not None else 0.0


def build_ranking(config: dict[str, Any], prices: dict[str, dict[str, Any]], date: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    claims = claim_scores()
    themes = theme_scores(config, claims)
    benchmark_rows = [prices[item["symbol"]] for item in config["benchmarks"] if prices.get(item["symbol"], {}).get("status") == "ok"]
    benchmark_returns = {
        period: weighted_average([(value_or_zero(row.get(period)), 1.0) for row in benchmark_rows], default=0.0)
        for period in ("return_1d", "return_5d", "return_20d")
    }
    rows: list[dict[str, Any]] = []
    for stock in config["stocks"]:
        price = prices.get(stock["symbol"], {"status": "error", "error": "missing"})
        thesis = weighted_average([(themes.get(theme_id, 50.0), float(weight)) for theme_id, weight in stock["themes"].items()])
        if price.get("status") == "ok":
            relative = (
                0.20 * (value_or_zero(price.get("return_1d")) - benchmark_returns["return_1d"])
                + 0.35 * (value_or_zero(price.get("return_5d")) - benchmark_returns["return_5d"])
                + 0.45 * (value_or_zero(price.get("return_20d")) - benchmark_returns["return_20d"])
            )
            momentum = 50.0 + 45.0 * math.tanh(relative / 12.0)
            attention = min(100.0, 8.0 * abs(value_or_zero(price.get("return_1d"))) + 2.0 * abs(value_or_zero(price.get("return_5d"))))
            priority = 0.72 * thesis + 0.20 * momentum + 0.08 * attention
        else:
            momentum = 50.0
            attention = 0.0
            priority = 0.85 * thesis + 0.15 * momentum
        rows.append({
            **stock,
            **price,
            "thesis_score": round(thesis, 2),
            "momentum_score": round(momentum, 2),
            "attention_score": round(attention, 2),
            "priority_score": round(priority, 2),
            "theme_labels": [config["themes"][theme_id]["label"] for theme_id in stock["themes"]],
        })
    rows.sort(key=lambda row: (row["priority_score"], row["thesis_score"]), reverse=True)
    old = previous_ranks(date)
    for rank, row in enumerate(rows, 1):
        row["rank"] = rank
        row["rank_change"] = old.get(row["symbol"], rank) - rank if old else 0

    valid = [row for row in rows if row.get("status") == "ok"]
    index_stats: dict[str, Any] = {"constituents_with_prices": len(valid), "benchmark_returns": benchmark_returns}
    for period in ("return_1d", "return_5d", "return_20d"):
        index_stats[f"equal_weight_{period}"] = round(weighted_average([(value_or_zero(row.get(period)), 1.0) for row in valid], 0.0), 3)
        index_stats[f"priority_weighted_{period}"] = round(weighted_average([(value_or_zero(row.get(period)), row["priority_score"]) for row in valid], 0.0), 3)
    return rows, index_stats


def fmt(value: Any, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    return f"{float(value):+.2f}{suffix}"


def write_report(config: dict[str, Any], prices: dict[str, dict[str, Any]], ranking: list[dict[str, Any]], stats: dict[str, Any], date: str) -> Path:
    MARKET_DIR.mkdir(parents=True, exist_ok=True)
    path = MARKET_DIR / f"{date}-market-watch.md"
    benchmarks = {item["symbol"]: item for item in config["benchmarks"]}
    lines = [
        f"# Telos 100 Market Watch - {date}", "",
        "> Research watchlist only. Priority is a monitoring score, not a buy/sell recommendation or portfolio weight.", "",
        "## Market Frame", "",
    ]
    for symbol, definition in benchmarks.items():
        row = prices.get(symbol, {})
        lines.append(f"- {definition['name']}: `{row.get('price', 'n/a')}` | 1d {fmt(row.get('return_1d'), '%')} | 5d {fmt(row.get('return_5d'), '%')} | 20d {fmt(row.get('return_20d'), '%')}")
    lines.extend([
        f"- Telos 100 equal-weight: 1d {fmt(stats.get('equal_weight_return_1d'), '%')} | 5d {fmt(stats.get('equal_weight_return_5d'), '%')} | 20d {fmt(stats.get('equal_weight_return_20d'), '%')}",
        f"- Telos 100 priority-weighted: 1d {fmt(stats.get('priority_weighted_return_1d'), '%')} | 5d {fmt(stats.get('priority_weighted_return_5d'), '%')} | 20d {fmt(stats.get('priority_weighted_return_20d'), '%')}",
        f"- Valid price series: `{stats['constituents_with_prices']}/100`", "",
        "## Ranking", "",
        "| Rank | Move | Symbol | Company | Priority | Thesis | Momentum | 1d | 5d | 20d | Themes |",
        "|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---|",
    ])
    for row in ranking:
        move = row["rank_change"]
        lines.append(
            f"| {row['rank']} | {move:+d} | {row['symbol']} | {row['name']} | {row['priority_score']:.1f} | "
            f"{row['thesis_score']:.1f} | {row['momentum_score']:.1f} | {fmt(row.get('return_1d'), '%')} | "
            f"{fmt(row.get('return_5d'), '%')} | {fmt(row.get('return_20d'), '%')} | {', '.join(row['theme_labels'])} |"
        )
    errors = [row for row in ranking if row.get("status") != "ok"]
    if errors:
        lines.extend(["", "## Price Errors", ""])
        for row in errors:
            lines.append(f"- {row['symbol']}: {row.get('error', 'unknown error')}")
    lines.extend([
        "", "## Method", "",
        "- Thesis score follows the current confidence and importance of linked Telos claims.",
        "- Momentum compares 1-day, 5-day and 20-day performance with the average of the S&P 500 and Nasdaq Composite.",
        "- Attention increases when a stock moves sharply in either direction.",
        "- Priority = 72% thesis score + 20% relative momentum + 8% movement attention.",
        "- Price data comes from Yahoo Finance's public chart endpoint and should be checked against a licensed source before financial use.", "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def run(args: argparse.Namespace) -> None:
    config = load_config(Path(args.config))
    date = args.date or dt.datetime.now().astimezone().date().isoformat()
    symbols = [item["symbol"] for item in config["benchmarks"]] + [item["symbol"] for item in config["stocks"]]
    prices = fetch_all(symbols, args.workers)
    ranking, stats = build_ranking(config, prices, date)
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    snapshot = {
        "date": date,
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "provider": config["price_provider"],
        "benchmarks": config["benchmarks"],
        "prices": prices,
        "theme_scores": theme_scores(config, claim_scores()),
        "index_stats": stats,
        "ranking": ranking,
    }
    snapshot_path = PRICE_DIR / f"{date}.json"
    snapshot_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    report = write_report(config, prices, ranking, stats, date)
    print(f"watchlist=100 valid_prices={stats['constituents_with_prices']} report={report.relative_to(ROOT)} snapshot={snapshot_path.relative_to(ROOT)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the Telos 100 daily market ranking.")
    parser.add_argument("run", nargs="?")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--date")
    parser.add_argument("--workers", type=int, default=6)
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())

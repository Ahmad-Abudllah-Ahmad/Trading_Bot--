"""
Backtest runner — evaluates TradingAgents decisions over historical data.

Run this BEFORE going live to confirm the system generates positive alpha.
Results are printed as a table and saved to autonomous/logs/backtest_results.txt.

Usage (from D:\\Trading Bot):
    .venv\\Scripts\\python.exe autonomous\\backtest_runner.py

Configuration is at the top of this file.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

from tradingagents.backtest import iter_grid, run_backtest, summarize
from tradingagents.default_config import DEFAULT_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(Path(__file__).parent / "logs" / "backtest.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("backtest_runner")


# ════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION — adjust these before running
# ════════════════════════════════════════════════════════════════════════════

# Tickers to backtest
TICKERS = ["AAPL", "NVDA", "MSFT", "GOOGL"]

# Date range — start further back for more data points
BACKTEST_DAYS = 90          # How many calendar days back to start
EVERY_N_DAYS  = 7           # One analysis every N days (7 = weekly)

# Analysts to include (all four gives the most complete picture)
ANALYSTS = ("market", "social", "news", "fundamentals")


def _build_backtest_config() -> dict:
    """Same config as the live runner, but with checkpointing off for speed."""
    cfg = DEFAULT_CONFIG.copy()
    cfg["llm_provider"]         = "openai"
    cfg["quick_think_llm"]      = "gpt-4o-mini"
    cfg["deep_think_provider"]  = "anthropic"
    cfg["deep_think_llm"]       = "claude-sonnet-4-5"
    cfg["max_debate_rounds"]    = 1      # Faster for backtesting
    cfg["max_risk_discuss_rounds"] = 1
    cfg["temperature"]          = 0.3
    cfg["checkpoint_enabled"]   = False  # Not needed for backtest cells
    cfg["holding_period_days"]  = 5
    cfg["results_dir"] = str(Path(__file__).parent / "reports" / "backtest")
    return cfg


def _print_summary(summary, tickers: list[str], start: str, end: str):
    """Pretty-print backtest results to console and save to file."""
    lines = [
        "",
        "═" * 65,
        f"  BACKTEST RESULTS",
        f"  Tickers : {', '.join(tickers)}",
        f"  Period  : {start}  →  {end}",
        f"  Holding : {summary.holding}",
        f"  Resolved: {summary.resolved}  |  Pending: {summary.pending}  |  Unscored: {summary.unscored}",
        "═" * 65,
        "",
        f"  {'Rating':<14} {'Count':>6} {'Hit Rate':>10} {'Mean Alpha':>12}",
        f"  {'─'*14} {'─'*6} {'─'*10} {'─'*12}",
    ]

    for rating, score in summary.by_rating.items():
        hit = f"{score.hit_rate*100:.1f}%" if score.hit_rate is not None else "  n/a"
        alpha = f"{score.mean_alpha*100:+.2f}%"
        lines.append(f"  {rating:<14} {score.count:>6} {hit:>10} {alpha:>12}")

    lines += [
        "",
        "  HIT RATE > 55% and MEAN ALPHA > 0% = system has edge",
        "  HIT RATE < 50% or MEAN ALPHA < 0% = do NOT go live yet",
        "═" * 65,
        "",
    ]

    output = "\n".join(lines)
    print(output)

    # Save to file
    result_path = Path(__file__).parent / "logs" / "backtest_results.txt"
    with open(result_path, "w", encoding="utf-8") as fh:
        fh.write(f"Generated: {datetime.now().isoformat()}\n")
        fh.write(output)
    print(f"  Results saved to: {result_path}\n")


def main():
    today     = datetime.now().date()
    end_date  = (today - timedelta(days=6)).strftime("%Y-%m-%d")   # Leave room for settlement
    start_date = (today - timedelta(days=BACKTEST_DAYS)).strftime("%Y-%m-%d")

    dates = list(iter_grid(start_date, end_date, every_n_days=EVERY_N_DAYS))

    print(f"\n  Starting backtest: {len(TICKERS)} tickers × {len(dates)} dates"
          f" = {len(TICKERS) * len(dates)} total cells")
    print(f"  Date range: {start_date} → {end_date}")
    print(f"  This may take a while (each cell is a full agent run).\n")

    cfg = _build_backtest_config()

    result = run_backtest(
        tickers          = TICKERS,
        dates            = dates,
        config           = cfg,
        selected_analysts= list(ANALYSTS),
    )

    logger.info(
        "Backtest done | cells=%d | skipped=%d | failures=%d",
        result.cells_run, result.skipped, result.failures,
    )

    if result.cells_run == 0:
        print("\n  ❌ No cells ran successfully. Check your API keys.\n")
        return

    summary = summarize(result)
    _print_summary(summary, TICKERS, start_date, end_date)


if __name__ == "__main__":
    main()


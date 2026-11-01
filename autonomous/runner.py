"""
Main autonomous trading runner.

Entry point for the scheduled daily run.  Orchestrates:
  1. TradingAgents analysis for each ticker in WATCHLIST
  2. Risk guardrail evaluation
  3. Telegram alerts (and optional human approval gating)
  4. Alpaca order execution
  5. Trade logging and end-of-day summary

Usage (from D:\\Trading Bot):
    .venv\\Scripts\\python.exe autonomous\\runner.py

Scheduled via Windows Task Scheduler — see setup guide.
"""
from __future__ import annotations

import io
import logging
import sys
from datetime import datetime
from pathlib import Path

# Force UTF-8 on Windows consoles
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Path setup ───────────────────────────────────────────────────────────────
# Add project root so tradingagents is importable from the venv
_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")

# ── Project imports ──────────────────────────────────────────────────────────
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.agents.rating import is_review
from tradingagents.portfolio import PortfolioContext

from broker import AlpacaBroker
from notifier import TelegramNotifier
from risk_guardrails import RiskGuardrails, TradeSignal
from trade_logger import TradeLogger

# ── Logging ───────────────────────────────────────────────────────────────────
_LOG_DIR = Path(__file__).parent / "logs"
_LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "runner.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("runner")


# ════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION — edit this section to change tickers, models, risk limits
# ════════════════════════════════════════════════════════════════════════════

# Tickers to analyse every day.
# Use Yahoo Finance format: AAPL, BTC-USD, 0700.HK, RELIANCE.NS, etc.
WATCHLIST: list[str] = [
    "AAPL",   # Apple — large-cap, liquid, well-covered by fundamentals
    "NVDA",   # NVIDIA — AI/semiconductor, high-momentum
    "MSFT",   # Microsoft — defensive tech
    "GOOGL",  # Alphabet — ad revenue proxy for macro
    "BTC-USD",# Bitcoin — crypto, 24/7
]

# Risk guardrail configuration
RISK_CONFIG: dict = {
    "max_single_position_pct":    0.20,   # Max 20% of equity in any one ticker
    "max_invested_pct":           0.80,   # Always keep ≥20% cash
    "min_account_equity":         50.0,   # Hard floor — stop trading if below $50
    "max_daily_trades":           4,      # No more than 4 orders per day
    "auto_execute_ratings":       ["Hold"],                      # Auto-execute (no action needed)
    "human_approval_ratings":     ["Buy", "Sell"],               # Require Telegram approval
    "buy_fraction_overweight":    0.50,   # Overweight = buy half-size
    "sell_fraction_underweight":  0.50,   # Underweight = sell half position
}


def _build_ta_config() -> dict:
    """
    TradingAgents config optimised for autonomous use.

    Uses OpenAI gpt-4o-mini for fast analyst work (cheap),
    and Claude claude-sonnet-4-5 for the Research Manager and Portfolio
    Manager (better reasoning for the decision that matters).

    Change quick_think_llm / deep_think_llm to adjust cost vs quality.
    """
    cfg = DEFAULT_CONFIG.copy()

    # LLMs — dual-provider: OpenAI fast / Claude deep
    cfg["llm_provider"]          = "openai"
    cfg["quick_think_llm"]       = "gpt-4o-mini"       # analysts, researchers, trader
    cfg["deep_think_provider"]   = "anthropic"
    cfg["deep_think_llm"]        = "claude-sonnet-4-5"  # research manager, portfolio manager

    # Quality / thoroughness knobs
    cfg["max_debate_rounds"]        = 2   # Bull & Bear each speak twice
    cfg["max_risk_discuss_rounds"]  = 1   # One full risk round
    cfg["temperature"]              = 0.3 # More consistent, less random
    cfg["max_tool_rounds"]          = 10  # Cap tool calls to save tokens

    # Holding period for memory settlement
    cfg["holding_period_days"] = 5        # Score each decision after 5 trading days

    # Checkpoint resume — recovers from crashes mid-run
    cfg["checkpoint_enabled"] = True

    # Save reports under autonomous/reports/
    cfg["results_dir"] = str(Path(__file__).parent / "reports")

    return cfg


def _build_portfolio(broker: AlpacaBroker) -> PortfolioContext | None:
    """Build a PortfolioContext from actual Alpaca positions."""
    try:
        acct      = broker.get_account()
        positions = broker.get_positions()
        return PortfolioContext.model_validate({
            "cash":      acct["cash"],
            "currency":  "USD",
            "positions": [
                {
                    "ticker":        sym,
                    "quantity":      pos["qty"],
                    "average_price": pos["avg_entry_price"],
                }
                for sym, pos in positions.items()
            ],
        })
    except Exception as exc:
        logger.warning("Could not build portfolio context: %s", exc)
        return None


def _run_analysis(
    ticker: str,
    ta: TradingAgentsGraph,
    portfolio: PortfolioContext | None,
    today: str,
) -> TradeSignal | None:
    """Run TradingAgents for one ticker, return a TradeSignal or None on failure."""
    logger.info("━━━ Analysing %s for %s ━━━", ticker, today)
    try:
        state, rating = ta.propagate(ticker, today, portfolio=portfolio)

        decision_text    = state.get("final_trade_decision", "")
        executive_summ   = state.get("final_rating_details", {}).get("executive_summary", decision_text[:300])
        investment_thesis = state.get("final_rating_details", {}).get("investment_thesis", "")
        price_target     = state.get("final_rating_details", {}).get("price_target")
        time_horizon     = state.get("final_rating_details", {}).get("time_horizon")

        # Save per-ticker report
        try:
            ta.save_reports(state, ticker)
        except Exception as exc:
            logger.warning("Could not save report for %s: %s", ticker, exc)

        signal = TradeSignal(
            ticker            = ticker,
            rating            = rating,
            executive_summary = executive_summ,
            investment_thesis = investment_thesis,
            price_target      = price_target,
            time_horizon      = time_horizon,
            full_decision     = decision_text,
            analysis_date     = today,
        )
        logger.info("Analysis complete: %s → %s", ticker, rating)
        return signal

    except Exception as exc:
        logger.error("Analysis failed for %s: %s", ticker, exc)
        return None


def _execute_signal(
    signal: TradeSignal,
    broker: AlpacaBroker,
    guardrails: RiskGuardrails,
    notifier: TelegramNotifier,
    trade_log: TradeLogger,
) -> bool:
    """
    Apply guardrails to a signal, then execute or alert as appropriate.
    Returns True if an order was placed.
    """
    acct      = broker.get_account()
    positions = broker.get_positions()

    verdict = guardrails.check(signal, acct["equity"], acct["cash"], positions)

    # ── Blocked ──────────────────────────────────────────────────────────────
    if not verdict.approved:
        logger.warning("BLOCKED %s (%s): %s", signal.ticker, signal.rating, verdict.reason)
        notifier.send_blocked(signal.ticker, signal.rating, verdict.reason)
        trade_log.log_signal(
            ticker=signal.ticker, rating=signal.rating,
            summary=signal.executive_summary, risk_approved=False,
            risk_reason=verdict.reason, action=verdict.action,
            executed=False,
        )
        return False

    # ── Hold — nothing to do ─────────────────────────────────────────────────
    if verdict.action == "hold":
        logger.info("HOLD %s — no order placed.", signal.ticker)
        trade_log.log_signal(
            ticker=signal.ticker, rating=signal.rating,
            summary=signal.executive_summary, risk_approved=True,
            risk_reason=verdict.reason, action="hold",
            executed=False,
        )
        return False

    # ── Needs human approval ─────────────────────────────────────────────────
    if verdict.requires_human:
        notifier.send_signal(
            ticker=signal.ticker, rating=signal.rating,
            summary=signal.executive_summary,
            requires_human=True, reason=verdict.reason,
            equity=acct["equity"],
        )
        trade_log.log_signal(
            ticker=signal.ticker, rating=signal.rating,
            summary=signal.executive_summary, risk_approved=True,
            risk_reason=verdict.reason, action=verdict.action,
            executed=False, awaiting_approval=True,
        )
        logger.info("Awaiting human approval for %s (%s).", signal.ticker, signal.rating)
        return False

    # ── Auto-execute ──────────────────────────────────────────────────────────
    notifier.send_signal(
        ticker=signal.ticker, rating=signal.rating,
        summary=signal.executive_summary,
        requires_human=False, reason=verdict.reason,
        equity=acct["equity"],
    )

    result = None
    if verdict.action == "buy":
        dollar_amount = acct["equity"] * verdict.position_pct
        result = broker.buy(signal.ticker, dollar_amount)

    elif verdict.action == "sell":
        result = broker.sell_all(signal.ticker)

    elif verdict.action == "reduce":
        pos = positions.get(signal.ticker, {})
        qty = pos.get("qty", 0) * verdict.position_pct
        result = broker.sell_qty(signal.ticker, qty)

    if result is None:
        logger.error("Unhandled action '%s' for %s", verdict.action, signal.ticker)
        return False

    acct_after = broker.get_account()
    notifier.send_execution(result, acct_after["equity"])

    if result.success:
        guardrails.record_trade()

    trade_log.log_signal(
        ticker=signal.ticker, rating=signal.rating,
        summary=signal.executive_summary, risk_approved=True,
        risk_reason=verdict.reason, action=verdict.action,
        executed=result.success, order_id=result.order_id,
        order_amount=result.amount,
        error=None if result.success else result.message,
    )
    return result.success


# ════════════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    today = datetime.now().strftime("%Y-%m-%d")
    logger.info("═" * 60)
    logger.info("AUTONOMOUS TRADING RUNNER — %s", today)
    logger.info("═" * 60)

    # ── Initialise components ────────────────────────────────────────────────
    try:
        broker = AlpacaBroker()
    except EnvironmentError as exc:
        print(f"\n❌ {exc}\n")
        sys.exit(1)

    notifier    = TelegramNotifier()
    guardrails  = RiskGuardrails(RISK_CONFIG)
    trade_log   = TradeLogger()
    ta_config   = _build_ta_config()
    ta          = TradingAgentsGraph(debug=False, config=ta_config)

    acct_start  = broker.get_account()
    portfolio   = _build_portfolio(broker)

    logger.info("Account equity: $%.2f | Cash: $%.2f", acct_start["equity"], acct_start["cash"])
    notifier.send_startup(acct_start["equity"], WATCHLIST, paper=broker.paper)

    # ── Run analysis and execute ──────────────────────────────────────────────
    signals: list[dict] = []
    trades_executed = 0

    for ticker in WATCHLIST:
        signal = _run_analysis(ticker, ta, portfolio, today)

        if signal is None:
            notifier.send_analysis_error(ticker, "Analysis returned no result")
            signals.append({"ticker": ticker, "rating": "ERROR"})
            continue

        signals.append({"ticker": ticker, "rating": signal.rating})

        if is_review(signal.rating):
            logger.warning("REVIEW signal for %s — skipping execution", ticker)
            notifier.send_blocked(ticker, "REVIEW", "Agent could not form a clear decision.")
            continue

        executed = _execute_signal(signal, broker, guardrails, notifier, trade_log)
        if executed:
            trades_executed += 1

    # ── End-of-run summary ───────────────────────────────────────────────────
    acct_end = broker.get_account()
    trade_log.print_summary()
    notifier.send_daily_summary(signals, trades_executed, acct_start["equity"], acct_end["equity"])

    logger.info("Run complete | Trades executed: %d | Equity: $%.2f → $%.2f",
                trades_executed, acct_start["equity"], acct_end["equity"])


if __name__ == "__main__":
    main()

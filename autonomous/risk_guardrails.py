"""
Risk Guardrails — hard-coded safety rules that no LLM output can override.

Every trade signal from TradingAgents passes through here before any broker
order is placed. Rules are intentionally conservative: protect capital first,
seek returns second.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

logger = logging.getLogger(__name__)


@dataclass
class TradeSignal:
    """Structured output from a TradingAgents propagation run."""
    ticker: str
    rating: str                  # Buy / Overweight / Hold / Underweight / Sell / REVIEW
    executive_summary: str       # PM's concise action plan
    investment_thesis: str       # PM's full reasoning
    price_target: float | None
    time_horizon: str | None
    full_decision: str           # Raw decision text from PM
    analysis_date: str           # YYYY-MM-DD


@dataclass
class RiskVerdict:
    """Result of the guardrail check."""
    approved: bool               # Whether any action is allowed
    requires_human: bool         # Whether human approval is needed before executing
    action: str                  # "buy" / "sell" / "reduce" / "hold" / "block"
    position_pct: float          # Fraction of portfolio equity to allocate (0.0–1.0)
    reason: str                  # Human-readable explanation


# Ratings that map to buying / selling / neutral
_BUY_RATINGS  = {"Buy", "Overweight"}
_SELL_RATINGS = {"Sell", "Underweight"}
_HOLD_RATINGS = {"Hold"}


class RiskGuardrails:
    """
    Stateless set of hard rules applied before every order.

    Config keys (all optional, sensible defaults applied):
        max_single_position_pct   float  Max fraction of equity in one ticker  (0.20)
        max_invested_pct          float  Max fraction of equity invested total  (0.80)
        min_account_equity        float  Hard floor — never trade below this    (50.0)
        max_daily_trades          int    Max orders per calendar day            (5)
        auto_execute_ratings      set    Ratings auto-executed without approval ({"Hold"})
        human_approval_ratings    set    Ratings that require human OK          ({"Buy","Sell"})
        buy_fraction_overweight   float  Fraction of max position for Overweight(0.50)
        sell_fraction_underweight float  Fraction of holding to sell for Underweight(0.50)
    """

    def __init__(self, config: dict | None = None):
        cfg = config or {}
        self.max_single_position_pct   = cfg.get("max_single_position_pct",   0.20)
        self.max_invested_pct          = cfg.get("max_invested_pct",           0.80)
        self.min_account_equity        = cfg.get("min_account_equity",         50.0)
        self.max_daily_trades          = cfg.get("max_daily_trades",           5)
        self.auto_execute_ratings      = set(cfg.get("auto_execute_ratings",   ["Hold"]))
        self.human_approval_ratings    = set(cfg.get("human_approval_ratings", ["Buy", "Sell"]))
        self.buy_fraction_overweight   = cfg.get("buy_fraction_overweight",    0.50)
        self.sell_fraction_underweight = cfg.get("sell_fraction_underweight",  0.50)

        # Mutable state tracked across calls within a single run session
        self._daily_trade_count: dict[str, int] = {}  # date_str -> count

    # ── Public API ───────────────────────────────────────────────────────────

    def check(
        self,
        signal: TradeSignal,
        equity: float,
        cash: float,
        positions: dict,           # {ticker: {qty, market_value, avg_entry_price, ...}}
    ) -> RiskVerdict:
        """
        Evaluate a signal against all guardrails.

        Returns a RiskVerdict.  Callers must respect ``approved`` and
        ``requires_human`` before submitting any order.
        """
        today = date.today().isoformat()

        # ── Hard blocks ──────────────────────────────────────────────────────

        # 1. Unparseable / review signals
        if signal.rating == "REVIEW":
            return RiskVerdict(False, False, "block", 0.0,
                               "Rating is REVIEW — agent could not form a clear decision. Skip.")

        # 2. Account equity floor
        if equity < self.min_account_equity:
            return RiskVerdict(False, False, "block", 0.0,
                               f"Account equity ${equity:.2f} is below the minimum "
                               f"${self.min_account_equity:.2f}. No trading until funded.")

        # 3. Daily trade limit
        today_count = self._daily_trade_count.get(today, 0)
        if today_count >= self.max_daily_trades and signal.rating not in _HOLD_RATINGS:
            return RiskVerdict(False, False, "block", 0.0,
                               f"Daily trade limit ({self.max_daily_trades}) already reached.")

        # ── Hold — no action needed ──────────────────────────────────────────
        if signal.rating in _HOLD_RATINGS:
            return RiskVerdict(True, False, "hold", 0.0,
                               "Hold signal — maintain current position, no order needed.")

        # ── Buy-side rules ───────────────────────────────────────────────────
        if signal.rating in _BUY_RATINGS:
            total_invested = sum(p.get("market_value", 0) for p in positions.values())
            investable_cap = equity * self.max_invested_pct
            remaining_investable = max(0.0, investable_cap - total_invested)

            if remaining_investable < 1.0:
                return RiskVerdict(False, False, "block", 0.0,
                                   f"Portfolio at {self.max_invested_pct*100:.0f}% invested cap "
                                   f"(${total_invested:,.2f} / ${investable_cap:,.2f}). "
                                   "Cannot add more positions.")

            max_new_dollars = min(
                equity * self.max_single_position_pct,
                remaining_investable,
            )

            # Reduce for existing holding in this ticker
            existing_value = positions.get(signal.ticker, {}).get("market_value", 0.0)
            headroom = max(0.0, max_new_dollars - existing_value)

            if headroom < 1.0:
                return RiskVerdict(True, False, "hold", 0.0,
                                   f"Already fully positioned in {signal.ticker} "
                                   f"(${existing_value:,.2f}). No additional buy needed.")

            # Overweight = half-size; Buy = full-size
            fraction = 1.0 if signal.rating == "Buy" else self.buy_fraction_overweight
            alloc_dollars = headroom * fraction
            alloc_pct = alloc_dollars / equity

            requires_human = signal.rating in self.human_approval_ratings
            action = "buy"
            reason = (f"{signal.rating}: allocate ${alloc_dollars:,.2f} "
                      f"({alloc_pct*100:.1f}% of equity) to {signal.ticker}.")

            logger.info("RiskGuardrails BUY approved | %s | $%.2f | human=%s",
                        signal.ticker, alloc_dollars, requires_human)
            return RiskVerdict(True, requires_human, action, alloc_pct, reason)

        # ── Sell-side rules ──────────────────────────────────────────────────
        if signal.rating in _SELL_RATINGS:
            current_pos = positions.get(signal.ticker)
            if not current_pos or current_pos.get("qty", 0) <= 0:
                return RiskVerdict(True, False, "hold", 0.0,
                                   f"No position in {signal.ticker} to sell — nothing to do.")

            # Underweight = sell half; Sell = close entirely
            if signal.rating == "Sell":
                action, reason_verb = "sell", "Close entire position in"
                fraction = 1.0
            else:
                action, reason_verb = "reduce", "Reduce position by 50% in"
                fraction = self.sell_fraction_underweight

            qty_to_sell = current_pos["qty"] * fraction
            requires_human = signal.rating in self.human_approval_ratings
            reason = f"{signal.rating}: {reason_verb} {signal.ticker} (sell {qty_to_sell:.4g} units)."

            logger.info("RiskGuardrails SELL approved | %s | qty=%.4g | human=%s",
                        signal.ticker, qty_to_sell, requires_human)
            return RiskVerdict(True, requires_human, action, fraction, reason)

        # Unknown rating — block
        return RiskVerdict(False, False, "block", 0.0,
                           f"Unknown rating '{signal.rating}' — blocked as safety measure.")

    def record_trade(self):
        """Call after every executed order to increment the daily counter."""
        today = date.today().isoformat()
        self._daily_trade_count[today] = self._daily_trade_count.get(today, 0) + 1

    def daily_trades_remaining(self) -> int:
        today = date.today().isoformat()
        return max(0, self.max_daily_trades - self._daily_trade_count.get(today, 0))


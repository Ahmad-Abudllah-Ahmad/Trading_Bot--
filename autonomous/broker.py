"""
Alpaca broker integration — paper and live trading.

Supports fractional (dollar-based) orders for stocks and crypto.
All methods degrade gracefully: they return an OrderResult with
success=False rather than raising, so the orchestrator can log and
alert without crashing the run.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


@dataclass
class OrderResult:
    success: bool
    order_id: str | None
    side: str            # "buy" / "sell" / "reduce" / "none"
    ticker: str
    amount: float        # dollars for buys; qty for sells
    message: str


class AlpacaBroker:
    """
    Thin, testable wrapper around Alpaca's SDK.

    Initialised from environment variables:
        ALPACA_API_KEY     — paper or live key
        ALPACA_SECRET_KEY  — paper or live secret
        ALPACA_PAPER       — "true" for paper trading (default), "false" for live
    """

    def __init__(self):
        from alpaca.trading.client import TradingClient

        api_key    = os.getenv("ALPACA_API_KEY", "")
        secret_key = os.getenv("ALPACA_SECRET_KEY", "")
        paper      = os.getenv("ALPACA_PAPER", "true").lower() in ("true", "1", "yes")

        if not api_key or not secret_key:
            raise EnvironmentError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY must be set in your .env file.\n"
                "Sign up free at https://app.alpaca.markets/signup"
            )

        self._client = TradingClient(api_key, secret_key, paper=paper)
        self.paper   = paper
        mode = "PAPER" if paper else "LIVE"
        logger.info("AlpacaBroker initialised (%s)", mode)
        print(f"  🔗 Alpaca connected [{mode}]")

    # ── Account ─────────────────────────────────────────────────────────────

    def get_account(self) -> dict:
        """Return a plain dict with the key account metrics."""
        acct = self._client.get_account()
        return {
            "equity":          float(acct.equity),
            "cash":            float(acct.cash),
            "buying_power":    float(acct.buying_power),
            "portfolio_value": float(acct.portfolio_value),
            "pattern_day_trader": acct.pattern_day_trader,
        }

    def get_positions(self) -> dict:
        """
        Return current positions as::

            {
              "AAPL": {
                "qty": 10.5,
                "market_value": 1750.25,
                "avg_entry_price": 165.00,
                "unrealized_pl": 12.50,
                "unrealized_plpc": 0.0072,
              },
              ...
            }
        """
        positions = self._client.get_all_positions()
        return {
            pos.symbol: {
                "qty":               float(pos.qty),
                "market_value":      float(pos.market_value),
                "avg_entry_price":   float(pos.avg_entry_price),
                "unrealized_pl":     float(pos.unrealized_pl),
                "unrealized_plpc":   float(pos.unrealized_plpc),
            }
            for pos in positions
        }

    # ── Orders ───────────────────────────────────────────────────────────────

    def buy(self, ticker: str, dollar_amount: float) -> OrderResult:
        """
        Place a fractional market buy order for ``dollar_amount`` dollars.

        Alpaca's notional orders support fractional shares, so this works
        even with small amounts (min $1).
        """
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        dollar_amount = round(max(dollar_amount, 1.0), 2)
        try:
            order = self._client.submit_order(
                MarketOrderRequest(
                    symbol=ticker,
                    notional=dollar_amount,
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY,
                )
            )
            msg = f"BUY ${dollar_amount:.2f} of {ticker} submitted (id={order.id})"
            logger.info(msg)
            return OrderResult(True, str(order.id), "buy", ticker, dollar_amount, msg)
        except Exception as exc:
            msg = f"BUY failed for {ticker}: {exc}"
            logger.error(msg)
            return OrderResult(False, None, "buy", ticker, dollar_amount, msg)

    def sell_all(self, ticker: str) -> OrderResult:
        """Close the entire position in ``ticker``."""
        try:
            self._client.close_position(ticker)
            msg = f"SELL ALL {ticker} submitted"
            logger.info(msg)
            return OrderResult(True, None, "sell", ticker, 0.0, msg)
        except Exception as exc:
            msg = f"SELL ALL failed for {ticker}: {exc}"
            logger.error(msg)
            return OrderResult(False, None, "sell", ticker, 0.0, msg)

    def sell_qty(self, ticker: str, qty: float) -> OrderResult:
        """Sell a specific quantity of ``ticker``."""
        from alpaca.trading.requests import MarketOrderRequest
        from alpaca.trading.enums import OrderSide, TimeInForce

        qty = round(qty, 6)
        try:
            order = self._client.submit_order(
                MarketOrderRequest(
                    symbol=ticker,
                    qty=qty,
                    side=OrderSide.SELL,
                    time_in_force=TimeInForce.DAY,
                )
            )
            msg = f"SELL {qty} {ticker} submitted (id={order.id})"
            logger.info(msg)
            return OrderResult(True, str(order.id), "sell", ticker, qty, msg)
        except Exception as exc:
            msg = f"SELL {qty} {ticker} failed: {exc}"
            logger.error(msg)
            return OrderResult(False, None, "sell", ticker, qty, msg)

    def is_market_open(self) -> bool:
        """Return True if the US market is currently open."""
        try:
            clock = self._client.get_clock()
            return clock.is_open
        except Exception:
            return False


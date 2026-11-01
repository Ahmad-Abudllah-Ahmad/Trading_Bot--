"""
Telegram notification system with graceful console fallback.

When TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set in .env, every alert
is sent to your phone. If those variables are missing it prints to stdout
instead — so you can develop and test without a bot configured.

Setting up Telegram (5 minutes):
    1. Message @BotFather on Telegram → /newbot → follow prompts → copy token
    2. Start a chat with your new bot, then visit:
       https://api.telegram.org/bot<TOKEN>/getUpdates
       to find your chat_id (the "id" field inside "chat").
    3. Add to .env:
           TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
           TELEGRAM_CHAT_ID=987654321
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Send trade alerts and summaries via Telegram (or console if not configured)."""

    # Rating → emoji
    _EMOJI = {
        "Buy":         "🟢",
        "Overweight":  "🟡",
        "Hold":        "⚪",
        "Underweight": "🟠",
        "Sell":        "🔴",
        "REVIEW":      "❓",
    }

    def __init__(self):
        self._token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self._chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        self.enabled  = bool(self._token and self._chat_id)
        if self.enabled:
            logger.info("Telegram notifications enabled (chat_id=%s)", self._chat_id)
        else:
            logger.warning(
                "Telegram not configured — alerts printed to console only.\n"
                "Add TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID to .env to enable."
            )

    # ── Low-level send ───────────────────────────────────────────────────────

    def send(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Send a message. Returns True on success."""
        # Always echo to console
        print(f"\n{'─'*60}")
        print(f"📱 ALERT [{datetime.now().strftime('%H:%M')}]")
        print(text)
        print('─'*60)

        if not self.enabled:
            return True  # console-only mode is "success"

        try:
            url = f"https://api.telegram.org/bot{self._token}/sendMessage"
            resp = requests.post(
                url,
                json={
                    "chat_id":    self._chat_id,
                    "text":       text,
                    "parse_mode": parse_mode,
                },
                timeout=15,
            )
            resp.raise_for_status()
            return True
        except Exception as exc:
            logger.warning("Telegram send failed: %s", exc)
            return False

    # ── Formatted alert helpers ──────────────────────────────────────────────

    def send_startup(self, equity: float, watchlist: list[str], paper: bool):
        """Daily startup notification."""
        mode = "📄 PAPER" if paper else "💰 LIVE"
        tickers = ", ".join(f"`{t}`" for t in watchlist)
        self.send(
            f"🤖 *Trading Bot Started* {mode}\n\n"
            f"*Account equity:* ${equity:,.2f}\n"
            f"*Analysing:* {tickers}\n"
            f"*Time:* {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )

    def send_signal(
        self,
        ticker: str,
        rating: str,
        summary: str,
        requires_human: bool,
        reason: str,
        equity: float,
    ):
        """Signal alert — tells user what the agent decided and why."""
        emoji = self._EMOJI.get(rating, "❓")
        approval = (
            "\n\n⚠️ *WAITING FOR YOUR APPROVAL*\n"
            "Reply to approve: `/approve " + ticker + "`\n"
            "Reply to skip: `/skip " + ticker + "`"
        ) if requires_human else "\n\n✅ *Auto-executing* (within safe limits)"

        # Truncate summary to keep message readable
        short_summary = summary[:400] + ("…" if len(summary) > 400 else "")

        self.send(
            f"{emoji} *Agent Signal — {ticker}*\n\n"
            f"*Rating:* {rating}\n"
            f"*Account:* ${equity:,.2f}\n\n"
            f"*Summary:*\n{short_summary}\n\n"
            f"*Risk check:* {reason}"
            f"{approval}"
        )

    def send_execution(self, result, equity_after: float):
        """Trade execution confirmation (or failure notice)."""
        icon = "✅" if result.success else "❌"
        side = result.side.upper()
        amt  = f"${result.amount:,.2f}" if result.side == "buy" else f"{result.amount:.4g} units"
        self.send(
            f"{icon} *Trade {'Executed' if result.success else 'FAILED'}*\n\n"
            f"`{result.ticker}` — {side} {amt}\n"
            f"{result.message}\n\n"
            f"*Equity now:* ${equity_after:,.2f}"
        )

    def send_blocked(self, ticker: str, rating: str, reason: str):
        """Trade blocked by guardrails."""
        self.send(
            f"🚫 *Trade Blocked — {ticker}*\n\n"
            f"*Rating:* {rating}\n"
            f"*Reason:* {reason}"
        )

    def send_analysis_error(self, ticker: str, error: str):
        """Analysis failed for a ticker."""
        self.send(
            f"⚠️ *Analysis Failed — {ticker}*\n\n"
            f"Error: `{str(error)[:300]}`\n\n"
            f"Skipping this ticker."
        )

    def send_daily_summary(
        self,
        signals: list[dict],
        trades_executed: int,
        equity_start: float,
        equity_end: float,
    ):
        """End-of-run summary."""
        delta  = equity_end - equity_start
        icon   = "📈" if delta >= 0 else "📉"
        rating_lines = "\n".join(
            f"  {self._EMOJI.get(s['rating'], '❓')} `{s['ticker']}` — {s['rating']}"
            for s in signals
        )
        self.send(
            f"📊 *Daily Run Complete*\n\n"
            f"*Signals:*\n{rating_lines}\n\n"
            f"*Trades executed:* {trades_executed}\n"
            f"*Start equity:* ${equity_start:,.2f}\n"
            f"*End equity:*   ${equity_end:,.2f}\n"
            f"{icon} *Session P/L:* ${delta:+,.2f}"
        )


"""
Trade logger — append-only JSONL audit trail of every decision and execution.

Every signal (approved, blocked, pending approval, executed) is written to
``autonomous/logs/trades.jsonl``.  The file is human-readable and trivially
importable into pandas, Excel, or a dashboard.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_LOG = Path(__file__).parent / "logs" / "trades.jsonl"


class TradeLogger:
    """Thread-safe append-only trade log."""

    def __init__(self, log_path: str | Path = _DEFAULT_LOG):
        self.path = Path(log_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("TradeLogger writing to %s", self.path)

    # ── Write ────────────────────────────────────────────────────────────────

    def log_signal(
        self,
        ticker: str,
        rating: str,
        summary: str,
        risk_approved: bool,
        risk_reason: str,
        action: str,
        executed: bool,
        order_id: str | None = None,
        order_amount: float = 0.0,
        awaiting_approval: bool = False,
        error: str | None = None,
    ) -> dict:
        """Write one entry to the JSONL log and return it."""
        entry = {
            "ts":                datetime.now().isoformat(),
            "date":              date.today().isoformat(),
            "ticker":            ticker,
            "rating":            rating,
            "summary":           summary[:300],
            "risk_approved":     risk_approved,
            "risk_reason":       risk_reason,
            "action":            action,
            "executed":          executed,
            "awaiting_approval": awaiting_approval,
            "order_id":          order_id,
            "order_amount":      order_amount,
            "error":             error,
        }
        try:
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry) + "\n")
        except OSError as exc:
            logger.error("TradeLogger write failed: %s", exc)
        return entry

    # ── Read ─────────────────────────────────────────────────────────────────

    def today_entries(self) -> list[dict]:
        """Return all log entries for today."""
        today = date.today().isoformat()
        return [e for e in self._all_entries() if e.get("date") == today]

    def today_executed(self) -> list[dict]:
        """Return only entries that resulted in an executed order today."""
        return [e for e in self.today_entries() if e.get("executed")]

    def all_entries(self) -> list[dict]:
        return self._all_entries()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _all_entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        entries = []
        with open(self.path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass
        return entries

    def print_summary(self):
        """Pretty-print today's activity to stdout."""
        entries = self.today_entries()
        executed = [e for e in entries if e.get("executed")]
        blocked  = [e for e in entries if not e.get("risk_approved")]
        pending  = [e for e in entries if e.get("awaiting_approval")]

        print(f"\n{'═'*55}")
        print(f"  TRADE LOG — {date.today().isoformat()}")
        print(f"{'═'*55}")
        print(f"  Signals analysed : {len(entries)}")
        print(f"  Executed         : {len(executed)}")
        print(f"  Awaiting approval: {len(pending)}")
        print(f"  Blocked          : {len(blocked)}")
        if executed:
            print(f"\n  Executed trades:")
            for e in executed:
                print(f"    • {e['ticker']:8s} {e['rating']:12s}  ${e['order_amount']:,.2f}  [{e['action']}]")
        print(f"{'═'*55}\n")


"""
Quick-start validation script.

Run this FIRST to verify your API keys and environment are working
before running the full backtest or live runner.

Usage (from D:\\Trading Bot):
    .venv\\Scripts\\python.exe autonomous\\validate_setup.py
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

# Force UTF-8 output on Windows so box-drawing characters print correctly
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env")


REQUIRED_KEYS = {
    "OPENAI_API_KEY":     "OpenAI (fast analysts)         → https://platform.openai.com/api-keys",
    "ANTHROPIC_API_KEY":  "Anthropic/Claude (deep reasoning) → https://console.anthropic.com",
    "FRED_API_KEY":       "FRED macro data (free)          → https://fred.stlouisfed.org/docs/api/api_key.html",
    "ALPACA_API_KEY":     "Alpaca paper/live trading       → https://app.alpaca.markets/signup",
    "ALPACA_SECRET_KEY":  "Alpaca secret key               → (same as above)",
}

OPTIONAL_KEYS = {
    "TELEGRAM_BOT_TOKEN": "Telegram notifications (optional) → message @BotFather on Telegram",
    "TELEGRAM_CHAT_ID":   "Telegram chat ID (optional)       → see setup guide",
}


def check_env_keys():
    print("\n── API Key Check ────────────────────────────────────────────────")
    all_ok = True
    for key, desc in REQUIRED_KEYS.items():
        val = os.getenv(key, "")
        status = "✅" if val else "❌ MISSING"
        if not val:
            all_ok = False
        masked = (val[:8] + "…" + val[-4:]) if len(val) > 12 else ("set" if val else "")
        print(f"  {status}  {key:<26} {masked}")
        if not val:
            print(f"         Get it at: {desc}")

    print("\n── Optional Keys ────────────────────────────────────────────────")
    for key, desc in OPTIONAL_KEYS.items():
        val = os.getenv(key, "")
        status = "✅" if val else "⚠️  not set"
        print(f"  {status}  {key:<26}")
        if not val:
            print(f"         {desc}")
    return all_ok


def check_tradingagents():
    print("\n── TradingAgents Package ────────────────────────────────────────")
    try:
        import tradingagents
        print(f"  ✅ tradingagents {tradingagents.__version__} imported successfully")
        return True
    except ImportError as exc:
        print(f"  ❌ Cannot import tradingagents: {exc}")
        print("     Run: pip install .")
        return False


def check_alpaca():
    print("\n── Alpaca Broker Connection ─────────────────────────────────────")
    try:
        from broker import AlpacaBroker
        broker = AlpacaBroker()
        acct   = broker.get_account()
        mode   = "PAPER" if broker.paper else "LIVE"
        print(f"  ✅ Connected [{mode}] | Equity: ${acct['equity']:,.2f} | Cash: ${acct['cash']:,.2f}")
        return True
    except EnvironmentError as exc:
        print(f"  ❌ {exc}")
        return False
    except Exception as exc:
        print(f"  ❌ Connection failed: {exc}")
        return False


def check_llm_openai():
    print("\n── OpenAI API ───────────────────────────────────────────────────")
    key = os.getenv("OPENAI_API_KEY", "")
    if not key:
        print("  ❌ OPENAI_API_KEY not set — skipping")
        return False
    try:
        from openai import OpenAI
        client = OpenAI(api_key=key)
        resp   = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Reply with just the word OK."}],
            max_tokens=5,
        )
        reply = resp.choices[0].message.content.strip()
        print(f"  ✅ gpt-4o-mini responded: '{reply}'")
        return True
    except Exception as exc:
        print(f"  ❌ OpenAI test failed: {exc}")
        return False


def check_llm_anthropic():
    print("\n── Anthropic/Claude API ─────────────────────────────────────────")
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        print("  ❌ ANTHROPIC_API_KEY not set — skipping")
        return False
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)
        msg    = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=10,
            messages=[{"role": "user", "content": "Reply with just the word OK."}],
        )
        reply = msg.content[0].text.strip()
        print(f"  ✅ claude-haiku-4-5 responded: '{reply}'")
        return True
    except Exception as exc:
        print(f"  ❌ Anthropic test failed: {exc}")
        return False


def check_yfinance():
    print("\n── Market Data (Yahoo Finance) ──────────────────────────────────")
    try:
        import yfinance as yf
        ticker = yf.Ticker("AAPL")
        hist   = ticker.history(period="5d")
        if hist.empty:
            print("  ⚠️  yfinance returned empty data — may be a temporary issue")
            return False
        latest = hist["Close"].iloc[-1]
        print(f"  ✅ AAPL latest close: ${latest:.2f}")
        return True
    except Exception as exc:
        print(f"  ❌ yfinance failed: {exc}")
        return False


def main():
    print("═" * 65)
    print("  SETUP VALIDATION — Autonomous Trading System")
    print("═" * 65)

    results = {
        "env_keys":      check_env_keys(),
        "tradingagents": check_tradingagents(),
        "alpaca":        check_alpaca(),
        "openai":        check_llm_openai(),
        "anthropic":     check_llm_anthropic(),
        "yfinance":      check_yfinance(),
    }

    print("\n── Summary ──────────────────────────────────────────────────────")
    all_pass = all(results.values())
    for name, ok in results.items():
        icon = "✅" if ok else "❌"
        print(f"  {icon}  {name}")

    print()
    if all_pass:
        print("  🎉 All checks passed! You're ready to run the backtest.")
        print("     Next step:  .venv\\Scripts\\python.exe autonomous\\backtest_runner.py")
    else:
        failed = [k for k, v in results.items() if not v]
        print(f"  ⚠️  Fix the failed checks above before proceeding.")
        print(f"     Failed: {', '.join(failed)}")
    print()


if __name__ == "__main__":
    main()

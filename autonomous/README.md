# Autonomous Trading System

Built on top of [TradingAgents](https://github.com/TauricResearch/TradingAgents) — a multi-agent LLM framework that mirrors a real trading firm's decision pipeline.

---

## Folder Structure

```
D:\Trading Bot\
├── tradingagents\          ← core TradingAgents package (don't modify)
├── autonomous\             ← our autonomous layer (all new code lives here)
│   ├── runner.py           ← MAIN ENTRY POINT — runs daily analysis + execution
│   ├── backtest_runner.py  ← run BEFORE going live to validate the system
│   ├── validate_setup.py   ← run FIRST to check all API keys and connections
│   ├── setup_scheduler.py  ← registers Windows Task Scheduler task
│   ├── risk_guardrails.py  ← hard safety rules — no LLM output can override these
│   ├── broker.py           ← Alpaca broker wrapper (paper + live)
│   ├── notifier.py         ← Telegram alerts with console fallback
│   ├── trade_logger.py     ← append-only JSONL audit log
│   ├── logs\               ← runner.log, backtest.log, trades.jsonl
│   └── reports\            ← saved TradingAgents analysis reports (HTML + markdown)
├── .env                    ← YOUR API KEYS (never commit this)
└── .env.autonomous.example ← template for .env
```

---

## Quick Start (follow in order)

### Step 1 — Fill in API Keys

```powershell
copy .env.autonomous.example .env
# Open .env and fill in your keys
notepad .env
```

Keys you need:
| Key | Where to get it | Cost |
|:----|:----------------|:-----|
| `OPENAI_API_KEY` | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) | Pay-per-use (~$10-30/month) |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | Pay-per-use (~$20-50/month) |
| `FRED_API_KEY` | [fred.stlouisfed.org/docs/api/api_key.html](https://fred.stlouisfed.org/docs/api/api_key.html) | **Free** |
| `ALPACA_API_KEY` + `ALPACA_SECRET_KEY` | [app.alpaca.markets/signup](https://app.alpaca.markets/signup) | **Free** |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Message @BotFather on Telegram | **Free** (optional) |

### Step 2 — Install Dependencies

```powershell
cd "D:\Trading Bot"
.venv\Scripts\pip.exe install .
.venv\Scripts\pip.exe install alpaca-py requests
```

### Step 3 — Validate Setup

```powershell
.venv\Scripts\python.exe autonomous\validate_setup.py
```

All checks must pass before proceeding.

### Step 4 — Run a Backtest (takes 1-4 hours)

```powershell
.venv\Scripts\python.exe autonomous\backtest_runner.py
```

**Interpret the results:**
- Hit Rate > 55% AND Mean Alpha > 0% → system has an edge, continue
- Hit Rate < 50% OR Mean Alpha < 0% → tune config or change ticker universe before going live

### Step 5 — Paper Trade (run daily for 4+ weeks)

```powershell
# Make sure ALPACA_PAPER=true in .env
.venv\Scripts\python.exe autonomous\runner.py
```

### Step 6 — Register as a Daily Scheduled Task

```powershell
# Run PowerShell as Administrator
.venv\Scripts\python.exe autonomous\setup_scheduler.py
```

This schedules the bot to run at 7:00 PM PKT (30 min before US market open) every day.

### Step 7 — Go Live (only after 4+ weeks of profitable paper trading)

```powershell
# Change in .env:
# ALPACA_PAPER=false
```

---

## Customising the Bot

Edit `autonomous/runner.py`:

```python
# Change what tickers to analyse
WATCHLIST = ["AAPL", "NVDA", "MSFT", "GOOGL", "BTC-USD"]

# Change risk limits
RISK_CONFIG = {
    "max_single_position_pct": 0.20,   # 20% max per ticker
    "max_invested_pct":        0.80,   # always keep 20% cash
    "min_account_equity":      50.0,   # stop trading below $50
    "max_daily_trades":        4,
    "human_approval_ratings":  ["Buy", "Sell"],   # these need Telegram approval
}
```

Edit `autonomous/runner.py` → `_build_ta_config()` to change LLM models.

---

## Trade Log

Every decision (executed, blocked, pending approval) is logged to:
```
autonomous\logs\trades.jsonl
```

Each line is a JSON object with: date, ticker, rating, action, risk_reason, executed, order_id, amount.

---

## Safety Rules (cannot be overridden by LLM output)

1. Never trade if account equity < $50
2. No single position > 20% of portfolio
3. Always keep ≥ 20% cash reserve
4. Max 4 trades per day
5. Buy/Sell signals require Telegram approval (auto-blocks if Telegram not configured)
6. REVIEW signals are always skipped

---

## Troubleshooting

| Problem | Fix |
|:--------|:----|
| `ALPACA_API_KEY not set` | Fill in your Alpaca keys in `.env` |
| `Cannot import tradingagents` | Run `.venv\Scripts\pip.exe install .` from `D:\Trading Bot` |
| `OpenAI test failed` | Check your API key and account balance at platform.openai.com |
| Analysis takes too long | Reduce `WATCHLIST` to 2-3 tickers, set `max_debate_rounds=1` |
| Telegram not sending | Verify BOT_TOKEN and CHAT_ID; start a chat with your bot first |


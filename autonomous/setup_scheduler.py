"""
Windows Task Scheduler setup script.

Creates a daily scheduled task that runs the autonomous trading bot.
Run this once as Administrator to register the task.

Usage (PowerShell as Administrator):
    cd "D:\\Trading Bot"
    .venv\\Scripts\\python.exe autonomous\\setup_scheduler.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT    = Path(__file__).parent.parent
_PYTHON  = _ROOT / ".venv" / "Scripts" / "python.exe"
_RUNNER  = Path(__file__).parent / "runner.py"
_TASK    = "TradingBot-DailyRun"

# ── Schedule configuration ────────────────────────────────────────────────────
# US market opens 9:30 AM ET.  PKT is UTC+5, so 9:30 AM ET = 19:30 PKT (7:30 PM).
# We run at 7:00 PM PKT (30 min before market open) to have the analysis ready.
# Adjust HOUR and MINUTE to your local timezone and preferred run time.
HOUR   = 19   # 7 PM local time (PKT)
MINUTE = 0


_PS_SCRIPT = f"""
$action   = New-ScheduledTaskAction `
    -Execute  '{_PYTHON}' `
    -Argument '{_RUNNER}' `
    -WorkingDirectory '{_ROOT}'

$trigger  = New-ScheduledTaskTrigger -Daily -At '{HOUR:02d}:{MINUTE:02d}'

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 4)

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

# Remove existing task with same name if present
Unregister-ScheduledTask -TaskName '{_TASK}' -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask `
    -TaskName    '{_TASK}' `
    -Action      $action `
    -Trigger     $trigger `
    -Settings    $settings `
    -Principal   $principal `
    -Description 'Autonomous trading bot — daily analysis and order execution'

Write-Output "Task registered: {_TASK}"
Write-Output "Scheduled at: {HOUR:02d}:{MINUTE:02d} local time (every day)"
"""


def main():
    print(f"\n  Registering Windows Task Scheduler task: '{_TASK}'")
    print(f"  Python : {_PYTHON}")
    print(f"  Script : {_RUNNER}")
    print(f"  Time   : {HOUR:02d}:{MINUTE:02d} local time (daily)\n")

    if not _PYTHON.exists():
        print(f"  ❌ Virtual environment not found at {_PYTHON}")
        print("     Run: python -m venv .venv && .venv\\Scripts\\pip install .")
        sys.exit(1)

    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", _PS_SCRIPT],
        capture_output=True, text=True,
    )

    if result.returncode == 0:
        print(f"  ✅ {result.stdout.strip()}")
        print("\n  To verify: open Task Scheduler and look for 'TradingBot-DailyRun'")
        print("  To run now: schtasks /Run /TN TradingBot-DailyRun")
    else:
        print(f"  ❌ Failed to register task:")
        print(f"     {result.stderr.strip()}")
        print("\n  Tip: Run PowerShell as Administrator and try again.")
        sys.exit(1)


if __name__ == "__main__":
    main()


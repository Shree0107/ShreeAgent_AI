"""Daily scheduled watchlist scan -> WhatsApp.

Run:  python -m alerts.scheduler          (blocks; runs every day at SCAN_TIME in SCAN_TIMEZONE)
      python -m alerts.scheduler --now    (one scan immediately, then exit)
"""
from __future__ import annotations

import argparse
import logging
import sys

from config.logging_setup import setup_logging
from config.settings import get_settings

log = logging.getLogger("scheduler")


def main() -> None:
    setup_logging()
    try:  # Windows consoles default to cp1252, which can't print the digest's emoji
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    p = argparse.ArgumentParser()
    p.add_argument("--now", action="store_true", help="run one scan immediately and exit")
    p.add_argument("--only-flagged", action="store_true", help="only include symbols with alerts")
    args = p.parse_args()

    from alerts.scanner import run_and_notify

    if args.now:
        print(run_and_notify(only_flagged=args.only_flagged))
        return

    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    s = get_settings()
    hh, mm = (int(x) for x in s.scan_time.split(":"))
    sched = BlockingScheduler(timezone=s.scan_timezone)
    sched.add_job(lambda: run_and_notify(args.only_flagged), CronTrigger(hour=hh, minute=mm, day_of_week="mon-fri"),
                  id="daily_scan", misfire_grace_time=3600, coalesce=True)
    log.info("Scheduler started: watchlist scan Mon-Fri at %s %s (backend: %s)", s.scan_time, s.scan_timezone,
             s.whatsapp_backend)
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("Scheduler stopped")


if __name__ == "__main__":
    main()

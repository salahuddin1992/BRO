# PyInstaller hook for APScheduler
# Ensures triggers, job stores, and executors are collected.
# Without this, BackgroundScheduler fails to find interval/cron triggers.
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules('apscheduler')

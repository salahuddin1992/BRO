# PyInstaller hook for limits (Flask-Limiter storage backend)
# Ensures in-memory and other storage backends are collected.
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules('limits')

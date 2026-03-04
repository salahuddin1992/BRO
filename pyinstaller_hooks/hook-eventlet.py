# PyInstaller hook for eventlet
# Ensures all eventlet submodules needed at runtime are collected
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules('eventlet')

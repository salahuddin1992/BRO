# PyInstaller hook for gevent
# Ensures all gevent submodules (including C extensions) are collected
from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs

hiddenimports = collect_submodules('gevent')
binaries = collect_dynamic_libs('gevent')

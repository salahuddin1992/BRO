# PyInstaller hook for Pillow (PIL)
# Ensures all image format plugins are collected so that
# JPEG, PNG, WebP, GIF, BMP etc. open/save correctly at runtime.
from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs

hiddenimports = collect_submodules('PIL')

binaries = collect_dynamic_libs('PIL')

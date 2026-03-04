# PyInstaller hook for greenlet
# The greenlet C extension (_greenlet) is frequently missed by PyInstaller
from PyInstaller.utils.hooks import collect_dynamic_libs

hiddenimports = ['greenlet', 'greenlet._greenlet']
binaries = collect_dynamic_libs('greenlet')

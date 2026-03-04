# PyInstaller hook for zeroconf
# zeroconf has many asyncio-based submodules that PyInstaller cannot
# discover automatically. collect_submodules ensures they are all bundled.
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

hiddenimports = collect_submodules('zeroconf')
datas = collect_data_files('zeroconf')

# PyInstaller hook for aiortc
# aiortc depends on cffi, OpenSSL, and av (FFmpeg Python bindings)
from PyInstaller.utils.hooks import (
    collect_submodules, collect_dynamic_libs, collect_data_files,
)

hiddenimports = (
    collect_submodules('aiortc')
    + collect_submodules('aioice')
    + collect_submodules('av')
    + collect_submodules('cffi')
    + collect_submodules('OpenSSL')
    + [
        '_cffi_backend',
        'pyOpenSSL',
        'cryptography.hazmat.bindings._rust',
    ]
)

# Collect FFmpeg shared libraries bundled with the 'av' package
binaries = (
    collect_dynamic_libs('av')
    + collect_dynamic_libs('cffi')
    + collect_dynamic_libs('OpenSSL')
)

datas = collect_data_files('aiortc')

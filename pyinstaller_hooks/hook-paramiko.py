# PyInstaller hook for paramiko
# Ensures bcrypt and nacl (PyNaCl) are bundled — required for
# Ed25519 keys, encrypted private keys, and modern SSH key exchange.
from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs

hiddenimports = (
    collect_submodules('paramiko')
    + collect_submodules('bcrypt')
    + collect_submodules('nacl')
)

binaries = (
    collect_dynamic_libs('bcrypt')
    + collect_dynamic_libs('nacl')
)

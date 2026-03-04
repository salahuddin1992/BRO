# PyInstaller hook for urllib3
# mesh_node.py uses urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
# and requests relies on urllib3 internally — ensure all submodules are bundled.
from PyInstaller.utils.hooks import collect_submodules

hiddenimports = collect_submodules('urllib3')

#!/usr/bin/env python3
"""Use build.py instead - this file is kept for compatibility."""
import subprocess, sys, os
subprocess.run([sys.executable, os.path.join(os.path.dirname(__file__), "build.py")])

#!/usr/bin/env python3
"""
BRO Communication Server - Main Entry Point

Usage:
    python run.py              # Start server (silent mode)
    python run.py --verbose    # Start with console output
    python run.py --port 9000  # Custom port
    python run.py --host 0.0.0.0 --port 8400
"""
import sys
import os
import argparse

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server.bro_server import create_app


def main():
    parser = argparse.ArgumentParser(description="BRO Communication Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8400, help="Port (default: 8400)")
    parser.add_argument("--verbose", action="store_true", help="Show console output")
    args = parser.parse_args()

    server = create_app()
    server.run(host=args.host, port=args.port, silent=not args.verbose)


if __name__ == "__main__":
    main()

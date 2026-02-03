#!/usr/bin/env python
"""
CLI-only entry point for Generator Booking Ledger.
For quick CLI access without going through main.py.
"""

import sys
import logging

from config import setup_logging
setup_logging()

from cli import CLI


def main():
    """Run CLI only."""
    cli = CLI()
    try:
        cli.run()
    except KeyboardInterrupt:
        print("\n\nGoodbye!")


if __name__ == "__main__":
    main()

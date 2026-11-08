#!/usr/bin/env python3
"""Backward-compatible entry point. Prefer `aws-fortiweb` (pip install aws-fortiweb) or `python3 aws_fortiweb.py`."""

import sys

from aws_fortiweb import main

if __name__ == '__main__':
    sys.exit(main())

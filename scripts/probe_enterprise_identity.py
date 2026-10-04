#!/usr/bin/env python3
"""Verify externally issued pilot API roles without business mutations."""

from regulated_ai.entrypoints.identity_pilot import main

if __name__ == "__main__":
    raise SystemExit(main())

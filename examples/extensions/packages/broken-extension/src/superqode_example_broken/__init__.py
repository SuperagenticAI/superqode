"""Deliberately fail at import time to probe extension isolation."""

raise RuntimeError("intentional broken extension import probe")

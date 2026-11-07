"""Tests run on synthetic data only.

The earlier release registers' store is about 90 MB, and every site build
reads it, so builds under test are pointed at a store that doesn't exist.
`test_earlier` writes its own and passes it explicitly.
"""

from pathlib import Path

from pipeline import earlier

earlier.STORE = Path(__file__).resolve().parent / "no-earlier-registers-store"

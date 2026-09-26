"""Agreements the site leaves out, though the register published them.

`data/excluded-agreements.json` lists them by base reference, each with the
reason. The facts store keeps them, because it records what each workbook said,
so this is a build-time decision like the aliases: an entry removes an agreement
from every page, count, download and "what changed" comparison at the next
build, and taking it out brings it back, with nothing to re-parse.

Only records that are not data sharing at all belong here: a test record
published in error, or a spreadsheet note the parser took for a row. An
agreement that is real but odd stays in.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDED_PATH = ROOT / "data" / "excluded-agreements.json"


def load(path: Path | None = None) -> list[dict]:
    path = path or EXCLUDED_PATH
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["agreements"]


def bases(path: Path | None = None) -> frozenset[str]:
    """The excluded base references, upper-cased for comparison."""
    return frozenset(entry["reference"].upper() for entry in load(path))

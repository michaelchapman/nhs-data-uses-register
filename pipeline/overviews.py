"""AI-written overviews shown at the top of agreement pages.

An overview is two or three sentences an AI model wrote from an agreement's
purpose text. It is not part of the register. It is written by
`pipeline.summarise` on a maintainer's machine, with an API key that never goes
into CI, and committed to `data/summaries.json`:

    {"DARS-NIC-00574-V2H1F": {"hash": "...", "summary": "...",
                              "model": "claude-haiku-5-5", "written": "2026-10-31"}}

`hash` is of the text the overview was written from. The build shows an
overview only while that hash matches the agreement's current text, so when
NHS England edits the text the overview disappears until the next run, rather
than describing wording that has gone.

This module is the part the build needs, and imports nothing outside the
standard library.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "data" / "summaries.json"

# The register's purpose fields, in the order an agreement page shows them.
FIELDS = [
    ("Objective for processing", "objective"),
    ("Processing activities", "activities"),
    ("Expected output", "expected_output"),
    ("Expected measurable benefits", "expected_benefits"),
    ("Benefits reported so far", "yielded_benefits"),
]

# How each model is named on the page.
MODEL_NAMES = {
    "claude-haiku-5-5": "Claude Haiku 5.5",
    "claude-sonnet-5-5": "Claude Sonnet 5.5",
}


def text_hash(version: dict) -> str:
    """A hash of the purpose text of `version`, as the page shows it."""
    text = json.dumps([version.get(field) or "" for _, field in FIELDS], ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load(path: Path | None = None) -> dict[str, dict]:
    path = path or PATH
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write(entries: dict[str, dict], path: Path | None = None) -> None:
    path = path or PATH
    text = json.dumps(dict(sorted(entries.items())), indent=1, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def current(agreement: dict, entries: dict[str, dict]) -> dict | None:
    """The overview for `agreement`, if one was written from its current text.

    An overview `pipeline.summarise` flagged is held back until a person has
    read it and deleted its `flags`.
    """
    entry = entries.get(agreement["base_reference"].upper())
    if not entry or entry.get("flags") or entry.get("hash") != text_hash(agreement["latest"]):
        return None
    return {**entry, "model_name": MODEL_NAMES.get(entry.get("model", ""), entry.get("model", "an AI model"))}

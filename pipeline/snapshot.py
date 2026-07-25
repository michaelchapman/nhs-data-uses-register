"""Per-edition fingerprints, so the site can show what changed each month.

The published workbooks are far too large to keep in git. Instead each run
writes a small fingerprint file per edition (`data/snapshots/<register>/<edition>.json`)
holding a hash of every agreement version. Comparing the current edition with
the previous one gives the "new and changed this month" view, and keeping the
files in git gives a durable history of editions the site has seen.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

SNAPSHOT_ROOT = Path(__file__).resolve().parent.parent / "data" / "snapshots"

# Fields whose change we consider a substantive amendment to an agreement.
FINGERPRINTED = (
    "title",
    "organisation",
    "organisation_type",
    "controller_basis",
    "start_date",
    "end_date",
    "sublicensing",
    "commercial",
    "objective",
    "activities",
    "expected_output",
    "expected_benefits",
    "yielded_benefits",
)


def _fingerprint(version: dict) -> str:
    fields = {key: version.get(key, "") for key in FINGERPRINTED}
    fields["datasets"] = sorted(d["name"] for d in version["datasets"])
    payload = json.dumps(fields, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def build_snapshot(data: dict, register_slug: str, edition: str, source_url: str, retrieved: str) -> dict:
    versions = {}
    for agreement in data["agreements"]:
        for version in agreement["versions"]:
            versions[version["reference"]] = {
                "base": agreement["base_reference"],
                "org": agreement["organisation"],
                "title": version["title"],
                "hash": _fingerprint(version),
            }
    return {
        "register": register_slug,
        "edition": edition,
        "source_url": source_url,
        "retrieved": retrieved,
        "counts": {
            "agreements": len(data["agreements"]),
            "agreement_versions": len(versions),
            "organisations": len(data["organisations"]),
            "datasets": len(data["datasets"]),
        },
        "versions": versions,
    }


def snapshot_dir(register_slug: str) -> Path:
    path = SNAPSHOT_ROOT / register_slug
    path.mkdir(parents=True, exist_ok=True)
    return path


def existing_editions(register_slug: str) -> list[Path]:
    """Snapshot files, oldest first, ordered by the edition date inside them."""
    files = list(snapshot_dir(register_slug).glob("*.json"))
    return sorted(files, key=lambda p: json.loads(p.read_text()).get("retrieved", ""))


def write_snapshot(snapshot: dict) -> Path:
    path = snapshot_dir(snapshot["register"]) / f"{snapshot['edition']}.json"
    # Compact: one of these lands in git every month, forever.
    path.write_text(json.dumps(snapshot, sort_keys=True, separators=(",", ":")) + "\n")
    return path


def previous_snapshot(register_slug: str, edition: str) -> dict | None:
    candidates = [p for p in existing_editions(register_slug) if p.stem != edition]
    if not candidates:
        return None
    return json.loads(candidates[-1].read_text())


def diff(current: dict, previous: dict | None) -> dict:
    """Agreement-version level changes between two editions."""
    if not previous:
        return {"comparable": False, "previous_edition": None, "added": [], "amended": [], "removed": []}

    old, new = previous["versions"], current["versions"]
    old_bases = {v["base"] for v in old.values()}

    added, amended = [], []
    for reference, version in new.items():
        if reference in old:
            if old[reference]["hash"] != version["hash"]:
                amended.append({"reference": reference, **version})
            continue
        added.append(
            {
                "reference": reference,
                **version,
                # A new version of an agreement we already knew about is a renewal,
                # not a brand new data release.
                "kind": "renewal" if version["base"] in old_bases else "new",
            }
        )
    removed = [{"reference": r, **v} for r, v in old.items() if r not in new]

    key = lambda item: (item["org"].lower(), item["reference"])
    return {
        "comparable": True,
        "previous_edition": previous["edition"],
        "added": sorted(added, key=key),
        "amended": sorted(amended, key=key),
        "removed": sorted(removed, key=key),
    }

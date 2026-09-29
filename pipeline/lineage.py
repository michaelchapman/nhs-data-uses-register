"""Which NHS organisation a register name belongs to, and what it became.

The register names organisations as they were called when an edition was
published, so an NHS reorganisation rewrites hundreds of agreements at once.
This module answers two questions for the rest of the pipeline, from two
committed files and without touching the network:

- `data/organisation-codes.json`: the ODS code for each register name that has
  one, and the evidence for it (written by `pipeline.odscheck`);
- `data/ods/organisations.json`: those organisations' ODS records (written by
  `pipeline.ods`).

`relation(old, new)` says whether a name that replaced another on an agreement
is the same organisation ("same") or its successor ("succeeded"). `page(name)`
says which organisation page a name belongs on: one page per ICB, with its
sub-ICB locations listed on it, and one per CCG, linked to the ICB that took
over from it.

A CCG and the sub-ICB location that continued it share an ODS code, because
ODS renamed the record on 1 July 2022 rather than closing it. A register name
recorded `"as": "CCG"` is the code as it was before then. That is how the two
are told apart. See docs/organisation-names.md, "NHS reorganisations (ODS)".
"""

from __future__ import annotations

import json
from pathlib import Path

from . import aliases, ods
from .names import strip_code

ROOT = Path(__file__).resolve().parent.parent
CODES_PATH = ROOT / "data" / "organisation-codes.json"
SUCCESSIONS_PATH = ROOT / "data" / "organisation-successions.json"

SAME = "same"
SUCCEEDED = "succeeded"


def load_codes(path: Path | None = None) -> list[dict]:
    path = path or CODES_PATH
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["names"]


def write_codes(entries: list[dict], path: Path | None = None) -> None:
    path = path or CODES_PATH
    data = {
        "_comment": (
            "The ODS code for each organisation name in the register that has one, "
            "and the evidence for it. Written by `python -m pipeline.odscheck`; an "
            "entry whose evidence starts \"reviewed:\" was decided by a person and "
            "is kept on every run. \"as\": \"CCG\" marks a name that belongs to the "
            "code as it was while a clinical commissioning group, before ODS renamed "
            "the record as a sub-ICB location. See docs/organisation-names.md."
        ),
        "names": sorted(entries, key=lambda e: (e["name"].casefold(), e["name"])),
    }
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def load_successions(path: Path | None = None) -> list[dict]:
    """Successions a person recorded where ODS has none, or dates one wrongly.

    Each is `{from, to, date, evidence}`, by register name. ODS stays the
    source wherever it is right; this file is for the exceptions, each with
    its reason.
    """
    path = path or SUCCESSIONS_PATH
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["successions"]


def _roles(record: dict) -> dict[str, dict]:
    return {role["id"]: role for role in record.get("roles", [])}


class Lineage:
    def __init__(
        self,
        codes: list[dict],
        organisations: dict[str, dict],
        alias_map: dict[str, str],
        successions: list[dict] = (),
    ):
        self.organisations = organisations
        self.alias_map = alias_map
        self.entries = {aliases.name_key(e["name"]): e for e in codes}
        # A reviewed alias makes its names one organisation, so they share
        # whichever code one of them has, and the page keeps the name the
        # reviewer chose: "Milton Keynes City Council", where ODS still says
        # "Milton Keynes Council".
        self.chosen: dict[str, str] = {}
        for variant, canonical in alias_map.items():
            if aliases.name_key(canonical) not in self.entries and variant in self.entries:
                self.entries[aliases.name_key(canonical)] = self.entries[variant]
        for canonical in set(alias_map.values()):
            entry = self.entries.get(aliases.name_key(canonical))
            if entry and not entry.get("as"):
                self.chosen.setdefault(entry["code"], canonical)
        self.successions = {
            aliases.name_key(aliases.resolve(s["from"], alias_map)): s for s in successions
        }
        # `relation` is asked the same pairs of names thousands of times a build.
        self._relations: dict[tuple[str, str], tuple[str, str] | None] = {}
        # ODS sometimes records a succession on one side only.
        self.later: dict[str, list[dict]] = {}
        for code, record in organisations.items():
            for link in record.get("successors", []):
                self.later.setdefault(code, []).append(link)
            for link in record.get("predecessors", []):
                self.later.setdefault(link["code"], []).append({"code": code, "date": link["date"]})

    # Names to nodes. A node is "org:<code>", or "ccg:<code>" for a code while
    # it was a CCG.

    def entry(self, name: str) -> dict | None:
        """The code entry for `name`, through its reviewed alias first.

        A reviewed alias says two names are one organisation, so they take the
        code of the name the reviewer chose, even where ODS holds them under
        two codes.
        """
        if not name:
            return None
        return self.entries.get(aliases.name_key(aliases.resolve(name, self.alias_map))) or self.entries.get(
            aliases.name_key(name)
        )

    def node(self, name: str) -> str | None:
        # A reviewed succession is a person's decision about this name, so it
        # comes before any code a search matched it to: the register's "HEALTH
        # & SOCIAL CARE INFORMATION CENTRE" also names an unrelated ODS record.
        key = aliases.name_key(aliases.resolve(name, self.alias_map)) if name else ""
        if key in self.successions:
            return f"name:{key}"
        entry = self.entry(name)
        if not entry:
            return None
        return f"{'ccg' if entry.get('as') == 'CCG' else 'org'}:{entry['code']}"

    def source(self, name: str) -> str:
        """Where what the site says about `name`'s succession comes from: ODS, or a person."""
        node = self.node(name)
        return "reviewed" if node and node.startswith("name:") else "ODS"

    def identity(self, node: str) -> str:
        """The organisation a node belongs to: a sub-ICB location belongs to its ICB."""
        kind, code = node.split(":", 1)
        if kind == "name":
            return node
        record = self.organisations.get(code, {})
        if kind == "org" and record.get("icb") and ods.SUB_ICB_LOCATION in _roles(record):
            return f"org:{record['icb']}"
        return node

    def _node_for(self, code: str, date: str) -> str:
        """The node a succession on `date` lands on: a CCG, if the code was one then."""
        roles = _roles(self.organisations.get(code, {}))
        sub_icb = roles.get(ods.SUB_ICB_LOCATION)
        if ods.CCG in roles and (not sub_icb or (date and date < sub_icb["start"])):
            return f"ccg:{code}"
        return f"org:{code}"

    def successors(self, node: str) -> list[tuple[str, str]]:
        """`[(node, date)]` that `node` passed to, per ODS or a reviewed succession."""
        kind, code = node.split(":", 1)
        if kind == "name":
            succession = self.successions[code]
            later = self.node(succession["to"])
            return [(self.identity(later), succession["date"])] if later else []
        record = self.organisations.get(code, {})
        found = []
        if kind == "ccg":
            sub_icb = _roles(record).get(ods.SUB_ICB_LOCATION)
            if sub_icb:
                # ICBs took over from CCGs on the day the record became a
                # sub-ICB location.
                found.append((self.identity(f"org:{code}"), sub_icb["start"]))
        for link in self.later.get(code, []):
            found.append((self._node_for(link["code"], link["date"]), link["date"]))
        return found

    def relation(self, old: str, new: str) -> tuple[str, str] | None:
        """`(SAME | SUCCEEDED, date)` if `new` is `old` or took over from it, else None."""
        # Remembered on the instance: a cache on the method would hold on to
        # every `Lineage` ever built, as each build and test builds its own.
        if (old, new) not in self._relations:
            self._relations[(old, new)] = self._relation(old, new)
        return self._relations[(old, new)]

    def _relation(self, old: str, new: str) -> tuple[str, str] | None:
        a, b = self.node(old), self.node(new)
        if not a or not b:
            return None
        target = self.identity(b)
        if self.identity(a) == target:
            return (SAME, "")
        seen, frontier = {a}, [(a, "")]
        for _ in range(ods.MAX_DEPTH + 2):
            following = []
            for node, _date in frontier:
                for later, date in self.successors(node):
                    if later in seen:
                        continue
                    if self.identity(later) == target:
                        return (SUCCEEDED, date)
                    seen.add(later)
                    following.append((later, date))
            frontier = following
        return None

    # Pages.

    def page(self, name: str) -> str | None:
        """The identity whose page `name` belongs on, or None if ODS says nothing."""
        node = self.node(name)
        return self.identity(node) if node else None

    def page_name(self, identity: str) -> str:
        kind, code = identity.split(":", 1)
        if kind == "name":
            return strip_code(self.successions[code]["from"])
        record = self.organisations.get(code)
        if kind == "org" and code in self.chosen:
            return strip_code(self.chosen[code])
        if kind == "org" and record:
            # ODS's name where the register uses it too. Where it does not, ODS
            # may simply be out of date ("Velindre NHS Trust" for what the
            # register calls Velindre University NHS Trust), so the register's
            # own name stands. An ICB the register names only by its sub-ICB
            # locations has no name of its own there, and takes ODS's.
            used = sorted(
                (e["name"] for e in self.entries.values() if e["code"] == code and not e.get("as")),
                key=lambda n: (n != n.upper(), n),
            )
            if used and aliases.name_key(record["name"]) not in {aliases.name_key(n) for n in used}:
                return strip_code(used[0])
            return strip_code(record["name"])
        # A CCG's name is gone from ODS if its record lives on as a sub-ICB
        # location, so it comes from the register.
        names = sorted(
            (e["name"] for e in self.entries.values() if e["code"] == code and (e.get("as") == "CCG") == (kind == "ccg")),
            key=lambda n: (n != n.upper(), n),
        )
        return strip_code(names[0]) if names else code

    def names_for(self, identity: str) -> list[dict]:
        return [e for e in self.entries.values() if self.page(e["name"]) == identity]

    def sub_icb_locations(self, identity: str) -> list[dict]:
        """`[{code, former}]`: the sub-ICB locations the register names under an ICB, with the CCG each continued."""
        kind, icb = identity.split(":", 1)
        rows: dict[str, set[str]] = {}
        for entry in self.entries.values():
            code = entry["code"]
            record = self.organisations.get(code, {})
            # ODS places councils and trusts "in the geography of" an ICB too;
            # only a sub-ICB location is part of it.
            if code == icb or record.get("icb") != icb or ods.SUB_ICB_LOCATION not in _roles(record):
                continue
            rows.setdefault(code, set())
            if entry.get("as") == "CCG":
                rows[code].add(strip_code(entry["name"]))
        return [
            {"code": code, "former": sorted(former, key=lambda n: (n != n.upper(), n))[:1]}
            for code, former in sorted(rows.items())
        ]

    def predecessors(self, identity: str) -> list[dict]:
        """`[{identity, name, date}]`: organisations named in the register that passed to this one."""
        found: dict[str, str] = {}
        names = [e["name"] for e in self.entries.values()] + [s["from"] for s in self.successions.values()]
        for name in names:
            node = self.node(name)
            own = self.identity(node)
            if own == identity:
                continue
            for later, date in self.successors(node):
                if self.identity(later) == identity:
                    found[own] = date
        return [
            {"identity": key, "name": self.page_name(key), "date": date, "reviewed": key.startswith("name:")}
            for key, date in sorted(found.items(), key=lambda kv: self.page_name(kv[0]).casefold())
        ]

    def successors_of(self, identity: str) -> list[dict]:
        """`[{identity, name, date}]`: what this organisation passed to, per ODS."""
        found: dict[str, str] = {}
        for later, date in self.successors(identity):
            own = self.identity(later)
            if own != identity:
                found[own] = date
        reviewed = identity.startswith("name:")
        return [
            {"identity": key, "name": self.page_name(key), "date": date, "reviewed": reviewed}
            for key, date in sorted(found.items())
        ]


def load(
    codes_path: Path | None = None, snapshot_path: Path | None = None, alias_map: dict[str, str] | None = None
) -> Lineage:
    """The lineage, under `alias_map` or, when not given, the organisation aliases on file."""
    return Lineage(
        load_codes(codes_path),
        ods.load_snapshot(snapshot_path)["organisations"],
        aliases.load_map(aliases.ALIASES_PATH) if alias_map is None else alias_map,
        load_successions(),
    )

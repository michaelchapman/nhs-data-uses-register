"""The reviewed files a build reads: which names are one organisation or one
dataset, what NHS organisations became, and which records are left out.

Every part of a build consults them — grouping pages, comparing versions,
naming the changes — and each used to read them for itself, 28 times over.
`Rules.load()` reads them once, and a build passes the one answer down, so
every part of the site is judged by the same files.

A function that takes `rules` still works without it, loading them itself:
the review tools and the tests call such functions one at a time.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import aliases, exclusions, lineage


@dataclass(frozen=True)
class Rules:
    # `{normalised variant: canonical name}`, looked up with `aliases.resolve`.
    organisation_aliases: dict[str, str]
    dataset_aliases: dict[str, str]
    # The groups those maps come from, for what a reviewer wrote as canonical.
    organisation_groups: list[dict]
    dataset_groups: list[dict]
    lineage: lineage.Lineage
    # Base references left out of the site, upper-cased.
    excluded: frozenset[str]

    @classmethod
    def load(cls) -> Rules:
        organisation_groups = aliases.load_groups(aliases.ALIASES_PATH)
        dataset_groups = aliases.load_groups(aliases.DATASET_ALIASES_PATH)
        organisation_aliases = aliases.map_of(organisation_groups)
        return cls(
            organisation_aliases=organisation_aliases,
            dataset_aliases=aliases.map_of(dataset_groups),
            organisation_groups=organisation_groups,
            dataset_groups=dataset_groups,
            lineage=lineage.load(alias_map=organisation_aliases),
            excluded=exclusions.bases(),
        )

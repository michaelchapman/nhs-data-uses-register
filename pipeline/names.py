"""How an organisation's name is shown on the site.

The register writes most organisations in capitals — 463 of the 611 names on
the site — and a table of them reads as shouting. `display_name` gives those
ordinary capitalisation for display only. The register's own spelling is still
what is stored, searched, exported to CSV and listed under "recorded in the
register as", so nothing here changes which organisation a name belongs to.

A name that already contains a lower-case letter is returned untouched: it was
written by someone who chose its capitals, and guessing again would only break
"NHS Bristol, North Somerset and South Gloucestershire ICB - 15C".

This is a heuristic, and it will get some names wrong. The failure to expect is
an acronym it doesn't know, which comes out as a word ("Ims Health"). Add it to
ACRONYMS. Names are never silently lost or merged by getting this wrong, and
`tests/test_names.py` runs it over the real register to catch a crash.
"""

from __future__ import annotations

import re

# Written in capitals whichever way the register spells the surrounding name.
ACRONYMS = frozenset(
    """
    NHS ICB CCG CSU UK UCL LSE ONS HQIP NWIS IQVIA NICE NIHR MHRA PHE RCOG RCPCH
    CHKS CJD CPRD ICNARC NHSBT PHIN MSD IQ RM PLC LLP LLC DHSC GP GPS GMC NCL
    NEL SEL SWL SHA PCT NDRS HES DARS AB HSJ LHB CIC NEC MAC IOM IARC MOD CQC BCP RAND
    """.split()
)

# Words with a capitalisation of their own.
OVERRIDES = {
    "GMBH": "GmbH",
    "RX": "Rx",
    "ASTRAZENECA": "AstraZeneca",
    "GLAXOSMITHKLINE": "GlaxoSmithKline",
    "PRESCQIPP": "PrescQIPP",
}

# Lower-case unless first: "Kingston upon Hull", "Stoke-on-Trent".
SMALL_WORDS = frozenset("and of the for in on at to upon with by as de le la".split())

# A word, possibly wrapped in brackets or trailing punctuation.
_TOKEN = re.compile(r"^(?P<lead>[^A-Za-z0-9&]*)(?P<core>.*?)(?P<trail>[^A-Za-z0-9&]*)$", re.DOTALL)
# Hyphens and slashes join parts of one token that are cased separately.
_JOINERS = re.compile(r"([-/])")
_MC = re.compile(r"^MC([A-Z]{3,})$")


def _word(core: str, first: bool) -> str:
    if not core or not any(c.isalpha() for c in core):
        return core
    if core in OVERRIDES:
        return OVERRIDES[core]
    # A code ("15C"), a lone initial ("T/A", "VITAMIN A"), an acronym, or a
    # pair joined by an ampersand ("R&D"): none of them is a word to re-case.
    if core in ACRONYMS or len(core) == 1 or "&" in core or any(c.isdigit() for c in core):
        return core
    lowered = core.lower()
    if not first and lowered in SMALL_WORDS:
        return lowered
    if "'" in core or "’" in core:
        # O'BRIEN -> O'Brien, but ST GEORGE'S -> St George's.
        parts = re.split(r"(['’])", core)
        out = []
        for i, part in enumerate(parts):
            if part in ("'", "’"):
                out.append(part)
            elif i and len(part) == 1 and part.upper() == "S":
                out.append("s")
            else:
                out.append(part.capitalize())
        return "".join(out)
    mc = _MC.match(core)
    if mc:
        return "Mc" + mc.group(1).capitalize()
    return core.capitalize()


def _token(token: str, first: bool) -> str:
    match = _TOKEN.match(token)
    lead, core, trail = match["lead"], match["core"], match["trail"]
    # The first word inside a bracket starts a phrase of its own.
    first = first or any(c in lead for c in "([")
    pieces = _JOINERS.split(core)
    cased = [
        piece if _JOINERS.fullmatch(piece) else _word(piece, first and i == 0)
        for i, piece in enumerate(pieces)
    ]
    return lead + "".join(cased) + trail


def display_name(name: str) -> str:
    """`name` in ordinary capitalisation if the register wrote it in capitals."""
    if not name or name != name.upper() or not any(c.isalpha() for c in name):
        return name
    tokens = name.split(" ")
    # The word after a spaced dash starts a new phrase: "Saving Faces - The Facial…".
    return " ".join(
        _token(token, first=i == 0 or tokens[i - 1] in ("-", "–", "—"))
        for i, token in enumerate(tokens)
    )

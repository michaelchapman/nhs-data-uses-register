"""Classify agreements for the Confidential data and Patient opt-outs filters.

Two questions a visitor asks of the whole register, which the agreement pages
answer only one agreement at a time:

- **Can confidential patient information flow under this agreement, and on
  what basis?** From the register's "Common Law Duty of Confidentiality"
  column, which gives each dataset on an agreement one of eight fixed values.
  Each names one or more of: section 251 support, consent, a statutory
  exemption, and data that is not confidential. An agreement is read from its
  latest version, as the rest of the agreements list is, and matches a basis if
  any of its datasets carries it. So one agreement can match several.

- **Were patient opt-outs applied to the files released?** From the release
  rows, which answer Yes or No for each file, counted across every version of
  the agreement. The four states are exclusive: every file, some files, no
  file, or no files recorded at all.

A value neither list knows stops the build rather than being filed somewhere
that looks deliberate. A new edition can reword the register's values; when it
does, add the wording here, having read what it means.
"""

from __future__ import annotations

# Every value the Common Law Duty of Confidentiality column has held, July
# 2021 to September 2026, and the bases each one names. "none" is a flow of
# data that is not confidential.
CONFIDENTIALITY = {
    "Does not include the flow of confidential data": ("none",),
    "Section 251 NHS Act 2006": ("s251",),
    "Consent (Reasonable Expectation)": ("consent",),
    "Statutory exemption to flow confidential data without consent": ("exemption",),
    "Mixture of confidential data flow(s) with support under section 251 NHS Act 2006 "
    "and non-confidential data flow(s)": ("s251", "none"),
    "Mixture of confidential data flow(s) with consent and flow(s) with support under "
    "section 251 NHS Act 2006": ("consent", "s251"),
    "Mixture of confidential data flow(s) with consent and non-confidential data flow(s)": ("consent", "none"),
}

# The Confidential data filter's options, in the order it lists them. The first
# three match an agreement with at least one dataset on that basis; "none" only
# one where every dataset says it has no confidential data.
CONFIDENTIALITY_OPTIONS = (
    ("s251", "Section 251 support"),
    ("consent", "Consent"),
    ("exemption", "Statutory exemption"),
    ("none", "No confidential data"),
    ("not-recorded", "Not recorded"),
)

# The Patient opt-outs filter's options. Exactly one fits each agreement.
OPT_OUT_OPTIONS = (
    ("all", "Applied to every file released"),
    ("some", "Applied to some files released"),
    ("none", "Not applied to any file released"),
    ("no-files", "No files recorded"),
)

OPT_OUT_ANSWERS = ("Yes", "No")


class UnknownValue(SystemExit):
    """A register value this module has no reading for."""


def confidentiality(datasets: list[dict]) -> list[str]:
    """The Confidential data filter's values for one version's datasets.

    `s251`, `consent` and `exemption` for each basis any dataset names;
    `not-recorded` if any dataset leaves the column blank, or there are no
    datasets; and `none` only when neither applies, so that "No confidential
    data" means none on any dataset rather than none on one of them.
    """
    bases: set[str] = set()
    unrecorded = not datasets
    for dataset in datasets:
        value = dataset.get("confidentiality", "")
        if not value:
            unrecorded = True
            continue
        if value not in CONFIDENTIALITY:
            raise UnknownValue(
                f'privacy: unknown Common Law Duty of Confidentiality value "{value}" '
                f'on dataset "{dataset.get("name", "")}". Add it to CONFIDENTIALITY in pipeline/privacy.py.'
            )
        bases.update(CONFIDENTIALITY[value])
    confidential = sorted(bases - {"none"})
    if unrecorded:
        return confidential + ["not-recorded"]
    return confidential or ["none"]


def opt_outs(versions: list[dict]) -> dict:
    """`{state, applied, files}` from the files released under every version.

    `applied` is how many of `files` had opt-outs applied; `state` is one of
    the `OPT_OUT_OPTIONS` keys.
    """
    counts = {answer: 0 for answer in OPT_OUT_ANSWERS}
    for version in versions:
        for release in version.get("releases", []):
            for answer, files in release.get("opt_out_files", {}).items():
                if answer not in counts:
                    raise UnknownValue(
                        f'privacy: unknown Patient Opt-Outs Applied value "{answer}" on '
                        f'{files} file(s) released under {version.get("reference", "")}. '
                        "Add it to OPT_OUT_ANSWERS in pipeline/privacy.py."
                    )
                counts[answer] += files
    applied, files = counts["Yes"], counts["Yes"] + counts["No"]
    if not files:
        state = "no-files"
    elif applied == files:
        state = "all"
    elif applied:
        state = "some"
    else:
        state = "none"
    return {"state": state, "applied": applied, "files": files}


def assign(agreements: list[dict]) -> None:
    """Set `confidentiality` and `opt_outs` on each agreement."""
    for agreement in agreements:
        agreement["confidentiality"] = confidentiality(agreement["versions"][-1]["datasets"])
        agreement["opt_outs"] = opt_outs(agreement["versions"])


def counts(agreements: list[dict]) -> dict:
    """`{"confidentiality": [(key, label, n)], "opt_outs": [...]}` for the filter labels.

    Options no agreement matches are left out, as the sector filter leaves out
    empty sectors.
    """
    by_basis = {key: 0 for key, _ in CONFIDENTIALITY_OPTIONS}
    by_state = {key: 0 for key, _ in OPT_OUT_OPTIONS}
    for agreement in agreements:
        for key in agreement["confidentiality"]:
            by_basis[key] += 1
        by_state[agreement["opt_outs"]["state"]] += 1
    return {
        "confidentiality": [(k, label, by_basis[k]) for k, label in CONFIDENTIALITY_OPTIONS if by_basis[k]],
        "opt_outs": [(k, label, by_state[k]) for k, label in OPT_OUT_OPTIONS if by_state[k]],
    }

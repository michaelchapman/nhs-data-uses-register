# Plan: show what actually changed between versions of an agreement

Status: **proposed.** Nothing here is implemented yet.

The site already answers *which* agreements changed this month
(`/changes/`, and one page per edition pair). It cannot answer *what*
changed in any of them. This document proposes closing that gap, in four
increments that can ship independently.

## 1. What we can say today, and what we can't

`snapshot._fingerprint` reduces each agreement version to a single 16-hex
digest over 13 text fields plus the sorted dataset names. `snapshot.diff`
compares two editions' digests and buckets every version into added,
amended or removed.

That is enough for "this changed" and structurally incapable of anything
more. A digest is one bit of information: same or different. It cannot
say which field moved, by how much, or in which direction.

The gap shows up twice:

- **Between versions of an agreement.** The agreement page lists
  `v1.0`, `v2.0`, `v2.1` as collapsible blocks with each one's full text
  repeated. A reader comparing a renewal against the version it replaced
  has to read two 3,000-word prose blocks side by side and spot the
  difference themselves. Nothing on the page marks the delta, even though
  both texts are right there in the same extract.
- **Within a version, between editions.** An agreement modified in place
  keeps its reference number, so it never appears as a new version at
  all — it lands in the "amended" bucket with no further detail.

## 2. Evidence: in-place amendment is the normal case, not an edge case

Fingerprint comparison across the 19 committed editions:

| Edition (vs previous) | Added | Amended in place | Removed |
| --- | ---: | ---: | ---: |
| April 2025 | 58 | 2 | 0 |
| May 2025 | 53 | 0 | 0 |
| June 2025 | 59 | 3 | 0 |
| July 2025 | 52 | 41 | 0 |
| August 2025 | 45 | 1 | 0 |
| September 2025 | 39 | 0 | 0 |
| October 2025 | 51 | 52 | 0 |
| November 2025 | 47 | 16 | 0 |
| December 2025 | 37 | 2 | 0 |
| January 2026 | 32 | 0 | 0 |
| February 2026 | 55 | 72 | 0 |
| March 2026 | 25 | 122 | 0 |
| April 2026 | 47 | 1 | 0 |
| May 2026 | 53 | 73 | 0 |
| June 2026 | 44 | 73 | 0 |
| July 2026 | 59 | 15 | 0 |
| August 2026 | 31 | 20 | 0 |
| September 2026 | 36 | 1 | 0 |

Three things stand out.

**Nothing is ever removed.** In 18 edition pairs, not one agreement
version has left the register. The "No longer listed" section of
`/changes/` has been empty every month of the archive. It should stay
(a withdrawal would be the single most newsworthy event on the site) but
it should not be given equal visual weight to a bucket with 122 entries.

**Amendment volume is spiky and unexplained.** March 2026 amended 122
versions — five times that month's new agreements. February, May and
June 2026 amended 70+. July and October 2025 amended 41 and 52. Those
spikes are exactly what a reader would want explained, and the site
cannot distinguish "NHS England restated the benefits text on 122
agreements after a template change" from "122 agreements had their end
dates extended". Those are very different stories and today they render
identically.

**The user-reported case is real and is this month's only amendment.**
`DARS-NIC-788663-G4F2D-v0.2` (Office for National Statistics, *Health
and Growth Accelerator (HGA) Programme National Evaluation*) is present
in both August and September 2026 under the same reference, with
different digests:

```
august2026     8350b60a84ce9386
september2026  cda7c782d1f38cc4
```

It is the sole amendment in the September edition. The site can say so.
It cannot say what was edited, and neither can anyone reading it, because
the August full extract has been pruned (`editions.DEFAULT_KEEP = 1`) and
the August workbook was never committed (`data/raw/` is gitignored). The
information needed to answer the obvious follow-up question no longer
exists anywhere in this repository. That is the strongest argument for
recording amendment detail at ingest time rather than trying to
reconstruct it later.

## 3. Blind spots in what counts as a change

Before adding detail, the definition of "changed" needs two fixes.

**Fields that should be fingerprinted and aren't.** `FINGERPRINTED`
omits `controllers` entirely. A change of data controller — arguably the
most consequential single edit an agreement can receive, and the thing a
journalist or a patient would most want flagged — currently produces no
change at all. Dataset *attributes* are also invisible: `_fingerprint`
hashes `sorted(d["name"] for d in version["datasets"])`, so a dataset
being re-classified from non-sensitive to sensitive, or its legal basis
changing from consent to Section 251 support, registers as no change.

Recommended additions: `controllers` (sorted), and per-dataset
`(name, legal_basis, sensitivity, type_of_data, confidentiality)` tuples
rather than bare names. `frequency` is borderline — it is often restated
in different words for the same meaning; include it, and let the
normalisation below absorb the noise.

`releases` and `files_released` should stay out. They change every month
by design; folding them in would mark most of the register as amended
every edition and drown the signal.

**Normalisation.** `_fingerprint` hashes `clean()`ed text, which collapses
`\r\n` and runs of blank lines but preserves trailing spaces, double
spaces, non-breaking spaces, smart-vs-straight quotes and case. A fair
share of the 122-amendment spike is plausibly that kind of churn. For
hashing only — never for display — normalise: `NFKC`, collapse all
whitespace runs to a single space, strip, and fold the register's `~`
bullet markers to a consistent form. Keep the displayed text exactly as
published.

This changes every digest, so it is a one-off reset: either re-ingest the
archive (18 manual downloads) or accept that the edition where it lands
shows an artificial mass amendment. Do it in the same change as the new
fields, once, and note it on the page.

## 4. Recommendations

### R1 — Per-agreement edition timeline (no new data required)

Ship this first. It needs no format change, no re-ingest and no new
dependency: every fingerprint file is already committed, and loading all
19 and indexing them by base reference takes 0.26s.

On each agreement page, add a short "Register history" list:

> First listed in the **March 2025** edition.
> `v0.2` amended in the **September 2026** edition.
> `v2.0` first appeared in the **February 2026** edition.

This alone answers "has this agreement been quietly edited, and when?" —
today unanswerable from the site even though the data is sitting in git.
It also gives the in-place amendments a permanent home: `/changes/` is
a monthly snapshot nobody revisits, whereas the agreement page is the
URL people cite.

Implementation: build an index of `base_reference -> [(edition, reference,
hash)]` once in `run.main`, pass it into `build.build`, and hand each
agreement its own slice. Cost is a few hundred lines of extra HTML per
page and no measurable build time.

### R2 — Per-field digests, so the site can name the fields that moved

Replace the single `hash` per version in the snapshot with a map of
per-field digests:

```python
def _fingerprints(version: dict) -> dict[str, str]:
    fields = {key: _normalise(version.get(key, "")) for key in FINGERPRINTED}
    fields["controllers"] = sorted(map(_normalise, version["controllers"]))
    fields["datasets"] = sorted(
        [d["name"], d["legal_basis"], d["sensitivity"], d["type_of_data"]]
        for d in version["datasets"]
    )
    return {k: _digest(v) for k, v in fields.items()}
```

The combined digest stays derivable (`_digest` of the sorted per-field
digests), so `diff` keeps working unchanged and no field is duplicated on
disk. `diff` then reports `changed_fields` alongside each amended entry,
and `/changes/` can show:

> **Health and Growth Accelerator (HGA) Programme National Evaluation** —
> ONS — `DARS-NIC-788663-G4F2D-v0.2` — *expected measurable benefits,
> end date*

Measured cost: per-field digests for 5,613 versions are 1.8 MB raw and
**202 KB gzipped**, against 210 KB for the whole current snapshot. So
roughly 2x per edition, ~4 MB across the full archive. That is an
acceptable price for turning "something changed" into "the end date
changed", and it scales: every future edition carries it for free.

It also makes the spikes readable. If March 2026's 122 amendments were
all `yielded_benefits`, the page can say so in one line instead of
listing 122 rows that look alike.

### R3 — An amendment log, for genuine redline

Field names are enough for a change summary. A redline needs the old
text, and after pruning the old text is gone. So write it at ingest time,
when both editions are briefly in hand, into a small permanent file:

```
data/amendments/<register>/<edition>.json.gz
```

One entry per amended version, one record per changed field, holding the
previous value and the new one. Only changed fields, only amended
versions — so the file is proportional to the month's churn, not to the
register:

| | Amendments | Rough raw size | Gzipped |
| --- | ---: | ---: | ---: |
| Typical month (15 amendments, ~2 fields each) | 15 | ~90 KB | ~25 KB |
| Worst observed (March 2026) | 122 | ~2.9 MB | ~600 KB |

Even the worst month is smaller than one edition fingerprint. Compare
that with the alternative of raising `editions.DEFAULT_KEEP` to 2, which
costs **32 MB of git history per edition** and still only lets you diff
one month back.

Mechanics: `ingest` already has the new extract; it needs the previous
edition's extract to compare against. Two workable routes —

- **Preferred:** compute the amendment log inside `ingest`, *before*
  `prune_extracts` runs, whenever the previous edition still has a full
  extract. Keep `DEFAULT_KEEP = 1` and simply order the operations so the
  outgoing extract is read before it is deleted. This works for every
  future month with no storage increase at all.
- **Fallback:** if the previous extract is already gone (a backfill, a
  skipped month), write no log for that pair and record `"comparable":
  false`. The per-field digests from R2 still give the field names; only
  the text is missing. Degrade to a summary rather than blocking.

### R4 — Rendering: summary by default, redline on request

Three levels, in increasing cost to the reader:

1. **Field summary** (from R2) — on `/changes/` and in the agreement's
   register history. Always shown.
2. **Before/after pairs** for short, scalar fields (dates, Yes/No flags,
   controller lists, dataset membership). A two-column table reads better
   than a redline for `2027-03-31 → 2028-03-31`, and much better for
   "dataset added: *Civil Registration - Deaths*".
3. **Word-level redline** for the five long prose fields (`objective`,
   `activities`, `expected_output`, `expected_benefits`,
   `yielded_benefits`). These are where a redline earns its keep:
   3,400-character blocks where a single sentence has been rewritten.

For (3), `difflib.SequenceMatcher` over word tokens is in the standard
library — no new dependency, consistent with the project's two-package
`requirements.txt`. Render as semantic `<ins>`/`<del>` inside a
`<details>` block, collapsed by default, with unchanged paragraphs
elided behind a "show unchanged text" summary. Colour must not be the
only signal: keep the strikethrough on `<del>`, keep underline on
`<ins>`, and add `aria-label`s, in keeping with the site's existing
no-JavaScript-required posture. Every diff must be in the HTML; none of
it should depend on script.

The same rendering serves **version-to-version diffs**, which need no new
stored data at all — consecutive versions of one agreement are both in
the current extract. On the agreement page, each version block after the
first gets a "What changed from `v1.0`" `<details>`. This is arguably the
highest-value item in the whole plan relative to its cost, and it can
ship alongside R1 without waiting for R2 or R3.

### R5 — Give in-place amendments their own vocabulary

The register's own model has no concept of an unversioned edit, so the
site has to supply one. Concretely:

- Split the agreement page's current "Version history" into **Version
  history** (new reference numbers) and **Amendments** (same reference,
  changed content), so `DARS-NIC-788663-G4F2D-v0.2` reads as one version
  amended once rather than as an unexplained tag.
- Reword the `/changes/` "Amended" section, which currently says
  "changed in place" only in passing. Lead with it: these are edits NHS
  England made to an existing agreement record without issuing a new
  version, and there is no official changelog for them anywhere. That is
  the site's genuinely novel contribution and it is currently buried
  under "Added".
- Keep the existing `tag-amended` badge but make it a link to the diff.
- Say plainly what an amendment is *not*: the register is a periodic
  publication, so an edit appearing in the September edition means only
  that it was made at some point between the two publication dates.

### R6 — Machine-readable change outputs

The site already publishes flat CSVs. Add, per edition:

- `downloads/changes-<edition>.csv` — one row per changed version:
  `edition, previous_edition, reference, base_reference, organisation,
  change_type, changed_fields, url`.
- `changes/<edition>/changes.json` — the same plus old/new values where
  R3 has them.

This is cheap (both are already-computed structures) and it makes the
month-on-month history citable by other people's tooling, which is the
stated point of the project.

## 5. Suggested sequencing

| Step | Needs | Blocked on a re-ingest? | Value |
| --- | --- | --- | --- |
| R1 register history + R4(3) version-to-version diffs | committed fingerprints and the current extract, both already present | No | High — ships now |
| R5 vocabulary and page structure | nothing | No | High |
| R2 per-field digests + R3 normalisation and new fields | snapshot format change | Only to backfill history; forward-looking from the next edition | High |
| R3 amendment log | reordering `ingest` before `prune_extracts` | No, for future editions | High |
| R6 exports | R2 | No | Medium |

Steps 1 and 2 are pure rendering over data already in git, so they should
not wait for the format work. R2 and R3 change what is captured and
therefore only help from the edition they land in — which is an argument
for landing them before the October 2026 workbook is ingested, not after.

## 6. What this cannot recover

Field-level detail for the 18 historical edition pairs cannot be
reconstructed from what is committed: the snapshots hold only digests and
the workbooks were never kept. Backfilling it means re-downloading 18
workbooks by hand from NHS England's archive and re-running `ingest` in
publication order with the amendment log enabled — roughly an afternoon,
and worth doing once if the historical amendments (the 122 in March 2026
especially) are interesting enough to justify it. If they are not, the
per-field digests and the amendment log simply start from the edition
they ship in, and the archive keeps the coarse added/amended/removed view
it has now.
